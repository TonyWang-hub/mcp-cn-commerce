"""Deterministic, offline daily-report aggregation for explicitly covered data.

No API fetching happens here. Callers extract every page, then declare coverage
per shop/date/source. Unknown or failed coverage never becomes a complete zero.
See docs/data-contracts.md for definitions and the raw/normalized input contract.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date as Date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from zoneinfo import ZoneInfo

from shared.normalizer import Normalizer, normalize_identifier, normalize_platform, normalize_time


_METRICS = ("order_count", "gmv", "avg_order_value", "refund_count", "refund_order_count", "refund_amount", "refund_rate")


def _error(code: str, source: str, record_id: str = "", **details: Any) -> dict:
    return {"code": code, "source": source, "record_id": record_id, **details}


def _cents(value: Any) -> int | None:
    # The unified contract is integer fen; floats/strings must first be normalized.
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _day(value: Any, timezone: ZoneInfo) -> str | None:
    normalized = normalize_time(value, "", warnings=[])
    if not normalized:
        return None
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        return None
    return dt.astimezone(timezone).date().isoformat()


def _average(gmv: int | None, count: int | None) -> int | None:
    if gmv is None or not count:
        return None
    return int((Decimal(gmv) / count).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _records(shop: dict, source: str, normalizer: Normalizer) -> tuple[list[dict], list[dict], int]:
    if source not in shop:
        return [], [_error("source_missing", source)], 0
    values = shop[source]
    if not isinstance(values, list):
        return [], [_error("records_not_list", source)], 0
    result: dict[str, dict] = {}
    conflicts: set[str] = set()
    errors = []
    duplicates = 0
    id_key = "order_id" if source == "orders" else "refund_id"
    for value in values:
        if is_dataclass(value) and not isinstance(value, type):
            value = asdict(value)
        if not isinstance(value, dict):
            errors.append(_error("record_not_object", source))
            continue
        if shop.get("input_format", "normalized") == "raw":
            method = normalizer.normalize_order if source == "orders" else normalizer.normalize_refund
            value = asdict(method(value, shop["platform"]))
        value = {**value, "platform": normalize_platform(value.get("platform", ""))}
        identity = normalize_identifier(value.get(id_key))
        if not identity:
            errors.append(_error("record_id_missing", source))
            continue
        record_shop_id = value.get("shop_id")
        normalized_shop_id = normalize_identifier(record_shop_id)
        warnings = value.get("warnings", [])
        invalid_shop_warning = isinstance(warnings, list) and any(
            isinstance(warning, dict) and warning.get("field") == "shop_id"
            and warning.get("code") == "identifier_invalid" for warning in warnings
        )
        invalid_shop_id = record_shop_id is not None and record_shop_id != "" and not normalized_shop_id
        if (value.get("platform") != shop["platform"] or invalid_shop_id or invalid_shop_warning
                or normalized_shop_id and normalized_shop_id != shop["shop_id"]):
            errors.append(_error("record_scope_mismatch", source, identity))
            continue
        value[id_key] = identity
        if source == "refunds":
            value["order_id"] = normalize_identifier(value.get("order_id"))
        if identity in conflicts:
            duplicates += 1
            continue
        if identity in result:
            duplicates += 1
            if value != result[identity]:
                conflicts.add(identity)
                del result[identity]
                errors.append(_error("duplicate_conflict", source, identity))
        else:
            result[identity] = value
    return [result[key] for key in sorted(result)], errors, duplicates


def _products(orders: list[dict], complete: bool, top_n: int) -> tuple[list[dict], bool, list[dict]]:
    products: dict[str, dict] = {}
    warnings = []
    valid = complete
    for order in orders:
        record_warnings = order.get("warnings", [])
        if not isinstance(record_warnings, list):
            valid = False
            record_warnings = []
        if any(isinstance(w, dict) and str(w.get("field", "")).startswith("items")
               and not str(w.get("field", "")).endswith(".sku_id") for w in record_warnings):
            valid = False
        items = order.get("items")
        if not isinstance(items, list) or not items:
            valid = False
            warnings.append(_error("items_missing", "products", str(order["order_id"])))
            continue
        for item in items:
            if not isinstance(item, dict):
                valid = False
                warnings.append(_error("item_invalid", "products", str(order["order_id"])))
                continue
            product_id = normalize_identifier(item.get("product_id"))
            quantity = _cents(item.get("quantity"))
            price = _cents(item.get("price"))
            if not product_id or quantity is None or price is None:
                valid = False
                warnings.append(_error("item_fields_unknown", "products", str(order["order_id"])))
                continue
            product = products.setdefault(product_id, {"product_id": product_id, "name": str(item.get("product_name") or product_id), "sales": 0, "gross_item_amount": 0, "gmv": None})
            product["sales"] += quantity
            product["gross_item_amount"] += price * quantity
    # Item list prices do not allocate order-level discounts/shipping/refunds.
    # Never claim this multiplication is product-level paid GMV.
    ranked = sorted(products.values(), key=lambda p: (-p["sales"], p["product_id"]))[:top_n]
    return ranked, valid, warnings


def _shop_report(shop: dict, days: tuple[str, str], timezone: ZoneInfo, top_n: int) -> dict:
    normalizer = Normalizer(source_timezone=timezone, amount_units=shop.get("amount_units"))
    orders, order_errors, order_duplicates = _records(shop, "orders", normalizer)
    refunds, refund_errors, refund_duplicates = _records(shop, "refunds", normalizer)
    external_errors = shop.get("errors", [])
    if not isinstance(external_errors, list):
        external_errors = [_error("errors_not_list", "input")]
    # Preserve error codes rather than arbitrary API payloads which may contain PII.
    errors = [_error("upstream_error", "input", detail=str(e.get("code", "unspecified")) if isinstance(e, dict) else "unspecified") for e in external_errors]
    errors += order_errors + refund_errors
    grouped_orders: dict[str, list[dict]] = {day: [] for day in days}
    grouped_refunds: dict[str, list[dict]] = {day: [] for day in days}
    invalid_orders = bool(order_errors)
    invalid_refunds = bool(refund_errors)
    for order in orders:
        paid_at = order.get("paid_at")
        if not paid_at and order.get("status") in ("pending", "cancelled") and order.get("amount_paid") in (None, 0):
            continue
        day = _day(paid_at, timezone)
        if day is None:
            invalid_orders = True
            errors.append(_error("payment_timestamp_unknown", "orders", str(order["order_id"])))
        elif day in grouped_orders:
            grouped_orders[day].append(order)
    for refund in refunds:
        if refund.get("status") in ("pending", "processing", "approved", "rejected") and not refund.get("completed_at"):
            continue
        if refund.get("status") != "completed":
            invalid_refunds = True
            errors.append(_error("refund_status_unknown_or_inconsistent", "refunds", str(refund["refund_id"])))
            continue
        day = _day(refund.get("completed_at"), timezone)
        if day is None:
            invalid_refunds = True
            errors.append(_error("refund_completed_timestamp_unknown", "refunds", str(refund["refund_id"])))
        elif day in grouped_refunds:
            grouped_refunds[day].append(refund)
    coverage = shop.get("coverage", {})
    if not isinstance(coverage, dict):
        coverage = {}
    summaries = {}
    observed = {}
    completeness = {}
    warnings = []
    for day in days:
        declared = coverage.get(day, {})
        if not isinstance(declared, dict):
            declared = {}
        day_orders = grouped_orders[day]
        day_refunds = grouped_refunds[day]
        paid_amounts = [_cents(order.get("amount_paid")) for order in day_orders]
        refund_amounts = [_cents(refund.get("amount")) for refund in day_refunds]
        amounts_valid = all(value is not None for value in paid_amounts)
        refund_amounts_valid = all(value is not None for value in refund_amounts)
        refund_ids_valid = all(isinstance(refund.get("order_id"), (str, int)) and not isinstance(refund.get("order_id"), bool) and str(refund["order_id"]).strip() not in ("", "None") for refund in day_refunds)
        orders_complete = declared.get("orders") is True and not invalid_orders and not external_errors
        refunds_complete = declared.get("refunds") is True and not invalid_refunds and not external_errors
        if declared.get("orders") is not True:
            errors.append(_error("coverage_unconfirmed", "orders", date=day))
        if declared.get("refunds") is not True:
            errors.append(_error("coverage_unconfirmed", "refunds", date=day))
        if not amounts_valid:
            errors.append(_error("paid_amount_unknown", "orders", date=day))
        if not refund_amounts_valid:
            errors.append(_error("refund_amount_unknown", "refunds", date=day))
        if not refund_ids_valid:
            errors.append(_error("refund_order_id_unknown", "refunds", date=day))
        order_ids = {str(order["order_id"]) for order in day_orders}
        refunded_order_ids = {str(refund.get("order_id")) for refund in day_refunds if refund.get("order_id") is not None}
        refunded_today_order_count = len(order_ids & refunded_order_ids)
        obs = {"order_count": len(day_orders), "gmv": sum(amount for amount in paid_amounts if amount is not None),
               "avg_order_value": _average(sum(amount for amount in paid_amounts if amount is not None), len(day_orders)) if amounts_valid else None,
               "refund_count": len(day_refunds), "refund_order_count": len(refunded_order_ids) if refund_ids_valid else None,
               "refund_amount": sum(amount for amount in refund_amounts if amount is not None),
               "refund_rate": refunded_today_order_count / len(day_orders) if day_orders and refund_ids_valid else None,
               "same_day_refunded_order_count": refunded_today_order_count if refund_ids_valid else None,
               "new_customer_count": None, "repeat_customer_count": None,
               "known_paid_amount_count": sum(amount is not None for amount in paid_amounts),
               "known_refund_amount_count": sum(amount is not None for amount in refund_amounts)}
        observed[day] = obs
        summary = dict(obs)
        metric_complete = {"order_count": orders_complete, "gmv": orders_complete and amounts_valid,
            "avg_order_value": orders_complete and amounts_valid, "refund_count": refunds_complete,
            "refund_order_count": refunds_complete and refund_ids_valid,
            "refund_amount": refunds_complete and refund_amounts_valid,
            "refund_rate": orders_complete and refunds_complete and refund_ids_valid,
            "same_day_refunded_order_count": orders_complete and refunds_complete and refund_ids_valid}
        for key, value in metric_complete.items():
            if not value:
                summary[key] = None
        summaries[day] = summary
        completeness[day] = {"complete": all(metric_complete.values()), "orders": orders_complete,
                             "refunds": refunds_complete, "metrics": metric_complete}
    top_products, products_complete, product_warnings = _products(grouped_orders[days[0]], completeness[days[0]]["orders"], top_n)
    warnings.extend(product_warnings)
    for source, values in (("orders", orders), ("refunds", refunds)):
        for record in values:
            for warning in record.get("warnings", []) if isinstance(record.get("warnings", []), list) else []:
                if isinstance(warning, dict):
                    warnings.append({"source": source, "record_id": str(record.get("order_id", record.get("refund_id", ""))),
                                     "field": str(warning.get("field", "")), "code": str(warning.get("code", "normalization_warning"))})
    return {"platform": shop["platform"], "shop_id": str(shop["shop_id"]), "shop_name": str(shop.get("shop_name", shop["shop_id"])),
            "summary": summaries[days[0]], "yesterday": summaries[days[1]],
            "observed_summary": observed[days[0]], "observed_yesterday": observed[days[1]],
            "completeness": completeness, "errors": errors, "warnings": warnings,
            "top_products": top_products if products_complete else [], "observed_top_products": top_products,
            "top_products_complete": products_complete,
            "duplicates_removed": {"orders": order_duplicates, "refunds": refund_duplicates}}


def _totals(shops: list[dict], key: str) -> dict:
    totals = {}
    for metric in (*_METRICS, "same_day_refunded_order_count"):
        values = [shop[key][metric] for shop in shops]
        totals[metric] = sum(values) if values and all(value is not None for value in values) else None
    totals["avg_order_value"] = _average(totals["gmv"], totals["order_count"])
    totals["refund_rate"] = (totals["same_day_refunded_order_count"] / totals["order_count"]
                              if totals["same_day_refunded_order_count"] is not None and totals["order_count"] else None)
    return totals


def build_daily_report(date: str, shops: list[dict], *, timezone: str, top_n: int = 3) -> dict[str, Any]:
    """Build template-ready report data, with unknown complete metrics as null.

    ``shops`` are explicitly scoped source lists, never opaque API envelopes.
    Each shop declares ``coverage[date][orders|refunds] = True`` only after all
    pages for that event-date range are fetched successfully. Date and timezone
    are required; no naive timestamp can be silently assigned to a report day.
    """
    report_date = Date.fromisoformat(date)
    if report_date.isoformat() != date:
        raise ValueError("date must be YYYY-MM-DD")
    tz = ZoneInfo(timezone)
    if not isinstance(shops, list) or not shops:
        raise ValueError("shops must be a non-empty list of explicitly scoped shops")
    if not isinstance(top_n, int) or isinstance(top_n, bool) or top_n < 1:
        raise ValueError("top_n must be a positive integer")
    shops = [{**shop, "platform": normalize_platform(shop.get("platform", "")),
              "shop_id": normalize_identifier(shop.get("shop_id"))} if isinstance(shop, dict) else shop for shop in shops]
    scopes = set()
    for shop in shops:
        if not isinstance(shop, dict) or not shop.get("shop_id") or not shop.get("platform"):
            raise ValueError("Each shop must have a nonempty shop_id and platform")
        scope = (str(shop["platform"]), str(shop["shop_id"]))
        if scope in scopes:
            raise ValueError("Duplicate shop scope; combine its pages before aggregation")
        scopes.add(scope)
        if shop.get("input_format", "normalized") not in ("normalized", "raw"):
            raise ValueError("input_format must be raw or normalized")
        Normalizer().validate_platform(shop["platform"])
    days = (date, (report_date - timedelta(days=1)).isoformat())
    reports = [_shop_report(shop, days, tz, top_n) for shop in sorted(shops, key=lambda s: (s["platform"], str(s["shop_id"])))]
    return {"schema_version": "1.0", "date": date, "timezone": timezone, "currency": "CNY", "money_unit": "fen",
            "shops": reports, "total_summary": _totals(reports, "summary"), "yesterday_summary": _totals(reports, "yesterday"),
            "complete": all(shop["completeness"][date]["complete"] for shop in reports),
            "yesterday_complete": all(shop["completeness"][days[1]]["complete"] for shop in reports),
            "low_stock_alerts": None,
            "metric_definitions": {
                "order_count": "Unique orders with paid_at in the report timezone day; never inferred from created_at or current status.",
                "gmv": "Sum of amount_paid, integer fen, before subtracting refunds; settlement revenue is not available.",
                "avg_order_value": "GMV / paid order count rounded half up to integer fen; null for no paid orders.",
                "refund_count": "Unique completed refund IDs with completed_at in the report day, including refunds of older orders.",
                "refund_rate": "Share of this day's paid order IDs with a completed refund on the same day; not a lifecycle refund rate.",
                "gross_item_amount": "Unit price times quantity before order-level allocations; product paid GMV is null.",
                "coverage": "Caller attestation of all pages fetched for each event-date/source; not inferred from list length.",
                "observed_summary": "Known records only, may omit unknown amounts; must not be presented as complete totals.",
                "null": "Unknown, incomplete or undefined; never replace with zero.",
                "new_customer_count": "Unavailable without customer history; remains null.",
                "low_stock_alerts": "Unavailable without stock data; remains null."}}
