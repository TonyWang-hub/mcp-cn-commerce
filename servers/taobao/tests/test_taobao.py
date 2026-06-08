"""Tests for Taobao MCP server tools."""

from __future__ import annotations

import json

# Must patch env BEFORE importing the server module (it reads env at import time)
import os
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("TAOBAO_APP_KEY", "test_key")
os.environ.setdefault("TAOBAO_APP_SECRET", "test_secret")
os.environ.setdefault("TAOBAO_ACCESS_TOKEN", "test_token")

from mcp_taobao.server import (
    get_increment_orders,
    get_logistics_tracking,
    get_order_detail,
    get_order_list,
    get_product_detail,
    get_product_list,
    get_refund_detail,
    get_refund_list,
    get_review_list,
    get_seller_info,
    get_shop_info,
    list_categories,
    list_promotions,
    taobao,
)

from shared.cn_commerce_base import CommerceAPIError

# ── Helpers ─────────────────────────────────────────────────────────────────────


def _mock_response(data: dict) -> dict:
    """Shallow wrapper for a successful Taobao API response."""
    return data


# ── Fixtures ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_request():
    """Patch taobao._request with an AsyncMock, reset after each test."""
    with patch.object(taobao, "_request", new_callable=AsyncMock) as mock:
        yield mock


# ── Fixtures: Orders ────────────────────────────────────────────────────────────


@pytest.fixture
def order_list_payload() -> dict:
    return {
        "taobao_trades_sold_get_response": {
            "total_results": 2,
            "trades": {
                "trade": [
                    {
                        "tid": "123456789012345678",
                        "status": "WAIT_SELLER_SEND_GOODS",
                        "created": "2024-01-15 10:30:00",
                        "payment": "99.00",
                        "receiver_name": "张三",
                        "receiver_mobile": "13800138000",
                        "receiver_address": "北京市朝阳区XX路1号",
                        "num_iid": "10000001",
                        "title": "无线蓝牙耳机",
                        "num": "1",
                    },
                    {
                        "tid": "876543210987654321",
                        "status": "TRADE_FINISHED",
                        "created": "2024-01-16 14:20:00",
                        "payment": "199.00",
                        "receiver_name": "李四",
                        "receiver_mobile": "13900139000",
                        "receiver_address": "上海市浦东新区YY路2号",
                        "num_iid": "10000002",
                        "title": "智能手表",
                        "num": "1",
                    },
                ],
            },
        },
    }


@pytest.fixture
def order_detail_payload() -> dict:
    return {
        "taobao_trade_fullinfo_get_response": {
            "trade": {
                "tid": "123456789012345678",
                "status": "WAIT_SELLER_SEND_GOODS",
                "created": "2024-01-15 10:30:00",
                "payment": "99.00",
                "post_fee": "0.00",
                "receiver_name": "张三",
                "receiver_mobile": "13800138000",
                "receiver_address": "北京市朝阳区XX路1号",
                "orders": {
                    "order": [
                        {
                            "oid": "1000000100001",
                            "num_iid": "10000001",
                            "title": "无线蓝牙耳机",
                            "num": "1",
                            "price": "99.00",
                            "payment": "99.00",
                        },
                    ],
                },
            },
        },
    }


@pytest.fixture
def increment_orders_payload() -> dict:
    return {
        "taobao_trades_sold_increment_get_response": {
            "total_results": 1,
            "trades": {
                "trade": [
                    {
                        "tid": "123456789012345678",
                        "status": "WAIT_SELLER_SEND_GOODS",
                        "modified": "2024-01-17 08:00:00",
                        "created": "2024-01-15 10:30:00",
                        "payment": "99.00",
                        "num_iid": "10000001",
                        "title": "无线蓝牙耳机",
                    },
                ],
            },
        },
    }


# ── Fixtures: Products ──────────────────────────────────────────────────────────


@pytest.fixture
def product_list_payload() -> dict:
    return {
        "taobao_items_onsale_get_response": {
            "total_results": 2,
            "items": {
                "item": [
                    {
                        "num_iid": "10000001",
                        "title": "无线蓝牙耳机 Pro",
                        "price": "129.00",
                        "num": "500",
                        "status": "onsale",
                        "created": "2024-01-01 00:00:00",
                    },
                    {
                        "num_iid": "10000002",
                        "title": "智能手表",
                        "price": "299.00",
                        "num": "200",
                        "status": "onsale",
                        "created": "2024-01-02 00:00:00",
                    },
                ],
            },
        },
    }


