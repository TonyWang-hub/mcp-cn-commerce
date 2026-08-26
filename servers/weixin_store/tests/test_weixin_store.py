"""Tests for WeChat Store (微信小店) MCP server tools.

Request-shape expectations here mirror the contract recorded in
``docs/api-contracts/weixin_store.md``. Wire-level assertions (path, HTTP verb,
credential placement, HTTP 403) live in ``tests/contract/test_wire_weixin_store.py``.
"""

from __future__ import annotations

import json

# Must patch env BEFORE importing the server module (it reads env at import time)
import os
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("WX_APP_ID", "test_app_id")
os.environ.setdefault("WX_APP_SECRET", "test_app_secret")
os.environ.setdefault("WX_ACCESS_TOKEN", "test_access_token_123456")

from servers.weixin_store.server import (
    _wx,
    get_logistics_tracking,
    get_order_detail,
    get_order_list,
    get_product_detail,
    get_product_list,
    get_refund_detail,
    get_refund_list,
    get_shop_info,
    get_supply_order_list,
    list_categories,
    list_coupons,
)
from shared.cn_commerce_base import CommerceAPIError

# ── Time constants ──────────────────────────────────────────────────────────
#
# WeChat Store wants epoch **seconds**, and caps the order list span at 7 days
# and the after-sale list span at 24 hours.

T0 = 1704067200  # 2024-01-01T00:00:00Z
T_PLUS_7D = T0 + 7 * 24 * 3600
T_PLUS_24H = T0 + 24 * 3600
T_PLUS_1H = T0 + 3600


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_request():
    """Patch _wx._request with an AsyncMock, reset after each test."""
    with patch.object(_wx, "_request", new_callable=AsyncMock) as mock:
        yield mock


@pytest.fixture(autouse=True)
def reset_coupon_cursor():
    """Coupon paging state is per-client; keep tests independent of each other."""
    _wx._coupon_page_cursor = None
    yield
    _wx._coupon_page_cursor = None


# ── Fixtures: Orders ────────────────────────────────────────────────────────


@pytest.fixture
def order_list_payload() -> dict:
    """Documented shape: order_id_list + has_more + next_key."""
    return {
        "errcode": 0,
        "errmsg": "ok",
        "order_id_list": ["3705115058471207123", "3705115058471207456"],
        "has_more": False,
        "next_key": "",
    }


@pytest.fixture
def order_detail_payload() -> dict:
    return {
        "errcode": 0,
        "errmsg": "ok",
        "order": {
            "order_id": "3705115058471207123",
            "status": 20,
            "product_count": 2,
            "order_detail": {
                "product_infos": [
                    {
                        "product_id": "10000000000001",
                        "sku_id": "20000000000001",
                        "title": "无线蓝牙耳机 Pro",
                        "sale_price": 9900,
                        "product_cnt": 1,
                        "thumb_img": "https://wximg.com/thumb1.jpg",
                    },
                ],
                "price_info": {
                    "product_price": 12800,
                    "order_price": 11800,
                    "freight": 0,
                    "discounted_price": 1000,
                },
                "delivery_info": {
                    "receiver_name": "张三",
                    "receiver_tel": "13800138000",
                    "receiver_address": "北京市朝阳区XX路1号",
                    "delivery_method": 1,
                    "waybill_id": "ZTO987654321",
                    "delivery_id": "WXDELIVERY0123456789",
                },
                "create_time": "2024-01-15 10:30:00",
                "pay_time": "2024-01-15 10:32:00",
                "expire_time": "2024-01-15 10:45:00",
            },
        },
    }


# ── Fixtures: Products ──────────────────────────────────────────────────────


@pytest.fixture
def product_list_payload() -> dict:
    """Documented shape: product_ids + next_key + total_num (no has_more)."""
    return {
        "errcode": 0,
        "errmsg": "ok",
        "product_ids": ["10000000000001", "10000000000002"],
        "next_key": "MTAwMDAwMDAwMDAwMDI=",
        "total_num": 2,
    }


