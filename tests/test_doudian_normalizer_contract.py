"""Current DouDian monetary and status contracts, not synthetic alias semantics."""

from dataclasses import asdict

import pytest

from shared.normalizer import Normalizer, normalize_order_status


def order(**changes):
    return {
        "order_id": "123",
        "shop_id": "10",
        "order_status": 5,
        "pay_amount": 1100,
        "promotion_pay_amount": 100,
        "order_amount": 1200,
        "promotion_amount": 100,
        "post_amount": 0,
        "actual_receive_amount_info": {"actual_receive_amount": 1050},
        "create_time": 1789027200,
        "pay_time": 1789027230,
        "update_time": 1789027500,
        "sku_order_list": [
            {
                "product_id": "456",
                "sku_id": "789",
                "origin_amount": 600,
                "item_num": 2,
                "product_pic": "https://example.com/product.png",
            }
        ],
        **changes,
    }


def refund(**changes):
    return {
        "shop_id": "10",
        "order_info": {"shop_order_id": 123},
        "process_info": {
            "after_sale_info": {
                "after_sale_id": 456,
                "after_sale_type": 0,
                "refund_status": 3,
                "refund_total_amount": 1000,
                "real_refund_amount": 950,
                "apply_time": 1789027200,
                "refund_time": 1789027600,
                **changes,
            }
        },
    }


@pytest.mark.parametrize("raw,expected", [(4, "cancelled"), (5, "completed"), (105, "paid"), (101, "shipped")])
def test_current_order_status_contract(raw, expected):
    assert normalize_order_status(raw, "doudian") == expected


def test_payment_metrics_remain_distinct_and_native_skus_survive():
    result = Normalizer().normalize_order(order(), "doudian")
    assert result.amount_paid == 1000
    assert result.amount_platform_payment == 1100
    assert result.amount_merchant_received == 1050
    assert result.amount_total == 1200
    assert result.amount_discount == 100
    assert result.updated_at == "2026-09-10T08:05:00+00:00"
    assert result.items[0].quantity == 2 and result.items[0].price == 600
    assert result.items[0].image_url == "https://example.com/product.png"


@pytest.mark.parametrize("promotion", [None, True, -1, 1101, "bad"])
def test_unavailable_or_invalid_payment_discount_never_becomes_zero(promotion):
    result = Normalizer().normalize_order(order(promotion_pay_amount=promotion), "doudian")
    assert result.amount_paid is None
    assert any(warning["field"] == "amount_paid" for warning in result.warnings)


def test_missing_discount_and_total_are_unknown_not_payment_aliases():
    raw = order()
    del raw["promotion_pay_amount"]
    del raw["order_amount"]
    result = Normalizer().normalize_order(raw, "doudian")
    assert result.amount_paid is None and result.amount_total is None


def test_explicit_zero_discount_is_valid():
    assert Normalizer().normalize_order(order(promotion_pay_amount=0), "doudian").amount_paid == 1100


def test_actual_refund_detail_uses_real_amount_and_success_time():
    result = Normalizer().normalize_refund(refund(), "doudian")
    assert result.refund_id == "456" and result.order_id == "123"
    assert result.amount == 950 and result.amount_requested == 1000
    assert result.status == "completed" and result.type == "return_and_refund"
    assert result.completed_at == "2026-09-10T08:06:40+00:00"


@pytest.mark.parametrize("status", [1, 2, 4, 5])
def test_non_success_refund_cannot_contribute_paid_out_amount(status):
    result = Normalizer().normalize_refund(refund(refund_status=status), "doudian")
    assert result.amount is None and result.completed_at is None
    assert result.status != "completed"


def test_missing_real_refund_never_uses_requested_amount():
    result = Normalizer().normalize_refund(refund(real_refund_amount=None), "doudian")
    assert result.amount is None and result.amount_requested == 1000


def test_negative_success_refund_is_unknown_with_warning():
    result = Normalizer().normalize_refund(refund(real_refund_amount=-100), "doudian")
    assert result.amount is None and any(w["field"] == "amount" for w in result.warnings)


def test_native_refund_processing_method_cannot_supply_after_sale_type():
    raw = refund(refund_type=1)
    del raw["process_info"]["after_sale_info"]["after_sale_type"]
    assert Normalizer().normalize_refund(raw, "doudian").type == "unknown"


def test_list_shape_is_explicitly_incomplete_until_detail():
    result = Normalizer().normalize_refund(
        {
            "order_info": {"shop_order_id": "123"},
            "aftersale_info": {
                "aftersale_id": "456",
                "refund_status": 3,
                "refund_amount": 1000,
                "apply_time": 1789027200,
                "aftersale_status_to_final_time": 1789027600,
            },
        },
        "doudian",
    )
    assert result.refund_id == "456" and result.order_id == "123"
    assert result.amount is None and result.completed_at is None
    assert "refund_detail_required" in {w["code"] for w in result.warnings}
    assert "refund_time" not in str(asdict(result).get("source_values", {}).get("completed_at"))


def test_legacy_refund_descriptive_fields_remain_available_to_core_callers():
    result = Normalizer().normalize_refund(
        {
            "refund_id": "1",
            "order_id": "2",
            "refund_status": 3,
            "real_refund_amount": 100,
            "reason": "damaged",
            "description": "broken package",
            "evidence": ["proof"],
        },
        "doudian",
    )
    assert result.reason == "damaged" and result.description == "broken package"
    assert result.evidence == ["proof"] and result.amount == 100