@pytest.fixture
def product_detail_payload() -> dict:
    return {
        "taobao_item_get_response": {
            "item": {
                "num_iid": "10000001",
                "title": "无线蓝牙耳机 Pro",
                "price": "129.00",
                "nick": "seller_nick_001",
                "desc": "高品质无线蓝牙耳机，续航长达20小时",
                "cid": "50011972",
                "props_name": "颜色:白色;版本:Pro版",
                "sku": {
                    "sku": [
                        {
                            "sku_id": "10000001001",
                            "properties": "颜色:白色",
                            "price": "129.00",
                            "quantity": "300",
                        },
                        {
                            "sku_id": "10000001002",
                            "properties": "颜色:黑色",
                            "price": "129.00",
                            "quantity": "200",
                        },
                    ],
                },
            },
        },
    }


# ── Fixtures: After-Sale ───────────────────────────────────────────────────────


@pytest.fixture
def refund_list_payload() -> dict:
    return {
        "taobao_refunds_receive_get_response": {
            "total_results": 2,
            "refunds": {
                "refund": [
                    {
                        "refund_id": "RF12345678901",
                        "tid": "123456789012345678",
                        "oid": "1000000100001",
                        "status": "WAIT_SELLER_AGREE",
                        "refund_phase": "onsale",
                        "created": "2024-01-20 10:00:00",
                        "modified": "2024-01-20 10:00:00",
                        "order_status": "WAIT_SELLER_SEND_GOODS",
                        "reason": "商品质量问题",
                        "refund_fee": "99.00",
                    },
                    {
                        "refund_id": "RF12345678902",
                        "tid": "876543210987654321",
                        "oid": "1000000200001",
                        "status": "SUCCESS",
                        "refund_phase": "onsale",
                        "created": "2024-01-25 15:30:00",
                        "modified": "2024-01-26 10:00:00",
                        "order_status": "TRADE_FINISHED",
                        "reason": "未收到货",
                        "refund_fee": "199.00",
                    },
                ],
            },
        },
    }


@pytest.fixture
def refund_detail_payload() -> dict:
    return {
        "taobao_refund_get_response": {
            "refund": {
                "refund_id": "RF12345678901",
                "tid": "123456789012345678",
                "oid": "1000000100001",
                "status": "WAIT_SELLER_AGREE",
                "reason": "商品质量问题",
                "desc": "收到商品后发现有划痕，要求退货退款",
                "refund_fee": "99.00",
                "created": "2024-01-20 10:00:00",
                "modified": "2024-01-20 10:00:00",
                "num_iid": "10000001",
                "title": "无线蓝牙耳机 Pro",
                "num": "1",
                "has_good_return": True,
                "refund_version": "1",
                "seller_nick": "seller_nick_001",
            },
        },
    }


# ── Fixtures: Logistics ─────────────────────────────────────────────────────────


@pytest.fixture
def logistics_tracking_payload() -> dict:
    return {
        "taobao_logistics_trace_search_response": {
            "total_results": 1,
            "trace_list": {
                "transit_step_info": [
                    {
                        "status_time": "2024-01-16 08:00:00",
                        "status_desc": "您的快件已由本人签收",
                        "action": "签收",
                    },
                    {
                        "status_time": "2024-01-16 06:30:00",
                        "status_desc": "您的快件正在派送中",
                        "action": "派送",
                    },
                    {
                        "status_time": "2024-01-15 20:00:00",
                        "status_desc": "您的快件已到达【北京朝阳分拣中心】",
                        "action": "到达",
                    },
                    {
                        "status_time": "2024-01-15 15:00:00",
                        "status_desc": "您的快件已发出",
                        "action": "发出",
                    },
                ],
            },
            "out_sid": "SF1234567890",
            "company_name": "顺丰速运",
        },
    }


# ── Fixtures: Reviews ───────────────────────────────────────────────────────────


