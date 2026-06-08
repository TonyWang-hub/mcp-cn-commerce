"""Tests for Xiaohongshu MCP server tools."""

from __future__ import annotations

import json

# Must patch env BEFORE importing the server module (it reads env at import time)
import os
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("XHS_CLIENT_ID", "test_client_id")
os.environ.setdefault("XHS_CLIENT_SECRET", "test_client_secret")
os.environ.setdefault("XHS_ACCESS_TOKEN", "test_access_token")

from mcp_xiaohongshu.server import (
    get_bill_list,
    get_inventory,
    get_logistics_tracking,
    get_order_detail,
    get_order_list,
    get_product_detail,
    get_product_list,
    get_refund_detail,
    get_refund_list,
    get_review_list,
    get_shop_info,
    list_coupons,
    list_promotions,
    xhs,
)

from shared.cn_commerce_base import CommerceAPIError

# ── Helpers ─────────────────────────────────────────────────────────────────────


def _mock_response(data: dict) -> dict:
    """Shallow wrapper for a successful XHS API response."""
    return data


# ── Fixtures ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_call():
    """Patch xhs._call with an AsyncMock, reset after each test."""
    with patch.object(xhs, "_call", new_callable=AsyncMock) as mock:
        yield mock


# ── Fixtures: Orders ────────────────────────────────────────────────────────────


