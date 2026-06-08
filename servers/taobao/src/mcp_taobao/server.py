"""Taobao (淘宝) MCP server — provides tools for reading merchant orders, products, shop info, and more.

Auth via env vars: TAOBAO_APP_KEY, TAOBAO_APP_SECRET, TAOBAO_ACCESS_TOKEN.
API endpoint: https://eco.taobao.com/router/rest
Sign method: MD5 (secret + sorted_kv_string + secret → MD5 → uppercase)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# Let the server find the shared base class at <repo-root>/shared/
_project_root = Path(__file__).resolve().parents[4]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from shared.cn_commerce_base import CommerceMCPBase, CommerceAPIError, SignMethod


# ── Taobao client ───────────────────────────────────────────────────────────────

class TaobaoMCP(CommerceMCPBase):
    """Taobao Open Platform (TOP) client.

    Signs with MD5 (not HMAC-MD5). All parameters (system + business) go
    together as query-string params in a POST to the single router endpoint.
    """

    BASE_URL = "https://eco.taobao.com/router/rest"
    sign_method = SignMethod.MD5

    async def _call(self, api_method: str, biz_params: dict | None = None) -> dict:
        """Make a Taobao API call.

        Merges system params (method, format, v) with business params and
        sends everything through _request as query-string parameters.

        Returns the API response dict, or an error_response dict on failure.
        """
        try:
            params: dict[str, str] = {
                "method": api_method,
                "format": "json",
                "v": "2.0",
            }
            if biz_params:
                params.update(biz_params)
            return await self._request("POST", "", params=params)
        except CommerceAPIError as e:
            return {"error_response": {"code": e.code, "msg": e.msg}}
        except Exception as e:
            return {"error_response": {"code": -1, "msg": str(e)}}


# ── Instantiate client from env ────────────────────────────────────────────────

taobao = TaobaoMCP(
    app_key=os.environ.get("TAOBAO_APP_KEY", ""),
    app_secret=os.environ.get("TAOBAO_APP_SECRET", ""),
    access_token=os.environ.get("TAOBAO_ACCESS_TOKEN", ""),
)


# ── MCP server ─────────────────────────────────────────────────────────────────

mcp = FastMCP("mcp-cn-taobao")


# ═══════════════════════════════════════════════════════════════════════════════════
# 订单 (Orders)
# ═══════════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_order_list(
    start_time: str,
    end_time: str,
    status: str = "",
    page: int = 1,
    page_size: int = 20,
) -> str:
    """Query order list by time range and optional status.

    Args:
        start_time: Order start time, e.g. "2024-01-01 00:00:00"
        end_time: Order end time, e.g. "2024-01-31 23:59:59"
        status: Order status filter. Common values:
            WAIT_BUYER_PAY (waiting for payment),
            WAIT_SELLER_SEND_GOODS (waiting for shipment),
            WAIT_BUYER_CONFIRM_GOODS (shipped, waiting confirm),
            TRADE_FINISHED (completed),
            TRADE_CLOSED (closed).
            Empty string means all statuses.
        page: Page number, starting from 1.
        page_size: Number of orders per page (max 100).
    """
    biz_params: dict[str, str] = {
        "start_created": start_time,
        "end_created": end_time,
        "page_no": str(page),
        "page_size": str(page_size),
    }
    if status:
        biz_params["status"] = status

    result = await taobao._call("taobao.trades.sold.get", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_order_detail(tid: str) -> str:
    """Get full details of a single order.

    Args:
        tid: The Taobao trade ID (e.g. "123456789012345678").
    """
    biz_params = {"tid": tid}
    result = await taobao._call("taobao.trade.fullinfo.get", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_increment_orders(
    start_time: str,
    end_time: str,
    page: int = 1,
    page_size: int = 20,
) -> str:
    """Query incrementally modified orders by time range.

    Useful for syncing order changes (status updates, modifications).

    Args:
        start_time: Modification start time, e.g. "2024-01-01 00:00:00"
        end_time: Modification end time, e.g. "2024-01-31 23:59:59"
        page: Page number, starting from 1.
        page_size: Number of orders per page (max 100).
    """
    biz_params: dict[str, str] = {
        "start_modified": start_time,
        "end_modified": end_time,
        "page_no": str(page),
        "page_size": str(page_size),
    }

    result = await taobao._call("taobao.trades.sold.increment.get", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════════
# 商品 (Products)
# ═══════════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_product_list(
    page: int = 1,
    page_size: int = 20,
    status: str = "",
) -> str:
    """Get on-sale product (item) list with stock and price info.

    Args:
        page: Page number, starting from 1.
        page_size: Number of products per page (max 200).
        status: Product status filter. Empty for all.
            Common values: "onsale" (on sale), "instock" (in stock/off shelf).
    """
    biz_params: dict[str, str] = {
        "page_no": str(page),
        "page_size": str(page_size),
    }
    if status:
        biz_params["status"] = status

    result = await taobao._call("taobao.items.onsale.get", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_product_detail(num_iid: str) -> str:
    """Get full details of a single product by item ID.

    Args:
        num_iid: The Taobao item ID (num_iid, e.g. "12345678901").
    """
    biz_params = {"num_iid": num_iid}
    result = await taobao._call("taobao.item.get", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════════
# 售后 (After-Sale)
# ═══════════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_refund_list(
    start_time: str,
    end_time: str,
    status: str = "",
    page: int = 1,
    page_size: int = 20,
) -> str:
    """Query refund/return list by time range and optional status.

    Args:
        start_time: Query start time, e.g. "2024-01-01 00:00:00"
        end_time: Query end time, e.g. "2024-01-31 23:59:59"
        status: Refund status filter. Common values:
            WAIT_SELLER_AGREE (waiting for seller approval),
            WAIT_BUYER_RETURN_GOODS (waiting for buyer to return goods),
            WAIT_SELLER_CONFIRM_GOODS (waiting for seller to confirm receipt),
            SUCCESS (completed),
            CLOSED (closed).
            Empty string means all statuses.
        page: Page number, starting from 1.
        page_size: Number of records per page (max 100).
    """
    biz_params: dict[str, str] = {
        "start_modified": start_time,
        "end_modified": end_time,
        "page_no": str(page),
        "page_size": str(page_size),
    }
    if status:
        biz_params["status"] = status

    result = await taobao._call("taobao.refunds.receive.get", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_refund_detail(refund_id: str) -> str:
    """Get full details of a single refund/return record.

    Args:
        refund_id: The refund record ID (e.g. "RF12345678901").
    """
    biz_params = {"refund_id": refund_id}
    result = await taobao._call("taobao.refund.get", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════════
# 物流 (Logistics)
# ═══════════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_logistics_tracking(tid: str) -> str:
    """Get logistics tracking information for an order.

    Args:
        tid: The Taobao trade ID (e.g. "123456789012345678").
    """
    biz_params = {"tid": tid}
    result = await taobao._call("taobao.logistics.trace.search", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════════
# 评价 (Reviews)
# ═══════════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_review_list(
    num_iid: str,
    page: int = 1,
    page_size: int = 20,
) -> str:
    """Query product review (rate/comment) list.

    Args:
        num_iid: The Taobao item ID (e.g. "12345678901").
        page: Page number, starting from 1.
        page_size: Number of reviews per page (max 200).
    """
    biz_params = {
        "num_iid": num_iid,
        "page_no": str(page),
        "page_size": str(page_size),
    }

    result = await taobao._call("taobao.traderates.get", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════════
# 店铺 (Shop)
# ═══════════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_shop_info(nick: str = "") -> str:
    """Get shop basic information.

    Args:
        nick: Taobao seller nick (shop identifier). Leave empty to use the authenticated seller's shop.
    """
    biz_params: dict[str, str] = {}
    if nick:
        biz_params["nick"] = nick

    result = await taobao._call("taobao.shop.get", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_seller_info() -> str:
    """Get authenticated seller (user) information including seller credit and profile."""
    result = await taobao._call("taobao.user.seller.get", {})
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════════
# 营销 (Marketing)
# ═══════════════════════════════════════════════════════════════════════════════════


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
    biz_params: dict[str, str] = {
        "page_no": str(page),
        "page_size": str(page_size),
    }
    if status:
        biz_params["status"] = status

    result = await taobao._call(
        "taobao.promotionmisc.activity.range.list.get", biz_params
    )
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════════
# 类目 (Categories)
# ═══════════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def list_categories(parent_cid: str = "0") -> str:
    """List product categories under a given parent category.

    Args:
        parent_cid: Parent category ID. Use "0" (default) to list top-level categories.
    """
    biz_params = {"parent_cid": parent_cid}

    result = await taobao._call("taobao.itemcats.get", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════════


def main() -> None:
    """Entry point for 'mcp-cn-taobao' console script."""
    mcp.run()


if __name__ == "__main__":
    main()
