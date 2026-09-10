"""Native read contracts retrieved from Youzan's official docs on 2026-09-10."""

import calendar
from datetime import datetime
from typing import Any

ORDER_LIST = "youzan.trades.sold.get/4.0.4"
ORDER_DETAIL = "youzan.trade.get/4.0.2"
REFUND_LIST = "youzan.trade.refund.search/3.0.1"
REFUND_DETAIL = "youzan.trade.refund.get/3.0.1"
SHOP_INFO = "youzan.shop.get/3.0.0"
REQUEST_FIELDS = {
    ORDER_LIST: frozenset(
        "type status start_created end_created start_update end_update delivery_start_time delivery_end_time fans_id fans_type page_no page_size offline_id receiver_phone receiver_name tid yz_open_id goods_id express_type goods_title need_order_url keywords node_kdt_id start_success end_success start_pay end_pay exclude_order_tag shop_org_id_list is_special_cloud_counter_order book_key custom_tags out_biz_no".split()
    ),
    ORDER_DETAIL: frozenset({"tid"}),
    REFUND_LIST: frozenset(
        "tid refund_id sku_no goods_title status type pay_type pay_way cs_status demand phase return_stock_status yz_open_id buyer_phone create_time_start create_time_end update_time_start update_time_end sale_way invalid refund_mode search_tag page_size page_no delivery_status delivery_no node_kdt_id custom_tags".split()
    ),
    REFUND_DETAIL: frozenset({"refund_id", "query_option"}),
    SHOP_INFO: frozenset(),
}


def _integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _date(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Youzan order dates must be yyyy-MM-dd HH:mm:ss strings")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError as exc:
        raise ValueError("Youzan order dates must be yyyy-MM-dd HH:mm:ss strings") from exc
    return parsed


def validate_params(endpoint: str, params: dict[str, Any]) -> None:
    """Validate only current official fields and known pagination/window limits."""
    if endpoint not in REQUEST_FIELDS:
        raise ValueError("Unsupported Youzan read endpoint")
    if set(params) - REQUEST_FIELDS[endpoint]:
        raise ValueError("Unsupported Youzan business fields")
    if endpoint in (ORDER_LIST, REFUND_LIST):
        page, size = params.get("page_no", 1), params.get("page_size", 20)
        if not _integer(page) or not 1 <= page <= 100 or not _integer(size) or size < 1:
            raise ValueError("Youzan page_no must be 1..100 and page_size a positive integer")
        if endpoint == ORDER_LIST and size > 100:
            raise ValueError("Youzan order page_size cannot exceed 100")
        if endpoint == REFUND_LIST and page * size > 3000:
            raise ValueError("Youzan refund page_no * page_size cannot exceed 3000; split time windows")
        pairs = (
            [("start_" + kind, "end_" + kind) for kind in ("created", "update", "success", "pay")]
            + [("delivery_start_time", "delivery_end_time")]
            if endpoint == ORDER_LIST
            else [(kind + "_time_start", kind + "_time_end") for kind in ("create", "update")]
        )
        for start_name, end_name in pairs:
            if (start_name in params) != (end_name in params):
                raise ValueError("Youzan time filters must provide both start and end")
            if start_name not in params:
                continue
            start, end = params[start_name], params[end_name]
            if endpoint == REFUND_LIST:
                if any(not _integer(value) or not 0 <= value < 100_000_000_000 for value in (start, end)):
                    raise ValueError("Youzan refund filters require seconds-based integer timestamps")
                if end <= start:
                    raise ValueError("Youzan end must be after start")
            else:
                start, end = _date(start), _date(end)
                if end <= start:
                    raise ValueError("Youzan end must be after start")
                if start_name != "delivery_start_time":
                    month_index = start.month - 1 + 3
                    year, month = start.year + month_index // 12, month_index % 12 + 1
                    limit = start.replace(
                        year=year, month=month, day=min(start.day, calendar.monthrange(year, month)[1])
                    )
                    if end > limit:
                        raise ValueError("Youzan order window cannot exceed three calendar months")
    elif endpoint in (ORDER_DETAIL, REFUND_DETAIL):
        key = "tid" if endpoint == ORDER_DETAIL else "refund_id"
        if not isinstance(params.get(key), str) or not params[key].strip():
            raise ValueError(f"Youzan {key} must be a nonempty identifier")


def _get(record: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(record, dict):
            return None
        record = record.get(key)
    return record


def validate_data(endpoint: str, data: Any) -> None:
    """An unidentified row or missing list is not a valid successful response."""
    if not isinstance(data, dict):
        raise ValueError("Youzan data must be an object")
    if endpoint in (ORDER_LIST, REFUND_LIST):
        list_key, total_key = (
            ("full_order_info_list", "total_results") if endpoint == ORDER_LIST else ("refunds", "total")
        )
        records, total = data.get(list_key), data.get(total_key)
        if not isinstance(records, list) or not _integer(total) or total < len(records):
            raise ValueError("Youzan response requires valid list and total")
        identifiers = (
            [_get(row, "full_order_info", "order_info", "tid") for row in records]
            if endpoint == ORDER_LIST
            else [_get(row, "refund_id") for row in records]
        )
    elif endpoint == ORDER_DETAIL:
        identifiers = [_get(data, "full_order_info", "order_info", "tid")]
    elif endpoint == REFUND_DETAIL:
        identifiers = [data.get("refund_id")]
    else:
        identifiers = [data.get("id")]
    if any(
        not ((isinstance(value, str) and value.strip()) or (_integer(value) and value > 0)) for value in identifiers
    ):
        raise ValueError("Youzan response requires a nonempty platform identifier")