@pytest.fixture
def product_detail_payload() -> dict:
    return {
        "errcode": 0,
        "errmsg": "ok",
        "product": {
            "product_id": "10000000000001",
            "title": "无线蓝牙耳机 Pro",
            "desc": "高品质无线蓝牙耳机，主动降噪，超长续航30小时",
            "status": 5,
            "category_id": 1001,
            "category_name": "数码电器",
            "min_price": 9900,
            "head_imgs": [
                "https://wximg.com/goods1_1.jpg",
                "https://wximg.com/goods1_2.jpg",
            ],
            "stock_num": 500,
            "total_sold_num": 1234,
            "rating": 4.8,
            "rating_count": 320,
            "create_time": "2024-01-01 00:00:00",
            "skus": [
                {"sku_id": "SKU001", "spec": "黑色", "sale_price": 9900, "stock_num": 300},
                {"sku_id": "SKU002", "spec": "白色", "sale_price": 12900, "stock_num": 200},
            ],
        },
    }


# ── Fixtures: After-Sale ────────────────────────────────────────────────────


@pytest.fixture
def refund_list_payload() -> dict:
    """Documented shape: after_sale_order_id_list + has_more + next_key."""
    return {
        "errcode": 0,
        "errmsg": "ok",
        "after_sale_order_id_list": ["3705115058471207123", "3705115058471207456"],
        "has_more": False,
        "next_key": "",
    }


@pytest.fixture
def refund_detail_payload() -> dict:
    return {
        "errcode": 0,
        "errmsg": "ok",
        "after_sale_order": {
            "after_sale_order_id": "3705115058471207123",
            "order_id": "3705115058471207123",
            "status": 1,
            "type": "RETURN",
            "refund_info": {"amount": 9900},
            "apply_time": "2024-01-20 10:00:00",
            "reason_text": "商品质量问题",
            "desc": "收到商品后发现有划痕，要求退货退款",
            "media": ["https://wximg.com/evidence1.jpg"],
            "product_info": {
                "product_id": "10000000000001",
                "title": "无线蓝牙耳机 Pro",
                "product_cnt": 1,
            },
        },
    }


# ── Fixtures: Shop ──────────────────────────────────────────────────────────


@pytest.fixture
def shop_info_payload() -> dict:
    return {
        "errcode": 0,
        "errmsg": "ok",
        "shop_info": {
            "shop_id": "test_shop_id_001",
            "shop_name": "数码旗舰店",
            "shop_type": 1,
            "shop_logo": "https://wximg.com/logo.png",
            "shop_desc": "专注数码产品，正品保障",
            "status": 1,
            "created_at": "2020-01-01",
        },
    }


# ── Fixtures: Marketing ─────────────────────────────────────────────────────


@pytest.fixture
def coupon_list_payload() -> dict:
    return {
        "errcode": 0,
        "errmsg": "ok",
        "coupons": [
            {
                "coupon_id": "CP00000001",
                "name": "新年大促满减券",
                "type": 1,
                "status": 2,
                "promote_info": {
                    "discount_amount": 3000,
                    "condition_amount": 19900,
                },
                "valid_info": {
                    "start_time": "2024-01-01 00:00:00",
                    "end_time": "2024-01-31 23:59:59",
                },
                "stock_info": {"issued_num": 5000, "receive_num": 2345, "used_num": 890},
            },
            {
                "coupon_id": "CP00000002",
                "name": "限时秒杀券",
                "type": 2,
                "status": 2,
                "promote_info": {
                    "discount_amount": 2000,
                    "condition_amount": 9900,
                },
                "valid_info": {
                    "start_time": "2024-01-20 10:00:00",
                    "end_time": "2024-01-20 12:00:00",
                },
                "stock_info": {"issued_num": 1000, "receive_num": 678, "used_num": 234},
            },
        ],
        "page_ctx": "eyJwYWdlIjoxfQ==",
        "total_num": 2,
    }


