"""Credential-explicit, read-only platform clients for application integrations.

Token refresh and tenant authorization belong to the host application. No MCP
server module is imported here; adapters accept one fixed credential snapshot.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from importlib import import_module
from types import MappingProxyType
from typing import Any

import httpx

from shared.cn_commerce_base import CommerceMCPBase, ConfigurableRateLimiter


@dataclass(frozen=True)
class Operation:
    """Available adapter mapping, independently of live merchant acceptance."""

    endpoint: str
    contract_status: str = "unverified"
    live_verified: bool = False
    supported: bool = True
    reason: str = ""


_OPERATIONS = {
    "youzan": {
        "get_order_list": Operation("youzan.trades.sold.get/4.0.4", "documented"),
        "get_order_detail": Operation("youzan.trade.get/4.0.2", "documented"),
        "get_refund_list": Operation("youzan.trade.refund.search/3.0.1", "documented"),
        "get_refund_detail": Operation("youzan.trade.refund.get/3.0.1", "documented"),
        "get_shop_info": Operation("youzan.shop.get/3.0.0", "documented"),
    },
    "doudian": {
        "get_order_list": Operation("order/searchList", "documented"),
        "get_order_detail": Operation("order/orderDetail", "documented"),
        "get_refund_list": Operation("afterSale/List", "documented"),
        "get_shop_info": Operation("", supported=False, reason="No verified general Doudian shop-info API"),
        "get_refund_detail": Operation("afterSale/Detail", "documented"),
    },
    "taobao": {
        "get_order_list": Operation("taobao.trades.sold.get", "documented"),
        "get_increment_orders": Operation("taobao.trades.sold.increment.get", "documented"),
        "get_order_detail": Operation("taobao.trade.fullinfo.get", "documented"),
        "get_refund_list": Operation("taobao.refunds.receive.get", "documented"),
        "get_refund_detail": Operation("taobao.refund.get", "documented"),
        "get_shop_info": Operation("taobao.shop.get", "transport_only"),
    },
    "jd": {
        "get_order_list": Operation("jd.pop.order.search"),
        "get_order_detail": Operation("jd.pop.order.get"),
        "get_refund_list": Operation("jd.pop.afs.search"),
        "get_refund_detail": Operation("jd.pop.afs.get"),
        "get_shop_info": Operation("jd.pop.shop.get"),
    },
    "pinduoduo": {
        "get_order_list": Operation("pdd.order.list.get"),
        "get_order_detail": Operation("pdd.order.information.get"),
        "get_refund_list": Operation("pdd.refund.list.get"),
        "get_refund_detail": Operation("pdd.refund.information.get"),
        "get_shop_info": Operation("pdd.mall.info.get"),
    },
    "kuaishou": {
        "get_order_list": Operation("/open/api/order/list"),
        "get_order_detail": Operation("/open/api/order/detail"),
        "get_refund_list": Operation("/open/api/refund/list"),
        "get_refund_detail": Operation("/open/api/refund/detail"),
        "get_shop_info": Operation("/open/api/shop/info"),
    },
    "xiaohongshu": {
        "get_order_list": Operation("/api/order/list", "documented"),
        "get_order_detail": Operation("/api/order/detail", "documented"),
        "get_refund_list": Operation("/api/refund/list", "documented"),
        "get_refund_detail": Operation("/api/refund/detail", "documented"),
        "get_shop_info": Operation("", supported=False, reason="No verified official shop-info mapping"),
    },
    "weixin_store": {
        "get_order_list": Operation("/channels/ec/order/list/get", "documented"),
        "get_order_detail": Operation("/channels/ec/order/get"),
        "get_refund_list": Operation("/channels/ec/aftersale/getaftersalelist"),
        "get_refund_detail": Operation("/channels/ec/aftersale/getaftersaleorder"),
        "get_shop_info": Operation("/channels/ec/basicinfo/get"),
    },
    "oceanengine": {
        "get_advertiser_info": Operation("2/advertiser/info/", "transport_only"),
        "get_account_balance": Operation("2/advertiser/fund/get/", "transport_only"),
        "get_campaign_report": Operation("2/report/advertiser/get/", "transport_only"),
        "get_ad_detail_report": Operation("2/report/ad/get/", "transport_only"),
        "get_qianchuan_report": Operation("2/qianchuan/report/ad/get/", "transport_only"),
        **{
            name: Operation("", supported=False, reason="Advertising API is not a merchant order/shop API")
            for name in ("get_order_list", "get_order_detail", "get_refund_list", "get_refund_detail", "get_shop_info")
        },
    },
}

_CLASSES = {
    "youzan": "YouzanClient",
    "doudian": "DouDianClient",
    "taobao": "TaobaoMCP",
    "jd": "JDMCP",
    "pinduoduo": "PinduoduoMCP",
    "kuaishou": "KuaishouMCP",
    "xiaohongshu": "XiaohongshuMCP",
    "weixin_store": "WeixinStoreMCP",
    "oceanengine": "OceanEngine",
}
_REQUIRED = {
    "youzan": {"access_token"},
    "doudian": {"app_key", "app_secret", "access_token", "shop_id"},
    "taobao": {"app_key", "app_secret", "access_token"},
    "jd": {"app_key", "app_secret", "access_token"},
    "pinduoduo": {"app_key", "app_secret", "access_token"},
    "kuaishou": {"app_key", "app_secret", "access_token", "sign_secret"},
    "xiaohongshu": {"app_key", "app_secret", "access_token"},
    "weixin_store": {"access_token"},
    "oceanengine": {"access_token"},
}
# Business parameters cannot select a different endpoint or replace credentials.
# Normalize case/separators to also reject accessToken and similar spellings.
_PROTOCOL_FIELDS = frozenset(
    {
        "method",
        "apimethod",
        "apitype",
        "type",
        "path",
        "url",
        "baseurl",
        "endpoint",
        "appkey",
        "appsecret",
        "appid",
        "clientid",
        "clientsecret",
        "accesstoken",
        "refreshtoken",
        "session",
        "sign",
        "signsecret",
        "signmethod",
        "authorization",
        "headers",
        "token",
        "timestamp",
        "format",
        "datatype",
        "version",
        "v",
        "paramjson",
    }
)


def operation_catalog(platform: str) -> Mapping[str, Operation]:
    """Inspect read operations before authentication, without loading any client."""
    if not isinstance(platform, str) or platform not in _OPERATIONS:
        raise ValueError("Unsupported platform")
    return MappingProxyType(dict(_OPERATIONS[platform]))


class PlatformClient:
    """One authorization snapshot with an explicit read-only operation catalogue."""

    def __init__(self, platform: str, adapter: CommerceMCPBase):
        self._platform = platform
        self._adapter = adapter
        self._closed = False
        self._operations = operation_catalog(platform)

    @property
    def platform(self) -> str:
        return self._platform

    @property
    def operations(self) -> Mapping[str, Operation]:
        return self._operations

    async def call(self, operation: str, params: dict[str, Any]) -> dict[str, Any]:
        """Call a named read operation with low-level platform business parameters."""
        if self._closed:
            raise RuntimeError("Platform client is closed")
        if not isinstance(operation, str) or operation not in self._operations:
            raise ValueError(f"Unsupported read-only operation for {self.platform}")
        if not self._operations[operation].supported:
            raise ValueError(f"Unsupported read-only operation: {self._operations[operation].reason}")
        if not isinstance(params, dict) or any(not isinstance(key, str) for key in params):
            raise ValueError("Business parameters must be a dictionary with string keys")
        for key in params:
            normalized = key.replace("_", "").replace("-", "").lower()
            if normalized == "type" and self.platform in {"taobao", "youzan"}:
                continue  # These platforms define type as a business filter, not a route.
            if normalized in _PROTOCOL_FIELDS:
                raise ValueError(f"Business parameter {key!r} cannot override platform protocol fields")
        business = deepcopy(params)
        endpoint = self._operations[operation].endpoint
        if self.platform == "doudian":
            result = await self._adapter.request(endpoint, business)
        elif self.platform == "xiaohongshu":
            result = await self._adapter._call("GET", endpoint, business)
        elif self.platform == "weixin_store":
            result = await self._adapter._request("POST", endpoint, data=business)
        elif self.platform == "oceanengine":
            result = await self._adapter._request("GET", endpoint, params=business)
        else:
            result = await self._adapter._call(endpoint, business)
        if not isinstance(result, dict):
            raise ValueError("Platform response must be a JSON object")
        return result

    async def close(self) -> None:
        """Close owned resources; borrowed HTTP clients remain caller-owned."""
        if not self._closed:
            self._closed = True
            await self._adapter.close()

    async def __aenter__(self) -> PlatformClient:
        if self._closed:
            raise RuntimeError("Platform client is closed")
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        await self.close()


def create_platform_client(
    platform: str,
    credentials: Mapping[str, str],
    *,
    http_client: httpx.AsyncClient | None = None,
    rate_limiter: ConfigurableRateLimiter | None = None,
) -> PlatformClient:
    """Construct an isolated adapter without consulting process credentials.

    ``rate_limiter.acquire(platform, endpoint)`` is awaited per request attempt.
    It may be shared across credential snapshots when an application shares quota.
    """
    if not isinstance(platform, str) or platform not in _CLASSES:
        raise ValueError("Unsupported platform")
    if not isinstance(credentials, Mapping):
        raise ValueError("Credentials must be an explicit mapping")
    snapshot = dict(credentials)
    required = _REQUIRED[platform]
    allowed = required | ({"app_key", "app_secret"} if platform in {"weixin_store", "oceanengine", "youzan"} else set())
    if set(snapshot) - allowed:
        raise ValueError(f"Unsupported credential fields for {platform}")
    if any(not isinstance(snapshot.get(key), str) or not snapshot[key].strip() for key in required):
        raise ValueError(f"Missing or empty explicit credentials for {platform}")
    if any(not isinstance(value, str) for value in snapshot.values()):
        raise ValueError("Credential values must be strings")
    module = import_module(f"servers.{platform}.client")
    adapter_class = getattr(module, _CLASSES[platform])
    if platform == "weixin_store":
        snapshot["token_mode"] = module.STATIC_MODE
    adapter = adapter_class(**snapshot, http_client=http_client, rate_limiter=rate_limiter)
    return PlatformClient(platform, adapter)
