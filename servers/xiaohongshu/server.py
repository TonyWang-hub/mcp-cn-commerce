"""Xiaohongshu (小红书) MCP server — provides tools for reading merchant orders,
products, shop info, after-sale, logistics, reviews, marketing, inventory, and billing data.

Auth via env vars: XHS_CLIENT_ID, XHS_CLIENT_SECRET, XHS_ACCESS_TOKEN.
API endpoint: https://ark.xiaohongshu.com/ark/open_api/v3/common_controller
Sign method: official OAuth v2 system-field MD5 (lowercase)
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta, timezone

from mcp.server.mcpserver import MCPServer

from shared.cn_commerce_base import (
    DEFAULT_RETRY,
    CommerceAPIError,
    CommerceMCPBase,
    ConfigValidationError,
    SignMethod,
    register_common_tools,
)

# ── Xiaohongshu client ────────────────────────────────────────────────────────


class XiaohongshuMCP(CommerceMCPBase):
    """Official OAuth adapter; old internal paths are local compatibility aliases.

    Protocol: https://open.xiaohongshu.com/document/developer/file/39 and /40.
    Existing XHS_CLIENT_ID / CLIENT_SECRET variables hold appId / appSecret.
    """

    PLATFORM = "XHS"
    BASE_URL = "https://ark.xiaohongshu.com/ark/open_api/v3/common_controller"
    sign_method = SignMethod.MD5

    def _sign(self, params: dict) -> str:
        # Official OAuth v2 protocol signs only these system fields, never
        # accessToken or business data. The digest is lower-case hexadecimal.
        raw = (
            f"{params['method']}?appId={params['appId']}"
            f"&timestamp={params['timestamp']}&version={params['version']}{self.app_secret}"
        )
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _timestamp(value: str, *, milliseconds: bool = False) -> int:
        text = str(value).strip()
        if text.lstrip("-").isdigit():
            number = int(text)
            millis = number if abs(number) >= 1_000_000_000_000 else number * 1000
        else:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone(timedelta(hours=8)))
            delta = dt - datetime(1970, 1, 1, tzinfo=UTC)
            millis = (delta.days * 86400 + delta.seconds) * 1000 + delta.microseconds // 1000
        return millis if milliseconds else millis // 1000

    @classmethod
    def _adapt_params(cls, path: str, params: dict) -> tuple[str, dict]:
        """Map compatibility aliases to verified read-only API schemas.

        Sources: https://open.xiaohongshu.com/api/doc/second/listNew and
        /api/doc/infoNew (official public documentation, checked 2026-09-10).
        Unknown aliases fail before any network request.
        """
        unsupported = {"/api/review/list", "/api/shop/info", "/api/promotion/list", "/api/coupon/list"}
        if path in unsupported:
            raise CommerceAPIError(
                code=-2,
                msg=f"Unsupported Xiaohongshu tool ({path}): no verified official API mapping; no request was sent.",
            )
        direct = {
            "/api/order/detail": ("order.getOrderDetail", "order_id", "orderId"),
            "/api/logistics/tracking": ("order.getOrderTracking", "order_id", "orderId"),
            "/api/product/detail": ("product.getItemInfo", "product_id", "itemId"),
            "/api/refund/detail": ("afterSale.getAfterSaleInfo", "refund_id", "returnsId"),
        }
        if path in direct:
            api, source, target = direct[path]
            if not params.get(source):
                raise ValueError(f"{source} is required")
            return api, {target: str(params[source])}
        if path == "/api/inventory/query":
            if not params.get("sku_id") or params.get("product_id"):
                raise ValueError("The official inventory API requires sku_id; product_id filtering is unsupported")
            if int(params.get("page", 1)) != 1:
                raise ValueError("The official inventory API returns one SKU and does not support pagination")
            return "inventory.getSkuStockV2", {"skuId": str(params["sku_id"])}
        if path not in {"/api/order/list", "/api/refund/list", "/api/product/list", "/api/bill/list"}:
            raise CommerceAPIError(code=-2, msg=f"Unsupported Xiaohongshu API alias: {path}")
        page = int(params.get("page", 1))
        size = int(params.get("page_size", 20))
        if page < 1 or not 1 <= size <= 100:
            raise ValueError("page must be positive and page_size must be between 1 and 100")
        if path == "/api/product/list":
            return "product.searchItemList", {"pageNo": page, "pageSize": size, "searchParam": {}}
        millis = path != "/api/order/list"
        start = cls._timestamp(params["start_time"], milliseconds=millis)
        end = cls._timestamp(params["end_time"], milliseconds=millis)
        if end <= start:
            raise ValueError("end_time must be after start_time")
        if path in {"/api/order/list", "/api/refund/list"} and end - start > 86400 * (1000 if millis else 1):
            raise ValueError("The official creation-time API supports at most 24 hours; split the requested range")
        result = {"startTime": start, "endTime": end, "pageNo": page, "pageSize": size}
        if path == "/api/order/list":
            if page > 100:
                raise ValueError("The official order API caps page at 100")
            result["timeType"] = 1
            if params.get("order_status"):
                status = int(params["order_status"])
                if not 0 <= status <= 10:
                    raise ValueError("order_status must be an official status code from 0 to 10")
                result["orderStatus"] = status
            return "order.getOrderList", result
        if path == "/api/refund/list":
            if page * size > 50000:
                raise ValueError("The official after-sale API caps page * page_size at 50000")
            result["timeType"] = 1
            if params.get("refund_status"):
                result["statuses"] = [int(value.strip()) for value in str(params["refund_status"]).split(",")]
            return "afterSale.listAfterSaleInfos", result
        result["pageNum"] = result.pop("pageNo")
        if params.get("bill_type"):
            valid = {
                "RECHARGE",
                "STATEMENT_IN",
                "STATEMENT_REFUND",
                "PAY_SUCCESS",
                "BOUNCE",
                "SELLER_FINE",
                "REFUND",
                "LOGISTIC_OUT",
                "MANUAL_ADJUST_STATEMENT",
                "TRANSFER_IN",
                "TRANSFER_OUT",
                "CUSTOMER_SERVICE_FEE",
                "MESSAGE_FEE",
                "INVOICE_SEND",
                "COMMISION_RETURN",
                "OTHER_IN",
                "OTHER_OUT",
            }
            types = [value.strip() for value in str(params["bill_type"]).split(",")]
            if any(value not in valid for value in types):
                raise ValueError(
                    "bill_type must contain official tradeTypes names, e.g. STATEMENT_IN or STATEMENT_REFUND"
                )
            result["tradeTypes"] = types
        return "finance.querySellerAccountRecords", result

    async def _call(self, method: str, path: str, biz_params: dict | None = None) -> dict:
        """Translate a legacy local alias and POST the verified official contract."""
        missing = [
            name
            for name, value in (
                ("XHS_CLIENT_ID", self.app_key),
                ("XHS_CLIENT_SECRET", self.app_secret),
                ("XHS_ACCESS_TOKEN", self.access_token),
            )
            if not value
        ]
        if missing:
            raise ConfigValidationError("XHS", missing)
        if method.upper() not in {"GET", "POST"}:
            raise ValueError("Only read-only API aliases are supported")
        api_method, business = self._adapt_params(path, biz_params or {})
        if self.validate_input:
            self._validate_params(business)

        def prepare_request():
            payload = {
                **business,
                "appId": self.app_key,
                "method": api_method,
                "timestamp": str(int(time.time())),
                "version": "2.0",
                "accessToken": self.access_token,
            }
            payload["sign"] = self._sign(payload)
            return {"json": payload, "headers": {"Content-Type": "application/json;charset=utf-8"}}

        def parse_response(result):
            if "error_response" in result:
                error = result["error_response"]
                raise CommerceAPIError(
                    code=error.get("code", error.get("error_code", -1)),
                    msg=error.get("msg", error.get("error_msg", "unknown")),
                )
            if result.get("success") is False or str(result.get("error_code", result.get("code", 0))) != "0":
                raise CommerceAPIError(
                    code=result.get("error_code", result.get("code", -1)),
                    msg=result.get("error_msg", result.get("msg", "unknown")),
                )
            return result

        return await self._send_request(
            "POST",
            self.BASE_URL,
            endpoint=api_method,
            prepare_request=prepare_request,
            retry_config=DEFAULT_RETRY,
            parse_response=parse_response,
        )


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
) -> str:
    """Query orders by creation time (maximum 24-hour range, Asia/Shanghai).

    Args:
        start_time: Order start time, e.g. "2024-01-01 00:00:00"
        end_time: Order end time, e.g. "2024-01-31 23:59:59"
        order_status: Status filter. Common values:
            1 (待付款), 2 (处理中), 3 (清关中), 4 (待发货), 5 (部分发货),
            6 (待收货), 7 (已完成), 8 (已关闭), 9 (已取消), 10 (换货申请中).
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
    """Query after-sales by creation time (maximum 24-hour range, Asia/Shanghai).

    Args:
        start_time: Query start time, e.g. "2024-01-01 00:00:00"
        end_time: Query end time, e.g. "2024-01-31 23:59:59"
        refund_status: Status filter. Common values:
            1 (待审核), 2 (待寄回), 3 (待收货), 4 (已完成), 5 (已取消),
            6 (已关闭), 9 (审核拒绝); comma-separated official status codes are accepted.
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
