"""Official TOP / Youzan money and identity shapes, never merchant live fixtures."""

from copy import deepcopy

import pytest

from shared.normalizer import Normalizer

DATE = "2026-09-10 08:00:00"
ISO = "2026-09-10T08:00:00+08:00"


def top_order():
    return {
        "tid": 101,
        "status": "TRADE_CLOSED",
        "payment": "6.00",
        "received_payment": "5.00",
        "created": DATE,
        "modified": DATE,
        "pay_time": DATE,
        "shop_id": "123",
        "total_fee": "12.00",
        "post_fee": "1.00",
        "discount_fee": "2.00",
        "orders": {"order": [{"oid": 999, "num_iid": 7, "sku_id": 8, "price": "4.05", "num": 3}]},
    }


def yz_order(*, detail=True):
    pay = {"payment": "12.00", "total_fee": "10.00", "post_fee": "2.00"}
    if detail:
        pay["real_payment"] = "11.00"
    return {
        "full_order_info": {
            "order_info": {
                "tid": "E123",
                "node_kdt_id": 123,
                "root_kdt_id": 456,
                "status": "TRADE_SUCCESS",
                "created": DATE,
                "pay_time": DATE,
                "update_time": DATE,
            },
            "pay_info": pay,
            "orders": [{"item_id": 7, "sku_id": 0, "price": "5.00", "num": 2}],
        }
    }


def yz_refund():
    return {
        "data": {
            "refund_id": "51",
            "tid": "E123",
            "kdt_id": 123,
            "status": "SUCCESS",
            "refund_type": "BUYER_APPLY_REFUND",
            "return_goods": False,
            "refund_fee": "11.00",
            "created": DATE,
            "modified": DATE,
            "refund_account_time": DATE,
            "refund_success_time": "2026-09-09 08:00:00",
            "refund_fund_list": [
                {"refund_no": "1", "refund_id": "51", "refund_fee": 600, "status": 2, "refund_mode": 0, "pay_way": 1},
                {"refund_no": "2", "refund_id": "51", "refund_fee": 500, "status": 2, "refund_mode": 0, "pay_way": 1},
            ],
        }
    }


def warning(result, code):
    return any(item["code"] == code for item in result.warnings)


def test_top_payment_is_current_not_original_buyer_cash():
    result = Normalizer(source_timezone="Asia/Shanghai").normalize_order(top_order(), "taobao")
    assert result.order_id == "101" and result.shop_id == "123" and result.status == "closed"
    assert result.amount_paid is None and warning(result, "buyer_payment_unknown")
    assert result.amount_platform_payment == 600 and result.amount_merchant_received == 500
    assert (result.amount_total, result.amount_shipping, result.amount_discount) == (1200, 100, 200)
    assert result.paid_at == result.updated_at == ISO
    assert [(x.product_id, x.sku_id, x.price, x.quantity) for x in result.items] == [("7", "8", 405, 3)]


@pytest.mark.parametrize(
    "status,expected",
    [
        ("TRADE_CLOSED", "closed"),
        ("TRADE_CLOSED_BY_TAOBAO", "cancelled"),
        ("SELLER_CONSIGNED_PART", "shipped"),
        ("TRADE_NO_CREATE_PAY", "pending"),
        ("PAID_FORBID_CONSIGN", "paid"),
    ],
)
def test_top_status_semantics(status, expected):
    raw = top_order()
    raw["status"] = status
    assert Normalizer().normalize_order(raw, "taobao").status == expected


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("REFUND", "refund_only"),
        ("REFUND_AND_RETURN", "return_and_refund"),
        ("TMALL_EXCHANGE", "exchange"),
        ("TAOBAO_EXCHANGE", "exchange"),
        ("REPAIR", "repair"),
        ("RESHIPPING", "reship"),
    ],
)
def test_top_refund_types_success_and_end_time(kind, expected):
    raw = {
        "refund_id": 51,
        "tid": 101,
        "status": "SUCCESS",
        "dispute_type": kind,
        "refund_fee": "3.21",
        "created": DATE,
        "modified": DATE,
        "end_time": "2026-09-09 07:00:00",
    }
    result = Normalizer(source_timezone="Asia/Shanghai").normalize_refund(raw, "taobao")
    assert result.refund_id == "51" and result.order_id == "101" and result.type == expected
    assert result.amount == (321 if kind in {"REFUND", "REFUND_AND_RETURN"} else None)
    assert result.completed_at == ("2026-09-09T07:00:00+08:00" if result.amount is not None else None)
    assert result.updated_at == ISO


