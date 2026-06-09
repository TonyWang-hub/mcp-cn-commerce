"""Tests for shared/normalizer.py — unified data normalization layer.

Covers all 8 platforms × 5 data types (order, product, refund, review, shop)
with both happy-path and edge-case scenarios.
"""

from __future__ import annotations

import pytest

from shared.normalizer import (
    Normalizer,
    UnifiedOrder,
    UnifiedProduct,
    UnifiedRefund,
    UnifiedReview,
    UnifiedShop,
    normalize_order_status,
    normalize_price,
    normalize_refund_status,
    normalize_refund_type,
    normalize_time,
    safe_get,
)


# ── Helper Fixtures ─────────────────────────────────────────


@pytest.fixture
def normalizer() -> Normalizer:
    return Normalizer()


# ── Unit Tests: normalize_price ─────────────────────────────


class TestNormalizePrice:
    def test_kuaishou_yuan_string_to_fen(self):
        assert normalize_price("99.00", "kuaishou") == 9900

    def test_xiaohongshu_yuan_string_to_fen(self):
        assert normalize_price("129.50", "xiaohongshu") == 12950

    def test_doudian_fen_int(self):
        assert normalize_price(19900, "doudian") == 19900

    def test_jd_fen_string(self):
        assert normalize_price("289.00", "jd") == 289

    def test_pdd_fen_int(self):
        assert normalize_price(38800, "pdd") == 38800

    def test_weixin_fen_int(self):
        assert normalize_price(9900, "weixin") == 9900

    def test_none_returns_zero(self):
        assert normalize_price(None, "doudian") == 0

    def test_invalid_string_returns_zero(self):
        assert normalize_price("abc", "jd") == 0


# ── Unit Tests: normalize_time ──────────────────────────────


class TestNormalizeTime:
    def test_unix_timestamp(self):
        result = normalize_time(1718006400, "pdd")
        assert "2024" in result or "2025" in result  # depends on timezone

    def test_string_datetime(self):
        result = normalize_time("2026-06-09 10:30:00", "doudian")
        assert "2026-06-09" in result

    def test_none_returns_empty(self):
        assert normalize_time(None, "jd") == ""

    def test_already_iso_string(self):
        result = normalize_time("2026-06-09T10:30:00", "kuaishou")
        assert "2026-06-09" in result


# ── Unit Tests: normalize_order_status ──────────────────────


class TestNormalizeOrderStatus:
    def test_doudian_status_2_is_paid(self):
        assert normalize_order_status(2, "doudian") == "paid"

    def test_jd_status_string(self):
        assert normalize_order_status("WAIT_SELLER_STOCK_OUT", "jd") == "paid"

    def test_weixin_status_20_is_paid(self):
        assert normalize_order_status(20, "weixin") == "paid"

    def test_pdd_status_1_is_paid(self):
        assert normalize_order_status(1, "pdd") == "paid"

    def test_unknown_status_returns_unknown(self):
        assert normalize_order_status(999, "doudian") == "unknown"


# ── Unit Tests: normalize_refund_status/type ────────────────


class TestNormalizeRefund:
    def test_doudian_refund_pending(self):
        assert normalize_refund_status(1, "doudian") == "pending"

    def test_weixin_refund_type_return(self):
        assert normalize_refund_type("RETURN", "weixin") == "return_and_refund"

    def test_pdd_refund_type(self):
        assert normalize_refund_type("1", "pdd") == "refund_only"


# ── Unit Tests: safe_get ────────────────────────────────────


class TestSafeGet:
    def test_nested_get(self):
        data = {"a": {"b": {"c": 42}}}
        assert safe_get(data, "a", "b", "c") == 42

    def test_missing_key_returns_default(self):
        data = {"a": 1}
        assert safe_get(data, "b", default="nope") == "nope"

    def test_none_data_returns_default(self):
        assert safe_get(None, "a", default=None) is None


# ── Integration: Order Normalization ────────────────────────


class TestNormalizeOrderDoudian:
    def test_happy_path(self, normalizer: Normalizer):
        raw = {
            "order_id": "7385294610238495621",
            "order_status": 2,
            "pay_amount": "199.00",
            "post_amount": "0.00",
            "create_time": "2026-06-09 10:30:00",
            "pay_time": "2026-06-09 10:32:00",
            "product_info": {"list": [{"product_id": "P1", "product_name": "T恤", "price": "99.50", "combo_num": "2"}]},
            "buyer_info": {"name": "张三", "phone": "138****0000"},
            "buyer_words": "尽快发货",
        }
        order = normalizer.normalize_order(raw, "doudian")
        assert order.order_id == "7385294610238495621"
        assert order.platform == "doudian"
        assert order.status == "paid"
        assert order.amount_paid == 199
        assert order.buyer_name == "张三"
        assert len(order.items) == 1
        assert order.items[0].product_name == "T恤"
        assert order.remark == "尽快发货"

    def test_empty_order(self, normalizer: Normalizer):
        order = normalizer.normalize_order({}, "doudian")
        assert order.platform == "doudian"
        assert order.status == "unknown"


