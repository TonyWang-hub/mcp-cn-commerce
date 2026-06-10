"""Tests for the Doudian MCP server tools and client."""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

import servers.doudian.server as _srv  # noqa: E402 — the module itself (for patching)
from servers.doudian.server import (  # noqa: E402
    ConfigError,
    DouDianAPIError,
    _safe_get,
    get_bill_list,
    get_feige_messages,
    get_live_data,
    get_logistics_tracking,
    get_order_detail,
    get_order_list,
    get_product_list,
    get_refund_list,
    get_review_detail,
    get_review_list,
    get_shop_info,
    get_shop_score,
    get_short_video_data,
    get_traffic_data,
    list_brands,
    list_categories,
    list_coupons,
    list_live_rooms,
    list_logistics_companies,
    list_promotions,
)

# ═════════════════════════════════════════════════════════════════════
#  Constants – mock environment for client instantiation
# ═════════════════════════════════════════════════════════════════════

VALID_ENV = {
    "DOUDIAN_APP_KEY": "test-app-key",
    "DOUDIAN_APP_SECRET": "test-app-secret",
    "DOUDIAN_SHOP_ID": "test-shop-id",
    "DOUDIAN_ACCESS_TOKEN": "test-access-token",
}

# ── Shared helpers ──────────────────────────────────────────────────


def make_mock_client(return_data: dict[str, Any]) -> AsyncMock:
    """Return an AsyncMock whose .request() yields *return_data*."""
    client = AsyncMock()
    client.request = AsyncMock(return_value=return_data)
    return client


def patch_environ() -> dict[str, str]:
    """Context-manager helper: patch os.environ with valid env vars."""
    return patch.dict(os.environ, VALID_ENV, clear=True)


# ═════════════════════════════════════════════════════════════════════
#  Tests
# ═════════════════════════════════════════════════════════════════════


class TestGetOrderList:
    """Tests for the get_order_list tool."""

    @pytest.mark.asyncio
    async def test_returns_orders_with_correct_fields(self):
        """When the API returns order data, every order has the expected keys."""
        mock_data = {
            "total": 2,
            "list": [
                {
                    "order_id": "001",
                    "shop_order_id": "SO-001",
                    "order_status": "2",
                    "order_status_desc": "备货中",
                    "pay_amount": "99.00",
                    "post_amount": "5.00",
                    "create_time": "2025-01-01 12:00:00",
                    "pay_time": "2025-01-01 12:05:00",
                    "product_info": {
                        "list": [
                            {
                                "product_id": "P1",
                                "product_name": "Test Product A",
                                "price": "49.50",
                                "combo_num": "2",
                                "spec_desc": "红色",
                            }
                        ]
                    },
                    "buyer_info": {"name": "张三", "phone": "138****0000"},
                    "buyer_words": "请尽快发货",
                },
                {
                    "order_id": "002",
                    "shop_order_id": "SO-002",
                    "order_status": "4",
                    "order_status_desc": "已收货",
                    "pay_amount": "150.00",
                    "post_amount": "0.00",
                    "create_time": "2025-01-02 10:00:00",
                    "pay_time": "2025-01-02 10:03:00",
                    "product_info": {"list": []},
                    "buyer_info": {},
                    "buyer_words": "",
                },
            ],
        }

        mock_client = make_mock_client(mock_data)
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await get_order_list(page=0, page_size=10)

        assert result["page"] == 0
        assert result["page_size"] == 10
        assert result["total"] == 2
        assert len(result["orders"]) == 2

        order = result["orders"][0]
        assert order["order_id"] == "001"
        assert order["shop_order_id"] == "SO-001"
        assert order["status"] == "2"
        assert order["status_desc"] == "备货中"
        assert order["amount"] == "99.00"
        assert order["post_amount"] == "5.00"
        assert order["create_time"] == "2025-01-01 12:00:00"
        assert order["pay_time"] == "2025-01-01 12:05:00"

        # product_info
        products = order["product_info"]
        assert isinstance(products, list)
        assert len(products) == 1
        assert products[0]["product_id"] == "P1"
        assert products[0]["product_name"] == "Test Product A"
        assert products[0]["price"] == "49.50"
        assert products[0]["quantity"] == "2"

        # buyer_info
        buyer = order["buyer_info"]
        assert buyer["buyer_name"] == "张三"
        assert buyer["buyer_phone"] == "138****0000"
        assert buyer["buyer_words"] == "请尽快发货"

    @pytest.mark.asyncio
    async def test_filters_passed_to_api(self):
        """Time and status filters are forwarded as API params."""
        mock_data = {"total": 0, "list": []}
        mock_client = make_mock_client(mock_data)

        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            await get_order_list(
                start_time="2025-03-01 00:00:00",
                end_time="2025-03-31 23:59:59",
                order_status="3",
                page=2,
                page_size=50,
            )

        mock_client.request.assert_called_once()
        call_args = mock_client.request.call_args
        # First positional arg (after self) is the method name
        assert call_args[0][0] == "order/list"
        # Second positional arg is the params dict (passed positionally)
        params = call_args[0][1]
        assert params["start_time"] == "2025-03-01 00:00:00"
        assert params["end_time"] == "2025-03-31 23:59:59"
        assert params["order_status"] == "3"
        assert params["page"] == "2"
        assert params["size"] == "50"

    @pytest.mark.asyncio
    async def test_empty_list_when_no_orders(self):
        """An empty list from the API yields an empty orders list."""
        mock_data: dict[str, Any] = {"list": []}
        mock_client = make_mock_client(mock_data)

        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await get_order_list()

        assert result["orders"] == []
        assert result["total"] == 0


class TestGetOrderDetail:
    """Tests for the get_order_detail tool."""

    @pytest.mark.asyncio
    async def test_returns_single_order_detail(self):
        """All detail fields are extracted from the API response."""
        mock_data = {
            "detail": {
                "order_id": "ORD-12345",
                "shop_order_id": "SHOP-001",
                "order_status": "3",
                "order_status_desc": "已发货",
                "create_time": "2025-06-01 08:00:00",
                "pay_time": "2025-06-01 08:01:00",
                "pay_type": "1",
                "pay_amount": "199.00",
                "post_amount": "10.00",
                "post_insurance_amount": "0.50",
                "coupon_amount": "20.00",
                "shop_coupon_amount": "5.00",
                "total_amount": "219.00",
                "cancel_reason": "",
                "buyer_words": "请发顺丰",
                "seller_words": "好的",
                "is_comment": "0",
                "logistics_info": {
                    "company": "顺丰速运",
                    "code": "SF1234567890",
                    "receiver_name": "王五",
                    "receiver_phone": "139****1111",
                    "receiver_address": "北京市朝阳区",
                    "ship_time": "2025-06-01 12:00:00",
                    "delivery_time": "2025-06-03 10:00:00",
                },
                "refund_status": "",
                "refund_amount": "",
                "refund_type": "",
                "after_sale_id": "",
                "product_info": {
                    "list": [
                        {
                            "product_id": "P-100",
                            "product_name": "蓝牙耳机",
                            "price": "199.00",
                            "combo_num": "1",
                            "spec_desc": "白色",
                            "outer_sku_id": "SKU-OUT",
                            "sku_id": "SKU-001",
                        }
                    ]
                },
                "buyer_info": {
                    "name": "王五",
                    "phone": "139****1111",
                    "post_addr": "北京市朝阳区XXX",
                    "post_code": "100000",
                    "province": {"name": "北京"},
                    "city": {"name": "北京市"},
                    "town": {"name": "朝阳区"},
                    "street": {"name": "XX街道"},
                },
                "order_tags": {},
                "appointment_delivery_time": "",
                "main_status": "3",
                "main_status_desc": "已发货",
                "shop_id": "S-001",
            }
        }

        mock_client = make_mock_client(mock_data)
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await get_order_detail(order_id="ORD-12345")

        mock_client.request.assert_called_once_with("order/detail", {"order_id": "ORD-12345"})

        order = result["order"]
        assert order is not None
        assert order["order_id"] == "ORD-12345"
        assert order["shop_order_id"] == "SHOP-001"
        assert order["status"] == "3"
        assert order["pay_amount"] == "199.00"
        assert order["post_amount"] == "10.00"
        assert order["coupon_amount"] == "20.00"
        assert order["total_amount"] == "219.00"

        # logistics
        log = order["logistics"]
        assert log["company"] == "顺丰速运"
        assert log["code"] == "SF1234567890"
        assert log["receiver_name"] == "王五"

        # products
        assert len(order["products"]) == 1
        prod = order["products"][0]
        assert prod["product_id"] == "P-100"
        assert prod["price"] == "199.00"
        assert prod["quantity"] == "1"

        # buyer
        buyer = order["buyer"]
        assert buyer["name"] == "王五"
        assert buyer["province"] == "北京"
        assert buyer["city"] == "北京市"

    @pytest.mark.asyncio
    async def test_with_shop_order_id(self):
        """When only shop_order_id is provided, it is sent to the API."""
        mock_data = {
            "detail": {
                "order_id": "ORD-999",
                "shop_order_id": "SHOP-999",
            }
        }
        mock_client = make_mock_client(mock_data)

        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await get_order_detail(shop_order_id="SHOP-999")

        assert result["order"]["order_id"] == "ORD-999"
        mock_client.request.assert_called_once_with("order/detail", {"shop_order_id": "SHOP-999"})

    @pytest.mark.asyncio
    async def test_missing_order_id_returns_error(self):
        """Empty order_id and empty shop_order_id returns an error dict."""
        mock_client = make_mock_client({})
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await get_order_detail(order_id="", shop_order_id="")

        assert result["error"] == "Please provide either order_id or shop_order_id"
        assert result["order"] is None
        # The API was never called
        mock_client.request.assert_not_called()


