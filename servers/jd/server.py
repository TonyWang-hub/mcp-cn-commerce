"""JD (京东) MCP server — provides tools for reading merchant orders, products, and shop info.

Auth via env vars: JD_APP_KEY, JD_APP_SECRET, JD_ACCESS_TOKEN.
API endpoint: https://api.jd.com/routerjson
Sign method: MD5 (official JOS form protocol)
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from servers.jd.client import JDMCP as JDMCP  # pylint: disable=useless-import-alias
from servers.jd.schema import ORDER_DETAIL, ORDER_SEARCH, SHOP_INFO, validate_params
from shared.cn_commerce_base import (
    ConfigValidationError,
    register_common_tools,
)

# ── JD client ───────────────────────────────────────────────────────────────


# ── Instantiate client from env ────────────────────────────────────────────


def _create_jd_client() -> JDMCP:
    """Create JD client with configuration validation."""
    try:
        return JDMCP.from_env("JD", ["APP_KEY", "APP_SECRET", "ACCESS_TOKEN"])
    except ConfigValidationError:
        # Fallback to direct instantiation for backward compatibility
        return JDMCP(
            app_key=os.environ.get("JD_APP_KEY", ""),
            app_secret=os.environ.get("JD_APP_SECRET", ""),
            access_token=os.environ.get("JD_ACCESS_TOKEN", ""),
        )


jd = _create_jd_client()


# ── MCP server ─────────────────────────────────────────────────────────────


@asynccontextmanager
async def _lifespan(_server):
    try:
        yield {}
    finally:
        client = jd
        if client is not None:
            await client.close()


mcp = MCPServer("mcp-cn-jd", lifespan=_lifespan)


def _require_official_read_contract() -> None:
    raise ToolError("JD POP after-sale service is not a verified completed-refund contract. See docs/jd-contract.md")


@mcp.tool()
async def get_order_list(
    start_time: str,
    end_time: str,
    order_status: str = "",
    page: int = 1,
    page_size: int = 20,
    source_id: str = "",
    optional_fields: str = "",
    date_type: int = 0,
    sort_type: int = 2,
) -> str:
    """Read POP orders in a fixed window, at most one calendar month.

    source_id must explicitly select the caller origin (official default: JOS).
    optional_fields is a comma-separated list of current orderInfo field names.
    date_type=1 selects creation; other integers select modification. sort_type=1
    is descending, other integers ascending. Page is one-based, size at most100.
    Empty order_status selects the documented ALL state.
    """
    biz_params = {
        "start_date": start_time,
        "end_date": end_time,
        "page": str(page),
        "page_size": str(page_size),
        "order_state": order_status or "ALL",
        "source_id": source_id,
        "optional_fields": optional_fields,
        "dateType": date_type,
        "sortType": sort_type,
    }
    try:
        validate_params(ORDER_SEARCH, biz_params)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    result = await jd._call(ORDER_SEARCH, biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_order_detail(order_id: str, source_id: str = "", optional_fields: str = "") -> str:
    """Read one POP order, requiring explicit caller origin and selected fields."""
    try:
        if not order_id.isascii() or not order_id.isdecimal():
            raise ValueError("JD POP order_id must be a positive decimal ID")
        biz_params = {"order_id": int(order_id), "source_id": source_id, "optional_fields": optional_fields}
        validate_params(ORDER_DETAIL, biz_params)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    result = await jd._call(ORDER_DETAIL, biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_product_list(
    page: int = 1,
    page_size: int = 20,
    ware_status: str = "",
) -> str:
    """Get product (ware) list with stock and price info.

    Args:
        page: Page number, starting from 1.
        page_size: Number of products per page (max 100).
        ware_status: Product status filter. Empty for all.
            Common values: "0" (draft), "1" (never-on-sale),
            "2" (on-sale), "3" (off-shelf).
    """
    biz_params = {
        "page": str(page),
        "page_size": str(page_size),
    }
    if ware_status:
        biz_params["ware_status"] = ware_status

    result = await jd._call("jd.pop.ware.search", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_shop_info(shop_id: str = "") -> str:
    """Read the token's POP shop; optional shop_id verifies the returned identity."""
    result = await jd._call(SHOP_INFO, {})
    if shop_id:
        shop = result.get("jingdong_vender_shop_query_responce", {}).get("shop_jos_result", {})
        if str(shop.get("shop_id", "")) != shop_id:
            raise ToolError("JD POP returned a different shop identity")
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 售后 (After-Sale)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_after_sale_list(
    start_time: str,
    end_time: str,
    status: str = "",
    page: int = 1,
    page_size: int = 20,
) -> str:
    """Query after-sale (return/refund/exchange) list by time range and optional status.

    Args:
        start_time: Query start time, e.g. "2024-01-01 00:00:00"
        end_time: Query end time, e.g. "2024-01-31 23:59:59"
        status: After-sale status filter. Common values:
            WAIT_SELLER_AGREE (waiting for seller approval),
            WAIT_BUYER_RETURN_GOODS (waiting for buyer to return goods),
            WAIT_SELLER_RECEIVE_GOODS (waiting for seller to receive goods),
            COMPLETE (completed),
            CLOSED (closed).
            Empty string means all statuses.
        page: Page number, starting from 1.
        page_size: Number of records per page (max 100).
    """
    _require_official_read_contract()
    biz_params = {
        "start_date": start_time,
        "end_date": end_time,
        "page": str(page),
        "page_size": str(page_size),
    }
    if status:
        biz_params["status"] = status

    result = await jd._call("jd.pop.afs.search", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_after_sale_detail(after_sale_id: str) -> str:
    """Get full details of a single after-sale (return/refund/exchange) record.

    Args:
        after_sale_id: The after-sale record ID (e.g. "AS00000001").
    """
    _require_official_read_contract()
    biz_params = {"after_sale_id": after_sale_id}
    result = await jd._call("jd.pop.afs.get", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 物流 (Logistics)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_logistics_tracking(order_id: str) -> str:
    """Get logistics tracking information for an order.

    Args:
        order_id: The JD order ID (e.g. "3000000000001").
    """
    biz_params = {"order_id": order_id}
    result = await jd._call("jd.pop.logistics.trace", biz_params)
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
    """Query product review (comment) list.

    Args:
        product_id: The product/ware ID (e.g. "20000001").
        page: Page number, starting from 1.
        page_size: Number of reviews per page (max 100).
    """
    biz_params = {
        "ware_id": product_id,
        "page": str(page),
        "page_size": str(page_size),
    }

    result = await jd._call("jd.pop.comment.search", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_review_detail(review_id: str) -> str:
    """Get full details of a single review.

    Args:
        review_id: The review/comment ID (e.g. "C00000001").
    """
    biz_params = {"comment_id": review_id}
    result = await jd._call("jd.pop.comment.get", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 价格 (Pricing)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_price_info(sku_ids: str) -> str:
    """Get real-time price information for given SKUs, including promotion overlay.

    Args:
        sku_ids: Comma-separated SKU IDs, e.g. "10000001,10000002,10000003".
            Maximum 100 SKUs per request.
    """
    biz_params = {"sku_ids": sku_ids}

    result = await jd._call("jd.pop.price.get", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 库存 (Inventory)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_inventory(ware_ids: str) -> str:
    """Query current inventory/stock levels for given ware IDs.

    Args:
        ware_ids: Comma-separated ware IDs, e.g. "20000001,20000002".
            Maximum 100 ware IDs per request.
    """
    biz_params = {"ware_ids": ware_ids}

    result = await jd._call("jd.pop.inventory.get", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 促销 (Marketing)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def list_promotions(
    status: str = "",
    page: int = 1,
    page_size: int = 20,
) -> str:
    """List promotion activities.

    Args:
        status: Promotion status filter. Common values:
            "1" (ongoing), "2" (ended), "3" (not started).
            Empty string means all statuses.
        page: Page number, starting from 1.
        page_size: Number of records per page (max 100).
    """
    biz_params = {
        "page": str(page),
        "page_size": str(page_size),
    }
    if status:
        biz_params["status"] = status

    result = await jd._call("jd.pop.promotion.search", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def list_coupons(
    status: str = "",
    page: int = 1,
    page_size: int = 20,
) -> str:
    """List coupon templates.

    Args:
        status: Coupon status filter. Common values:
            "1" (active), "2" (expired), "3" (not started).
            Empty string means all statuses.
        page: Page number, starting from 1.
        page_size: Number of records per page (max 100).
    """
    biz_params = {
        "page": str(page),
        "page_size": str(page_size),
    }
    if status:
        biz_params["status"] = status

    result = await jd._call("jd.pop.coupon.search", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 类目 (Categories)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def list_categories(parent_id: str = "0") -> str:
    """List product categories under a given parent category.

    Args:
        parent_id: Parent category ID. Use "0" (default) to list top-level categories.
    """
    biz_params = {"parent_id": parent_id}

    result = await jd._call("jd.pop.category.search", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 店铺-扩展 (Shop extended)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_shop_score() -> str:
    """Get shop DSR (Detail Seller Rating) scores including product description,
    service attitude, and delivery speed ratings.
    """
    result = await jd._call("jd.pop.shop.score.get", {})
    return json.dumps(result, ensure_ascii=False, indent=2)


# ── Cross-platform operational tools (get_metrics/get_traces/get_alerts/export_data) ──
register_common_tools(mcp, jd)


def main() -> None:
    """Entry point for 'mcp-cn-jd' console script."""
    mcp.run()


if __name__ == "__main__":
    main()
