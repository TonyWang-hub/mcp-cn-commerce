"""Unified data normalizer for Chinese e-commerce platform responses.

Converts platform-specific API responses from supported platforms
into a common schema so workflow templates can consume them uniformly.

Supported platforms:
  oceanengine, doudian, jd, pdd, kuaishou, xiaohongshu, weixin, taobao, youzan

Usage::

    from shared.normalizer import Normalizer

    n = Normalizer()
    order = n.normalize_order(raw_response, platform="doudian")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, tzinfo
from decimal import Decimal, DecimalException, InvalidOperation, localcontext
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# ── Platform Constants ──────────────────────────────────────

PLATFORMS = frozenset(
    {
        "oceanengine",
        "doudian",
        "jd",
        "pdd",
        "kuaishou",
        "xiaohongshu",
        "weixin",
        "taobao",
        "youzan",
    }
)


PLATFORM_ALIASES = {"pinduoduo": "pdd", "weixin_store": "weixin", "tmall": "taobao"}


def normalize_platform(platform: str) -> str:
    """Accept CLI package names while retaining the existing schema identifiers."""
    return PLATFORM_ALIASES.get(platform, platform) if isinstance(platform, str) else ""


# ── Unified Data Classes ────────────────────────────────────


@dataclass
class OrderItem:
    """A single item within an order."""

    product_id: str = ""
    product_name: str = ""
    sku_id: str = ""
    sku_name: str = ""
    price: int | None = None  # 分 (cents)
    quantity: int | None = None
    image_url: str = ""


@dataclass
class UnifiedOrder:
    """Platform-agnostic order representation.

    All monetary values are in 分 (cents, 1/100 CNY).
    All timestamps are ISO 8601 strings.
    """

    order_id: str = ""
    platform: str = ""
    status: str = ""  # pending|paid|shipped|completed|cancelled|refunding
    status_raw: str = ""  # original platform status code
    created_at: str = ""  # ISO8601
    paid_at: str | None = None
    amount_total: int | None = None  # 分
    amount_discount: int | None = None  # 分
    amount_shipping: int | None = None  # 分
    amount_paid: int | None = None  # 分
    buyer_name: str = ""
    buyer_phone: str = ""
    buyer_address: str = ""
    items: list[OrderItem] = field(default_factory=list)
    remark: str = ""
    shop_id: str = ""
    warnings: list[dict[str, Any]] = field(default_factory=list)
    source_values: dict[str, Any] = field(default_factory=dict)
    updated_at: str | None = None
    amount_platform_payment: int | None = None  # Platform payment definition, separately from buyer cash.
    amount_merchant_received: int | None = None  # Merchant receipts, separately from buyer cash.


@dataclass
class ProductSku:
    """A single SKU variant of a product."""

    sku_id: str = ""
    spec: str = ""
    price: int | None = None  # 分
    stock: int = 0


@dataclass
class UnifiedProduct:
    """Platform-agnostic product representation."""

    product_id: str = ""
    platform: str = ""
    name: str = ""
    status: str = ""  # on_sale|off_sale|audit|rejected
    category: str = ""
    price_min: int | None = None  # 分
    price_max: int | None = None  # 分
    stock: int = 0
    sold_count: int = 0
    rating: float = 0.0
    rating_count: int = 0
    images: list[str] = field(default_factory=list)
    skus: list[ProductSku] = field(default_factory=list)
    created_at: str = ""
    warnings: list[dict[str, Any]] = field(default_factory=list)
    source_values: dict[str, Any] = field(default_factory=dict)


@dataclass
class UnifiedRefund:
    """Platform-agnostic refund representation."""

    refund_id: str = ""
    order_id: str = ""
    platform: str = ""
    status: str = ""  # pending|processing|approved|rejected|completed
    type: str = ""  # refund_only|return_and_refund
    amount: int | None = None  # 分
    reason: str = ""
    description: str = ""
    evidence: list[str] = field(default_factory=list)
    applied_at: str = ""
    completed_at: str | None = None
    shop_id: str = ""
    warnings: list[dict[str, Any]] = field(default_factory=list)
    source_values: dict[str, Any] = field(default_factory=dict)
    amount_requested: int | None = None  # Requested refund; never substitute for actual refund.
    updated_at: str | None = None


@dataclass
class UnifiedReview:
    """Platform-agnostic review representation."""

    review_id: str = ""
    product_id: str = ""
    order_id: str = ""
    platform: str = ""
    score: int = 0  # 1-5
    content: str = ""
    images: list[str] = field(default_factory=list)
    user_name: str = ""
    reply: str = ""
    created_at: str = ""
    warnings: list[dict[str, Any]] = field(default_factory=list)
    source_values: dict[str, Any] = field(default_factory=dict)


@dataclass
class UnifiedShop:
    """Platform-agnostic shop representation."""

    shop_id: str = ""
    shop_name: str = ""
    platform: str = ""
    type: str = ""
    status: str = ""
    score_overall: float = 0.0
    score_product: float = 0.0
    score_service: float = 0.0
    score_logistics: float = 0.0
    product_count: int = 0
    warnings: list[dict[str, Any]] = field(default_factory=list)
    source_values: dict[str, Any] = field(default_factory=dict)


# ── Normalization Helpers ───────────────────────────────────


def _warn(warnings: list[dict[str, Any]] | None, field_name: str, code: str) -> None:
    if warnings is not None:
        warnings.append({"field": field_name, "code": code})


def normalize_identifier(
    value: Any,
    *,
    field_name: str = "id",
    warnings: list[dict[str, Any]] | None = None,
) -> str:
    """Preserve string/integer identifiers; never stringify booleans or objects."""
    if value is None or isinstance(value, str) and value.strip() in ("", "None"):
        _warn(warnings, field_name, "identifier_missing")
        return ""
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        _warn(warnings, field_name, "identifier_invalid")
        return ""
    return str(value).strip()


def normalize_price(
    value: Any,
    platform: str,
    *,
    unit: str | None = None,
    field_name: str = "amount",
    warnings: list[dict[str, Any]] | None = None,
) -> int | None:
    """Convert an explicitly specified ``yuan``/``fen`` value without rounding.

    The two-argument helper retains legacy platform units for compatibility;
    record normalizers use field-specific schemas instead. Missing, malformed,
    nonfinite, fractional-fen or unknown-unit values return None, never zero.
    """
    platform = normalize_platform(platform)
    if value is None or value == "":
        _warn(warnings, field_name, "amount_missing")
        return None
    if unit is None:
        unit = {
            "kuaishou": "yuan",
            "xiaohongshu": "yuan",
            "doudian": "fen",
            "jd": "fen",
            "pdd": "fen",
            "weixin": "fen",
            "taobao": "fen",
        }.get(platform)
        _warn(warnings, field_name, "legacy_platform_unit")
    if unit not in ("yuan", "fen"):
        _warn(warnings, field_name, "amount_unit_unknown")
        return None
    try:
        if isinstance(value, bool):
            raise ValueError("Boolean is not an amount")
        amount = Decimal(str(value))
        with localcontext() as context:
            context.prec = max(28, len(amount.as_tuple().digits) + 3)
            cents = amount * (100 if unit == "yuan" else 1)
        if not cents.is_finite():
            raise ValueError("Amount must be finite")
        if cents != cents.to_integral_value():
            _warn(warnings, field_name, "fractional_fen")
            return None
        return int(cents)
    except (DecimalException, ValueError, TypeError, OverflowError):
        _warn(warnings, field_name, "amount_invalid")
        return None


def normalize_time(
    value: Any,
    platform: str,
    *,
    source_timezone: str | tzinfo | None = None,
    timestamp_unit: str = "auto",
    field_name: str = "timestamp",
    warnings: list[dict[str, Any]] | None = None,
) -> str:
    """Parse ISO/date strings and Unix seconds/milliseconds, including strings.

    Epoch values are UTC instants. Naive civil dates remain offset-free unless
    the caller supplies a timezone; no platform timezone is silently assumed.
    Auto epochs use milliseconds at abs(value) >= 1e11; use timestamp_unit for
    ambiguous historical values. Invalid values return an empty string.
    """
    if value is None or value == "":
        return ""
    if timestamp_unit not in ("auto", "seconds", "milliseconds"):
        raise ValueError("timestamp_unit must be auto, seconds or milliseconds")
    tz = ZoneInfo(source_timezone) if isinstance(source_timezone, str) else source_timezone
    try:
        if isinstance(value, bool):
            raise ValueError("Boolean is not a timestamp")
        if isinstance(value, datetime):
            dt = value
        else:
            try:
                numeric = Decimal(str(value).strip())
            except InvalidOperation:
                numeric = None
            if numeric is not None:
                if not numeric.is_finite():
                    raise ValueError("Nonfinite timestamp")
                milliseconds = timestamp_unit == "milliseconds" or (
                    timestamp_unit == "auto" and abs(numeric) >= Decimal("1e11")
                )
                seconds = numeric / 1000 if milliseconds else numeric
                return datetime.fromtimestamp(float(seconds), tz=UTC).isoformat()
            dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        if dt.tzinfo is None:
            if tz is None:
                _warn(warnings, field_name, "timezone_missing")
                return dt.isoformat()
            earlier = dt.replace(tzinfo=tz, fold=0)
            later = dt.replace(tzinfo=tz, fold=1)
            if earlier.utcoffset() != later.utcoffset():
                _warn(warnings, field_name, "timezone_ambiguous_or_nonexistent")
                return ""
            dt = earlier
        return dt.isoformat()
    except (InvalidOperation, ValueError, TypeError, OSError, OverflowError):
        _warn(warnings, field_name, "timestamp_invalid")
        return ""


# Order status mapping per platform → unified status
_ORDER_STATUS_MAP: dict[str, dict[str | int, str]] = {
    "doudian": {
        1: "pending",
        2: "paid",
        3: "shipped",
        4: "cancelled",
        5: "completed",
        101: "shipped",  # Partially shipped; preserve the native code in status_raw.
        105: "paid",
    },
    "jd": {
        "NOT_PAY": "pending",
        "WAIT_SELLER_STOCK_OUT": "paid",
        "DengDaiChuKu": "paid",
        "WAIT_GOODS_RECEIVE_CONFIRM": "shipped",
        "DengDaiQueRenShouHuo": "shipped",
        "FINISHED_L": "completed",
        "WanCheng": "completed",
        "TRADE_CANCELED": "cancelled",
    },
    "pdd": {
        1: "paid",
        2: "shipped",
        3: "shipped",
        4: "completed",
        5: "completed",
    },
    "kuaishou": {
        1: "paid",
        2: "shipped",
        3: "completed",
        4: "refunding",
        5: "cancelled",
    },
    "xiaohongshu": {
        1: "pending",
        2: "paid",
        3: "paid",
        4: "paid",
        5: "paid",
        6: "shipped",
        7: "completed",
        8: "cancelled",
        9: "cancelled",
        10: "refunding",
    },
    "weixin": {
        10: "pending",
        12: "pending",
        13: "pending",
        20: "paid",
        21: "paid",
        30: "shipped",
        100: "completed",
        250: "cancelled",
    },
    "taobao": {
        "WAIT_BUYER_PAY": "pending",
        "WAIT_SELLER_SEND_GOODS": "paid",
        "WAIT_BUYER_CONFIRM_GOODS": "shipped",
        "TRADE_BUYER_SIGNED": "completed",
        "TRADE_FINISHED": "completed",
        "TRADE_CLOSED": "closed",
        "TRADE_CLOSED_BY_TAOBAO": "cancelled",
        "TRADE_NO_CREATE_PAY": "pending",
        "SELLER_CONSIGNED_PART": "shipped",
        "PAID_FORBID_CONSIGN": "paid",
    },
    "youzan": {
        "WAIT_BUYER_PAY": "pending",
        "TRADE_PAID": "paid",
        "WAIT_CONFIRM": "paid",
        "WAIT_SELLER_SEND_GOODS": "paid",
        "WAIT_BUYER_CONFIRM_GOODS": "shipped",
        "TRADE_SUCCESS": "completed",
        "TRADE_CLOSED": "closed",
        "TRADE_REFUND": "refunding",
    },
    "oceanengine": {
        "ADVERTISER_STATUS_ENABLE": "completed",
        "ADVERTISER_STATUS_DISABLE": "cancelled",
    },
}

# Refund status mapping per platform → unified status
_REFUND_STATUS_MAP: dict[str, dict[str | int, str]] = {
    "doudian": {1: "pending", 2: "processing", 3: "completed", 4: "rejected", 5: "reversed"},
    "jd": {
        "WAIT_PROCESS": "pending",
        "PROCESSING": "processing",
        "FINISHED": "completed",
        "REFUSED": "rejected",
    },
    "pdd": {1: "pending", 2: "processing", 3: "completed", 4: "rejected", 5: "completed"},
    "kuaishou": {1: "pending", 2: "completed", 3: "rejected"},
    "xiaohongshu": {
        1: "pending",
        2: "processing",
        3: "processing",
        4: "completed",
        5: "rejected",
        6: "rejected",
        9: "rejected",
        9001: "rejected",
        12: "processing",
        13: "processing",
        14: "processing",
    },
    "weixin": {1: "pending", 2: "processing", 3: "completed", 4: "rejected"},
    "taobao": {
        "WAIT_SELLER_AGREE": "pending",
        "SELLER_AGREE_BUYER_RETURN": "processing",
        "WAIT_BUYER_RETURN": "processing",
        "WAIT_BUYER_RETURN_GOODS": "processing",
        "WAIT_SELLER_CONFIRM_GOODS": "processing",
        "SELLER_REFUSE_BUYER": "rejected",
        "CLOSED": "closed",
        "SUCCESS": "completed",
    },
    "youzan": {
        "WAIT_SELLER_AGREE": "pending",
        "WAIT_BUYER_RETURN_GOODS": "processing",
        "WAIT_SELLER_CONFIRM_GOODS": "processing",
        "SELLER_RETURN_GOODS": "processing",
        "SELLER_REFUSE_BUYER": "rejected",
        "SELLER_REFUSE_BUYER_RETURN_GOODS": "rejected",
        "CUSTOMER_SERVICE_IN": "processing",
        "CLOSED": "closed",
        "SUCCESS": "completed",
    },
}

# Refund type mapping
_REFUND_TYPE_MAP: dict[str, dict[str | int, str]] = {
    "doudian": {
        "仅退款": "refund_only",
        "退货退款": "return_and_refund",
        "0": "return_and_refund",
        "1": "refund_only",
        "2": "refund_only",
        "3": "exchange",
        "4": "cancel",
        "5": "cancel",
        "6": "price_protection",
        "7": "reship",
        "8": "repair",
    },
    "jd": {"退款": "refund_only", "退换货": "return_and_refund"},
    "pdd": {"1": "refund_only", "2": "return_and_refund"},
    "kuaishou": {"仅退款": "refund_only", "退货退款": "return_and_refund"},
    "xiaohongshu": {"仅退款": "refund_only", "退货退款": "return_and_refund"},
    "weixin": {"REFUND": "refund_only", "RETURN": "return_and_refund"},
    "taobao": {
        "仅退款": "refund_only",
        "退货退款": "return_and_refund",
        "REFUND": "refund_only",
        "REFUND_AND_RETURN": "return_and_refund",
        "TMALL_EXCHANGE": "exchange",
        "TAOBAO_EXCHANGE": "exchange",
        "REPAIR": "repair",
        "RESHIPPING": "reship",
    },
}


def normalize_order_status(raw: Any, platform: str) -> str:
    """Map platform-specific order status to unified status.

    Args:
        raw: Raw status value from API.
        platform: Platform identifier.

    Returns:
        Unified status string.
    """
    mapping = _ORDER_STATUS_MAP.get(normalize_platform(platform), {})
    result = mapping.get(raw) if isinstance(raw, (str, int)) and not isinstance(raw, bool) else None
    if result:
        return result
    # Try string conversion
    result = mapping.get(str(raw))
    if result is None and isinstance(raw, str) and raw.isdigit():
        result = mapping.get(int(raw))
    if result:
        return result
    logger.warning(f"Unknown order status {raw!r} for {platform}")
    return "unknown"


def normalize_refund_status(raw: Any, platform: str) -> str:
    """Map platform-specific refund status to unified status."""
    mapping = _REFUND_STATUS_MAP.get(normalize_platform(platform), {})
    result = mapping.get(raw) if isinstance(raw, (str, int)) and not isinstance(raw, bool) else None
    if result:
        return result
    result = mapping.get(str(raw))
    if result is None and isinstance(raw, str) and raw.isdigit():
        result = mapping.get(int(raw))
    if result:
        return result
    logger.warning(f"Unknown refund status {raw!r} for {platform}")
    return "unknown"


def normalize_refund_type(raw: Any, platform: str) -> str:
    """Map platform-specific refund type to unified type."""
    mapping = _REFUND_TYPE_MAP.get(normalize_platform(platform), {})
    result = mapping.get(str(raw))
    if result is None and isinstance(raw, str) and raw.isdigit():
        result = mapping.get(int(raw))
    if result:
        return result
    logger.warning(f"Unknown refund type {raw!r} for {platform}")
    return "unknown"


def safe_get(data: dict, *keys: str, default: Any = None) -> Any:
    """Safely get a nested value from a dict.

    Args:
        data: The dictionary to search.
        *keys: Keys to traverse.
        default: Default value if key not found.

    Returns:
        The value at the nested key path, or default.
    """
    current = data
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key, default)
        else:
            return default
    return current


# ── Normalizer Class ────────────────────────────────────────


# These schemas describe the accepted response shapes, not every API on a
# platform. Mixed/unaudited fields (notably JD, Taobao and ad spend) deliberately
# require an override. Units may also be overridden with platform.field keys.
_MONEY_SCHEMA = {
    "doudian": dict.fromkeys(
        (
            "pay_amount",
            "promotion_pay_amount",
            "promotion_amount",
            "origin_amount",
            "actual_receive_amount",
            "amount",
            "order_amount",
            "total_amount",
            "discount_amount",
            "post_amount",
            "price",
            "min_price",
            "max_price",
            "refund_amount",
            "real_refund_amount",
            "refund_total_amount",
        ),
        "fen",
    ),
    "weixin": dict.fromkeys(
        (
            "product_price",
            "discounted_price",
            "freight",
            "order_price",
            "original_order_price",
            "merchant_receieve_price",
            "sale_price",
            "min_price",
            "max_price",
            "price",
            "refund_amount",
            "amount",
        ),
        "fen",
    ),
    "pdd": dict.fromkeys(("pay_amount", "goods_price", "min_group_price", "market_price", "refund_amount"), "fen"),
    "kuaishou": dict.fromkeys(
        (
            "order_amount",
            "total_amount",
            "pay_amount",
            "payment",
            "discount_amount",
            "post_amount",
            "price",
            "sale_price",
            "min_price",
            "max_price",
            "refund_amount",
            "amount",
        ),
        "yuan",
    ),
    "xiaohongshu": dict.fromkeys(
        (
            "order_amount",
            "total_amount",
            "pay_amount",
            "payment",
            "discount_amount",
            "post_amount",
            "price",
            "sale_price",
            "min_price",
            "max_price",
            "refund_amount",
            "amount",
        ),
        "yuan",
    ),
}


# Reviewed route-specific yuan fields; refund fund entries are explicitly fen.
_MONEY_SCHEMA["taobao"] = dict.fromkeys(
    ("payment", "received_payment", "total_fee", "discount_fee", "post_fee", "price", "refund_fee"), "yuan"
)
_MONEY_SCHEMA["youzan"] = dict.fromkeys(("real_payment", "total_fee", "post_fee", "price", "refund_fee"), "yuan")
_MONEY_SCHEMA["jd"] = dict.fromkeys(("actualPay", "freightPrice", "jdPrice"), "yuan")


class _Record:
    """Per-record parse state; never shared across concurrent normalizations."""

    def __init__(self, normalizer: Normalizer, platform: str):
        self.normalizer = normalizer
        self.platform = platform
        self.warnings: list[dict[str, Any]] = []
        self.source_values: dict[str, Any] = {}

    def amount(self, data: dict, names: tuple[str, ...], output: str) -> int | None:
        key = next((key for key in names if key in data), names[0])
        value = data.get(key)
        self.source_values[output] = {"field": key, "value": value}
        units = self.normalizer.amount_units
        unit = units.get(f"{self.platform}.{key}", units.get(key, _MONEY_SCHEMA.get(self.platform, {}).get(key)))
        self.source_values[output]["unit"] = unit
        return normalize_price(value, self.platform, unit=unit or "unknown", field_name=output, warnings=self.warnings)

    def time(self, value: Any, output: str) -> str:
        self.source_values[output] = value
        return normalize_time(
            value,
            self.platform,
            source_timezone=self.normalizer.source_timezone,
            field_name=output,
            warnings=self.warnings,
        )

    def identifier(self, value: Any, output: str) -> str:
        return normalize_identifier(value, field_name=output, warnings=self.warnings)

    def integer(self, value: Any, output: str, default: int | None = None) -> int | None:
        if value is None:
            _warn(self.warnings, output, "integer_missing")
            return default
        try:
            if isinstance(value, bool):
                raise ValueError
            parsed = Decimal(str(value))
            if not parsed.is_finite() or parsed != parsed.to_integral_value():
                raise ValueError
            result = int(parsed)
            if result < 0:
                raise ValueError
            return result
        except (ValueError, TypeError, InvalidOperation):
            _warn(self.warnings, output, "integer_invalid")
            return default

    def number(self, value: Any, output: str) -> float:
        try:
            parsed = Decimal(str(value))
            if not parsed.is_finite():
                raise ValueError
            return float(parsed)
        except (ValueError, TypeError, InvalidOperation):
            _warn(self.warnings, output, "number_invalid")
            return 0.0

    def mapping(self, value: Any, output: str) -> dict:
        if isinstance(value, dict):
            return value
        if value is not None:
            _warn(self.warnings, output, "object_invalid")
        return {}

    def array(self, value: Any, output: str) -> list:
        if isinstance(value, list):
            return value
        if value is not None:
            _warn(self.warnings, output, "list_invalid")
        return []

    def attach(self, result: Any) -> Any:
        result.warnings = self.warnings
        result.source_values = self.source_values
        return result


def _first(data: dict, *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return default


class Normalizer:
    """Normalize individual extracted records, preserving unknowns and warnings.

    ``source_timezone`` is required to locate naive timestamps. ``amount_units``
    overrides raw field units, e.g. {"jd.payment": "yuan", "salePrice": "yuan"}.
    Each record has source_values for money/time and structured warnings. A
    malformed optional item never discards already parsed order-level money.
    """

    def __init__(self, *, source_timezone: str | tzinfo | None = None, amount_units: dict[str, str] | None = None):
        if isinstance(source_timezone, str):
            ZoneInfo(source_timezone)  # configuration errors fail at construction
        self.source_timezone = source_timezone
        self.amount_units = {
            (normalize_platform(key.split(".", 1)[0]) + "." + key.split(".", 1)[1] if "." in key else key): value
            for key, value in (amount_units or {}).items()
        }
        if any(unit not in ("yuan", "fen") for unit in self.amount_units.values()):
            raise ValueError("amount_units values must be yuan or fen")

    def validate_platform(self, platform: str) -> None:
        if normalize_platform(platform) not in PLATFORMS:
            raise ValueError(f"Unsupported platform '{platform}'. Supported: {', '.join(sorted(PLATFORMS))}")

    def _record(self, raw: dict, platform: str) -> _Record:
        self.validate_platform(platform)
        if not isinstance(raw, dict):
            raise TypeError("Expected one extracted record as a dictionary")
        return _Record(self, platform)

    def normalize_order(self, raw: dict, platform: str) -> UnifiedOrder:
        platform = normalize_platform(platform)
        r = self._record(raw, platform)
        if platform == "weixin" and any(key in raw for key in ("order", "order_detail")):
            return self._weixin_order(raw, r)
        if platform == "taobao":
            return self._taobao_order(raw, r)
        if platform == "youzan":
            return self._youzan_order(raw, r)
        info = r.mapping(raw.get("orderInfo", raw), "orderInfo") if platform == "jd" else raw
        if platform == "jd" and any(key in info for key in ("venderId", "actualPay", "paymentConfirmTime", "modified")):
            return self._jd_order(raw, r)
        detail = r.mapping(raw.get("order_detail", raw), "order_detail") if platform == "weixin" else info
        prices = r.mapping(detail.get("price_info"), "price_info") if platform == "weixin" else info
        buyer = r.mapping(raw.get("buyer_info", raw.get("buyer") if platform == "doudian" else None), "buyer_info")
        if platform == "jd":
            buyer = r.mapping(raw.get("consigneeInfo"), "consigneeInfo")
        elif platform == "weixin":
            buyer = r.mapping(detail.get("delivery_info"), "delivery_info")
        status = _first(info, "order_status", "orderState", "status")
        result = UnifiedOrder(
            order_id=r.identifier(_first(info, "order_id", "order_sn", "orderId", "tid"), "order_id"),
            shop_id=r.identifier(_first(raw, "shop_id", "mall_id"), "shop_id"),
            platform=platform,
            status=normalize_order_status(status, platform),
            status_raw=str(status),
            created_at=r.time(
                _first(
                    detail,
                    "create_time",
                    "created_at",
                    "orderStartTime",
                    "created",
                    default=_first(raw, "create_time", "created_at"),
                ),
                "created_at",
            ),
            paid_at=r.time(
                _first(detail, "pay_time", "paid_at", "paymentTime", default=_first(raw, "pay_time", "paid_at")),
                "paid_at",
            )
            or None,
            updated_at=r.time(_first(detail, "update_time", "modified", "updated_at"), "updated_at") or None,
            buyer_name=str(
                _first(buyer, "name", "fullname", "receiver_name", "buyer_name", default=raw.get("receiver_name", ""))
            ),
            buyer_phone=str(
                _first(buyer, "phone", "mobile", "receiver_tel", "buyer_phone", default=raw.get("receiver_phone", ""))
            ),
            buyer_address=str(
                _first(buyer, "fullAddress", "receiver_address", default=raw.get("receiver_address", ""))
            ),
            remark=str(_first(info, "buyer_words", "remark", default="")),
        )
        money: dict[str, tuple[str, ...]]
        if platform == "weixin":
            money = {
                "amount_total": ("product_price",),
                "amount_discount": ("discounted_price",),
                "amount_shipping": ("freight",),
                "amount_paid": ("order_price",),
            }
        elif platform == "jd":
            money = {
                "amount_total": ("orderTotalPrice",),
                "amount_discount": ("sellerDiscount",),
                "amount_shipping": ("freightPrice",),
                "amount_paid": ("payment",),
            }
        else:
            money = {
                "amount_total": ("order_amount", "total_amount", "order_total_price"),
                "amount_discount": ("discount_amount", "seller_discount"),
                "amount_shipping": ("post_amount", "postage", "freight_price"),
                "amount_paid": ("pay_amount", "payment"),
            }
            if platform == "doudian":
                money["amount_total"] = ("order_amount", "total_amount")
                money["amount_discount"] = ("promotion_amount", "discount_amount")
                # Official FAQ 2019: buyer cash = pay_amount - promotion_pay_amount.
                # The old projected `amount` aliases platform pay_amount, so it
                # cannot establish buyer cash if the payment discount is missing.
                del money["amount_paid"]
        for output, keys in money.items():
            setattr(result, output, r.amount(prices, keys, output))
        if platform == "doudian":
            result.amount_platform_payment = r.amount(prices, ("pay_amount",), "amount_platform_payment")
            payment_discount = r.amount(prices, ("promotion_pay_amount",), "amount_payment_promotion")
            receipt = r.mapping(prices.get("actual_receive_amount_info"), "actual_receive_amount_info")
            result.amount_merchant_received = r.amount(receipt, ("actual_receive_amount",), "amount_merchant_received")
            if (
                result.amount_platform_payment is not None
                and payment_discount is not None
                and 0 <= payment_discount <= result.amount_platform_payment
            ):
                result.amount_paid = result.amount_platform_payment - payment_discount
            else:
                _warn(r.warnings, "amount_paid", "buyer_payment_unknown")
            r.source_values["amount_paid"] = {"formula": "pay_amount - promotion_pay_amount", "unit": "fen"}
        if platform == "jd":
            items = raw.get("itemInfoList")
        elif platform == "weixin":
            items = detail.get("product_infos")
        elif platform == "doudian":
            product_info = raw.get("product_info")
            projected_items = product_info if isinstance(product_info, list) else safe_get(raw, "product_info", "list")
            items = _first(
                raw, "sku_order_list", "items", "item_list", "goods_list", "products", default=projected_items
            )
        else:
            items = _first(raw, "items", "item_list", "goods_list", default=safe_get(raw, "product_info", "list"))
        for i, value in enumerate(r.array(items, "items")):
            prefix = f"items[{i}]"
            if not isinstance(value, dict):
                _warn(r.warnings, prefix, "object_invalid")
                continue
            item = OrderItem(
                product_id=r.identifier(
                    _first(value, "product_id", "item_id", "goods_id", "skuId"), f"{prefix}.product_id"
                ),
                product_name=str(
                    _first(value, "product_name", "item_name", "goods_name", "title", "skuName", default="")
                ),
                sku_id=r.identifier(_first(value, "sku_id", "outerSkuId"), f"{prefix}.sku_id"),
                sku_name=str(_first(value, "sku_name", "spec_desc", "spec", default="")),
                price=r.amount(
                    value,
                    (
                        ("origin_amount", "price", "sale_price", "item_price", "salePrice", "jdPrice")
                        if platform == "doudian"
                        else ("price", "sale_price", "item_price", "salePrice", "jdPrice")
                    ),
                    f"{prefix}.price",
                ),
                quantity=r.integer(
                    _first(value, "item_num", "num", "quantity", "product_cnt", "combo_num"), f"{prefix}.quantity"
                ),
                image_url=str(
                    _first(
                        value,
                        "image",
                        "thumb_img",
                        "thumb_url",
                        "img",
                        default=value.get("product_pic", "") if platform == "doudian" else "",
                    )
                ),
            )
            result.items.append(item)
        if result.status == "unknown":
            _warn(r.warnings, "status", "status_unknown")
        return r.attach(result)

    def normalize_orders(self, raw_list: list[dict], platform: str) -> list[UnifiedOrder]:
        return [self.normalize_order(raw, platform) for raw in raw_list]

    def normalize_product(self, raw: dict, platform: str) -> UnifiedProduct:
        platform = normalize_platform(platform)
        r = self._record(raw, platform)
        result = UnifiedProduct(
            product_id=r.identifier(_first(raw, "product_id", "goods_id", "item_id", "wareId"), "product_id"),
            platform=platform,
            name=str(_first(raw, "product_name", "goods_name", "item_name", "title", default="")),
            status=self._map_product_status(
                _first(raw, "product_status", "goods_status", "is_onsale", "status"), platform
            ),
            category=str(raw.get("category_name", "")),
            price_min=r.amount(raw, ("min_price", "min_group_price"), "price_min"),
            price_max=r.amount(raw, ("max_price", "market_price"), "price_max"),
            stock=r.integer(_first(raw, "stock", "stock_num", default=0), "stock", 0),
            sold_count=r.integer(
                _first(raw, "sold_count", "sold_quantity", "total_sold_num", default=0), "sold_count", 0
            ),
            rating=r.number(_first(raw, "rating", "dsr_score", default=0), "rating"),
            rating_count=r.integer(raw.get("rating_count", 0), "rating_count", 0),
            images=r.array(_first(raw, "images", "head_imgs", default=[]), "images"),
            created_at=r.time(_first(raw, "created_at", "create_time"), "created_at"),
        )
        for i, value in enumerate(r.array(raw.get("skus", []), "skus")):
            if not isinstance(value, dict):
                _warn(r.warnings, f"skus[{i}]", "object_invalid")
                continue
            result.skus.append(
                ProductSku(
                    sku_id=r.identifier(value.get("sku_id"), f"skus[{i}].sku_id"),
                    spec=str(_first(value, "spec", "spec_desc", default="")),
                    price=r.amount(value, ("price", "sale_price"), f"skus[{i}].price"),
                    stock=r.integer(_first(value, "stock", "stock_num", default=0), f"skus[{i}].stock", 0),
                )
            )
        return r.attach(result)

    def normalize_products(self, raw_list: list[dict], platform: str) -> list[UnifiedProduct]:
        return [self.normalize_product(raw, platform) for raw in raw_list]

    def _map_product_status(self, raw: Any, platform: str) -> str:
        value = str(raw).lower()
        if value in ("1", "on_sale", "已上架", "onsale"):
            return "on_sale"
        if value in ("0", "off_sale", "已下架", "offsale"):
            return "off_sale"
        return "unknown" if raw is None else str(raw)

    def normalize_refund(self, raw: dict, platform: str) -> UnifiedRefund:
        platform = normalize_platform(platform)
        r = self._record(raw, platform)
        if platform == "weixin" and ("after_sale_order" in raw or "after_sale_order_id" in raw):
            return self._weixin_refund(raw, r)
        if platform == "doudian":
            return self._doudian_refund(raw, r)
        if platform == "taobao":
            return self._taobao_refund(raw, r)
        if platform == "youzan":
            return self._youzan_refund(raw, r)
        prices = raw if "refund_amount" in raw or "amount" in raw else r.mapping(raw.get("refund_info"), "refund_info")
        result = UnifiedRefund(
            refund_id=r.identifier(_first(raw, "refund_id", "after_sale_order_id", "afsNo", "returnsId"), "refund_id"),
            order_id=r.identifier(_first(raw, "order_id", "order_sn", "orderId"), "order_id"),
            shop_id=r.identifier(_first(raw, "shop_id", "mall_id"), "shop_id"),
            platform=platform,
            status=normalize_refund_status(_first(raw, "refund_status", "status", "orderState"), platform),
            type=normalize_refund_type(_first(raw, "refund_type", "type", "serviceType"), platform),
            amount=r.amount(prices, ("refund_amount", "amount"), "amount"),
            reason=str(_first(raw, "reason", "reason_text", "afsReason", default="")),
            description=str(_first(raw, "description", "desc", default="")),
            evidence=r.array(_first(raw, "evidence", "media", "pic_urls", default=[]), "evidence"),
            applied_at=r.time(_first(raw, "apply_time", "create_at", "afsApplyTime", "applyTime"), "applied_at"),
            completed_at=r.time(_first(raw, "completed_at", "refund_time", "success_time"), "completed_at") or None,
        )
        if result.status == "unknown":
            _warn(r.warnings, "status", "status_unknown")
        return r.attach(result)

    @staticmethod
    def _weixin_time(value: Any, r: _Record, field_name: str) -> str:
        """Native shop timestamps are seconds; never infer milliseconds/civil time."""
        if value in (None, ""):
            return r.time(None, field_name)
        if not isinstance(value, int) or isinstance(value, bool) or not 0 < value < 100_000_000_000:
            _warn(r.warnings, field_name, "timestamp_invalid")
            return ""
        return r.time(value, field_name)

    @staticmethod
    def _weixin_order(raw: dict, r: _Record) -> UnifiedOrder:
        info = r.mapping(raw.get("order", raw), "order")
        detail = r.mapping(info.get("order_detail"), "order_detail")
        price = r.mapping(detail.get("price_info"), "price_info")
        pay = r.mapping(detail.get("pay_info"), "pay_info")
        present_value = info.get("order_present_info", {})
        present = r.mapping(present_value, "order_present_info")
        state = info.get("status")
        result = UnifiedOrder(
            order_id=r.identifier(info.get("order_id"), "order_id"),
            shop_id=r.identifier(raw.get("shop_id"), "shop_id"),
            platform="weixin",
            status=(
                "shipped"
                if isinstance(state, int) and not isinstance(state, bool) and state == 21
                else normalize_order_status(state, "weixin")
            ),
            status_raw=str(state),
            created_at=Normalizer._weixin_time(info.get("create_time"), r, "created_at"),
            updated_at=Normalizer._weixin_time(info.get("update_time"), r, "updated_at") or None,
            amount_total=r.amount(price, ("original_order_price",), "amount_total"),
            amount_discount=r.amount(price, ("discounted_price",), "amount_discount"),
            amount_shipping=r.amount(price, ("freight",), "amount_shipping"),
            amount_merchant_received=r.amount(price, ("merchant_receieve_price",), "amount_merchant_received"),
        )
        # Method 2 records pay-later confirmation; 3/4 record order creation.
        # None of those timestamps establishes an actual payment event.
        standard_payment = (
            isinstance(pay.get("payment_method"), int)
            and not isinstance(pay.get("payment_method"), bool)
            and pay["payment_method"] == 1
        )
        if (
            standard_payment
            and isinstance(present_value, dict)
            and ("is_b2c_free_present" not in present or present["is_b2c_free_present"] is False)
        ):
            result.amount_paid = r.amount(price, ("order_price",), "amount_paid")
            result.paid_at = Normalizer._weixin_time(pay.get("pay_time"), r, "paid_at") or None
        for field_name in (
            "amount_paid",
            "amount_total",
            "amount_discount",
            "amount_shipping",
            "amount_merchant_received",
        ):
            value = getattr(result, field_name)
            if value is not None and value < 0:
                setattr(result, field_name, None)
                _warn(r.warnings, field_name, "amount_invalid")
        if result.amount_paid is None:
            _warn(r.warnings, "amount_paid", "buyer_payment_unknown")
        if result.status == "paid" and (result.paid_at is None or result.amount_paid is None):
            result.status = "unknown"
        for i, item in enumerate(r.array(detail.get("product_infos"), "items")):
            if not isinstance(item, dict):
                _warn(r.warnings, f"items[{i}]", "object_invalid")
                continue
            prefix = f"items[{i}]"
            result.items.append(
                OrderItem(
                    product_id=r.identifier(item.get("product_id"), prefix + ".product_id"),
                    sku_id=r.identifier(item.get("sku_id"), prefix + ".sku_id"),
                    price=r.amount(item, ("sale_price",), prefix + ".price"),
                    quantity=r.integer(item.get("count"), prefix + ".quantity"),
                )
            )
        if result.status == "unknown":
            _warn(r.warnings, "status", "status_unknown")
        return r.attach(result)

    @staticmethod
    def _weixin_refund(raw: dict, r: _Record) -> UnifiedRefund:
        info = r.mapping(raw.get("after_sale_order", raw), "after_sale_order")
        kind, status = info.get("type"), info.get("status")
        success = (kind, status) in (("REFUND", "MERCHANT_REFUND_SUCCESS"), ("RETURN", "MERCHANT_RETURN_SUCCESS"))
        result = UnifiedRefund(
            refund_id=r.identifier(info.get("after_sale_order_id"), "refund_id"),
            order_id=r.identifier(info.get("order_id"), "order_id"),
            shop_id=r.identifier(raw.get("shop_id"), "shop_id"),
            platform="weixin",
            status="completed" if success else "unknown",
            type=normalize_refund_type(kind, "weixin"),
            applied_at=Normalizer._weixin_time(info.get("create_time"), r, "applied_at"),
            updated_at=Normalizer._weixin_time(info.get("update_time"), r, "updated_at") or None,
        )
        if success:
            amount = r.amount(r.mapping(info.get("refund_info"), "refund_info"), ("amount",), "amount")
            if amount is not None and amount < 0:
                amount = None
                _warn(r.warnings, "amount", "refund_amount_negative")
            result.amount = amount
            result.completed_at = Normalizer._weixin_time(info.get("complete_time"), r, "completed_at") or None
        else:
            _warn(r.warnings, "status", "status_unknown")
        return r.attach(result)

    @staticmethod
    def _jd_order(raw: dict, r: _Record) -> UnifiedOrder:
        """Modern JOS fields; legacy caller-supplied unit shapes stay separate."""
        info = r.mapping(raw.get("orderInfo", raw), "orderInfo")
        status = info.get("orderState")
        paid_time = info.get("paymentConfirmTime")
        if paid_time == "0001-01-01 00:00:00":
            paid_time = None
        result = UnifiedOrder(
            order_id=r.identifier(info.get("orderId"), "order_id"),
            shop_id=r.identifier(raw.get("shop_id"), "shop_id"),
            platform="jd",
            status=normalize_order_status(status, "jd"),
            status_raw=str(status),
            created_at=r.time(info.get("orderStartTime"), "created_at"),
            updated_at=r.time(info.get("modified"), "updated_at") or None,
            paid_at=r.time(paid_time, "paid_at") or None,
            amount_paid=r.amount(info, ("actualPay",), "amount_paid"),
            amount_shipping=r.amount(info, ("freightPrice",), "amount_shipping"),
        )
        # Goods-only totals and seller receivables do not establish order totals
        # or settled receipts. Due/stale payment fields never replace actualPay.
        if result.amount_paid is not None and result.amount_paid < 0:
            result.amount_paid = None
            _warn(r.warnings, "amount_paid", "amount_invalid")
        # This marker is documented only for Jingxi second-stage supply orders;
        # the detail contract explicitly excludes Jingxi from actualPay support.
        if info.get("tradeOrderId") not in (None, ""):
            result.amount_paid = None
        if result.amount_paid is None:
            _warn(r.warnings, "amount_paid", "buyer_payment_unknown")
        # Awaiting warehouse dispatch includes COD and other pay-later orders.
        if result.status == "paid" and (not result.paid_at or result.amount_paid is None):
            result.status = "unknown"
        for i, item in enumerate(r.array(info.get("itemInfoList"), "items")):
            if not isinstance(item, dict):
                _warn(r.warnings, f"items[{i}]", "object_invalid")
                continue
            prefix = f"items[{i}]"
            result.items.append(
                OrderItem(
                    product_id=r.identifier(item.get("wareId"), prefix + ".product_id"),
                    sku_id=r.identifier(item.get("skuId"), prefix + ".sku_id"),
                    price=r.amount(item, ("jdPrice",), prefix + ".price"),
                    quantity=r.integer(item.get("itemTotal"), prefix + ".quantity"),
                )
            )
        if result.status == "unknown":
            _warn(r.warnings, "status", "status_unknown")
        return r.attach(result)

    @staticmethod
    def _taobao_order(raw: dict, r: _Record) -> UnifiedOrder:
        status = _first(raw, "status", "order_status")
        result = UnifiedOrder(
            order_id=r.identifier(_first(raw, "tid", "order_id"), "order_id"),
            shop_id=r.identifier(raw.get("shop_id"), "shop_id"),
            platform="taobao",
            status=normalize_order_status(status, "taobao"),
            status_raw=str(status),
            created_at=r.time(_first(raw, "created", "create_time"), "created_at"),
            paid_at=r.time(raw.get("pay_time"), "paid_at") or None,
            updated_at=r.time(raw.get("modified"), "updated_at") or None,
            amount_total=r.amount(raw, ("total_fee",), "amount_total"),
            amount_discount=r.amount(raw, ("discount_fee",), "amount_discount"),
            amount_shipping=r.amount(raw, ("post_fee",), "amount_shipping"),
            amount_platform_payment=r.amount(raw, ("payment",), "amount_platform_payment"),
            amount_merchant_received=r.amount(raw, ("received_payment",), "amount_merchant_received"),
        )
        # Official money FAQ: current payment may already reflect a refund.
        # A current snapshot cannot recover the original buyer cash payment.
        _warn(r.warnings, "amount_paid", "buyer_payment_unknown")
        orders = r.mapping(raw.get("orders"), "items")
        for i, value in enumerate(r.array(orders.get("order"), "items")):
            if not isinstance(value, dict):
                _warn(r.warnings, f"items[{i}]", "object_invalid")
                continue
            prefix = f"items[{i}]"
            result.items.append(
                OrderItem(
                    product_id=r.identifier(value.get("num_iid"), prefix + ".product_id"),
                    sku_id=r.identifier(value.get("sku_id"), prefix + ".sku_id"),
                    price=r.amount(value, ("price",), prefix + ".price"),
                    quantity=r.integer(value.get("num"), prefix + ".quantity"),
                )
            )
        if result.status == "unknown":
            _warn(r.warnings, "status", "status_unknown")
        return r.attach(result)

    @staticmethod
    def _youzan_order(raw: dict, r: _Record) -> UnifiedOrder:
        outer = r.mapping(raw.get("data", raw), "order_info")
        full = r.mapping(outer.get("full_order_info", outer), "order_info")
        info = r.mapping(full.get("order_info"), "order_info")
        pay = r.mapping(full.get("pay_info"), "pay_info")
        status = info.get("status")
        result = UnifiedOrder(
            order_id=r.identifier(info.get("tid"), "order_id"),
            shop_id=r.identifier(info.get("node_kdt_id"), "shop_id"),
            platform="youzan",
            status=normalize_order_status(status, "youzan"),
            status_raw=str(status),
            created_at=r.time(info.get("created"), "created_at"),
            paid_at=r.time(info.get("pay_time"), "paid_at") or None,
            updated_at=r.time(info.get("update_time"), "updated_at") or None,
            amount_total=r.amount(pay, ("total_fee",), "amount_total"),
            amount_shipping=r.amount(pay, ("post_fee",), "amount_shipping"),
            amount_paid=r.amount(pay, ("real_payment",), "amount_paid"),
        )
        # `real_payment` is platform whole-order paid value, including stored-value
        # and gift-card orders. It is not bank cash or merchant settlement.
        # `payment` means different things in list and detail. Never substitute it.
        if result.amount_paid is None:
            _warn(r.warnings, "amount_paid", "buyer_payment_unknown")
        for i, value in enumerate(r.array(full.get("orders"), "items")):
            if not isinstance(value, dict):
                _warn(r.warnings, f"items[{i}]", "object_invalid")
                continue
            prefix = f"items[{i}]"
            result.items.append(
                OrderItem(
                    product_id=r.identifier(value.get("item_id"), prefix + ".product_id"),
                    sku_id=r.identifier(value.get("sku_id"), prefix + ".sku_id"),
                    price=r.amount(value, ("price",), prefix + ".price"),
                    quantity=r.integer(value.get("num"), prefix + ".quantity"),
                )
            )
        if result.status == "unknown":
            _warn(r.warnings, "status", "status_unknown")
        return r.attach(result)

    @staticmethod
    def _taobao_refund(raw: dict, r: _Record) -> UnifiedRefund:
        result = UnifiedRefund(
            refund_id=r.identifier(raw.get("refund_id"), "refund_id"),
            order_id=r.identifier(raw.get("tid"), "order_id"),
            shop_id=r.identifier(raw.get("shop_id"), "shop_id"),
            platform="taobao",
            status=normalize_refund_status(raw.get("status"), "taobao"),
            type=normalize_refund_type(raw.get("dispute_type"), "taobao"),
            applied_at=r.time(raw.get("created"), "applied_at"),
            updated_at=r.time(raw.get("modified"), "updated_at") or None,
        )
        if result.status == "completed" and result.type in {"refund_only", "return_and_refund"}:
            result.amount = r.amount(raw, ("refund_fee",), "amount")
            if result.amount is not None and result.amount < 0:
                result.amount = None
                _warn(r.warnings, "amount", "refund_amount_negative")
            # This is TOP refund completion, not a verified channel arrival time.
            result.completed_at = r.time(raw.get("end_time"), "completed_at") or None
        if result.status == "unknown":
            _warn(r.warnings, "status", "status_unknown")
        return r.attach(result)

    @staticmethod
    def _youzan_refund(raw: dict, r: _Record) -> UnifiedRefund:
        detail = "data" in raw or "refund_fund_list" in raw or "refund_account_time" in raw
        info = r.mapping(raw.get("data", raw), "refund_info")
        kind = "unknown"
        native_kind = info.get("refund_type")
        if isinstance(native_kind, str) and native_kind in {"EXCHANGE_GOODS", "OFFLINE_EXCHANGE_GOODS"}:
            kind = "exchange"
        elif (
            not detail
            and native_kind is None
            or isinstance(native_kind, str)
            and native_kind in {"BUYER_APPLY_REFUND", "SELLER_REFUND", "SYSTEM_REFUND"}
        ):
            if isinstance(info.get("return_goods"), bool):
                kind = "return_and_refund" if info["return_goods"] else "refund_only"
        if kind == "unknown":
            _warn(r.warnings, "type", "status_unknown")
        result = UnifiedRefund(
            refund_id=r.identifier(info.get("refund_id"), "refund_id"),
            order_id=r.identifier(info.get("tid"), "order_id"),
            shop_id=r.identifier(info.get("kdt_id"), "shop_id"),
            platform="youzan",
            status=normalize_refund_status(info.get("status"), "youzan"),
            type=kind,
            applied_at=r.time(info.get("created"), "applied_at"),
            updated_at=r.time(info.get("modified"), "updated_at") or None,
        )
        if not detail:
            result.amount_requested = r.amount(info, ("refund_fee",), "amount_requested")
            _warn(r.warnings, "amount", "refund_detail_required")
        elif result.status == "completed" and kind in {"refund_only", "return_and_refund"}:
            result.completed_at = r.time(info.get("refund_account_time"), "completed_at") or None
            Normalizer._youzan_funds(info, result, r)
        if result.status == "unknown":
            _warn(r.warnings, "status", "status_unknown")
        return r.attach(result)

    @staticmethod
    def _youzan_funds(info: dict, result: UnifiedRefund, r: _Record) -> None:
        funds = info.get("refund_fund_list")
        if not isinstance(funds, list) or not funds:
            _warn(r.warnings, "amount", "refund_funds_incomplete")
            return
        seen = set()
        total = 0
        for item in funds:
            if not isinstance(item, dict):
                _warn(r.warnings, "amount", "refund_funds_incomplete")
                return
            identifier = r.identifier(item.get("refund_no"), "amount")
            amount = item.get("refund_fee")  # Native integer fen, unlike the top-level yuan string.
            status = item.get("status")
            valid_status = isinstance(status, int) and not isinstance(status, bool) and status == 2
            valid_money = isinstance(amount, int) and not isinstance(amount, bool) and 0 <= amount < 2**63
            if (
                not identifier
                or identifier in seen
                or str(item.get("refund_id")) != result.refund_id
                or not valid_status
                or not valid_money
            ):
                _warn(r.warnings, "amount", "refund_funds_incomplete")
                return
            mode = item.get("refund_mode")
            channel = item.get("pay_way")
            # Platform-recorded refunds include gift/stored-value credits. Keep
            # every documented nonzero pay_way, without calling it bank cash.
            # Omit the whole amount if any channel is missing or unconfirmed.
            valid_channel = (
                isinstance(channel, int)
                and not isinstance(channel, bool)
                and channel
                in {
                    1,
                    2,
                    3,
                    5,
                    7,
                    8,
                    9,
                    10,
                    11,
                    12,
                    13,
                    14,
                    15,
                    16,
                    17,
                    18,
                    19,
                    20,
                    21,
                    22,
                    24,
                    25,
                    27,
                    28,
                    29,
                    30,
                    33,
                    35,
                    36,
                    37,
                    40,
                    72,
                    80,
                    90,
                    100,
                    101,
                    102,
                    103,
                    104,
                    105,
                    106,
                    107,
                    110,
                    111,
                    112,
                    113,
                    114,
                    115,
                    116,
                    117,
                    118,
                    119,
                    200,
                    201,
                    202,
                    203,
                    204,
                    300,
                    400,
                }
            )
            if not isinstance(mode, int) or isinstance(mode, bool) or mode != 0 or not valid_channel:
                _warn(r.warnings, "amount", "refund_channel_unknown")
                return
            seen.add(identifier)
            total += amount
        expected = r.amount(info, ("refund_fee",), "amount")
        if expected is None or expected != total or total >= 2**63:
            _warn(r.warnings, "amount", "refund_amount_mismatch")
            return
        result.amount = total

    @staticmethod
    def _doudian_refund(raw: dict, r: _Record) -> UnifiedRefund:
        """List amounts are requested; only successful detail contains payout."""
        is_list = "aftersale_info" in raw or raw.get("detail_required") is True
        info = safe_get(raw, "process_info", "after_sale_info")
        if info is None:
            info = raw.get("aftersale_info", raw)
        info = r.mapping(info, "after_sale_info")
        order_info = r.mapping(raw.get("order_info", raw), "order_info")
        status = normalize_refund_status(_first(info, "refund_status", "status"), "doudian")
        sale_type = _first(info, "after_sale_type", "aftersale_type")
        if sale_type is None and not is_list and "process_info" not in raw:
            # Legacy flattened input accepted descriptive Chinese labels.
            # The native numeric refund_type is a processing method, not this enum.
            if info.get("refund_type") in ("仅退款", "退货退款"):
                sale_type = info["refund_type"]
        result = UnifiedRefund(
            refund_id=r.identifier(_first(info, "after_sale_id", "aftersale_id", "refund_id"), "refund_id"),
            order_id=r.identifier(_first(order_info, "shop_order_id", "order_id"), "order_id"),
            shop_id=r.identifier(raw.get("shop_id"), "shop_id"),
            platform="doudian",
            status=status,
            type=normalize_refund_type(sale_type, "doudian"),
            amount_requested=r.amount(info, ("refund_total_amount", "refund_amount"), "amount_requested"),
            reason=str(_first(info, "reason", "reason_text", default="")),
            description=str(_first(info, "description", "desc", default="")),
            evidence=r.array(_first(info, "evidence", "media", "pic_urls", default=[]), "evidence"),
            applied_at=r.time(_first(info, "apply_time", "create_time"), "applied_at"),
            updated_at=r.time(info.get("update_time"), "updated_at") or None,
        )
        if status == "completed" and not is_list:
            result.amount = r.amount(info, ("real_refund_amount",), "amount")
            if result.amount is not None and result.amount < 0:
                result.amount = None
                _warn(r.warnings, "amount", "refund_amount_negative")
            result.completed_at = r.time(info.get("refund_time"), "completed_at") or None
        if is_list:
            _warn(r.warnings, "amount", "refund_detail_required")
        if status == "unknown":
            _warn(r.warnings, "status", "status_unknown")
        return r.attach(result)

    def normalize_refunds(self, raw_list: list[dict], platform: str) -> list[UnifiedRefund]:
        return [self.normalize_refund(raw, platform) for raw in raw_list]

    def normalize_review(self, raw: dict, platform: str) -> UnifiedReview:
        platform = normalize_platform(platform)
        r = self._record(raw, platform)
        return r.attach(
            UnifiedReview(
                review_id=r.identifier(_first(raw, "review_id", "comment_id"), "review_id"),
                product_id=r.identifier(_first(raw, "product_id", "item_id", "goods_id"), "product_id"),
                order_id=r.identifier(_first(raw, "order_id", "order_sn"), "order_id"),
                platform=platform,
                score=r.integer(raw.get("score", 0), "score", 0),
                content=str(_first(raw, "content", "comment", default="")),
                images=r.array(_first(raw, "images", "pic_urls", default=[]), "images"),
                user_name=str(_first(raw, "user_name", "buyer_nick", default="")),
                reply=str(raw.get("reply", "")),
                created_at=r.time(_first(raw, "create_time", "comment_time", "created_at"), "created_at"),
            )
        )

    def normalize_reviews(self, raw_list: list[dict], platform: str) -> list[UnifiedReview]:
        return [self.normalize_review(raw, platform) for raw in raw_list]

    def normalize_shop(self, raw: dict, platform: str) -> UnifiedShop:
        platform = normalize_platform(platform)
        r = self._record(raw, platform)
        scores = r.mapping(_first(raw, "scores", "dsr", default={}), "scores")
        return r.attach(
            UnifiedShop(
                shop_id=r.identifier(_first(raw, "shop_id", "mall_id"), "shop_id"),
                shop_name=str(_first(raw, "shop_name", "mall_name", default="")),
                platform=platform,
                type=str(_first(raw, "shop_type", "merchant_type", default="")),
                status=str(_first(raw, "shop_status", "status", default="")),
                score_overall=r.number(
                    _first(scores, "overall", "dsr_score", default=raw.get("dsr_score", 0)), "score_overall"
                ),
                score_product=r.number(
                    _first(scores, "product", "itemScore", default=raw.get("itemScore", 0)), "score_product"
                ),
                score_service=r.number(
                    _first(scores, "service", "serviceScore", default=raw.get("serviceScore", 0)), "score_service"
                ),
                score_logistics=r.number(
                    _first(scores, "logistics", "logisticsScore", default=raw.get("logisticsScore", 0)),
                    "score_logistics",
                ),
                product_count=r.integer(
                    _first(raw, "product_count", "goods_onsale_count", default=0), "product_count", 0
                ),
            )
        )