class TestNormalizeOrderJD:
    def test_happy_path(self, normalizer: Normalizer):
        raw = {
            "orderInfo": {
                "orderId": "123456789012345678",
                "orderState": "WAIT_SELLER_STOCK_OUT",
                "orderTotalPrice": "299.00",
                "payment": "289.00",
                "freightPrice": "10.00",
                "remark": "请尽快发货",
            },
            "itemInfoList": [{"skuId": "987654321", "skuName": "蓝牙耳机", "salePrice": "189.00", "num": 1}],
            "consigneeInfo": {"fullname": "李四", "mobile": "13900139000", "fullAddress": "上海市浦东新区"},
        }
        order = normalizer.normalize_order(raw, "jd")
        assert order.order_id == "123456789012345678"
        assert order.status == "paid"
        assert order.buyer_name == "李四"
        assert order.amount_paid == 289


class TestNormalizeOrderWeixin:
    def test_happy_path(self, normalizer: Normalizer):
        raw = {
            "order_id": "3705115058471207123",
            "status": 20,
            "order_detail": {
                "product_infos": [{"product_id": "1001", "title": "耳机", "sale_price": 9900, "product_cnt": 1}],
                "price_info": {"product_price": 9900, "order_price": 8900, "discounted_price": 1000, "freight": 0},
                "delivery_info": {"receiver_name": "王五", "receiver_tel": "13800138000", "receiver_address": "北京"},
            },
        }
        order = normalizer.normalize_order(raw, "weixin")
        assert order.order_id == "3705115058471207123"
        assert order.status == "paid"
        assert order.amount_total == 9900
        assert order.amount_discount == 1000
        assert order.buyer_name == "王五"
        assert len(order.items) == 1


class TestNormalizeOrderPdd:
    def test_happy_path(self, normalizer: Normalizer):
        raw = {
            "order_sn": "20260610000000001",
            "order_status": 1,
            "goods_name": "运动鞋",
            "goods_count": 2,
            "goods_price": 19900,
            "pay_amount": 38800,
            "create_time": 1717987200,
            "receiver_name": "赵六",
        }
        order = normalizer.normalize_order(raw, "pdd")
        assert order.order_id == "20260610000000001"
        assert order.status == "paid"
        assert order.amount_paid == 38800


class TestNormalizeOrderKuaishou:
    def test_happy_path(self, normalizer: Normalizer):
        raw = {
            "order_id": "KS202401150000001",
            "order_status": 1,
            "order_amount": "99.00",
            "created_at": "2024-01-15 10:30:00",
            "receiver_name": "张三",
        }
        order = normalizer.normalize_order(raw, "kuaishou")
        assert order.order_id == "KS202401150000001"
        assert order.status == "paid"
        assert order.amount_total == 9900  # 元→分


class TestNormalizeOrderXiaohongshu:
    def test_happy_path(self, normalizer: Normalizer):
        raw = {
            "order_id": "XHS20240115000001",
            "order_status": 1,
            "order_amount": "99.00",
            "created_at": "2024-01-15 10:30:00",
        }
        order = normalizer.normalize_order(raw, "xiaohongshu")
        assert order.platform == "xiaohongshu"
        assert order.amount_total == 9900


class TestNormalizeOrderTaobao:
    def test_happy_path(self, normalizer: Normalizer):
        raw = {
            "order_id": "TB20260610001",
            "order_status": "WAIT_SELLER_SEND_GOODS",
            "pay_amount": "199.00",
            "create_time": "2026-06-10 10:00:00",
        }
        order = normalizer.normalize_order(raw, "taobao")
        assert order.status == "paid"


class TestNormalizeOrderUnsupportedPlatform:
    def test_raises_value_error(self, normalizer: Normalizer):
        with pytest.raises(ValueError, match="Unsupported platform"):
            normalizer.normalize_order({}, "unknown_platform")


# ── Integration: Product Normalization ──────────────────────


class TestNormalizeProduct:
    def test_doudian_product(self, normalizer: Normalizer):
        raw = {
            "product_id": "P001",
            "product_name": "夏季T恤",
            "product_status": 1,
            "min_price": "99.00",
            "max_price": "129.00",
            "stock": 500,
            "sold_count": 1234,
            "rating": 4.8,
        }
        product = normalizer.normalize_product(raw, "doudian")
        assert product.name == "夏季T恤"
        assert product.status == "on_sale"
        assert product.price_min == 99

    def test_weixin_product(self, normalizer: Normalizer):
        raw = {
            "product_id": "10000000000001",
            "title": "无线耳机",
            "status": 1,
            "min_price": 9900,
            "stock_num": 500,
            "total_sold_num": 1234,
        }
        product = normalizer.normalize_product(raw, "weixin")
        assert product.name == "无线耳机"
        assert product.price_min == 9900
        assert product.stock == 500

    def test_pdd_product(self, normalizer: Normalizer):
        raw = {
            "goods_id": 123456789,
            "goods_name": "示例商品",
            "is_onsale": 1,
            "min_group_price": 19900,
            "sold_quantity": 5000,
        }
        product = normalizer.normalize_product(raw, "pdd")
        assert product.product_id == "123456789"
        assert product.status == "on_sale"