@pytest.fixture
def review_list_payload() -> dict:
    return {
        "taobao_traderates_get_response": {
            "total_results": 2,
            "trade_rates": {
                "trade_rate": [
                    {
                        "tid": "876543210987654321",
                        "oid": "1000000200001",
                        "nick": "j***1",
                        "result": "good",
                        "role": "buyer",
                        "rated_nick": "seller_nick_001",
                        "item_title": "无线蓝牙耳机 Pro",
                        "item_price": "129.00",
                        "content": "音质很好，佩戴舒适，推荐购买！",
                        "reply": "感谢您的支持和认可！",
                        "created": "2024-01-20 12:00:00",
                    },
                    {
                        "tid": "123456789012345679",
                        "oid": "1000000100002",
                        "nick": "j***2",
                        "result": "neutral",
                        "role": "buyer",
                        "rated_nick": "seller_nick_001",
                        "item_title": "无线蓝牙耳机 Pro",
                        "item_price": "129.00",
                        "content": "续航还不错，但是蓝牙偶尔会断连",
                        "reply": "",
                        "created": "2024-01-18 09:30:00",
                    },
                ],
            },
        },
    }


# ── Fixtures: Shop ──────────────────────────────────────────────────────────────


@pytest.fixture
def shop_info_payload() -> dict:
    return {
        "taobao_shop_get_response": {
            "shop": {
                "sid": "12345678",
                "cid": "50011972",
                "nick": "seller_nick_001",
                "title": "XX官方旗舰店",
                "desc": "专注高品质电子产品",
                "bulletin": "春节不打烊，满200包邮",
                "pic_path": "https://img.alicdn.com/shop_banner_001.jpg",
                "shop_score": {
                    "item_score": "4.9",
                    "service_score": "4.9",
                    "delivery_score": "4.9",
                },
            },
        },
    }


@pytest.fixture
def seller_info_payload() -> dict:
    return {
        "taobao_user_seller_get_response": {
            "user": {
                "user_id": "123456789",
                "nick": "seller_nick_001",
                "sex": "m",
                "seller_credit": {
                    "level": 15,
                    "score": 8500,
                    "total_num": 5000,
                    "good_num": 4950,
                },
                "has_shop": True,
                "type": "C",
                "created": "2018-01-01 00:00:00",
            },
        },
    }


# ── Fixtures: Marketing ─────────────────────────────────────────────────────────


@pytest.fixture
def promotion_list_payload() -> dict:
    return {
        "taobao_promotionmisc_activity_range_list_get_response": {
            "total_results": 2,
            "promotions": {
                "promotion": [
                    {
                        "activity_id": "ACT0000001",
                        "activity_name": "新年大促满减",
                        "activity_type": "满减",
                        "status": "1",
                        "start_time": "2024-01-01 00:00:00",
                        "end_time": "2024-01-31 23:59:59",
                        "description": "满199减30，满399减60",
                    },
                    {
                        "activity_id": "ACT0000002",
                        "activity_name": "限时秒杀",
                        "activity_type": "秒杀",
                        "status": "1",
                        "start_time": "2024-01-20 10:00:00",
                        "end_time": "2024-01-20 12:00:00",
                        "description": "无线蓝牙耳机限时秒杀99元",
                    },
                ],
            },
        },
    }


# ── Fixtures: Categories ────────────────────────────────────────────────────────


@pytest.fixture
def category_list_payload() -> dict:
    return {
        "taobao_itemcats_get_response": {
            "item_cats": {
                "item_cat": [
                    {
                        "cid": "50011972",
                        "name": "手机通讯",
                        "parent_cid": "0",
                        "status": "normal",
                        "sort_order": "1",
                        "is_parent": True,
                    },
                    {
                        "cid": "50011973",
                        "name": "电脑办公",
                        "parent_cid": "0",
                        "status": "normal",
                        "sort_order": "2",
                        "is_parent": True,
                    },
                    {
                        "cid": "50011974",
                        "name": "家用电器",
                        "parent_cid": "0",
                        "status": "normal",
                        "sort_order": "3",
                        "is_parent": True,
                    },
                ],
            },
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════════
# Tests: get_order_list
# ═══════════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_order_list_returns_orders_with_correct_fields(mock_request, order_list_payload):
    """get_order_list should return a list of orders with expected fields."""
    mock_request.return_value = order_list_payload

    result_json = await get_order_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
    )
    result = json.loads(result_json)

    assert "taobao_trades_sold_get_response" in result
    response = result["taobao_trades_sold_get_response"]
    assert response["total_results"] == 2
    trades = response["trades"]["trade"]
    assert len(trades) == 2

    for trade in trades:
        assert "tid" in trade
        assert "status" in trade
        assert "created" in trade
        assert "payment" in trade
        assert "receiver_name" in trade
        assert "num_iid" in trade
        assert "title" in trade

    # Verify _request was called with correct params (including system params)
    _, kwargs = mock_request.call_args
    params = kwargs["params"]
    assert params["method"] == "taobao.trades.sold.get"
    assert params["start_created"] == "2024-01-01 00:00:00"
    assert params["end_created"] == "2024-01-31 23:59:59"
    assert params["page_no"] == "1"
    assert params["page_size"] == "20"


@pytest.mark.asyncio
async def test_get_order_list_with_status_filter(mock_request, order_list_payload):
    """get_order_list should include status in params when provided."""
    mock_request.return_value = order_list_payload

    await get_order_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
        status="TRADE_FINISHED",
    )

    _, kwargs = mock_request.call_args
    params = kwargs["params"]
    assert params["status"] == "TRADE_FINISHED"
    assert params["method"] == "taobao.trades.sold.get"


