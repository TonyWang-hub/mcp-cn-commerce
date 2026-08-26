"""Pinduoduo (拼多多) MCP server — provides tools for reading merchant orders,
products, shop info, after-sale, logistics and marketing data.

Auth via env vars: PINDUODUO_CLIENT_ID, PINDUODUO_CLIENT_SECRET, PINDUODUO_ACCESS_TOKEN.
API endpoint: https://gw-api.pinduoduo.com/api/router
Sign method: MD5 (params sorted, secret+string+secret → MD5 → uppercase)

Contract declaration (official sources, open items, platform-side constraints):
``docs/api-contracts/pinduoduo.md``.

Scope note: this server speaks the *merchant* (商家 / ISV) API only. Affiliate
selection (多多进宝 / 多多客, ``pdd.ddk.*``) needs a different developer
identity and app type, so it cannot share this connector's access_token — see
the contract declaration for details.
"""

from __future__ import annotations

import json
import os
import time

import httpx
from mcp.server.mcpserver import MCPServer

from shared.cn_commerce_base import (
    CommerceAPIError,
    CommerceMCPBase,
    ConfigValidationError,
    SignMethod,
    register_common_tools,
)

# ── Pinduoduo client ────────────────────────────────────────────────────────


class PinduoduoMCP(CommerceMCPBase):
    """Pinduoduo-specific client.

    PDD uses 'type' param for the API method name, 'client_id' for app key,
    and sends all params as POST form data to a single router endpoint.
    Signing is standard MD5 (provided by the base class).
    """

    BASE_URL = "https://gw-api.pinduoduo.com/api/router"
    sign_method = SignMethod.MD5

    async def _call(self, api_type: str, biz_params: dict | None = None) -> dict:
        """Make a PDD API call.

        Builds system params (type, client_id, timestamp, data_type,
        access_token), merges business params, signs with MD5, and POSTs
        as form data.
        """
        params: dict[str, str] = {
            "type": api_type,
            "client_id": self.app_key,
            # UNIX seconds, 10 digits. The official parameter table says
            # 「UNIX时间（秒）」 with example 1480411125; tolerance is 10 minutes,
            # and pdd.time.get is offered for clock alignment. Milliseconds land
            # ~45000 years in the future and are rejected outright.
            "timestamp": str(int(time.time())),
            "data_type": "JSON",
        }
        if self.access_token:
            params["access_token"] = self.access_token

        # Merge business params (convert all values to strings)
        if biz_params:
            for k, v in biz_params.items():
                params[k] = str(v)

        # Sign (base-class MD5: secret + sorted_kv + secret → md5 → upper)
        params["sign"] = self._sign(params)

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(self.BASE_URL, data=params)

        result = resp.json()
        if "error_response" in result:
            raise CommerceAPIError(
                code=result["error_response"].get("error_code", result["error_response"].get("code", -1)),
                msg=result["error_response"].get("error_msg", result["error_response"].get("msg", "unknown")),
            )
        return result


# ── Instantiate client from env ────────────────────────────────────────────


def _create_pinduoduo_client() -> PinduoduoMCP:
    """Create pinduoduo client with configuration validation."""
    try:
        return PinduoduoMCP.from_env("PINDUODUO", ["CLIENT_ID", "CLIENT_SECRET", "ACCESS_TOKEN"])
    except ConfigValidationError:
        # Fallback to direct instantiation for backward compatibility
        return PinduoduoMCP(
            app_key=os.environ.get("PINDUODUO_CLIENT_ID", ""),
            app_secret=os.environ.get("PINDUODUO_CLIENT_SECRET", ""),
            access_token=os.environ.get("PINDUODUO_ACCESS_TOKEN", ""),
        )


pdd = _create_pinduoduo_client()


# ── MCP server ─────────────────────────────────────────────────────────────

