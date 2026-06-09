"""Xiaohongshu (小红书) MCP server — provides tools for reading merchant orders,
products, shop info, after-sale, logistics, reviews, marketing, inventory, and billing data.

Auth via env vars: XHS_CLIENT_ID, XHS_CLIENT_SECRET, XHS_ACCESS_TOKEN.
API endpoint: https://open.xiaohongshu.com
Sign method: MD5 (params sorted, secret+string+secret → MD5 → uppercase)
"""

from __future__ import annotations

import json
import os
import time

import httpx
from mcp.server.fastmcp import FastMCP

from shared.cn_commerce_base import (
    CommerceAPIError,
    CommerceMCPBase,
    ConfigValidationError,
    SignMethod,
    register_common_tools,
)

# ── Xiaohongshu client ────────────────────────────────────────────────────────


class XiaohongshuMCP(CommerceMCPBase):
    """Xiaohongshu-specific client.

    XHS uses OAuth 2.0 (client_id + client_secret), standard MD5 signing,
    and RESTful API paths under the open platform gateway.
    """

    BASE_URL = "https://open.xiaohongshu.com"
    sign_method = SignMethod.MD5

    async def _call(self, method: str, path: str, biz_params: dict | None = None) -> dict:
        """Make a XHS API call.

        Builds system params (client_id, timestamp, sign_method, access_token),
        merges business params, signs with MD5, and sends the request.
        """
        biz_params = biz_params or {}

        params: dict[str, str] = {
            "client_id": self.app_key,
            "timestamp": str(int(time.time() * 1000)),
            "sign_method": self.sign_method,
        }
        if self.access_token:
            params["access_token"] = self.access_token

        # Merge business params (convert all values to strings for signing)
        for k, v in biz_params.items():
            params[k] = str(v)

        # Sign (base-class MD5: secret + sorted_kv + secret → md5 → upper)
        params["sign"] = self._sign(params)

        url = f"{self.BASE_URL}{path}"
        async with httpx.AsyncClient(timeout=30) as client:
            if method == "GET":
                resp = await client.get(url, params=params)
            else:
                resp = await client.post(url, params=params, json=biz_params)

        result = resp.json()
        if "error_response" in result:
            raise CommerceAPIError(
                code=result["error_response"].get("code", result["error_response"].get("error_code", -1)),
                msg=result["error_response"].get("msg", result["error_response"].get("error_msg", "unknown")),
            )
        return result


# ── Instantiate client from env ────────────────────────────────────────────


def _create_xiaohongshu_client() -> XiaohongshuMCP:
    """Create xiaohongshu client with configuration validation."""
    try:
        return XiaohongshuMCP.from_env("XHS", ["CLIENT_ID", "CLIENT_SECRET", "ACCESS_TOKEN"])
    except ConfigValidationError:
        # Fallback to direct instantiation for backward compatibility
        return XiaohongshuMCP(
            client_id=os.environ.get("XHS_CLIENT_ID", ""),
            client_secret=os.environ.get("XHS_CLIENT_SECRET", ""),
            access_token=os.environ.get("XHS_ACCESS_TOKEN", ""),
        )


xhs = _create_xiaohongshu_client()


# ── MCP server ─────────────────────────────────────────────────────────────────

mcp = FastMCP("mcp-cn-xiaohongshu")


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
    """Query order list by time range and optional status.

    Args:
        start_time: Order start time, e.g. "2024-01-01 00:00:00"
        end_time: Order end time, e.g. "2024-01-31 23:59:59"
        order_status: Status filter. Common values:
            1 (待发货), 2 (已发货), 3 (已签收), 4 (退款中), 5 (已退款).
            Empty string means all statuses.
        page: Page number, starting from 1.
        page_size: Number of orders per page (max 100).
    """
    biz_params: dict = {
        "start_time": start_time,
        "end_time": end_time,
        "page": str(page),
        "page_size": str(page_size),
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
) -> str:
    """Query refund (after-sale) list by time range.

    Args:
        start_time: Query start time, e.g. "2024-01-01 00:00:00"
        end_time: Query end time, e.g. "2024-01-31 23:59:59"
        refund_status: Status filter. Common values:
            1 (待处理), 2 (处理中), 3 (已退款), 4 (已拒绝).
            Empty string means all statuses.
        page: Page number, starting from 1.
        page_size: Number of records per page (max 100).
    """
    biz_params = {
        "start_time": start_time,
        "end_time": end_time,
        "page": str(page),
        "page_size": str(page_size),
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
    """Query product review (comment) list by product ID.

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
    """Get shop basic information for the authenticated merchant."""
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
    """List promotion activities for the authenticated shop.

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
    """List coupon templates for the authenticated shop.

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
    """Query inventory information for products.

    Args:
        product_id: Optional product ID filter.
        sku_id: Optional SKU ID filter.
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
    """Query bill list by time range.

    Args:
        start_time: Bill start time, e.g. "2024-01-01 00:00:00"
        end_time: Bill end time, e.g. "2024-01-31 23:59:59"
        bill_type: Bill type filter. Common values:
            1 (订单结算), 2 (退款), 3 (佣金), 4 (保证金).
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
