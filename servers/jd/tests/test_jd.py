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


# ── Tests: get_order_list ──────────────────────────────────────────────────

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


# ── Tests: get_order_detail ─────────────────────────────────────────────────

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


# ── Tests: get_product_list ────────────────────────────────────────────────

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


# ── Tests: get_shop_info ────────────────────────────────────────────────────

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


# ── Tests: Error handling ───────────────────────────────────────────────────

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


# ── Tests: Pagination edge cases ───────────────────────────────────────────

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


# ── Tests: JSON output format ───────────────────────────────────────────────

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
async def test_call_passthrough_with_minimal_params(mock_call):
    """Verify _call receives the expected API method name and biz params shape."""
    mock_call.return_value = _mock_response({"ok": True})

    await get_order_detail(order_id="12345")

    api_method, biz_params = mock_call.call_args[0]
    assert api_method == "jd.pop.order.get"
    assert biz_params == {"order_id": "12345"}
