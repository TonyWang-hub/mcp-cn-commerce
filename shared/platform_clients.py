"""Credential-explicit, read-only platform clients for application integrations.

Token refresh and tenant authorization belong to the host application. No MCP
server module is imported here; adapters accept one fixed credential snapshot.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from functools import wraps
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
        "get_order_list": Operation("jingdong.pop.order.search", "documented"),
        "get_order_detail": Operation("jingdong.pop.order.get", "documented"),
        "get_shop_info": Operation("jingdong.vender.shop.query", "documented"),
        "get_aftersale_list": Operation("jingdong.asc.serviceAndRefund.view", "documented"),
        "get_aftersale_refund_detail": Operation("jingdong.b2c.shop.aftersales.refund.get", "documented"),
        **{
            name: Operation(
                "",
                "partial",
                supported=False,
                reason="JD POP after-sale service is not a verified completed-refund contract; see docs/jd-contract.md",
            )
            for name in ("get_refund_list", "get_refund_detail")
        },
    },
    "pinduoduo": {
        name: Operation(
            endpoint,
            "partial",
            supported=False,
            reason="PDD read schema unavailable (official document HTTP 403); see docs/pinduoduo-contract.md",
        )
        for name, endpoint in {
            "get_order_list": "pdd.order.list.get",
            "get_increment_orders": "pdd.order.number.list.increment.get",
            "get_order_detail": "pdd.order.information.get",
            "get_refund_list": "pdd.refund.list.increment.get",
            "get_refund_detail": "pdd.refund.information.get",
            "get_shop_info": "pdd.mall.info.get",
        }.items()
    },
    "kuaishou": {
        "get_order_list": Operation("open.order.cursor.list", "documented"),
        "get_order_detail": Operation("open.order.detail", "documented"),
        "get_refund_list": Operation("open.seller.order.refund.pcursor.list", "documented"),
        "get_refund_detail": Operation("open.seller.order.refund.detail", "documented"),
        "get_shop_info": Operation("open.shop.info.get", "documented"),
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
        "get_order_detail": Operation("/channels/ec/order/get", "documented"),
        "get_refund_list": Operation("/channels/ec/aftersale/getaftersalelist", "documented"),
        "get_refund_detail": Operation("/channels/ec/aftersale/getaftersaleorder", "documented"),
        "get_shop_info": Operation("/channels/ec/basics/info/get", "documented"),
    },
    "oceanengine": {
        "get_advertiser_info": Operation("2/advertiser/info/", "documented"),
        "get_account_balance": Operation("2/advertiser/fund/get/", "documented"),
        "get_campaign_report": Operation(
            "2/report/advertiser/get/",
            "partial",
            supported=False,
            reason="OceanEngine report contract migration pending; see docs/remaining-platform-contracts.md",
        ),
        "get_ad_detail_report": Operation(
            "2/report/ad/get/",
            "partial",
            supported=False,
            reason="OceanEngine report contract migration pending; see docs/remaining-platform-contracts.md",
        ),
        "get_qianchuan_report": Operation(
            "2/qianchuan/report/ad/get/",
            "partial",
            supported=False,
            reason="OceanEngine report contract migration pending; see docs/remaining-platform-contracts.md",
        ),
        **{
            name: Operation("", supported=False, reason="Advertising API is not a merchant order/shop API")
            for name in ("get_order_list", "get_order_detail", "get_refund_list", "get_refund_detail", "get_shop_info")
        },
    },
}


@dataclass(frozen=True)
class MCPToolCapability:
    """Discovery and guard metadata for one registered platform business tool."""

    operation: Operation
    enforce_before_call: bool


_MCP_CAPABILITY_OVERRIDES = {
    "jd": {
        name: Operation(
            "",
            "partial",
            supported=False,
            reason="JD POP after-sale service is not a verified completed-refund contract; see docs/jd-contract.md",
        )
        for name in ("get_after_sale_list", "get_after_sale_detail")
    },
    "xiaohongshu": {
        name: Operation(
            "",
            "unverified",
            supported=False,
            reason="No verified official Xiaohongshu API mapping; no request is allowed",
        )
        for name in ("get_review_list", "list_promotions", "list_coupons")
    },
}

# These tools already preserve a public, pre-network unsupported response or
# exception contract. Discovery still comes from this catalogue, while their
# existing implementation remains responsible for the exact public error type.
_MCP_DELEGATED_UNSUPPORTED = frozenset(
    {
        ("doudian", "get_shop_info"),
        ("jd", "get_after_sale_list"),
        ("jd", "get_after_sale_detail"),
        ("pinduoduo", "get_order_list"),
        ("pinduoduo", "get_order_detail"),
        ("pinduoduo", "get_refund_list"),
        ("pinduoduo", "get_refund_detail"),
        ("pinduoduo", "get_shop_info"),
        ("xiaohongshu", "get_review_list"),
        ("xiaohongshu", "get_shop_info"),
        ("xiaohongshu", "list_promotions"),
        ("xiaohongshu", "list_coupons"),
    }
)

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


def require_supported_operation(platform: str, operation: str) -> Operation:
    """Return supported SDK metadata or reject before client/network access."""
    operations = operation_catalog(platform)
    if not isinstance(operation, str) or operation not in operations:
        raise ValueError(f"Unsupported read-only operation for {platform}")
    metadata = operations[operation]
    if not metadata.supported:
        raise ValueError(f"Unsupported read-only operation: {metadata.reason}")
    return metadata


def mcp_tool_capability(platform: str, tool_name: str) -> MCPToolCapability:
    """Classify one MCP business tool without promoting legacy names to SDK contracts."""
    operations = operation_catalog(platform)
    overrides = _MCP_CAPABILITY_OVERRIDES.get(platform, {})
    if tool_name in overrides:
        operation = overrides[tool_name]
    elif tool_name in operations:
        operation = operations[tool_name]
    else:
        operation = Operation(
            "",
            "unverified",
            supported=True,
            reason=(
                "Historical MCP transport compatibility only; official contract verification "
                "and live merchant acceptance are incomplete"
            ),
        )
    return MCPToolCapability(
        operation=operation,
        enforce_before_call=not operation.supported and (platform, tool_name) not in _MCP_DELEGATED_UNSUPPORTED,
    )


def _capability_description(capability: MCPToolCapability, original: str | None) -> str:
    operation = capability.operation
    header = (
        "[Capability: "
        f"contract_status={operation.contract_status}; "
        f"supported={str(operation.supported).lower()}; "
        f"live_verified={str(operation.live_verified).lower()}]"
    )
    if operation.reason:
        boundary = operation.reason.rstrip(".") + "."
    elif operation.contract_status == "documented":
        boundary = "Official contract is documented; live merchant acceptance is incomplete."
    elif operation.contract_status == "transport_only":
        boundary = (
            "Transport compatibility is retained; response-contract and live merchant verification are incomplete."
        )
    else:
        boundary = "Official contract and live merchant verification are incomplete."
    return f"{header}\n{boundary}" + (f"\n\n{original.strip()}" if original else "")


def mcp_capability_tool(
    register_tool: Callable[..., Callable[[Callable[..., Any]], Callable[..., Any]]],
    platform: str,
    *,
    unavailable_error: type[Exception] = ValueError,
) -> Callable[..., Callable[[Callable[..., Any]], Callable[..., Any]]]:
    """Wrap an MCP ``tool`` registrar with capability metadata and fail-closed guards.

    The helper deliberately accepts a registrar rather than importing MCP, so
    SDK/catalogue code cannot form an import cycle with server modules.
    """
    operation_catalog(platform)  # validate once during server construction

    def tool(*args: Any, **kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        register = register_tool(*args, **kwargs)

        def decorate(function: Callable[..., Any]) -> Callable[..., Any]:
            capability = mcp_tool_capability(platform, function.__name__)

            @wraps(function)
            async def guarded(*function_args: Any, **function_kwargs: Any) -> Any:
                if capability.enforce_before_call:
                    raise unavailable_error(f"Unsupported read-only operation: {capability.operation.reason}")
                return await function(*function_args, **function_kwargs)

            guarded.__doc__ = _capability_description(capability, function.__doc__)
            guarded.__mcp_capability__ = capability  # type: ignore[attr-defined]
            return register(guarded)

        return decorate

    return tool


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
        metadata = require_supported_operation(self.platform, operation)
        if not isinstance(params, dict) or any(not isinstance(key, str) for key in params):
            raise ValueError("Business parameters must be a dictionary with string keys")
        for key in params:
            normalized = key.replace("_", "").replace("-", "").lower()
            if normalized == "type" and self.platform in {"taobao", "youzan", "kuaishou"}:
                continue  # These platforms define type as a business filter, not a route.
            if normalized in _PROTOCOL_FIELDS:
                raise ValueError(f"Business parameter {key!r} cannot override platform protocol fields")
        business = deepcopy(params)
        endpoint = metadata.endpoint
        if self.platform == "doudian":
            result = await self._adapter.request(endpoint, business)
        elif self.platform == "xiaohongshu":
            result = await self._adapter._call("GET", endpoint, business)
        elif self.platform == "weixin_store":
            if operation == "get_shop_info":
                result = await self._adapter._request("GET", endpoint, params=business)
            else:
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
