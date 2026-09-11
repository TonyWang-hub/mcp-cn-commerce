"""POP aftersale queries; neither operation covers completed cancellation refunds."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from decimal import Decimal

from shared.cn_commerce_base import CommerceAPIError

AFTERSALE_LIST = "jingdong.asc.serviceAndRefund.view"
AFTERSALE_REFUND_DETAIL = "jingdong.b2c.shop.aftersales.refund.get"
READ_METHODS = frozenset({AFTERSALE_LIST, AFTERSALE_REFUND_DETAIL})
_LIST_FIELDS = frozenset(
    {"orderId", "applyTimeBegin", "applyTimeEnd", "approveTimeBegin", "approveTimeEnd", "pageNumber", "pageSize"}
)


def _integer(value, *, maximum=2**63 - 1, zero=False, response=False):
    if response and isinstance(value, str) and re.fullmatch(r"0|[1-9][0-9]{0,18}", value):
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or not (0 if zero else 1) <= value <= maximum:
        raise ValueError("JD aftersale requires a bounded integer")
    return value


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", value):
        raise ValueError("JD aftersale date must use yyyy-MM-dd HH:mm:ss")
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        raise ValueError("JD aftersale date must use yyyy-MM-dd HH:mm:ss") from None


def validate_params(method: str, params: dict) -> None:
    """Expose only SDK leaf fields, with bounded scans and no identity overrides."""
    allowed = _LIST_FIELDS if method == AFTERSALE_LIST else {"afsServiceId", "skuNum"}
    if params.keys() - allowed:
        raise ValueError("JD aftersale unsupported business field")
    if method == AFTERSALE_REFUND_DETAIL:
        _integer(params.get("afsServiceId"))
        if "skuNum" in params:
            _integer(params["skuNum"], maximum=2**31 - 1)
        return
    _integer(params.get("pageNumber"), maximum=2**31 - 1)
    _integer(params.get("pageSize"), maximum=50)
    if "orderId" in params:
        _integer(params["orderId"])
    has_window = False
    for first, last, days in (("applyTimeBegin", "applyTimeEnd", 7), ("approveTimeBegin", "approveTimeEnd", 10)):
        if first in params or last in params:
            start, end = _date(params.get(first)), _date(params.get(last))
            if not timedelta(0) < end - start <= timedelta(days=days):
                raise ValueError("JD aftersale date window exceeds the documented limit")
            has_window = True
    if not has_window and "orderId" not in params:
        raise ValueError("JD aftersale requires an order or a bounded date window")


def _mapping(value):
    if not isinstance(value, dict):
        raise ValueError("JD aftersale response is missing a documented object")
    return value


def _amount(value):
    if type(value) not in (int, float, str) or not re.fullmatch(r"[0-9]{1,24}(?:\.[0-9]{1,12})?", str(value)):
        raise ValueError("JD aftersale amount must be a nonnegative decimal")
    if not Decimal(str(value)).is_finite():
        raise ValueError("JD aftersale amount must be a nonnegative decimal")


def validate_response(method: str, wrapper: dict) -> None:
    """Require method-specific success and preserve native amount branches."""
    listing = method == AFTERSALE_LIST
    result = _mapping(wrapper.get("pageResult" if listing else "result"))
    code = result.get("code" if listing else "errorCode")
    success = result.get("success")
    expected = "00000" if listing else "200"
    if success is False or success == "false" or str(code) != expected:
        number = int(str(code)) if type(code) in (int, str) and re.fullmatch(r"[0-9]{1,9}", str(code)) else -1
        raise CommerceAPIError(number, "JD aftersale API failure")
    if success is not True and success != "true":
        raise ValueError("JD aftersale response must explicitly confirm success")
    if listing:
        _validate_list(result)
        return
    data = _mapping(result.get("data"))
    _integer(data.get("orderId"), response=True)
    branches = [key for key in ("afsActualRefundDetail", "afsEstimateRefundDetail") if data.get(key) is not None]
    if len(branches) != 1:
        raise ValueError("JD aftersale response requires one actual or estimated refund branch")
    key = branches[0]
    branch = _mapping(data[key])
    _amount(branch.get("actualRefundAmount" if key == "afsActualRefundDetail" else "maxRefundAmount"))


def _validate_list(result):
    total = _integer(result.get("totalCount"), zero=True, response=True)
    _integer(result.get("pageNumber"), maximum=2**31 - 1, response=True)
    size = _integer(result.get("pageSize"), maximum=50, response=True)
    rows = result.get("data")
    if not isinstance(rows, list) or len(rows) > min(total, size):
        raise ValueError("JD aftersale page must have counted rows")
    for row in rows:
        row = _mapping(row)
        service = _mapping(row.get("sameOrderServiceBill"))
        for key in ("serviceId", "orderId"):
            _integer(service.get(key), response=True)
        for key in ("afsRefundId", "status"):
            if row.get(key) is not None:
                _integer(row[key], zero=key == "status", response=True)
        if row.get("completeTime") is not None:
            _date(row["completeTime"])