@pytest.mark.asyncio
async def test_get_order_list_without_status_omits_field(mock_request, order_list_payload):
    """get_order_list should NOT include status key when status is empty string."""
    mock_request.return_value = order_list_payload

    await get_order_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
        status="",
    )

    _, kwargs = mock_request.call_args
    params = kwargs["params"]
    assert "status" not in params


# ═══════════════════════════════════════════════════════════════════════════════════
# Tests: get_order_detail
# ═══════════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_order_detail_returns_single_order_with_all_fields(mock_request, order_detail_payload):
    """get_order_detail should return a single order with full details."""
    mock_request.return_value = order_detail_payload

    result_json = await get_order_detail(tid="123456789012345678")
    result = json.loads(result_json)

    trade = result["taobao_trade_fullinfo_get_response"]["trade"]
    assert trade["tid"] == "123456789012345678"
    assert trade["status"] == "WAIT_SELLER_SEND_GOODS"
    assert trade["payment"] == "99.00"
    assert trade["receiver_name"] == "张三"
    assert "post_fee" in trade
    assert "orders" in trade
    assert len(trade["orders"]["order"]) == 1

    order_item = trade["orders"]["order"][0]
    assert order_item["title"] == "无线蓝牙耳机"
    assert order_item["price"] == "99.00"

    _, kwargs = mock_request.call_args
    params = kwargs["params"]
    assert params["method"] == "taobao.trade.fullinfo.get"
    assert params["tid"] == "123456789012345678"


# ═══════════════════════════════════════════════════════════════════════════════════
# Tests: get_increment_orders
# ═══════════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_increment_orders_returns_modified_orders(mock_request, increment_orders_payload):
    """get_increment_orders should return orders modified within the time range."""
    mock_request.return_value = increment_orders_payload

    result_json = await get_increment_orders(
        start_time="2024-01-17 00:00:00",
        end_time="2024-01-17 23:59:59",
    )
    result = json.loads(result_json)

    response = result["taobao_trades_sold_increment_get_response"]
    assert response["total_results"] == 1
    trades = response["trades"]["trade"]
    assert len(trades) == 1
    assert trades[0]["tid"] == "123456789012345678"
    assert trades[0]["status"] == "WAIT_SELLER_SEND_GOODS"
    assert "modified" in trades[0]

    _, kwargs = mock_request.call_args
    params = kwargs["params"]
    assert params["method"] == "taobao.trades.sold.increment.get"
    assert params["start_modified"] == "2024-01-17 00:00:00"
    assert params["end_modified"] == "2024-01-17 23:59:59"
    assert params["page_no"] == "1"
    assert params["page_size"] == "20"


# ═══════════════════════════════════════════════════════════════════════════════════
# Tests: get_product_list
# ═══════════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_product_list_returns_products_with_stock_price(mock_request, product_list_payload):
    """get_product_list should return on-sale products with stock and price info."""
    mock_request.return_value = product_list_payload

    result_json = await get_product_list()
    result = json.loads(result_json)

    items = result["taobao_items_onsale_get_response"]["items"]["item"]
    assert len(items) == 2

    for item in items:
        assert "num_iid" in item
        assert "title" in item
        assert "price" in item
        assert "num" in item
        assert "status" in item

    _, kwargs = mock_request.call_args
    params = kwargs["params"]
    assert params["method"] == "taobao.items.onsale.get"
    assert params["page_no"] == "1"
    assert params["page_size"] == "20"


@pytest.mark.asyncio
async def test_get_product_list_with_status(mock_request, product_list_payload):
    """get_product_list should pass status param when provided."""
    mock_request.return_value = product_list_payload

    await get_product_list(status="onsale")

    _, kwargs = mock_request.call_args
    params = kwargs["params"]
    assert params["status"] == "onsale"


