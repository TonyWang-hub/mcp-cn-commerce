"""Current shop API fields, synthetic examples; no merchant live verification."""

from copy import deepcopy
from datetime import UTC, datetime

import pytest

from shared.normalizer import Normalizer

T = 1789030000
ISO = datetime.fromtimestamp(T, UTC).isoformat()


def order():
    return {
        "order_id": 3700000000000000001,
        "create_time": T - 60,
        "update_time": T + 60,
        "status": 20,
        "order_detail": {
            "pay_info": {"payment_method": 1, "pay_time": T},
            "price_info": {
                "order_price": 1230,
                "original_order_price": 1530,
                "product_price": 1300,
                "freight": 230,
                "discounted_price": 100,
                "merchant_receieve_price": 1430,
            },
            "product_infos": [{"product_id": 7, "sku_id": 8, "count": 2, "sale_price": 650}],
            "delivery_info": {"address_info": {"user_name": "PRIVATE"}},
        },
        "intra_city_order_info": {"shop_id": "STORE_LOCATION_NOT_MERCHANT"},
    }


@pytest.mark.parametrize("wrapped", [False, True])
def test_official_nested_order_uses_paid_timestamp_and_fen_without_subsidy_addition(wrapped):
    value = order()
    before = deepcopy(value)
    raw = {"order": value, "shop_id": "opaque-store"} if wrapped else {**value, "shop_id": "opaque-store"}
    got = Normalizer().normalize_order(raw, "weixin_store")
    assert got.order_id == "3700000000000000001" and got.shop_id == "opaque-store"
    assert got.amount_paid == 1230 and got.paid_at == ISO and got.status == "paid"
    assert got.amount_total == 1530 and got.amount_shipping == 230 and got.amount_merchant_received == 1430
    assert got.updated_at == datetime.fromtimestamp(T + 60, UTC).isoformat()
    assert [(x.product_id, x.sku_id, x.price, x.quantity) for x in got.items] == [("7", "8", 650, 2)]
    assert got.buyer_name == "" and value == before


@pytest.mark.parametrize("method", [None, 2, 3, 4, 99, True, "1"])
def test_nonordinary_or_unknown_payment_does_not_create_paid_amount_or_event(method):
    value = order()
    value["order_detail"]["pay_info"]["payment_method"] = method
    got = Normalizer().normalize_order(value, "weixin_store")
    assert got.paid_at is None and got.amount_paid is None and got.status == "unknown"
    assert any(w["code"] == "buyer_payment_unknown" for w in got.warnings)


def test_free_merchant_gift_is_not_a_payment_even_with_inconsistent_pay_info():
    value = order()
    value["order_present_info"] = {"is_b2c_free_present": True}
    got = Normalizer().normalize_order(value, "weixin")
    assert got.paid_at is None and got.amount_paid is None and got.status == "unknown"


@pytest.mark.parametrize("time", [None, 0, True, T * 1000, "2026-09-10 08:00:00"])
def test_payment_time_requires_positive_documented_epoch_seconds(time):
    value = order()
    value["order_detail"]["pay_info"]["pay_time"] = time
    got = Normalizer().normalize_order(value, "weixin")
    assert got.paid_at is None and got.status == "unknown"


def refund(status="MERCHANT_REFUND_SUCCESS", kind="REFUND"):
    return {
        "after_sale_order_id": "900",
        "order_id": "3700000000000000001",
        "status": status,
        "type": kind,
        "create_time": T - 60,
        "update_time": T + 60,
        "complete_time": T,
        "refund_info": {"amount": 300, "platform_discount_return_amount": 200},
        "refund_resp": {"ret": 0, "code": "", "message": "PRIVATE"},
    }


@pytest.mark.parametrize("status,kind", [("MERCHANT_REFUND_SUCCESS", "REFUND"), ("MERCHANT_RETURN_SUCCESS", "RETURN")])
def test_completed_refund_requires_matching_type_and_uses_complete_time(status, kind):
    got = Normalizer().normalize_refund({"after_sale_order": refund(status, kind), "shop_id": "opaque"}, "weixin")
    assert (got.refund_id, got.order_id, got.shop_id) == ("900", "3700000000000000001", "opaque")
    assert got.status == "completed" and got.amount == 300 and got.completed_at == ISO
    assert got.updated_at == datetime.fromtimestamp(T + 60, UTC).isoformat()


@pytest.mark.parametrize(
    "status,kind",
    [
        ("PLATFORM_REFUNDING", "REFUND"),
        ("PLATFORM_REFUND_FAIL", "REFUND"),
        ("MERCHANT_REFUND_RETRY_FAIL", "REFUND"),
        ("MERCHANT_EXCHANGE_SUCCESS", "EXCHANGE"),
        ("MERCHANT_REFUND_SUCCESS", "RETURN"),
        ("MERCHANT_RETURN_SUCCESS", "REFUND"),
        ("NEW_STATUS", "REFUND"),
    ],
)
def test_other_aftersale_states_are_not_successful_refunds(status, kind):
    got = Normalizer().normalize_refund(refund(status, kind), "weixin")
    assert got.status != "completed" and got.amount is None and got.completed_at is None


@pytest.mark.parametrize("completed", [None, 0, True, T * 1000])
def test_refund_missing_completion_never_uses_update_time(completed):
    value = refund()
    value["complete_time"] = completed
    got = Normalizer().normalize_refund(value, "weixin")
    assert got.amount == 300 and got.completed_at is None


@pytest.mark.parametrize("amount", [None, -1, True, 1.5, "NaN"])
def test_refund_invalid_amount_remains_unknown(amount):
    value = refund()
    value["refund_info"]["amount"] = amount
    got = Normalizer().normalize_refund(value, "weixin")
    assert got.amount is None


def test_partial_shipment_is_not_a_payment_state():
    value = order()
    value["status"] = 21
    got = Normalizer().normalize_order(value, "weixin")
    assert got.status == "shipped"


@pytest.mark.parametrize("flag", [0, "", "true", None, [], {}])
def test_invalid_present_flag_never_establishes_normal_payment(flag):
    value = order()
    value["order_present_info"] = {"is_b2c_free_present": flag}
    got = Normalizer().normalize_order(value, "weixin")
    assert got.amount_paid is None and got.paid_at is None and got.status == "unknown"
