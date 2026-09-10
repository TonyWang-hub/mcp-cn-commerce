"""Kuaishou (快手) MCP server — provides tools for reading merchant orders,
products, shop info, after-sale, logistics, reviews, marketing, and coupons.

Auth via env vars: KUAISHOU_APP_KEY, KUAISHOU_APP_SECRET, KUAISHOU_SIGN_SECRET, KUAISHOU_ACCESS_TOKEN.
API endpoint: https://openapi.kwaixiaodian.com
Sign method: MD5 (sorted key=value pairs + &signSecret=... → lowercase hex)
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from servers.kuaishou.client import KuaishouMCP as KuaishouMCP  # pylint: disable=useless-import-alias
from servers.kuaishou.schema import ORDER_DETAIL, ORDER_LIST, REFUND_DETAIL, REFUND_LIST, SHOP_INFO, validate_params
from shared.cn_commerce_base import (
    register_common_tools,
)

# ── Kuaishou client ───────────────────────────────────────────────────────────


# ── Instantiate client from env ────────────────────────────────────────────


def _create_kuaishou_client() -> KuaishouMCP:
    """Preserve the platform-specific signing secret in every configuration."""
    return KuaishouMCP(
        app_key=os.environ.get("KUAISHOU_APP_KEY", ""),
        app_secret=os.environ.get("KUAISHOU_APP_SECRET", ""),
        sign_secret=os.environ.get("KUAISHOU_SIGN_SECRET", ""),
        access_token=os.environ.get("KUAISHOU_ACCESS_TOKEN", ""),
    )


ks = _create_kuaishou_client()


# ── MCP server ────────────────────────────────────────────────────────────────


@asynccontextmanager
async def _lifespan(_server):
    try:
        yield {}
    finally:
        client = ks
        if client is not None:
            await client.close()


mcp = MCPServer("mcp-cn-kuaishou", lifespan=_lifespan)


def _milliseconds(value: str) -> int:
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        return int(parsed.timestamp() * 1000)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ToolError("Kuaishou time must be ISO8601 (naive values use Asia/Shanghai)") from exc


def _numeric_id(value: str, field: str) -> int:
    if not value.isascii() or not value.isdecimal():
        raise ToolError(f"Kuaishou {field} must be a positive decimal ID")
    number = int(value)
    if not 0 < number < 2**63:
        raise ToolError(f"Kuaishou {field} must fit positive int64")
    return number


def _check(method: str, params: dict) -> None:
    try:
        validate_params(method, params)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


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
    cursor: str = "",
    query_type: int = 1,
    sort: int = 1,
) -> str:
    """Read orders with a real cursor and a fixed window of at most seven days.

    Times accept ISO8601; naive values use Asia/Shanghai. order_status selects
    orderViewStatus: empty/1 all,2 unpaid,3 unshipped,4 shipped,5 received,6 success,
    7 closed. These differ from output order status. Size is at most50.
    page>1 requires the preceding response cursor; never derive it from a page.
    query_type=1 creation,2 modification; sort=1 descending,2 ascending.
    """
    if page < 1 or (page > 1 and not cursor):
        raise ToolError("Kuaishou pagination requires a real cursor after the first page")
    params = {
        "beginTime": _milliseconds(start_time),
        "endTime": _milliseconds(end_time),
        "orderViewStatus": _numeric_id(order_status, "order_status") if order_status else 1,
        "pageSize": page_size,
        "cursor": cursor,
        "queryType": query_type,
        "sort": sort,
    }
    _check(ORDER_LIST, params)
    result = await ks._call(ORDER_LIST, params)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_order_detail(order_id: str) -> str:
    """Read one order using its official numeric int64 oid."""
    params = {"oid": _numeric_id(order_id, "order_id")}
    result = await ks._call(ORDER_DETAIL, params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 商品 (Products)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_product_list(
    page: int = 1,
    page_size: int = 20,
) -> str:
    """Get product (item) list with basic info.

    Args:
        page: Page number, starting from 1.
        page_size: Number of products per page (max 100).
    """
    params = {
        "page": str(page),
        "page_size": str(page_size),
    }
    result = await ks._call("/open/api/item/list", params)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_product_detail(item_id: str) -> str:
    """Get full details of a single product by item ID.

    Args:
        item_id: The Kuaishou item ID (e.g. "KS987654321").
    """
    params = {"item_id": item_id}
    result = await ks._call("/open/api/item/detail", params)
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
    pcursor: str = "",
    query_type: int = 1,
    request_type: int = 9,
    sort: int = 1,
) -> str:
    """Read after-sales within one day using the returned pcursor.

    ISO8601 times are converted to milliseconds (naive means Asia/Shanghai).
    request_type=8 waiting or9 all; query_type=1 created or2 updated. page_size<=100.
    Statuses:10 waiting,12 rejected,20 intervention,30 awaiting return,40 awaiting
    receipt,45 exchanged delivery,50 refund processing,60 success,70 closed.
    Success can include exchanges: consumers must also inspect handlingWay.
    """
    if page < 1 or (page > 1 and not pcursor):
        raise ToolError("Kuaishou pagination requires a real pcursor after the first page")
    params = {
        "beginTime": _milliseconds(start_time),
        "endTime": _milliseconds(end_time),
        "type": request_type,
        "pageSize": page_size,
        "currentPage": page,
        "pcursor": pcursor,
        "queryType": query_type,
        "sort": sort,
    }
    if refund_status:
        params["status"] = _numeric_id(refund_status, "refund_status")
    _check(REFUND_LIST, params)
    result = await ks._call(REFUND_LIST, params)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_refund_detail(refund_id: str) -> str:
    """Read one after-sale using its official numeric int64 refundId."""
    result = await ks._call(REFUND_DETAIL, {"refundId": _numeric_id(refund_id, "refund_id")})
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 物流 (Logistics)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_logistics_tracking(order_id: str) -> str:
    """Get logistics tracking information for an order.

    Args:
        order_id: The Kuaishou order ID (e.g. "KS202401150000001").
    """
    params = {"order_id": order_id}
    result = await ks._call("/open/api/logistics/track", params)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def list_logistics_companies() -> str:
    """List all available logistics companies on Kuaishou platform."""
    result = await ks._call("/open/api/logistics/company/list")
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 评价 (Reviews)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_review_list(
    item_id: str,
    page: int = 1,
    page_size: int = 20,
) -> str:
    """Query product review (comment) list by item ID.

    Args:
        item_id: The Kuaishou item ID (e.g. "KS987654321").
        page: Page number, starting from 1.
        page_size: Number of reviews per page (max 100).
    """
    params = {
        "item_id": item_id,
        "page": str(page),
        "page_size": str(page_size),
    }
    result = await ks._call("/open/api/comment/list", params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 店铺 (Shop)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_shop_info() -> str:
    """Read the authorized user's shop name/type; this API has no shop ID."""
    result = await ks._call(SHOP_INFO, {})
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 营销 (Marketing)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def list_promotions(
    page: int = 1,
    page_size: int = 20,
) -> str:
    """List promotion activities for the authenticated shop.

    Args:
        page: Page number, starting from 1.
        page_size: Number of records per page (max 100).
    """
    params = {
        "page": str(page),
        "page_size": str(page_size),
    }
    result = await ks._call("/open/api/promotion/list", params)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def list_coupons(
    page: int = 1,
    page_size: int = 20,
    status: str = "",
) -> str:
    """List coupon activities for the authenticated shop.

    Args:
        page: Page number, starting from 1.
        page_size: Number of records per page (max 100).
        status: Coupon status filter. Common values:
            1 (未生效), 2 (生效中), 3 (已过期), 4 (已停止).
            Empty string means all statuses.
    """
    params: dict = {
        "page": str(page),
        "page_size": str(page_size),
    }
    if status:
        params["status"] = status

    result = await ks._call("/open/api/coupon/list", params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ── Cross-platform operational tools (get_metrics/get_traces/get_alerts/export_data) ──
register_common_tools(mcp, ks)


# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════


def main() -> None:
    """Entry point for 'mcp-cn-kuaishou' console script."""
    mcp.run()


if __name__ == "__main__":
    main()