# ── Fixtures: Supply Chain ──────────────────────────────────────────────────


@pytest.fixture
def supply_order_list_payload() -> dict:
    return {
        "errcode": 0,
        "errmsg": "ok",
        "order_id_list": ["SUPP20240115001", "SUPP20240120002"],
        "has_more": False,
    }


# ── Fixtures: Categories ────────────────────────────────────────────────────


@pytest.fixture
def categories_payload() -> dict:
    """One call returns the whole tree; the current tree lives in cats_v2."""
    return {
        "errcode": 0,
        "errmsg": "ok",
        "cats_v2": [
            {"cat_id": "1", "name": "服饰鞋包", "f_cat_id": "0", "level": 1},
            {"cat_id": "2", "name": "数码电器", "f_cat_id": "0", "level": 1},
            {"cat_id": "201", "name": "手机", "f_cat_id": "2", "level": 2},
            {"cat_id": "3", "name": "家居日用", "f_cat_id": "0", "level": 1},
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_order_list
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_order_list_sends_nested_create_time_range(mock_request, order_list_payload):
    """The bounds go in create_time_range, as epoch seconds."""
    mock_request.return_value = order_list_payload

    result_json = await get_order_list(start_time=T0, end_time=T_PLUS_24H)
    result = json.loads(result_json)

    assert result["errcode"] == 0
    assert result["order_id_list"] == ["3705115058471207123", "3705115058471207456"]
    assert result["has_more"] is False

    mock_request.assert_called_once_with(
        "POST",
        "/channels/ec/order/list/get",
        data={
            "create_time_range": {"start_time": T0, "end_time": T_PLUS_24H},
            "page_size": 20,
        },
    )


@pytest.mark.asyncio
async def test_get_order_list_never_sends_the_invented_flat_fields(mock_request, order_list_payload):
    """start_create_time / end_create_time / page do not exist (errcode 40097)."""
    mock_request.return_value = order_list_payload

    await get_order_list(start_time=T0, end_time=T_PLUS_24H)

    body = mock_request.call_args[1]["data"]
    for absent in ("start_create_time", "end_create_time", "page"):
        assert absent not in body


@pytest.mark.asyncio
async def test_get_order_list_can_filter_on_update_time(mock_request, order_list_payload):
    mock_request.return_value = order_list_payload

    await get_order_list(start_time=T0, end_time=T_PLUS_24H, time_field="update_time")

    body = mock_request.call_args[1]["data"]
    assert body["update_time_range"] == {"start_time": T0, "end_time": T_PLUS_24H}
    assert "create_time_range" not in body


@pytest.mark.asyncio
async def test_get_order_list_with_status_filter(mock_request, order_list_payload):
    mock_request.return_value = order_list_payload

    await get_order_list(start_time=T0, end_time=T_PLUS_24H, order_status="30")

    assert mock_request.call_args[1]["data"]["status"] == 30


@pytest.mark.asyncio
async def test_get_order_list_without_status_omits_field(mock_request, order_list_payload):
    mock_request.return_value = order_list_payload

    await get_order_list(start_time=T0, end_time=T_PLUS_24H, order_status="")

    assert "status" not in mock_request.call_args[1]["data"]


@pytest.mark.asyncio
async def test_get_order_list_rejects_undocumented_status(mock_request):
    """50 is not a WeChat order status; 250 (订单取消) is."""
    with pytest.raises(ValueError, match="not a documented value"):
        await get_order_list(start_time=T0, end_time=T_PLUS_24H, order_status="50")
    mock_request.assert_not_called()


@pytest.mark.asyncio
async def test_get_order_list_accepts_status_250(mock_request, order_list_payload):
    mock_request.return_value = order_list_payload

    await get_order_list(start_time=T0, end_time=T_PLUS_24H, order_status="250")

    assert mock_request.call_args[1]["data"]["status"] == 250


@pytest.mark.asyncio
async def test_get_order_list_rejects_span_over_seven_days(mock_request):
    with pytest.raises(ValueError, match="exceeds the documented maximum"):
        await get_order_list(start_time=T0, end_time=T_PLUS_7D + 1)
    mock_request.assert_not_called()


@pytest.mark.asyncio
async def test_get_order_list_accepts_span_of_exactly_seven_days(mock_request, order_list_payload):
    mock_request.return_value = order_list_payload

    await get_order_list(start_time=T0, end_time=T_PLUS_7D)

    assert mock_request.call_args[1]["data"]["create_time_range"]["end_time"] == T_PLUS_7D


@pytest.mark.asyncio
async def test_get_order_list_rejects_date_strings(mock_request):
    """The old signature took "2024-01-01 00:00:00"; that earns errcode 40097."""
    with pytest.raises(ValueError, match="epoch timestamp in seconds"):
        await get_order_list(start_time="2024-01-01 00:00:00", end_time="2024-01-02 00:00:00")
    mock_request.assert_not_called()


@pytest.mark.asyncio
async def test_get_order_list_rejects_millisecond_timestamps(mock_request):
    with pytest.raises(ValueError, match="looks like milliseconds"):
        await get_order_list(start_time=T0 * 1000, end_time=T_PLUS_24H * 1000)
    mock_request.assert_not_called()


@pytest.mark.asyncio
async def test_get_order_list_rejects_page_size_over_100(mock_request):
    with pytest.raises(ValueError, match=r"out of range \[1, 100\]"):
        await get_order_list(start_time=T0, end_time=T_PLUS_24H, page_size=101)
    mock_request.assert_not_called()


@pytest.mark.asyncio
async def test_get_order_list_forwards_next_key(mock_request, order_list_payload):
    mock_request.return_value = order_list_payload

    await get_order_list(start_time=T0, end_time=T_PLUS_24H, next_key="cursor-abc")

    assert mock_request.call_args[1]["data"]["next_key"] == "cursor-abc"


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_order_detail
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_order_detail_returns_single_order_with_all_fields(mock_request, order_detail_payload):
    """get_order_detail should return a single order with full details."""
    mock_request.return_value = order_detail_payload

    result_json = await get_order_detail(order_id="3705115058471207123")
    result = json.loads(result_json)

    assert result["errcode"] == 0
    order = result["order"]
    assert order["order_id"] == "3705115058471207123"
    assert order["status"] == 20
    detail = order["order_detail"]
    assert "product_infos" in detail
    assert "price_info" in detail
    assert "delivery_info" in detail
    assert "pay_time" in detail
    assert len(detail["product_infos"]) == 1
    assert detail["product_infos"][0]["title"] == "无线蓝牙耳机 Pro"

    mock_request.assert_called_once_with(
        "POST",
        "/channels/ec/order/get",
        data={"order_id": "3705115058471207123"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_product_list
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_product_list_sends_page_size_only_by_default(mock_request, product_list_payload):
    """page_size is mandatory and defaults to 10; page does not exist."""
    mock_request.return_value = product_list_payload

    result_json = await get_product_list()
    result = json.loads(result_json)

    assert result["product_ids"] == ["10000000000001", "10000000000002"]
    assert result["total_num"] == 2
    assert "has_more" not in result

    mock_request.assert_called_once_with(
        "POST",
        "/channels/ec/product/list/get",
        data={"page_size": 10},
    )


@pytest.mark.asyncio
async def test_get_product_list_omits_status_for_all(mock_request, product_list_payload):
    """ "All statuses" means omitting the field — status=0 means 初始值."""
    mock_request.return_value = product_list_payload

    await get_product_list()

    assert "status" not in mock_request.call_args[1]["data"]


@pytest.mark.asyncio
async def test_get_product_list_with_status_filter(mock_request, product_list_payload):
    mock_request.return_value = product_list_payload

    await get_product_list(status="5")

    assert mock_request.call_args[1]["data"]["status"] == 5


@pytest.mark.asyncio
async def test_get_product_list_rejects_undocumented_status(mock_request):
    with pytest.raises(ValueError, match="not a documented value"):
        await get_product_list(status="3")
    mock_request.assert_not_called()


@pytest.mark.asyncio
async def test_get_product_list_rejects_page_size_over_30(mock_request):
    """The old docstring claimed 200; WeChat caps this endpoint at 30."""
    with pytest.raises(ValueError, match=r"out of range \[1, 30\]"):
        await get_product_list(page_size=31)
    mock_request.assert_not_called()


@pytest.mark.asyncio
async def test_get_product_list_forwards_next_key(mock_request, product_list_payload):
    mock_request.return_value = product_list_payload

    await get_product_list(next_key="cursor-xyz")

    assert mock_request.call_args[1]["data"]["next_key"] == "cursor-xyz"


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_product_detail
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_product_detail_returns_full_product_info(mock_request, product_detail_payload):
    """get_product_detail should return a single product with SKUs and images."""
    mock_request.return_value = product_detail_payload

    result_json = await get_product_detail(product_id="10000000000001")
    result = json.loads(result_json)

    assert result["errcode"] == 0
    product = result["product"]
    assert product["product_id"] == "10000000000001"
    assert product["title"] == "无线蓝牙耳机 Pro"
    assert "desc" in product
    assert "category_name" in product
    assert "rating" in product
    assert "head_imgs" in product
    assert len(product["head_imgs"]) == 2
    assert "skus" in product
    assert len(product["skus"]) == 2
    assert product["skus"][0]["spec"] == "黑色"

    mock_request.assert_called_once_with(
        "POST",
        "/channels/ec/product/get",
        data={"product_id": "10000000000001", "data_type": 1},
    )


@pytest.mark.asyncio
async def test_get_product_detail_can_request_draft(mock_request, product_detail_payload):
    mock_request.return_value = product_detail_payload

    await get_product_detail(product_id="10000000000001", data_type=2)

    assert mock_request.call_args[1]["data"]["data_type"] == 2


@pytest.mark.asyncio
async def test_get_product_detail_rejects_unknown_data_type(mock_request):
    with pytest.raises(ValueError, match="not a documented value"):
        await get_product_detail(product_id="10000000000001", data_type=4)
    mock_request.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_refund_list
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_refund_list_sends_flat_epoch_bounds(mock_request, refund_list_payload):
    """Four flat fields, epoch seconds, and no page/page_size at all."""
    mock_request.return_value = refund_list_payload

    result_json = await get_refund_list(start_time=T0, end_time=T_PLUS_1H)
    result = json.loads(result_json)

    assert result["after_sale_order_id_list"] == [
        "3705115058471207123",
        "3705115058471207456",
    ]
    assert result["has_more"] is False

    mock_request.assert_called_once_with(
        "POST",
        "/channels/ec/aftersale/getaftersalelist",
        data={"begin_create_time": T0, "end_create_time": T_PLUS_1H},
    )


@pytest.mark.asyncio
async def test_get_refund_list_sends_no_pagination_fields(mock_request, refund_list_payload):
    mock_request.return_value = refund_list_payload

    await get_refund_list(start_time=T0, end_time=T_PLUS_1H)

    body = mock_request.call_args[1]["data"]
    assert "page" not in body
    assert "page_size" not in body


@pytest.mark.asyncio
async def test_get_refund_list_can_filter_on_update_time(mock_request, refund_list_payload):
    mock_request.return_value = refund_list_payload

    await get_refund_list(start_time=T0, end_time=T_PLUS_1H, time_field="update_time")

    body = mock_request.call_args[1]["data"]
    assert body == {"begin_update_time": T0, "end_update_time": T_PLUS_1H}


@pytest.mark.asyncio
async def test_get_refund_list_rejects_span_over_24_hours(mock_request):
    """The after-sale cap is 24h, not the order list's 7 days."""
    with pytest.raises(ValueError, match="exceeds the documented maximum"):
        await get_refund_list(start_time=T0, end_time=T_PLUS_24H + 1)
    mock_request.assert_not_called()


@pytest.mark.asyncio
async def test_get_refund_list_rejects_date_strings(mock_request):
    with pytest.raises(ValueError, match="epoch timestamp in seconds"):
        await get_refund_list(start_time="2024-01-01 00:00:00", end_time="2024-01-01 01:00:00")
    mock_request.assert_not_called()


@pytest.mark.asyncio
async def test_get_refund_list_forwards_next_key(mock_request, refund_list_payload):
    mock_request.return_value = refund_list_payload

    await get_refund_list(start_time=T0, end_time=T_PLUS_1H, next_key="cursor-1")

    assert mock_request.call_args[1]["data"]["next_key"] == "cursor-1"


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_refund_detail
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_refund_detail_returns_full_refund_record(mock_request, refund_detail_payload):
    """get_refund_detail should return a single after-sale record with details."""
    mock_request.return_value = refund_detail_payload

    result_json = await get_refund_detail(after_sale_order_id="3705115058471207123")
    result = json.loads(result_json)

    assert result["errcode"] == 0
    detail = result["after_sale_order"]
    assert detail["after_sale_order_id"] == "3705115058471207123"
    assert detail["order_id"] == "3705115058471207123"
    assert detail["status"] == 1
    assert "type" in detail
    assert "refund_info" in detail
    assert "reason_text" in detail
    assert "desc" in detail
    assert "media" in detail
    assert "product_info" in detail

    mock_request.assert_called_once_with(
        "POST",
        "/channels/ec/aftersale/getaftersaleorder",
        data={"after_sale_order_id": "3705115058471207123"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_logistics_tracking
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_logistics_tracking_reads_order_detail(mock_request, order_detail_payload):
    """There is no logistics-pull endpoint: this comes out of order/get."""
    mock_request.return_value = order_detail_payload

    result_json = await get_logistics_tracking(order_id="3705115058471207123")
    result = json.loads(result_json)

    assert result["errcode"] == 0
    assert result["order_id"] == "3705115058471207123"
    delivery = result["delivery_info"]
    assert delivery["waybill_id"] == "ZTO987654321"
    assert delivery["delivery_id"] == "WXDELIVERY0123456789"
    assert result["source"]["endpoint"] == "/channels/ec/order/get"
    assert result["source"]["field"] == "order.order_detail.delivery_info"

    mock_request.assert_called_once_with(
        "POST",
        "/channels/ec/order/get",
        data={"order_id": "3705115058471207123"},
    )


@pytest.mark.asyncio
async def test_get_logistics_tracking_handles_order_without_delivery_info(mock_request):
    """An unshipped order simply has no delivery_info to report."""
    mock_request.return_value = {"errcode": 0, "errmsg": "ok", "order": {"order_detail": {}}}

    result = json.loads(await get_logistics_tracking(order_id="3705115058471207123"))

    assert result["delivery_info"] is None


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_shop_info
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_shop_info_returns_shop_details(mock_request, shop_info_payload):
    """get_shop_info should GET the basics path with no body."""
    mock_request.return_value = shop_info_payload

    result_json = await get_shop_info()
    result = json.loads(result_json)

    assert result["errcode"] == 0
    shop = result["shop_info"]
    assert shop["shop_id"] == "test_shop_id_001"
    assert shop["shop_name"] == "数码旗舰店"
    assert shop["shop_type"] == 1
    assert "shop_logo" in shop
    assert "shop_desc" in shop
    assert "status" in shop
    assert "created_at" in shop

    mock_request.assert_called_once_with("GET", "/channels/ec/basics/info/get")


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: list_coupons
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_list_coupons_sends_all_four_required_fields(mock_request, coupon_list_payload):
    mock_request.return_value = coupon_list_payload

    result_json = await list_coupons(status=2)
    result = json.loads(result_json)

    assert result["errcode"] == 0
    coupons = result["coupons"]
    assert len(coupons) == 2
    for c in coupons:
        assert "coupon_id" in c
        assert "name" in c
        assert "status" in c

    mock_request.assert_called_once_with(
        "POST",
        "/channels/ec/coupon/get_list",
        data={"status": 2, "page": 1, "page_size": 20, "page_ctx": ""},
    )


@pytest.mark.asyncio
async def test_list_coupons_rejects_status_zero(mock_request):
    """status is mandatory and 0 is not one of its members."""
    with pytest.raises(ValueError, match="not a documented value"):
        await list_coupons(status=0)
    mock_request.assert_not_called()


@pytest.mark.asyncio
async def test_list_coupons_accepts_status_200(mock_request, coupon_list_payload):
    mock_request.return_value = coupon_list_payload

    await list_coupons(status=200)

    assert mock_request.call_args[1]["data"]["status"] == 200


@pytest.mark.asyncio
async def test_list_coupons_rejects_page_size_over_200(mock_request):
    with pytest.raises(ValueError, match=r"out of range \[1, 200\]"):
        await list_coupons(status=2, page_size=201)
    mock_request.assert_not_called()


@pytest.mark.asyncio
async def test_list_coupons_forwards_page_ctx(mock_request, coupon_list_payload):
    mock_request.return_value = coupon_list_payload

    await list_coupons(status=2, page=2, page_ctx="eyJwYWdlIjoxfQ==")

    body = mock_request.call_args[1]["data"]
    assert body["page"] == 2
    assert body["page_ctx"] == "eyJwYWdlIjoxfQ=="


@pytest.mark.asyncio
async def test_list_coupons_rejects_page_jump_over_ten(mock_request, coupon_list_payload):
    """Consecutive requests may not skip more than 10 pages."""
    mock_request.return_value = coupon_list_payload

    await list_coupons(status=2, page=1)
    with pytest.raises(ValueError, match="may not jump more than 10 pages"):
        await list_coupons(status=2, page=12)

    assert mock_request.call_count == 1


@pytest.mark.asyncio
async def test_list_coupons_allows_page_step_within_stride(mock_request, coupon_list_payload):
    mock_request.return_value = coupon_list_payload

    await list_coupons(status=2, page=1)
    await list_coupons(status=2, page=11)

    assert mock_request.call_count == 2


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_supply_order_list
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_supply_order_list_calls_shop_side_dropship(mock_request, supply_order_list_payload):
    """We authenticate as the shop, so we call the shop-side dropship endpoint.

    The body is empty on purpose: the path is confirmed but its request-field
    contract is not, and spec §8 forbids inventing one.
    """
    mock_request.return_value = supply_order_list_payload

    result_json = await get_supply_order_list()
    result = json.loads(result_json)

    assert result["errcode"] == 0
    assert result["order_id_list"] == ["SUPP20240115001", "SUPP20240120002"]

    mock_request.assert_called_once_with(
        "POST",
        "/channels/ec/order/dropship/list",
        data={},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: list_categories
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_list_categories_gets_the_whole_tree(mock_request, categories_payload):
    """One GET on /shop/ec/category/all returns the full tree in cats_v2."""
    mock_request.return_value = categories_payload

    result_json = await list_categories()
    result = json.loads(result_json)

    assert result["errcode"] == 0
    cats = result["cats_v2"]
    assert len(cats) == 4
    for c in cats:
        assert "cat_id" in c
        assert "name" in c
        assert "f_cat_id" in c

    mock_request.assert_called_once_with("GET", "/shop/ec/category/all")


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: Error handling
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_missing_order_id_returned_in_result(mock_request):
    """When order_id is not found, the error response is serialized as JSON."""
    error_response = {
        "errcode": 10001,
        "errmsg": "order_id not found",
    }
    mock_request.return_value = error_response

    result_json = await get_order_detail(order_id="999999-9999999999999")
    result = json.loads(result_json)

    assert result["errcode"] == 10001
    assert "order_id not found" in result["errmsg"]


@pytest.mark.asyncio
async def test_api_error_propagates(mock_request):
    """When _request raises CommerceAPIError, it should propagate."""
    mock_request.side_effect = CommerceAPIError(code=40001, msg="invalid access_token")

    with pytest.raises(CommerceAPIError) as exc_info:
        await get_order_list(start_time=T0, end_time=T_PLUS_24H)

    assert exc_info.value.code == 40001
    assert "invalid access_token" in exc_info.value.msg


@pytest.mark.asyncio
async def test_ip_allowlist_error_propagates(mock_request):
    """HTTP 403 is surfaced as code 403 — it never carries an errcode."""
    mock_request.side_effect = CommerceAPIError(code=403, msg="HTTP 403 from api.weixin.qq.com")

    with pytest.raises(CommerceAPIError) as exc_info:
        await get_shop_info()

    assert exc_info.value.code == 403


@pytest.mark.asyncio
async def test_timeout_propagates(mock_request):
    """When _request raises TimeoutError, it should propagate."""
    mock_request.side_effect = TimeoutError("Connection timed out")

    with pytest.raises(TimeoutError, match="Connection timed out"):
        await get_product_list()


@pytest.mark.asyncio
async def test_refund_api_error_propagates(mock_request):
    """CommerceAPIError from refund tools should propagate."""
    mock_request.side_effect = CommerceAPIError(code=50001, msg="After-sale record not found")

    with pytest.raises(CommerceAPIError) as exc_info:
        await get_refund_detail(after_sale_order_id="99999999")

    assert exc_info.value.code == 50001
    assert "After-sale record not found" in exc_info.value.msg


@pytest.mark.asyncio
async def test_supply_order_api_error_propagates(mock_request):
    """CommerceAPIError from supply chain tools should propagate."""
    mock_request.side_effect = CommerceAPIError(code=60001, msg="Supply order not found")

    with pytest.raises(CommerceAPIError) as exc_info:
        await get_supply_order_list()

    assert exc_info.value.code == 60001
    assert "Supply order not found" in exc_info.value.msg


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: JSON output format
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_output_is_valid_json_string(mock_request, order_list_payload):
    """All tool return values should be valid JSON strings."""
    mock_request.return_value = order_list_payload

    result = await get_order_list(start_time=T0, end_time=T_PLUS_24H)

    assert isinstance(result, str)
    parsed = json.loads(result)
    assert isinstance(parsed, dict)


@pytest.mark.asyncio
async def test_refund_output_is_valid_json_string(mock_request, refund_list_payload):
    """Refund tools should return valid JSON strings."""
    mock_request.return_value = refund_list_payload

    result = await get_refund_list(start_time=T0, end_time=T_PLUS_1H)

    assert isinstance(result, str)
    parsed = json.loads(result)
    assert isinstance(parsed, dict)


@pytest.mark.asyncio
async def test_shop_info_output_is_valid_json_string(mock_request, shop_info_payload):
    """Shop info should return valid JSON string."""
    mock_request.return_value = shop_info_payload

    result = await get_shop_info()
    assert isinstance(result, str)
    parsed = json.loads(result)
    assert isinstance(parsed, dict)


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: Pagination
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_order_pagination_is_cursor_based(mock_request, order_list_payload):
    """Orders page by next_key, not by a page number."""
    mock_request.return_value = order_list_payload

    await get_order_list(start_time=T0, end_time=T_PLUS_24H, page_size=100)

    body = mock_request.call_args[1]["data"]
    assert body["page_size"] == 100
    assert "page" not in body


@pytest.mark.asyncio
async def test_pagination_empty_result_set(mock_request):
    """An empty order list should be handled gracefully."""
    empty_response = {
        "errcode": 0,
        "errmsg": "ok",
        "order_id_list": [],
        "has_more": False,
        "next_key": "",
    }
    mock_request.return_value = empty_response

    result_json = await get_order_list(start_time=T0, end_time=T0 + 1)
    result = json.loads(result_json)

    assert result["errcode"] == 0
    assert result["order_id_list"] == []
    assert result["has_more"] is False
