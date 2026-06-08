"""Kuaishou (快手) MCP server — provides tools for reading merchant orders,
products, shop info, after-sale, logistics, reviews, marketing, and coupons.

Auth via env vars: KUAISHOU_APP_KEY, KUAISHOU_APP_SECRET, KUAISHOU_SIGN_SECRET, KUAISHOU_ACCESS_TOKEN.
API endpoint: https://openapi.kwaixiaodian.com
Sign method: MD5 (params sorted, sign_secret+string+sign_secret → MD5 → uppercase)
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

# Let the server find the shared base class at <repo-root>/shared/
_project_root = Path(__file__).resolve().parents[4]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from shared.cn_commerce_base import CommerceMCPBase, CommerceAPIError, SignMethod


# ── Kuaishou client ───────────────────────────────────────────────────────────

class KuaishouMCP(CommerceMCPBase):
    """Kuaishou-specific client.

    Kuaishou uses a separate `sign_secret` for request signing (distinct from
    `app_secret`).  The base class MD5 signing is overridden to use
    `sign_secret` in the canonical format:
        sign_secret + sorted(k+v) + sign_secret  →  MD5  →  uppercase.

    API calls are made via GET to individual REST paths under BASE_URL.
    """

    BASE_URL = "https://openapi.kwaixiaodian.com"
    sign_method = SignMethod.MD5

    def __init__(
        self,
        app_key: str = "",
        app_secret: str = "",
        sign_secret: str = "",
        access_token: str = "",
    ):
        super().__init__(
            app_key=app_key,
            app_secret=app_secret,
            access_token=access_token,
        )
        self.sign_secret = sign_secret

    # ── Override signing to use sign_secret ───────────────────────────────

    def _sign(self, params: dict) -> str:
        """Generate MD5 signature using sign_secret."""

        to_sign = {
            k: v
            for k, v in params.items()
            if k not in ("sign", "sign_method") and v != ""
        }
        sorted_keys = sorted(to_sign.keys())
        raw = (
            self.sign_secret
            + "".join(f"{k}{to_sign[k]}" for k in sorted_keys)
            + self.sign_secret
        )
        return hashlib.md5(raw.encode()).hexdigest().upper()

    # ── Convenience wrapper ───────────────────────────────────────────────

    async def _call(self, path: str, params: dict | None = None) -> dict[str, Any]:
        """Make a signed GET request to a Kuaishou API path."""
        return await self._request("GET", path, params=params)


# ── Instantiate client from env ───────────────────────────────────────────────

ks = KuaishouMCP(
    app_key=os.environ.get("KUAISHOU_APP_KEY", ""),
    app_secret=os.environ.get("KUAISHOU_APP_SECRET", ""),
    sign_secret=os.environ.get("KUAISHOU_SIGN_SECRET", ""),
    access_token=os.environ.get("KUAISHOU_ACCESS_TOKEN", ""),
)


# ── MCP server ────────────────────────────────────────────────────────────────

mcp = FastMCP("mcp-cn-kuaishou")


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
    params: dict = {
        "start_time": start_time,
        "end_time": end_time,
        "page": str(page),
        "page_size": str(page_size),
    }
    if order_status:
        params["order_status"] = order_status

    result = await ks._call("/open/api/order/list", params)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_order_detail(order_id: str) -> str:
    """Get full details of a single order.

    Args:
        order_id: The Kuaishou order ID (e.g. "KS202401150000001").
    """
    params = {"order_id": order_id}
    result = await ks._call("/open/api/order/detail", params)
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
) -> str:
    """Query refund (after-sale) list by time range.

    Args:
        start_time: Query start time, e.g. "2024-01-01 00:00:00"
        end_time: Query end time, e.g. "2024-01-31 23:59:59"
        refund_status: Status filter. Common values:
            1 (退款中), 2 (退款成功), 3 (退款失败).
            Empty string means all statuses.
        page: Page number, starting from 1.
        page_size: Number of records per page (max 100).
    """
    params: dict = {
        "start_time": start_time,
        "end_time": end_time,
        "page": str(page),
        "page_size": str(page_size),
    }
    if refund_status:
        params["refund_status"] = refund_status

    result = await ks._call("/open/api/refund/list", params)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_refund_detail(refund_id: str) -> str:
    """Get full details of a single refund record.

    Args:
        refund_id: The refund/after-sale record ID (e.g. "RF123456789").
    """
    params = {"refund_id": refund_id}
    result = await ks._call("/open/api/refund/detail", params)
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
    """Get shop/mall basic information for the authenticated merchant."""
    result = await ks._call("/open/api/shop/info")
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


# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════


def main() -> None:
    """Entry point for 'mcp-cn-kuaishou' console script."""
    mcp.run()


if __name__ == "__main__":
    main()
