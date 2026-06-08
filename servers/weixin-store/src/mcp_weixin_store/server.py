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

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

# Let the server find the shared base class at <repo-root>/shared/
_project_root = Path(__file__).resolve().parents[4]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from shared.cn_commerce_base import CommerceMCPBase, CommerceAPIError


# ── WeChat Store client ───────────────────────────────────────────────────────

class WeixinStoreMCP(CommerceMCPBase):
    """WeChat Store (微信小店) client.

    WeChat Store uses OAuth 2.0 with an access_token that is passed as a
    query-string parameter on every request.  No per-request signing is needed.

    If WX_ACCESS_TOKEN is set in the environment, it is used directly.
    Otherwise, WX_APP_ID + WX_APP_SECRET are used to fetch a new token via
    GET /cgi-bin/token, which is cached in-memory (valid for ~2 hours).
    """

    BASE_URL = "https://api.weixin.qq.com"
    sign_method = ""  # No signing for WeChat Store

    # Internal token cache
    _access_token: str = ""
    _token_expires_at: float = 0.0

    def __init__(self, app_key: str = "", app_secret: str = "", access_token: str = ""):
        super().__init__(app_key=app_key, app_secret=app_secret, access_token=access_token)
        if self.access_token:
            self._access_token = self.access_token

    async def _ensure_token(self) -> str:
        """Return a valid access_token, fetching one if necessary."""
        # If caller provided a static token, use it
        if self._access_token and not self.app_key:
            return self._access_token

        # If the cached token is still valid (allow 5 min buffer)
        if self._access_token and time.time() < self._token_expires_at - 300:
            return self._access_token

        # Fetch a fresh token
        if not self.app_key or not self.app_secret:
            raise CommerceAPIError(
                code=-1,
                msg=(
                    "WX_ACCESS_TOKEN not set and no WX_APP_ID / WX_APP_SECRET "
                    "available to fetch one. Set at least one pair of env vars."
                ),
            )

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self.BASE_URL}/cgi-bin/token",
                params={
                    "grant_type": "client_credential",
                    "appid": self.app_key,
                    "secret": self.app_secret,
                },
            )
        data = resp.json()
        if "errcode" in data and data["errcode"] != 0:
            raise CommerceAPIError(code=data["errcode"], msg=data.get("errmsg", "unknown"))
        self._access_token = data["access_token"]
        self._token_expires_at = time.time() + data.get("expires_in", 7200)
        return self._access_token

    async def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        data: dict | None = None,
    ) -> dict[str, Any]:
        """Make an API request with access_token in query string.

        Overrides the base-class _request which does complex MD5/HMAC signing.
        WeChat Store only needs ?access_token=TOKEN appended to the URL.
        """
        token = await self._ensure_token()
        url = f"{self.BASE_URL}{path}"
        query_params: dict[str, str] = {"access_token": token}
        if params:
            query_params.update(params)

        async with httpx.AsyncClient(timeout=30) as client:
            if method == "GET":
                resp = await client.get(url, params=query_params)
            else:
                resp = await client.post(url, params=query_params, json=(data or {}))

        result = resp.json()
        # WeChat errors use "errcode" (0 = success)
        if "errcode" in result and result["errcode"] != 0:
            raise CommerceAPIError(
                code=result["errcode"],
                msg=result.get("errmsg", "unknown"),
            )
        return result


# ── Instantiate client from env ───────────────────────────────────────────────

_wx = WeixinStoreMCP(
    app_key=os.environ.get("WX_APP_ID", ""),
    app_secret=os.environ.get("WX_APP_SECRET", ""),
    access_token=os.environ.get("WX_ACCESS_TOKEN", ""),
)


# ── MCP server ────────────────────────────────────────────────────────────────

mcp = FastMCP("mcp-cn-weixin-store")


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


# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════


def main() -> None:
    """Entry point for 'mcp-cn-weixin-store' console script."""
    mcp.run()


if __name__ == "__main__":
    main()