class TestGetProductList:
    """Tests for the get_product_list tool."""

    @pytest.mark.asyncio
    async def test_returns_products_with_stock_and_price(self):
        """Products include stock, price, and other merchandise fields."""
        mock_data = {
            "total": 3,
            "list": [
                {
                    "product_id": "P-A",
                    "product_id_str": "P-A-str",
                    "name": "智能手表",
                    "price": "299.00",
                    "market_price": "399.00",
                    "stock": "500",
                    "sales": "1200",
                    "status": "on_sale",
                    "status_desc": "在售",
                    "category_id": "C1",
                    "category_name": "数码",
                    "img": "https://img.example.com/p1.jpg",
                    "create_time": "2025-01-01",
                    "update_time": "2025-06-01",
                    "spec_count": "3",
                    "min_price": "299.00",
                    "max_price": "359.00",
                    "description": "一款智能手表",
                    "outer_product_id": "OUT-P001",
                },
                {
                    "product_id": "P-B",
                    "product_id_str": "P-B-str",
                    "name": "无线鼠标",
                    "price": "59.00",
                    "market_price": "79.00",
                    "stock": "200",
                    "sales": "500",
                    "status": "off_sale",
                    "status_desc": "下架",
                    "category_id": "C1",
                    "category_name": "数码",
                    "img": "",
                    "create_time": "2025-02-01",
                    "update_time": "2025-05-01",
                    "spec_count": "1",
                    "min_price": "59.00",
                    "max_price": "59.00",
                    "description": "",
                    "outer_product_id": "",
                },
            ],
        }

        mock_client = make_mock_client(mock_data)
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await get_product_list(page=0, page_size=20)

        assert result["total"] == 3
        assert result["page"] == 0
        assert result["page_size"] == 20
        assert len(result["products"]) == 2

        p1 = result["products"][0]
        assert p1["product_id"] == "P-A"
        assert p1["name"] == "智能手表"
        assert p1["price"] == "299.00"
        assert p1["stock"] == "500"
        assert p1["sales"] == "1200"
        assert p1["status"] == "on_sale"
        assert p1["market_price"] == "399.00"
        assert p1["image"] == "https://img.example.com/p1.jpg"

        p2 = result["products"][1]
        assert p2["price"] == "59.00"
        assert p2["stock"] == "200"
        assert p2["status"] == "off_sale"

    @pytest.mark.asyncio
    async def test_status_filter_applied(self):
        """The status parameter is forwarded to the API."""
        mock_data = {"total": 0, "list": []}
        mock_client = make_mock_client(mock_data)
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            await get_product_list(status="on_sale")

        params = mock_client.request.call_args[0][1]
        assert params["status"] == "on_sale"


class TestGetRefundList:
    """Tests for the get_refund_list tool."""

    @pytest.mark.asyncio
    async def test_returns_refund_records(self):
        """Refund/after-sale records include amount, status, and reason."""
        mock_data = {
            "total": 1,
            "list": [
                {
                    "refund_id": "RF-001",
                    "order_id": "ORD-001",
                    "refund_type": "1",
                    "refund_type_desc": "退货退款",
                    "refund_amount": "99.00",
                    "status": "2",
                    "status_desc": "商家同意",
                    "reason": "不喜欢",
                    "reason_desc": "不喜欢/不想要",
                    "create_time": "2025-06-01 10:00:00",
                    "update_time": "2025-06-02 14:00:00",
                    "refund_phase": "2",
                    "pay_amount": "99.00",
                    "logistics_code": "SF001",
                    "logistics_company": "顺丰速运",
                    "product_name": "蓝牙耳机",
                    "product_id": "P-100",
                    "buyer_name": "张三",
                    "arbitrate_status": "0",
                }
            ],
        }

        mock_client = make_mock_client(mock_data)
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await get_refund_list(
                start_time="2025-06-01 00:00:00",
                end_time="2025-06-30 23:59:59",
                refund_type="1",
                page=0,
                page_size=10,
            )

        assert result["total"] == 1
        assert len(result["refunds"]) == 1

        refund = result["refunds"][0]
        assert refund["refund_id"] == "RF-001"
        assert refund["order_id"] == "ORD-001"
        assert refund["refund_type"] == "1"
        assert refund["refund_type_desc"] == "退货退款"
        assert refund["amount"] == "99.00"
        assert refund["status"] == "2"
        assert refund["status_desc"] == "商家同意"
        assert refund["reason"] == "不喜欢"
        assert refund["product_name"] == "蓝牙耳机"
        assert refund["buyer_name"] == "张三"

    @pytest.mark.asyncio
    async def test_refund_type_mapped_to_api_param(self):
        """The refund_type arg is sent as 'type' in the API params."""
        mock_data = {"total": 0, "list": []}
        mock_client = make_mock_client(mock_data)
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            await get_refund_list(refund_type="0")

        params = mock_client.request.call_args[0][1]
        assert params["type"] == "0"

    @pytest.mark.asyncio
    async def test_empty_list_when_no_refunds(self):
        """Empty API response returns an empty refunds list."""
        mock_data: dict[str, Any] = {"list": []}
        mock_client = make_mock_client(mock_data)
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await get_refund_list()

        assert result["refunds"] == []
        assert result["total"] == 0


class TestGetShopInfo:
    """Tests for the get_shop_info tool."""

    @pytest.mark.asyncio
    async def test_returns_shop_name_and_rating(self):
        """Shop info response includes name, rating, and other fields."""
        mock_data = {
            "shop": {
                "shop_id": "S-001",
                "shop_name": "小王的数码店",
                "logo": "https://img.example.com/logo.png",
                "shop_score": "4.8",
                "status": "1",
                "status_desc": "正常营业",
                "shop_type": "品牌店",
                "main_product": "数码产品",
                "open_time": "2020-01-01",
                "province": {"name": "广东"},
                "city": {"name": "深圳市"},
                "certification_status": "1",
                "brand_info": "华为",
                "goods_count": "150",
                "order_count_30d": "5000",
                "refund_rate": "0.02",
                "dispute_rate": "0.01",
            }
        }

        mock_client = make_mock_client(mock_data)
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await get_shop_info()

        mock_client.request.assert_called_once_with("shop/basicInfo", {})

        shop = result["shop"]
        assert shop is not None
        assert shop["shop_id"] == "S-001"
        assert shop["shop_name"] == "小王的数码店"
        assert shop["rating"] == "4.8"
        assert shop["logo"] == "https://img.example.com/logo.png"
        assert shop["status"] == "1"
        assert shop["status_desc"] == "正常营业"
        assert shop["province"] == "广东"
        assert shop["city"] == "深圳市"
        assert shop["goods_count"] == "150"
        assert shop["order_count_30d"] == "5000"
        assert shop["refund_rate"] == "0.02"

    @pytest.mark.asyncio
    async def test_shop_score_fallback(self):
        """When 'shop_score' is absent, 'rating' is used as fallback."""
        mock_data = {"shop": {"shop_id": "S-002", "shop_name": "Test Shop", "rating": "4.5"}}
        mock_client = make_mock_client(mock_data)
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await get_shop_info()

        assert result["shop"]["rating"] == "4.5"


