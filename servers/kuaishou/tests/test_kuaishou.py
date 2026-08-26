"""Tests for Kuaishou MCP server tools.

These stub ``ks._call``, so they assert the tool-level contract: the official
dotted ``method`` name each tool targets, the camelCase business params it
packs, and the pagination paradigm it uses.  The layers *below* ``_call``
(path derivation, system params, signing, envelope) are asserted at the wire
level in ``tests/contract/test_wire_kuaishou.py``.

Response payloads are wrapped in Kuaishou's real envelope — ``result: 1`` with
the payload under ``data`` — because that, not ``error_response``, is how this
gateway reports success.
"""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, patch

import pytest

# Must patch env BEFORE importing the server module (it reads env at import time)
os.environ.setdefault("KUAISHOU_APP_KEY", "test_app_key")
os.environ.setdefault("KUAISHOU_APP_SECRET", "test_app_secret")
os.environ.setdefault("KUAISHOU_SIGN_SECRET", "test_sign_secret")
os.environ.setdefault("KUAISHOU_ACCESS_TOKEN", "test_access_token")

import servers.kuaishou.server as ks_server  # noqa: E402
from servers.kuaishou.server import (  # noqa: E402
    KuaishouMCP,
    get_order_detail,
    get_order_list,
    get_product_detail,
    get_product_list,
    get_refund_detail,
    get_refund_list,
    get_review_list,
    get_shop_info,
    ks,
    list_coupons,
)
from shared.cn_commerce_base import CommerceAPIError  # noqa: E402

# ── Helpers ─────────────────────────────────────────────────────────────────


def _envelope(data: dict) -> dict:
    """Wrap a payload in Kuaishou's success envelope."""
    return {"result": 1, "error_msg": "", "data": data}


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_call():
    """Patch ks._call with an AsyncMock, reset after each test."""
    with patch.object(ks, "_call", new_callable=AsyncMock) as mock:
        yield mock


# ── Fixtures: Orders ─────────────────────────────────────────────────────────


@pytest.fixture
def order_list_payload() -> dict:
    return _envelope(
        {
            "order_list": [
                {
                    "order_id": "2000001",
                    "order_status": 1,
                    "order_amount": "99.00",
                    "goods_count": 2,
                    "created_at": "2024-01-15 10:30:00",
                    "receiver_name": "张三",
                    "receiver_phone": "138****8000",
                    "receiver_address": "北京市朝阳区XX路1号",
                },
                {
                    "order_id": "2000002",
                    "order_status": 3,
                    "order_amount": "199.00",
                    "goods_count": 1,
                    "created_at": "2024-01-16 14:20:00",
                    "receiver_name": "李四",
                    "receiver_phone": "139****9000",
                    "receiver_address": "上海市浦东新区YY路2号",
                },
            ],
            # Cursor pagination: no total count, just the next cursor.
            "cursor": "eyJvZmZzZXQiOjIwfQ==",
        }
    )


@pytest.fixture
def order_detail_payload() -> dict:
    return _envelope(
        {
            "order_info": {
                "order_id": "2000001",
                "order_status": 1,
                "order_amount": "99.00",
                "discount_amount": "10.00",
                "shipping_fee": "0.00",
                "pay_amount": "89.00",
                "created_at": "2024-01-15 10:30:00",
                "paid_at": "2024-01-15 10:32:00",
                "receiver_name": "张三",
                "receiver_phone": "13800138000",
                "receiver_address": "北京市朝阳区XX路1号",
                "items": [
                    {
                        "item_id": "30001",
                        "item_name": "无线蓝牙耳机 Pro",
                        "item_price": "99.00",
                        "item_count": 1,
                        "item_thumb": "https://img.kwaixiaodian.com/thumb1.jpg",
                    },
                ],
            },
        }
    )


# ── Fixtures: Products ───────────────────────────────────────────────────────


@pytest.fixture
def product_list_payload() -> dict:
    return _envelope(
        {
            "item_list": [
                {
                    "item_id": "30001",
                    "item_name": "无线蓝牙耳机 Pro",
                    "item_status": 1,
                    "min_price": "99.00",
                    "max_price": "129.00",
                    "stock": 500,
                    "sold_count": 1234,
                    "created_at": "2024-01-01 00:00:00",
                },
                {
                    "item_id": "30002",
                    "item_name": "智能手表 运动版",
                    "item_status": 1,
                    "min_price": "299.00",
                    "max_price": "399.00",
                    "stock": 200,
                    "sold_count": 567,
                    "created_at": "2024-01-05 00:00:00",
                },
            ],
            "total_count": 2,
        }
    )


