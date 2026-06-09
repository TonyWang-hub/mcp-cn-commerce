"""Tests for Kuaishou MCP server tools."""

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

from servers.kuaishou.server import (  # noqa: E402
    get_logistics_tracking,
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
    list_logistics_companies,
    list_promotions,
)

from shared.cn_commerce_base import CommerceAPIError  # noqa: E402

# ── Helpers ─────────────────────────────────────────────────────────────────


def _mock_response(data: dict) -> dict:
    """Shallow wrapper for a successful KS API response."""
    return data


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_call():
    """Patch ks._call with an AsyncMock, reset after each test."""
    with patch.object(ks, "_call", new_callable=AsyncMock) as mock:
        yield mock


# ── Fixtures: Orders ─────────────────────────────────────────────────────────


@pytest.fixture
def order_list_payload() -> dict:
    return {
        "code": 0,
        "msg": "success",
        "data": {
            "order_list": [
                {
                    "order_id": "KS202401150000001",
                    "order_status": 1,
                    "order_amount": "99.00",
                    "goods_count": 2,
                    "created_at": "2024-01-15 10:30:00",
                    "receiver_name": "张三",
                    "receiver_phone": "138****8000",
                    "receiver_address": "北京市朝阳区XX路1号",
                },
                {
                    "order_id": "KS202401160000001",
                    "order_status": 3,
                    "order_amount": "199.00",
                    "goods_count": 1,
                    "created_at": "2024-01-16 14:20:00",
                    "receiver_name": "李四",
                    "receiver_phone": "139****9000",
                    "receiver_address": "上海市浦东新区YY路2号",
                },
            ],
            "total_count": 2,
        },
    }


@pytest.fixture
def order_detail_payload() -> dict:
    return {
        "code": 0,
        "msg": "success",
        "data": {
            "order_info": {
                "order_id": "KS202401150000001",
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
                        "item_id": "KS987654321",
                        "item_name": "无线蓝牙耳机 Pro",
                        "item_price": "99.00",
                        "item_count": 1,
                        "item_thumb": "https://img.kwaixiaodian.com/thumb1.jpg",
                    },
                ],
            },
        },
    }


# ── Fixtures: Products ───────────────────────────────────────────────────────