@pytest.mark.asyncio
async def test_get_product_list_without_status_omits_field(mock_request, product_list_payload):
    """get_product_list should NOT include status when empty."""
    mock_request.return_value = product_list_payload

    await get_product_list(status="")

    _, kwargs = mock_request.call_args
    params = kwargs["params"]
    assert "status" not in params


# ═══════════════════════════════════════════════════════════════════════════════════
# Tests: get_product_detail
# ═══════════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_product_detail_returns_full_item_with_skus(mock_request, product_detail_payload):
    """get_product_detail should return a single product with SKU variants."""
    mock_request.return_value = product_detail_payload

    result_json = await get_product_detail(num_iid="10000001")
    result = json.loads(result_json)

    item = result["taobao_item_get_response"]["item"]
    assert item["num_iid"] == "10000001"
    assert item["title"] == "无线蓝牙耳机 Pro"
    assert item["nick"] == "seller_nick_001"
    assert "price" in item
    assert "desc" in item
    assert "sku" in item
    assert len(item["sku"]["sku"]) == 2

    sku1 = item["sku"]["sku"][0]
    assert sku1["sku_id"] == "10000001001"
    assert sku1["properties"] == "颜色:白色"
    assert "price" in sku1
    assert "quantity" in sku1

    _, kwargs = mock_request.call_args
    params = kwargs["params"]
    assert params["method"] == "taobao.item.get"
    assert params["num_iid"] == "10000001"


# ═══════════════════════════════════════════════════════════════════════════════════
# Tests: get_refund_list
# ═══════════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_refund_list_returns_refunds_with_expected_fields(mock_request, refund_list_payload):
    """get_refund_list should return refund records with correct fields."""
    mock_request.return_value = refund_list_payload

    result_json = await get_refund_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
    )
    result = json.loads(result_json)

    response = result["taobao_refunds_receive_get_response"]
    assert response["total_results"] == 2
    refunds = response["refunds"]["refund"]
    assert len(refunds) == 2

    for refund in refunds:
        assert "refund_id" in refund
        assert "tid" in refund
        assert "status" in refund
        assert "reason" in refund
        assert "refund_fee" in refund
        assert "created" in refund

    _, kwargs = mock_request.call_args
    params = kwargs["params"]
    assert params["method"] == "taobao.refunds.receive.get"
    assert params["start_modified"] == "2024-01-01 00:00:00"
    assert params["end_modified"] == "2024-01-31 23:59:59"
    assert params["page_no"] == "1"
    assert params["page_size"] == "20"


# ═══════════════════════════════════════════════════════════════════════════════════
# Tests: get_refund_detail
# ═══════════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_refund_detail_returns_full_record(mock_request, refund_detail_payload):
    """get_refund_detail should return a single refund record with full details."""
    mock_request.return_value = refund_detail_payload

    result_json = await get_refund_detail(refund_id="RF12345678901")
    result = json.loads(result_json)

    refund = result["taobao_refund_get_response"]["refund"]
    assert refund["refund_id"] == "RF12345678901"
    assert refund["tid"] == "123456789012345678"
    assert refund["status"] == "WAIT_SELLER_AGREE"
    assert refund["reason"] == "商品质量问题"
    assert refund["desc"] == "收到商品后发现有划痕，要求退货退款"
    assert refund["refund_fee"] == "99.00"
    assert "has_good_return" in refund
    assert "num_iid" in refund

    _, kwargs = mock_request.call_args
    params = kwargs["params"]
    assert params["method"] == "taobao.refund.get"
    assert params["refund_id"] == "RF12345678901"


# ═══════════════════════════════════════════════════════════════════════════════════
# Tests: get_logistics_tracking
# ═══════════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_logistics_tracking_returns_tracking_nodes(mock_request, logistics_tracking_payload):
    """get_logistics_tracking should return logistics tracking with ordered steps."""
    mock_request.return_value = logistics_tracking_payload

    result_json = await get_logistics_tracking(tid="123456789012345678")
    result = json.loads(result_json)

    response = result["taobao_logistics_trace_search_response"]
    assert response["out_sid"] == "SF1234567890"
    assert response["company_name"] == "顺丰速运"
    assert "trace_list" in response
    assert "transit_step_info" in response["trace_list"]
    steps = response["trace_list"]["transit_step_info"]
    assert len(steps) == 4
    assert steps[0]["status_desc"] == "您的快件已由本人签收"
    assert steps[0]["action"] == "签收"

    _, kwargs = mock_request.call_args
    params = kwargs["params"]
    assert params["method"] == "taobao.logistics.trace.search"
    assert params["tid"] == "123456789012345678"


