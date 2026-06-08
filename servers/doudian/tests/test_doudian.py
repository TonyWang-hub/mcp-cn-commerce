"""Tests for the Doudian MCP server tools and client."""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

# ═════════════════════════════════════════════════════════════════════
#  Compatibility shim — MCP >=1.27 moved the tool() decorator to
#  FastMCP.  The server under test was written for an older MCP API
#  where Server had a .tool() method.  Monkey-patch it so the module
#  can be imported and the decorator is a transparent pass-through.
# ═════════════════════════════════════════════════════════════════════

import mcp.server  # noqa: E402

_orig_server_cls = mcp.server.Server

if not hasattr(_orig_server_cls, "tool"):
    def _mock_tool(self, *args: Any, **kwargs: Any) -> Any:
        """Pass-through decorator — returns the function unchanged."""
        def decorator(func: Any) -> Any:
            return func
        return decorator

    _orig_server_cls.tool = _mock_tool  # type: ignore[attr-defined]


# Now safe to import the module under test.
import mcp_doudian.server as _srv  # noqa: E402 — the module itself (for patching)

from mcp_doudian.server import (  # noqa: E402
    ConfigError,
    DouDianAPIError,
    get_order_detail,
    get_order_list,
    get_product_list,
    get_refund_list,
    get_shop_info,
    _get_client,
    _safe_get,
    server,
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
        with patch_environ(), patch.object(
            _srv, "_get_client", return_value=mock_client
        ):
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

        with patch_environ(), patch.object(
            _srv, "_get_client", return_value=mock_client
        ):
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

        with patch_environ(), patch.object(
            _srv, "_get_client", return_value=mock_client
        ):
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
        with patch_environ(), patch.object(
            _srv, "_get_client", return_value=mock_client
        ):
            result = await get_order_detail(order_id="ORD-12345")

        mock_client.request.assert_called_once_with(
            "order/detail", {"order_id": "ORD-12345"}
        )

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

        with patch_environ(), patch.object(
            _srv, "_get_client", return_value=mock_client
        ):
            result = await get_order_detail(shop_order_id="SHOP-999")

        assert result["order"]["order_id"] == "ORD-999"
        mock_client.request.assert_called_once_with(
            "order/detail", {"shop_order_id": "SHOP-999"}
        )

    @pytest.mark.asyncio
    async def test_missing_order_id_returns_error(self):
        """Empty order_id and empty shop_order_id returns an error dict."""
        mock_client = make_mock_client({})
        with patch_environ(), patch.object(
            _srv, "_get_client", return_value=mock_client
        ):
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
        with patch_environ(), patch.object(
            _srv, "_get_client", return_value=mock_client
        ):
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
        with patch_environ(), patch.object(
            _srv, "_get_client", return_value=mock_client
        ):
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
        with patch_environ(), patch.object(
            _srv, "_get_client", return_value=mock_client
        ):
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
        with patch_environ(), patch.object(
            _srv, "_get_client", return_value=mock_client
        ):
            await get_refund_list(refund_type="0")

        params = mock_client.request.call_args[0][1]
        assert params["type"] == "0"

    @pytest.mark.asyncio
    async def test_empty_list_when_no_refunds(self):
        """Empty API response returns an empty refunds list."""
        mock_data: dict[str, Any] = {"list": []}
        mock_client = make_mock_client(mock_data)
        with patch_environ(), patch.object(
            _srv, "_get_client", return_value=mock_client
        ):
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
        with patch_environ(), patch.object(
            _srv, "_get_client", return_value=mock_client
        ):
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
        with patch_environ(), patch.object(
            _srv, "_get_client", return_value=mock_client
        ):
            result = await get_shop_info()

        assert result["shop"]["rating"] == "4.5"


class TestAPIErrorHandling:
    """Tests for error handling across all tools."""

    @pytest.mark.asyncio
    async def test_doudian_api_error_caught_in_get_order_list(self):
        """When the API raises DouDianAPIError, the tool returns an error dict."""
        mock_client = make_mock_client({})
        mock_client.request = AsyncMock(
            side_effect=DouDianAPIError(code=40001, msg="Invalid params",
                                        sub_code="40001-1", sub_msg="Missing timestamp")
        )

        with patch_environ(), patch.object(
            _srv, "_get_client", return_value=mock_client
        ):
            result = await get_order_list()

        assert "error" in result
        assert result["code"] == 40001
        assert "Invalid params" in result["error"]
        assert result["orders"] == []

    @pytest.mark.asyncio
    async def test_api_error_in_get_order_detail(self):
        """DouDianAPIError is caught and returned for order detail."""
        mock_client = make_mock_client({})
        mock_client.request = AsyncMock(
            side_effect=DouDianAPIError(code=50000, msg="Server error")
        )

        with patch_environ(), patch.object(
            _srv, "_get_client", return_value=mock_client
        ):
            result = await get_order_detail(order_id="123")

        assert result["error"]
        assert result["code"] == 50000
        assert result["order"] is None

    @pytest.mark.asyncio
    async def test_api_error_in_get_product_list(self):
        """DouDianAPIError is caught for product list."""
        mock_client = make_mock_client({})
        mock_client.request = AsyncMock(
            side_effect=DouDianAPIError(code=40002, msg="Shop not found")
        )

        with patch_environ(), patch.object(
            _srv, "_get_client", return_value=mock_client
        ):
            result = await get_product_list()

        assert result["error"]
        assert result["code"] == 40002
        assert result["products"] == []

    @pytest.mark.asyncio
    async def test_api_error_in_get_refund_list(self):
        """DouDianAPIError is caught for refund list."""
        mock_client = make_mock_client({})
        mock_client.request = AsyncMock(
            side_effect=DouDianAPIError(code=40003, msg="Unauthorized")
        )

        with patch_environ(), patch.object(
            _srv, "_get_client", return_value=mock_client
        ):
            result = await get_refund_list()

        assert result["error"]
        assert result["code"] == 40003
        assert result["refunds"] == []

    @pytest.mark.asyncio
    async def test_api_error_in_get_shop_info(self):
        """DouDianAPIError is caught for shop info."""
        mock_client = make_mock_client({})
        mock_client.request = AsyncMock(
            side_effect=DouDianAPIError(code=40004, msg="Token expired")
        )

        with patch_environ(), patch.object(
            _srv, "_get_client", return_value=mock_client
        ):
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
            import mcp_doudian.server as srv
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
            import mcp_doudian.server as srv
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
            import mcp_doudian.server as srv
            srv._client = None

            result = await get_order_list()

        assert "error" in result
        assert "Missing required environment variables" in result["error"]
        assert result["orders"] == []

    @pytest.mark.asyncio
    async def test_config_error_caught_in_tool_get_shop_info(self):
        """ConfigError is caught in get_shop_info too."""
        with patch.dict(os.environ, {}, clear=True):
            import mcp_doudian.server as srv
            srv._client = None

            result = await get_shop_info()

        assert "error" in result
        assert result["shop"] is None

    @pytest.mark.asyncio
    async def test_config_error_caught_in_tool_get_product_list(self):
        """ConfigError is caught in get_product_list."""
        with patch.dict(os.environ, {}, clear=True):
            import mcp_doudian.server as srv
            srv._client = None

            result = await get_product_list()

        assert "error" in result
        assert result["products"] == []

    @pytest.mark.asyncio
    async def test_config_error_caught_in_tool_get_refund_list(self):
        """ConfigError is caught in get_refund_list."""
        with patch.dict(os.environ, {}, clear=True):
            import mcp_doudian.server as srv
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
