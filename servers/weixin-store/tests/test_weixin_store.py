"""Tests for WeChat Store (微信小店) MCP server tools."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

# Must patch env BEFORE importing the server module (it reads env at import time)
import os

os.environ.setdefault("WX_ACCESS_TOKEN", "test_access_token_123456")

from mcp_weixin_store.server import (
    get_order_list,
    get_order_detail,
    get_product_list,
    get_product_detail,
    get_refund_list,
    get_refund_detail,
    get_logistics_tracking,
    get_shop_info,
    list_coupons,
    get_supply_order_list,
    list_categories,
    _wx,
)
from shared.cn_commerce_base import CommerceAPIError


# ── Helpers ─────────────────────────────────────────────────────────────────


def _mock_response(data: dict) -> dict:
    """Shallow wrapper for a successful WeChat Store API response (no errcode)."""
    return data


# ── Fixture ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_request():
    """Patch _wx._request with an AsyncMock, reset after each test."""
    with patch.object(_wx, "_request", new_callable=AsyncMock) as mock:
        yield mock


# ── Fixtures: Orders ────────────────────────────────────────────────────────


@pytest.fixture
def order_list_payload() -> dict:
    return {
        "errcode": 0,
        "errmsg": "ok",
        "orders": [
            {
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
                        },
                        {
                            "product_id": "10000000000002",
                            "sku_id": "20000000000002",
                            "title": "手机壳 透明款",
                            "sale_price": 2900,
                            "product_cnt": 1,
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
                        "receiver_tel": "138****8000",
                        "receiver_address": "北京市朝阳区XX路1号",
                    },
                    "create_time": "2024-01-15 10:30:00",
                },
            },
            {
                "order_id": "3705115058471207456",
                "status": 50,
                "product_count": 1,
                "order_detail": {
                    "product_infos": [
                        {
                            "product_id": "10000000000003",
                            "sku_id": "20000000000003",
                            "title": "智能手表 运动版",
                            "sale_price": 29900,
                            "product_cnt": 1,
                        },
                    ],
                    "price_info": {
                        "product_price": 29900,
                        "order_price": 27900,
                        "freight": 0,
                        "discounted_price": 2000,
                    },
                    "delivery_info": {
                        "receiver_name": "李四",
                        "receiver_tel": "139****9000",
                        "receiver_address": "上海市浦东新区YY路2号",
                    },
                    "create_time": "2024-01-16 14:20:00",
                },
            },
        ],
        "total_num": 2,
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
    return {
        "errcode": 0,
        "errmsg": "ok",
        "product_ids": ["10000000000001", "10000000000002"],
        "products": [
            {
                "product_id": "10000000000001",
                "title": "无线蓝牙耳机 Pro",
                "status": 1,
                "min_price": 9900,
                "head_imgs": ["https://wximg.com/p1.jpg"],
                "stock_num": 500,
                "total_sold_num": 1234,
                "create_time": "2024-01-01 00:00:00",
            },
            {
                "product_id": "10000000000002",
                "title": "手机壳 透明款",
                "status": 1,
                "min_price": 2900,
                "head_imgs": ["https://wximg.com/p2.jpg"],
                "stock_num": 200,
                "total_sold_num": 567,
                "create_time": "2024-01-05 00:00:00",
            },
        ],
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
            "status": 1,
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
    return {
        "errcode": 0,
        "errmsg": "ok",
        "after_sale_orders": [
            {
                "after_sale_order_id": "3705115058471207123",
                "order_id": "3705115058471207123",
                "status": 1,
                "type": "RETURN",
                "refund_info": {"amount": 9900},
                "apply_time": "2024-01-20 10:00:00",
                "reason_text": "商品质量问题",
            },
            {
                "after_sale_order_id": "3705115058471207456",
                "order_id": "3705115058471207456",
                "status": 3,
                "type": "REFUND",
                "refund_info": {"amount": 29900},
                "apply_time": "2024-01-25 15:30:00",
                "reason_text": "未收到货",
            },
        ],
        "total_num": 2,
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


# ── Fixtures: Logistics ─────────────────────────────────────────────────────


@pytest.fixture
def logistics_tracking_payload() -> dict:
    return {
        "errcode": 0,
        "errmsg": "ok",
        "delivery_info": {
            "order_id": "3705115058471207123",
            "delivery_id": "WXDELIVERY0123456789",
            "delivery_company": "中通快递",
            "status": 3,
            "waybill_id": "ZTO987654321",
            "nodes": [
                {"time": "2024-01-18 08:00:00", "desc": "您的快递已由本人签收", "status": 3},
                {"time": "2024-01-18 06:30:00", "desc": "您的快递正在派送中", "status": 2},
                {"time": "2024-01-17 20:00:00", "desc": "您的快递已到达【北京朝阳网点】", "status": 1},
                {"time": "2024-01-16 15:00:00", "desc": "您的快递已发货", "status": 0},
            ],
        },
    }


# ── Fixtures: Shop ──────────────────────────────────────────────────────────


@pytest.fixture
def shop_info_payload() -> dict:
    return {
        "errcode": 0,
        "errmsg": "ok",
        "shop_info": {
            "shop_id": "wx1234567890abcdef",
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
                "status": 1,
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
                "status": 1,
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
        "total_num": 2,
    }


# ── Fixtures: Supply Chain ──────────────────────────────────────────────────


@pytest.fixture
def supply_order_list_payload() -> dict:
    return {
        "errcode": 0,
        "errmsg": "ok",
        "orders": [
            {
                "supply_order_id": "SUPP20240115001",
                "status": 2,
                "product_name": "无线蓝牙耳机 Pro",
                "quantity": 100,
                "unit_price": 6900,
                "total_price": 690000,
                "create_time": "2024-01-10 09:00:00",
                "ship_time": "2024-01-15 16:00:00",
            },
            {
                "supply_order_id": "SUPP20240120002",
                "status": 1,
                "product_name": "手机壳 透明款",
                "quantity": 500,
                "unit_price": 1500,
                "total_price": 750000,
                "create_time": "2024-01-20 11:00:00",
            },
        ],
        "total_num": 2,
    }


# ── Fixtures: Categories ────────────────────────────────────────────────────


@pytest.fixture
def categories_payload() -> dict:
    return {
        "errcode": 0,
        "errmsg": "ok",
        "categories": [
            {
                "category_id": 1,
                "category_name": "服饰鞋包",
                "level": 1,
                "parent_id": 0,
                "has_child": True,
            },
            {
                "category_id": 2,
                "category_name": "数码电器",
                "level": 1,
                "parent_id": 0,
                "has_child": True,
            },
            {
                "category_id": 3,
                "category_name": "家居日用",
                "level": 1,
                "parent_id": 0,
                "has_child": True,
            },
            {
                "category_id": 4,
                "category_name": "食品生鲜",
                "level": 1,
                "parent_id": 0,
                "has_child": True,
            },
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_order_list
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_order_list_returns_orders_with_correct_fields(
    mock_request, order_list_payload
):
    """get_order_list should return a list of orders with expected fields."""
    mock_request.return_value = order_list_payload

    result_json = await get_order_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
    )
    result = json.loads(result_json)

    assert result["errcode"] == 0
    assert "orders" in result
    orders = result["orders"]
    assert len(orders) == 2
    assert result["total_num"] == 2

    for order in orders:
        assert "order_id" in order
        assert "status" in order
        assert "order_detail" in order
        assert "create_time" in order["order_detail"]

    mock_request.assert_called_once_with(
        "POST",
        "/channels/ec/order/list/get",
        data={
            "start_create_time": "2024-01-01 00:00:00",
            "end_create_time": "2024-01-31 23:59:59",
            "page": 1,
            "page_size": 20,
        },
    )


@pytest.mark.asyncio
async def test_get_order_list_with_status_filter(mock_request, order_list_payload):
    """get_order_list should include status in data when provided."""
    mock_request.return_value = order_list_payload

    await get_order_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
        order_status="20",
    )

    kwargs = mock_request.call_args[1]
    assert kwargs["data"]["status"] == 20


@pytest.mark.asyncio
async def test_get_order_list_without_status_omits_field(mock_request, order_list_payload):
    """get_order_list should NOT include status when empty."""
    mock_request.return_value = order_list_payload

    await get_order_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
        order_status="",
    )

    kwargs = mock_request.call_args[1]
    assert "status" not in kwargs["data"]


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_order_detail
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_order_detail_returns_single_order_with_all_fields(
    mock_request, order_detail_payload
):
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
async def test_get_product_list_returns_products_with_stock_sold(
    mock_request, product_list_payload
):
    """get_product_list should return products with stock and sold count."""
    mock_request.return_value = product_list_payload

    result_json = await get_product_list()
    result = json.loads(result_json)

    assert result["errcode"] == 0
    products = result["products"]
    assert len(products) == 2

    for p in products:
        assert "product_id" in p
        assert "title" in p
        assert "status" in p
        assert "min_price" in p
        assert "stock_num" in p
        assert "total_sold_num" in p

    mock_request.assert_called_once_with(
        "POST",
        "/channels/ec/product/list/get",
        data={"status": 0, "page": 1, "page_size": 20},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_product_detail
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_product_detail_returns_full_product_info(
    mock_request, product_detail_payload
):
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
        data={"product_id": "10000000000001"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_refund_list
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_refund_list_returns_refunds_with_expected_fields(
    mock_request, refund_list_payload
):
    """get_refund_list should return after-sale records with correct fields."""
    mock_request.return_value = refund_list_payload

    result_json = await get_refund_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
    )
    result = json.loads(result_json)

    assert result["errcode"] == 0
    refunds = result["after_sale_orders"]
    assert len(refunds) == 2

    for r in refunds:
        assert "after_sale_order_id" in r
        assert "order_id" in r
        assert "status" in r
        assert "type" in r
        assert "refund_info" in r
        assert "reason_text" in r

    mock_request.assert_called_once_with(
        "POST",
        "/channels/ec/aftersale/getaftersalelist",
        data={
            "begin_create_time": "2024-01-01 00:00:00",
            "end_create_time": "2024-01-31 23:59:59",
            "page": 1,
            "page_size": 20,
        },
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_refund_detail
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_refund_detail_returns_full_refund_record(
    mock_request, refund_detail_payload
):
    """get_refund_detail should return a single after-sale record with full details."""
    mock_request.return_value = refund_detail_payload

    result_json = await get_refund_detail(
        after_sale_order_id="3705115058471207123"
    )
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
async def test_get_logistics_tracking_returns_tracking_nodes(
    mock_request, logistics_tracking_payload
):
    """get_logistics_tracking should return tracking with ordered nodes."""
    mock_request.return_value = logistics_tracking_payload

    result_json = await get_logistics_tracking(order_id="3705115058471207123")
    result = json.loads(result_json)

    assert result["errcode"] == 0
    delivery = result["delivery_info"]
    assert delivery["order_id"] == "3705115058471207123"
    assert delivery["delivery_id"] == "WXDELIVERY0123456789"
    assert delivery["delivery_company"] == "中通快递"
    assert "waybill_id" in delivery
    assert "nodes" in delivery
    assert len(delivery["nodes"]) == 4
    assert delivery["nodes"][0]["desc"] == "您的快递已由本人签收"

    mock_request.assert_called_once_with(
        "POST",
        "/channels/ec/order/deliveryinfo/get",
        data={"order_id": "3705115058471207123"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_shop_info
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_shop_info_returns_shop_details(
    mock_request, shop_info_payload
):
    """get_shop_info should return shop details."""
    mock_request.return_value = shop_info_payload

    result_json = await get_shop_info()
    result = json.loads(result_json)

    assert result["errcode"] == 0
    shop = result["shop_info"]
    assert shop["shop_id"] == "wx1234567890abcdef"
    assert shop["shop_name"] == "数码旗舰店"
    assert shop["shop_type"] == 1
    assert "shop_logo" in shop
    assert "shop_desc" in shop
    assert "status" in shop
    assert "created_at" in shop

    mock_request.assert_called_once_with(
        "POST",
        "/channels/ec/basicinfo/get",
        data={},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: list_coupons
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_list_coupons_returns_coupons_with_expected_fields(
    mock_request, coupon_list_payload
):
    """list_coupons should return coupon activities with timing and stock info."""
    mock_request.return_value = coupon_list_payload

    result_json = await list_coupons()
    result = json.loads(result_json)

    assert result["errcode"] == 0
    coupons = result["coupons"]
    assert len(coupons) == 2

    for c in coupons:
        assert "coupon_id" in c
        assert "name" in c
        assert "type" in c
        assert "status" in c
        assert "promote_info" in c
        assert "valid_info" in c
        assert "stock_info" in c

    mock_request.assert_called_once_with(
        "POST",
        "/channels/ec/coupon/list/get",
        data={"status": 0, "page": 1, "page_size": 20},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_supply_order_list
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_supply_order_list_returns_supply_orders(
    mock_request, supply_order_list_payload
):
    """get_supply_order_list should return supply chain orders with pricing."""
    mock_request.return_value = supply_order_list_payload

    result_json = await get_supply_order_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
    )
    result = json.loads(result_json)

    assert result["errcode"] == 0
    orders = result["orders"]
    assert len(orders) == 2

    for o in orders:
        assert "supply_order_id" in o
        assert "status" in o
        assert "product_name" in o
        assert "quantity" in o
        assert "unit_price" in o
        assert "total_price" in o
        assert "create_time" in o

    mock_request.assert_called_once_with(
        "POST",
        "/channels/ec/supplier/order/list/get",
        data={
            "start_create_time": "2024-01-01 00:00:00",
            "end_create_time": "2024-01-31 23:59:59",
            "status": 0,
            "page": 1,
            "page_size": 20,
        },
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: list_categories
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_list_categories_returns_top_level_categories(
    mock_request, categories_payload
):
    """list_categories should return top-level categories with has_child flag."""
    mock_request.return_value = categories_payload

    result_json = await list_categories()
    result = json.loads(result_json)

    assert result["errcode"] == 0
    cats = result["categories"]
    assert len(cats) == 4

    for c in cats:
        assert "category_id" in c
        assert "category_name" in c
        assert "level" in c
        assert "parent_id" in c
        assert "has_child" in c

    mock_request.assert_called_once_with(
        "POST",
        "/channels/ec/category/list/get",
        data={"parent_id": 0},
    )


@pytest.mark.asyncio
async def test_list_categories_with_parent_id(mock_request, categories_payload):
    """list_categories should pass parent_id to the API when provided."""
    mock_request.return_value = categories_payload

    await list_categories(parent_id=1)

    kwargs = mock_request.call_args[1]
    assert kwargs["data"]["parent_id"] == 1


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
    mock_request.side_effect = CommerceAPIError(
        code=40001, msg="invalid access_token"
    )

    with pytest.raises(CommerceAPIError) as exc_info:
        await get_order_list(
            start_time="2024-01-01 00:00:00",
            end_time="2024-01-31 23:59:59",
        )

    assert exc_info.value.code == 40001
    assert "invalid access_token" in exc_info.value.msg


@pytest.mark.asyncio
async def test_timeout_propagates(mock_request):
    """When _request raises TimeoutError, it should propagate."""
    mock_request.side_effect = TimeoutError("Connection timed out")

    with pytest.raises(TimeoutError, match="Connection timed out"):
        await get_product_list()


@pytest.mark.asyncio
async def test_refund_api_error_propagates(mock_request):
    """CommerceAPIError from refund tools should propagate."""
    mock_request.side_effect = CommerceAPIError(
        code=50001, msg="After-sale record not found"
    )

    with pytest.raises(CommerceAPIError) as exc_info:
        await get_refund_detail(after_sale_order_id="99999999")

    assert exc_info.value.code == 50001
    assert "After-sale record not found" in exc_info.value.msg


@pytest.mark.asyncio
async def test_supply_order_api_error_propagates(mock_request):
    """CommerceAPIError from supply chain tools should propagate."""
    mock_request.side_effect = CommerceAPIError(
        code=60001, msg="Supply order not found"
    )

    with pytest.raises(CommerceAPIError) as exc_info:
        await get_supply_order_list(
            start_time="2024-01-01 00:00:00",
            end_time="2024-01-31 23:59:59",
        )

    assert exc_info.value.code == 60001
    assert "Supply order not found" in exc_info.value.msg


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: JSON output format
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_output_is_valid_json_string(mock_request, order_list_payload):
    """All tool return values should be valid JSON strings."""
    mock_request.return_value = order_list_payload

    result = await get_order_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
    )

    assert isinstance(result, str)
    parsed = json.loads(result)
    assert isinstance(parsed, dict)


@pytest.mark.asyncio
async def test_refund_output_is_valid_json_string(mock_request, refund_list_payload):
    """Refund tools should return valid JSON strings."""
    mock_request.return_value = refund_list_payload

    result = await get_refund_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
    )

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
async def test_pagination_default_page_and_size(mock_request, order_list_payload):
    """Default page=1, page_size=20 should be sent as ints."""
    mock_request.return_value = order_list_payload

    await get_order_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
    )

    kwargs = mock_request.call_args[1]
    assert kwargs["data"]["page"] == 1
    assert kwargs["data"]["page_size"] == 20


@pytest.mark.asyncio
async def test_pagination_custom_page(mock_request, order_list_payload):
    """Custom page and page_size values should be passed correctly."""
    mock_request.return_value = order_list_payload

    await get_order_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
        page=3,
        page_size=50,
    )

    kwargs = mock_request.call_args[1]
    assert kwargs["data"]["page"] == 3
    assert kwargs["data"]["page_size"] == 50


@pytest.mark.asyncio
async def test_pagination_empty_result_set(mock_request):
    """An empty order list should be handled gracefully."""
    empty_response = {
        "errcode": 0,
        "errmsg": "ok",
        "orders": [],
        "total_num": 0,
    }
    mock_request.return_value = empty_response

    result_json = await get_order_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-01 00:00:01",
    )
    result = json.loads(result_json)

    assert result["errcode"] == 0
    assert result["total_num"] == 0
    assert result["orders"] == []
