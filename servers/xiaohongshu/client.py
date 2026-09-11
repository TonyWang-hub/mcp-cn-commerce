"""Explicit platform transport; importing this module does not load credentials."""

from __future__ import annotations

import hashlib
import re
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

    @staticmethod
    def _integer(value, field: str) -> int:
        """Read a native nonnegative Long without guessing its time unit."""
        if type(value) is int:
            number = value
        elif isinstance(value, str) and re.fullmatch(r"[0-9]+", value.strip()):
            number = int(value.strip())
        else:
            raise ValueError(f"{field} must be a native integer")
        if not 0 <= number <= 2**63 - 1:
            raise ValueError(f"{field} must be a nonnegative signed 64-bit integer")
        return number

    @staticmethod
    def _fields(params: dict, aliases: dict[str, str]) -> dict:
        """Resolve only the documented read fields; duplicates are ambiguous."""
        if set(params) - (set(aliases) | set(aliases.values())):
            raise ValueError("Unsupported Xiaohongshu business parameter")
        result = {}
        for native, alias in aliases.items():
            if native in params and alias in params:
                raise ValueError(f"Specify only one of {native} and {alias}")
            if native in params or alias in params:
                result[native] = params[native] if native in params else params[alias]
        return result

    @staticmethod
    def _identifier(value, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be a nonempty string")
        return value

    @classmethod
    def _refund_time(cls, value, field: str, *, allow_iso: bool) -> int:
        # Only refund query fields explicitly document milliseconds. Numeric
        # values already use native units, including dates close to the epoch.
        if allow_iso and isinstance(value, str) and not re.fullmatch(r"[0-9]+", value.strip()):
            try:
                dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            except ValueError:
                raise ValueError(f"{field} must be milliseconds or timezone-aware ISO time") from None
            if dt.tzinfo is None:
                raise ValueError(f"{field} ISO time must include a timezone")
            delta = dt - datetime(1970, 1, 1, tzinfo=UTC)
            value = (delta.days * 86400 + delta.seconds) * 1000 + delta.microseconds // 1000
        return cls._integer(value, field)

    @classmethod
    def _adapt_order_refund(cls, path: str, params: dict) -> tuple[str, dict]:
        if path in {"/api/order/detail", "/api/refund/detail"}:
            refund = path == "/api/refund/detail"
            field, alias = ("returnsId", "refund_id") if refund else ("orderId", "order_id")
            values = cls._fields(params, {field: alias})
            value = cls._identifier(values.get(field), field)
            method = "afterSale.getAfterSaleInfo" if refund else "order.getOrderDetail"
            return method, {field: value}

        refund = path == "/api/refund/list"
        aliases = {
            "startTime": "start_time",
            "endTime": "end_time",
            "timeType": "time_type",
            "pageNo": "page",
            "pageSize": "page_size",
        }
        aliases.update(
            {"orderId": "order_id", "statuses": "refund_status", "returnTypes": "return_types"}
            if refund
            else {"orderStatus": "order_status", "orderType": "order_type"}
        )
        values = cls._fields(params, aliases)
        page = cls._integer(values.get("pageNo", 1), "pageNo")
        size = cls._integer(values.get("pageSize", 20), "pageSize")
        if page < 1 or not 1 <= size <= 100:
            raise ValueError("pageNo must be positive and pageSize must be between 1 and 100")
        if refund and page * size > 50000:
            raise ValueError("The official after-sale API caps pageNo * pageSize at 50000")
        if not refund and page > 100:
            raise ValueError("The official order API caps pageNo at 100")
        result = {"pageNo": page, "pageSize": size}
        if refund and "orderId" in values:
            result["orderId"] = cls._identifier(values["orderId"], "orderId")
        has_time = any(field in values for field in ("startTime", "endTime", "timeType"))
        if not refund or has_time or "orderId" not in result:
            if "startTime" not in values or "endTime" not in values:
                raise ValueError("startTime and endTime are required for time queries")
            time_type = cls._integer(values.get("timeType", 1), "timeType")
            if time_type not in {1, 2}:
                raise ValueError("timeType must be 1 (creation) or 2 (update)")
            for field in ("startTime", "endTime"):
                result[field] = (
                    cls._refund_time(values[field], field, allow_iso=aliases[field] in params)
                    if refund
                    else cls._integer(values[field], field)
                )
            window = result["endTime"] - result["startTime"]
            if window <= 0:
                raise ValueError("endTime must be after startTime")
            if refund and window > (86_400_000 if time_type == 1 else 1_800_000):
                limit = "24 hours" if time_type == 1 else "30 minutes"
                raise ValueError(f"The official after-sale time range cannot exceed {limit}")
            # Order query units are unconfirmed. Its official 24h/30min limits
            # cannot be converted to numeric deltas without inventing a unit.
            result["timeType"] = time_type
        filters = (
            {"statuses": {1, 2, 3, 4, 5, 6, 9, 9001, 12, 13, 14}, "returnTypes": {1, 2, 4, 5, 6}} if refund else {}
        )
        for field, allowed in filters.items():
            if field not in values or (aliases[field] in params and values[field] == ""):
                continue
            entries = values[field]
            if aliases[field] in params and isinstance(entries, str):
                entries = entries.split(",")
            if not isinstance(entries, list):
                raise ValueError(f"{field} must be a list of official status/type integers")
            result[field] = [cls._integer(entry, field) for entry in entries]
            if any(entry not in allowed for entry in result[field]):
                raise ValueError(f"{field} contains an unsupported official status/type")
        if not refund:
            for field, maximum in (("orderStatus", 10), ("orderType", 5)):
                if field not in values or (aliases[field] in params and values[field] == ""):
                    continue
                result[field] = cls._integer(values[field], field)
                if result[field] > maximum:
                    raise ValueError(f"{field} must be between 0 and {maximum}")
        return ("afterSale.listAfterSaleInfos" if refund else "order.getOrderList"), result

    @staticmethod
    def _check_envelope(result) -> None:
        message = "Xiaohongshu API response failed or has an unverified envelope"
        if not isinstance(result, dict):
            raise CommerceAPIError(code=-1, msg=message)
        codes = []
        for field in ("error_code", "code"):
            if field not in result:
                continue
            value = result[field]
            if type(value) is int and -(2**31) <= value < 2**31:
                codes.append(value)
            elif isinstance(value, str) and re.fullmatch(r"-?[0-9]{1,10}", value):
                number = int(value)
                codes.append(number if -(2**31) <= number < 2**31 else -1)
            else:
                codes.append(-1)
        if (
            "error_response" in result
            or result.get("success") is not True
            or not codes
            or any(code != 0 for code in codes)
            or not isinstance(result.get("data"), dict)
        ):
            raise CommerceAPIError(code=next((code for code in codes if code != 0), -1), msg=message)

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
        if path in {"/api/order/list", "/api/order/detail", "/api/refund/list", "/api/refund/detail"}:
            return cls._adapt_order_refund(path, params)
        direct = {
            "/api/logistics/tracking": ("order.getOrderTracking", "order_id", "orderId"),
            "/api/product/detail": ("product.getItemInfo", "product_id", "itemId"),
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
        if path not in {"/api/product/list", "/api/bill/list"}:
            raise CommerceAPIError(code=-2, msg=f"Unsupported Xiaohongshu API alias: {path}")
        page = int(params.get("page", 1))
        size = int(params.get("page_size", 20))
        if page < 1 or not 1 <= size <= 100:
            raise ValueError("page must be positive and page_size must be between 1 and 100")
        if path == "/api/product/list":
            return "product.searchItemList", {"pageNo": page, "pageSize": size, "searchParam": {}}
        start = cls._timestamp(params["start_time"], milliseconds=True)
        end = cls._timestamp(params["end_time"], milliseconds=True)
        if end <= start:
            raise ValueError("end_time must be after start_time")
        result = {"startTime": start, "endTime": end, "pageNo": page, "pageSize": size}
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
            self._check_envelope(result)
            # common_controller wraps the new after-sale response schema in
            # another success/error_code/data envelope. Validate both levels,
            # preserving the original response shape for SDK callers.
            if api_method.startswith("afterSale.") and any(
                field in result["data"] for field in ("success", "code", "error_code", "error_response")
            ):
                self._check_envelope(result["data"])
            return result

        return await self._send_request(
            "POST",
            self.BASE_URL,
            endpoint=api_method,
            prepare_request=prepare_request,
            retry_config=DEFAULT_RETRY,
            parse_response=parse_response,
        )