class TestAPIErrorHandling:
    """Tests for error handling across all tools."""

    @pytest.mark.asyncio
    async def test_doudian_api_error_caught_in_get_order_list(self):
        """When the API raises DouDianAPIError, the tool returns an error dict."""
        mock_client = make_mock_client({})
        mock_client.request = AsyncMock(
            side_effect=DouDianAPIError(
                code=40001, msg="Invalid params", sub_code="40001-1", sub_msg="Missing timestamp"
            )
        )

        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await get_order_list()

        assert "error" in result
        assert result["code"] == 40001
        assert "Invalid params" in result["error"]
        assert result["orders"] == []

    @pytest.mark.asyncio
    async def test_api_error_in_get_order_detail(self):
        """DouDianAPIError is caught and returned for order detail."""
        mock_client = make_mock_client({})
        mock_client.request = AsyncMock(side_effect=DouDianAPIError(code=50000, msg="Server error"))

        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await get_order_detail(order_id="123")

        assert result["error"]
        assert result["code"] == 50000
        assert result["order"] is None

    @pytest.mark.asyncio
    async def test_api_error_in_get_product_list(self):
        """DouDianAPIError is caught for product list."""
        mock_client = make_mock_client({})
        mock_client.request = AsyncMock(side_effect=DouDianAPIError(code=40002, msg="Shop not found"))

        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await get_product_list()

        assert result["error"]
        assert result["code"] == 40002
        assert result["products"] == []

    @pytest.mark.asyncio
    async def test_api_error_in_get_refund_list(self):
        """DouDianAPIError is caught for refund list."""
        mock_client = make_mock_client({})
        mock_client.request = AsyncMock(side_effect=DouDianAPIError(code=40003, msg="Unauthorized"))

        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await get_refund_list()

        assert result["error"]
        assert result["code"] == 40003
        assert result["refunds"] == []

    @pytest.mark.asyncio
    async def test_api_error_in_get_shop_info(self):
        """DouDianAPIError is caught for shop info."""
        mock_client = make_mock_client({})
        mock_client.request = AsyncMock(side_effect=DouDianAPIError(code=40004, msg="Token expired"))

        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await get_shop_info()

        assert result["error"]
        assert result["code"] == 40004
        assert result["shop"] is None


class TestConfigErrorHandling:
    """Tests for missing environment-variable handling."""

    @pytest.mark.asyncio
    async def test_get_client_raises_when_all_vars_missing(self):
        """_get_client raises ConfigError listing every missing variable."""
        with patch.dict(os.environ, {}, clear=True):
            # Reset singleton cache
            import servers.doudian.server as srv

            srv._client = None

            with pytest.raises(ConfigError) as exc_info:
                srv._get_client()

            msg = str(exc_info.value)
            assert "DOUDIAN_APP_KEY" in msg
            assert "DOUDIAN_APP_SECRET" in msg
            assert "DOUDIAN_SHOP_ID" in msg
            assert "DOUDIAN_ACCESS_TOKEN" in msg

    @pytest.mark.asyncio
    async def test_get_client_raises_when_single_var_missing(self):
        """Missing a single variable raises ConfigError naming it."""
        partial = {
            "DOUDIAN_APP_KEY": "k",
            "DOUDIAN_APP_SECRET": "s",
            "DOUDIAN_SHOP_ID": "sid",
            # DOUDIAN_ACCESS_TOKEN intentionally omitted
        }
        with patch.dict(os.environ, partial, clear=True):
            import servers.doudian.server as srv

            srv._client = None

            with pytest.raises(ConfigError) as exc_info:
                srv._get_client()

            msg = str(exc_info.value)
            assert "DOUDIAN_ACCESS_TOKEN" in msg
            # The other three should NOT appear
            assert "DOUDIAN_APP_KEY" not in msg
            assert "DOUDIAN_APP_SECRET" not in msg
            assert "DOUDIAN_SHOP_ID" not in msg

    @pytest.mark.asyncio
    async def test_config_error_caught_in_tool_get_order_list(self):
        """When env vars are missing, tools catch ConfigError gracefully."""
        with patch.dict(os.environ, {}, clear=True):
            import servers.doudian.server as srv

            srv._client = None

            result = await get_order_list()

        assert "error" in result
        assert "Missing required environment variables" in result["error"]
        assert result["orders"] == []

    @pytest.mark.asyncio
    async def test_config_error_caught_in_tool_get_shop_info(self):
        """ConfigError is caught in get_shop_info too."""
        with patch.dict(os.environ, {}, clear=True):
            import servers.doudian.server as srv

            srv._client = None

            result = await get_shop_info()

        assert "error" in result
        assert result["shop"] is None

    @pytest.mark.asyncio
    async def test_config_error_caught_in_tool_get_product_list(self):
        """ConfigError is caught in get_product_list."""
        with patch.dict(os.environ, {}, clear=True):
            import servers.doudian.server as srv

            srv._client = None

            result = await get_product_list()

        assert "error" in result
        assert result["products"] == []

    @pytest.mark.asyncio
    async def test_config_error_caught_in_tool_get_refund_list(self):
        """ConfigError is caught in get_refund_list."""
        with patch.dict(os.environ, {}, clear=True):
            import servers.doudian.server as srv

            srv._client = None

            result = await get_refund_list()

        assert "error" in result
        assert result["refunds"] == []


class TestSafeGet:
    """Tests for the _safe_get helper."""

    def test_returns_value_for_existing_key(self):
        assert _safe_get({"a": 1}, "a") == 1

    def test_returns_default_for_missing_key(self):
        assert _safe_get({"a": 1}, "b") == ""

    def test_returns_custom_default(self):
        assert _safe_get({"a": 1}, "b", default=42) == 42

    def test_nested_keys(self):
        d = {"a": {"b": {"c": "val"}}}
        assert _safe_get(d, "a", "b", "c") == "val"

    def test_nested_missing_intermediate(self):
        d = {"a": {"b": {}}}
        assert _safe_get(d, "a", "missing", "c") == ""

    def test_non_dict_intermediate(self):
        d = {"a": "not-a-dict"}
        assert _safe_get(d, "a", "b") == ""

    def test_fallback_default_keyword(self):
        """The 'default' keyword in _safe_get is used as a fallback value
        on the source dict for a second key lookup."""
        # This tests the pattern: _safe_get(p, "name", default=_safe_get(p, "product_name"))
        d = {"product_name": "Fallback Name"}
        result = _safe_get(d, "name", default=_safe_get(d, "product_name"))
        assert result == "Fallback Name"


# ═════════════════════════════════════════════════════════════════════
#  New tools tests — logistics, reviews, customer service,
#  live streaming, traffic, short video, marketing, billing,
#  shop extended
# ═════════════════════════════════════════════════════════════════════


# ── 物流 (logistics) ──────────────────────────────────────────────


