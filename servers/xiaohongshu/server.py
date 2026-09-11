"""Xiaohongshu (小红书) MCP server — provides tools for reading merchant orders,
products, shop info, after-sale, logistics, reviews, marketing, inventory, and billing data.

Auth via env vars: XHS_CLIENT_ID, XHS_CLIENT_SECRET, XHS_ACCESS_TOKEN.
API endpoint: https://ark.xiaohongshu.com/ark/open_api/v3/common_controller
Sign method: official OAuth v2 system-field MD5 (lowercase)
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager

from mcp.server.mcpserver import MCPServer

from servers.xiaohongshu.client import XiaohongshuMCP
from shared.cn_commerce_base import (
    ConfigValidationError,
    register_common_tools,
)

# ── Xiaohongshu client ────────────────────────────────────────────────────────


# ── Instantiate client from env ────────────────────────────────────────────


def _create_xiaohongshu_client() -> XiaohongshuMCP:
    """Create xiaohongshu client with configuration validation."""
    try:
        return XiaohongshuMCP.from_env("XHS", ["CLIENT_ID", "CLIENT_SECRET", "ACCESS_TOKEN"])
    except ConfigValidationError:
        # Fallback to direct instantiation for backward compatibility
        return XiaohongshuMCP(
            app_key=os.environ.get("XHS_CLIENT_ID", ""),
            app_secret=os.environ.get("XHS_CLIENT_SECRET", ""),
            access_token=os.environ.get("XHS_ACCESS_TOKEN", ""),
        )


xhs = _create_xiaohongshu_client()


# ── MCP server ─────────────────────────────────────────────────────────────────


@asynccontextmanager
async def _lifespan(_server):
    try:
        yield {}
    finally:
        client = xhs
        if client is not None:
            await client.close()


mcp = MCPServer("mcp-cn-xiaohongshu", lifespan=_lifespan)


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
    time_type: int = 1,
) -> str:
    """Query one order page using native integer query times.

    Query time units require platform confirmation; date strings are rejected.
    Official windows are 24 hours for creation and 30 minutes for update.
    For update scans use maxPageNo and read from the last page to the first.

    Args:
        start_time: Platform-confirmed native integer start time, as a string.
        end_time: Platform-confirmed native integer end time, as a string.
        order_status: Status filter. Common values:
            1 (待付款), 2 (处理中), 3 (清关中), 4 (待发货), 5 (部分发货),
            6 (待收货), 7 (已完成), 8 (已关闭), 9 (已取消), 10 (换货申请中).
            Empty string means all statuses.
        page: Page number, starting from 1.
        page_size: Number of orders per page (max 100).
        time_type: 1 for creation time; 2 for update time.
    """
    biz_params: dict = {
        "start_time": start_time,
        "end_time": end_time,
        "page": str(page),
        "page_size": str(page_size),
        "time_type": time_type,
    }
    if order_status:
        biz_params["order_status"] = str(order_status)

    result = await xhs._call("GET", "/api/order/list", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_order_detail(order_id: str) -> str:
    """Get full details of a single order.

    Args:
        order_id: The XHS order ID (e.g. "XHS20240115000001").
    """
    biz_params = {"order_id": order_id}
    result = await xhs._call("GET", "/api/order/detail", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 商品 (Products)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_product_list(
    page: int = 1,
    page_size: int = 20,
) -> str:
    """Get product (goods) list with basic info.

    Args:
        page: Page number, starting from 1.
        page_size: Number of products per page (max 100).
    """
    biz_params = {
        "page": str(page),
        "page_size": str(page_size),
    }
    result = await xhs._call("GET", "/api/product/list", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_product_detail(product_id: str) -> str:
    """Get full details of a single product by product ID.

    Args:
        product_id: The XHS product ID (e.g. "5f8a9b2c3d4e5f6a7b8c9d0e").
    """
    biz_params = {"product_id": product_id}
    result = await xhs._call("GET", "/api/product/detail", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 售后 (After-Sale)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_refund_list(
    start_time: str,
    end_time: str,
    refund_status: str = "",
    page: int = 1,
    page_size: int = 20,
    time_type: int = 1,
) -> str:
    """Query one after-sale page with inclusive millisecond time boundaries.

    Maximum window: 24 hours for creation, 30 minutes for update.

    Args:
        start_time: Native milliseconds or ISO time including a timezone.
        end_time: Native milliseconds or ISO time including a timezone.
        refund_status: Status filter. Common values:
            1 (待审核), 2 (待寄回), 3 (待收货), 4 (已完成), 5 (已取消),
            6 (已关闭), 9 (审核拒绝); comma-separated official status codes are accepted.
            Empty string means all statuses.
        page: Page number, starting from 1.
        page_size: Number of records per page (max 100).
        time_type: 1 for creation time; 2 for update time.
    """
    biz_params = {
        "start_time": start_time,
        "end_time": end_time,
        "page": str(page),
        "page_size": str(page_size),
        "time_type": time_type,
    }
    if refund_status:
        biz_params["refund_status"] = str(refund_status)

    result = await xhs._call("GET", "/api/refund/list", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_refund_detail(refund_id: str) -> str:
    """Get full details of a single refund record.

    Args:
        refund_id: The refund/after-sale record ID (e.g. "RF2024011500001").
    """
    biz_params = {"refund_id": refund_id}
    result = await xhs._call("GET", "/api/refund/detail", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 物流 (Logistics)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_logistics_tracking(order_id: str) -> str:
    """Get logistics tracking information for an order.

    Args:
        order_id: The XHS order ID (e.g. "XHS20240115000001").
    """
    biz_params = {"order_id": order_id}
    result = await xhs._call("GET", "/api/logistics/tracking", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 评价 (Reviews)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_review_list(
    product_id: str,
    page: int = 1,
    page_size: int = 20,
) -> str:
    """Unavailable: no verified official review API mapping; returns an explicit error.

    Args:
        product_id: The XHS product ID (e.g. "5f8a9b2c3d4e5f6a7b8c9d0e").
        page: Page number, starting from 1.
        page_size: Number of reviews per page (max 100).
    """
    biz_params = {
        "product_id": product_id,
        "page": str(page),
        "page_size": str(page_size),
    }
    result = await xhs._call("GET", "/api/review/list", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 店铺 (Shop)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_shop_info() -> str:
    """Unavailable: no verified official shop-info API mapping; returns an explicit error."""
    result = await xhs._call("GET", "/api/shop/info")
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 营销 (Marketing)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def list_promotions(
    page: int = 1,
    page_size: int = 20,
) -> str:
    """Unavailable: no verified official promotion API mapping; returns an explicit error.

    Args:
        page: Page number, starting from 1.
        page_size: Number of records per page (max 100).
    """
    biz_params = {
        "page": str(page),
        "page_size": str(page_size),
    }
    result = await xhs._call("GET", "/api/promotion/list", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def list_coupons(
    status: str = "",
    page: int = 1,
    page_size: int = 20,
) -> str:
    """Unavailable: no verified official marketing-coupon API mapping; returns an explicit error.

    Args:
        status: Coupon status filter. Common values:
            1 (进行中), 2 (已结束), 3 (未开始).
            Empty string means all statuses.
        page: Page number, starting from 1.
        page_size: Number of records per page (max 100).
    """
    biz_params: dict = {
        "page": str(page),
        "page_size": str(page_size),
    }
    if status:
        biz_params["status"] = str(status)

    result = await xhs._call("GET", "/api/coupon/list", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 库存 (Inventory)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_inventory(
    product_id: str = "",
    sku_id: str = "",
    page: int = 1,
    page_size: int = 20,
) -> str:
    """Query one SKU using the official inventory V2 API. sku_id is required.

    Args:
        product_id: Unsupported by the official SKU inventory endpoint; leave empty.
        sku_id: Required official SKU ID.
        page: Page number, starting from 1.
        page_size: Number of records per page (max 100).
    """
    biz_params: dict = {
        "page": str(page),
        "page_size": str(page_size),
    }
    if product_id:
        biz_params["product_id"] = product_id
    if sku_id:
        biz_params["sku_id"] = sku_id

    result = await xhs._call("GET", "/api/inventory/query", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 财务 (Finance)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_bill_list(
    start_time: str,
    end_time: str,
    bill_type: str = "",
    page: int = 1,
    page_size: int = 20,
) -> str:
    """Query account transaction records by time range (Asia/Shanghai for naive dates).

    Args:
        start_time: Bill start time, e.g. "2024-01-01 00:00:00"
        end_time: Bill end time, e.g. "2024-01-31 23:59:59"
        bill_type: Bill type filter. Common values:
            STATEMENT_IN (结算入账), STATEMENT_REFUND (退款), RECHARGE (充值).
            Use comma-separated official tradeTypes names; legacy numeric codes are unsupported.
            Empty string means all types.
        page: Page number, starting from 1.
        page_size: Number of records per page (max 100).
    """
    biz_params: dict = {
        "start_time": start_time,
        "end_time": end_time,
        "page": str(page),
        "page_size": str(page_size),
    }
    if bill_type:
        biz_params["bill_type"] = str(bill_type)

    result = await xhs._call("GET", "/api/bill/list", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ── Cross-platform operational tools (get_metrics/get_traces/get_alerts/export_data) ──
register_common_tools(mcp, xhs)


# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════


def main() -> None:
    """Entry point for 'mcp-cn-xiaohongshu' console script."""
    mcp.run()


if __name__ == "__main__":
    main()