@pytest.fixture
def product_detail_payload() -> dict:
    return _envelope(
        {
            "item_info": {
                "item_id": "30001",
                "item_name": "无线蓝牙耳机 Pro",
                "item_desc": "高品质无线蓝牙耳机，主动降噪，超长续航30小时",
                "item_status": 1,
                "category_id": "1001",
                "category_name": "数码电器",
                "min_price": "99.00",
                "max_price": "129.00",
                "stock": 500,
                "sold_count": 1234,
                "rating": 4.8,
                "rating_count": 320,
                "created_at": "2024-01-01 00:00:00",
                "images": [
                    "https://img.kwaixiaodian.com/goods1_1.jpg",
                    "https://img.kwaixiaodian.com/goods1_2.jpg",
                ],
                "skus": [
                    {"sku_id": "SKU001", "spec": "黑色", "price": "99.00", "stock": 300},
                    {"sku_id": "SKU002", "spec": "白色", "price": "129.00", "stock": 200},
                ],
            },
        }
    )


# ── Fixtures: After-Sale ─────────────────────────────────────────────────────


@pytest.fixture
def refund_list_payload() -> dict:
    return _envelope(
        {
            "refund_list": [
                {
                    "refund_id": "40001",
                    "order_id": "2000001",
                    "refund_status": 1,
                    "refund_type": "退货退款",
                    "refund_amount": "99.00",
                    "apply_time": "2024-01-20 10:00:00",
                    "reason": "商品质量问题",
                },
                {
                    "refund_id": "40002",
                    "order_id": "2000002",
                    "refund_status": 3,
                    "refund_type": "仅退款",
                    "refund_amount": "199.00",
                    "apply_time": "2024-01-25 15:30:00",
                    "reason": "未收到货",
                },
            ],
            "pcursor": "MjA=",
            "current_page": 1,
        }
    )


@pytest.fixture
def refund_detail_payload() -> dict:
    return _envelope(
        {
            "refund_info": {
                "refund_id": "40001",
                "order_id": "2000001",
                "refund_status": 1,
                "refund_type": "退货退款",
                "refund_amount": "99.00",
                "apply_time": "2024-01-20 10:00:00",
                "reason": "商品质量问题",
                "description": "收到商品后发现有划痕，要求退货退款",
                "evidence": ["https://img.kwaixiaodian.com/evidence1.jpg"],
            },
        }
    )


# ── Fixtures: Reviews ────────────────────────────────────────────────────────


@pytest.fixture
def review_list_payload() -> dict:
    return _envelope(
        {
            "comment_list": [
                {
                    "comment_id": "CM00000001",
                    "item_id": "30001",
                    "content": "音质很好，佩戴舒适，推荐购买！",
                    "score": 5,
                    "create_time": "2024-01-20 12:00:00",
                    "user_name": "匿***户",
                    "reply": "感谢您的支持和认可！",
                },
                {
                    "comment_id": "CM00000002",
                    "item_id": "30001",
                    "content": "续航还不错，但是蓝牙偶尔会断连",
                    "score": 3,
                    "create_time": "2024-01-18 09:30:00",
                    "user_name": "匿***户",
                    "reply": "",
                },
            ],
            "total_count": 2,
        }
    )


# ── Fixtures: Shop ───────────────────────────────────────────────────────────


@pytest.fixture
def shop_info_payload() -> dict:
    return _envelope(
        {
            "shop_info": {
                "shop_id": "12345",
                "shop_name": "数码旗舰店",
                "shop_type": "旗舰店",
                "shop_status": 1,
                "shop_logo": "https://img.kwaixiaodian.com/logo.png",
                "shop_desc": "专注数码产品，正品保障",
                "created_at": "2020-01-01",
            },
        }
    )


# ── Fixtures: Marketing ──────────────────────────────────────────────────────