class TestGetLogisticsTracking:
    """Tests for the get_logistics_tracking tool."""

    @pytest.mark.asyncio
    async def test_returns_tracking_with_steps(self):
        """Tracking data includes status, company, and trace steps."""
        mock_data = {
            "logistics_trace": {
                "order_id": "ORD-001",
                "logistics_code": "SF1234567890",
                "company": "顺丰速运",
                "status": "3",
                "status_desc": "运输中",
                "receiver_name": "张三",
                "receiver_phone": "138****0000",
                "receiver_address": "北京市朝阳区",
                "sender_name": "小王数码店",
                "sender_phone": "139****1111",
                "sender_address": "广东省深圳市",
                "ship_time": "2025-06-01 10:00:00",
                "delivery_time": "",
                "sign_time": "",
                "trace_list": [
                    {
                        "time": "2025-06-01 10:00:00",
                        "status": "已揽件",
                        "desc": "快递已揽收",
                        "city": "深圳市",
                    },
                    {
                        "time": "2025-06-01 18:00:00",
                        "status": "运输中",
                        "desc": "到达深圳分拣中心",
                        "city": "深圳市",
                    },
                    {
                        "time": "2025-06-02 08:00:00",
                        "status": "运输中",
                        "desc": "到达北京分拣中心",
                        "city": "北京市",
                    },
                ],
            }
        }

        mock_client = make_mock_client(mock_data)
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await get_logistics_tracking(order_id="ORD-001")

        mock_client.request.assert_called_once_with("order/logisticsTrace", {"order_id": "ORD-001"})

        tracking = result["tracking"]
        assert tracking is not None
        assert tracking["order_id"] == "ORD-001"
        assert tracking["tracking_id"] == "SF1234567890"
        assert tracking["company"] == "顺丰速运"
        assert tracking["status"] == "3"
        assert tracking["receiver_name"] == "张三"
        assert tracking["sender_name"] == "小王数码店"

        assert len(tracking["steps"]) == 3
        assert tracking["steps"][0]["time"] == "2025-06-01 10:00:00"
        assert tracking["steps"][1]["desc"] == "到达深圳分拣中心"
        assert tracking["steps"][2]["location"] == "北京市"

    @pytest.mark.asyncio
    async def test_missing_order_id_returns_error(self):
        """Empty order_id returns an error dict."""
        mock_client = make_mock_client({})
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await get_logistics_tracking(order_id="")

        assert result["error"] == "Please provide order_id"
        assert result["tracking"] is None
        mock_client.request.assert_not_called()

    @pytest.mark.asyncio
    async def test_api_error_caught(self):
        """DouDianAPIError is caught and returned."""
        mock_client = make_mock_client({})
        mock_client.request = AsyncMock(side_effect=DouDianAPIError(code=40001, msg="Order not found"))
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await get_logistics_tracking(order_id="ORD-999")

        assert result["error"]
        assert result["code"] == 40001
        assert result["tracking"] is None


class TestListLogisticsCompanies:
    """Tests for the list_logistics_companies tool."""

    @pytest.mark.asyncio
    async def test_returns_company_list(self):
        """Returns a list of logistics companies with code and name."""
        mock_data = {
            "list": [
                {"code": "SF", "name": "顺丰速运", "short_name": "顺丰", "phone": "95338"},
                {"code": "YTO", "name": "圆通速递", "short_name": "圆通", "phone": "95554"},
                {"code": "ZTO", "name": "中通快递", "short_name": "中通", "phone": "95311"},
            ],
        }

        mock_client = make_mock_client(mock_data)
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await list_logistics_companies()

        mock_client.request.assert_called_once_with("order/getLogisticsCompanyList", {})

        assert result["total"] == 3
        companies = result["companies"]
        assert companies[0]["company_code"] == "SF"
        assert companies[0]["company_name"] == "顺丰速运"
        assert companies[1]["company_code"] == "YTO"
        assert companies[2]["company_name"] == "中通快递"

    @pytest.mark.asyncio
    async def test_empty_list(self):
        """Empty API response yields empty companies list."""
        mock_data = {"list": []}
        mock_client = make_mock_client(mock_data)
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await list_logistics_companies()

        assert result["companies"] == []
        assert result["total"] == 0


# ── 评价 (reviews) ─────────────────────────────────────────────────


class TestGetReviewList:
    """Tests for the get_review_list tool."""

    @pytest.mark.asyncio
    async def test_returns_reviews_with_scores(self):
        """Reviews include score, content, and product info."""
        mock_data = {
            "total": 2,
            "list": [
                {
                    "comment_id": "C-001",
                    "order_id": "ORD-001",
                    "product_id": "P-100",
                    "product_name": "蓝牙耳机",
                    "comment_score": "5",
                    "content": "音质很好，物流快",
                    "images": ["img1.jpg", "img2.jpg"],
                    "videos": [],
                    "seller_reply": "感谢好评",
                    "seller_reply_time": "2025-06-02 10:00:00",
                    "create_time": "2025-06-01 15:00:00",
                    "is_anonymous": "0",
                    "buyer_name": "张三",
                    "buyer_avatar": "avatar.jpg",
                    "spec_desc": "白色",
                    "is_auto_comment": "0",
                    "score_product": "5",
                    "score_service": "5",
                    "score_logistics": "5",
                },
                {
                    "comment_id": "C-002",
                    "order_id": "ORD-002",
                    "product_id": "P-200",
                    "product_name": "智能手表",
                    "comment_score": "4",
                    "content": "还行吧，充电有点慢",
                    "images": [],
                    "videos": [],
                    "seller_reply": "",
                    "seller_reply_time": "",
                    "create_time": "2025-06-02 10:00:00",
                    "is_anonymous": "1",
                    "buyer_name": "李**",
                    "buyer_avatar": "",
                    "spec_desc": "黑色",
                    "is_auto_comment": "0",
                    "score_product": "4",
                    "score_service": "5",
                    "score_logistics": "4",
                },
            ],
        }

        mock_client = make_mock_client(mock_data)
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await get_review_list(
                start_time="2025-06-01 00:00:00",
                end_time="2025-06-30 23:59:59",
                page=0,
                page_size=10,
            )

        assert result["total"] == 2
        assert result["page"] == 0
        assert len(result["reviews"]) == 2

        r1 = result["reviews"][0]
        assert r1["review_id"] == "C-001"
        assert r1["score"] == "5"
        assert r1["content"] == "音质很好，物流快"
        assert r1["product_name"] == "蓝牙耳机"
        assert r1["buyer_name"] == "张三"
        assert r1["reply"] == "感谢好评"
        assert r1["score_product"] == "5"
        assert r1["score_service"] == "5"
        assert r1["score_logistics"] == "5"

        r2 = result["reviews"][1]
        assert r2["review_id"] == "C-002"
        assert r2["score"] == "4"
        assert r2["is_anonymous"] == "1"

    @pytest.mark.asyncio
    async def test_time_filters_passed_to_api(self):
        """Start and end time filters are sent to API."""
        mock_data = {"total": 0, "list": []}
        mock_client = make_mock_client(mock_data)

        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            await get_review_list(
                start_time="2025-03-01 00:00:00",
                end_time="2025-03-31 23:59:59",
            )

        params = mock_client.request.call_args[0][1]
        assert params["start_time"] == "2025-03-01 00:00:00"
        assert params["end_time"] == "2025-03-31 23:59:59"


class TestGetReviewDetail:
    """Tests for the get_review_detail tool."""

    @pytest.mark.asyncio
    async def test_returns_review_detail(self):
        """Review detail includes all score dimensions and reply info."""
        mock_data = {
            "detail": {
                "comment_id": "C-001",
                "order_id": "ORD-001",
                "product_id": "P-100",
                "product_name": "蓝牙耳机",
                "product_image": "product.jpg",
                "comment_score": "5",
                "score_product": "5",
                "score_service": "5",
                "score_logistics": "5",
                "content": "音质很好，物流快",
                "images": ["img1.jpg"],
                "videos": [],
                "seller_reply": "感谢好评！",
                "seller_reply_time": "2025-06-02 10:00:00",
                "additional_content": "用了几天很不错",
                "additional_time": "2025-06-05 12:00:00",
                "additional_reply": "感谢追加评价",
                "create_time": "2025-06-01 15:00:00",
                "is_anonymous": "0",
                "is_auto_comment": "0",
                "buyer_name": "张三",
                "buyer_avatar": "avatar.jpg",
                "spec_desc": "白色",
                "order_amount": "199.00",
            }
        }

        mock_client = make_mock_client(mock_data)
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await get_review_detail(review_id="C-001")

        mock_client.request.assert_called_once_with("comment/detail", {"comment_id": "C-001"})

        review = result["review"]
        assert review is not None
        assert review["review_id"] == "C-001"
        assert review["score"] == "5"
        assert review["product_name"] == "蓝牙耳机"
        assert review["reply"] == "感谢好评！"
        assert review["additional"] == "用了几天很不错"
        assert review["order_amount"] == "199.00"

    @pytest.mark.asyncio
    async def test_missing_review_id_returns_error(self):
        """Empty review_id returns an error dict."""
        mock_client = make_mock_client({})
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await get_review_detail(review_id="")

        assert result["error"] == "Please provide review_id"
        assert result["review"] is None
        mock_client.request.assert_not_called()


# ── 客服 (customer service — 飞鸽) ────────────────────────────────


