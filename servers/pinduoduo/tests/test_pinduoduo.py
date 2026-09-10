"""Legacy tool fixtures: order/refund/shop reads must now fail explicitly.

These payloads are unverified examples, not evidence of the official API schema.
The former positive/error tests now prove they cannot bypass that boundary.
"""

from __future__ import annotations

import json

# Must patch env BEFORE importing the server module (it reads env at import time)
import os
from unittest.mock import AsyncMock, patch

import pytest
from mcp.server.mcpserver.exceptions import ToolError

os.environ.setdefault("PINDUODUO_CLIENT_ID", "test_client_id")
os.environ.setdefault("PINDUODUO_CLIENT_SECRET", "test_client_secret")
os.environ.setdefault("PINDUODUO_ACCESS_TOKEN", "test_access_token")

from servers.pinduoduo.server import (
    get_logistics_tracking,
    get_order_detail,
    get_order_list,
    get_product_detail,
    get_product_list,
    get_refund_detail,
    get_refund_list,
    get_review_list,
    get_shop_info,
    list_logistics_companies,
    list_promotions,
    pdd,
    search_affiliate_goods,
    search_products,
)
from shared.cn_commerce_base import CommerceAPIError

# ── Helpers ─────────────────────────────────────────────────────────────────


def _mock_response(data: dict) -> dict:
    """Shallow wrapper for a successful PDD API response."""
    return data


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_call():
    """Patch pdd._call with an AsyncMock, reset after each test."""
    with patch.object(pdd, "_call", new_callable=AsyncMock) as mock:
        yield mock


# ── Fixtures: Orders ────────────────────────────────────────────────────────