mcp = MCPServer("mcp-cn-pinduoduo")


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
        "start_created_at": start_time,
        "end_created_at": end_time,
        "page": str(page),
        "page_size": str(page_size),
    }
    if order_status:
        biz_params["order_status"] = order_status

    result = await pdd._call("pdd.order.list.get", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_order_detail(order_sn: str) -> str:
    """Get full details of a single order.

    Args:
        order_sn: The PDD order serial number (e.g. "231215-1234567890123").
    """
    biz_params = {"order_sn": order_sn}
    result = await pdd._call("pdd.order.information.get", biz_params)
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
    result = await pdd._call("pdd.goods.list.get", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_product_detail(goods_id: str) -> str:
    """Get full details of a single product by goods ID.

    Args:
        goods_id: The PDD goods ID (e.g. "123456789").
    """
    biz_params = {"goods_id": goods_id}
    result = await pdd._call("pdd.goods.detail.get", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# NOTE: no platform-wide product search tool exists here on purpose. The
# merchant API has no "search all of Pinduoduo" capability — pdd.goods.list.get
# lists only the authenticated merchant's own goods. See the "Removed tools"
# section of docs/api-contracts/pinduoduo.md.


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
    """Query refund (after-sale) list by time range.

    Backed by the incremental after-sale interface; its business parameter names
    are not yet confirmed against the official table (open item in
    docs/api-contracts/pinduoduo.md).

    Args:
        start_time: Query start time, e.g. "2024-01-01 00:00:00"
        end_time: Query end time, e.g. "2024-01-31 23:59:59"
        page: Page number, starting from 1.
        page_size: Number of records per page (max 100).
    """
    biz_params = {
        "start_created_at": start_time,
        "end_created_at": end_time,
        "page": str(page),
        "page_size": str(page_size),
    }
    result = await pdd._call("pdd.refund.list.increment.get", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_refund_detail(refund_id: str) -> str:
    """Get full details of a single refund record.

    Args:
        refund_id: The refund/after-sale record ID (e.g. "RF123456789").
    """
    biz_params = {"refund_id": refund_id}
    result = await pdd._call("pdd.refund.information.get", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 物流 (Logistics)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_logistics_tracking(order_sn: str) -> str:
    """Get logistics tracking information for an order.

    The business parameter names of the order-trace interface are not yet
    confirmed against the official table (open item in
    docs/api-contracts/pinduoduo.md).

    Args:
        order_sn: The PDD order serial number (e.g. "231215-1234567890123").
    """
    biz_params = {"order_sn": order_sn}
    result = await pdd._call("pdd.logistics.ordertrace.get", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def list_logistics_companies() -> str:
    """List all available logistics companies on Pinduoduo platform."""
    result = await pdd._call("pdd.logistics.companies.get", {})
    return json.dumps(result, ensure_ascii=False, indent=2)


# NOTE: no product-review tool exists here on purpose. Pinduoduo has never
# opened a review/comment API to third parties: zero hits for
# comment/review/评价/评论 across the 493 live interfaces and 344 announcements.
# See the "Removed tools" section of docs/api-contracts/pinduoduo.md.


# ═══════════════════════════════════════════════════════════════════════════════
# 店铺 (Shop)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_shop_info() -> str:
    """Get mall/shop basic information for the authenticated merchant."""
    result = await pdd._call("pdd.mall.info.get", {})
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 营销 (Marketing)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def list_promotions(
    page: int = 1,
    page_size: int = 20,
) -> str:
    """List the authenticated shop's coupon (店铺券) batches.

    Pinduoduo has no single "all promotions" interface; shop-level coupon
    batches are the closest published equivalent. The business parameter names
    for this interface are not yet confirmed against the official table — see
    the open items in docs/api-contracts/pinduoduo.md.

    Args:
        page: Page number, starting from 1.
        page_size: Number of records per page (max 100).
    """
    biz_params = {
        "page": str(page),
        "page_size": str(page_size),
    }
    result = await pdd._call("pdd.promotion.merchant.coupon.list.get", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# NOTE: affiliate (多多进宝 / 多多客, pdd.ddk.*) selection tools were moved out of
# this server. They belong to a separate identity system — 推手 role +
# 多多客联盟类 app type + client_id ↔ 多多进宝账号 binding — so a merchant ISV
# access_token cannot carry that permission. See the "Moved out" section of
# docs/api-contracts/pinduoduo.md.


# ── Cross-platform operational tools (get_metrics/get_traces/get_alerts/export_data) ──
register_common_tools(mcp, pdd)


# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════


def main() -> None:
    """Entry point for 'mcp-cn-pinduoduo' console script."""
    mcp.run()


if __name__ == "__main__":
    main()