class TestGetFeigeMessages:
    """Tests for the get_feige_messages tool."""

    @pytest.mark.asyncio
    async def test_returns_messages(self):
        """Returns chat messages with role, content, and time."""
        mock_data = {
            "total": 3,
            "list": [
                {
                    "message_id": "MSG-001",
                    "content": "你好，这个耳机有货吗？",
                    "msg_type": "text",
                    "from_role": "buyer",
                    "from_user_id": "U001",
                    "to_user_id": "S001",
                    "create_time": "2025-06-01 10:00:00",
                    "conversation_id": "CONV-001",
                    "is_read": "1",
                    "media_url": "",
                },
                {
                    "message_id": "MSG-002",
                    "content": "有的，需要什么颜色？",
                    "msg_type": "text",
                    "from_role": "seller",
                    "from_user_id": "S001",
                    "to_user_id": "U001",
                    "create_time": "2025-06-01 10:01:00",
                    "conversation_id": "CONV-001",
                    "is_read": "1",
                },
                {
                    "message_id": "MSG-003",
                    "content": "",
                    "msg_type": "image",
                    "from_role": "buyer",
                    "from_user_id": "U001",
                    "to_user_id": "S001",
                    "create_time": "2025-06-01 10:02:00",
                    "conversation_id": "CONV-001",
                    "is_read": "0",
                    "media_url": "https://img.example.com/photo.jpg",
                },
            ],
        }

        mock_client = make_mock_client(mock_data)
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await get_feige_messages(
                user_id="U001",
                start_time="2025-06-01 00:00:00",
                end_time="2025-06-02 00:00:00",
            )

        assert result["total"] == 3
        assert len(result["messages"]) == 3

        m1 = result["messages"][0]
        assert m1["message_id"] == "MSG-001"
        assert m1["content"] == "你好，这个耳机有货吗？"
        assert m1["from_role"] == "buyer"
        assert m1["content_type"] == "text"

        m2 = result["messages"][1]
        assert m2["from_role"] == "seller"

        m3 = result["messages"][2]
        assert m3["content_type"] == "image"
        assert m3["media_url"] == "https://img.example.com/photo.jpg"

    @pytest.mark.asyncio
    async def test_missing_user_id_returns_error(self):
        """Empty user_id returns an error dict."""
        mock_client = make_mock_client({})
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await get_feige_messages(user_id="")

        assert result["error"] == "Please provide user_id"
        assert result["messages"] == []
        mock_client.request.assert_not_called()

    @pytest.mark.asyncio
    async def test_time_filters_passed(self):
        """Start/end time filters are forwarded to the API."""
        mock_data = {"total": 0, "list": []}
        mock_client = make_mock_client(mock_data)

        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            await get_feige_messages(
                user_id="U001",
                start_time="2025-06-01 00:00:00",
                end_time="2025-06-30 23:59:59",
            )

        params = mock_client.request.call_args[0][1]
        assert params["user_id"] == "U001"
        assert params["start_time"] == "2025-06-01 00:00:00"
        assert params["end_time"] == "2025-06-30 23:59:59"


# ── 直播 (live streaming) ──────────────────────────────────────────


class TestGetLiveData:
    """Tests for the get_live_data tool."""

    @pytest.mark.asyncio
    async def test_returns_live_data_with_all_metrics(self):
        """Live data includes viewership, interaction, and conversion metrics."""
        mock_data = {
            "live_data": {
                "room_id": "ROOM-001",
                "title": "新品发布会",
                "status": "2",
                "status_desc": "进行中",
                "start_time": "2025-06-01 19:00:00",
                "end_time": "",
                "duration": "3600",
                "cover": "https://cover.example.com/room001.jpg",
                "anchor_name": "小王主播",
                "anchor_id": "A001",
                "total_viewers": "50000",
                "peak_viewers": "12000",
                "avg_viewers": "8000",
                "watch_duration_avg": "320",
                "new_followers": "1500",
                "comments_count": "8000",
                "likes_count": "50000",
                "share_count": "2000",
                "pay_count": "500",
                "pay_amount": "150000.00",
                "pay_user_count": "400",
                "product_click_count": "12000",
                "conversion_rate": "0.01",
            }
        }

        mock_client = make_mock_client(mock_data)
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await get_live_data(
                room_id="ROOM-001",
                start_time="2025-06-01 18:00:00",
                end_time="2025-06-01 22:00:00",
            )

        mock_client.request.assert_called_once_with(
            "live/getLiveRoomData",
            {
                "room_id": "ROOM-001",
                "start_time": "2025-06-01 18:00:00",
                "end_time": "2025-06-01 22:00:00",
            },
        )

        live = result["live_data"]
        assert live is not None
        assert live["room_id"] == "ROOM-001"
        assert live["room_title"] == "新品发布会"
        assert live["anchor_name"] == "小王主播"
        assert live["total_viewers"] == "50000"
        assert live["peak_viewers"] == "12000"
        assert live["avg_viewers"] == "8000"
        assert live["comments_count"] == "8000"
        assert live["likes_count"] == "50000"
        assert live["pay_count"] == "500"
        assert live["pay_amount"] == "150000.00"
        assert live["conversion_rate"] == "0.01"

    @pytest.mark.asyncio
    async def test_missing_room_id_returns_error(self):
        """Empty room_id returns an error dict."""
        mock_client = make_mock_client({})
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await get_live_data(room_id="")

        assert result["error"] == "Please provide room_id"
        assert result["live_data"] is None
        mock_client.request.assert_not_called()


class TestListLiveRooms:
    """Tests for the list_live_rooms tool."""

    @pytest.mark.asyncio
    async def test_returns_live_room_list(self):
        """Returns a list of live rooms with summary metrics."""
        mock_data = {
            "total": 2,
            "list": [
                {
                    "room_id": "ROOM-001",
                    "title": "新品发布会",
                    "status": "2",
                    "status_desc": "进行中",
                    "start_time": "2025-06-01 19:00:00",
                    "end_time": "",
                    "duration": "3600",
                    "cover": "https://cover.example.com/room001.jpg",
                    "anchor_name": "小王主播",
                    "anchor_id": "A001",
                    "uv": "50000",
                    "max_uv": "12000",
                    "gmv": "150000.00",
                    "pay_count": "500",
                    "new_followers": "1500",
                    "comments_count": "8000",
                    "likes_count": "50000",
                },
                {
                    "room_id": "ROOM-002",
                    "title": "618大促",
                    "status": "3",
                    "status_desc": "已结束",
                    "start_time": "2025-06-02 20:00:00",
                    "end_time": "2025-06-02 23:00:00",
                    "duration": "10800",
                    "cover": "https://cover.example.com/room002.jpg",
                    "anchor_name": "小丽主播",
                    "anchor_id": "A002",
                    "uv": "80000",
                    "max_uv": "20000",
                    "gmv": "300000.00",
                    "pay_count": "1200",
                    "new_followers": "3000",
                    "comments_count": "15000",
                    "likes_count": "100000",
                },
            ],
        }

        mock_client = make_mock_client(mock_data)
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await list_live_rooms(
                start_time="2025-06-01 00:00:00",
                end_time="2025-06-30 23:59:59",
            )

        assert result["total"] == 2
        assert len(result["rooms"]) == 2

        r1 = result["rooms"][0]
        assert r1["room_id"] == "ROOM-001"
        assert r1["title"] == "新品发布会"
        assert r1["status_desc"] == "进行中"
        assert r1["total_viewers"] == "50000"
        assert r1["pay_amount"] == "150000.00"

        r2 = result["rooms"][1]
        assert r2["room_id"] == "ROOM-002"
        assert r2["status_desc"] == "已结束"
        assert r2["peak_viewers"] == "20000"
        assert r2["new_followers"] == "3000"


# ── 流量 (traffic) ─────────────────────────────────────────────────