# ═══════════════════════════════════════════════════════════════════════════════════
# Tests: get_review_list
# ═══════════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_review_list_returns_reviews_with_expected_fields(mock_request, review_list_payload):
    """get_review_list should return reviews with content, result, and user info."""
    mock_request.return_value = review_list_payload

    result_json = await get_review_list(num_iid="10000001")
    result = json.loads(result_json)

    response = result["taobao_traderates_get_response"]
    assert response["total_results"] == 2
    rates = response["trade_rates"]["trade_rate"]
    assert len(rates) == 2

    for rate in rates:
        assert "tid" in rate
        assert "nick" in rate
        assert "result" in rate
        assert "content" in rate
        assert "item_title" in rate
        assert "created" in rate

    assert rates[0]["result"] == "good"
    assert rates[0]["nick"] == "j***1"

    _, kwargs = mock_request.call_args
    params = kwargs["params"]
    assert params["method"] == "taobao.traderates.get"
    assert params["num_iid"] == "10000001"
    assert params["page_no"] == "1"
    assert params["page_size"] == "20"


# ═══════════════════════════════════════════════════════════════════════════════════
# Tests: get_shop_info
# ═══════════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_shop_info_returns_shop_details(mock_request, shop_info_payload):
    """get_shop_info should return shop details with scores."""
    mock_request.return_value = shop_info_payload

    result_json = await get_shop_info()
    result = json.loads(result_json)

    shop = result["taobao_shop_get_response"]["shop"]
    assert shop["sid"] == "12345678"
    assert shop["nick"] == "seller_nick_001"
    assert shop["title"] == "XX官方旗舰店"
    assert "desc" in shop
    assert "shop_score" in shop
    assert shop["shop_score"]["item_score"] == "4.9"
    assert shop["shop_score"]["service_score"] == "4.9"
    assert shop["shop_score"]["delivery_score"] == "4.9"

    _, kwargs = mock_request.call_args
    params = kwargs["params"]
    assert params["method"] == "taobao.shop.get"


@pytest.mark.asyncio
async def test_get_shop_info_with_nick(mock_request, shop_info_payload):
    """get_shop_info should include nick in params when provided."""
    mock_request.return_value = shop_info_payload

    await get_shop_info(nick="other_nick")

    _, kwargs = mock_request.call_args
    params = kwargs["params"]
    assert params["nick"] == "other_nick"
    assert params["method"] == "taobao.shop.get"


# ═══════════════════════════════════════════════════════════════════════════════════
# Tests: get_seller_info
# ═══════════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_seller_info_returns_seller_profile(mock_request, seller_info_payload):
    """get_seller_info should return authenticated seller profile with credit info."""
    mock_request.return_value = seller_info_payload

    result_json = await get_seller_info()
    result = json.loads(result_json)

    user = result["taobao_user_seller_get_response"]["user"]
    assert user["user_id"] == "123456789"
    assert user["nick"] == "seller_nick_001"
    assert user["sex"] == "m"
    assert user["has_shop"] is True
    assert "seller_credit" in user
    assert user["seller_credit"]["level"] == 15
    assert user["seller_credit"]["score"] == 8500
    assert "good_num" in user["seller_credit"]

    _, kwargs = mock_request.call_args
    params = kwargs["params"]
    assert params["method"] == "taobao.user.seller.get"


# ═══════════════════════════════════════════════════════════════════════════════════
# Tests: list_promotions
# ═══════════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_list_promotions_returns_promotions_with_timing_info(mock_request, promotion_list_payload):
    """list_promotions should return promotion activities with timing and type info."""
    mock_request.return_value = promotion_list_payload

    result_json = await list_promotions()
    result = json.loads(result_json)

    response = result["taobao_promotionmisc_activity_range_list_get_response"]
    assert response["total_results"] == 2
    promotions = response["promotions"]["promotion"]
    assert len(promotions) == 2

    for promo in promotions:
        assert "activity_id" in promo
        assert "activity_name" in promo
        assert "activity_type" in promo
        assert "status" in promo
        assert "start_time" in promo
        assert "end_time" in promo

    _, kwargs = mock_request.call_args
    params = kwargs["params"]
    assert params["method"] == "taobao.promotionmisc.activity.range.list.get"
    assert params["page_no"] == "1"
    assert params["page_size"] == "20"


