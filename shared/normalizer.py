"""Unified data normalizer for Chinese e-commerce platform responses.

Converts platform-specific API responses from all 8 supported platforms
into a common schema so workflow templates can consume them uniformly.

Supported platforms:
  oceanengine, doudian, jd, pdd, kuaishou, xiaohongshu, weixin, taobao

Usage::

    from shared.normalizer import Normalizer

    n = Normalizer()
    order = n.normalize_order(raw_response, platform="doudian")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# ── Platform Constants ──────────────────────────────────────

PLATFORMS = frozenset({
    "oceanengine",
    "doudian",
    "jd",
    "pdd",
    "kuaishou",
    "xiaohongshu",
    "weixin",
    "taobao",
})


# ── Unified Data Classes ────────────────────────────────────


@dataclass
class OrderItem:
    """A single item within an order."""

    product_id: str = ""
    product_name: str = ""
    sku_id: str = ""
    sku_name: str = ""
    price: int = 0  # 分 (cents)
    quantity: int = 0
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
    amount_total: int = 0  # 分
    amount_discount: int = 0  # 分
    amount_shipping: int = 0  # 分
    amount_paid: int = 0  # 分
    buyer_name: str = ""
    buyer_phone: str = ""
    buyer_address: str = ""
    items: list[OrderItem] = field(default_factory=list)
    remark: str = ""


@dataclass
class ProductSku:
    """A single SKU variant of a product."""

    sku_id: str = ""
    spec: str = ""
    price: int = 0  # 分
    stock: int = 0


@dataclass
class UnifiedProduct:
    """Platform-agnostic product representation."""

    product_id: str = ""
    platform: str = ""
    name: str = ""
    status: str = ""  # on_sale|off_sale|audit|rejected
    category: str = ""
    price_min: int = 0  # 分
    price_max: int = 0  # 分
    stock: int = 0
    sold_count: int = 0
    rating: float = 0.0
    rating_count: int = 0
    images: list[str] = field(default_factory=list)
    skus: list[ProductSku] = field(default_factory=list)
    created_at: str = ""


@dataclass
class UnifiedRefund:
    """Platform-agnostic refund representation."""

    refund_id: str = ""
    order_id: str = ""
    platform: str = ""
    status: str = ""  # pending|processing|approved|rejected|completed
    type: str = ""  # refund_only|return_and_refund
    amount: int = 0  # 分
    reason: str = ""
    description: str = ""
    evidence: list[str] = field(default_factory=list)
    applied_at: str = ""


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


# ── Normalization Helpers ───────────────────────────────────


def normalize_price(value: Any, platform: str) -> int:
    """Convert platform price to 分 (cents).

    Platforms using 元 as string: kuaishou, xiaohongshu
    Platforms using 分 as int: doudian, jd, pdd, weixin
    oceanengine: mixed, caller should check field context
    taobao: 分

    Args:
        value: Raw price value (str, int, or float).
        platform: Platform identifier.

    Returns:
        Price in 分 (cents). Returns 0 on failure.
    """
    if value is None:
        return 0
    try:
        if platform in ("kuaishou", "xiaohongshu"):
            # 元 string → 分
            return int(float(value) * 100)
        elif platform in ("doudian", "jd", "pdd", "weixin", "taobao"):
            # already in 分
            return int(float(value))
        elif platform == "oceanengine":
            # mixed — assume 分 by default, caller overrides if needed
            return int(float(value))
        else:
            return int(float(value))
    except (ValueError, TypeError):
        logger.warning(f"Failed to normalize price {value!r} for {platform}")
        return 0


def normalize_time(value: Any, platform: str) -> str:
    """Convert platform timestamp to ISO 8601 string.

    Args:
        value: Raw timestamp (int Unix seconds, or string).
        platform: Platform identifier.

    Returns:
        ISO 8601 string. Returns raw str(value) on failure.
    """
    if value is None:
        return ""
    try:
        if isinstance(value, int | float) and value > 1_000_000_000:
            # Unix timestamp
            return datetime.fromtimestamp(value, tz=UTC).isoformat()
        if isinstance(value, str):
            # Already a string — try common formats
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(value, fmt)
                    return dt.replace(tzinfo=UTC).isoformat()
                except ValueError:
                    continue
            return value  # return as-is if no format matches
        return str(value)
    except (ValueError, TypeError, OSError):
        logger.warning(f"Failed to normalize time {value!r} for {platform}")
        return str(value) if value else ""


# Order status mapping per platform → unified status
_ORDER_STATUS_MAP: dict[str, dict[str | int, str]] = {
    "doudian": {
        1: "pending",
        2: "paid",
        3: "shipped",
        4: "completed",
        5: "cancelled",
    },
    "jd": {
        "WAIT_SELLER_STOCK_OUT": "paid",
        "WAIT_GOODS_RECEIVE_CONFIRM": "shipped",
        "FINISHED_L": "completed",
        "TRADE_CANCELED": "cancelled",
        "LOCKED": "paid",
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
        1: "paid",
        2: "shipped",
        3: "completed",
        4: "refunding",
        5: "cancelled",
    },
    "weixin": {
        10: "pending",
        20: "paid",
        30: "shipped",
        50: "completed",
        100: "cancelled",
    },
    "taobao": {
        "WAIT_BUYER_PAY": "pending",
        "WAIT_SELLER_SEND_GOODS": "paid",
        "WAIT_BUYER_CONFIRM_GOODS": "shipped",
        "TRADE_BUYER_SIGNED": "completed",
        "TRADE_FINISHED": "completed",
        "TRADE_CLOSED": "cancelled",
    },
    "oceanengine": {
        "ADVERTISER_STATUS_ENABLE": "completed",
        "ADVERTISER_STATUS_DISABLE": "cancelled",
    },
}

# Refund status mapping per platform → unified status
_REFUND_STATUS_MAP: dict[str, dict[str | int, str]] = {
    "doudian": {1: "pending", 2: "processing", 3: "completed", 4: "rejected"},
    "jd": {
        "WAIT_PROCESS": "pending",
        "PROCESSING": "processing",
        "FINISHED": "completed",
        "REFUSED": "rejected",
    },
    "pdd": {1: "pending", 2: "processing", 3: "completed", 4: "rejected", 5: "completed"},
    "kuaishou": {1: "pending", 2: "completed", 3: "rejected"},
    "xiaohongshu": {1: "pending", 2: "processing", 3: "completed", 4: "rejected"},
    "weixin": {1: "pending", 2: "processing", 3: "completed", 4: "rejected"},
    "taobao": {
        "WAIT_SELLER_AGREE": "pending",
        "SELLER_AGREE_BUYER_RETURN": "processing",
        "WAIT_BUYER_RETURN": "processing",
        "CLOSED": "rejected",
        "SUCCESS": "completed",
    },
}

# Refund type mapping
_REFUND_TYPE_MAP: dict[str, dict[str, str]] = {
    "doudian": {"仅退款": "refund_only", "退货退款": "return_and_refund"},
    "jd": {"退款": "refund_only", "退换货": "return_and_refund"},
    "pdd": {"1": "refund_only", "2": "return_and_refund"},
    "kuaishou": {"仅退款": "refund_only", "退货退款": "return_and_refund"},
    "xiaohongshu": {"仅退款": "refund_only", "退货退款": "return_and_refund"},
    "weixin": {"REFUND": "refund_only", "RETURN": "return_and_refund"},
    "taobao": {"仅退款": "refund_only", "退货退款": "return_and_refund"},
}


def normalize_order_status(raw: Any, platform: str) -> str:
    """Map platform-specific order status to unified status.

    Args:
        raw: Raw status value from API.
        platform: Platform identifier.

    Returns:
        Unified status string.
    """
    mapping = _ORDER_STATUS_MAP.get(platform, {})
    result = mapping.get(raw)
    if result:
        return result
    # Try string conversion
    result = mapping.get(str(raw))
    if result:
        return result
    logger.warning(f"Unknown order status {raw!r} for {platform}")
    return "unknown"


def normalize_refund_status(raw: Any, platform: str) -> str:
    """Map platform-specific refund status to unified status."""
    mapping = _REFUND_STATUS_MAP.get(platform, {})
    result = mapping.get(raw)
    if result:
        return result
    result = mapping.get(str(raw))
    if result:
        return result
    logger.warning(f"Unknown refund status {raw!r} for {platform}")
    return "unknown"


def normalize_refund_type(raw: Any, platform: str) -> str:
    """Map platform-specific refund type to unified type."""
    mapping = _REFUND_TYPE_MAP.get(platform, {})
    result = mapping.get(str(raw))
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


class Normalizer:
    """Converts platform-specific API responses to unified schemas.

    Usage::

        n = Normalizer()
        order = n.normalize_order(raw, platform="doudian")
        orders = n.normalize_orders(raw_list, platform="jd")
    """

    def validate_platform(self, platform: str) -> None:
        """Raise ValueError if platform is not supported."""
        if platform not in PLATFORMS:
            raise ValueError(
                f"Unsupported platform '{platform}'. "
                f"Supported: {', '.join(sorted(PLATFORMS))}"
            )

    # ── Order ───────────────────────────────────────────────

    def normalize_order(self, raw: dict, platform: str) -> UnifiedOrder:
        """Convert a single platform order response to UnifiedOrder.

        Args:
            raw: Raw order dict from platform API.
            platform: Platform identifier.

        Returns:
            UnifiedOrder instance.
        """
        self.validate_platform(platform)
        try:
            handler = getattr(self, f"_normalize_order_{platform}", None)
            if handler:
                return handler(raw)
            return self._normalize_order_generic(raw, platform)
        except Exception as exc:
            logger.warning(f"Order normalization failed for {platform}: {exc}")
            return UnifiedOrder(
                order_id=str(raw.get("order_id", raw.get("order_sn", ""))),
                platform=platform,
                status="unknown",
                status_raw=str(raw.get("order_status", "")),
            )

    def normalize_orders(self, raw_list: list[dict], platform: str) -> list[UnifiedOrder]:
        """Convert a list of platform orders to UnifiedOrder list."""
        return [self.normalize_order(o, platform) for o in raw_list]

    def _normalize_order_generic(self, raw: dict, platform: str) -> UnifiedOrder:
        """Generic order normalizer for platforms with standard structure."""
        return UnifiedOrder(
            order_id=str(raw.get("order_id", raw.get("order_sn", ""))),
            platform=platform,
            status=normalize_order_status(raw.get("order_status"), platform),
            status_raw=str(raw.get("order_status", "")),
            created_at=normalize_time(raw.get("create_time", raw.get("created_at")), platform),
            paid_at=normalize_time(raw.get("pay_time", raw.get("paid_at")), platform) or None,
            amount_total=normalize_price(
                raw.get("order_amount", raw.get("total_amount", raw.get("order_total_price"))),
                platform,
            ),
            amount_discount=normalize_price(raw.get("discount_amount", raw.get("seller_discount")), platform),
            amount_shipping=normalize_price(raw.get("post_amount", raw.get("postage", raw.get("freight_price"))), platform),
            amount_paid=normalize_price(raw.get("pay_amount", raw.get("payment")), platform),
            buyer_name=str(safe_get(raw, "buyer_info", "name", default=raw.get("receiver_name", ""))),
            buyer_phone=str(safe_get(raw, "buyer_info", "phone", default=raw.get("receiver_phone", ""))),
            buyer_address=str(raw.get("receiver_address", safe_get(raw, "consigneeInfo", "fullAddress", default=""))),
            items=self._extract_items(raw, platform),
            remark=str(raw.get("buyer_words", raw.get("remark", ""))),
        )

    def _normalize_order_doudian(self, raw: dict) -> UnifiedOrder:
        """Doudian-specific order normalizer."""
        items_data = safe_get(raw, "product_info", "list", default=[])
        items = []
        for item in (items_data or []):
            items.append(OrderItem(
                product_id=str(item.get("product_id", "")),
                product_name=str(item.get("product_name", "")),
                sku_id=str(item.get("sku_id", "")),
                sku_name=str(item.get("spec_desc", "")),
                price=normalize_price(item.get("price"), "doudian"),
                quantity=int(item.get("combo_num", 1)),
                image_url=str(item.get("img", "")),
            ))
        return UnifiedOrder(
            order_id=str(raw.get("order_id", "")),
            platform="doudian",
            status=normalize_order_status(raw.get("order_status"), "doudian"),
            status_raw=str(raw.get("order_status", "")),
            created_at=normalize_time(raw.get("create_time"), "doudian"),
            paid_at=normalize_time(raw.get("pay_time"), "doudian") or None,
            amount_total=normalize_price(raw.get("pay_amount"), "doudian"),
            amount_discount=normalize_price(raw.get("discount_amount"), "doudian"),
            amount_shipping=normalize_price(raw.get("post_amount"), "doudian"),
            amount_paid=normalize_price(raw.get("pay_amount"), "doudian"),
            buyer_name=str(safe_get(raw, "buyer_info", "name", default="")),
            buyer_phone=str(safe_get(raw, "buyer_info", "phone", default="")),
            buyer_address=str(raw.get("receiver_address", "")),
            items=items,
            remark=str(raw.get("buyer_words", "")),
        )

    def _normalize_order_jd(self, raw: dict) -> UnifiedOrder:
        """JD-specific order normalizer."""
        order_info = raw.get("orderInfo", raw)
        items_data = raw.get("itemInfoList", [])
        consignee = raw.get("consigneeInfo", {})
        items = []
        for item in (items_data or []):
            items.append(OrderItem(
                product_id=str(item.get("skuId", "")),
                product_name=str(item.get("skuName", "")),
                sku_id=str(item.get("outerSkuId", "")),
                sku_name="",
                price=normalize_price(item.get("salePrice", item.get("jdPrice")), "jd"),
                quantity=int(item.get("num", 1)),
                image_url="",
            ))
        return UnifiedOrder(
            order_id=str(order_info.get("orderId", "")),
            platform="jd",
            status=normalize_order_status(order_info.get("orderState"), "jd"),
            status_raw=str(order_info.get("orderState", "")),
            created_at=normalize_time(order_info.get("orderStartTime"), "jd"),
            paid_at=None,
            amount_total=normalize_price(order_info.get("orderTotalPrice"), "jd"),
            amount_discount=normalize_price(order_info.get("sellerDiscount"), "jd"),
            amount_shipping=normalize_price(order_info.get("freightPrice"), "jd"),
            amount_paid=normalize_price(order_info.get("payment"), "jd"),
            buyer_name=str(consignee.get("fullname", "")),
            buyer_phone=str(consignee.get("mobile", "")),
            buyer_address=str(consignee.get("fullAddress", "")),
            items=items,
            remark=str(order_info.get("remark", "")),
        )

    def _normalize_order_weixin(self, raw: dict) -> UnifiedOrder:
        """WeChat Store-specific order normalizer."""
        detail = raw.get("order_detail", raw)
        price_info = detail.get("price_info", {})
        delivery = detail.get("delivery_info", {})
        products = detail.get("product_infos", [])
        items = []
        for p in (products or []):
            items.append(OrderItem(
                product_id=str(p.get("product_id", "")),
                product_name=str(p.get("title", "")),
                sku_id=str(p.get("sku_id", "")),
                sku_name="",
                price=normalize_price(p.get("sale_price"), "weixin"),
                quantity=int(p.get("product_cnt", 1)),
                image_url=str(p.get("thumb_img", "")),
            ))
        return UnifiedOrder(
            order_id=str(raw.get("order_id", "")),
            platform="weixin",
            status=normalize_order_status(raw.get("status"), "weixin"),
            status_raw=str(raw.get("status", "")),
            created_at=normalize_time(detail.get("create_time"), "weixin"),
            paid_at=normalize_time(detail.get("pay_time"), "weixin") or None,
            amount_total=normalize_price(price_info.get("product_price"), "weixin"),
            amount_discount=normalize_price(price_info.get("discounted_price"), "weixin"),
            amount_shipping=normalize_price(price_info.get("freight"), "weixin"),
            amount_paid=normalize_price(price_info.get("order_price"), "weixin"),
            buyer_name=str(delivery.get("receiver_name", "")),
            buyer_phone=str(delivery.get("receiver_tel", "")),
            buyer_address=str(delivery.get("receiver_address", "")),
            items=items,
            remark=str(raw.get("remark", "")),
        )

    def _extract_items(self, raw: dict, platform: str) -> list[OrderItem]:
        """Extract order items from raw response using platform-specific keys."""
        items_raw = (
            raw.get("items")
            or raw.get("item_list")
            or raw.get("goods_list")
            or safe_get(raw, "product_info", "list")
            or []
        )
        items = []
        for it in (items_raw or []):
            items.append(OrderItem(
                product_id=str(it.get("product_id", it.get("item_id", it.get("goods_id", it.get("product_id"))))),
                product_name=str(it.get("product_name", it.get("item_name", it.get("goods_name", it.get("title", ""))))),
                sku_id=str(it.get("sku_id", "")),
                sku_name=str(it.get("sku_name", it.get("spec_desc", it.get("spec", "")))),
                price=normalize_price(it.get("price", it.get("sale_price", it.get("item_price"))), platform),
                quantity=int(it.get("num", it.get("quantity", it.get("product_cnt", it.get("combo_num", 1))))),
                image_url=str(it.get("image", it.get("thumb_img", it.get("thumb_url", "")))),
            ))
        return items

    # ── Product ─────────────────────────────────────────────

    def normalize_product(self, raw: dict, platform: str) -> UnifiedProduct:
        """Convert a single platform product to UnifiedProduct."""
        self.validate_platform(platform)
        try:
            handler = getattr(self, f"_normalize_product_{platform}", None)
            if handler:
                return handler(raw)
            return self._normalize_product_generic(raw, platform)
        except Exception as exc:
            logger.warning(f"Product normalization failed for {platform}: {exc}")
            return UnifiedProduct(
                product_id=str(raw.get("product_id", raw.get("goods_id", raw.get("wareId", "")))),
                platform=platform,
                name=str(raw.get("product_name", raw.get("goods_name", raw.get("wareTitle", "")))),
                status="unknown",
            )

    def normalize_products(self, raw_list: list[dict], platform: str) -> list[UnifiedProduct]:
        """Convert a list of platform products to UnifiedProduct list."""
        return [self.normalize_product(p, platform) for p in raw_list]

    def _normalize_product_generic(self, raw: dict, platform: str) -> UnifiedProduct:
        """Generic product normalizer."""
        return UnifiedProduct(
            product_id=str(raw.get("product_id", raw.get("goods_id", raw.get("item_id", "")))),
            platform=platform,
            name=str(raw.get("product_name", raw.get("goods_name", raw.get("item_name", "")))),
            status=self._map_product_status(raw.get("product_status", raw.get("goods_status", raw.get("is_onsale"))), platform),
            category=str(raw.get("category_name", "")),
            price_min=normalize_price(raw.get("min_price", raw.get("min_group_price")), platform),
            price_max=normalize_price(raw.get("max_price", raw.get("market_price")), platform),
            stock=int(raw.get("stock", raw.get("stock_num", 0))),
            sold_count=int(raw.get("sold_count", raw.get("sold_quantity", raw.get("total_sold_num", 0)))),
            rating=float(raw.get("rating", raw.get("dsr_score", 0))),
            rating_count=int(raw.get("rating_count", 0)),
            images=list(raw.get("images", raw.get("head_imgs", []))),
            skus=self._extract_skus(raw, platform),
            created_at=normalize_time(raw.get("created_at", raw.get("create_time")), platform),
        )

    def _normalize_product_weixin(self, raw: dict) -> UnifiedProduct:
        """WeChat Store product normalizer (price in 分)."""
        return UnifiedProduct(
            product_id=str(raw.get("product_id", "")),
            platform="weixin",
            name=str(raw.get("title", raw.get("product_name", ""))),
            status=self._map_product_status(raw.get("status"), "weixin"),
            category=str(raw.get("category_name", "")),
            price_min=normalize_price(raw.get("min_price"), "weixin"),
            price_max=normalize_price(raw.get("min_price"), "weixin"),
            stock=int(raw.get("stock_num", 0)),
            sold_count=int(raw.get("total_sold_num", 0)),
            rating=float(raw.get("rating", 0)),
            rating_count=int(raw.get("rating_count", 0)),
            images=list(raw.get("head_imgs", [])),
            skus=self._extract_skus(raw, "weixin"),
            created_at=normalize_time(raw.get("create_time"), "weixin"),
        )

    def _map_product_status(self, raw: Any, platform: str) -> str:
        """Map product status to unified value."""
        if raw is None:
            return "unknown"
        if raw == 1 or raw == "1" or str(raw).lower() == "on_sale":
            return "on_sale"
        if raw == 0 or raw == "0" or str(raw).lower() == "off_sale":
            return "off_sale"
        if str(raw).lower() in ("已上架", "onsale"):
            return "on_sale"
        if str(raw).lower() in ("已下架", "offsale"):
            return "off_sale"
        return str(raw)

    def _extract_skus(self, raw: dict, platform: str) -> list[ProductSku]:
        """Extract SKU list from raw product data."""
        skus_raw = raw.get("skus", [])
        result = []
        for s in (skus_raw or []):
            result.append(ProductSku(
                sku_id=str(s.get("sku_id", "")),
                spec=str(s.get("spec", s.get("spec_desc", ""))),
                price=normalize_price(s.get("price", s.get("sale_price")), platform),
                stock=int(s.get("stock", s.get("stock_num", 0))),
            ))
        return result

    # ── Refund ──────────────────────────────────────────────

    def normalize_refund(self, raw: dict, platform: str) -> UnifiedRefund:
        """Convert a single platform refund to UnifiedRefund."""
        self.validate_platform(platform)
        try:
            return UnifiedRefund(
                refund_id=str(raw.get("refund_id", raw.get("after_sale_order_id", raw.get("afsNo", "")))),
                order_id=str(raw.get("order_id", raw.get("order_sn", raw.get("orderId", "")))),
                platform=platform,
                status=normalize_refund_status(
                    raw.get("refund_status", raw.get("status", raw.get("orderState"))),
                    platform,
                ),
                type=normalize_refund_type(
                    raw.get("refund_type", raw.get("type", raw.get("serviceType"))),
                    platform,
                ),
                amount=normalize_price(
                    raw.get("refund_amount", safe_get(raw, "refund_info", "amount", default=raw.get("amount"))),
                    platform,
                ),
                reason=str(raw.get("reason", raw.get("reason_text", raw.get("afsReason", "")))),
                description=str(raw.get("description", raw.get("desc", ""))),
                evidence=list(raw.get("evidence", raw.get("media", raw.get("pic_urls", [])))),
                applied_at=normalize_time(
                    raw.get("apply_time", raw.get("create_at", raw.get("afsApplyTime"))),
                    platform,
                ),
            )
        except Exception as exc:
            logger.warning(f"Refund normalization failed for {platform}: {exc}")
            return UnifiedRefund(
                refund_id=str(raw.get("refund_id", "")),
                platform=platform,
                status="unknown",
            )

    def normalize_refunds(self, raw_list: list[dict], platform: str) -> list[UnifiedRefund]:
        """Convert a list of platform refunds to UnifiedRefund list."""
        return [self.normalize_refund(r, platform) for r in raw_list]

    # ── Review ──────────────────────────────────────────────

    def normalize_review(self, raw: dict, platform: str) -> UnifiedReview:
        """Convert a single platform review to UnifiedReview."""
        self.validate_platform(platform)
        try:
            return UnifiedReview(
                review_id=str(raw.get("review_id", raw.get("comment_id", ""))),
                product_id=str(raw.get("product_id", raw.get("item_id", raw.get("goods_id", "")))),
                order_id=str(raw.get("order_id", raw.get("order_sn", ""))),
                platform=platform,
                score=int(raw.get("score", 0)),
                content=str(raw.get("content", raw.get("comment", ""))),
                images=list(raw.get("images", raw.get("pic_urls", []))),
                user_name=str(raw.get("user_name", raw.get("buyer_nick", ""))),
                reply=str(raw.get("reply", "")),
                created_at=normalize_time(
                    raw.get("create_time", raw.get("comment_time", raw.get("created_at"))),
                    platform,
                ),
            )
        except Exception as exc:
            logger.warning(f"Review normalization failed for {platform}: {exc}")
            return UnifiedReview(
                review_id=str(raw.get("review_id", raw.get("comment_id", ""))),
                platform=platform,
            )

    def normalize_reviews(self, raw_list: list[dict], platform: str) -> list[UnifiedReview]:
        """Convert a list of platform reviews to UnifiedReview list."""
        return [self.normalize_review(r, platform) for r in raw_list]

    # ── Shop ────────────────────────────────────────────────

    def normalize_shop(self, raw: dict, platform: str) -> UnifiedShop:
        """Convert a single platform shop to UnifiedShop."""
        self.validate_platform(platform)
        try:
            scores = raw.get("scores", raw.get("dsr", {}))
            if isinstance(scores, dict) and scores:
                score_overall = float(scores.get("overall", scores.get("dsr_score", raw.get("dsr_score", 0))))
                score_product = float(scores.get("product", scores.get("itemScore", raw.get("itemScore", 0))))
                score_service = float(scores.get("service", scores.get("serviceScore", raw.get("serviceScore", 0))))
                score_logistics = float(scores.get("logistics", scores.get("logisticsScore", raw.get("logisticsScore", 0))))
            else:
                score_overall = float(raw.get("dsr_score", 0))
                score_product = float(raw.get("itemScore", 0))
                score_service = float(raw.get("serviceScore", 0))
                score_logistics = float(raw.get("logisticsScore", 0))

            return UnifiedShop(
                shop_id=str(raw.get("shop_id", raw.get("mall_id", ""))),
                shop_name=str(raw.get("shop_name", raw.get("mall_name", ""))),
                platform=platform,
                type=str(raw.get("shop_type", raw.get("merchant_type", ""))),
                status=str(raw.get("shop_status", raw.get("status", ""))),
                score_overall=score_overall,
                score_product=score_product,
                score_service=score_service,
                score_logistics=score_logistics,
                product_count=int(raw.get("product_count", raw.get("goods_onsale_count", 0))),
            )
        except Exception as exc:
            logger.warning(f"Shop normalization failed for {platform}: {exc}")
            return UnifiedShop(
                shop_id=str(raw.get("shop_id", "")),
                platform=platform,
            )