class TestGetTrafficData:
    """Tests for the get_traffic_data tool."""

    @pytest.mark.asyncio
    async def test_returns_traffic_with_sources(self):
        """Traffic data includes totals and source breakdown."""
        mock_data = {
            "traffic_data": {
                "start_date": "2025-06-01",
                "end_date": "2025-06-07",
                "total_uv": "100000",
                "total_pv": "250000",
                "avg_stay_time": "120",
                "bounce_rate": "0.35",
                "conversion_rate": "0.03",
                "new_buyer_rate": "0.60",
                "old_buyer_rate": "0.40",
                "source_list": [
                    {
                        "source_name": "直播推荐",
                        "source_type": "live",
                        "uv": "40000",
                        "pv": "100000",
                        "uv_ratio": "0.40",
                        "pay_count": "500",
                        "pay_amount": "80000.00",
                        "conversion_rate": "0.0125",
                    },
                    {
                        "source_name": "短视频",
                        "source_type": "video",
                        "uv": "30000",
                        "pv": "80000",
                        "uv_ratio": "0.30",
                        "pay_count": "300",
                        "pay_amount": "50000.00",
                        "conversion_rate": "0.01",
                    },
                    {
                        "source_name": "搜索",
                        "source_type": "search",
                        "uv": "20000",
                        "pv": "50000",
                        "uv_ratio": "0.20",
                        "pay_count": "200",
                        "pay_amount": "30000.00",
                        "conversion_rate": "0.01",
                    },
                ],
            }
        }

        mock_client = make_mock_client(mock_data)
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await get_traffic_data(
                start_date="2025-06-01",
                end_date="2025-06-07",
            )

        mock_client.request.assert_called_once_with(
            "shop/getTrafficData",
            {"start_date": "2025-06-01", "end_date": "2025-06-07"},
        )

        traffic = result["traffic"]
        assert traffic is not None
        assert traffic["total_uv"] == "100000"
        assert traffic["total_pv"] == "250000"
        assert traffic["conversion_rate"] == "0.03"
        assert traffic["bounce_rate"] == "0.35"

        sources = traffic["sources"]
        assert len(sources) == 3
        assert sources[0]["source_name"] == "直播推荐"
        assert sources[0]["uv_ratio"] == "0.40"
        assert sources[1]["source_type"] == "video"
        assert sources[2]["source_name"] == "搜索"

    @pytest.mark.asyncio
    async def test_no_date_filters_ok(self):
        """Call without start/end dates still works."""
        mock_data = {"traffic_data": {"total_uv": "1000"}}
        mock_client = make_mock_client(mock_data)
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await get_traffic_data()

        assert result["traffic"]["total_uv"] == "1000"
        mock_client.request.assert_called_once_with("shop/getTrafficData", {})


# ── 短视频 (short video) ───────────────────────────────────────────


class TestGetShortVideoData:
    """Tests for the get_short_video_data tool."""

    @pytest.mark.asyncio
    async def test_returns_video_data_with_engagement_and_conversion(self):
        """Video data includes play, engagement, and conversion metrics."""
        mock_data = {
            "video_data": {
                "video_id": "VID-001",
                "title": "蓝牙耳机开箱评测",
                "description": "性价比超高的蓝牙耳机",
                "cover_url": "https://cover.example.com/vid001.jpg",
                "video_url": "https://video.example.com/vid001.mp4",
                "duration": "60",
                "status": "1",
                "status_desc": "发布中",
                "create_time": "2025-06-01 10:00:00",
                "play_count": "200000",
                "like_count": "15000",
                "comment_count": "3000",
                "share_count": "5000",
                "collect_count": "2000",
                "download_count": "500",
                "finish_rate": "0.45",
                "avg_watch_duration": "28",
                "product_click_count": "8000",
                "pay_count": "600",
                "gmv": "120000.00",
                "conversion_rate": "0.075",
            }
        }

        mock_client = make_mock_client(mock_data)
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await get_short_video_data(
                video_id="VID-001",
                start_date="2025-06-01",
                end_date="2025-06-30",
            )

        mock_client.request.assert_called_once_with(
            "video/getVideoData",
            {
                "video_id": "VID-001",
                "start_date": "2025-06-01",
                "end_date": "2025-06-30",
            },
        )

        vid = result["video_data"]
        assert vid is not None
        assert vid["video_id"] == "VID-001"
        assert vid["title"] == "蓝牙耳机开箱评测"
        assert vid["play_count"] == "200000"
        assert vid["like_count"] == "15000"
        assert vid["comment_count"] == "3000"
        assert vid["share_count"] == "5000"
        assert vid["finish_rate"] == "0.45"
        assert vid["pay_count"] == "600"
        assert vid["pay_amount"] == "120000.00"
        assert vid["conversion_rate"] == "0.075"

    @pytest.mark.asyncio
    async def test_missing_video_id_returns_error(self):
        """Empty video_id returns error."""
        mock_client = make_mock_client({})
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await get_short_video_data(video_id="")

        assert result["error"] == "Please provide video_id"
        assert result["video_data"] is None
        mock_client.request.assert_not_called()


# ── 营销 (marketing) ───────────────────────────────────────────────


class TestListPromotions:
    """Tests for the list_promotions tool."""

    @pytest.mark.asyncio
    async def test_returns_promotions_with_discount_rules(self):
        """Promotions include type, discount rules, and performance metrics."""
        mock_data = {
            "total": 2,
            "list": [
                {
                    "promotion_id": "PROMO-001",
                    "promotion_name": "618满减活动",
                    "promotion_type": "1",
                    "promotion_type_desc": "满减",
                    "status": "1",
                    "status_desc": "进行中",
                    "start_time": "2025-06-01 00:00:00",
                    "end_time": "2025-06-18 23:59:59",
                    "discount_rule": "满200减30",
                    "product_count": "50",
                    "order_count": "2000",
                    "gmv": "500000.00",
                    "create_time": "2025-05-20 10:00:00",
                },
                {
                    "promotion_id": "PROMO-002",
                    "promotion_name": "限时秒杀",
                    "promotion_type": "2",
                    "promotion_type_desc": "秒杀",
                    "status": "3",
                    "status_desc": "已结束",
                    "start_time": "2025-06-01 10:00:00",
                    "end_time": "2025-06-01 12:00:00",
                    "discount_rule": "5折秒杀",
                    "product_count": "10",
                    "order_count": "800",
                    "gmv": "100000.00",
                    "create_time": "2025-05-28 15:00:00",
                },
            ],
        }

        mock_client = make_mock_client(mock_data)
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await list_promotions(status="1", page=0, page_size=10)

        assert result["total"] == 2
        assert len(result["promotions"]) == 2

        p1 = result["promotions"][0]
        assert p1["promotion_id"] == "PROMO-001"
        assert p1["name"] == "618满减活动"
        assert p1["type_desc"] == "满减"
        assert p1["status_desc"] == "进行中"
        assert p1["discount_rule"] == "满200减30"
        assert p1["product_count"] == "50"
        assert p1["order_count"] == "2000"

        p2 = result["promotions"][1]
        assert p2["type_desc"] == "秒杀"
        assert p2["status_desc"] == "已结束"

    @pytest.mark.asyncio
    async def test_status_filter_passed(self):
        """Status filter is forwarded to the API."""
        mock_data = {"total": 0, "list": []}
        mock_client = make_mock_client(mock_data)
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            await list_promotions(status="1")

        params = mock_client.request.call_args[0][1]
        assert params["status"] == "1"


class TestListCoupons:
    """Tests for the list_coupons tool."""

    @pytest.mark.asyncio
    async def test_returns_coupons_with_usage_stats(self):
        """Coupons include discount info and usage statistics."""
        mock_data = {
            "total": 2,
            "list": [
                {
                    "coupon_id": "COUP-001",
                    "coupon_name": "新人优惠券",
                    "coupon_type": "1",
                    "type_desc": "满减券",
                    "discount_amount": "30.00",
                    "min_order_amount": "200.00",
                    "total_count": "10000",
                    "received_count": "5000",
                    "used_count": "2000",
                    "status": "1",
                    "status_desc": "生效中",
                    "start_time": "2025-06-01 00:00:00",
                    "end_time": "2025-06-30 23:59:59",
                    "applicable_scope": "all",
                    "usage_scope_desc": "全场通用",
                    "create_time": "2025-05-25 10:00:00",
                },
                {
                    "coupon_id": "COUP-002",
                    "coupon_name": "会员专享券",
                    "coupon_type": "2",
                    "type_desc": "折扣券",
                    "discount_amount": "8.5",
                    "min_order_amount": "100.00",
                    "total_count": "5000",
                    "received_count": "3000",
                    "used_count": "1500",
                    "status": "2",
                    "status_desc": "已失效",
                    "start_time": "2025-05-01 00:00:00",
                    "end_time": "2025-05-31 23:59:59",
                    "applicable_scope": "category",
                    "usage_scope_desc": "指定类目可用",
                    "create_time": "2025-04-25 10:00:00",
                },
            ],
        }

        mock_client = make_mock_client(mock_data)
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await list_coupons(status="1", page=0, page_size=10)

        assert result["total"] == 2
        assert len(result["coupons"]) == 2

        c1 = result["coupons"][0]
        assert c1["coupon_id"] == "COUP-001"
        assert c1["name"] == "新人优惠券"
        assert c1["type_desc"] == "满减券"
        assert c1["discount_amount"] == "30.00"
        assert c1["min_order_amount"] == "200.00"
        assert c1["received_count"] == "5000"
        assert c1["used_count"] == "2000"
        assert c1["status_desc"] == "生效中"

        c2 = result["coupons"][1]
        assert c2["name"] == "会员专享券"
        assert c2["status_desc"] == "已失效"
        assert c2["usage_scope_desc"] == "指定类目可用"

    @pytest.mark.asyncio
    async def test_empty_list(self):
        """Empty API response yields empty list."""
        mock_data = {"total": 0, "list": []}
        mock_client = make_mock_client(mock_data)
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await list_coupons()

        assert result["coupons"] == []
        assert result["total"] == 0