@pytest.mark.asyncio
async def test_list_promotions_with_status_filter(mock_request, promotion_list_payload):
    """list_promotions should include status in params when provided."""
    mock_request.return_value = promotion_list_payload

    await list_promotions(status="1")

    _, kwargs = mock_request.call_args
    params = kwargs["params"]
    assert params["status"] == "1"


# ═══════════════════════════════════════════════════════════════════════════════════
# Tests: list_categories
# ═══════════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_list_categories_returns_top_level_by_default(mock_request, category_list_payload):
    """list_categories should list top-level categories when no parent_cid given."""
    mock_request.return_value = category_list_payload

    result_json = await list_categories()
    result = json.loads(result_json)

    cats = result["taobao_itemcats_get_response"]["item_cats"]["item_cat"]
    assert len(cats) == 3

    for cat in cats:
        assert "cid" in cat
        assert "name" in cat
        assert "parent_cid" in cat
        assert cat["parent_cid"] == "0"
        assert "is_parent" in cat

    _, kwargs = mock_request.call_args
    params = kwargs["params"]
    assert params["method"] == "taobao.itemcats.get"
    assert params["parent_cid"] == "0"


@pytest.mark.asyncio
async def test_list_categories_with_parent_cid(mock_request, category_list_payload):
    """list_categories should pass parent_cid to query sub-categories."""
    mock_request.return_value = category_list_payload

    await list_categories(parent_cid="50011972")

    _, kwargs = mock_request.call_args
    params = kwargs["params"]
    assert params["parent_cid"] == "50011972"
    assert params["method"] == "taobao.itemcats.get"


# ═══════════════════════════════════════════════════════════════════════════════════
# Tests: Pagination edge cases
# ═══════════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_pagination_default_page_and_size(mock_request, order_list_payload):
    """Default page=1, page_size=20 should be sent as strings in params."""
    mock_request.return_value = order_list_payload

    await get_order_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
    )

    _, kwargs = mock_request.call_args
    params = kwargs["params"]
    assert params["page_no"] == "1"
    assert params["page_size"] == "20"


@pytest.mark.asyncio
async def test_pagination_custom_page_and_size(mock_request, order_list_payload):
    """Custom page and page_size values should be passed as strings."""
    mock_request.return_value = order_list_payload

    await get_order_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
        page=3,
        page_size=50,
    )

    _, kwargs = mock_request.call_args
    params = kwargs["params"]
    assert params["page_no"] == "3"
    assert params["page_size"] == "50"


@pytest.mark.asyncio
async def test_pagination_empty_result_set(mock_request):
    """An empty order list should be handled gracefully."""
    empty_response = {
        "taobao_trades_sold_get_response": {
            "total_results": 0,
            "trades": {"trade": []},
        },
    }
    mock_request.return_value = empty_response

    result_json = await get_order_list(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-01 00:00:01",
    )
    result = json.loads(result_json)

    response = result["taobao_trades_sold_get_response"]
    assert response["total_results"] == 0
    assert response["trades"]["trade"] == []


@pytest.mark.asyncio
async def test_pagination_product_list_defaults(mock_request, product_list_payload):
    """Product list pagination defaults should match order list behavior."""
    mock_request.return_value = product_list_payload

    await get_product_list()

    _, kwargs = mock_request.call_args
    params = kwargs["params"]
    assert params["page_no"] == "1"
    assert params["page_size"] == "20"


@pytest.mark.asyncio
async def test_pagination_review_list_custom(mock_request, review_list_payload):
    """Review list should support custom pagination."""
    mock_request.return_value = review_list_payload

    await get_review_list(num_iid="10000001", page=2, page_size=10)

    _, kwargs = mock_request.call_args
    params = kwargs["params"]
    assert params["page_no"] == "2"
    assert params["page_size"] == "10"


# ═══════════════════════════════════════════════════════════════════════════════════
# Tests: Error handling
# ═══════════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_commerce_api_error_returns_error_response_dict(mock_request):
    """When _request raises CommerceAPIError, _call catches it and returns error dict."""
    mock_request.side_effect = CommerceAPIError(code=15, msg="remote service error")

    result_json = await get_order_detail(tid="999999999999999999")
    result = json.loads(result_json)

    assert "error_response" in result
    assert result["error_response"]["code"] == 15
    assert "remote service error" in result["error_response"]["msg"]


