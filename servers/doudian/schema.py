"""Order/after-sale contracts read from official documentation on 2026-09-10.

The SDK uses native fields. MCP helpers translate their user-facing date strings
and retain distinct platform-payment, buyer-payment and refund amount semantics.
See docs/doudian-contract.md for versions, field paths and remaining live gates.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

ORDER_LIST = "order/searchList"
ORDER_DETAIL = "order/orderDetail"
REFUND_LIST = "afterSale/List"
REFUND_DETAIL = "afterSale/Detail"

# Fields are taken from each official requestParam schema, not inferred aliases.
REQUEST_FIELDS = {
    ORDER_LIST: frozenset(
        {
            "product",
            "b_type",
            "after_sale_status_desc",
            "tracking_no",
            "presell_type",
            "order_type",
            "create_time_start",
            "create_time_end",
            "abnormal_order",
            "trade_type",
            "combine_status",
            "update_time_start",
            "update_time_end",
            "size",
            "page",
            "order_by",
            "order_asc",
            "fulfil_status",
        }
    ),
    ORDER_DETAIL: frozenset({"shop_order_id"}),
    REFUND_LIST: frozenset(
        {
            "order_id",
            "aftersale_type",
            "aftersale_status",
            "reason",
            "logistics_status",
            "pay_type",
            "refund_type",
            "arbitrate_status",
            "order_flag",
            "start_time",
            "end_time",
            "amount_start",
            "amount_end",
            "risk_flag",
            "order_by",
            "page",
            "size",
            "aftersale_id",
            "standard_aftersale_status",
            "need_special_type",
            "update_start_time",
            "update_end_time",
            "order_logistics_tracking_no",
            "order_logistics_state",
            "agree_refuse_sign",
            "aftersale_sub_type",
            "aftersale_status_to_final_start_time",
            "aftersale_status_to_final_end_time",
            "store_id_list",
        }
    ),
    REFUND_DETAIL: frozenset({"after_sale_id", "need_operation_record"}),
}
_TIME_FIELDS = {
    ORDER_LIST: (("create_time_start", "create_time_end"), ("update_time_start", "update_time_end")),
    REFUND_LIST: (
        ("start_time", "end_time"),
        ("update_start_time", "update_end_time"),
        ("aftersale_status_to_final_start_time", "aftersale_status_to_final_end_time"),
    ),
}


def _is_integer(value: Any) -> bool:
    """JSON booleans are not integer page numbers, timestamps or amounts."""
    return isinstance(value, int) and not isinstance(value, bool)


def validate_read_params(path: str, params: dict[str, Any]) -> None:
    """Reject invalid pagination, old aliases and incompatible update-time sort."""
    if path not in REQUEST_FIELDS:
        return  # Other pre-existing tools have separate, not-yet-verified contracts.
    unknown = set(params) - REQUEST_FIELDS[path]
    if unknown:
        raise ValueError(f"Unsupported business fields for {path}: {', '.join(sorted(unknown))}")
    if path in (ORDER_LIST, REFUND_LIST):
        page, size = params.get("page"), params.get("size")
        if not _is_integer(page) or page < 0 or not _is_integer(size) or not 1 <= size <= 100:
            raise ValueError("page must be an integer >= 0 and size an integer from 1 through 100")
        if path == REFUND_LIST and page * size > 50000:
            raise ValueError("afterSale/List caps page * size at 50000; split the time window")
        for start, end in _TIME_FIELDS[path]:
            for field in (start, end):
                if field in params and (not _is_integer(params[field]) or not 0 <= params[field] < 100_000_000_000):
                    raise ValueError(f"{field} must be a seconds-based integer timestamp")
            if start in params and end in params and params[end] <= params[start]:
                raise ValueError(f"{end} must be after {start}")
        if path == ORDER_LIST and any(k in params for k in ("update_time_start", "update_time_end")):
            if params.get("order_by") != "update_time":
                raise ValueError("Order update-time polling requires order_by=update_time")
        if path == REFUND_LIST and any(k in params for k in ("update_start_time", "update_end_time")):
            ordering = params.get("order_by")
            if (
                not isinstance(ordering, list)
                or not ordering
                or ordering[0] not in ("update_time asc", "update_time desc")
            ):
                raise ValueError("After-sale update-time polling requires order_by=['update_time asc'] or desc")
    else:
        key = "shop_order_id" if path == ORDER_DETAIL else "after_sale_id"
        if not isinstance(params.get(key), str) or not params[key].strip():
            raise ValueError(f"{key} must be a nonempty platform identifier")


def validate_read_response(path: str, data: dict[str, Any]) -> None:
    """Schema mismatches must not masquerade as successful empty pages."""
    if path not in REQUEST_FIELDS:
        return
    if not isinstance(data, dict):
        raise ValueError(f"{path} response data must be an object")
    if path in (ORDER_LIST, REFUND_LIST):
        key = "shop_order_list" if path == ORDER_LIST else "items"
        if not isinstance(data.get(key), list) or any(not isinstance(item, dict) for item in data[key]):
            raise ValueError(f"{path} response is missing a valid {key} array")
        if not _is_integer(data.get("total")) or data["total"] < len(data[key]):
            raise ValueError(f"{path} response requires a valid total")
        if path == REFUND_LIST and not isinstance(data.get("has_more"), bool):
            raise ValueError("afterSale/List response requires has_more")
        records = data[key]
        identifiers = (
            [item.get("order_id") for item in records]
            if path == ORDER_LIST
            else [
                item["aftersale_info"].get("aftersale_id") if isinstance(item.get("aftersale_info"), dict) else None
                for item in records
            ]
        )
    elif path == ORDER_DETAIL:
        if not isinstance(data.get("shop_order_detail"), dict):
            raise ValueError("order/orderDetail response requires shop_order_detail")
        identifiers = [data["shop_order_detail"].get("order_id")]
    else:
        if not isinstance(data.get("process_info"), dict) or not isinstance(
            data["process_info"].get("after_sale_info"), dict
        ):
            raise ValueError("afterSale/Detail response requires process_info.after_sale_info")
        identifiers = [data["process_info"]["after_sale_info"].get("after_sale_id")]
    if any(
        not (
            (isinstance(identifier, str) and identifier.strip())
            or (path == REFUND_DETAIL and _is_integer(identifier) and identifier > 0)
        )
        for identifier in identifiers
    ):
        raise ValueError(f"{path} response record requires a nonempty platform identifier")


def timestamp_seconds(value: str) -> int:
    """Interpret naive human dates as Asia/Shanghai, never host-local time."""
    if value.isdigit():
        result = int(value)
    else:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        result = int(parsed.timestamp())
    if not 0 <= result < 100_000_000_000:
        raise ValueError("Use a seconds-based timestamp")
    return result


def list_params(kind: str, start: str, end: str, page: int, size: int, *, time_type: str) -> dict[str, Any]:
    """Construct native list fields; this does not assert complete collection."""
    if bool(start) != bool(end):
        raise ValueError("Provide both start_time and end_time")
    if kind not in (ORDER_LIST, REFUND_LIST) or time_type not in ("create", "update"):
        raise ValueError("time_type must be create or update")
    params: dict[str, Any] = {"page": page, "size": size}
    if start:
        index = 0 if time_type == "create" else 1
        names = _TIME_FIELDS[kind][index]
        params.update(zip(names, (timestamp_seconds(start), timestamp_seconds(end)), strict=True))
    if time_type == "update":
        if kind == ORDER_LIST:
            params.update(order_by="update_time", order_asc=True)
        else:
            params["order_by"] = ["update_time asc"]
    validate_read_params(kind, params)
    return params


def project_order(raw: dict[str, Any]) -> dict[str, Any]:
    """Retain official fields and name payment metrics without conflating them."""
    payment, discount = raw.get("pay_amount"), raw.get("promotion_pay_amount")
    products = [{**item, "quantity": item.get("item_num")} for item in raw.get("sku_order_list", [])]
    return {
        **raw,
        "shop_order_id": raw.get("order_id"),
        "status": raw.get("order_status"),
        "status_desc": raw.get("order_status_desc"),
        "amount": payment,
        "amount_basis": "platform_pay_amount",
        "amount_unit": "fen",
        "buyer_paid_amount": payment - discount if _is_integer(payment) and _is_integer(discount) else None,
        "merchant_received_amount": raw.get("actual_receive_amount_info", {}).get("actual_receive_amount"),
        "product_info": products,
        "products": products,
        "logistics": raw.get("logistics_info", []),
    }


def project_refund(item: dict[str, Any]) -> dict[str, Any]:
    """The list has a requested amount, not the detail's real refunded amount."""
    info = item.get("aftersale_info")
    if not isinstance(info, dict) or not isinstance(item.get("order_info"), dict):
        raise ValueError("afterSale/List item requires aftersale_info and order_info")
    return {
        "refund_id": info.get("aftersale_id"),
        "order_id": item["order_info"].get("shop_order_id"),
        "status": info.get("refund_status"),
        "after_sale_status": info.get("aftersale_status"),
        "refund_type": info.get("aftersale_type"),
        "requested_amount": info.get("refund_amount"),
        "amount": None,
        "amount_unit": "fen",
        "detail_required": True,
        "create_time": info.get("apply_time"),
        "update_time": info.get("update_time"),
    }