@pytest.fixture
def order_list_payload() -> dict:
    return {
        "order_list_get_response": {
            "order_list": [
                {
                    "order_sn": "231215-1234567890123",
                    "order_status": 1,
                    "order_amount": "99.00",
                    "goods_count": 2,
                    "created_at": "2024-01-15 10:30:00",
                    "receiver_name": "张三",
                    "receiver_phone": "138****8000",
                    "receiver_address": "北京市朝阳区XX路1号",
                },
                {
                    "order_sn": "231215-1234567890456",
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
        "order_information_get_response": {
            "order_info": {
                "order_sn": "231215-1234567890123",
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
                        "goods_id": "987654321",
                        "goods_name": "无线蓝牙耳机 Pro",
                        "goods_price": "99.00",
                        "goods_count": 1,
                        "goods_thumb": "https://img.pdd.com/thumb1.jpg",
                    },
                ],
            },
        },
    }


# ── Fixtures: Products ──────────────────────────────────────────────────────


@pytest.fixture
def product_list_payload() -> dict:
    return {
        "goods_list_get_response": {
            "goods_list": [
                {
                    "goods_id": "987654321",
                    "goods_name": "无线蓝牙耳机 Pro",
                    "goods_status": 1,
                    "min_price": "99.00",
                    "max_price": "129.00",
                    "stock": 500,
                    "sold_count": 1234,
                    "created_at": "2024-01-01 00:00:00",
                },
                {
                    "goods_id": "987654322",
                    "goods_name": "智能手表 运动版",
                    "goods_status": 1,
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
        "goods_detail_get_response": {
            "goods_info": {
                "goods_id": "987654321",
                "goods_name": "无线蓝牙耳机 Pro",
                "goods_desc": "高品质无线蓝牙耳机，主动降噪，超长续航30小时",
                "goods_status": 1,
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
                    "https://img.pdd.com/goods1_1.jpg",
                    "https://img.pdd.com/goods1_2.jpg",
                ],
                "skus": [
                    {"sku_id": "SKU001", "spec": "黑色", "price": "99.00", "stock": 300},
                    {"sku_id": "SKU002", "spec": "白色", "price": "129.00", "stock": 200},
                ],
            },
        },
    }


@pytest.fixture
def search_products_payload() -> dict:
    return {
        "goods_search_response": {
            "goods_list": [
                {
                    "goods_id": "987654321",
                    "goods_name": "无线蓝牙耳机 Pro 主动降噪",
                    "min_price": "99.00",
                    "sold_count": 1234,
                    "mall_name": "数码旗舰店",
                },
                {
                    "goods_id": "987654399",
                    "goods_name": "无线蓝牙耳机 青春版",
                    "min_price": "59.00",
                    "sold_count": 5678,
                    "mall_name": "耳机专营店",
                },
            ],
            "total_count": 2,
        },
    }


# ── Fixtures: After-Sale ────────────────────────────────────────────────────


@pytest.fixture
def refund_list_payload() -> dict:
    return {
        "refund_list_get_response": {
            "refund_list": [
                {
                    "refund_id": "RF123456789",
                    "order_sn": "231215-1234567890123",
                    "refund_status": 1,
                    "refund_type": "退货退款",
                    "refund_amount": "99.00",
                    "apply_time": "2024-01-20 10:00:00",
                    "reason": "商品质量问题",
                },
                {
                    "refund_id": "RF123456790",
                    "order_sn": "231215-1234567890456",
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
        "refund_information_get_response": {
            "refund_info": {
                "refund_id": "RF123456789",
                "order_sn": "231215-1234567890123",
                "refund_status": 1,
                "refund_type": "退货退款",
                "refund_amount": "99.00",
                "apply_time": "2024-01-20 10:00:00",
                "reason": "商品质量问题",
                "description": "收到商品后发现有划痕，要求退货退款",
                "evidence": ["https://img.pdd.com/evidence1.jpg"],
                "goods_info": {
                    "goods_id": "987654321",
                    "goods_name": "无线蓝牙耳机 Pro",
                },
            },
        },
    }


# ── Fixtures: Logistics ─────────────────────────────────────────────────────


@pytest.fixture
def logistics_tracking_payload() -> dict:
    return {
        "logistics_trace_query_response": {
            "logistics_info": {
                "order_sn": "231215-1234567890123",
                "logistics_no": "PDD0001234567890",
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
        "logistics_companies_get_response": {
            "companies": [
                {"company_id": "ZTO", "company_name": "中通快递"},
                {"company_id": "YTO", "company_name": "圆通速递"},
                {"company_id": "STO", "company_name": "申通快递"},
                {"company_id": "EMS", "company_name": "EMS"},
                {"company_id": "SF", "company_name": "顺丰速运"},
            ],
        },
    }


# ── Fixtures: Reviews ───────────────────────────────────────────────────────


@pytest.fixture
def review_list_payload() -> dict:
    return {
        "goods_comments_get_response": {
            "comment_list": [
                {
                    "comment_id": "CM00000001",
                    "goods_id": "987654321",
                    "content": "音质很好，佩戴舒适，推荐购买！",
                    "score": 5,
                    "create_time": "2024-01-20 12:00:00",
                    "user_name": "匿***户",
                    "reply": "感谢您的支持和认可！",
                },
                {
                    "comment_id": "CM00000002",
                    "goods_id": "987654321",
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


# ── Fixtures: Shop ──────────────────────────────────────────────────────────


@pytest.fixture
def shop_info_payload() -> dict:
    return {
        "mall_info_get_response": {
            "mall_info": {
                "mall_id": "12345",
                "mall_name": "数码旗舰店",
                "mall_type": "旗舰店",
                "mall_status": 1,
                "mall_logo": "https://img.pdd.com/logo.png",
                "mall_desc": "专注数码产品，正品保障",
                "created_at": "2020-01-01",
            },
        },
    }


# ── Fixtures: Marketing ─────────────────────────────────────────────────────


@pytest.fixture
def promotion_list_payload() -> dict:
    return {
        "promotion_list_get_response": {
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


# ── Fixtures: Affiliate ─────────────────────────────────────────────────────


@pytest.fixture
def affiliate_goods_payload() -> dict:
    return {
        "ddk_goods_search_response": {
            "goods_list": [
                {
                    "goods_id": "987654321",
                    "goods_name": "无线蓝牙耳机 Pro 主动降噪",
                    "min_price": "99.00",
                    "coupon_price": "79.00",
                    "coupon_discount": "20.00",
                    "commission_rate": 15,
                    "commission_amount": "11.85",
                    "sold_count": 1234,
                    "mall_name": "数码旗舰店",
                },
                {
                    "goods_id": "987654399",
                    "goods_name": "无线蓝牙耳机 青春版",
                    "min_price": "59.00",
                    "coupon_price": "49.00",
                    "coupon_discount": "10.00",
                    "commission_rate": 10,
                    "commission_amount": "4.90",
                    "sold_count": 5678,
                    "mall_name": "耳机专营店",
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
    """An unverified fixture or upstream error cannot authorize a read contract."""
    mock_call.return_value = order_list_payload
    with pytest.raises(ToolError, match="schema"):
        await get_order_list(start_time="2024-01-01 00:00:00", end_time="2024-01-31 23:59:59")
    mock_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_order_list_with_status_filter(mock_call, order_list_payload):
    """An unverified fixture or upstream error cannot authorize a read contract."""
    mock_call.return_value = order_list_payload
    with pytest.raises(ToolError, match="schema"):
        await get_order_list(start_time="2024-01-01 00:00:00", end_time="2024-01-31 23:59:59", order_status="3")
    mock_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_order_list_without_status_omits_field(mock_call, order_list_payload):
    """An unverified fixture or upstream error cannot authorize a read contract."""
    mock_call.return_value = order_list_payload
    with pytest.raises(ToolError, match="schema"):
        await get_order_list(start_time="2024-01-01 00:00:00", end_time="2024-01-31 23:59:59", order_status="")
    mock_call.assert_not_awaited()


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_order_detail
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_order_detail_returns_single_order_with_all_fields(mock_call, order_detail_payload):
    """An unverified fixture or upstream error cannot authorize a read contract."""
    mock_call.return_value = order_detail_payload
    with pytest.raises(ToolError, match="schema"):
        await get_order_detail(order_sn="231215-1234567890123")
    mock_call.assert_not_awaited()


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_product_list
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_product_list_returns_products_with_stock_sold(mock_call, product_list_payload):
    """get_product_list should return products with stock and sold count."""
    mock_call.return_value = product_list_payload

    result_json = await get_product_list()
    result = json.loads(result_json)

    goods = result["goods_list_get_response"]["goods_list"]
    assert len(goods) == 2

    for g in goods:
        assert "goods_id" in g
        assert "goods_name" in g
        assert "goods_status" in g
        assert "min_price" in g
        assert "stock" in g
        assert "sold_count" in g

    mock_call.assert_called_once_with(
        "pdd.goods.list.get",
        {"page": "1", "page_size": "20"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_product_detail
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_product_detail_returns_full_product_info(mock_call, product_detail_payload):
    """get_product_detail should return a single product with SKUs and images."""
    mock_call.return_value = product_detail_payload

    result_json = await get_product_detail(goods_id="987654321")
    result = json.loads(result_json)

    info = result["goods_detail_get_response"]["goods_info"]
    assert info["goods_id"] == "987654321"
    assert info["goods_name"] == "无线蓝牙耳机 Pro"
    assert "goods_desc" in info
    assert "category_name" in info
    assert "rating" in info
    assert "images" in info
    assert len(info["images"]) == 2
    assert "skus" in info
    assert len(info["skus"]) == 2
    assert info["skus"][0]["spec"] == "黑色"

    mock_call.assert_called_once_with(
        "pdd.goods.detail.get",
        {"goods_id": "987654321"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: search_products
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_search_products_returns_matching_results(mock_call, search_products_payload):
    """search_products should return goods matching the search keyword."""
    mock_call.return_value = search_products_payload

    result_json = await search_products(keyword="蓝牙耳机")
    result = json.loads(result_json)

    goods = result["goods_search_response"]["goods_list"]
    assert len(goods) == 2

    for g in goods:
        assert "goods_id" in g
        assert "goods_name" in g
        assert "min_price" in g
        assert "mall_name" in g

    mock_call.assert_called_once_with(
        "pdd.goods.search",
        {"keyword": "蓝牙耳机", "page": "1", "page_size": "20"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_refund_list
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_refund_list_returns_refunds_with_expected_fields(mock_call, refund_list_payload):
    """An unverified fixture or upstream error cannot authorize a read contract."""
    mock_call.return_value = refund_list_payload
    with pytest.raises(ToolError, match="schema"):
        await get_refund_list(start_time="2024-01-01 00:00:00", end_time="2024-01-31 23:59:59")
    mock_call.assert_not_awaited()


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_refund_detail
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_refund_detail_returns_full_refund_record(mock_call, refund_detail_payload):
    """An unverified fixture or upstream error cannot authorize a read contract."""
    mock_call.return_value = refund_detail_payload
    with pytest.raises(ToolError, match="schema"):
        await get_refund_detail(refund_id="RF123456789")
    mock_call.assert_not_awaited()


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_logistics_tracking
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_logistics_tracking_returns_tracking_nodes(mock_call, logistics_tracking_payload):
    """get_logistics_tracking should return tracking with ordered nodes."""
    mock_call.return_value = logistics_tracking_payload

    result_json = await get_logistics_tracking(order_sn="231215-1234567890123")
    result = json.loads(result_json)

    logistics = result["logistics_trace_query_response"]["logistics_info"]
    assert logistics["order_sn"] == "231215-1234567890123"
    assert logistics["logistics_no"] == "PDD0001234567890"
    assert logistics["company"] == "中通快递"
    assert "status" in logistics
    assert "nodes" in logistics
    assert len(logistics["nodes"]) == 4
    assert logistics["nodes"][0]["desc"] == "您的快递已由本人签收"

    mock_call.assert_called_once_with(
        "pdd.logistics.trace.query",
        {"order_sn": "231215-1234567890123"},
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

    companies = result["logistics_companies_get_response"]["companies"]
    assert len(companies) == 5

    for c in companies:
        assert "company_id" in c
        assert "company_name" in c

    assert companies[0]["company_name"] == "中通快递"

    mock_call.assert_called_once_with("pdd.logistics.companies.get", {})


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_review_list
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_review_list_returns_reviews_with_expected_fields(mock_call, review_list_payload):
    """get_review_list should return reviews with content, score, and user info."""
    mock_call.return_value = review_list_payload

    result_json = await get_review_list(goods_id="987654321")
    result = json.loads(result_json)

    comments = result["goods_comments_get_response"]["comment_list"]
    assert len(comments) == 2

    for c in comments:
        assert "comment_id" in c
        assert "goods_id" in c
        assert "content" in c
        assert "score" in c
        assert "create_time" in c
        assert "user_name" in c

    mock_call.assert_called_once_with(
        "pdd.goods.comments.get",
        {"goods_id": "987654321", "page": "1", "page_size": "20"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_shop_info
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_shop_info_returns_shop_details(mock_call, shop_info_payload):
    """An unverified fixture or upstream error cannot authorize a read contract."""
    mock_call.return_value = shop_info_payload
    with pytest.raises(ToolError, match="schema"):
        await get_shop_info()
    mock_call.assert_not_awaited()


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: list_promotions
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_list_promotions_returns_promotions_with_expected_fields(mock_call, promotion_list_payload):
    """list_promotions should return promotion activities with timing and type."""
    mock_call.return_value = promotion_list_payload

    result_json = await list_promotions()
    result = json.loads(result_json)

    promos = result["promotion_list_get_response"]["promotion_list"]
    assert len(promos) == 2

    for p in promos:
        assert "promotion_id" in p
        assert "promotion_name" in p
        assert "promotion_type" in p
        assert "status" in p
        assert "start_time" in p
        assert "end_time" in p

    mock_call.assert_called_once_with(
        "pdd.promotion.list.get",
        {"page": "1", "page_size": "20"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: search_affiliate_goods
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_search_affiliate_goods_returns_goods_with_commission(mock_call, affiliate_goods_payload):
    """search_affiliate_goods should return affiliate goods with commission info."""
    mock_call.return_value = affiliate_goods_payload

    result_json = await search_affiliate_goods(keyword="蓝牙耳机")
    result = json.loads(result_json)

    goods = result["ddk_goods_search_response"]["goods_list"]
    assert len(goods) == 2

    for g in goods:
        assert "goods_id" in g
        assert "goods_name" in g
        assert "min_price" in g
        assert "coupon_price" in g
        assert "commission_rate" in g
        assert "commission_amount" in g
        assert "mall_name" in g

    mock_call.assert_called_once_with(
        "pdd.ddk.goods.search",
        {"keyword": "蓝牙耳机", "page": "1", "page_size": "20"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: Error handling
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_missing_order_sn_returned_in_result(mock_call):
    """An unverified fixture or upstream error cannot authorize a read contract."""
    error_response = {"error_response": {"error_code": 10001, "error_msg": "order_sn not found"}}
    mock_call.return_value = error_response
    with pytest.raises(ToolError, match="schema"):
        await get_order_detail(order_sn="999999-9999999999999")
    mock_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_api_error_propagates(mock_call):
    """An unverified fixture or upstream error cannot authorize a read contract."""
    mock_call.side_effect = CommerceAPIError(code=40001, msg="Invalid client_id")
    with pytest.raises(ToolError, match="schema"):
        await get_order_list(start_time="2024-01-01 00:00:00", end_time="2024-01-31 23:59:59")
    mock_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_timeout_propagates(mock_call):
    """When _call raises TimeoutError, it should propagate."""
    mock_call.side_effect = TimeoutError("Connection timed out")

    with pytest.raises(TimeoutError, match="Connection timed out"):
        await get_product_list()


@pytest.mark.asyncio
async def test_refund_api_error_propagates(mock_call):
    """An unverified fixture or upstream error cannot authorize a read contract."""
    mock_call.side_effect = CommerceAPIError(code=50001, msg="Refund record not found")
    with pytest.raises(ToolError, match="schema"):
        await get_refund_detail(refund_id="RF99999999")
    mock_call.assert_not_awaited()


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: Pagination edge cases
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_pagination_default_page_and_size(mock_call, order_list_payload):
    """An unverified fixture or upstream error cannot authorize a read contract."""
    mock_call.return_value = order_list_payload
    with pytest.raises(ToolError, match="schema"):
        await get_order_list(start_time="2024-01-01 00:00:00", end_time="2024-01-31 23:59:59")
    mock_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_pagination_custom_page(mock_call, order_list_payload):
    """An unverified fixture or upstream error cannot authorize a read contract."""
    mock_call.return_value = order_list_payload
    with pytest.raises(ToolError, match="schema"):
        await get_order_list(start_time="2024-01-01 00:00:00", end_time="2024-01-31 23:59:59", page=3, page_size=50)
    mock_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_pagination_empty_result_set(mock_call):
    """An unverified fixture or upstream error cannot authorize a read contract."""
    empty_response = {"order_list_get_response": {"order_list": [], "total_count": 0}}
    mock_call.return_value = empty_response
    with pytest.raises(ToolError, match="schema"):
        await get_order_list(start_time="2024-01-01 00:00:00", end_time="2024-01-01 00:00:01")
    mock_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_pagination_product_list_defaults(mock_call, product_list_payload):
    """Product list pagination defaults should match order list behavior."""
    mock_call.return_value = product_list_payload

    await get_product_list()

    _, biz_params = mock_call.call_args[0]
    assert biz_params["page"] == "1"
    assert biz_params["page_size"] == "20"


@pytest.mark.asyncio
async def test_pagination_review_list_custom(mock_call, review_list_payload):
    """Review list should support custom pagination."""
    mock_call.return_value = review_list_payload

    await get_review_list(goods_id="987654321", page=2, page_size=10)

    _, biz_params = mock_call.call_args[0]
    assert biz_params["goods_id"] == "987654321"
    assert biz_params["page"] == "2"
    assert biz_params["page_size"] == "10"


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: JSON output format
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_output_is_valid_json_string(mock_call, order_list_payload):
    """An unverified fixture or upstream error cannot authorize a read contract."""
    mock_call.return_value = order_list_payload
    with pytest.raises(ToolError, match="schema"):
        await get_order_list(start_time="2024-01-01 00:00:00", end_time="2024-01-31 23:59:59")
    mock_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_refund_output_is_valid_json_string(mock_call, refund_list_payload):
    """An unverified fixture or upstream error cannot authorize a read contract."""
    mock_call.return_value = refund_list_payload
    with pytest.raises(ToolError, match="schema"):
        await get_refund_list(start_time="2024-01-01 00:00:00", end_time="2024-01-31 23:59:59")
    mock_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_shop_info_output_is_valid_json_string(mock_call, shop_info_payload):
    """An unverified fixture or upstream error cannot authorize a read contract."""
    mock_call.return_value = shop_info_payload
    with pytest.raises(ToolError, match="schema"):
        await get_shop_info()
    mock_call.assert_not_awaited()


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: _call passthrough
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_call_passthrough_with_minimal_params(mock_call):
    """An unverified fixture or upstream error cannot authorize a read contract."""
    mock_call.return_value = _mock_response({"ok": True})
    with pytest.raises(ToolError, match="schema"):
        await get_order_detail(order_sn="231215-1234567890123")
    mock_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_call_passthrough_search_products(mock_call):
    """Verify _call receives correct API type and params for search."""
    mock_call.return_value = _mock_response({"ok": True})

    await search_products(keyword="耳机", page=2, page_size=10)

    api_type, biz_params = mock_call.call_args[0]
    assert api_type == "pdd.goods.search"
    assert biz_params == {"keyword": "耳机", "page": "2", "page_size": "10"}


@pytest.mark.asyncio
async def test_call_passthrough_list_logistics_companies(mock_call):
    """Verify _call receives empty biz params for no-arg tool."""
    mock_call.return_value = _mock_response({"ok": True})

    await list_logistics_companies()

    api_type, biz_params = mock_call.call_args[0]
    assert api_type == "pdd.logistics.companies.get"
    assert biz_params == {}