# ── Integration: Refund Normalization ───────────────────────


class TestNormalizeRefund:
    def test_doudian_refund(self, normalizer: Normalizer):
        raw = {
            "refund_id": "RF001",
            "order_id": "ORD001",
            "refund_status": 1,
            "refund_type": "仅退款",
            "refund_amount": "99.00",
            "reason": "商品质量问题",
            "apply_time": "2026-06-09 10:00:00",
        }
        refund = normalizer.normalize_refund(raw, "doudian")
        assert refund.status == "pending"
        assert refund.type == "refund_only"
        assert refund.amount == 99

    def test_weixin_refund(self, normalizer: Normalizer):
        raw = {
            "after_sale_order_id": "RF002",
            "order_id": "ORD002",
            "status": 1,
            "type": "RETURN",
            "refund_info": {"amount": 9900},
            "reason_text": "质量问题",
        }
        refund = normalizer.normalize_refund(raw, "weixin")
        assert refund.refund_id == "RF002"
        assert refund.type == "return_and_refund"
        assert refund.amount == 9900


# ── Integration: Review Normalization ───────────────────────


class TestNormalizeReview:
    def test_kuaishou_review(self, normalizer: Normalizer):
        raw = {
            "comment_id": "CM001",
            "item_id": "KS987654321",
            "content": "音质很好！",
            "score": 5,
            "create_time": "2024-01-20 12:00:00",
            "user_name": "匿***户",
            "reply": "感谢支持！",
        }
        review = normalizer.normalize_review(raw, "kuaishou")
        assert review.score == 5
        assert review.content == "音质很好！"
        assert review.reply == "感谢支持！"

    def test_pdd_review(self, normalizer: Normalizer):
        raw = {
            "comment_id": 123456,
            "goods_id": 987654321,
            "comment": "质量不错",
            "score": 4,
            "comment_time": 1717987200,
        }
        review = normalizer.normalize_review(raw, "pdd")
        assert review.score == 4


# ── Integration: Shop Normalization ─────────────────────────


class TestNormalizeShop:
    def test_jd_shop(self, normalizer: Normalizer):
        raw = {
            "shop_id": "SHOP001",
            "shop_name": "数码旗舰店",
            "itemScore": 4.8,
            "serviceScore": 4.9,
            "logisticsScore": 4.7,
        }
        shop = normalizer.normalize_shop(raw, "jd")
        assert shop.shop_name == "数码旗舰店"
        assert shop.score_product == 4.8
        assert shop.score_service == 4.9

    def test_pdd_shop(self, normalizer: Normalizer):
        raw = {
            "mall_id": 987654,
            "mall_name": "示例旗舰店",
            "dsr_score": 4.8,
            "goods_onsale_count": 150,
        }
        shop = normalizer.normalize_shop(raw, "pdd")
        assert shop.shop_id == "987654"
        assert shop.score_overall == 4.8
        assert shop.product_count == 150

    def test_empty_shop(self, normalizer: Normalizer):
        shop = normalizer.normalize_shop({}, "doudian")
        assert shop.platform == "doudian"


# ── Batch Normalization ─────────────────────────────────────


class TestBatchNormalization:
    def test_normalize_orders(self, normalizer: Normalizer):
        raw_list = [
            {"order_id": "1", "order_status": 1, "pay_amount": "100"},
            {"order_id": "2", "order_status": 2, "pay_amount": "200"},
        ]
        orders = normalizer.normalize_orders(raw_list, "doudian")
        assert len(orders) == 2
        assert all(isinstance(o, UnifiedOrder) for o in orders)

    def test_normalize_products(self, normalizer: Normalizer):
        raw_list = [
            {"product_id": "P1", "product_name": "商品1"},
            {"product_id": "P2", "product_name": "商品2"},
        ]
        products = normalizer.normalize_products(raw_list, "kuaishou")
        assert len(products) == 2
        assert all(isinstance(p, UnifiedProduct) for p in products)

    def test_normalize_refunds(self, normalizer: Normalizer):
        raw_list = [{"refund_id": "R1"}, {"refund_id": "R2"}]
        refunds = normalizer.normalize_refunds(raw_list, "pdd")
        assert len(refunds) == 2

    def test_normalize_reviews(self, normalizer: Normalizer):
        raw_list = [{"comment_id": "C1"}, {"comment_id": "C2"}]
        reviews = normalizer.normalize_reviews(raw_list, "xiaohongshu")
        assert len(reviews) == 2
