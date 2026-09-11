"""Current official Kuaishou merchant read schemas, checked 2026-09-10."""

from __future__ import annotations

from typing import Any

from shared.cn_commerce_base import CommerceAPIError

ORDER_LIST = "open.order.cursor.list"
ORDER_DETAIL = "open.order.detail"
REFUND_LIST = "open.seller.order.refund.pcursor.list"
REFUND_DETAIL = "open.seller.order.refund.detail"
SHOP_INFO = "open.shop.info.get"
READ_METHODS = frozenset({ORDER_LIST, ORDER_DETAIL, REFUND_LIST, REFUND_DETAIL, SHOP_INFO})
_LIST_COMMON = {"beginTime", "endTime", "pageSize", "sort", "queryType"}
_ALLOWED = {
    ORDER_LIST: _LIST_COMMON | {"orderViewStatus", "cursor", "cpsType"},
    ORDER_DETAIL: {"oid"},
    REFUND_LIST: _LIST_COMMON | {"type", "currentPage", "pcursor", "negotiateStatus", "status", "option", "orderId"},
    REFUND_DETAIL: {"refundId"},
    SHOP_INFO: set(),
}


def _number(value: Any, key: str, maximum: int = 2**63 - 1, minimum: int = 1) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise ValueError(f"Kuaishou {key} must be an integer in [{minimum}, {maximum}]")
    return value


def _enum(params: dict, key: str, values: set[int]) -> None:
    number = _number(params.get(key), key, minimum=0)
    if number not in values:
        raise ValueError(f"Kuaishou {key} is not a documented value")


def validate_params(method: str, params: dict) -> None:
    """Only native business fields can enter the signed param envelope."""
    if method not in READ_METHODS:
        return
    if not isinstance(params, dict) or params.keys() - _ALLOWED[method]:
        raise ValueError("Kuaishou unsupported business field or protocol override")
    if method == SHOP_INFO:
        return
    if method in {ORDER_DETAIL, REFUND_DETAIL}:
        key = "oid" if method == ORDER_DETAIL else "refundId"
        _number(params.get(key), key)
        return
    start = _number(params.get("beginTime"), "beginTime")
    end = _number(params.get("endTime"), "endTime")
    days = 7 if method == ORDER_LIST else 1
    if not 0 < end - start <= days * 86400000:
        raise ValueError(f"Kuaishou query window must be positive and at most {days} days in milliseconds")
    _number(params.get("pageSize"), "pageSize", 50 if method == ORDER_LIST else 100)
    cursor = "cursor" if method == ORDER_LIST else "pcursor"
    if not isinstance(params.get(cursor), str):
        raise ValueError(f"Kuaishou {cursor} must be a string; first call requires an explicit empty string")
    for key in ("sort", "queryType"):
        if key in params:
            _enum(params, key, {1, 2})
    if method == ORDER_LIST:
        _enum(params, "orderViewStatus", set(range(8)))
        if "cpsType" in params:
            _enum(params, "cpsType", {0, 1, 2})
        return
    _enum(params, "type", {8, 9})
    _number(params.get("currentPage"), "currentPage")
    if "negotiateStatus" in params:
        _enum(params, "negotiateStatus", {1, 2, 3})
    if "status" in params:
        _enum(params, "status", {10, 12, 20, 30, 40, 45, 50, 60, 70})
    if "orderId" in params:
        _number(params["orderId"], "orderId")
    if "option" in params:
        option = params["option"]
        if not isinstance(option, dict) or option.keys() - {"needExchange"}:
            raise ValueError("Kuaishou option accepts only needExchange")
        if "needExchange" in option and not isinstance(option["needExchange"], bool):
            raise ValueError("Kuaishou option.needExchange must be boolean")


def _mapping(value: Any) -> dict:
    if not isinstance(value, dict):
        raise ValueError("Kuaishou response is missing a documented object")
    return value


def validate_response(method: str, payload: Any) -> dict:
    """Do not turn failed business results or cursor omissions into empty pages."""
    body = _mapping(payload)
    result = body.get("result")
    if isinstance(result, bool):
        raise ValueError("Kuaishou result must be numeric")
    if result not in (1, "1") or body.get("code") not in (None, 0, "0", 1, "1"):
        code = body.get("code", result)
        try:
            number = int(code)
        except (ValueError, TypeError):
            number = -1
        raise CommerceAPIError(number, str(body.get("error_msg") or body.get("msg") or "Kuaishou API failure"))
    data = _mapping(body.get("data"))
    if method in {ORDER_LIST, REFUND_LIST}:
        rows_key, cursor_key = ("orderList", "cursor") if method == ORDER_LIST else ("refundOrderInfoList", "pcursor")
        rows = data.get(rows_key)
        cursor = data.get(cursor_key)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError(f"Kuaishou {rows_key} must be an array of objects")
        if not isinstance(cursor, str) or not cursor:
            raise ValueError(f"Kuaishou {cursor_key} must explicitly continue or finish the query")
        return body
    if method == ORDER_DETAIL:
        _number(_mapping(data.get("orderBaseInfo")).get("oid"), "response oid")
    elif method == REFUND_DETAIL:
        _number(data.get("refundId"), "response refundId")
        _number(data.get("oid"), "response oid")
    elif method == SHOP_INFO and not isinstance(data.get("shopName"), str):
        raise ValueError("Kuaishou shop info lacks shopName; it does not provide a shop identity")
    return body
