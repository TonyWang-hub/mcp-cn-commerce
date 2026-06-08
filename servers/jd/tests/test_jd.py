"""Tests for JD MCP server tools."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

# Must patch env BEFORE importing the server module (it reads env at import time)
import os

os.environ.setdefault("JD_APP_KEY", "test_key")
os.environ.setdefault("JD_APP_SECRET", "test_secret")
os.environ.setdefault("JD_ACCESS_TOKEN", "test_token")

from mcp_jd.server import (
    get_order_list,
    get_order_detail,
    get_product_list,
    get_shop_info,
    get_after_sale_list,
    get_after_sale_detail,
    get_logistics_tracking,
    get_review_list,
    get_review_detail,
    get_price_info,
    get_inventory,
    list_promotions,
    list_coupons,
    list_categories,
    get_shop_score,
    jd,
)
from shared.cn_commerce_base import CommerceAPIError


# ── Helpers ─────────────────────────────────────────────────────────────────

def _mock_response(data: dict) -> dict:
    """Shallow wrapper for a successful JD API response."""
    return data


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_call():
    """Patch jd._call with an AsyncMock, reset after each test."""
    with patch.object(jd, "_call", new_callable=AsyncMock) as mock:
        yield mock


# ── Fixtures: existing tools ────────────────────────────────────────────────

@pytest.fixture
def order_payload() -> dict:
    return {
        "jingdong_pop_order_search_responce": {
            "searchorderinfo_result": {
                "order_info_list": {
                    "order_info": [
                        {
                            "order_id": "3000000000001",
                            "order_state": "WAIT_SELLER_STOCK_OUT",
                            "order_create_time": "2024-01-15 10:30:00",
                            "order_payment": "99.00",
                            "order_total_price": "99.00",
                            "consignee_info": {
                                "fullname": "张三",
                                "mobile": "13800138000",
                                "full_address": "北京市朝阳区XX路1号",
                            },
                        },
                        {
                            "order_id": "3000000000002",
                            "order_state": "FINISHED_L",
                            "order_create_time": "2024-01-16 14:20:00",
                            "order_payment": "199.00",
                            "order_total_price": "199.00",
                            "consignee_info": {
                                "fullname": "李四",
                                "mobile": "13900139000",
                                "full_address": "上海市浦东新区YY路2号",
                            },
                        },
                    ],
                },
                "order_total": 2,
            },
        },
    }


@pytest.fixture
def order_detail_payload() -> dict:
    return {
        "jingdong_pop_order_get_responce": {
            "orderDetailInfo": {
                "order_id": "3000000000001",
                "order_state": "WAIT_SELLER_STOCK_OUT",
                "order_create_time": "2024-01-15 10:30:00",
                "order_payment": "99.00",
                "order_total_price": "99.00",
                "order_delivery_price": "0.00",
                "consignee_info": {
                    "fullname": "张三",
                    "mobile": "13800138000",
                    "full_address": "北京市朝阳区XX路1号",
                },
                "item_info_list": [
                    {
                        "sku_id": "10000001",
                        "sku_name": "无线蓝牙耳机",
                        "sku_num": "1",
                        "sku_price": "99.00",
                    },
                ],
            },
        },
    }


@pytest.fixture
def product_list_payload() -> dict:
    return {
        "jingdong_pop_ware_search_responce": {
            "ware_list": {
                "ware_info": [
                    {
                        "ware_id": "20000001",
                        "ware_name": "无线蓝牙耳机 Pro",
                        "ware_status": "2",
                        "jd_price": "129.00",
                        "stock_num": "500",
                    },
                    {
                        "ware_id": "20000002",
                        "ware_name": "智能手表",
                        "ware_status": "2",
                        "jd_price": "299.00",
                        "stock_num": "200",
                    },
                ],
                "total": 2,
            },
        },
    }


@pytest.fixture
def shop_info_payload() -> dict:
    return {
        "jingdong_pop_shop_get_responce": {
            "shop_info": {
                "shop_id": "10000001",
                "shop_name": "XX官方旗舰店",
                "shop_status": "1",
                "shop_score": "4.9",
                "open_time": "2020-01-01",
            },
        },
    }


# ── Fixtures: after-sale ────────────────────────────────────────────────────

@pytest.fixture
def after_sale_list_payload() -> dict:
    return {
        "jingdong_pop_afs_search_responce": {
            "after_sale_list": {
                "after_sale_info": [
                    {
                        "after_sale_id": "AS00000001",
                        "order_id": "3000000000001",
                        "status": "WAIT_SELLER_AGREE",
                        "type": "退货退款",
                        "apply_time": "2024-01-20 10:00:00",
                        "amount": "99.00",
                        "reason": "商品质量问题",
                    },
                    {
                        "after_sale_id": "AS00000002",
                        "order_id": "3000000000002",
                        "status": "COMPLETE",
                        "type": "仅退款",
                        "apply_time": "2024-01-25 15:30:00",
                        "amount": "199.00",
                        "reason": "未收到货",
                    },
                ],
                "total": 2,
            },
        },
    }


@pytest.fixture
def after_sale_detail_payload() -> dict:
    return {
        "jingdong_pop_afs_get_responce": {
            "after_sale_detail": {
                "after_sale_id": "AS00000001",
                "order_id": "3000000000001",
                "status": "WAIT_SELLER_AGREE",
                "type": "退货退款",
                "apply_time": "2024-01-20 10:00:00",
                "amount": "99.00",
                "reason": "商品质量问题",
                "description": "收到商品后发现有划痕，要求退货退款",
                "evidence": ["https://img.jd.com/evidence1.jpg"],
                "sku_info": {
                    "sku_id": "10000001",
                    "sku_name": "无线蓝牙耳机",
                    "sku_num": "1",
                },
            },
        },
    }


# ── Fixtures: logistics ─────────────────────────────────────────────────────

@pytest.fixture
def logistics_tracking_payload() -> dict:
    return {
        "jingdong_pop_logistics_trace_responce": {
            "logistics_info": {
                "order_id": "3000000000001",
                "logistics_no": "JD0001234567890",
                "company": "京东物流",
                "status": "已签收",
                "nodes": [
                    {
                        "time": "2024-01-16 08:00:00",
                        "desc": "您的订单已由本人签收",
                        "operator": "快递员张三",
                    },
                    {
                        "time": "2024-01-16 06:30:00",
                        "desc": "您的订单正在派送中",
                        "operator": "快递员张三",
                    },
                    {
                        "time": "2024-01-15 20:00:00",
                        "desc": "您的订单已到达【北京朝阳分拣中心】",
                        "operator": "分拣员",
                    },
                    {
                        "time": "2024-01-15 15:00:00",
                        "desc": "您的订单已出库",
                        "operator": "仓库",
                    },
                ],
            },
        },
    }


# ── Fixtures: reviews ───────────────────────────────────────────────────────

@pytest.fixture
def review_list_payload() -> dict:
    return {
        "jingdong_pop_comment_search_responce": {
            "comment_list": {
                "comment_info": [
                    {
                        "comment_id": "C00000001",
                        "ware_id": "20000001",
                        "content": "音质很好，佩戴舒适，推荐购买！",
                        "score": 5,
                        "create_time": "2024-01-20 12:00:00",
                        "user_name": "j***1",
                        "reply": "感谢您的支持和认可！",
                    },
                    {
                        "comment_id": "C00000002",
                        "ware_id": "20000001",
                        "content": "续航还不错，但是蓝牙偶尔会断连",
                        "score": 3,
                        "create_time": "2024-01-18 09:30:00",
                        "user_name": "j***2",
                        "reply": "",
                    },
                ],
                "total": 2,
            },
        },
    }


@pytest.fixture
def review_detail_payload() -> dict:
    return {
        "jingdong_pop_comment_get_responce": {
            "comment_detail": {
                "comment_id": "C00000001",
                "ware_id": "20000001",
                "ware_name": "无线蓝牙耳机 Pro",
                "content": "音质很好，佩戴舒适，推荐购买！",
                "score": 5,
                "score_detail": {
                    "product_score": 5,
                    "service_score": 5,
                    "delivery_score": 5,
                },
                "create_time": "2024-01-20 12:00:00",
                "user_name": "j***1",
                "user_level": "PLUS会员",
                "images": ["https://img.jd.com/comment1.jpg"],
                "reply": "感谢您的支持和认可！",
                "reply_time": "2024-01-20 14:00:00",
            },
        },
    }


# ── Fixtures: pricing ───────────────────────────────────────────────────────

@pytest.fixture
def price_info_payload() -> dict:
    return {
        "jingdong_pop_price_get_responce": {
            "price_list": {
                "price_info": [
                    {
                        "sku_id": "10000001",
                        "jd_price": "129.00",
                        "promo_price": "99.00",
                        "promo_type": "满减",
                        "promo_label": "满199减30",
                        "promo_start": "2024-01-15 00:00:00",
                        "promo_end": "2024-01-31 23:59:59",
                    },
                    {
                        "sku_id": "10000002",
                        "jd_price": "299.00",
                        "promo_price": "269.00",
                        "promo_type": "直降",
                        "promo_label": "限时直降30元",
                        "promo_start": "2024-01-20 00:00:00",
                        "promo_end": "2024-01-25 23:59:59",
                    },
                ],
            },
        },
    }


# ── Fixtures: inventory ─────────────────────────────────────────────────────

@pytest.fixture
def inventory_payload() -> dict:
    return {
        "jingdong_pop_inventory_get_responce": {
            "inventory_list": {
                "inventory_info": [
                    {
                        "ware_id": "20000001",
                        "ware_name": "无线蓝牙耳机 Pro",
                        "stock_num": "500",
                        "available_stock": "480",
                        "reserved_stock": "20",
                        "ware_status": "2",
                    },
                    {
                        "ware_id": "20000002",
                        "ware_name": "智能手表",
                        "stock_num": "200",
                        "available_stock": "195",
                        "reserved_stock": "5",
                        "ware_status": "2",
                    },
                ],
            },
        },
    }


# ── Fixtures: marketing ─────────────────────────────────────────────────────

@pytest.fixture
def promotion_list_payload() -> dict:
    return {
        "jingdong_pop_promotion_search_responce": {
            "promotion_list": {
                "promotion_info": [
                    {
                        "promotion_id": "P00000001",
                        "promotion_name": "新年大促满减",
                        "type": "满减",
                        "status": "1",
                        "start_time": "2024-01-01 00:00:00",
                        "end_time": "2024-01-31 23:59:59",
                        "description": "满199减30，满399减60",
                    },
                    {
                        "promotion_id": "P00000002",
                        "promotion_name": "限时秒杀",
                        "type": "秒杀",
                        "status": "1",
                        "start_time": "2024-01-20 10:00:00",
                        "end_time": "2024-01-20 12:00:00",
                        "description": "无线蓝牙耳机限时秒杀99元",
                    },
                ],
                "total": 2,
            },
        },
    }


@pytest.fixture
def coupon_list_payload() -> dict:
    return {
        "jingdong_pop_coupon_search_responce": {
            "coupon_list": {
                "coupon_info": [
                    {
                        "coupon_id": "CP00000001",
                        "coupon_name": "新人专享券",
                        "type": "满减券",
                        "status": "1",
                        "discount": "10",
                        "quota": "99",
                        "start_time": "2024-01-01 00:00:00",
                        "end_time": "2024-12-31 23:59:59",
                        "total_count": "10000",
                        "received_count": "3500",
                    },
                    {
                        "coupon_id": "CP00000002",
                        "coupon_name": "年终回馈券",
                        "type": "满减券",
                        "status": "1",
                        "discount": "30",
                        "quota": "199",
                        "start_time": "2024-01-15 00:00:00",
                        "end_time": "2024-02-15 23:59:59",
                        "total_count": "5000",
                        "received_count": "1200",
                    },
                ],
                "total": 2,
            },
        },
    }


# ── Fixtures: categories ────────────────────────────────────────────────────

@pytest.fixture
def category_list_payload() -> dict:
    return {
        "jingdong_pop_category_search_responce": {
            "category_list": {
                "category_info": [
                    {
                        "category_id": "1001",
                        "category_name": "手机通讯",
                        "parent_id": "0",
                        "level": "1",
                        "is_leaf": "0",
                    },
                    {
                        "category_id": "1002",
                        "category_name": "电脑办公",
                        "parent_id": "0",
                        "level": "1",
                        "is_leaf": "0",
                    },
                    {
                        "category_id": "1003",
                        "category_name": "家用电器",
                        "parent_id": "0",
                        "level": "1",
                        "is_leaf": "0",
                    },
                ],
            },
        },
    }


# ── Fixtures: shop score ────────────────────────────────────────────────────

@pytest.fixture
def shop_score_payload() -> dict:
    return {
        "jingdong_pop_shop_score_get_responce": {
            "shop_score": {
                "shop_id": "10000001",
                "shop_name": "XX官方旗舰店",
                "score_describe": "4.92",
                "score_service": "4.88",
                "score_delivery": "4.95",
                "industry_avg_describe": "4.80",
                "industry_avg_service": "4.75",
                "industry_avg_delivery": "4.85",
                "update_time": "2024-01-31 23:59:59",
            },
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_order_list
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_order_list_returns_orders_with_correct_fields(
    mock_call, order_payload
):
    """get_order_list should return a list of orders with expected fields."""
    mock_call.return_value = order_payload

    result_json = await get_order_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
    )
    result = json.loads(result_json)

    assert "jingdong_pop_order_search_responce" in result
    info_result = result["jingdong_pop_order_search_responce"]["searchorderinfo_result"]
    orders = info_result["order_info_list"]["order_info"]

    assert len(orders) == 2
    assert info_result["order_total"] == 2

    for order in orders:
        assert "order_id" in order
        assert "order_state" in order
        assert "order_create_time" in order
        assert "order_payment" in order
        assert "order_total_price" in order
        assert "consignee_info" in order

    # Verify the correct API method was called with correct params
    mock_call.assert_called_once_with(
        "jd.pop.order.search",
        {"start_date": "2024-01-01 00:00:00", "end_date": "2024-01-31 23:59:59", "page": "1", "page_size": "20"},
    )


@pytest.mark.asyncio
async def test_get_order_list_with_status_filter(mock_call, order_payload):
    """get_order_list should include order_status in biz params when provided."""
    mock_call.return_value = order_payload

    await get_order_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
        order_status="FINISHED_L",
    )

    mock_call.assert_called_once()
    _, biz_params = mock_call.call_args[0]
    assert biz_params["order_status"] == "FINISHED_L"


@pytest.mark.asyncio
async def test_get_order_list_without_status_omits_field(mock_call, order_payload):
    """get_order_list should NOT include order_status key when status is empty string."""
    mock_call.return_value = order_payload

    await get_order_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
        order_status="",  # default
    )

    _, biz_params = mock_call.call_args[0]
    assert "order_status" not in biz_params


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_order_detail
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_order_detail_returns_single_order_with_all_fields(
    mock_call, order_detail_payload
):
    """get_order_detail should return a single order with full details."""
    mock_call.return_value = order_detail_payload

    result_json = await get_order_detail(order_id="3000000000001")
    result = json.loads(result_json)

    details = result["jingdong_pop_order_get_responce"]["orderDetailInfo"]

    assert details["order_id"] == "3000000000001"
    assert details["order_state"] == "WAIT_SELLER_STOCK_OUT"
    assert "order_payment" in details
    assert "order_total_price" in details
    assert "order_delivery_price" in details
    assert "consignee_info" in details
    assert "item_info_list" in details
    assert len(details["item_info_list"]) == 1
    assert details["item_info_list"][0]["sku_name"] == "无线蓝牙耳机"

    # Verify correct API method and params
    mock_call.assert_called_once_with(
        "jd.pop.order.get",
        {"order_id": "3000000000001"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_product_list
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_product_list_returns_products_with_stock_price(
    mock_call, product_list_payload
):
    """get_product_list should return products with stock and price information."""
    mock_call.return_value = product_list_payload

    result_json = await get_product_list()
    result = json.loads(result_json)

    wares = result["jingdong_pop_ware_search_responce"]["ware_list"]["ware_info"]

    assert len(wares) == 2

    for ware in wares:
        assert "ware_id" in ware
        assert "ware_name" in ware
        assert "ware_status" in ware
        assert "jd_price" in ware
        assert "stock_num" in ware

    # Verify correct API method was called
    mock_call.assert_called_once_with(
        "jd.pop.ware.search",
        {"page": "1", "page_size": "20"},
    )


@pytest.mark.asyncio
async def test_get_product_list_with_ware_status(mock_call, product_list_payload):
    """get_product_list should pass ware_status when provided."""
    mock_call.return_value = product_list_payload

    await get_product_list(ware_status="2")

    _, biz_params = mock_call.call_args[0]
    assert biz_params["ware_status"] == "2"


@pytest.mark.asyncio
async def test_get_product_list_without_ware_status_omits_field(mock_call, product_list_payload):
    """get_product_list should NOT include ware_status when empty."""
    mock_call.return_value = product_list_payload

    await get_product_list(ware_status="")  # default

    _, biz_params = mock_call.call_args[0]
    assert "ware_status" not in biz_params


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_shop_info
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_shop_info_returns_shop_details(mock_call, shop_info_payload):
    """get_shop_info should return shop details."""
    mock_call.return_value = shop_info_payload

    result_json = await get_shop_info()
    result = json.loads(result_json)

    shop = result["jingdong_pop_shop_get_responce"]["shop_info"]

    assert shop["shop_id"] == "10000001"
    assert shop["shop_name"] == "XX官方旗舰店"
    assert "shop_status" in shop
    assert "shop_score" in shop
    assert "open_time" in shop

    # Verify API method called with NO shop_id (use authenticated shop)
    mock_call.assert_called_once_with("jd.pop.shop.get", {})


@pytest.mark.asyncio
async def test_get_shop_info_with_shop_id(mock_call, shop_info_payload):
    """get_shop_info should include shop_id when provided."""
    mock_call.return_value = shop_info_payload

    await get_shop_info(shop_id="10000002")

    mock_call.assert_called_once_with("jd.pop.shop.get", {"shop_id": "10000002"})


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_after_sale_list
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_after_sale_list_returns_records_with_expected_fields(
    mock_call, after_sale_list_payload
):
    """get_after_sale_list should return after-sale records with correct fields."""
    mock_call.return_value = after_sale_list_payload

    result_json = await get_after_sale_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
    )
    result = json.loads(result_json)

    records = result["jingdong_pop_afs_search_responce"]["after_sale_list"]["after_sale_info"]

    assert len(records) == 2
    assert result["jingdong_pop_afs_search_responce"]["after_sale_list"]["total"] == 2

    for record in records:
        assert "after_sale_id" in record
        assert "order_id" in record
        assert "status" in record
        assert "type" in record
        assert "apply_time" in record
        assert "amount" in record
        assert "reason" in record

    mock_call.assert_called_once_with(
        "jd.pop.afs.search",
        {"start_date": "2024-01-01 00:00:00", "end_date": "2024-01-31 23:59:59", "page": "1", "page_size": "20"},
    )


@pytest.mark.asyncio
async def test_get_after_sale_list_with_status_filter(mock_call, after_sale_list_payload):
    """get_after_sale_list should include status in biz params when provided."""
    mock_call.return_value = after_sale_list_payload

    await get_after_sale_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
        status="COMPLETE",
    )

    mock_call.assert_called_once()
    _, biz_params = mock_call.call_args[0]
    assert biz_params["status"] == "COMPLETE"


@pytest.mark.asyncio
async def test_get_after_sale_list_without_status_omits_field(mock_call, after_sale_list_payload):
    """get_after_sale_list should NOT include status key when status is empty string."""
    mock_call.return_value = after_sale_list_payload

    await get_after_sale_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
        status="",
    )

    _, biz_params = mock_call.call_args[0]
    assert "status" not in biz_params


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_after_sale_detail
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_after_sale_detail_returns_full_record(
    mock_call, after_sale_detail_payload
):
    """get_after_sale_detail should return a single after-sale record with full details."""
    mock_call.return_value = after_sale_detail_payload

    result_json = await get_after_sale_detail(after_sale_id="AS00000001")
    result = json.loads(result_json)

    detail = result["jingdong_pop_afs_get_responce"]["after_sale_detail"]

    assert detail["after_sale_id"] == "AS00000001"
    assert detail["order_id"] == "3000000000001"
    assert detail["status"] == "WAIT_SELLER_AGREE"
    assert "type" in detail
    assert "amount" in detail
    assert "reason" in detail
    assert "description" in detail
    assert "evidence" in detail
    assert "sku_info" in detail

    mock_call.assert_called_once_with(
        "jd.pop.afs.get",
        {"after_sale_id": "AS00000001"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_logistics_tracking
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_logistics_tracking_returns_tracking_nodes(
    mock_call, logistics_tracking_payload
):
    """get_logistics_tracking should return logistics tracking with ordered nodes."""
    mock_call.return_value = logistics_tracking_payload

    result_json = await get_logistics_tracking(order_id="3000000000001")
    result = json.loads(result_json)

    logistics = result["jingdong_pop_logistics_trace_responce"]["logistics_info"]

    assert logistics["order_id"] == "3000000000001"
    assert logistics["logistics_no"] == "JD0001234567890"
    assert logistics["company"] == "京东物流"
    assert "status" in logistics
    assert "nodes" in logistics
    assert len(logistics["nodes"]) == 4
    assert logistics["nodes"][0]["desc"] == "您的订单已由本人签收"

    mock_call.assert_called_once_with(
        "jd.pop.logistics.trace",
        {"order_id": "3000000000001"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_review_list
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_review_list_returns_reviews_with_expected_fields(
    mock_call, review_list_payload
):
    """get_review_list should return reviews with content, score, and user info."""
    mock_call.return_value = review_list_payload

    result_json = await get_review_list(product_id="20000001")
    result = json.loads(result_json)

    comments = result["jingdong_pop_comment_search_responce"]["comment_list"]["comment_info"]

    assert len(comments) == 2
    assert result["jingdong_pop_comment_search_responce"]["comment_list"]["total"] == 2

    for comment in comments:
        assert "comment_id" in comment
        assert "ware_id" in comment
        assert "content" in comment
        assert "score" in comment
        assert "create_time" in comment
        assert "user_name" in comment
        assert "reply" in comment

    mock_call.assert_called_once_with(
        "jd.pop.comment.search",
        {"ware_id": "20000001", "page": "1", "page_size": "20"},
    )


@pytest.mark.asyncio
async def test_get_review_list_with_pagination(mock_call, review_list_payload):
    """get_review_list should pass custom page and page_size."""
    mock_call.return_value = review_list_payload

    await get_review_list(product_id="20000001", page=2, page_size=10)

    _, biz_params = mock_call.call_args[0]
    assert biz_params["ware_id"] == "20000001"
    assert biz_params["page"] == "2"
    assert biz_params["page_size"] == "10"


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_review_detail
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_review_detail_returns_full_comment(
    mock_call, review_detail_payload
):
    """get_review_detail should return a single review with score breakdown."""
    mock_call.return_value = review_detail_payload

    result_json = await get_review_detail(review_id="C00000001")
    result = json.loads(result_json)

    detail = result["jingdong_pop_comment_get_responce"]["comment_detail"]

    assert detail["comment_id"] == "C00000001"
    assert detail["ware_id"] == "20000001"
    assert detail["score"] == 5
    assert "score_detail" in detail
    assert detail["score_detail"]["product_score"] == 5
    assert detail["score_detail"]["service_score"] == 5
    assert detail["score_detail"]["delivery_score"] == 5
    assert "content" in detail
    assert "images" in detail
    assert "reply" in detail

    mock_call.assert_called_once_with(
        "jd.pop.comment.get",
        {"comment_id": "C00000001"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_price_info
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_price_info_returns_prices_with_promotion_overlay(
    mock_call, price_info_payload
):
    """get_price_info should return real-time prices including promotion overlay."""
    mock_call.return_value = price_info_payload

    result_json = await get_price_info(sku_ids="10000001,10000002")
    result = json.loads(result_json)

    prices = result["jingdong_pop_price_get_responce"]["price_list"]["price_info"]

    assert len(prices) == 2

    for price in prices:
        assert "sku_id" in price
        assert "jd_price" in price
        assert "promo_price" in price
        assert "promo_type" in price
        assert "promo_label" in price
        assert "promo_start" in price
        assert "promo_end" in price

    assert prices[0]["sku_id"] == "10000001"
    assert prices[0]["jd_price"] == "129.00"
    assert prices[0]["promo_price"] == "99.00"

    mock_call.assert_called_once_with(
        "jd.pop.price.get",
        {"sku_ids": "10000001,10000002"},
    )


@pytest.mark.asyncio
async def test_get_price_info_single_sku(mock_call, price_info_payload):
    """get_price_info should work with a single SKU."""
    # Trim payload to single result for single-SKU test
    single_result = dict(price_info_payload)
    single_result["jingdong_pop_price_get_responce"]["price_list"]["price_info"] = [
        price_info_payload["jingdong_pop_price_get_responce"]["price_list"]["price_info"][0]
    ]

    mock_call.return_value = single_result

    result_json = await get_price_info(sku_ids="10000001")
    result = json.loads(result_json)

    prices = result["jingdong_pop_price_get_responce"]["price_list"]["price_info"]
    assert len(prices) == 1

    mock_call.assert_called_once_with(
        "jd.pop.price.get",
        {"sku_ids": "10000001"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_inventory
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_inventory_returns_stock_levels(
    mock_call, inventory_payload
):
    """get_inventory should return stock counts and availability for given ware IDs."""
    mock_call.return_value = inventory_payload

    result_json = await get_inventory(ware_ids="20000001,20000002")
    result = json.loads(result_json)

    inventories = result["jingdong_pop_inventory_get_responce"]["inventory_list"]["inventory_info"]

    assert len(inventories) == 2

    for inv in inventories:
        assert "ware_id" in inv
        assert "ware_name" in inv
        assert "stock_num" in inv
        assert "available_stock" in inv
        assert "reserved_stock" in inv
        assert "ware_status" in inv

    assert inventories[0]["ware_id"] == "20000001"
    assert inventories[0]["stock_num"] == "500"
    assert inventories[0]["available_stock"] == "480"

    mock_call.assert_called_once_with(
        "jd.pop.inventory.get",
        {"ware_ids": "20000001,20000002"},
    )


@pytest.mark.asyncio
async def test_get_inventory_single_ware(mock_call, inventory_payload):
    """get_inventory should work with a single ware ID."""
    single_result = dict(inventory_payload)
    single_result["jingdong_pop_inventory_get_responce"]["inventory_list"]["inventory_info"] = [
        inventory_payload["jingdong_pop_inventory_get_responce"]["inventory_list"]["inventory_info"][0]
    ]

    mock_call.return_value = single_result

    result_json = await get_inventory(ware_ids="20000001")
    result = json.loads(result_json)

    inventories = result["jingdong_pop_inventory_get_responce"]["inventory_list"]["inventory_info"]
    assert len(inventories) == 1

    mock_call.assert_called_once_with(
        "jd.pop.inventory.get",
        {"ware_ids": "20000001"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: list_promotions
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_list_promotions_returns_promotions_with_expected_fields(
    mock_call, promotion_list_payload
):
    """list_promotions should return promotion activities with timing and type info."""
    mock_call.return_value = promotion_list_payload

    result_json = await list_promotions()
    result = json.loads(result_json)

    promotions = result["jingdong_pop_promotion_search_responce"]["promotion_list"]["promotion_info"]

    assert len(promotions) == 2

    for promo in promotions:
        assert "promotion_id" in promo
        assert "promotion_name" in promo
        assert "type" in promo
        assert "status" in promo
        assert "start_time" in promo
        assert "end_time" in promo
        assert "description" in promo

    mock_call.assert_called_once_with(
        "jd.pop.promotion.search",
        {"page": "1", "page_size": "20"},
    )


@pytest.mark.asyncio
async def test_list_promotions_with_status_filter(mock_call, promotion_list_payload):
    """list_promotions should include status in biz params when provided."""
    mock_call.return_value = promotion_list_payload

    await list_promotions(status="1")

    _, biz_params = mock_call.call_args[0]
    assert biz_params["status"] == "1"


@pytest.mark.asyncio
async def test_list_promotions_without_status_omits_field(mock_call, promotion_list_payload):
    """list_promotions should NOT include status key when empty."""
    mock_call.return_value = promotion_list_payload

    await list_promotions(status="")

    _, biz_params = mock_call.call_args[0]
    assert "status" not in biz_params


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: list_coupons
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_list_coupons_returns_coupons_with_quota_and_usage(
    mock_call, coupon_list_payload
):
    """list_coupons should return coupon templates with discount and usage stats."""
    mock_call.return_value = coupon_list_payload

    result_json = await list_coupons()
    result = json.loads(result_json)

    coupons = result["jingdong_pop_coupon_search_responce"]["coupon_list"]["coupon_info"]

    assert len(coupons) == 2

    for coupon in coupons:
        assert "coupon_id" in coupon
        assert "coupon_name" in coupon
        assert "type" in coupon
        assert "status" in coupon
        assert "discount" in coupon
        assert "quota" in coupon
        assert "start_time" in coupon
        assert "end_time" in coupon
        assert "total_count" in coupon
        assert "received_count" in coupon

    mock_call.assert_called_once_with(
        "jd.pop.coupon.search",
        {"page": "1", "page_size": "20"},
    )


@pytest.mark.asyncio
async def test_list_coupons_with_status_filter(mock_call, coupon_list_payload):
    """list_coupons should include status in biz params when provided."""
    mock_call.return_value = coupon_list_payload

    await list_coupons(status="2")

    _, biz_params = mock_call.call_args[0]
    assert biz_params["status"] == "2"


@pytest.mark.asyncio
async def test_list_coupons_without_status_omits_field(mock_call, coupon_list_payload):
    """list_coupons should NOT include status key when empty."""
    mock_call.return_value = coupon_list_payload

    await list_coupons(status="")

    _, biz_params = mock_call.call_args[0]
    assert "status" not in biz_params


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: list_categories
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_list_categories_returns_top_level_by_default(
    mock_call, category_list_payload
):
    """list_categories should list top-level categories when no parent_id given."""
    mock_call.return_value = category_list_payload

    result_json = await list_categories()
    result = json.loads(result_json)

    categories = result["jingdong_pop_category_search_responce"]["category_list"]["category_info"]

    assert len(categories) == 3

    for cat in categories:
        assert "category_id" in cat
        assert "category_name" in cat
        assert "parent_id" in cat
        assert "level" in cat
        assert "is_leaf" in cat
        assert cat["parent_id"] == "0"

    mock_call.assert_called_once_with(
        "jd.pop.category.search",
        {"parent_id": "0"},
    )


@pytest.mark.asyncio
async def test_list_categories_with_parent_id(mock_call, category_list_payload):
    """list_categories should pass parent_id to query sub-categories."""
    mock_call.return_value = category_list_payload

    await list_categories(parent_id="1001")

    mock_call.assert_called_once_with(
        "jd.pop.category.search",
        {"parent_id": "1001"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: get_shop_score
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_shop_score_returns_dsr_ratings(
    mock_call, shop_score_payload
):
    """get_shop_score should return DSR scores with industry averages."""
    mock_call.return_value = shop_score_payload

    result_json = await get_shop_score()
    result = json.loads(result_json)

    score = result["jingdong_pop_shop_score_get_responce"]["shop_score"]

    assert score["shop_id"] == "10000001"
    assert "shop_name" in score
    assert score["score_describe"] == "4.92"
    assert score["score_service"] == "4.88"
    assert score["score_delivery"] == "4.95"
    assert "industry_avg_describe" in score
    assert "industry_avg_service" in score
    assert "industry_avg_delivery" in score
    assert "update_time" in score

    mock_call.assert_called_once_with("jd.pop.shop.score.get", {})


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: Error handling (existing + new tools)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_missing_order_id_returned_in_result(mock_call):
    """When order_id is present but API returns an error response, it propagates as JSON."""
    # This test verifies error information flows through — the server serializes
    # whatever _call returns (including error responses) as JSON.
    error_response = {
        "error_response": {
            "code": 1001,
            "msg": "order_id not found",
        },
    }
    mock_call.return_value = error_response

    result_json = await get_order_detail(order_id="9999999999999")
    result = json.loads(result_json)

    assert "error_response" in result
    assert result["error_response"]["code"] == 1001
    assert "order_id not found" in result["error_response"]["msg"]


@pytest.mark.asyncio
async def test_api_error_handling_commerce_api_error(mock_call):
    """When _call raises CommerceAPIError (via _request), it should propagate."""
    mock_call.side_effect = CommerceAPIError(code=4003, msg="Invalid access token")

    with pytest.raises(CommerceAPIError) as exc_info:
        await get_order_list(
            start_time="2024-01-01 00:00:00",
            end_time="2024-01-31 23:59:59",
        )

    assert exc_info.value.code == 4003
    assert "Invalid access token" in exc_info.value.msg


@pytest.mark.asyncio
async def test_api_error_handling_timeout(mock_call):
    """When _call raises a generic exception (e.g. timeout), it should propagate."""
    mock_call.side_effect = TimeoutError("Connection timed out")

    with pytest.raises(TimeoutError, match="Connection timed out"):
        await get_product_list()


@pytest.mark.asyncio
async def test_after_sale_api_error_propagates(mock_call):
    """CommerceAPIError from after-sale tools should propagate."""
    mock_call.side_effect = CommerceAPIError(code=5001, msg="After-sale record not found")

    with pytest.raises(CommerceAPIError) as exc_info:
        await get_after_sale_detail(after_sale_id="AS99999999")

    assert exc_info.value.code == 5001
    assert "After-sale record not found" in exc_info.value.msg


@pytest.mark.asyncio
async def test_logistics_error_propagates(mock_call):
    """CommerceAPIError from logistics tools should propagate."""
    mock_call.side_effect = CommerceAPIError(code=6001, msg="Logistics info not found")

    with pytest.raises(CommerceAPIError) as exc_info:
        await get_logistics_tracking(order_id="9999999999999")

    assert exc_info.value.code == 6001
    assert "Logistics info not found" in exc_info.value.msg


@pytest.mark.asyncio
async def test_price_info_error_propagates(mock_call):
    """CommerceAPIError from pricing tools should propagate."""
    mock_call.side_effect = CommerceAPIError(code=7001, msg="SKU not found")

    with pytest.raises(CommerceAPIError) as exc_info:
        await get_price_info(sku_ids="99999999")

    assert exc_info.value.code == 7001
    assert "SKU not found" in exc_info.value.msg


@pytest.mark.asyncio
async def test_new_tool_timeout_propagates(mock_call):
    """TimeoutError from new tools should propagate."""
    mock_call.side_effect = TimeoutError("Connection timed out")

    with pytest.raises(TimeoutError, match="Connection timed out"):
        await list_promotions()


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: Pagination edge cases (existing)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_pagination_default_page_and_size(mock_call, order_payload):
    """Default page=1, page_size=20 should be sent as strings."""
    mock_call.return_value = order_payload

    await get_order_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
    )

    _, biz_params = mock_call.call_args[0]
    assert biz_params["page"] == "1"
    assert biz_params["page_size"] == "20"


@pytest.mark.asyncio
async def test_pagination_custom_page(mock_call, order_payload):
    """Custom page and page_size values should be passed as strings."""
    mock_call.return_value = order_payload

    await get_order_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
        page=3,
        page_size=50,
    )

    _, biz_params = mock_call.call_args[0]
    assert biz_params["page"] == "3"
    assert biz_params["page_size"] == "50"


@pytest.mark.asyncio
async def test_pagination_max_page_size(mock_call, order_payload):
    """page_size of 100 (the documented max) should work."""
    mock_call.return_value = order_payload

    await get_order_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
        page=1,
        page_size=100,
    )

    _, biz_params = mock_call.call_args[0]
    assert biz_params["page_size"] == "100"


@pytest.mark.asyncio
async def test_pagination_product_list_defaults(mock_call, product_list_payload):
    """Product list pagination defaults should match order list behavior."""
    mock_call.return_value = product_list_payload

    await get_product_list()

    _, biz_params = mock_call.call_args[0]
    assert biz_params["page"] == "1"
    assert biz_params["page_size"] == "20"


@pytest.mark.asyncio
async def test_pagination_empty_result_set(mock_call):
    """An empty order list should be handled gracefully."""
    empty_response = {
        "jingdong_pop_order_search_responce": {
            "searchorderinfo_result": {
                "order_info_list": [],
                "order_total": 0,
            },
        },
    }
    mock_call.return_value = empty_response

    result_json = await get_order_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-01 00:00:01",  # very narrow window
    )
    result = json.loads(result_json)

    info = result["jingdong_pop_order_search_responce"]["searchorderinfo_result"]
    assert info["order_total"] == 0
    assert info["order_info_list"] == []


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: JSON output format (existing + new)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_output_is_valid_json_string(mock_call, order_payload):
    """All tool return values should be valid JSON strings."""
    mock_call.return_value = order_payload

    result = await get_order_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
    )

    assert isinstance(result, str)
    # Must not raise
    parsed = json.loads(result)
    assert isinstance(parsed, dict)


@pytest.mark.asyncio
async def test_new_tools_return_valid_json_strings(mock_call, after_sale_list_payload):
    """New tools should also return valid JSON strings."""
    mock_call.return_value = after_sale_list_payload

    result = await get_after_sale_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
    )

    assert isinstance(result, str)
    parsed = json.loads(result)
    assert isinstance(parsed, dict)


@pytest.mark.asyncio
async def test_call_passthrough_with_minimal_params(mock_call):
    """Verify _call receives the expected API method name and biz params shape."""
    mock_call.return_value = _mock_response({"ok": True})

    await get_order_detail(order_id="12345")

    api_method, biz_params = mock_call.call_args[0]
    assert api_method == "jd.pop.order.get"
    assert biz_params == {"order_id": "12345"}


@pytest.mark.asyncio
async def test_new_tool_call_passthrough(mock_call):
    """Verify _call receives correct API method and params for new tools."""
    mock_call.return_value = _mock_response({"ok": True})

    await get_price_info(sku_ids="S1,S2,S3")

    api_method, biz_params = mock_call.call_args[0]
    assert api_method == "jd.pop.price.get"
    assert biz_params == {"sku_ids": "S1,S2,S3"}