# ── 资金 (billing) ─────────────────────────────────────────────────


class TestGetBillList:
    """Tests for the get_bill_list tool."""

    @pytest.mark.asyncio
    async def test_returns_bills_with_amounts(self):
        """Bills include type, amount, balance changes, and description."""
        mock_data = {
            "total": 3,
            "list": [
                {
                    "bill_id": "BILL-001",
                    "order_id": "ORD-001",
                    "bill_type": "1",
                    "bill_type_desc": "订单收入",
                    "amount": "+199.00",
                    "balance_before": "1000.00",
                    "balance_after": "1199.00",
                    "create_time": "2025-06-01 10:00:00",
                    "remark": "订单ORD-001支付成功",
                    "status": "1",
                    "status_desc": "已入账",
                    "biz_type": "order",
                    "biz_type_desc": "订单结算",
                },
                {
                    "bill_id": "BILL-002",
                    "order_id": "ORD-002",
                    "bill_type": "2",
                    "bill_type_desc": "退款支出",
                    "amount": "-50.00",
                    "balance_before": "1199.00",
                    "balance_after": "1149.00",
                    "create_time": "2025-06-02 14:00:00",
                    "remark": "订单ORD-002退款",
                    "status": "1",
                    "status_desc": "已入账",
                    "biz_type": "refund",
                    "biz_type_desc": "退款",
                },
                {
                    "bill_id": "BILL-003",
                    "order_id": "",
                    "bill_type": "3",
                    "bill_type_desc": "提现",
                    "amount": "-500.00",
                    "balance_before": "1149.00",
                    "balance_after": "649.00",
                    "create_time": "2025-06-03 09:00:00",
                    "remark": "提现到银行卡",
                    "status": "2",
                    "status_desc": "处理中",
                    "biz_type": "withdraw",
                    "biz_type_desc": "提现",
                },
            ],
        }

        mock_client = make_mock_client(mock_data)
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await get_bill_list(
                start_date="2025-06-01",
                end_date="2025-06-30",
                page=0,
                page_size=20,
            )

        assert result["total"] == 3
        assert len(result["bills"]) == 3

        b1 = result["bills"][0]
        assert b1["bill_id"] == "BILL-001"
        assert b1["order_id"] == "ORD-001"
        assert b1["type_desc"] == "订单收入"
        assert b1["amount"] == "+199.00"
        assert b1["balance_before"] == "1000.00"
        assert b1["balance_after"] == "1199.00"
        assert b1["description"] == "订单ORD-001支付成功"
        assert b1["status_desc"] == "已入账"

        b2 = result["bills"][1]
        assert b2["type_desc"] == "退款支出"
        assert b2["amount"] == "-50.00"

        b3 = result["bills"][2]
        assert b3["type_desc"] == "提现"
        assert b3["balance_after"] == "649.00"
        assert b3["status_desc"] == "处理中"

    @pytest.mark.asyncio
    async def test_date_filters_passed(self):
        """Date filters are passed to the API."""
        mock_data = {"total": 0, "list": []}
        mock_client = make_mock_client(mock_data)
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            await get_bill_list(
                start_date="2025-06-01",
                end_date="2025-06-30",
            )

        params = mock_client.request.call_args[0][1]
        assert params["start_date"] == "2025-06-01"
        assert params["end_date"] == "2025-06-30"


# ── 店铺 (shop extended) ──────────────────────────────────────────


class TestGetShopScore:
    """Tests for the get_shop_score tool."""

    @pytest.mark.asyncio
    async def test_returns_detailed_scores(self):
        """Shop score includes DSR, product, service, and logistics dimensions."""
        mock_data = {
            "score_data": {
                "shop_id": "S-001",
                "dsr_score": "4.85",
                "dsr_rank": "90",
                "dsr_rank_rate": "0.10",
                "product_score": "4.80",
                "product_rank": "85",
                "product_rank_rate": "0.15",
                "product_quality_return_rate": "0.02",
                "product_negative_review_rate": "0.01",
                "service_score": "4.90",
                "service_rank": "95",
                "service_rank_rate": "0.05",
                "complaint_rate": "0.01",
                "dispute_resolution_rate": "0.98",
                "im_response_rate": "0.95",
                "im_avg_response_time": "45",
                "logistics_score": "4.85",
                "logistics_rank": "90",
                "logistics_rank_rate": "0.10",
                "ship_time_avg": "12",
                "delivery_time_avg": "48",
                "logistics_negative_rate": "0.01",
                "evaluate_time": "2025-06-01",
                "update_time": "2025-06-01 10:00:00",
            }
        }

        mock_client = make_mock_client(mock_data)
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await get_shop_score()

        mock_client.request.assert_called_once_with("shop/getShopScore", {})

        score = result["shop_score"]
        assert score is not None
        assert score["shop_id"] == "S-001"
        assert score["dsr_score"] == "4.85"
        assert score["dsr_rank_rate"] == "0.10"
        assert score["product_score"] == "4.80"
        assert score["product_rank_rate"] == "0.15"
        assert score["service_score"] == "4.90"
        assert score["im_response_rate"] == "0.95"
        assert score["im_avg_response_time"] == "45"
        assert score["logistics_score"] == "4.85"
        assert score["ship_time_avg"] == "12"
        assert score["delivery_time_avg"] == "48"
        assert score["complaint_rate"] == "0.01"

    @pytest.mark.asyncio
    async def test_api_error_caught(self):
        """DouDianAPIError is caught and returned."""
        mock_client = make_mock_client({})
        mock_client.request = AsyncMock(side_effect=DouDianAPIError(code=50000, msg="Server error"))
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await get_shop_score()

        assert result["error"]
        assert result["code"] == 50000
        assert result["shop_score"] is None


class TestListCategories:
    """Tests for the list_categories tool."""

    @pytest.mark.asyncio
    async def test_returns_category_tree(self):
        """Returns categories with parent-child relationship info."""
        mock_data = {
            "list": [
                {
                    "category_id": "C1",
                    "name": "服饰内衣",
                    "parent_id": "0",
                    "level": "1",
                    "has_child": "1",
                    "is_leaf": "0",
                    "image": "https://img.example.com/c1.png",
                    "status": "1",
                },
                {
                    "category_id": "C2",
                    "name": "数码家电",
                    "parent_id": "0",
                    "level": "1",
                    "has_child": "1",
                    "is_leaf": "0",
                    "image": "https://img.example.com/c2.png",
                    "status": "1",
                },
            ],
        }

        mock_client = make_mock_client(mock_data)
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await list_categories(parent_id="0")

        mock_client.request.assert_called_once_with("product/getCategoryList", {"parent_id": "0"})

        assert result["total"] == 2
        assert result["parent_id"] == "0"

        c1 = result["categories"][0]
        assert c1["category_id"] == "C1"
        assert c1["name"] == "服饰内衣"
        assert c1["parent_id"] == "0"
        assert c1["level"] == "1"
        assert c1["has_child"] == "1"
        assert c1["is_leaf"] == "0"

    @pytest.mark.asyncio
    async def test_default_parent_id_is_zero(self):
        """Default parent_id is '0' (root categories)."""
        mock_data = {"list": []}
        mock_client = make_mock_client(mock_data)
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            await list_categories()

        params = mock_client.request.call_args[0][1]
        assert params["parent_id"] == "0"

    @pytest.mark.asyncio
    async def test_child_categories(self):
        """Fetching child categories by parent_id."""
        mock_data = {
            "list": [
                {
                    "category_id": "C1-1",
                    "name": "男装",
                    "parent_id": "C1",
                    "level": "2",
                    "has_child": "1",
                    "is_leaf": "0",
                    "status": "1",
                },
                {
                    "category_id": "C1-2",
                    "name": "女装",
                    "parent_id": "C1",
                    "level": "2",
                    "has_child": "1",
                    "is_leaf": "0",
                    "status": "1",
                },
            ],
        }

        mock_client = make_mock_client(mock_data)
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await list_categories(parent_id="C1")

        assert result["total"] == 2
        assert result["categories"][0]["parent_id"] == "C1"
        mock_client.request.assert_called_once_with("product/getCategoryList", {"parent_id": "C1"})


