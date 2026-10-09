"""Reviewed JOS order fields; synthetic official shapes, not live merchant data."""

from copy import deepcopy

import pytest

from shared.normalizer import Normalizer

DATE = "2026-09-10 08:00:05"
ISO = "2026-09-10T08:00:05+08:00"


def order():
    return {
        "orderId": "123",
        "venderId": "456",
        "orderState": "WAIT_GOODS_RECEIVE_CONFIRM",
        "orderStartTime": DATE,
        "modified": DATE,
        "paymentConfirmTime": "2026-09-09 07:00:00",
        "actualPay": "12.30",
        "shouldPay": "15.00",
        "orderPayment": "99.00",
        "totalOriginalPrice": "20.00",
        "totalSellerReceivable": "10.00",
        "freightPrice": "2.30",
        "payType": "99",
        "itemInfoList": [{"wareId": "7", "skuId": "8", "jdPrice": "5.50", "itemTotal": "2"}],
    }


@pytest.mark.parametrize("wrapped", [False, True])
def test_jd_actual_pay_and_confirmation_time_have_reviewed_platform_semantics(wrapped):
    raw = order()
    before = deepcopy(raw)
    result = Normalizer(source_timezone="Asia/Shanghai").normalize_order({"orderInfo": raw} if wrapped else raw, "jd")
    assert result.order_id == "123" and result.shop_id == ""  # venderId is never a shop ID.
    assert result.amount_paid == 1230 and result.amount_shipping == 230
    assert result.amount_total is None and result.amount_merchant_received is None
    assert result.paid_at == "2026-09-09T07:00:00+08:00"  # Gift payment can precede creation.
    assert result.created_at == result.updated_at == ISO
    assert [(x.product_id, x.sku_id, x.price, x.quantity) for x in result.items] == [("7", "8", 550, 2)]
    assert raw == before


@pytest.mark.parametrize("payment", [None, "", "bad", True, "NaN", "1.001", "-1.00"])
def test_missing_invalid_jd_actual_pay_never_uses_due_or_legacy_amount(payment):
    raw = order()
    raw["actualPay"] = payment
    result = Normalizer(source_timezone="Asia/Shanghai").normalize_order(raw, "jd")
    assert result.amount_paid is None
    assert any(w["code"] == "buyer_payment_unknown" for w in result.warnings)


@pytest.mark.parametrize("pay_type", ["1", "12", "20", "21"])
@pytest.mark.parametrize("state", ["WAIT_SELLER_STOCK_OUT", "DengDaiChuKu"])
def test_jd_unpaid_time_sentinel_and_fulfilment_status_do_not_create_payment_date(pay_type, state):
    raw = order()
    raw["paymentConfirmTime"] = "0001-01-01 00:00:00"
    raw["orderState"] = state
    raw["payType"] = pay_type
    result = Normalizer(source_timezone="Asia/Shanghai").normalize_order(raw, "jd")
    assert result.paid_at is None
    assert result.status == "unknown" and result.status_raw == state


def test_jd_warehouse_status_with_time_but_unknown_paid_amount_stays_unknown():
    raw = order()
    raw["orderState"] = "WAIT_SELLER_STOCK_OUT"
    raw["actualPay"] = None
    result = Normalizer(source_timezone="Asia/Shanghai").normalize_order(raw, "jd")
    assert result.paid_at and result.status == "unknown"


def test_jd_known_jingxi_trade_order_cannot_use_unsupported_actual_pay_field():
    raw = order()
    raw["tradeOrderId"] = "98765"
    result = Normalizer(source_timezone="Asia/Shanghai").normalize_order(raw, "jd")
    assert result.amount_paid is None
    assert any(w["code"] == "buyer_payment_unknown" for w in result.warnings)


@pytest.mark.parametrize(
    "state,expected",
    [
        ("NOT_PAY", "pending"),
        ("DengDaiChuKu", "paid"),
        ("DengDaiQueRenShouHuo", "shipped"),
        ("WanCheng", "completed"),
        ("TRADE_CANCELED", "cancelled"),
        ("LOCKED", "unknown"),
        ("POP_ORDER_PAUSE", "unknown"),
        ("DELIVERY_RETURN", "unknown"),
    ],
)
def test_jd_status_aliases_do_not_invent_payment_or_refund(state, expected):
    raw = order()
    raw["orderState"] = state
    result = Normalizer(source_timezone="Asia/Shanghai").normalize_order(raw, "jd")
    assert result.status == expected


def test_jd_native_shape_does_not_assume_timezone_or_emit_buyer_fields():
    raw = order()
    raw["consigneeInfo"] = {"fullname": "PRIVATE_NAME", "mobile": "PRIVATE_PHONE"}
    result = Normalizer().normalize_order(raw, "jd")
    assert result.updated_at == "2026-09-10T08:00:05"
    assert any(w["code"] == "timezone_missing" for w in result.warnings)
    assert result.buyer_name == result.buyer_phone == ""
