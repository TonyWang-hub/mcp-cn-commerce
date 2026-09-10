"""WeChat Store (微信小店) MCP server — provides read-only tools for merchant
orders, products, after-sale, logistics, shop info, marketing, supply chain,
and categories.

Auth: OAuth 2.0 access_token passed as a query-string parameter (?access_token=...).
Users can provide WX_ACCESS_TOKEN directly, or let the server fetch it
automatically using WX_APP_ID + WX_APP_SECRET (which is cached for 2 hours).

API endpoint: https://api.weixin.qq.com
No per-request signing — just append the access_token to the URL.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.mcpserver import MCPServer

from shared.cn_commerce_base import (
    DEFAULT_RETRY,
    CommerceAPIError,
    CommerceMCPBase,
    ConfigValidationError,
    RetryConfig,
    register_common_tools,
)

# ── WeChat Store client ───────────────────────────────────────────────────────


class WeixinStoreMCP(CommerceMCPBase):
    """WeChat Store (微信小店) client.

    WeChat Store uses OAuth 2.0 with an access_token that is passed as a
    query-string parameter on every request.  No per-request signing is needed.

    If WX_ACCESS_TOKEN is set in the environment, it is used directly.
    Otherwise, WX_APP_ID + WX_APP_SECRET are used to fetch a new token via
    GET /cgi-bin/token, which is cached in-memory (valid for ~2 hours).
    """

    PLATFORM = "WEIXIN_STORE"
    BASE_URL = "https://api.weixin.qq.com"
    sign_method = ""  # No signing for WeChat Store

    def __init__(
        self, app_key: str = "", app_secret: str = "", access_token: str = "",
        token_mode: str | None = None,
    ):
        super().__init__(app_key=app_key, app_secret=app_secret, access_token=access_token)
        self.token_mode = token_mode or ("static" if access_token else "managed")
        if self.token_mode not in {"static", "managed"}:
            raise ValueError("WX_TOKEN_MODE must be static or managed")
        self._access_token = access_token if self.token_mode == "static" else ""
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()

    @staticmethod
    def _parse_response(payload: dict) -> dict:
        if str(payload.get("errcode", 0)) != "0":
            raise CommerceAPIError(code=payload["errcode"], msg=payload.get("errmsg", "unknown"))
        return payload

    async def _ensure_token(self) -> str:
        """Use an explicit token unchanged or serialize managed token refreshes."""
        if self.token_mode == "static":
            if not self._access_token:
                raise ConfigValidationError("WX", ["WX_ACCESS_TOKEN"])
            return self._access_token
        missing = [name for name, value in (("WX_APP_ID", self.app_key),
                   ("WX_APP_SECRET", self.app_secret)) if not value]
        if missing:
            raise ConfigValidationError("WX", missing)
        async with self._token_lock:
            if self._access_token and time.monotonic() < self._token_expires_at:
                return self._access_token
            payload = await self._send_request(
                "GET", f"{self.BASE_URL}/cgi-bin/token", endpoint="/cgi-bin/token",
                params={"grant_type": "client_credential", "appid": self.app_key,
                        "secret": self.app_secret},
                parse_response=self._parse_response,
            )
            if not payload.get("access_token"):
                raise CommerceAPIError(code=-1, msg="Token response is missing access_token")
            lifetime = float(payload.get("expires_in", 7200))
            if lifetime <= 0:
                raise CommerceAPIError(code=-1, msg="Token response has invalid expires_in")
            self._access_token = payload["access_token"]
            self._token_expires_at = time.monotonic() + lifetime - min(300.0, lifetime * 0.1)
            return self._access_token

    async def _request(
        self, method: str, path: str, params: dict | None = None,
        data: dict | None = None, retry_config: RetryConfig | None = DEFAULT_RETRY,
    ) -> dict[str, Any]:
        """Use the shared pool, limits and metrics for read-only store APIs."""
        if self.validate_input:
            self._validate_params(data or params or {})
        token = await self._ensure_token()
        query = dict(params or {})
        query["access_token"] = token
        try:
            return await self._send_request(
                method, f"{self.BASE_URL}{path}", endpoint=path, params=query,
                json_body=(data or {}) if method.upper() != "GET" else None,
                retry_config=retry_config, parse_response=self._parse_response,
            )
        except CommerceAPIError as exc:
            # Only managed tokens can be refreshed automatically. Retry once.
            if self.token_mode != "managed" or str(exc.code) not in {"40001", "40014", "42001"}:
                raise
            async with self._token_lock:
                if self._access_token == token:
                    self._token_expires_at = 0.0
            query["access_token"] = await self._ensure_token()
            return await self._send_request(
                method, f"{self.BASE_URL}{path}", endpoint=path, params=query,
                json_body=(data or {}) if method.upper() != "GET" else None,
                retry_config=retry_config, parse_response=self._parse_response,
            )


# ── Instantiate client from env ────────────────────────────────────────────


def _create_weixin_store_client(*, strict: bool = True) -> WeixinStoreMCP:
    """Accept a static token OR app credentials for managed token renewal."""
    token = os.environ.get("WX_ACCESS_TOKEN", "")
    mode = os.environ.get("WX_TOKEN_MODE") or ("static" if token else "managed")
    required = ["WX_ACCESS_TOKEN"] if mode == "static" else ["WX_APP_ID", "WX_APP_SECRET"]
    missing = [name for name in required if not os.environ.get(name)]
    if strict and missing:
        raise ConfigValidationError("WX", missing)
    return WeixinStoreMCP(
        app_key=os.environ.get("WX_APP_ID", ""),
        app_secret=os.environ.get("WX_APP_SECRET", ""), access_token=token,
        token_mode=mode,
    )


# Permit MCP discovery without credentials; business calls validate configuration.
_wx = _create_weixin_store_client(strict=False)


# ── MCP server ────────────────────────────────────────────────────────────────


@asynccontextmanager
async def _lifespan(_server):
    try:
        yield {}
    finally:
        client = _wx
        if client is not None:
            await client.close()


mcp = MCPServer("mcp-cn-weixin-store", lifespan=_lifespan)


# ═══════════════════════════════════════════════════════════════════════════════
# 订单 (Orders)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_order_list(
    start_time: str,
    end_time: str,
    order_status: str = "",
    page: int = 1,
    page_size: int = 20,
) -> str:
    """Query WeChat Store order list by time range and optional status.

    Args:
        start_time: Order start time, e.g. "2024-01-01 00:00:00"
        end_time: Order end time, e.g. "2024-01-31 23:59:59"
        order_status: Status filter. Common values:
            10 (待付款), 20 (待发货), 30 (已发货), 50 (已完成), 100 (已关闭).
            Empty string means all statuses.
        page: Page number, starting from 1.
        page_size: Number of orders per page (max 100).
    """
    data: dict = {
        "start_create_time": start_time,
        "end_create_time": end_time,
        "page": page,
        "page_size": page_size,
    }
    if order_status:
        data["status"] = int(order_status)

    result = await _wx._request("POST", "/channels/ec/order/list/get", data=data)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_order_detail(order_id: str) -> str:
    """Get full details of a single WeChat Store order.

    Args:
        order_id: The WeChat Store order ID (e.g. "3705115058471207000").
    """
    data = {"order_id": order_id}
    result = await _wx._request("POST", "/channels/ec/order/get", data=data)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 商品 (Products)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_product_list(
    status: int = 0,
    page: int = 1,
    page_size: int = 20,
) -> str:
    """Get product (商品) list with basic info.

    Args:
        status: Product status filter.
            0 (全部), 1 (上架), 2 (下架), 3 (审核中), 4 (审核失败).
            Default 0 = all.
        page: Page number, starting from 1.
        page_size: Number of products per page (max 200).
    """
    data = {
        "status": status,
        "page": page,
        "page_size": page_size,
    }
    result = await _wx._request("POST", "/channels/ec/product/list/get", data=data)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_product_detail(product_id: str) -> str:
    """Get full details of a single product by product ID.

    Args:
        product_id: The WeChat Store product ID (e.g. "10000000000001").
    """
    data = {"product_id": product_id}
    result = await _wx._request("POST", "/channels/ec/product/get", data=data)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 售后 (After-Sale)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_refund_list(
    start_time: str,
    end_time: str,
    page: int = 1,
    page_size: int = 20,
) -> str:
    """Query after-sale (售后) record list by time range.

    Args:
        start_time: Query start time, e.g. "2024-01-01 00:00:00"
        end_time: Query end time, e.g. "2024-01-31 23:59:59"
        page: Page number, starting from 1.
        page_size: Number of records per page (max 100).
    """
    data = {
        "begin_create_time": start_time,
        "end_create_time": end_time,
        "page": page,
        "page_size": page_size,
    }
    result = await _wx._request("POST", "/channels/ec/aftersale/getaftersalelist", data=data)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_refund_detail(after_sale_order_id: str) -> str:
    """Get full details of a single after-sale (refund) record.

    Args:
        after_sale_order_id: The after-sale order ID (e.g. "3705115058471207000").
    """
    data = {"after_sale_order_id": after_sale_order_id}
    result = await _wx._request("POST", "/channels/ec/aftersale/getaftersaleorder", data=data)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 物流 (Logistics)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_logistics_tracking(order_id: str) -> str:
    """Get logistics tracking information for a WeChat Store order.

    Args:
        order_id: The WeChat Store order ID (e.g. "3705115058471207000").
    """
    data = {"order_id": order_id}
    result = await _wx._request("POST", "/channels/ec/order/deliveryinfo/get", data=data)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 店铺 (Shop)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_shop_info() -> str:
    """Get basic shop (店铺) information for the authenticated merchant."""
    result = await _wx._request("POST", "/channels/ec/basicinfo/get", data={})
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 营销 (Marketing)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def list_coupons(
    status: int = 0,
    page: int = 1,
    page_size: int = 20,
) -> str:
    """List coupon (优惠券) activities for the WeChat Store.

    Args:
        status: Coupon status filter.
            0 (全部), 1 (进行中), 2 (未开始), 3 (已结束), 4 (已停止).
            Default 0 = all.
        page: Page number, starting from 1.
        page_size: Number of records per page (max 100).
    """
    data = {
        "status": status,
        "page": page,
        "page_size": page_size,
    }
    result = await _wx._request("POST", "/channels/ec/coupon/list/get", data=data)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 供货 (Supply Chain)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_supply_order_list(
    start_time: str,
    end_time: str,
    status: int = 0,
    page: int = 1,
    page_size: int = 20,
) -> str:
    """Query supply chain order (供货订单) list, unique to WeChat Store.

    Args:
        start_time: Start time, e.g. "2024-01-01 00:00:00"
        end_time: End time, e.g. "2024-01-31 23:59:59"
        status: Supply order status.
            0 (全部), 1 (待发货), 2 (已发货), 3 (已完成), 4 (已取消).
        page: Page number, starting from 1.
        page_size: Number of records per page (max 100).
    """
    data = {
        "start_create_time": start_time,
        "end_create_time": end_time,
        "status": status,
        "page": page,
        "page_size": page_size,
    }
    result = await _wx._request("POST", "/channels/ec/supplier/order/list/get", data=data)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 类目 (Categories)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def list_categories(parent_id: int = 0) -> str:
    """List available product categories (类目) on WeChat Store.

    Args:
        parent_id: Parent category ID. Use 0 to get top-level categories.
    """
    data = {"parent_id": parent_id}
    result = await _wx._request("POST", "/channels/ec/category/list/get", data=data)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ── Cross-platform operational tools (get_metrics/get_traces/get_alerts/export_data) ──
register_common_tools(mcp, _wx)


# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════


def main() -> None:
    """Entry point for 'mcp-cn-weixin-store' console script."""
    mcp.run()


if __name__ == "__main__":
    main()