class TestListBrands:
    """Tests for the list_brands tool."""

    @pytest.mark.asyncio
    async def test_returns_brands_with_logo(self):
        """Brands include name, logo, and registration info."""
        mock_data = {
            "total": 2,
            "list": [
                {
                    "brand_id": "B001",
                    "brand_name": "华为",
                    "brand_name_en": "Huawei",
                    "brand_logo": "https://img.example.com/huawei.png",
                    "description": "华为技术有限公司",
                    "category_id": "C2",
                    "category_name": "数码家电",
                    "status": "1",
                    "registered_capital": "1000000000",
                    "registered_address": "广东省深圳市",
                },
                {
                    "brand_id": "B002",
                    "brand_name": "小米",
                    "brand_name_en": "Xiaomi",
                    "brand_logo": "https://img.example.com/xiaomi.png",
                    "description": "小米科技",
                    "category_id": "C2",
                    "category_name": "数码家电",
                    "status": "1",
                    "registered_capital": "500000000",
                    "registered_address": "北京市",
                },
            ],
        }

        mock_client = make_mock_client(mock_data)
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await list_brands(category_id="C2", page=0, page_size=20)

        assert result["total"] == 2
        assert len(result["brands"]) == 2

        b1 = result["brands"][0]
        assert b1["brand_id"] == "B001"
        assert b1["name"] == "华为"
        assert b1["name_en"] == "Huawei"
        assert b1["logo"] == "https://img.example.com/huawei.png"
        assert b1["category_name"] == "数码家电"

        b2 = result["brands"][1]
        assert b2["name"] == "小米"
        assert b2["status"] == "1"

    @pytest.mark.asyncio
    async def test_category_filter_passed(self):
        """Category filter is forwarded to API."""
        mock_data = {"total": 0, "list": []}
        mock_client = make_mock_client(mock_data)
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            await list_brands(category_id="C2")

        params = mock_client.request.call_args[0][1]
        assert params["category_id"] == "C2"

    @pytest.mark.asyncio
    async def test_no_category_filter(self):
        """Brands can be listed without a category filter."""
        mock_data = {"total": 0, "list": []}
        mock_client = make_mock_client(mock_data)
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            await list_brands()

        params = mock_client.request.call_args[0][1]
        assert "category_id" not in params


# ── New tools: API error handling ─────────────────────────────────


class TestNewToolsAPIErrorHandling:
    """Error handling tests for the new tools."""

    @pytest.mark.asyncio
    async def test_api_error_in_get_review_list(self):
        mock_client = make_mock_client({})
        mock_client.request = AsyncMock(side_effect=DouDianAPIError(code=40001, msg="Invalid params"))
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await get_review_list()
        assert result["error"]
        assert result["code"] == 40001
        assert result["reviews"] == []

    @pytest.mark.asyncio
    async def test_api_error_in_get_feige_messages(self):
        mock_client = make_mock_client({})
        mock_client.request = AsyncMock(side_effect=DouDianAPIError(code=40002, msg="User not found"))
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await get_feige_messages(user_id="U001")
        assert result["error"]
        assert result["code"] == 40002
        assert result["messages"] == []

    @pytest.mark.asyncio
    async def test_api_error_in_get_live_data(self):
        mock_client = make_mock_client({})
        mock_client.request = AsyncMock(side_effect=DouDianAPIError(code=40003, msg="Room not found"))
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await get_live_data(room_id="ROOM-001")
        assert result["error"]
        assert result["code"] == 40003
        assert result["live_data"] is None

    @pytest.mark.asyncio
    async def test_api_error_in_get_traffic_data(self):
        mock_client = make_mock_client({})
        mock_client.request = AsyncMock(side_effect=DouDianAPIError(code=40004, msg="Shop not found"))
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await get_traffic_data()
        assert result["error"]
        assert result["code"] == 40004
        assert result["traffic"] is None

    @pytest.mark.asyncio
    async def test_api_error_in_get_short_video_data(self):
        mock_client = make_mock_client({})
        mock_client.request = AsyncMock(side_effect=DouDianAPIError(code=40005, msg="Video not found"))
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await get_short_video_data(video_id="VID-001")
        assert result["error"]
        assert result["code"] == 40005
        assert result["video_data"] is None

    @pytest.mark.asyncio
    async def test_api_error_in_list_promotions(self):
        mock_client = make_mock_client({})
        mock_client.request = AsyncMock(side_effect=DouDianAPIError(code=40006, msg="Invalid status"))
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await list_promotions()
        assert result["error"]
        assert result["code"] == 40006
        assert result["promotions"] == []

    @pytest.mark.asyncio
    async def test_api_error_in_list_coupons(self):
        mock_client = make_mock_client({})
        mock_client.request = AsyncMock(side_effect=DouDianAPIError(code=40007, msg="Invalid status"))
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await list_coupons()
        assert result["error"]
        assert result["code"] == 40007
        assert result["coupons"] == []

    @pytest.mark.asyncio
    async def test_api_error_in_get_bill_list(self):
        mock_client = make_mock_client({})
        mock_client.request = AsyncMock(side_effect=DouDianAPIError(code=40008, msg="Date range too large"))
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await get_bill_list()
        assert result["error"]
        assert result["code"] == 40008
        assert result["bills"] == []

    @pytest.mark.asyncio
    async def test_api_error_in_list_categories(self):
        mock_client = make_mock_client({})
        mock_client.request = AsyncMock(side_effect=DouDianAPIError(code=40009, msg="Invalid parent_id"))
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await list_categories()
        assert result["error"]
        assert result["code"] == 40009
        assert result["categories"] == []

    @pytest.mark.asyncio
    async def test_api_error_in_list_brands(self):
        mock_client = make_mock_client({})
        mock_client.request = AsyncMock(side_effect=DouDianAPIError(code=40010, msg="Category not found"))
        with patch_environ(), patch.object(_srv, "_get_client", return_value=mock_client):
            result = await list_brands()
        assert result["error"]
        assert result["code"] == 40010
        assert result["brands"] == []


class TestNewToolsConfigErrorHandling:
    """Config error handling tests for the new tools."""

    @pytest.mark.asyncio
    async def test_config_error_in_get_logistics_tracking(self):
        with patch.dict(os.environ, {}, clear=True):
            import servers.doudian.server as srv

            srv._client = None
            result = await get_logistics_tracking(order_id="ORD-001")
        assert "error" in result
        assert result["tracking"] is None

    @pytest.mark.asyncio
    async def test_config_error_in_get_review_detail(self):
        with patch.dict(os.environ, {}, clear=True):
            import servers.doudian.server as srv

            srv._client = None
            result = await get_review_detail(review_id="C-001")
        assert "error" in result
        assert result["review"] is None

    @pytest.mark.asyncio
    async def test_config_error_in_list_live_rooms(self):
        with patch.dict(os.environ, {}, clear=True):
            import servers.doudian.server as srv

            srv._client = None
            result = await list_live_rooms()
        assert "error" in result
        assert result["rooms"] == []

    @pytest.mark.asyncio
    async def test_config_error_in_get_shop_score(self):
        with patch.dict(os.environ, {}, clear=True):
            import servers.doudian.server as srv

            srv._client = None
            result = await get_shop_score()
        assert "error" in result
        assert result["shop_score"] is None