@pytest.mark.parametrize(
    "status",
    [
        "WAIT_SELLER_AGREE",
        "WAIT_BUYER_RETURN_GOODS",
        "WAIT_SELLER_CONFIRM_GOODS",
        "SELLER_REFUSE_BUYER",
        "CLOSED",
        "invented",
    ],
)
def test_top_non_success_does_not_count_actual_refund(status):
    result = Normalizer().normalize_refund(
        {"refund_id": 1, "tid": 2, "status": status, "dispute_type": "REFUND", "refund_fee": "8", "modified": DATE},
        "taobao",
    )
    assert result.amount is None and result.completed_at is None


def test_top_missing_end_time_does_not_use_modified():
    result = Normalizer().normalize_refund(
        {"refund_id": 1, "tid": 2, "status": "SUCCESS", "dispute_type": "REFUND", "refund_fee": "8", "modified": DATE},
        "taobao",
    )
    assert result.completed_at is None and result.updated_at == "2026-09-10T08:00:00"


def test_youzan_detail_real_payment_not_due_payment_and_node_identity():
    result = Normalizer(source_timezone="Asia/Shanghai").normalize_order(yz_order(), "youzan")
    assert result.order_id == "E123" and result.shop_id == "123" and result.status == "completed"
    assert result.amount_paid == 1100 and result.amount_total == 1000 and result.amount_shipping == 200
    assert result.amount_platform_payment is None
    assert result.paid_at == result.updated_at == ISO
    assert [(x.product_id, x.sku_id, x.price, x.quantity) for x in result.items] == [("7", "0", 500, 2)]


def test_youzan_list_payment_alone_not_buyer_cash():
    result = Normalizer().normalize_order(yz_order(detail=False), "youzan")
    assert result.amount_paid is None and warning(result, "buyer_payment_unknown")
    assert warning(result, "timezone_missing")


def test_youzan_refund_fund_fen_not_yuan_and_account_time_not_success_time():
    result = Normalizer(source_timezone="Asia/Shanghai").normalize_refund(yz_refund(), "youzan")
    assert result.refund_id == "51" and result.order_id == "E123" and result.shop_id == "123"
    assert result.amount == 1100 and result.amount_requested is None and result.type == "refund_only"
    assert result.completed_at == result.updated_at == ISO


@pytest.mark.parametrize(
    "channel",
    [None, 0, -1, 999, True, "1", {}, [], 1.0],
)
@pytest.mark.parametrize("mixed", [False, True])
def test_youzan_original_route_unknown_or_mixed_unknown_channels_do_not_become_actual_money(channel, mixed):
    raw = yz_refund()
    funds = raw["data"]["refund_fund_list"]
    for item in funds[1:] if mixed else funds:
        if channel is None:
            item.pop("pay_way")
        else:
            item["pay_way"] = channel
    result = Normalizer(source_timezone="Asia/Shanghai").normalize_refund(raw, "youzan")
    assert result.amount is None
    assert warning(result, "refund_channel_unknown")