@pytest.fixture
def order_list_payload() -> dict:
    return {
        "result": {
            "order_list": [
                {
                    "order_id": "XHS20240115000001",
                    "order_status": 1,
                    "order_amount": "99.00",
                    "goods_count": 2,
                    "created_at": "2024-01-15 10:30:00",
                    "receiver_name": "张三",
                    "receiver_phone": "138****8000",
                    "receiver_address": "北京市朝阳区XX路1号",
                },
                {
                    "order_id": "XHS20240116000002",
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
        "result": {
            "order_info": {
                "order_id": "XHS20240115000001",
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
                "goods_list": [
                    {
                        "product_id": "5f8a9b2c3d4e5f6a7b8c9d0e",
                        "product_name": "复古碎花连衣裙 优雅款",
                        "product_price": "99.00",
                        "goods_count": 1,
                        "product_thumb": "https://img.xhs.com/thumb1.jpg",
                    },
                ],
            },
        },
    }


# ── Fixtures: Products ──────────────────────────────────────────────────────────


@pytest.fixture
def product_list_payload() -> dict:
    return {
        "result": {
            "product_list": [
                {
                    "product_id": "5f8a9b2c3d4e5f6a7b8c9d0e",
                    "product_name": "复古碎花连衣裙 优雅款",
                    "product_status": 1,
                    "min_price": "99.00",
                    "max_price": "129.00",
                    "stock": 500,
                    "sold_count": 1234,
                    "created_at": "2024-01-01 00:00:00",
                },
                {
                    "product_id": "5f8a9b2c3d4e5f6a7b8c9d1f",
                    "product_name": "简约纯棉T恤 通勤款",
                    "product_status": 1,
                    "min_price": "59.00",
                    "max_price": "79.00",
                    "stock": 800,
                    "sold_count": 2567,
                    "created_at": "2024-01-05 00:00:00",
                },
            ],
            "total_count": 2,
        },
    }


@pytest.fixture
def product_detail_payload() -> dict:
    return {
        "result": {
            "product_info": {
                "product_id": "5f8a9b2c3d4e5f6a7b8c9d0e",
                "product_name": "复古碎花连衣裙 优雅款",
                "product_desc": "优质纯棉面料，法式复古碎花设计，适合春夏穿搭",
                "product_status": 1,
                "category_id": "2001",
                "category_name": "女装",
                "min_price": "99.00",
                "max_price": "129.00",
                "stock": 500,
                "sold_count": 1234,
                "rating": 4.9,
                "rating_count": 520,
                "created_at": "2024-01-01 00:00:00",
                "images": [
                    "https://img.xhs.com/product1_1.jpg",
                    "https://img.xhs.com/product1_2.jpg",
                ],
                "skus": [
                    {"sku_id": "SKU001", "spec": "S码 蓝色碎花", "price": "99.00", "stock": 200},
                    {"sku_id": "SKU002", "spec": "M码 蓝色碎花", "price": "99.00", "stock": 150},
                    {"sku_id": "SKU003", "spec": "L码 蓝色碎花", "price": "129.00", "stock": 150},
                ],
            },
        },
    }


# ── Fixtures: After-Sale ────────────────────────────────────────────────────────


@pytest.fixture
def refund_list_payload() -> dict:
    return {
        "result": {
            "refund_list": [
                {
                    "refund_id": "RF2024011500001",
                    "order_id": "XHS20240115000001",
                    "refund_status": 1,
                    "refund_type": "退货退款",
                    "refund_amount": "99.00",
                    "apply_time": "2024-01-20 10:00:00",
                    "reason": "商品质量问题",
                },
                {
                    "refund_id": "RF2024012500002",
                    "order_id": "XHS20240116000002",
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
        "result": {
            "refund_info": {
                "refund_id": "RF2024011500001",
                "order_id": "XHS20240115000001",
                "refund_status": 1,
                "refund_type": "退货退款",
                "refund_amount": "99.00",
                "apply_time": "2024-01-20 10:00:00",
                "reason": "商品质量问题",
                "description": "收到商品后发现有瑕疵，要求退货退款",
                "evidence": ["https://img.xhs.com/evidence1.jpg"],
                "product_info": {
                    "product_id": "5f8a9b2c3d4e5f6a7b8c9d0e",
                    "product_name": "复古碎花连衣裙 优雅款",
                },
            },
        },
    }


# ── Fixtures: Logistics ─────────────────────────────────────────────────────────


@pytest.fixture
def logistics_tracking_payload() -> dict:
    return {
        "result": {
            "logistics_info": {
                "order_id": "XHS20240115000001",
                "logistics_no": "XHS0001234567890",
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


# ── Fixtures: Reviews ───────────────────────────────────────────────────────────


@pytest.fixture
def review_list_payload() -> dict:
    return {
        "result": {
            "comment_list": [
                {
                    "comment_id": "CM00000001",
                    "product_id": "5f8a9b2c3d4e5f6a7b8c9d0e",
                    "content": "裙子质量很好，花色很正，穿上很显气质！",
                    "score": 5,
                    "create_time": "2024-01-20 12:00:00",
                    "user_name": "小***书",
                    "reply": "感谢亲的好评和支持！",
                },
                {
                    "comment_id": "CM00000002",
                    "product_id": "5f8a9b2c3d4e5f6a7b8c9d0e",
                    "content": "颜色比图片深一点，但整体还不错",
                    "score": 4,
                    "create_time": "2024-01-18 09:30:00",
                    "user_name": "幸***福",
                    "reply": "",
                },
            ],
            "total_count": 2,
        },
    }


# ── Fixtures: Shop ──────────────────────────────────────────────────────────────


@pytest.fixture
def shop_info_payload() -> dict:
    return {
        "result": {
            "shop_info": {
                "shop_id": "SHOP12345",
                "shop_name": "优雅女装旗舰店",
                "shop_type": "旗舰店",
                "shop_status": 1,
                "shop_logo": "https://img.xhs.com/logo.png",
                "shop_desc": "专注女装设计，品质生活从这里开始",
                "created_at": "2020-01-01",
            },
        },
    }


# ── Fixtures: Marketing ─────────────────────────────────────────────────────────


@pytest.fixture
def promotion_list_payload() -> dict:
    return {
        "result": {
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
                    "description": "连衣裙限时秒杀79元",
                },
            ],
            "total_count": 2,
        },
    }


@pytest.fixture
def coupon_list_payload() -> dict:
    return {
        "result": {
            "coupon_list": [
                {
                    "coupon_id": "CP00000001",
                    "coupon_name": "新人专享券",
                    "coupon_type": "满减券",
                    "discount_amount": "20.00",
                    "min_order_amount": "99.00",
                    "status": 1,
                    "total_count": 1000,
                    "used_count": 345,
                    "start_time": "2024-01-01 00:00:00",
                    "end_time": "2024-01-31 23:59:59",
                },
                {
                    "coupon_id": "CP00000002",
                    "coupon_name": "粉丝专享折扣券",
                    "coupon_type": "折扣券",
                    "discount_rate": 8.5,
                    "min_order_amount": "199.00",
                    "status": 1,
                    "total_count": 500,
                    "used_count": 120,
                    "start_time": "2024-01-15 00:00:00",
                    "end_time": "2024-02-15 23:59:59",
                },
            ],
            "total_count": 2,
        },
    }


# ── Fixtures: Inventory ─────────────────────────────────────────────────────────


@pytest.fixture
def inventory_payload() -> dict:
    return {
        "result": {
            "inventory_list": [
                {
                    "product_id": "5f8a9b2c3d4e5f6a7b8c9d0e",
                    "product_name": "复古碎花连衣裙 优雅款",
                    "skus": [
                        {"sku_id": "SKU001", "spec": "S码 蓝色碎花", "stock": 200, "locked_stock": 10},
                        {"sku_id": "SKU002", "spec": "M码 蓝色碎花", "stock": 150, "locked_stock": 5},
                    ],
                },
                {
                    "product_id": "5f8a9b2c3d4e5f6a7b8c9d1f",
                    "product_name": "简约纯棉T恤 通勤款",
                    "skus": [
                        {"sku_id": "SKU010", "spec": "M码 白色", "stock": 300, "locked_stock": 20},
                        {"sku_id": "SKU011", "spec": "L码 白色", "stock": 200, "locked_stock": 8},
                    ],
                },
            ],
            "total_count": 2,
        },
    }


# ── Fixtures: Finance ───────────────────────────────────────────────────────────


@pytest.fixture
def bill_list_payload() -> dict:
    return {
        "result": {
            "bill_list": [
                {
                    "bill_id": "BL2024010100001",
                    "bill_type": "订单结算",
                    "amount": "99.00",
                    "fee": "5.00",
                    "settle_amount": "94.00",
                    "order_id": "XHS20240115000001",
                    "create_time": "2024-01-20 10:00:00",
                    "status": 1,
                },
                {
                    "bill_id": "BL2024010200002",
                    "bill_type": "退款",
                    "amount": "-99.00",
                    "fee": "0.00",
                    "settle_amount": "-99.00",
                    "order_id": "XHS20240115000001",
                    "create_time": "2024-01-25 15:00:00",
                    "status": 1,
                },
            ],
            "total_count": 2,
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════════
# Tests: get_order_list
# ═══════════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_order_list_returns_orders_with_correct_fields(mock_call, order_list_payload):
    """get_order_list should return a list of orders with expected fields."""
    mock_call.return_value = order_list_payload

    result_json = await get_order_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
    )
    result = json.loads(result_json)

    assert "result" in result
    orders = result["result"]["order_list"]
    assert len(orders) == 2
    assert result["result"]["total_count"] == 2

    for order in orders:
        assert "order_id" in order
        assert "order_status" in order
        assert "order_amount" in order
        assert "created_at" in order

    mock_call.assert_called_once_with(
        "GET",
        "/api/order/list",
        {"start_time": "2024-01-01 00:00:00", "end_time": "2024-01-31 23:59:59", "page": "1", "page_size": "20"},
    )


@pytest.mark.asyncio
async def test_get_order_list_with_status_filter(mock_call, order_list_payload):
    """get_order_list should include order_status in biz params when provided."""
    mock_call.return_value = order_list_payload

    await get_order_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
        order_status="3",
    )

    _, _, biz_params = mock_call.call_args[0]
    assert biz_params["order_status"] == "3"


@pytest.mark.asyncio
async def test_get_order_list_without_status_omits_field(mock_call, order_list_payload):
    """get_order_list should NOT include order_status when empty."""
    mock_call.return_value = order_list_payload

    await get_order_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
        order_status="",
    )

    _, _, biz_params = mock_call.call_args[0]
    assert "order_status" not in biz_params


# ═══════════════════════════════════════════════════════════════════════════════════
# Tests: get_order_detail
# ═══════════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_order_detail_returns_single_order_with_all_fields(mock_call, order_detail_payload):
    """get_order_detail should return a single order with full details."""
    mock_call.return_value = order_detail_payload

    result_json = await get_order_detail(order_id="XHS20240115000001")
    result = json.loads(result_json)

    details = result["result"]["order_info"]
    assert details["order_id"] == "XHS20240115000001"
    assert details["order_status"] == 1
    assert "order_amount" in details
    assert "discount_amount" in details
    assert "shipping_fee" in details
    assert "pay_amount" in details
    assert "receiver_name" in details
    assert "goods_list" in details
    assert len(details["goods_list"]) == 1
    assert details["goods_list"][0]["product_name"] == "复古碎花连衣裙 优雅款"

    mock_call.assert_called_once_with(
        "GET",
        "/api/order/detail",
        {"order_id": "XHS20240115000001"},
    )


# ═══════════════════════════════════════════════════════════════════════════════════
# Tests: get_product_list
# ═══════════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_product_list_returns_products_with_stock_sold(mock_call, product_list_payload):
    """get_product_list should return products with stock and sold count."""
    mock_call.return_value = product_list_payload

    result_json = await get_product_list()
    result = json.loads(result_json)

    products = result["result"]["product_list"]
    assert len(products) == 2

    for p in products:
        assert "product_id" in p
        assert "product_name" in p
        assert "product_status" in p
        assert "min_price" in p
        assert "stock" in p
        assert "sold_count" in p

    mock_call.assert_called_once_with(
        "GET",
        "/api/product/list",
        {"page": "1", "page_size": "20"},
    )


# ═══════════════════════════════════════════════════════════════════════════════════
# Tests: get_product_detail
# ═══════════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_product_detail_returns_full_product_info(mock_call, product_detail_payload):
    """get_product_detail should return a single product with SKUs and images."""
    mock_call.return_value = product_detail_payload

    result_json = await get_product_detail(product_id="5f8a9b2c3d4e5f6a7b8c9d0e")
    result = json.loads(result_json)

    info = result["result"]["product_info"]
    assert info["product_id"] == "5f8a9b2c3d4e5f6a7b8c9d0e"
    assert info["product_name"] == "复古碎花连衣裙 优雅款"
    assert "product_desc" in info
    assert "category_name" in info
    assert "rating" in info
    assert "images" in info
    assert len(info["images"]) == 2
    assert "skus" in info
    assert len(info["skus"]) == 3
    assert info["skus"][0]["spec"] == "S码 蓝色碎花"

    mock_call.assert_called_once_with(
        "GET",
        "/api/product/detail",
        {"product_id": "5f8a9b2c3d4e5f6a7b8c9d0e"},
    )


# ═══════════════════════════════════════════════════════════════════════════════════
# Tests: get_refund_list
# ═══════════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_refund_list_returns_refunds_with_expected_fields(mock_call, refund_list_payload):
    """get_refund_list should return refund records with correct fields."""
    mock_call.return_value = refund_list_payload

    result_json = await get_refund_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
    )
    result = json.loads(result_json)

    refunds = result["result"]["refund_list"]
    assert len(refunds) == 2

    for r in refunds:
        assert "refund_id" in r
        assert "order_id" in r
        assert "refund_status" in r
        assert "refund_type" in r
        assert "refund_amount" in r
        assert "reason" in r

    mock_call.assert_called_once_with(
        "GET",
        "/api/refund/list",
        {"start_time": "2024-01-01 00:00:00", "end_time": "2024-01-31 23:59:59", "page": "1", "page_size": "20"},
    )


# ═══════════════════════════════════════════════════════════════════════════════════
# Tests: get_refund_detail
# ═══════════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_refund_detail_returns_full_refund_record(mock_call, refund_detail_payload):
    """get_refund_detail should return a single refund record with full details."""
    mock_call.return_value = refund_detail_payload

    result_json = await get_refund_detail(refund_id="RF2024011500001")
    result = json.loads(result_json)

    detail = result["result"]["refund_info"]
    assert detail["refund_id"] == "RF2024011500001"
    assert detail["order_id"] == "XHS20240115000001"
    assert detail["refund_status"] == 1
    assert "refund_type" in detail
    assert "refund_amount" in detail
    assert "reason" in detail
    assert "description" in detail
    assert "evidence" in detail
    assert "product_info" in detail

    mock_call.assert_called_once_with(
        "GET",
        "/api/refund/detail",
        {"refund_id": "RF2024011500001"},
    )


# ═══════════════════════════════════════════════════════════════════════════════════
# Tests: get_logistics_tracking
# ═══════════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_logistics_tracking_returns_tracking_nodes(mock_call, logistics_tracking_payload):
    """get_logistics_tracking should return tracking with ordered nodes."""
    mock_call.return_value = logistics_tracking_payload

    result_json = await get_logistics_tracking(order_id="XHS20240115000001")
    result = json.loads(result_json)

    logistics = result["result"]["logistics_info"]
    assert logistics["order_id"] == "XHS20240115000001"
    assert logistics["logistics_no"] == "XHS0001234567890"
    assert logistics["company"] == "中通快递"
    assert "status" in logistics
    assert "nodes" in logistics
    assert len(logistics["nodes"]) == 4
    assert logistics["nodes"][0]["desc"] == "您的快递已由本人签收"

    mock_call.assert_called_once_with(
        "GET",
        "/api/logistics/tracking",
        {"order_id": "XHS20240115000001"},
    )


# ═══════════════════════════════════════════════════════════════════════════════════
# Tests: get_review_list
# ═══════════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_review_list_returns_reviews_with_expected_fields(mock_call, review_list_payload):
    """get_review_list should return reviews with content, score, and user info."""
    mock_call.return_value = review_list_payload

    result_json = await get_review_list(product_id="5f8a9b2c3d4e5f6a7b8c9d0e")
    result = json.loads(result_json)

    comments = result["result"]["comment_list"]
    assert len(comments) == 2

    for c in comments:
        assert "comment_id" in c
        assert "product_id" in c
        assert "content" in c
        assert "score" in c
        assert "create_time" in c
        assert "user_name" in c

    mock_call.assert_called_once_with(
        "GET",
        "/api/review/list",
        {"product_id": "5f8a9b2c3d4e5f6a7b8c9d0e", "page": "1", "page_size": "20"},
    )


# ═══════════════════════════════════════════════════════════════════════════════════
# Tests: get_shop_info
# ═══════════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_shop_info_returns_shop_details(mock_call, shop_info_payload):
    """get_shop_info should return shop details."""
    mock_call.return_value = shop_info_payload

    result_json = await get_shop_info()
    result = json.loads(result_json)

    shop = result["result"]["shop_info"]
    assert shop["shop_id"] == "SHOP12345"
    assert shop["shop_name"] == "优雅女装旗舰店"
    assert shop["shop_type"] == "旗舰店"
    assert "shop_status" in shop
    assert "shop_logo" in shop
    assert "shop_desc" in shop
    assert "created_at" in shop

    mock_call.assert_called_once_with("GET", "/api/shop/info")


# ═══════════════════════════════════════════════════════════════════════════════════
# Tests: list_promotions
# ═══════════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_list_promotions_returns_promotions_with_expected_fields(mock_call, promotion_list_payload):
    """list_promotions should return promotion activities with timing and type."""
    mock_call.return_value = promotion_list_payload

    result_json = await list_promotions()
    result = json.loads(result_json)

    promos = result["result"]["promotion_list"]
    assert len(promos) == 2

    for p in promos:
        assert "promotion_id" in p
        assert "promotion_name" in p
        assert "promotion_type" in p
        assert "status" in p
        assert "start_time" in p
        assert "end_time" in p

    mock_call.assert_called_once_with(
        "GET",
        "/api/promotion/list",
        {"page": "1", "page_size": "20"},
    )


# ═══════════════════════════════════════════════════════════════════════════════════
# Tests: list_coupons
# ═══════════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_list_coupons_returns_coupons_with_expected_fields(mock_call, coupon_list_payload):
    """list_coupons should return coupons with discount and usage info."""
    mock_call.return_value = coupon_list_payload

    result_json = await list_coupons()
    result = json.loads(result_json)

    coupons = result["result"]["coupon_list"]
    assert len(coupons) == 2

    for c in coupons:
        assert "coupon_id" in c
        assert "coupon_name" in c
        assert "coupon_type" in c
        assert "status" in c
        assert "start_time" in c
        assert "end_time" in c

    # First coupon is a specific-amount coupon
    assert coupons[0]["discount_amount"] == "20.00"
    assert coupons[0]["total_count"] == 1000
    assert coupons[0]["used_count"] == 345

    # Second coupon is a rate-based coupon
    assert coupons[1]["discount_rate"] == 8.5

    mock_call.assert_called_once_with(
        "GET",
        "/api/coupon/list",
        {"page": "1", "page_size": "20"},
    )


@pytest.mark.asyncio
async def test_list_coupons_with_status_filter(mock_call, coupon_list_payload):
    """list_coupons should include status in biz params when provided."""
    mock_call.return_value = coupon_list_payload

    await list_coupons(status="1")

    _, _, biz_params = mock_call.call_args[0]
    assert biz_params["status"] == "1"


# ═══════════════════════════════════════════════════════════════════════════════════
# Tests: get_inventory
# ═══════════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_inventory_returns_inventory_with_sku_details(mock_call, inventory_payload):
    """get_inventory should return inventory with SKU-level stock data."""
    mock_call.return_value = inventory_payload

    result_json = await get_inventory()
    result = json.loads(result_json)

    items = result["result"]["inventory_list"]
    assert len(items) == 2

    for item in items:
        assert "product_id" in item
        assert "product_name" in item
        assert "skus" in item
        for sku in item["skus"]:
            assert "sku_id" in sku
            assert "spec" in sku
            assert "stock" in sku
            assert "locked_stock" in sku

    mock_call.assert_called_once_with(
        "GET",
        "/api/inventory/query",
        {"page": "1", "page_size": "20"},
    )


@pytest.mark.asyncio
async def test_get_inventory_with_product_id_filter(mock_call, inventory_payload):
    """get_inventory should include product_id in biz params when provided."""
    mock_call.return_value = inventory_payload

    await get_inventory(product_id="5f8a9b2c3d4e5f6a7b8c9d0e")

    _, _, biz_params = mock_call.call_args[0]
    assert biz_params["product_id"] == "5f8a9b2c3d4e5f6a7b8c9d0e"


@pytest.mark.asyncio
async def test_get_inventory_without_product_id_omits_field(mock_call, inventory_payload):
    """get_inventory should NOT include product_id when empty string."""
    mock_call.return_value = inventory_payload

    await get_inventory(product_id="")

    _, _, biz_params = mock_call.call_args[0]
    assert "product_id" not in biz_params


# ═══════════════════════════════════════════════════════════════════════════════════
# Tests: get_bill_list
# ═══════════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_bill_list_returns_bills_with_expected_fields(mock_call, bill_list_payload):
    """get_bill_list should return bill records with amount and settlement info."""
    mock_call.return_value = bill_list_payload

    result_json = await get_bill_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
    )
    result = json.loads(result_json)

    bills = result["result"]["bill_list"]
    assert len(bills) == 2

    for b in bills:
        assert "bill_id" in b
        assert "bill_type" in b
        assert "amount" in b
        assert "settle_amount" in b
        assert "create_time" in b
        assert "status" in b

    mock_call.assert_called_once_with(
        "GET",
        "/api/bill/list",
        {"start_time": "2024-01-01 00:00:00", "end_time": "2024-01-31 23:59:59", "page": "1", "page_size": "20"},
    )


# ═══════════════════════════════════════════════════════════════════════════════════
# Tests: Error handling
# ═══════════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_missing_order_id_returned_in_result(mock_call):
    """When order_id is not found, the error response is serialized as JSON."""
    error_response = {
        "error_response": {
            "code": 10001,
            "msg": "order not found",
        },
    }
    mock_call.return_value = error_response

    result_json = await get_order_detail(order_id="XHS99999999999999")
    result = json.loads(result_json)

    assert "error_response" in result
    assert result["error_response"]["code"] == 10001
    assert "order not found" in result["error_response"]["msg"]


@pytest.mark.asyncio
async def test_api_error_propagates(mock_call):
    """When _call raises CommerceAPIError, it should propagate."""
    mock_call.side_effect = CommerceAPIError(code=40001, msg="Invalid client_id")

    with pytest.raises(CommerceAPIError) as exc_info:
        await get_order_list(
            start_time="2024-01-01 00:00:00",
            end_time="2024-01-31 23:59:59",
        )

    assert exc_info.value.code == 40001
    assert "Invalid client_id" in exc_info.value.msg


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


# ═══════════════════════════════════════════════════════════════════════════════════
# Tests: Pagination edge cases
# ═══════════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_pagination_default_page_and_size(mock_call, order_list_payload):
    """Default page=1, page_size=20 should be sent as strings."""
    mock_call.return_value = order_list_payload

    await get_order_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
    )

    _, _, biz_params = mock_call.call_args[0]
    assert biz_params["page"] == "1"
    assert biz_params["page_size"] == "20"


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

    _, _, biz_params = mock_call.call_args[0]
    assert biz_params["page"] == "3"
    assert biz_params["page_size"] == "50"


@pytest.mark.asyncio
async def test_pagination_empty_result_set(mock_call):
    """An empty order list should be handled gracefully."""
    empty_response = {
        "result": {
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

    info = result["result"]
    assert info["total_count"] == 0
    assert info["order_list"] == []


@pytest.mark.asyncio
async def test_pagination_product_list_defaults(mock_call, product_list_payload):
    """Product list pagination defaults should match order list behavior."""
    mock_call.return_value = product_list_payload

    await get_product_list()

    _, _, biz_params = mock_call.call_args[0]
    assert biz_params["page"] == "1"
    assert biz_params["page_size"] == "20"


@pytest.mark.asyncio
async def test_pagination_review_list_custom(mock_call, review_list_payload):
    """Review list should support custom pagination."""
    mock_call.return_value = review_list_payload

    await get_review_list(product_id="5f8a9b2c3d4e5f6a7b8c9d0e", page=2, page_size=10)

    _, _, biz_params = mock_call.call_args[0]
    assert biz_params["product_id"] == "5f8a9b2c3d4e5f6a7b8c9d0e"
    assert biz_params["page"] == "2"
    assert biz_params["page_size"] == "10"


# ═══════════════════════════════════════════════════════════════════════════════════
# Tests: JSON output format
# ═══════════════════════════════════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════════════════════════════════
# Tests: _call passthrough
# ═══════════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_call_passthrough_with_minimal_params(mock_call):
    """Verify _call receives the expected method, path, and biz params."""
    mock_call.return_value = _mock_response({"ok": True})

    await get_order_detail(order_id="XHS20240115000001")

    method, path, biz_params = mock_call.call_args[0]
    assert method == "GET"
    assert path == "/api/order/detail"
    assert biz_params == {"order_id": "XHS20240115000001"}


@pytest.mark.asyncio
async def test_call_passthrough_get_shop_info(mock_call):
    """Verify _call receives correct method and path for no-arg tool."""
    mock_call.return_value = _mock_response({"ok": True})

    await get_shop_info()

    args = mock_call.call_args[0]
    assert args[0] == "GET"
    assert args[1] == "/api/shop/info"


@pytest.mark.asyncio
async def test_call_passthrough_get_logistics_tracking(mock_call):
    """Verify _call receives correct params for logistics tracking."""
    mock_call.return_value = _mock_response({"ok": True})

    await get_logistics_tracking(order_id="XHS20240115000001")

    method, path, biz_params = mock_call.call_args[0]
    assert method == "GET"
    assert path == "/api/logistics/tracking"
    assert biz_params == {"order_id": "XHS20240115000001"}
