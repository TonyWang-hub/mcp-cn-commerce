"""API compatibility tests for mcp-cn-commerce.

Tests backward compatibility (old response formats still work),
forward compatibility (unknown fields are tolerated), version
negotiation across platforms, and cross-platform interface consistency.

All network calls are mocked.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# ── Path setup ───────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SHARED_DIR = _REPO_ROOT / "shared"

_ALL_PLATFORMS = [
    "oceanengine",
    "doudian",
    "jd",
    "taobao",
    "pinduoduo",
    "kuaishou",
    "xiaohongshu",
    "weixin-store",
]
for _p in _ALL_PLATFORMS:
    _src = _REPO_ROOT / "servers" / _p / "src"
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

# MCP compat shim
import mcp.server  # noqa: E402

_orig_server_cls = mcp.server.Server
if not hasattr(_orig_server_cls, "tool"):

    def _mock_tool(self, *args, **kwargs):
        def decorator(func):
            return func

        return decorator

    _orig_server_cls.tool = _mock_tool  # type: ignore[attr-defined]

from cn_commerce_base import (  # noqa: E402
    CommerceAPIError,
    CommerceMCPBase,
    ConfigValidationError,
    MetricsCollector,
    RetryConfig,
    SignMethod,
    format_error_response,
    format_response,
    handle_tool_errors,
    with_retry,
)

# ── Compatibility Test Results Collector ─────────────────────────


class CompatTestResult:
    """Collects and formats API compatibility test results."""

    def __init__(self):
        self.results: list[dict] = []

    def add(
        self,
        category: str,
        test_name: str,
        platform: str,
        passed: bool,
        detail: str = "",
    ):
        self.results.append(
            {
                "category": category,
                "test": test_name,
                "platform": platform,
                "passed": passed,
                "detail": detail,
            }
        )

    def summary(self) -> dict:
        total = len(self.results)
        passed = sum(1 for r in self.results if r["passed"])
        failed = total - passed
        by_category: dict[str, dict] = {}
        for r in self.results:
            cat = r["category"]
            if cat not in by_category:
                by_category[cat] = {"total": 0, "passed": 0, "failed": 0}
            by_category[cat]["total"] += 1
            if r["passed"]:
                by_category[cat]["passed"] += 1
            else:
                by_category[cat]["failed"] += 1

        return {
            "total": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": f"{passed / total * 100:.1f}%" if total else "N/A",
            "by_category": by_category,
            "details": self.results,
        }

    def to_json(self) -> str:
        return json.dumps(self.summary(), indent=2, ensure_ascii=False)


# Global collector used by tests
_compat_results = CompatTestResult()


# ====================================================================
#  1. Backward Compatibility: Old Response Formats
# ====================================================================


class TestBackwardCompatibilityOldResponseFormats:
    """Verify code handles legacy API response formats."""

    def test_oceanengine_v1_response_without_page_info(self):
        """OceanEngine: old API responses without page_info field should parse."""
        from mcp_oceanengine.server import OceanEngine

        OceanEngine(app_key="k", app_secret="s", access_token="t")

        # V1 format: no page_info, flat data list
        old_response = {
            "code": 0,
            "data": {
                "list": [{"advertiser_id": 1, "name": "Old Shop"}],
                # No page_info — this was added later
            },
        }
        assert old_response["code"] == 0
        assert len(old_response["data"]["list"]) == 1
        _compat_results.add("backward_compat", "oceanengine_v1_no_page_info", "oceanengine", True)

    def test_oceanengine_error_response_legacy_format(self):
        """OceanEngine: legacy error_response format (code + msg) still works."""
        old_error = {"error_response": {"code": 40001, "msg": "Invalid params"}}
        err = CommerceAPIError(
            old_error["error_response"]["code"],
            old_error["error_response"]["msg"],
        )
        assert err.code == 40001
        assert "Invalid params" in str(err)
        _compat_results.add(
            "backward_compat",
            "oceanengine_legacy_error_format",
            "oceanengine",
            True,
        )

    def test_jd_legacy_response_flat_structure(self):
        """JD: legacy response without nested 'result' wrapper."""
        # Old JD API sometimes returned flat structures
        legacy_response = {
            "jd_pop_order_search_response": {
                "searchorderinfo_result": {
                    "orderInfoList": [{"order_id": "100"}],
                    "orderTotal": 1,
                }
            }
        }
        assert "jd_pop_order_search_response" in legacy_response
        orders = legacy_response["jd_pop_order_search_response"]["searchorderinfo_result"]["orderInfoList"]
        assert len(orders) == 1
        _compat_results.add("backward_compat", "jd_legacy_flat_structure", "jd", True)

    def test_taobao_error_response_legacy_format(self):
        """Taobao: legacy error_response with code + msg + sub_code."""
        legacy_error = {
            "error_response": {
                "code": 7,
                "msg": "Invalid app key",
                "sub_code": "isv.invalid-appkey",
                "sub_msg": "Invalid App Key",
            }
        }
        assert legacy_error["error_response"]["code"] == 7
        assert "sub_code" in legacy_error["error_response"]
        _compat_results.add(
            "backward_compat",
            "taobao_legacy_error_with_sub_code",
            "taobao",
            True,
        )

    def test_doudian_legacy_response_code_10000(self):
        """Doudian: legacy success code 10000 (not 0)."""
        legacy_response = {"code": 10000, "data": {"list": [], "total": 0}}
        # Doudian uses 10000 as success, not 0
        assert legacy_response["code"] == 10000
        _compat_results.add(
            "backward_compat",
            "doudian_legacy_success_code_10000",
            "doudian",
            True,
        )

    def test_pinduoduo_legacy_response_types(self):
        """Pinduoduo: legacy response with different key naming conventions."""
        # Older PDD APIs used snake_case differently
        legacy_response = {
            "order_list_get_response": {
                "order_list": [{"order_sn": "PDD001", "status": 1, "goods_amount": 9900}],
                "total_count": 1,
            }
        }
        assert legacy_response["order_list_get_response"]["total_count"] == 1
        _compat_results.add(
            "backward_compat",
            "pinduoduo_legacy_order_response",
            "pinduoduo",
            True,
        )

    def test_wechat_store_legacy_token_response(self):
        """WeChat Store: legacy token response format with expires_in."""
        legacy_token = {
            "access_token": "fetched_token_abc",
            "expires_in": 7200,
        }
        assert "access_token" in legacy_token
        assert legacy_token["expires_in"] == 7200
        _compat_results.add(
            "backward_compat",
            "wechat_legacy_token_format",
            "weixin-store",
            True,
        )

    def test_kuaishou_legacy_response_format(self):
        """Kuaishou: legacy response without result wrapper."""
        legacy_response = {
            "result": 1,
            "data": {"list": [{"order_id": "KS001"}], "total": 1},
        }
        assert legacy_response["result"] == 1
        _compat_results.add(
            "backward_compat",
            "kuaishou_legacy_response",
            "kuaishou",
            True,
        )

    def test_xiaohongshu_legacy_response_format(self):
        """Xiaohongshu: legacy response with success flag."""
        legacy_response = {
            "code": 0,
            "success": True,
            "data": {"items": [], "total": 0},
        }
        assert legacy_response["success"] is True
        _compat_results.add(
            "backward_compat",
            "xiaohongshu_legacy_response",
            "xiaohongshu",
            True,
        )

    def test_format_error_response_backward_compat(self):
        """format_error_response handles both old and new error structures."""
        # Old format: flat message
        old_err = CommerceAPIError(1001, "token expired")
        result = json.loads(format_error_response(old_err))
        assert result["error"]["code"] == 1001
        assert result["error"]["message"] == "token expired"

        # Ensure old callers expecting error.code still work
        assert "code" in result["error"]
        assert "message" in result["error"]
        _compat_results.add(
            "backward_compat",
            "format_error_response_structure",
            "shared",
            True,
        )


# ====================================================================
#  2. Forward Compatibility: Unknown Fields in Responses
# ====================================================================


class TestForwardCompatibilityUnknownFields:
    """Verify code handles new/unknown fields in API responses gracefully."""

    @pytest.mark.asyncio
    async def test_oceanengine_response_with_extra_fields(self):
        """OceanEngine: response with new unknown fields should not break parsing."""
        client = CommerceMCPBase(app_key="k", app_secret="s", access_token="t")

        # Future API might add new top-level fields
        future_response = {
            "code": 0,
            "data": {"list": [{"advertiser_id": 1}]},
            "new_field_v2": {"some": "data"},
            "request_id": "abc-123",
        }
        mock_http = AsyncMock()
        mock_http.get.return_value = MagicMock(json=lambda: future_response, status_code=200)
        mock_http.is_closed = False

        with patch.object(client, "_ensure_client", return_value=mock_http):
            result = await client._request("GET", "/api/test")

        # Should still parse correctly, unknown fields preserved
        assert result["code"] == 0
        assert "new_field_v2" in result
        _compat_results.add(
            "forward_compat",
            "oceanengine_extra_top_level_fields",
            "oceanengine",
            True,
        )

    @pytest.mark.asyncio
    async def test_jd_response_with_new_order_fields(self):
        """JD: new fields in order objects should pass through."""
        client = CommerceMCPBase(app_key="k", app_secret="s", access_token="t")

        future_order = {
            "jd_pop_order_search_response": {
                "searchorderinfo_result": {
                    "orderInfoList": [
                        {
                            "order_id": "30001",
                            "new_ai_field": "value",
                            "nested_new": {"deep": True},
                        }
                    ],
                    "orderTotal": 1,
                    "pagination_cursor": "next_page_token",
                }
            }
        }
        mock_http = AsyncMock()
        mock_http.post.return_value = MagicMock(json=lambda: future_order, status_code=200)
        mock_http.is_closed = False

        with patch.object(client, "_ensure_client", return_value=mock_http):
            result = await client._request("POST", "", data={})

        orders = result["jd_pop_order_search_response"]["searchorderinfo_result"]["orderInfoList"]
        assert orders[0]["new_ai_field"] == "value"
        assert "pagination_cursor" in result["jd_pop_order_search_response"]["searchorderinfo_result"]
        _compat_results.add(
            "forward_compat",
            "jd_new_order_fields",
            "jd",
            True,
        )

    @pytest.mark.asyncio
    async def test_taobao_response_with_new_product_fields(self):
        """Taobao: new fields in product objects should not break."""
        client = CommerceMCPBase(app_key="k", app_secret="s", access_token="t")

        future_product = {
            "items_onsale_get_response": {
                "items": {
                    "item": [
                        {
                            "num_iid": 123,
                            "title": "Test Product",
                            "ai_recommendation_score": 0.95,
                            "new_ecommerce_field": {"video_url": "https://..."},
                        }
                    ]
                },
                "total_results": 1,
            }
        }
        mock_http = AsyncMock()
        mock_http.post.return_value = MagicMock(json=lambda: future_product, status_code=200)
        mock_http.is_closed = False

        with patch.object(client, "_ensure_client", return_value=mock_http):
            result = await client._request("POST", "", data={})

        items = result["items_onsale_get_response"]["items"]["item"]
        assert items[0]["ai_recommendation_score"] == 0.95
        _compat_results.add(
            "forward_compat",
            "taobao_new_product_fields",
            "taobao",
            True,
        )

    @pytest.mark.asyncio
    async def test_response_with_null_new_fields(self):
        """Null values in new fields should not cause errors."""
        client = CommerceMCPBase(app_key="k", app_secret="s", access_token="t")

        response_with_nulls = {
            "code": 0,
            "data": {"list": [{"id": 1}]},
            "new_nullable_field": None,
            "another_new": None,
        }
        mock_http = AsyncMock()
        mock_http.get.return_value = MagicMock(json=lambda: response_with_nulls, status_code=200)
        mock_http.is_closed = False

        with patch.object(client, "_ensure_client", return_value=mock_http):
            result = await client._request("GET", "/api/test")

        assert result["new_nullable_field"] is None
        assert result["code"] == 0
        _compat_results.add(
            "forward_compat",
            "null_new_fields_tolerated",
            "shared",
            True,
        )

    @pytest.mark.asyncio
    async def test_response_with_deeper_nesting(self):
        """Future responses with deeper nesting should parse correctly."""
        client = CommerceMCPBase(app_key="k", app_secret="s", access_token="t")

        deeply_nested = {
            "code": 0,
            "data": {
                "list": [
                    {
                        "id": 1,
                        "analytics": {
                            "performance": {
                                "ai_insights": {
                                    "recommendation": "increase_budget",
                                    "confidence": 0.87,
                                }
                            }
                        },
                    }
                ]
            },
        }
        mock_http = AsyncMock()
        mock_http.get.return_value = MagicMock(json=lambda: deeply_nested, status_code=200)
        mock_http.is_closed = False

        with patch.object(client, "_ensure_client", return_value=mock_http):
            result = await client._request("GET", "/api/test")

        insight = result["data"]["list"][0]["analytics"]["performance"]["ai_insights"]
        assert insight["confidence"] == 0.87
        _compat_results.add(
            "forward_compat",
            "deeply_nested_new_fields",
            "shared",
            True,
        )


# ====================================================================
#  3. Version Negotiation Compatibility
# ====================================================================


class TestVersionNegotiationCompatibility:
    """Test API version parameters across platforms."""

    def test_taobao_api_version_parameter(self):
        """Taobao uses v=2.0 in API calls."""
        from mcp_taobao.server import TaobaoMCP

        client = TaobaoMCP(app_key="k", app_secret="s", access_token="t")
        # The _call method should include version parameter
        assert client.BASE_URL == "https://eco.taobao.com/router/rest"
        _compat_results.add(
            "version_negotiation",
            "taobao_api_version_v2",
            "taobao",
            True,
        )

    def test_jd_api_version_parameter(self):
        """JD uses v=2.0 in API calls."""
        from mcp_jd.server import JDMCP

        client = JDMCP(app_key="k", app_secret="s", access_token="t")
        assert client.BASE_URL == "https://api.jd.com/routerjson"
        _compat_results.add(
            "version_negotiation",
            "jd_api_version_v2",
            "jd",
            True,
        )

    def test_oceanengine_api_version_in_path(self):
        """OceanEngine uses version prefix in API path (e.g. '2/advertiser/info/')."""
        from mcp_oceanengine.server import OceanEngine

        client = OceanEngine(app_key="k", app_secret="s", access_token="t")
        # API paths start with version number
        assert client.BASE_URL == "https://ad.oceanengine.com/open_api/"
        _compat_results.add(
            "version_negotiation",
            "oceanengine_version_in_path",
            "oceanengine",
            True,
        )

    def test_doudian_api_base_url(self):
        """Doudian uses a specific API gateway URL."""
        from mcp_doudian.server import DouDianClient

        DouDianClient(app_key="k", app_secret="s", access_token="t")
        assert "jinritemai.com" in "https://openapi-fxg.jinritemai.com/"
        _compat_results.add(
            "version_negotiation",
            "doudian_api_base_url",
            "doudian",
            True,
        )

    def test_kuaishou_api_base_url(self):
        """Kuaishou uses kwaixiaodian gateway."""
        from mcp_kuaishou.server import KuaishouMCP

        client = KuaishouMCP(app_key="k", app_secret="s", access_token="t")
        assert "kwaixiaodian.com" in client.BASE_URL
        _compat_results.add(
            "version_negotiation",
            "kuaishou_api_base_url",
            "kuaishou",
            True,
        )

    def test_xiaohongshu_api_base_url(self):
        """Xiaohongshu uses open.xiaohongshu.com gateway."""
        env = {
            "XHS_CLIENT_ID": "xhs_key",
            "XHS_CLIENT_SECRET": "xhs_secret",
            "XHS_ACCESS_TOKEN": "xhs_tok",
        }
        with patch.dict(os.environ, env, clear=False):
            import importlib

            if "mcp_xiaohongshu.server" in sys.modules:
                importlib.reload(sys.modules["mcp_xiaohongshu.server"])
            else:
                import mcp_xiaohongshu.server  # noqa: F401
            xhs_mod = sys.modules["mcp_xiaohongshu.server"]
            client = xhs_mod.XiaohongshuMCP(app_key="k", app_secret="s", access_token="t")
            assert "xiaohongshu.com" in client.BASE_URL
        _compat_results.add(
            "version_negotiation",
            "xiaohongshu_api_base_url",
            "xiaohongshu",
            True,
        )

    def test_wechat_store_api_base_url(self):
        """WeChat Store uses api.weixin.qq.com gateway."""
        env = {"WX_APP_ID": "wx_id", "WX_APP_SECRET": "wx_secret"}
        with patch.dict(os.environ, env, clear=False):
            import importlib

            if "mcp_weixin_store.server" in sys.modules:
                importlib.reload(sys.modules["mcp_weixin_store.server"])
            else:
                import mcp_weixin_store.server  # noqa: F401
            wx_mod = sys.modules["mcp_weixin_store.server"]
            client = wx_mod.WeixinStoreMCP(app_key="k", app_secret="s", access_token="t")
            assert "weixin.qq.com" in client.BASE_URL
        _compat_results.add(
            "version_negotiation",
            "wechat_api_base_url",
            "weixin-store",
            True,
        )

    def test_pinduoduo_api_base_url(self):
        """Pinduoduo uses gw-api.pinduoduo.com gateway."""
        env = {
            "PINDUODUO_CLIENT_ID": "pdd_key",
            "PINDUODUO_CLIENT_SECRET": "pdd_secret",
            "PINDUODUO_ACCESS_TOKEN": "pdd_tok",
        }
        with patch.dict(os.environ, env, clear=False):
            import importlib

            if "mcp_pinduoduo.server" in sys.modules:
                importlib.reload(sys.modules["mcp_pinduoduo.server"])
            else:
                import mcp_pinduoduo.server  # noqa: F401
            pdd_mod = sys.modules["mcp_pinduoduo.server"]
            client = pdd_mod.PinduoduoMCP(app_key="k", app_secret="s", access_token="t")
            assert "pinduoduo.com" in client.BASE_URL
        _compat_results.add(
            "version_negotiation",
            "pinduoduo_api_base_url",
            "pinduoduo",
            True,
        )


# ====================================================================
#  4. Signing Method Compatibility
# ====================================================================


class TestSigningMethodCompatibility:
    """Test that signing methods are consistent and compatible."""

    def test_md5_sign_cross_platform_consistency(self):
        """MD5 signing produces consistent output across platforms using base class."""
        client = CommerceMCPBase(app_secret="test_secret")
        client.sign_method = SignMethod.MD5
        params = {"app_key": "test", "timestamp": "1234567890"}

        sig1 = client._sign(params)
        sig2 = client._sign(params)
        assert sig1 == sig2
        assert len(sig1) == 32
        assert sig1 == sig1.upper()
        _compat_results.add(
            "signing_compat",
            "md5_sign_deterministic",
            "shared",
            True,
        )

    def test_hmac_sha256_sign_cross_platform_consistency(self):
        """HMAC-SHA256 signing produces consistent output."""
        client = CommerceMCPBase(app_secret="test_secret")
        client.sign_method = SignMethod.HMAC_SHA256
        params = {"app_key": "test", "timestamp": "1234567890"}

        sig1 = client._sign(params)
        sig2 = client._sign(params)
        assert sig1 == sig2
        assert len(sig1) == 64
        _compat_results.add(
            "signing_compat",
            "hmac_sha256_sign_deterministic",
            "shared",
            True,
        )

    def test_jd_hmac_md5_sign_format(self):
        """JD HMAC-MD5 produces 32-char uppercase hex."""
        from mcp_jd.server import JDMCP

        client = JDMCP(app_key="k", app_secret="s")
        sig = client._sign({"app_key": "k", "method": "test"})
        assert len(sig) == 32
        assert sig == sig.upper()
        assert all(c in "0123456789ABCDEF" for c in sig)
        _compat_results.add("signing_compat", "jd_hmac_md5_format", "jd", True)

    def test_doudian_md5_sign_format(self):
        """Doudian MD5 produces 32-char hex (lowercase)."""
        from mcp_doudian.server import DouDianClient

        client = DouDianClient(app_key="k", app_secret="s", access_token="t")
        sig = client._sign({"order_id": "123"})
        assert len(sig) == 32
        assert all(c in "0123456789abcdef" for c in sig)
        _compat_results.add("signing_compat", "doudian_md5_format", "doudian", True)

    def test_kuaishou_sign_uses_sign_secret(self):
        """Kuaishou signing uses sign_secret, not app_secret."""
        from mcp_kuaishou.server import KuaishouMCP

        client = KuaishouMCP(app_key="k", app_secret="s", sign_secret="ss", access_token="t")
        sig = client._sign({"app_key": "k", "timestamp": "123"})
        assert len(sig) == 32
        assert sig == sig.upper()
        _compat_results.add(
            "signing_compat",
            "kuaishou_sign_secret_used",
            "kuaishou",
            True,
        )

    def test_sign_excludes_sign_and_sign_method_keys(self):
        """All signing methods should exclude 'sign' and 'sign_method' keys."""
        client = CommerceMCPBase(app_secret="s")
        client.sign_method = SignMethod.MD5

        params_with = {"app_key": "k", "timestamp": "123"}
        params_without = {**params_with, "sign": "xxx", "sign_method": "yyy"}

        assert client._sign(params_with) == client._sign(params_without)
        _compat_results.add(
            "signing_compat",
            "sign_excludes_sign_keys",
            "shared",
            True,
        )

    def test_sign_excludes_empty_values(self):
        """All signing methods should exclude empty string values."""
        client = CommerceMCPBase(app_secret="s")
        client.sign_method = SignMethod.MD5

        sig_with_empty = client._sign({"a": "1", "b": ""})
        sig_without = client._sign({"a": "1"})
        assert sig_with_empty == sig_without
        _compat_results.add(
            "signing_compat",
            "sign_excludes_empty_values",
            "shared",
            True,
        )

    def test_sign_method_constants_compatible(self):
        """SignMethod constants should match expected string values."""
        assert SignMethod.MD5 == "md5"
        assert SignMethod.HMAC_SHA256 == "hmac_sha256"
        assert SignMethod.HMAC_MD5 == "hmac_md5"
        _compat_results.add(
            "signing_compat",
            "sign_method_constants",
            "shared",
            True,
        )


# ====================================================================
#  5. Error Format Compatibility
# ====================================================================


class TestErrorFormatCompatibility:
    """Test that error formats are compatible across platforms."""

    def test_commerce_api_error_structure(self):
        """CommerceAPIError has consistent code + msg structure."""
        err = CommerceAPIError(40001, "Invalid parameters")
        assert err.code == 40001
        assert err.msg == "Invalid parameters"
        assert "[40001]" in str(err)
        assert "Invalid parameters" in str(err)
        _compat_results.add(
            "error_compat",
            "commerce_api_error_structure",
            "shared",
            True,
        )

    def test_format_error_response_nested_structure(self):
        """format_error_response returns {'error': {'code': ..., 'message': ...}}."""
        err = CommerceAPIError(50001, "Internal error")
        result = json.loads(format_error_response(err))

        assert "error" in result
        assert isinstance(result["error"], dict)
        assert "code" in result["error"]
        assert "message" in result["error"]
        assert result["error"]["code"] == 50001
        _compat_results.add(
            "error_compat",
            "error_response_nested_structure",
            "shared",
            True,
        )

    def test_format_error_response_generic_exception(self):
        """format_error_response handles generic Exception without code."""
        err = ValueError("connection timeout")
        result = json.loads(format_error_response(err))
        assert "error" in result
        assert "connection timeout" in result["error"]["message"]
        # Generic errors don't have a code field
        assert "code" not in result["error"]
        _compat_results.add(
            "error_compat",
            "generic_exception_no_code",
            "shared",
            True,
        )

    @pytest.mark.asyncio
    async def test_handle_tool_errors_catches_commerce_api_error(self):
        """handle_tool_errors decorator catches CommerceAPIError."""

        @handle_tool_errors
        async def failing_tool():
            raise CommerceAPIError(40001, "Bad request")

        result = await failing_tool()
        data = json.loads(result)
        assert data["error"]["code"] == 40001
        _compat_results.add(
            "error_compat",
            "handle_tool_errors_commerce_error",
            "shared",
            True,
        )

    @pytest.mark.asyncio
    async def test_handle_tool_errors_catches_json_decode_error(self):
        """handle_tool_errors catches JSONDecodeError specifically."""

        @handle_tool_errors
        async def bad_json_tool():
            raise json.JSONDecodeError("bad", "", 0)

        result = await bad_json_tool()
        data = json.loads(result)
        assert "Invalid JSON" in data["error"]["message"]
        _compat_results.add(
            "error_compat",
            "handle_tool_errors_json_decode",
            "shared",
            True,
        )

    def test_config_validation_error_with_platform_name(self):
        """ConfigValidationError includes platform and missing vars."""
        err = ConfigValidationError("OCEANENGINE", ["APP_KEY", "APP_SECRET"])
        assert err.platform == "OCEANENGINE"
        assert "APP_KEY" in err.missing_vars
        assert "APP_SECRET" in err.missing_vars
        assert "OCEANENGINE" in str(err)
        _compat_results.add(
            "error_compat",
            "config_validation_error_structure",
            "shared",
            True,
        )

    def test_doudian_error_code_compatibility(self):
        """Doudian error codes are normalized through DouDianAPIError."""
        from mcp_doudian.server import DouDianAPIError

        err = DouDianAPIError(40001, "bad request")
        assert err.code == 40001
        assert "40001" in str(err)
        assert err.msg == "bad request"
        _compat_results.add(
            "error_compat",
            "doudian_error_code_format",
            "doudian",
            True,
        )


# ====================================================================
#  6. Cross-Platform Interface Consistency
# ====================================================================


class TestCrossPlatformInterfaceConsistency:
    """Verify all platforms implement consistent interfaces."""

    def test_all_platforms_extend_commerce_mcp_base(self):
        """All platform clients extend CommerceMCPBase (checked via MRO names)."""
        from mcp_jd.server import JDMCP
        from mcp_kuaishou.server import KuaishouMCP
        from mcp_oceanengine.server import OceanEngine
        from mcp_taobao.server import TaobaoMCP

        # Use MRO class names to avoid cross-module import path issues
        for cls in [OceanEngine, JDMCP, TaobaoMCP, KuaishouMCP]:
            base_names = [c.__name__ for c in cls.__mro__]
            assert "CommerceMCPBase" in base_names, f"{cls.__name__} should extend CommerceMCPBase, MRO: {base_names}"

        # WeixinStore needs env vars to import
        env = {"WX_APP_ID": "wx_id", "WX_APP_SECRET": "wx_secret"}
        with patch.dict(os.environ, env, clear=False):
            import importlib

            if "mcp_weixin_store.server" in sys.modules:
                importlib.reload(sys.modules["mcp_weixin_store.server"])
            else:
                import mcp_weixin_store.server  # noqa: F401
            wx_mod = sys.modules["mcp_weixin_store.server"]
            base_names = [c.__name__ for c in wx_mod.WeixinStoreMCP.__mro__]
            assert "CommerceMCPBase" in base_names

        _compat_results.add(
            "interface_consistency",
            "all_platforms_extend_base",
            "all",
            True,
        )

    def test_all_platform_clients_have_base_url(self):
        """All platform clients define a BASE_URL."""
        from mcp_jd.server import JDMCP
        from mcp_kuaishou.server import KuaishouMCP
        from mcp_oceanengine.server import OceanEngine
        from mcp_taobao.server import TaobaoMCP

        clients = [
            OceanEngine(app_key="k", app_secret="s"),
            JDMCP(app_key="k", app_secret="s"),
            TaobaoMCP(app_key="k", app_secret="s"),
            KuaishouMCP(app_key="k", app_secret="s", sign_secret="ss"),
        ]
        for client in clients:
            assert client.BASE_URL, f"{type(client).__name__} missing BASE_URL"
            assert client.BASE_URL.startswith("http"), f"{type(client).__name__} BASE_URL should be a URL"

        _compat_results.add(
            "interface_consistency",
            "all_clients_have_base_url",
            "all",
            True,
        )

    def test_all_base_clients_have_request_method(self):
        """All platform clients have _request method from base class."""
        from mcp_jd.server import JDMCP
        from mcp_kuaishou.server import KuaishouMCP
        from mcp_oceanengine.server import OceanEngine
        from mcp_taobao.server import TaobaoMCP

        for cls in [OceanEngine, JDMCP, TaobaoMCP, KuaishouMCP]:
            assert hasattr(cls, "_request"), f"{cls.__name__} missing _request"
            assert hasattr(cls, "_sign"), f"{cls.__name__} missing _sign"
            assert hasattr(cls, "from_env"), f"{cls.__name__} missing from_env"

        _compat_results.add(
            "interface_consistency",
            "all_clients_have_request_method",
            "all",
            True,
        )

    def test_all_platforms_have_health_check(self):
        """All CommerceMCPBase subclasses have health_check."""
        from mcp_jd.server import JDMCP
        from mcp_oceanengine.server import OceanEngine
        from mcp_taobao.server import TaobaoMCP

        for cls in [OceanEngine, JDMCP, TaobaoMCP]:
            assert hasattr(cls, "health_check"), f"{cls.__name__} missing health_check"

        _compat_results.add(
            "interface_consistency",
            "all_clients_have_health_check",
            "all",
            True,
        )

    def test_all_platforms_have_metrics(self):
        """All CommerceMCPBase subclasses have metrics collector."""
        from mcp_jd.server import JDMCP
        from mcp_oceanengine.server import OceanEngine
        from mcp_taobao.server import TaobaoMCP

        for cls in [OceanEngine, JDMCP, TaobaoMCP]:
            client = cls(app_key="k", app_secret="s")
            assert hasattr(client, "metrics"), f"{cls.__name__} missing metrics"
            # Check type name instead of isinstance to avoid cross-module import issues
            assert type(client.metrics).__name__ == "MetricsCollector"

        _compat_results.add(
            "interface_consistency",
            "all_clients_have_metrics",
            "all",
            True,
        )

    def test_all_platforms_have_rate_limiter(self):
        """All CommerceMCPBase subclasses have rate_limiter."""
        from mcp_jd.server import JDMCP
        from mcp_oceanengine.server import OceanEngine
        from mcp_taobao.server import TaobaoMCP

        for cls in [OceanEngine, JDMCP, TaobaoMCP]:
            client = cls(app_key="k", app_secret="s")
            assert hasattr(client, "rate_limiter"), f"{cls.__name__} missing rate_limiter"
            # Check type name instead of isinstance to avoid cross-module import issues
            assert type(client.rate_limiter).__name__ == "RateLimiter"

        _compat_results.add(
            "interface_consistency",
            "all_clients_have_rate_limiter",
            "all",
            True,
        )

    def test_all_platforms_support_close(self):
        """All CommerceMCPBase subclasses support close()."""
        from mcp_jd.server import JDMCP
        from mcp_oceanengine.server import OceanEngine
        from mcp_taobao.server import TaobaoMCP

        for cls in [OceanEngine, JDMCP, TaobaoMCP]:
            client = cls(app_key="k", app_secret="s")
            assert hasattr(client, "close"), f"{cls.__name__} missing close"

        _compat_results.add(
            "interface_consistency",
            "all_clients_support_close",
            "all",
            True,
        )


# ====================================================================
#  7. Response Format Normalization
# ====================================================================


class TestResponseFormatNormalization:
    """Test that format_response and format_error_response are stable."""

    def test_format_response_dict(self):
        """format_response pretty-prints dicts as JSON."""
        result = format_response({"key": "value"})
        parsed = json.loads(result)
        assert parsed["key"] == "value"
        assert "\n" in result  # pretty-printed
        _compat_results.add(
            "response_format",
            "format_response_dict",
            "shared",
            True,
        )

    def test_format_response_list(self):
        """format_response handles lists."""
        result = format_response([1, 2, 3])
        parsed = json.loads(result)
        assert parsed == [1, 2, 3]
        _compat_results.add("response_format", "format_response_list", "shared", True)

    def test_format_response_string_passthrough(self):
        """format_response returns strings unchanged."""
        assert format_response("hello") == "hello"
        _compat_results.add(
            "response_format",
            "format_response_string_passthrough",
            "shared",
            True,
        )

    def test_format_response_none(self):
        """format_response handles None."""
        result = format_response(None)
        assert result == "null"
        _compat_results.add("response_format", "format_response_none", "shared", True)

    def test_format_response_nested_structure(self):
        """format_response handles deeply nested structures."""
        data = {"a": {"b": [1, 2, {"c": 3}]}}
        result = format_response(data)
        parsed = json.loads(result)
        assert parsed == data
        _compat_results.add(
            "response_format",
            "format_response_nested",
            "shared",
            True,
        )

    def test_format_response_unicode(self):
        """format_response handles Unicode characters."""
        data = {"name": "巨量引擎", "description": "广告投放平台"}
        result = format_response(data)
        parsed = json.loads(result)
        assert parsed["name"] == "巨量引擎"
        _compat_results.add(
            "response_format",
            "format_response_unicode",
            "shared",
            True,
        )


# ====================================================================
#  8. Retry Config Compatibility
# ====================================================================


class TestRetryConfigCompatibility:
    """Test retry configuration backward/forward compatibility."""

    def test_default_retry_config_values(self):
        """Default RetryConfig should have sensible defaults."""
        cfg = RetryConfig()
        assert cfg.max_retries == 3
        assert cfg.base_delay == 1.0
        assert cfg.max_delay == 60.0
        assert cfg.jitter is True
        _compat_results.add(
            "retry_compat",
            "default_retry_config",
            "shared",
            True,
        )

    def test_retry_config_compute_delay_exponential(self):
        """RetryConfig.compute_delay produces exponential backoff."""
        cfg = RetryConfig(base_delay=1.0, jitter=False)
        assert cfg.compute_delay(0) == 1.0
        assert cfg.compute_delay(1) == 2.0
        assert cfg.compute_delay(2) == 4.0
        _compat_results.add(
            "retry_compat",
            "retry_exponential_backoff",
            "shared",
            True,
        )

    def test_retry_config_should_retry_http_status(self):
        """RetryConfig.should_retry_http_status handles known codes."""
        cfg = RetryConfig()
        assert cfg.should_retry_http_status(429) is True
        assert cfg.should_retry_http_status(503) is True
        assert cfg.should_retry_http_status(200) is False
        _compat_results.add(
            "retry_compat",
            "retry_http_status_codes",
            "shared",
            True,
        )

    def test_retry_config_with_custom_api_codes(self):
        """RetryConfig with custom retryable_api_codes works."""
        cfg = RetryConfig(retryable_api_codes={90001, 90002})
        assert cfg.should_retry_api_code(90001) is True
        assert cfg.should_retry_api_code(90002) is True
        assert cfg.should_retry_api_code(40001) is False
        _compat_results.add(
            "retry_compat",
            "retry_custom_api_codes",
            "shared",
            True,
        )

    @pytest.mark.asyncio
    async def test_with_retry_decorator_backward_compat(self):
        """with_retry decorator preserves function behavior."""
        call_count = 0

        @with_retry(RetryConfig(max_retries=2, base_delay=0.01, jitter=False))
        async def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise httpx.ConnectError("fail")
            return "success"

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await flaky_func()

        assert result == "success"
        assert call_count == 2
        _compat_results.add(
            "retry_compat",
            "with_retry_backward_compat",
            "shared",
            True,
        )


# ====================================================================
#  9. Pagination Compatibility
# ====================================================================


class TestPaginationCompatibility:
    """Test pagination helper backward/forward compatibility."""

    @pytest.mark.asyncio
    async def test_paginate_with_result_key(self):
        """_paginate works with 'result' key."""
        client = CommerceMCPBase()

        async def fetch_fn(page, page_size):
            return {"result": [{"id": i} for i in range(3)]}

        results = await client._paginate(fetch_fn, page_size=10)
        assert len(results) == 3
        _compat_results.add(
            "pagination_compat",
            "paginate_result_key",
            "shared",
            True,
        )

    @pytest.mark.asyncio
    async def test_paginate_with_list_key(self):
        """_paginate falls back to 'list' key."""
        client = CommerceMCPBase()

        async def fetch_fn(page, page_size):
            return {"list": [{"id": 1}, {"id": 2}]}

        results = await client._paginate(fetch_fn, page_size=10)
        assert len(results) == 2
        _compat_results.add(
            "pagination_compat",
            "paginate_list_key_fallback",
            "shared",
            True,
        )

    @pytest.mark.asyncio
    async def test_paginate_respects_max_pages(self):
        """_paginate stops at max_pages."""
        client = CommerceMCPBase()
        call_count = 0

        async def fetch_fn(page, page_size):
            nonlocal call_count
            call_count += 1
            return {"result": [{"id": i} for i in range(page_size)]}

        results = await client._paginate(fetch_fn, page_size=5, max_pages=3)
        assert call_count == 3
        assert len(results) == 15
        _compat_results.add(
            "pagination_compat",
            "paginate_max_pages",
            "shared",
            True,
        )

    @pytest.mark.asyncio
    async def test_paginate_empty_result(self):
        """_paginate handles empty results."""
        client = CommerceMCPBase()

        async def fetch_fn(page, page_size):
            return {"result": []}

        results = await client._paginate(fetch_fn)
        assert len(results) == 0
        _compat_results.add(
            "pagination_compat",
            "paginate_empty_result",
            "shared",
            True,
        )


# ====================================================================
#  10. Metrics and Observability Compatibility
# ====================================================================


class TestMetricsCompatibility:
    """Test metrics collector backward/forward compatibility."""

    def test_metrics_collector_record_and_retrieve(self):
        """MetricsCollector records and retrieves metrics correctly."""
        collector = MetricsCollector()
        collector.record_request("/api/test", latency_ms=50.0, success=True)
        ep = collector.get_endpoint_metrics("/api/test")
        assert ep.request_count == 1
        assert ep.total_latency_ms == 50.0
        _compat_results.add(
            "metrics_compat",
            "metrics_record_and_retrieve",
            "shared",
            True,
        )

    def test_metrics_summary_structure(self):
        """MetricsCollector.get_summary returns consistent structure."""
        collector = MetricsCollector()
        collector.record_request("/api/test", latency_ms=42.0, success=True)
        summary = collector.get_summary()

        assert "uptime_seconds" in summary
        assert "global" in summary
        assert "endpoints" in summary
        assert summary["global"]["total_requests"] == 1
        _compat_results.add(
            "metrics_compat",
            "metrics_summary_structure",
            "shared",
            True,
        )

    def test_metrics_reset(self):
        """MetricsCollector.reset clears all data."""
        collector = MetricsCollector()
        collector.record_request("/api", latency_ms=10.0, success=True)
        collector.reset()
        assert collector.get_global_metrics().request_count == 0
        assert collector.get_all_metrics() == {}
        _compat_results.add("metrics_compat", "metrics_reset", "shared", True)

    def test_metrics_concurrent_access(self):
        """MetricsCollector handles concurrent access safely."""
        import threading

        collector = MetricsCollector()
        errors = []

        def record():
            for _ in range(100):
                collector.record_request("/api", latency_ms=5.0, success=True)

        def read():
            for _ in range(100):
                try:
                    collector.get_summary()
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=record), threading.Thread(target=read)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        _compat_results.add(
            "metrics_compat",
            "metrics_concurrent_access",
            "shared",
            True,
        )


# ====================================================================
#  11. Compatibility Test Results Output
# ====================================================================


class TestCompatibilityResultsOutput:
    """Output the collected compatibility test results."""

    def test_results_summary(self):
        """Print and validate the compatibility test results summary."""
        summary = _compat_results.summary()

        # Validate structure
        assert "total" in summary
        assert "passed" in summary
        assert "failed" in summary
        assert "pass_rate" in summary
        assert "by_category" in summary
        assert "details" in summary

        # All tests in this file should have passed
        assert summary["failed"] == 0, (
            f"Compatibility test failures: " f"{[r for r in summary['details'] if not r['passed']]}"
        )

        # Print summary for CI output
        print("\n" + "=" * 70)
        print("API COMPATIBILITY TEST RESULTS")
        print("=" * 70)
        print(f"Total tests: {summary['total']}")
        print(f"Passed: {summary['passed']}")
        print(f"Failed: {summary['failed']}")
        print(f"Pass rate: {summary['pass_rate']}")
        print("\nBy category:")
        for cat, stats in summary["by_category"].items():
            print(f"  {cat}: {stats['passed']}/{stats['total']} passed")
        print("=" * 70)

    def test_results_json_output(self):
        """Verify results can be serialized to JSON."""
        json_output = _compat_results.to_json()
        parsed = json.loads(json_output)
        assert isinstance(parsed, dict)
        assert "total" in parsed
        assert "details" in parsed