@pytest.fixture
def coupon_list_payload() -> dict:
    return _envelope(
        {
            "coupon_list": [
                {
                    "coupon_id": "CP00000001",
                    "coupon_name": "新人专享券",
                    "coupon_type": "折扣券",
                    "discount": "9折",
                    "min_amount": "0.00",
                    "max_discount": "50.00",
                    "total_quantity": 1000,
                    "issued_quantity": 350,
                    "used_quantity": 120,
                    "status": 2,
                    "start_time": "2024-01-01 00:00:00",
                    "end_time": "2024-01-31 23:59:59",
                },
                {
                    "coupon_id": "CP00000002",
                    "coupon_name": "满199减30",
                    "coupon_type": "满减券",
                    "discount": "30.00",
                    "min_amount": "199.00",
                    "max_discount": "30.00",
                    "total_quantity": 500,
                    "issued_quantity": 200,
                    "used_quantity": 85,
                    "status": 2,
                    "start_time": "2024-01-01 00:00:00",
                    "end_time": "2024-01-31 23:59:59",
                },
            ],
            "total_count": 2,
        }
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_order_list
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_order_list_returns_orders_with_correct_fields(mock_call, order_list_payload):
    """get_order_list should return a list of orders with expected fields."""
    mock_call.return_value = order_list_payload

    result_json = await get_order_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-07 23:59:59",
    )
    result = json.loads(result_json)

    assert result["result"] == 1
    orders = result["data"]["order_list"]
    assert len(orders) == 2
    assert result["data"]["cursor"] == "eyJvZmZzZXQiOjIwfQ=="

    for order in orders:
        assert "order_id" in order
        assert "order_status" in order
        assert "order_amount" in order
        assert "created_at" in order

    mock_call.assert_called_once_with(
        "open.order.cursor.list",
        {
            "orderViewStatus": 1,
            "beginTime": 1704038400000,
            "endTime": 1704643199000,
            "pageSize": 50,
            "cursor": "",
        },
    )


@pytest.mark.asyncio
async def test_get_order_list_order_view_status_is_required_and_enum_checked(mock_call, order_list_payload):
    """orderViewStatus is mandatory; the tool defaults to 1 (全部) and validates."""
    mock_call.return_value = order_list_payload

    await get_order_list(start_time="2024-01-01", end_time="2024-01-02", order_view_status="3")
    _, biz = mock_call.call_args[0]
    assert biz["orderViewStatus"] == 3

    with pytest.raises(ValueError, match="order_view_status"):
        await get_order_list(start_time="2024-01-01", end_time="2024-01-02", order_view_status="0")


@pytest.mark.asyncio
async def test_get_order_list_accepts_epoch_millis_unchanged(mock_call, order_list_payload):
    """Callers that already hold epoch millis should not be re-interpreted."""
    mock_call.return_value = order_list_payload

    await get_order_list(start_time="1704038400000", end_time="1704124800000")
    _, biz = mock_call.call_args[0]
    assert biz["beginTime"] == 1704038400000
    assert biz["endTime"] == 1704124800000


