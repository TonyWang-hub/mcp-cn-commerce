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
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from mcp.server.mcpserver import MCPServer

from servers.weixin_store.client import WeixinStoreMCP as WeixinStoreMCP
from shared.cn_commerce_base import (
    ConfigValidationError,
    register_common_tools,
)

# ── WeChat Store client ───────────────────────────────────────────────────────


STATIC_MODE = "static"
MANAGED_MODE = "managed"


# ── Instantiate client from env ────────────────────────────────────────────


def _create_weixin_store_client(*, strict: bool = True) -> WeixinStoreMCP:
    """Accept a static token OR app credentials for managed token renewal."""
    token = os.environ.get("WX_ACCESS_TOKEN", "")
    mode = os.environ.get("WX_TOKEN_MODE") or ("static" if token else "managed")
    required = ["WX_ACCESS_TOKEN"] if mode == STATIC_MODE else ["WX_APP_ID", "WX_APP_SECRET"]
    missing = [name for name in required if not os.environ.get(name)]
    if strict and missing:
        raise ConfigValidationError("WX", missing)
    return WeixinStoreMCP(
        app_key=os.environ.get("WX_APP_ID", ""),
        app_secret=os.environ.get("WX_APP_SECRET", ""),
        access_token=token,
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
    next_key: str = "",
    time_type: str = "create",
) -> str:
    """Query orders using a seconds-based time range and the returned cursor.

    Args:
        start_time: ISO date/time (naive values use Asia/Shanghai).
        end_time: ISO date/time, no more than 7 days after start_time.
        order_status: Optional official status: 10, 12, 13, 20, 21, 30, 100 or 250.
        page: Compatibility parameter; only 1 is accepted. Use next_key for subsequent pages.
        page_size: Number of orders per page, 1 through 100.
        next_key: Cursor returned by the previous response; empty on the first request.
        time_type: create or update. Neither is a payment-date completeness guarantee.
    """
    if page != 1:
        raise ValueError("WeChat orders use next_key, not page numbers")
    if not 1 <= page_size <= 100:
        raise ValueError("page_size must be between 1 and 100")
    if time_type not in {"create", "update"}:
        raise ValueError("time_type must be create or update")

    def seconds(value):
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        return int(parsed.timestamp())

    start, end = seconds(start_time), seconds(end_time)
    if end < start or end - start > 7 * 86400:
        raise ValueError("Order time range must be ordered and no more than 7 days")
    data: dict = {
        f"{time_type}_time_range": {"start_time": start, "end_time": end},
        "page_size": page_size,
        "next_key": next_key,
    }
    if order_status:
        status = int(order_status)
        if status not in {10, 12, 13, 20, 21, 30, 100, 250}:
            raise ValueError("Unknown WeChat order status")
        data["status"] = status
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
