"""Explicit platform transport; importing this module does not load credentials."""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime, timedelta, timezone

from shared.cn_commerce_base import (
    DEFAULT_RETRY,
    CommerceAPIError,
    CommerceMCPBase,
    ConfigValidationError,
    SignMethod,
)


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