@pytest.fixture
def product_list_payload() -> dict:
    return {
        "code": 0,
        "msg": "success",
        "data": {
            "item_list": [
                {
                    "item_id": "KS987654321",
                    "item_name": "无线蓝牙耳机 Pro",
                    "item_status": 1,
                    "min_price": "99.00",
                    "max_price": "129.00",
                    "stock": 500,
                    "sold_count": 1234,
                    "created_at": "2024-01-01 00:00:00",
                },
                {
                    "item_id": "KS987654322",
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
        },
    }


@pytest.fixture
def product_detail_payload() -> dict:
    return {
        "code": 0,
        "msg": "success",
        "data": {
            "item_info": {
                "item_id": "KS987654321",
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
        },
    }


# ── Fixtures: After-Sale ─────────────────────────────────────────────────────


@pytest.fixture
def refund_list_payload() -> dict:
    return {
        "code": 0,
        "msg": "success",
        "data": {
            "refund_list": [
                {
                    "refund_id": "RF123456789",
                    "order_id": "KS202401150000001",
                    "refund_status": 1,
                    "refund_type": "退货退款",
                    "refund_amount": "99.00",
                    "apply_time": "2024-01-20 10:00:00",
                    "reason": "商品质量问题",
                },
                {
                    "refund_id": "RF123456790",
                    "order_id": "KS202401160000001",
                    "refund_status": 3,
                    "refund_type": "仅退款",
                    "refund_amount": "199.00",
                    "apply_time": "2024-01-25 15:30:00",
                    "reason": "未收到货",
                },
            ],
            "total_count": 2,
        },
    }


@pytest.fixture
def refund_detail_payload() -> dict:
    return {
        "code": 0,
        "msg": "success",
        "data": {
            "refund_info": {
                "refund_id": "RF123456789",
                "order_id": "KS202401150000001",
                "refund_status": 1,
                "refund_type": "退货退款",
                "refund_amount": "99.00",
                "apply_time": "2024-01-20 10:00:00",
                "reason": "商品质量问题",
                "description": "收到商品后发现有划痕，要求退货退款",
                "evidence": ["https://img.kwaixiaodian.com/evidence1.jpg"],
            },
        },
    }


# ── Fixtures: Logistics ──────────────────────────────────────────────────────


@pytest.fixture
def logistics_tracking_payload() -> dict:
    return {
        "code": 0,
        "msg": "success",
        "data": {
            "logistics_info": {
                "order_id": "KS202401150000001",
                "logistics_no": "KS0001234567890",
                "company": "中通快递",
                "status": "已签收",
                "nodes": [
                    {"time": "2024-01-18 08:00:00", "desc": "您的快递已由本人签收"},
                    {"time": "2024-01-18 06:30:00", "desc": "您的快递正在派送中"},
                    {"time": "2024-01-17 20:00:00", "desc": "您的快递已到达【北京朝阳网点】"},
                    {"time": "2024-01-16 15:00:00", "desc": "您的快递已发货"},
                ],
            },
        },
    }


@pytest.fixture
def logistics_companies_payload() -> dict:
    return {
        "code": 0,
        "msg": "success",
        "data": {
            "companies": [
                {"company_id": "ZTO", "company_name": "中通快递"},
                {"company_id": "YTO", "company_name": "圆通速递"},
                {"company_id": "STO", "company_name": "申通快递"},
                {"company_id": "EMS", "company_name": "EMS"},
                {"company_id": "SF", "company_name": "顺丰速运"},
            ],
        },
    }


# ── Fixtures: Reviews ────────────────────────────────────────────────────────


@pytest.fixture
def review_list_payload() -> dict:
    return {
        "code": 0,
        "msg": "success",
        "data": {
            "comment_list": [
                {
                    "comment_id": "CM00000001",
                    "item_id": "KS987654321",
                    "content": "音质很好，佩戴舒适，推荐购买！",
                    "score": 5,
                    "create_time": "2024-01-20 12:00:00",
                    "user_name": "匿***户",
                    "reply": "感谢您的支持和认可！",
                },
                {
                    "comment_id": "CM00000002",
                    "item_id": "KS987654321",
                    "content": "续航还不错，但是蓝牙偶尔会断连",
                    "score": 3,
                    "create_time": "2024-01-18 09:30:00",
                    "user_name": "匿***户",
                    "reply": "",
                },
            ],
            "total_count": 2,
        },
    }


# ── Fixtures: Shop ───────────────────────────────────────────────────────────


@pytest.fixture
def shop_info_payload() -> dict:
    return {
        "code": 0,
        "msg": "success",
        "data": {
            "shop_info": {
                "shop_id": "12345",
                "shop_name": "数码旗舰店",
                "shop_type": "旗舰店",
                "shop_status": 1,
                "shop_logo": "https://img.kwaixiaodian.com/logo.png",
                "shop_desc": "专注数码产品，正品保障",
                "created_at": "2020-01-01",
            },
        },
    }


# ── Fixtures: Marketing ──────────────────────────────────────────────────────


@pytest.fixture
def promotion_list_payload() -> dict:
    return {
        "code": 0,
        "msg": "success",
        "data": {
            "promotion_list": [
                {
                    "promotion_id": "PM00000001",
                    "promotion_name": "新年大促满减",
                    "promotion_type": "满减",
                    "status": 1,
                    "start_time": "2024-01-01 00:00:00",
                    "end_time": "2024-01-31 23:59:59",
                    "description": "满199减30，满399减60",
                },
                {
                    "promotion_id": "PM00000002",
                    "promotion_name": "限时秒杀",
                    "promotion_type": "秒杀",
                    "status": 1,
                    "start_time": "2024-01-20 10:00:00",
                    "end_time": "2024-01-20 12:00:00",
                    "description": "无线蓝牙耳机限时秒杀99元",
                },
            ],
            "total_count": 2,
        },
    }


@pytest.fixture
def coupon_list_payload() -> dict:
    return {
        "code": 0,
        "msg": "success",
        "data": {
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
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_order_list
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_order_list_returns_orders_with_correct_fields(mock_call, order_list_payload):
    """get_order_list should return a list of orders with expected fields."""
    mock_call.return_value = order_list_payload

    result_json = await get_order_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
    )
    result = json.loads(result_json)

    assert result["code"] == 0
    orders = result["data"]["order_list"]
    assert len(orders) == 2
    assert result["data"]["total_count"] == 2

    for order in orders:
        assert "order_id" in order
        assert "order_status" in order
        assert "order_amount" in order
        assert "created_at" in order

    mock_call.assert_called_once_with(
        "/open/api/order/list",
        {"start_time": "2024-01-01 00:00:00", "end_time": "2024-01-31 23:59:59", "page": "1", "page_size": "20"},
    )


@pytest.mark.asyncio
async def test_get_order_list_with_status_filter(mock_call, order_list_payload):
    """get_order_list should include order_status in params when provided."""
    mock_call.return_value = order_list_payload

    await get_order_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
        order_status="3",
    )

    _, params = mock_call.call_args[0]
    assert params["order_status"] == "3"


@pytest.mark.asyncio
async def test_get_order_list_without_status_omits_field(mock_call, order_list_payload):
    """get_order_list should NOT include order_status when empty."""
    mock_call.return_value = order_list_payload

    await get_order_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
        order_status="",
    )

    _, params = mock_call.call_args[0]
    assert "order_status" not in params


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_order_detail
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_order_detail_returns_single_order_with_all_fields(mock_call, order_detail_payload):
    """get_order_detail should return a single order with full details."""
    mock_call.return_value = order_detail_payload

    result_json = await get_order_detail(order_id="KS202401150000001")
    result = json.loads(result_json)

    details = result["data"]["order_info"]
    assert details["order_id"] == "KS202401150000001"
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
        "/open/api/order/detail",
        {"order_id": "KS202401150000001"},
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
        "/open/api/item/list",
        {"page": "1", "page_size": "20"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_product_detail
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_product_detail_returns_full_product_info(mock_call, product_detail_payload):
    """get_product_detail should return a single product with SKUs and images."""
    mock_call.return_value = product_detail_payload

    result_json = await get_product_detail(item_id="KS987654321")
    result = json.loads(result_json)

    info = result["data"]["item_info"]
    assert info["item_id"] == "KS987654321"
    assert info["item_name"] == "无线蓝牙耳机 Pro"
    assert "item_desc" in info
    assert "category_name" in info
    assert "rating" in info
    assert "images" in info
    assert len(info["images"]) == 2
    assert "skus" in info
    assert len(info["skus"]) == 2
    assert info["skus"][0]["spec"] == "黑色"

    mock_call.assert_called_once_with(
        "/open/api/item/detail",
        {"item_id": "KS987654321"},
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
        end_time="2024-01-31 23:59:59",
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
        "/open/api/refund/list",
        {"start_time": "2024-01-01 00:00:00", "end_time": "2024-01-31 23:59:59", "page": "1", "page_size": "20"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_refund_detail
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_refund_detail_returns_full_refund_record(mock_call, refund_detail_payload):
    """get_refund_detail should return a single refund record with full details."""
    mock_call.return_value = refund_detail_payload

    result_json = await get_refund_detail(refund_id="RF123456789")
    result = json.loads(result_json)

    detail = result["data"]["refund_info"]
    assert detail["refund_id"] == "RF123456789"
    assert detail["order_id"] == "KS202401150000001"
    assert detail["refund_status"] == 1
    assert "refund_type" in detail
    assert "refund_amount" in detail
    assert "reason" in detail
    assert "description" in detail
    assert "evidence" in detail

    mock_call.assert_called_once_with(
        "/open/api/refund/detail",
        {"refund_id": "RF123456789"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_logistics_tracking
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_logistics_tracking_returns_tracking_nodes(mock_call, logistics_tracking_payload):
    """get_logistics_tracking should return tracking with ordered nodes."""
    mock_call.return_value = logistics_tracking_payload

    result_json = await get_logistics_tracking(order_id="KS202401150000001")
    result = json.loads(result_json)

    logistics = result["data"]["logistics_info"]
    assert logistics["order_id"] == "KS202401150000001"
    assert logistics["logistics_no"] == "KS0001234567890"
    assert logistics["company"] == "中通快递"
    assert "status" in logistics
    assert "nodes" in logistics
    assert len(logistics["nodes"]) == 4
    assert logistics["nodes"][0]["desc"] == "您的快递已由本人签收"

    mock_call.assert_called_once_with(
        "/open/api/logistics/track",
        {"order_id": "KS202401150000001"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: list_logistics_companies
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_list_logistics_companies_returns_companies(mock_call, logistics_companies_payload):
    """list_logistics_companies should return available logistics companies."""
    mock_call.return_value = logistics_companies_payload

    result_json = await list_logistics_companies()
    result = json.loads(result_json)

    companies = result["data"]["companies"]
    assert len(companies) == 5

    for c in companies:
        assert "company_id" in c
        assert "company_name" in c

    assert companies[0]["company_name"] == "中通快递"

    mock_call.assert_called_once_with("/open/api/logistics/company/list")


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_review_list
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_review_list_returns_reviews_with_expected_fields(mock_call, review_list_payload):
    """get_review_list should return reviews with content, score, and user info."""
    mock_call.return_value = review_list_payload

    result_json = await get_review_list(item_id="KS987654321")
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
        "/open/api/comment/list",
        {"item_id": "KS987654321", "page": "1", "page_size": "20"},
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
    assert "shop_desc" in shop
    assert "created_at" in shop

    mock_call.assert_called_once_with("/open/api/shop/info")


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: list_promotions
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_list_promotions_returns_promotions_with_expected_fields(mock_call, promotion_list_payload):
    """list_promotions should return promotion activities with timing and type."""
    mock_call.return_value = promotion_list_payload

    result_json = await list_promotions()
    result = json.loads(result_json)

    promos = result["data"]["promotion_list"]
    assert len(promos) == 2

    for p in promos:
        assert "promotion_id" in p
        assert "promotion_name" in p
        assert "promotion_type" in p
        assert "status" in p
        assert "start_time" in p
        assert "end_time" in p

    mock_call.assert_called_once_with(
        "/open/api/promotion/list",
        {"page": "1", "page_size": "20"},
    )


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
        assert "issued_quantity" in c
        assert "used_quantity" in c

    mock_call.assert_called_once_with(
        "/open/api/coupon/list",
        {"page": "1", "page_size": "20"},
    )


@pytest.mark.asyncio
async def test_list_coupons_with_status_filter(mock_call, coupon_list_payload):
    """list_coupons should include status in params when provided."""
    mock_call.return_value = coupon_list_payload

    await list_coupons(status="2")

    _, params = mock_call.call_args[0]
    assert params["status"] == "2"


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: Error handling
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_missing_order_id_returned_in_result(mock_call):
    """When order_id is not found, the error response is serialized as JSON."""
    error_response = {
        "code": 10001,
        "msg": "order_id not found",
        "data": None,
    }
    mock_call.return_value = error_response

    result_json = await get_order_detail(order_id="KS9999999999999")
    result = json.loads(result_json)

    assert result["code"] == 10001
    assert "order_id not found" in result["msg"]


@pytest.mark.asyncio
async def test_api_error_propagates(mock_call):
    """When _call raises CommerceAPIError, it should propagate."""
    mock_call.side_effect = CommerceAPIError(code=40001, msg="Invalid app_key")

    with pytest.raises(CommerceAPIError) as exc_info:
        await get_order_list(
            start_time="2024-01-01 00:00:00",
            end_time="2024-01-31 23:59:59",
        )

    assert exc_info.value.code == 40001
    assert "Invalid app_key" in exc_info.value.msg


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
        await get_refund_detail(refund_id="RF99999999")

    assert exc_info.value.code == 50001
    assert "Refund record not found" in exc_info.value.msg


@pytest.mark.asyncio
async def test_coupon_api_error_propagates(mock_call):
    """CommerceAPIError from coupon tools should propagate."""
    mock_call.side_effect = CommerceAPIError(code=60001, msg="Coupon not found")

    with pytest.raises(CommerceAPIError) as exc_info:
        await list_coupons()

    assert exc_info.value.code == 60001
    assert "Coupon not found" in exc_info.value.msg


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: Pagination edge cases
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_pagination_default_page_and_size(mock_call, order_list_payload):
    """Default page=1, page_size=20 should be sent as strings."""
    mock_call.return_value = order_list_payload

    await get_order_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
    )

    _, params = mock_call.call_args[0]
    assert params["page"] == "1"
    assert params["page_size"] == "20"


@pytest.mark.asyncio
async def test_pagination_custom_page(mock_call, order_list_payload):
    """Custom page and page_size values should be passed correctly."""
    mock_call.return_value = order_list_payload

    await get_order_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
        page=3,
        page_size=50,
    )

    _, params = mock_call.call_args[0]
    assert params["page"] == "3"
    assert params["page_size"] == "50"


@pytest.mark.asyncio
async def test_pagination_empty_result_set(mock_call):
    """An empty order list should be handled gracefully."""
    empty_response = {
        "code": 0,
        "msg": "success",
        "data": {
            "order_list": [],
            "total_count": 0,
        },
    }
    mock_call.return_value = empty_response

    result_json = await get_order_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-01 00:00:01",
    )
    result = json.loads(result_json)

    assert result["data"]["total_count"] == 0
    assert result["data"]["order_list"] == []


@pytest.mark.asyncio
async def test_pagination_product_list_defaults(mock_call, product_list_payload):
    """Product list pagination defaults should match order list behavior."""
    mock_call.return_value = product_list_payload

    await get_product_list()

    _, params = mock_call.call_args[0]
    assert params["page"] == "1"
    assert params["page_size"] == "20"


@pytest.mark.asyncio
async def test_pagination_review_list_custom(mock_call, review_list_payload):
    """Review list should support custom pagination."""
    mock_call.return_value = review_list_payload

    await get_review_list(item_id="KS987654321", page=2, page_size=10)

    _, params = mock_call.call_args[0]
    assert params["item_id"] == "KS987654321"
    assert params["page"] == "2"
    assert params["page_size"] == "10"


@pytest.mark.asyncio
async def test_pagination_coupon_list_defaults(mock_call, coupon_list_payload):
    """Coupon list should use default pagination."""
    mock_call.return_value = coupon_list_payload

    await list_coupons()

    _, params = mock_call.call_args[0]
    assert params["page"] == "1"
    assert params["page_size"] == "20"


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: JSON output format
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_output_is_valid_json_string(mock_call, order_list_payload):
    """All tool return values should be valid JSON strings."""
    mock_call.return_value = order_list_payload

    result = await get_order_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
    )

    assert isinstance(result, str)
    parsed = json.loads(result)
    assert isinstance(parsed, dict)


@pytest.mark.asyncio
async def test_refund_output_is_valid_json_string(mock_call, refund_list_payload):
    """Refund tools should return valid JSON strings."""
    mock_call.return_value = refund_list_payload

    result = await get_refund_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
    )

    assert isinstance(result, str)
    parsed = json.loads(result)
    assert isinstance(parsed, dict)


@pytest.mark.asyncio
async def test_shop_info_output_is_valid_json_string(mock_call, shop_info_payload):
    """Shop info should return valid JSON string."""
    mock_call.return_value = shop_info_payload

    result = await get_shop_info()
    assert isinstance(result, str)
    parsed = json.loads(result)
    assert isinstance(parsed, dict)


@pytest.mark.asyncio
async def test_coupon_output_is_valid_json_string(mock_call, coupon_list_payload):
    """Coupon list should return valid JSON string."""
    mock_call.return_value = coupon_list_payload

    result = await list_coupons()
    assert isinstance(result, str)
    parsed = json.loads(result)
    assert isinstance(parsed, dict)


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: _call passthrough
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_call_passthrough_with_minimal_params(mock_call):
    """Verify _call receives the expected API path and params."""
    mock_call.return_value = _mock_response({"ok": True})

    await get_order_detail(order_id="KS202401150000001")

    path, params = mock_call.call_args[0]
    assert path == "/open/api/order/detail"
    assert params == {"order_id": "KS202401150000001"}


@pytest.mark.asyncio
async def test_call_passthrough_list_logistics_companies(mock_call):
    """Verify _call receives no params for no-arg tool."""
    mock_call.return_value = _mock_response({"ok": True})

    await list_logistics_companies()

    path = mock_call.call_args[0][0]
    assert path == "/open/api/logistics/company/list"
    # No second positional arg means no params dict
    assert len(mock_call.call_args[0]) == 1


@pytest.mark.asyncio
async def test_call_passthrough_review_list(mock_call):
    """Verify _call receives correct API path and params for reviews."""
    mock_call.return_value = _mock_response({"ok": True})

    await get_review_list(item_id="KS987654321", page=2, page_size=10)

    path, params = mock_call.call_args[0]
    assert path == "/open/api/comment/list"
    assert params == {"item_id": "KS987654321", "page": "2", "page_size": "10"}