@pytest.mark.asyncio
async def test_timeout_error_returns_error_response_dict(mock_request):
    """When _request raises TimeoutError, _call catches it and returns error dict."""
    mock_request.side_effect = TimeoutError("Connection timed out")

    result_json = await get_product_list()
    result = json.loads(result_json)

    assert "error_response" in result
    assert result["error_response"]["code"] == -1
    assert "Connection timed out" in result["error_response"]["msg"]


@pytest.mark.asyncio
async def test_refund_api_error_returns_error_response_dict(mock_request):
    """Error from refund tool should return error dict."""
    mock_request.side_effect = CommerceAPIError(code=27, msg="refund not found")

    result_json = await get_refund_detail(refund_id="RF99999999999")
    result = json.loads(result_json)

    assert "error_response" in result
    assert result["error_response"]["code"] == 27
    assert "refund not found" in result["error_response"]["msg"]

    # Verify _request was called with the correct refund_id
    _, kwargs = mock_request.call_args
    params = kwargs["params"]
    assert params["method"] == "taobao.refund.get"
    assert params["refund_id"] == "RF99999999999"


@pytest.mark.asyncio
async def test_missing_required_params_raises_type_error():
    """Calling a tool without required positional params should raise TypeError."""
    with pytest.raises(TypeError):
        await get_order_detail()

    with pytest.raises(TypeError):
        await get_order_list()

    with pytest.raises(TypeError):
        await get_refund_detail()

    with pytest.raises(TypeError):
        await get_product_detail()


# ═══════════════════════════════════════════════════════════════════════════════════
# Tests: JSON output format
# ═══════════════════════════════════════════════════════════════════════════════════


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
    assert "taobao_trades_sold_get_response" in parsed


@pytest.mark.asyncio
async def test_increment_orders_output_is_valid_json(mock_request, increment_orders_payload):
    """get_increment_orders should return valid JSON string."""
    mock_request.return_value = increment_orders_payload

    result = await get_increment_orders(
        start_time="2024-01-01 00:00:00",
        end_time="2024-01-31 23:59:59",
    )

    assert isinstance(result, str)
    parsed = json.loads(result)
    assert isinstance(parsed, dict)
    assert "taobao_trades_sold_increment_get_response" in parsed


@pytest.mark.asyncio
async def test_logistics_output_is_valid_json(mock_request, logistics_tracking_payload):
    """get_logistics_tracking should return valid JSON string."""
    mock_request.return_value = logistics_tracking_payload

    result = await get_logistics_tracking(tid="123456789012345678")

    assert isinstance(result, str)
    parsed = json.loads(result)
    assert isinstance(parsed, dict)
    assert "taobao_logistics_trace_search_response" in parsed


@pytest.mark.asyncio
async def test_seller_info_output_is_valid_json(mock_request, seller_info_payload):
    """get_seller_info should return valid JSON string."""
    mock_request.return_value = seller_info_payload

    result = await get_seller_info()

    assert isinstance(result, str)
    parsed = json.loads(result)
    assert isinstance(parsed, dict)
    assert "taobao_user_seller_get_response" in parsed


# ═══════════════════════════════════════════════════════════════════════════════════
# Tests: API method and param passthrough verification
# ═══════════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_request_api_method_verification(mock_request):
    """Verify _request receives the exact Taobao API method name in params."""
    mock_request.return_value = _mock_response({"ok": True})

    await get_order_detail(tid="12345")

    _, kwargs = mock_request.call_args
    params = kwargs["params"]
    assert params["method"] == "taobao.trade.fullinfo.get"
    assert params["tid"] == "12345"


@pytest.mark.asyncio
async def test_request_refund_api_method_verification(mock_request):
    """Verify _request receives correct Taobao API method for refund detail."""
    mock_request.return_value = _mock_response({"ok": True})

    await get_refund_detail(refund_id="RF001")

    _, kwargs = mock_request.call_args
    params = kwargs["params"]
    assert params["method"] == "taobao.refund.get"
    assert params["refund_id"] == "RF001"


@pytest.mark.asyncio
async def test_request_seller_info_no_biz_params(mock_request):
    """get_seller_info should pass no business params (empty dict to _call)."""
    mock_request.return_value = _mock_response({"ok": True})

    await get_seller_info()

    _, kwargs = mock_request.call_args
    params = kwargs["params"]
    assert params["method"] == "taobao.user.seller.get"
