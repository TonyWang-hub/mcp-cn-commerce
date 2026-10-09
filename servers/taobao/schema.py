"""TOP read contracts checked against official API docs on 2026-09-10."""

from datetime import datetime, timedelta
from typing import Any

ORDER_LIST = "taobao.trades.sold.get"
ORDER_DETAIL = "taobao.trade.fullinfo.get"
ORDER_INCREMENT = "taobao.trades.sold.increment.get"
REFUND_LIST = "taobao.refunds.receive.get"
REFUND_DETAIL = "taobao.refund.get"
ORDER_FIELDS = "tid,type,status,payment,pay_time,created,modified,end_time,orders"
ORDER_DETAIL_FIELDS = ORDER_FIELDS + ",received_payment,platform_subsidy_fee"
REFUND_FIELDS = "refund_id,tid,oid,status,refund_fee,created,modified,end_time,dispute_type"
REFUND_DETAIL_FIELDS = "refund_id,tid,oid,status,refund_fee,created,end_time,dispute_type"
REQUEST_FIELDS = {
    ORDER_LIST: frozenset(
        "fields start_created end_created status buyer_nick type ext_type rate_status tag page_no page_size use_has_next buyer_open_id".split()
    ),
    ORDER_INCREMENT: frozenset(
        "fields start_modified end_modified status type buyer_nick ext_type tag page_no page_size rate_status use_has_next buyer_open_uid".split()
    ),
    ORDER_DETAIL: frozenset({"fields", "tid", "include_oaid"}),
    REFUND_LIST: frozenset(
        "fields status type start_modified end_modified page_no page_size use_has_next ouid buyer_open_uid buyer_nick".split()
    ),
    REFUND_DETAIL: frozenset({"fields", "refund_id"}),
}


def _integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _positive_number(value: Any) -> bool:
    return (_integer(value) and value > 0) or (isinstance(value, str) and value.isdecimal() and int(value) > 0)


def _date(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("TOP dates must use yyyy-MM-dd HH:mm:ss")
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def validate_params(method: str, params: dict[str, Any]) -> None:
    """Validate known business routes before signing; other legacy tools remain separate."""
    if method not in REQUEST_FIELDS:
        return
    if set(params) - REQUEST_FIELDS[method]:
        raise ValueError("Unsupported TOP business fields")
    fields = params.get("fields")
    if not isinstance(fields, str) or not fields.strip() or any(not name.strip() for name in fields.split(",")):
        raise ValueError("TOP fields must be a nonempty comma-separated field selection")
    if method in (ORDER_DETAIL, REFUND_DETAIL):
        key = "tid" if method == ORDER_DETAIL else "refund_id"
        if not _positive_number(params.get(key)):
            raise ValueError(f"TOP {key} must be a positive platform identifier")
        return
    page, size = params.get("page_no", 1), params.get("page_size", 40)
    if not _positive_number(page) or not _positive_number(size) or int(size) > 100:
        raise ValueError("TOP page_no must be >=1 and page_size must be 1..100")
    if "use_has_next" in params and params["use_has_next"] not in (True, False, "true", "false"):
        raise ValueError("TOP use_has_next must be boolean")
    start, end = ("start_created", "end_created") if method == ORDER_LIST else ("start_modified", "end_modified")
    if method == ORDER_INCREMENT and (start not in params or end not in params):
        raise ValueError("TOP increment requires both modification dates")
    for field in (start, end):
        if field in params:
            _date(params[field])
    if start in params and end in params:
        difference = _date(params[end]) - _date(params[start])
        if difference <= timedelta(0):
            raise ValueError("TOP end must be after start")
        if method == ORDER_INCREMENT and difference > timedelta(days=1):
            raise ValueError("TOP increment modification window cannot exceed one day")


def validate_response(method: str, params: dict[str, Any], payload: dict[str, Any]) -> None:
    """Preserve the official unsimplified TOP envelope and pagination signal."""
    if method not in REQUEST_FIELDS:
        return
    envelope = method.removeprefix("taobao.").replace(".", "_") + "_response"
    data = payload.get(envelope)
    if not isinstance(data, dict):
        raise ValueError(f"TOP response requires {envelope}")
    is_refund = method in (REFUND_LIST, REFUND_DETAIL)
    identifier = "refund_id" if is_refund else "tid"
    if method in (ORDER_DETAIL, REFUND_DETAIL):
        record = data.get("refund" if is_refund else "trade")
        if not isinstance(record, dict):
            raise ValueError("TOP response requires a detail object")
        records = [record]
    else:
        container = data.get("refunds" if is_refund else "trades")
        records = container.get("refund" if is_refund else "trade") if isinstance(container, dict) else None
        if not isinstance(records, list) or any(not isinstance(record, dict) for record in records):
            raise ValueError("TOP response requires a records array")
        if params.get("use_has_next") in (True, "true"):
            if not isinstance(data.get("has_next"), bool):
                raise ValueError("TOP has-next pagination requires has_next")
        elif not _integer(data.get("total_results")) or data["total_results"] < len(records):
            raise ValueError("TOP counted pagination requires total_results")
    if identifier in {field.strip() for field in params["fields"].split(",")}:
        if any(not _positive_number(record.get(identifier)) for record in records):
            raise ValueError("TOP response requires the requested platform identifier")