@pytest.mark.asyncio
async def test_get_order_list_rejects_unparseable_time(mock_call):
    """A time we cannot convert to millis is an error, not a silent zero."""
    with pytest.raises(ValueError, match="start_time"):
        await get_order_list(start_time="last tuesday", end_time="2024-01-02")


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_order_detail
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_order_detail_returns_single_order_with_all_fields(mock_call, order_detail_payload):
    """get_order_detail should return a single order with full details."""
    mock_call.return_value = order_detail_payload

    result_json = await get_order_detail(order_id="2000001")
    result = json.loads(result_json)

    details = result["data"]["order_info"]
    assert details["order_id"] == "2000001"
    assert details["order_status"] == 1
    assert "order_amount" in details
    assert "discount_amount" in details
    assert "shipping_fee" in details
    assert "pay_amount" in details
    assert "receiver_name" in details
    assert "items" in details
    assert len(details["items"]) == 1
    assert details["items"][0]["item_name"] == "无线蓝牙耳机 Pro"

    mock_call.assert_called_once_with(
        "open.order.detail",
        {"orderId": "2000001"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_product_list
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_product_list_returns_products_with_stock_sold(mock_call, product_list_payload):
    """get_product_list should return products with stock and sold count."""
    mock_call.return_value = product_list_payload

    result_json = await get_product_list()
    result = json.loads(result_json)

    items = result["data"]["item_list"]
    assert len(items) == 2

    for g in items:
        assert "item_id" in g
        assert "item_name" in g
        assert "item_status" in g
        assert "min_price" in g
        assert "stock" in g
        assert "sold_count" in g

    mock_call.assert_called_once_with(
        "open.item.list.get",
        {"pageNumber": 1, "pageSize": 20},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_product_detail
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_product_detail_returns_full_product_info(mock_call, product_detail_payload):
    """get_product_detail should return a single product with SKUs and images."""
    mock_call.return_value = product_detail_payload

    result_json = await get_product_detail(item_id="30001")
    result = json.loads(result_json)

    info = result["data"]["item_info"]
    assert info["item_id"] == "30001"
    assert info["item_name"] == "无线蓝牙耳机 Pro"
    assert "item_desc" in info
    assert "category_name" in info
    assert "rating" in info
    assert len(info["images"]) == 2
    assert len(info["skus"]) == 2
    assert info["skus"][0]["spec"] == "黑色"

    mock_call.assert_called_once_with(
        "open.item.get",
        {"itemId": "30001"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_refund_list
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_refund_list_returns_refunds_with_expected_fields(mock_call, refund_list_payload):
    """get_refund_list should return refund records with correct fields."""
    mock_call.return_value = refund_list_payload

    result_json = await get_refund_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-01 23:59:59",
    )
    result = json.loads(result_json)

    refunds = result["data"]["refund_list"]
    assert len(refunds) == 2

    for r in refunds:
        assert "refund_id" in r
        assert "order_id" in r
        assert "refund_status" in r
        assert "refund_type" in r
        assert "refund_amount" in r
        assert "reason" in r

    mock_call.assert_called_once_with(
        "open.seller.order.refund.pcursor.list",
        {
            "beginTime": 1704038400000,
            "endTime": 1704124799000,
            "currentPage": 1,
            "pageSize": 20,
            "pcursor": "",
        },
    )


@pytest.mark.asyncio
async def test_get_refund_list_sends_both_halves_of_the_hybrid_cursor(mock_call, refund_list_payload):
    """pcursor and currentPage are both required by the platform."""
    mock_call.return_value = refund_list_payload

    await get_refund_list(
        start_time="2024-01-01",
        end_time="2024-01-02",
        pcursor="MjA=",
        current_page=2,
    )
    _, biz = mock_call.call_args[0]
    assert biz["pcursor"] == "MjA="
    assert biz["currentPage"] == 2


@pytest.mark.asyncio
async def test_refund_window_ceiling_is_configurable():
    """The 1-day window is tightened during sales events, so it is a setting."""
    client = KuaishouMCP(app_key="k", sign_secret="s", access_token="t", refund_window_hours=1)
    assert client.REFUND_WINDOW_HOURS == 1
    assert KuaishouMCP.REFUND_WINDOW_HOURS == 24


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_refund_detail
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_refund_detail_returns_full_refund_record(mock_call, refund_detail_payload):
    """get_refund_detail should return a single refund record with full details."""
    mock_call.return_value = refund_detail_payload

    result_json = await get_refund_detail(refund_id="40001")
    result = json.loads(result_json)

    detail = result["data"]["refund_info"]
    assert detail["refund_id"] == "40001"
    assert detail["order_id"] == "2000001"
    assert detail["refund_status"] == 1
    assert "refund_type" in detail
    assert "refund_amount" in detail
    assert "reason" in detail
    assert "description" in detail
    assert "evidence" in detail

    mock_call.assert_called_once_with(
        "open.seller.order.refund.detail",
        {"refundId": "40001"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_review_list
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_review_list_returns_reviews_with_expected_fields(mock_call, review_list_payload):
    """get_review_list should return reviews with content, score, and user info."""
    mock_call.return_value = review_list_payload

    result_json = await get_review_list(item_id="30001")
    result = json.loads(result_json)

    comments = result["data"]["comment_list"]
    assert len(comments) == 2

    for c in comments:
        assert "comment_id" in c
        assert "item_id" in c
        assert "content" in c
        assert "score" in c
        assert "create_time" in c
        assert "user_name" in c

    mock_call.assert_called_once_with(
        "open.comment.list.get",
        {"itemId": "30001", "offset": 0, "limit": 20},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_shop_info
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_shop_info_returns_shop_details(mock_call, shop_info_payload):
    """get_shop_info should return shop details."""
    mock_call.return_value = shop_info_payload

    result_json = await get_shop_info()
    result = json.loads(result_json)

    shop = result["data"]["shop_info"]
    assert shop["shop_id"] == "12345"
    assert shop["shop_name"] == "数码旗舰店"
    assert shop["shop_type"] == "旗舰店"
    assert "shop_status" in shop
    assert "shop_logo" in shop

    mock_call.assert_called_once_with("open.shop.info.get")


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: list_coupons
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_list_coupons_returns_coupons_with_expected_fields(mock_call, coupon_list_payload):
    """list_coupons should return coupon activities with discount details."""
    mock_call.return_value = coupon_list_payload

    result_json = await list_coupons()
    result = json.loads(result_json)

    coupons = result["data"]["coupon_list"]
    assert len(coupons) == 2

    for c in coupons:
        assert "coupon_id" in c
        assert "coupon_name" in c
        assert "coupon_type" in c
        assert "discount" in c
        assert "status" in c
        assert "total_quantity" in c

    mock_call.assert_called_once_with(
        "open.promotion.coupon.page.list",
        {"pageNo": 1, "pageSize": 20},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: capabilities the platform does not offer
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "removed",
    ["get_logistics_tracking", "list_logistics_companies", "list_promotions"],
)
def test_unavailable_capabilities_are_not_exposed(removed):
    """Three former tools had no counterpart in the platform's API surface.

    Logistics tracking exists only as a *write* endpoint for carriers pushing
    data to Kuaishou; carrier codes are published as a static document table,
    not an API (and shipping with a retired code is treated as a fake shipment);
    and the marketing API set covers only coupons and audience packages.
    """
    assert not hasattr(ks_server, removed)


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: Error handling
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_api_error_propagates(mock_call):
    """When _call raises CommerceAPIError, it should propagate."""
    mock_call.side_effect = CommerceAPIError(code=40001, msg="Invalid appkey")

    with pytest.raises(CommerceAPIError) as exc_info:
        await get_order_list(start_time="2024-01-01", end_time="2024-01-02")

    assert exc_info.value.code == 40001
    assert "Invalid appkey" in exc_info.value.msg


@pytest.mark.asyncio
async def test_timeout_propagates(mock_call):
    """When _call raises TimeoutError, it should propagate."""
    mock_call.side_effect = TimeoutError("Connection timed out")

    with pytest.raises(TimeoutError, match="Connection timed out"):
        await get_product_list()


@pytest.mark.asyncio
async def test_refund_api_error_propagates(mock_call):
    """CommerceAPIError from refund tools should propagate."""
    mock_call.side_effect = CommerceAPIError(code=50001, msg="Refund record not found")

    with pytest.raises(CommerceAPIError) as exc_info:
        await get_refund_detail(refund_id="49999")

    assert exc_info.value.code == 50001


@pytest.mark.asyncio
async def test_coupon_api_error_propagates(mock_call):
    """CommerceAPIError from coupon tools should propagate."""
    mock_call.side_effect = CommerceAPIError(code=60001, msg="Coupon not found")

    with pytest.raises(CommerceAPIError) as exc_info:
        await list_coupons()

    assert exc_info.value.code == 60001


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: Pagination paradigms (one per endpoint — they are not interchangeable)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_order_list_is_cursor_only(mock_call, order_list_payload):
    """No page number exists for orders; the cursor is empty on the first call."""
    mock_call.return_value = order_list_payload

    await get_order_list(start_time="2024-01-01", end_time="2024-01-02")
    _, biz = mock_call.call_args[0]
    assert biz["cursor"] == ""
    assert not {"pageNumber", "pageNo", "currentPage", "offset"} & set(biz)

    await get_order_list(start_time="2024-01-01", end_time="2024-01-02", cursor="AAAA")
    _, biz = mock_call.call_args[0]
    assert biz["cursor"] == "AAAA"


@pytest.mark.asyncio
async def test_order_list_page_size_capped_at_50(mock_call, order_list_payload):
    mock_call.return_value = order_list_payload

    await get_order_list(start_time="2024-01-01", end_time="2024-01-02", page_size=200)
    _, biz = mock_call.call_args[0]
    assert biz["pageSize"] == 50


@pytest.mark.asyncio
async def test_nomore_cursor_is_not_echoed_back(mock_call, order_list_payload):
    """'nomore' marks exhaustion; sending it back would be meaningless."""
    mock_call.return_value = order_list_payload

    await get_order_list(
        start_time="2024-01-01",
        end_time="2024-01-02",
        cursor=ks_server.CURSOR_EXHAUSTED,
    )
    _, biz = mock_call.call_args[0]
    assert biz["cursor"] == ""


@pytest.mark.asyncio
async def test_refund_list_page_size_capped_at_100(mock_call, refund_list_payload):
    mock_call.return_value = refund_list_payload

    await get_refund_list(start_time="2024-01-01", end_time="2024-01-02", page_size=500)
    _, biz = mock_call.call_args[0]
    assert biz["pageSize"] == 100


@pytest.mark.asyncio
async def test_product_list_page_size_clamped_to_10_100(mock_call, product_list_payload):
    mock_call.return_value = product_list_payload

    await get_product_list(page=2, page_size=5)
    _, biz = mock_call.call_args[0]
    assert biz == {"pageNumber": 2, "pageSize": 10}

    await get_product_list(page=2, page_size=500)
    _, biz = mock_call.call_args[0]
    assert biz["pageSize"] == 100


@pytest.mark.asyncio
async def test_review_limit_capped_at_20(mock_call, review_list_payload):
    """Reviews cap `limit` at 20 — lower than any other list endpoint here."""
    mock_call.return_value = review_list_payload

    await get_review_list(item_id="30001", offset=20, limit=100)
    _, biz = mock_call.call_args[0]
    assert biz == {"itemId": "30001", "offset": 20, "limit": 20}


@pytest.mark.asyncio
async def test_coupon_page_no_starts_at_one(mock_call, coupon_list_payload):
    mock_call.return_value = coupon_list_payload

    await list_coupons(page=0)
    _, biz = mock_call.call_args[0]
    assert biz["pageNo"] == 1


@pytest.mark.asyncio
async def test_pagination_empty_result_set(mock_call):
    """An empty order list should be handled gracefully."""
    mock_call.return_value = _envelope({"order_list": [], "cursor": "nomore"})

    result = json.loads(await get_order_list(start_time="2024-01-01", end_time="2024-01-02"))

    assert result["data"]["order_list"] == []
    assert result["data"]["cursor"] == ks_server.CURSOR_EXHAUSTED


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: JSON output format
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_output_is_valid_json_string(mock_call, order_list_payload):
    """All tool return values should be valid JSON strings."""
    mock_call.return_value = order_list_payload

    result = await get_order_list(start_time="2024-01-01", end_time="2024-01-02")

    assert isinstance(result, str)
    assert isinstance(json.loads(result), dict)


@pytest.mark.asyncio
async def test_refund_output_is_valid_json_string(mock_call, refund_list_payload):
    """Refund tools should return valid JSON strings."""
    mock_call.return_value = refund_list_payload

    result = await get_refund_list(start_time="2024-01-01", end_time="2024-01-02")

    assert isinstance(result, str)
    assert isinstance(json.loads(result), dict)


@pytest.mark.asyncio
async def test_shop_info_output_is_valid_json_string(mock_call, shop_info_payload):
    """Shop info should return valid JSON string."""
    mock_call.return_value = shop_info_payload

    result = await get_shop_info()
    assert isinstance(json.loads(result), dict)


@pytest.mark.asyncio
async def test_coupon_output_is_valid_json_string(mock_call, coupon_list_payload):
    """Coupon list should return valid JSON string."""
    mock_call.return_value = coupon_list_payload

    result = await list_coupons()
    assert isinstance(json.loads(result), dict)


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: _call passthrough
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_call_receives_dotted_method_names_not_paths(mock_call):
    """_call takes the official `method` name; the path is derived from it."""
    mock_call.return_value = _envelope({})

    await get_order_detail(order_id="2000001")
    api_method, biz = mock_call.call_args[0]

    assert api_method == "open.order.detail"
    assert not api_method.startswith("/"), "a path here would reintroduce the fabricated URLs"
    assert biz == {"orderId": "2000001"}
    assert ks.path_for(api_method) == "/open/order/detail"


@pytest.mark.asyncio
async def test_call_passthrough_no_business_params(mock_call):
    """Verify _call receives no business params for the no-arg tool."""
    mock_call.return_value = _envelope({})

    await get_shop_info()

    assert mock_call.call_args[0] == ("open.shop.info.get",)