@pytest.mark.parametrize(
    "channel",
    [
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
    ],
)
@pytest.mark.parametrize("mixed", [False, True])
def test_youzan_reviewed_channels_include_non_cash_and_mixed_platform_refunds(channel, mixed):
    raw = yz_refund()
    funds = raw["data"]["refund_fund_list"]
    for item in funds[1:] if mixed else funds:
        item["pay_way"] = channel
    result = Normalizer(source_timezone="Asia/Shanghai").normalize_refund(raw, "youzan")
    assert result.amount == 1100 and not warning(result, "refund_channel_unknown")


@pytest.mark.parametrize("pay_type", [25, 28, 33, 35, 90, 116, 202])
def test_youzan_real_payment_keeps_platform_definition_for_non_cash_orders(pay_type):
    raw = yz_order()
    raw["full_order_info"]["order_info"]["pay_type"] = pay_type
    result = Normalizer(source_timezone="Asia/Shanghai").normalize_order(raw, "youzan")
    assert result.amount_paid == 1100  # Platform whole-order paid value, not bank cash settlement.


@pytest.mark.parametrize(
    "problem",
    [
        "missing",
        "empty",
        "pending",
        "failed",
        "duplicate",
        "wrong_refund",
        "fraction",
        "negative",
        "mismatch",
        "marked",
        "cash",
        "unknown_mode",
        "exchange",
    ],
)
def test_youzan_ambiguous_funds_never_make_actual_money(problem):
    raw = yz_refund()
    data = raw["data"]
    funds = data["refund_fund_list"]
    if problem == "missing":
        data.pop("refund_fund_list")
    if problem == "empty":
        data["refund_fund_list"] = []
    if problem == "pending":
        funds[1]["status"] = 0
    if problem == "failed":
        funds[1]["status"] = 1
    if problem == "duplicate":
        funds[1]["refund_no"] = "1"
    if problem == "wrong_refund":
        funds[1]["refund_id"] = "99"
    if problem == "fraction":
        funds[1]["refund_fee"] = 500.5
    if problem == "negative":
        funds[1]["refund_fee"] = -500
    if problem == "mismatch":
        data["refund_fee"] = "20.00"
    if problem == "marked":
        funds[1]["refund_mode"] = 2
    if problem == "cash":
        funds[1]["refund_mode"] = 1
    if problem == "unknown_mode":
        funds[1].pop("refund_mode")
    if problem == "exchange":
        data["refund_type"] = "EXCHANGE_GOODS"
    result = Normalizer(source_timezone="Asia/Shanghai").normalize_refund(raw, "youzan")
    assert result.amount is None


def test_youzan_list_refund_is_only_requested_and_no_date_substitution():
    data = deepcopy(yz_refund()["data"])
    for key in ("refund_fund_list", "refund_account_time", "refund_success_time"):
        data.pop(key)
    result = Normalizer().normalize_refund(data, "youzan")
    assert result.amount_requested == 1100 and result.amount is None and result.completed_at is None
    assert warning(result, "refund_detail_required")
    detail = yz_refund()
    detail["data"].pop("refund_account_time")
    result = Normalizer().normalize_refund(detail, "youzan")
    assert result.completed_at is None


@pytest.mark.parametrize("platform,raw", [("taobao", top_order()), ("youzan", yz_order())])
def test_no_input_mutation_or_implicit_timezone(platform, raw):
    before = deepcopy(raw)
    result = Normalizer().normalize_order(raw, platform)
    assert raw == before and result.updated_at == "2026-09-10T08:00:00"
    assert warning(result, "timezone_missing")


@pytest.mark.parametrize("value", [[], {}, True, "UNREVIEWED_KIND"])
def test_youzan_invalid_refund_type_does_not_become_cash_from_return_goods(value):
    raw = yz_refund()
    raw["data"]["refund_type"] = value
    result = Normalizer().normalize_refund(raw, "youzan")
    assert result.type == "unknown" and result.amount is None


def test_top_alias_tmall_preserves_same_money_semantics():
    result = Normalizer().normalize_order(top_order(), "tmall")
    assert result.platform == "taobao" and result.amount_paid is None
