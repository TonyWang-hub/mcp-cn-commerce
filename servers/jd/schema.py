"""Current JOS POP read contract (official sources checked 2026-09-10)."""

from __future__ import annotations

import calendar
import re
from datetime import datetime
from typing import Any

from servers.jd import aftersale
from shared.cn_commerce_base import CommerceAPIError

ORDER_SEARCH = "jingdong.pop.order.search"
ORDER_DETAIL = "jingdong.pop.order.get"
SHOP_INFO = "jingdong.vender.shop.query"
READ_METHODS = frozenset({ORDER_SEARCH, ORDER_DETAIL, SHOP_INFO}) | aftersale.READ_METHODS
_ORDER_FIELDS = frozenset({"source_id", "optional_fields", "order_state", "realPin", "open_id_buyer", "xid_buyer"})
_LIST_FIELDS = _ORDER_FIELDS | {"start_date", "end_date", "page", "page_size", "sortType", "dateType"}
_STATES = frozenset(
    {
        "ALL",
        "NOT_PAY",
        "WAIT_SELLER_STOCK_OUT",
        "DengDaiChuKu",
        "WAIT_GOODS_RECEIVE_CONFIRM",
        "DengDaiQueRenShouHuo",
        "WAIT_SELLER_DELIVERY",
        "DengDaiFaHuo",
        "POP_ORDER_PAUSE",
        "POP",
        "ZanTing",
        "FINISHED_L",
        "WanCheng",
        "TRADE_CANCELED",
        "LOCKED",
        "PAUSE",
        "DELIVERY_RETURN",
        "PeiSongTuiHuo",
    }
)


def _text(params: dict, key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"JD POP requires a nonempty {key}")
    return value


def _integer_string(value: Any, name: str, maximum: int | None = None) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*", value):
        raise ValueError(f"JD POP {name} must be a positive decimal string")
    number = int(value)
    if maximum is not None and number > maximum:
        raise ValueError(f"JD POP {name} must be <= {maximum}")
    return number


def validate_params(method: str, params: dict) -> None:
    """Validate exposed native reads; no system identity can be overridden."""
    if method not in READ_METHODS:
        return
    if method in aftersale.READ_METHODS:
        aftersale.validate_params(method, params)
        return
    allowed = (
        set() if method == SHOP_INFO else (_LIST_FIELDS if method == ORDER_SEARCH else _ORDER_FIELDS | {"order_id"})
    )
    if params.keys() - allowed:
        raise ValueError("JD POP unsupported business field; system fields and service containers cannot be supplied")
    if method == SHOP_INFO:
        return
    _text(params, "source_id")  # Official default is JOS; require the caller to select it explicitly.
    fields = _text(params, "optional_fields")
    if not all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", field) for field in fields.split(",")):
        raise ValueError("JD POP optional_fields must be comma-separated field names")
    for key in ("realPin", "open_id_buyer", "xid_buyer"):
        if key in params:
            _text(params, key)
    if "order_state" in params or method == ORDER_SEARCH:
        states = _text(params, "order_state").split(",")
        if any(state not in _STATES for state in states) or ("ALL" in states and len(states) != 1):
            raise ValueError("JD POP order_state must contain documented states")
    if method == ORDER_DETAIL:
        identifier = params.get("order_id")
        if not isinstance(identifier, int) or isinstance(identifier, bool) or not 0 < identifier < 2**63:
            raise ValueError("JD POP order_id must be a positive int64")
        return
    _integer_string(params.get("page"), "page")
    _integer_string(params.get("page_size"), "page_size", 100)
    for key in ("dateType", "sortType"):
        if key in params and (not isinstance(params[key], int) or isinstance(params[key], bool)):
            raise ValueError(f"JD POP {key} must be an integer")
    dates = []
    for key in ("start_date", "end_date"):
        value = _text(params, key)
        try:
            date = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
            if date.strftime("%Y-%m-%d %H:%M:%S") != value:
                raise ValueError
        except ValueError as exc:
            raise ValueError(f"JD POP {key} must use yyyy-MM-dd HH:mm:ss") from exc
        dates.append(date)
    start, end = dates[0], dates[1]
    month = start.month % 12 + 1
    year = start.year + (start.month == 12)
    last = start.replace(year=year, month=month, day=min(start.day, calendar.monthrange(year, month)[1]))
    if not start < end <= last:
        raise ValueError("JD POP order window must be positive and no more than one calendar month")


def _error(error: dict, code_key: str = "code", text_key: str = "errorMessage") -> None:
    code = error.get(code_key, -1)
    try:
        number = int(code)
    except (ValueError, TypeError):
        number = -1
    message = (
        error.get(text_key)
        or error.get("msg")
        or error.get("zh_desc")
        or error.get("englishErrCode")
        or "JD POP API failure"
    )
    raise CommerceAPIError(number, str(message))


def _mapping(value: Any) -> dict:
    if not isinstance(value, dict):
        raise ValueError("JD POP response is missing a documented object")
    return value


def validate_response(method: str, payload: Any) -> dict:
    """Check gateway errors and exact method envelopes before counting success."""
    body = _mapping(payload)
    if "error_response" in body:
        _error(_mapping(body["error_response"]), text_key="msg")
    if "code" in body and str(body["code"]) != "0":
        _error(body)
    if method not in READ_METHODS:
        return body
    wrapper = _mapping(body.get(method.replace(".", "_") + "_responce"))
    if "code" in wrapper and str(wrapper["code"]) != "0":
        _error(wrapper)
    if method in aftersale.READ_METHODS:
        aftersale.validate_response(method, wrapper)
        return body
    if method == SHOP_INFO:
        shop = _mapping(wrapper.get("shop_jos_result"))
        for key in ("shop_id", "vender_id"):
            value = shop.get(key)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, str))
                or not re.fullmatch(r"[1-9][0-9]*", str(value))
            ):
                raise ValueError("JD POP shop response lacks a valid shop/vendor identity")
        return body
    result = _mapping(wrapper.get("searchorderinfo_result" if method == ORDER_SEARCH else "orderDetailInfo"))
    outcome = _mapping(result.get("apiResult"))
    success = outcome.get("success")
    if success is False or success == "false" or outcome.get("numberCode") not in (None, "", 0, "0"):
        _error(outcome, code_key="numberCode", text_key="chineseErrCode")
    if success is not True and success != "true":
        raise ValueError("JD POP apiResult.success must explicitly confirm success")
    if method == ORDER_DETAIL:
        _mapping(result.get("orderInfo"))
        return body
    rows = result.get("orderInfoList")
    total = result.get("orderTotal")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("JD POP orderInfoList must be an array of objects")
    if (
        isinstance(total, bool)
        or not isinstance(total, (int, str))
        or not re.fullmatch(r"0|[1-9][0-9]*", str(total))
        or int(total) < len(rows)
    ):
        raise ValueError("JD POP orderTotal must be a nonnegative count covering the page")
    return body
