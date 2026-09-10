"""Taobao (淘宝) MCP server — provides tools for reading merchant orders, products, shop info, and more.

Auth via env vars: TAOBAO_APP_KEY, TAOBAO_APP_SECRET, TAOBAO_ACCESS_TOKEN.
API endpoint: https://eco.taobao.com/router/rest
Sign method: MD5 (secret + sorted_kv_string + secret → MD5 → uppercase)
"""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from mcp.server.mcpserver import MCPServer

from shared.cn_commerce_base import (
    DEFAULT_RETRY,
    CommerceAPIError,
    CommerceMCPBase,
    ConfigValidationError,
    SignMethod,
    canonicalize_sign_value,
    register_common_tools,
)

# ── Taobao client ───────────────────────────────────────────────────────────────


class TaobaoMCP(CommerceMCPBase):
    """Taobao Open Platform (TOP) client.

    Signs with MD5 (not HMAC-MD5). All parameters (system + business) go
    together as query-string params in a POST to the single router endpoint.
    """

    PLATFORM = "TAOBAO"
    BASE_URL = "https://eco.taobao.com/router/rest"
    sign_method = SignMethod.MD5

    async def _call(self, api_method: str, biz_params: dict | None = None) -> dict:
        """Make a Taobao API call.

        Merges system params (method, format, v) with business params and
        sends everything through _request as query-string parameters.

        Returns the API response dict, or an error_response dict on failure.
        """
        missing = [
            name
            for name, value in (
                ("TAOBAO_APP_KEY", self.app_key),
                ("TAOBAO_APP_SECRET", self.app_secret),
                ("TAOBAO_ACCESS_TOKEN", self.access_token),
            )
            if not value
        ]
        if missing:
            raise ConfigValidationError("TAOBAO", missing)
        params = {"method": api_method, "format": "json", "v": "2.0", **(biz_params or {})}
        return await self._request("POST", "", params=params, retry_config=DEFAULT_RETRY)

    def _sign(self, params: dict) -> str:
        """TOP signs all nonempty fields except sign, including sign_method."""
        raw = (
            self.app_secret
            + "".join(
                key + canonicalize_sign_value(value)
                for key, value in sorted(params.items())
                if key != "sign" and value != ""
            )
            + self.app_secret
        )
        return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()

    async def _request(self, method, path, params=None, data=None, retry_config=None):
        """TOP uses seller session and GMT+8 timestamps, not generic auth."""
        business = {**(params or {}), **(data or {})}
        if self.validate_input:
            self._validate_params(business)

        def prepare():
            signed = {key: canonicalize_sign_value(value) for key, value in business.items()}
            signed.update(
                app_key=self.app_key,
                session=self.access_token,
                timestamp=datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S"),
                sign_method="md5",
            )
            signed["sign"] = self._sign(signed)
            return {"params": signed}

        def parse(payload):
            if not isinstance(payload, dict):
                raise ValueError("Expected a JSON object from TOP")
            if "error_response" in payload:
                error = payload["error_response"]
                raise CommerceAPIError(error.get("code", -1), error.get("msg", "unknown"))
            return payload

        return await self._send_request(
            method,
            self.BASE_URL + path,
            endpoint=business.get("method", path),
            prepare_request=prepare,
            parse_response=parse,
            retry_config=retry_config,
        )


# ── Instantiate client from env ────────────────────────────────────────────────


def _create_taobao_client() -> TaobaoMCP:
    """Create Taobao client with configuration validation."""
    try:
        return TaobaoMCP.from_env("TAOBAO", ["APP_KEY", "APP_SECRET", "ACCESS_TOKEN"])
    except ConfigValidationError:
        # Fallback to direct instantiation for backward compatibility
        return TaobaoMCP(
            app_key=os.environ.get("TAOBAO_APP_KEY", ""),
            app_secret=os.environ.get("TAOBAO_APP_SECRET", ""),
            access_token=os.environ.get("TAOBAO_ACCESS_TOKEN", ""),
        )


taobao = _create_taobao_client()


# ── MCP server ─────────────────────────────────────────────────────────────────


@asynccontextmanager
async def _lifespan(_server):
    try:
        yield {}
    finally:
        client = taobao
        if client is not None:
            await client.close()


mcp = MCPServer("mcp-cn-taobao", lifespan=_lifespan)


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

    result = await taobao._call("taobao.promotionmisc.activity.range.list.get", biz_params)
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


# ── Cross-platform operational tools (get_metrics/get_traces/get_alerts/export_data) ──
register_common_tools(mcp, taobao)


# ═══════════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════════


def main() -> None:
    """Entry point for 'mcp-cn-taobao' console script."""
    mcp.run()


if __name__ == "__main__":
    main()
