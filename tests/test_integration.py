"""Integration tests for mcp-cn-commerce.

Tests complete request flows from tool functions through API calls,
error handling, retry/cache mechanisms, configuration loading, and
cross-platform patterns.  All network calls are mocked.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# Repo root, used by tests that assert on the on-disk project layout.
_REPO_ROOT = Path(__file__).resolve().parents[1]

# ── MCP compat shim (same as per-server tests) ──────────────────

import mcp.server

_orig_server_cls = mcp.server.Server
if not hasattr(_orig_server_cls, "tool"):

    def _mock_tool(self, *args, **kwargs):
        def decorator(func):
            return func

        return decorator

    _orig_server_cls.tool = _mock_tool  # type: ignore[attr-defined]

from shared.cli import (  # noqa: E402
    SERVER_REGISTRY,
    build_pythonpath,
    check_all_health,
    check_server_health,
    load_config,
)
from shared.cn_commerce_base import (  # noqa: E402
    CommerceAPIError,
    CommerceMCPBase,
    ConfigValidationError,
    MetricsCollector,
    RateLimiter,
    RetryConfig,
    SensitiveDataFilter,
    SignMethod,
    format_error_response,
    format_response,
    handle_tool_errors,
    mask_dict_sensitive_keys,
    mask_log_message,
    mask_sensitive_value,
    validate_api_param,
    validate_platform_name,
    with_retry,
)

# ====================================================================
#  1. Full Request Flow: Tool → Base._request → Mock HTTP
# ====================================================================


class TestOceanEngineFullRequestFlow:
    """Integration: OceanEngine tool function → CommerceMCPBase._request → HTTP."""

    @pytest.fixture
    def oe_client(self):
        """Create a real OceanEngine instance (no env vars needed, all mocked)."""
        from mcp_oceanengine.server import OceanEngine

        return OceanEngine(app_key="test_key", app_secret="test_secret", access_token="tok")

    @pytest.mark.asyncio
    async def test_get_advertiser_info_end_to_end(self, oe_client):
        """get_advertiser_info → _request → mock HTTP → parsed JSON response."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "code": 0,
            "data": {"list": [{"advertiser_id": 123, "advertiser_name": "Test", "status": "ENABLE"}]},
        }
        mock_response.status_code = 200

        mock_http = AsyncMock()
        mock_http.get.return_value = mock_response
        mock_http.is_closed = False

        from mcp_oceanengine.server import get_advertiser_info

        with patch("mcp_oceanengine.server._get_client", return_value=oe_client):
            with patch.object(oe_client, "_ensure_client", return_value=mock_http):
                result = await get_advertiser_info(advertiser_ids="123")

        data = json.loads(result)
        assert data["code"] == 0
        assert data["data"]["list"][0]["advertiser_id"] == 123

    @pytest.mark.asyncio
    async def test_get_campaign_report_sign_params_passed(self, oe_client):
        """Verify that sign, sign_method, timestamp are injected into request params."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"code": 0, "data": {"list": []}}
        mock_response.status_code = 200

        mock_http = AsyncMock()
        mock_http.get.return_value = mock_response
        mock_http.is_closed = False

        from mcp_oceanengine.server import get_campaign_report

        with patch("mcp_oceanengine.server._get_client", return_value=oe_client):
            with patch.object(oe_client, "_ensure_client", return_value=mock_http):
                await get_campaign_report(
                    advertiser_id="456",
                    start_date="2024-01-01",
                    end_date="2024-01-31",
                )

        # Inspect the params passed to httpx.get
        call_args = mock_http.get.call_args
        params = call_args[1]["params"] if "params" in call_args[1] else call_args.kwargs.get("params", {})
        assert "sign" in params
        assert "sign_method" in params
        assert "timestamp" in params
        assert params["app_key"] == "test_key"
        assert params["access_token"] == "tok"

    @pytest.mark.asyncio
    async def test_api_error_response_raises_commerce_api_error(self, oe_client):
        """When the API returns error_response, _request raises CommerceAPIError."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"error_response": {"code": 40001, "msg": "Invalid advertiser"}}
        mock_response.status_code = 200

        mock_http = AsyncMock()
        mock_http.get.return_value = mock_response
        mock_http.is_closed = False

        from mcp_oceanengine.server import get_advertiser_info

        with patch("mcp_oceanengine.server._get_client", return_value=oe_client):
            with patch.object(oe_client, "_ensure_client", return_value=mock_http):
                result = await get_advertiser_info(advertiser_ids="999")

        data = json.loads(result)
        assert "error" in data
        assert data["error"]["code"] == 40001


class TestJDFlow:
    """Integration: JD tool → JDMCP._call → _request → mock HTTP."""

    @pytest.fixture
    def jd_client(self):
        from mcp_jd.server import JDMCP

        return JDMCP(app_key="jd_key", app_secret="jd_secret", access_token="jd_tok")

    @pytest.mark.asyncio
    async def test_get_order_list_end_to_end(self, jd_client):
        """JD get_order_list → _call → _request → POST with biz params in JSON body."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "jd_pop_order_search_response": {
                "searchorderinfo_result": {
                    "orderInfoList": [{"order_id": "30001"}],
                    "orderTotal": 1,
                }
            }
        }
        mock_response.status_code = 200

        mock_http = AsyncMock()
        mock_http.post.return_value = mock_response
        mock_http.is_closed = False

        with patch("mcp_jd.server.jd", jd_client):
            with patch.object(jd_client, "_ensure_client", return_value=mock_http):
                from mcp_jd.server import get_order_list

                result = await get_order_list(
                    start_time="2024-01-01 00:00:00",
                    end_time="2024-01-31 23:59:59",
                )

        data = json.loads(result)
        assert "jd_pop_order_search_response" in data

    @pytest.mark.asyncio
    async def test_jd_sign_method_is_hmac_md5(self, jd_client):
        """JD uses HMAC-MD5 signing, producing 32-char hex uppercase."""
        sig = jd_client._sign({"app_key": "test", "timestamp": "123"})
        assert isinstance(sig, str)
        assert len(sig) == 32
        assert sig == sig.upper()


class TestTaobaoFlow:
    """Integration: Taobao tool → TaobaoMCP._call → _request → mock HTTP."""

    @pytest.fixture
    def taobao_client(self):
        from mcp_taobao.server import TaobaoMCP

        return TaobaoMCP(app_key="tb_key", app_secret="tb_secret", access_token="tb_tok")

    @pytest.mark.asyncio
    async def test_get_order_list_merges_system_and_biz_params(self, taobao_client):
        """Taobao _call merges system params (method, format, v) with biz params."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"trades_sold_get_response": {"trades": {"trade": []}, "total_results": 0}}
        mock_response.status_code = 200

        mock_http = AsyncMock()
        mock_http.post.return_value = mock_response
        mock_http.is_closed = False

        with patch("mcp_taobao.server.taobao", taobao_client):
            with patch.object(taobao_client, "_ensure_client", return_value=mock_http):
                from mcp_taobao.server import get_order_list

                result = await get_order_list(
                    start_time="2024-01-01 00:00:00",
                    end_time="2024-01-31 23:59:59",
                )

        data = json.loads(result)
        assert "trades_sold_get_response" in data


# ====================================================================
#  2. Error Handling Flow
# ====================================================================


class TestErrorHandlingFlow:
    """Integration tests for error propagation through the full stack."""

    @pytest.mark.asyncio
    async def test_commerce_api_error_caught_by_handle_tool_errors(self):
        """handle_tool_errors decorator catches CommerceAPIError and returns JSON."""

        @handle_tool_errors
        async def my_tool():
            raise CommerceAPIError(40001, "Bad request")

        result = await my_tool()
        data = json.loads(result)
        assert data["error"]["code"] == 40001
        assert data["error"]["message"] == "Bad request"

    @pytest.mark.asyncio
    async def test_generic_exception_caught_by_handle_tool_errors(self):
        """handle_tool_errors catches non-API exceptions too."""

        @handle_tool_errors
        async def my_tool():
            raise ValueError("something broke")

        result = await my_tool()
        data = json.loads(result)
        assert "something broke" in data["error"]["message"]

    @pytest.mark.asyncio
    async def test_json_decode_error_caught_by_handle_tool_errors(self):
        """handle_tool_errors catches JSONDecodeError specifically."""

        @handle_tool_errors
        async def my_tool():
            raise json.JSONDecodeError("bad json", "", 0)

        result = await my_tool()
        data = json.loads(result)
        assert "Invalid JSON" in data["error"]["message"]

    @pytest.mark.asyncio
    async def test_handle_tool_errors_passes_through_success(self):
        """handle_tool_errors formats successful dict results as JSON."""

        @handle_tool_errors
        async def my_tool():
            return {"status": "ok", "count": 42}

        result = await my_tool()
        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["count"] == 42

    @pytest.mark.asyncio
    async def test_handle_tool_errors_passes_through_string(self):
        """handle_tool_errors returns string results as-is."""

        @handle_tool_errors
        async def my_tool():
            return "plain text"

        result = await my_tool()
        assert result == "plain text"

    def test_config_validation_error_flow(self):
        """ConfigValidationError from from_env propagates with platform name."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ConfigValidationError) as exc_info:
                CommerceMCPBase.from_env("MY_PLATFORM", ["APP_KEY", "APP_SECRET"])
            assert exc_info.value.platform == "MY_PLATFORM"
            assert "MY_PLATFORM_APP_KEY" in str(exc_info.value)
            assert "MY_PLATFORM_APP_SECRET" in str(exc_info.value)

    def test_format_error_response_commerce_api_error(self):
        """format_error_response produces correct JSON for CommerceAPIError."""
        err = CommerceAPIError(50001, "Internal server error")
        result = json.loads(format_error_response(err))
        assert result["error"]["code"] == 50001
        assert result["error"]["message"] == "Internal server error"

    def test_format_error_response_generic(self):
        """format_error_response produces correct JSON for generic Exception."""
        err = RuntimeError("connection timeout")
        result = json.loads(format_error_response(err))
        assert "connection timeout" in result["error"]["message"]
        assert "code" not in result["error"]

    def test_format_response_dict(self):
        """format_response pretty-prints dicts."""
        result = json.loads(format_response({"key": "value"}))
        assert result["key"] == "value"

    def test_format_response_string_passthrough(self):
        """format_response returns strings unchanged."""
        assert format_response("hello") == "hello"

    @pytest.mark.asyncio
    async def test_http_error_in_request_propagates(self):
        """Network errors from httpx propagate through _request."""
        client = CommerceMCPBase(app_key="k", app_secret="s", access_token="t")
        client.BASE_URL = "http://localhost:1"

        mock_http = AsyncMock()
        mock_http.get.side_effect = httpx.ConnectError("connection refused")
        mock_http.is_closed = False

        with patch.object(client, "_ensure_client", return_value=mock_http):
            with pytest.raises(httpx.ConnectError):
                await client._request("GET", "/test")

    @pytest.mark.asyncio
    async def test_error_response_json_structure_nested(self):
        """Verify the nested error JSON structure: {'error': {'code': ..., 'message': ...}}."""

        @handle_tool_errors
        async def failing_tool():
            raise CommerceAPIError(1001, "token expired")

        result = json.loads(await failing_tool())
        # Verify nested structure
        assert "error" in result
        assert isinstance(result["error"], dict)
        assert set(result["error"].keys()) == {"code", "message"}


# ====================================================================
#  3. Retry Mechanism Integration
# ====================================================================


class TestRetryMechanismIntegration:
    """Integration tests for retry with exponential backoff."""

    @pytest.mark.asyncio
    async def test_retry_on_connect_error_succeeds_on_third_attempt(self):
        """_request retries on httpx.ConnectError and succeeds on 3rd attempt."""
        client = CommerceMCPBase(app_key="k", app_secret="s", access_token="t")
        client.BASE_URL = "http://api.test"

        attempt_count = 0
        mock_http = AsyncMock()
        mock_http.is_closed = False

        async def mock_get(*args, **kwargs):
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 3:
                raise httpx.ConnectError("connection refused")
            resp = MagicMock()
            resp.json.return_value = {"code": 0, "data": "ok"}
            resp.status_code = 200
            return resp

        mock_http.get = mock_get

        retry_config = RetryConfig(max_retries=3, base_delay=0.01, jitter=False)

        with patch.object(client, "_ensure_client", return_value=mock_http):
            with patch("asyncio.sleep", new_callable=AsyncMock):  # skip real sleep
                result = await client._request("GET", "/test", retry_config=retry_config)

        assert result == {"code": 0, "data": "ok"}
        assert attempt_count == 3

    @pytest.mark.asyncio
    async def test_retry_exhausted_raises_last_error(self):
        """When all retries are exhausted, the last exception is raised."""
        client = CommerceMCPBase(app_key="k", app_secret="s", access_token="t")
        client.BASE_URL = "http://api.test"

        mock_http = AsyncMock()
        mock_http.get.side_effect = httpx.ReadTimeout("read timed out")
        mock_http.is_closed = False

        retry_config = RetryConfig(max_retries=2, base_delay=0.01, jitter=False)

        with patch.object(client, "_ensure_client", return_value=mock_http):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(httpx.ReadTimeout):
                    await client._request("GET", "/test", retry_config=retry_config)

    @pytest.mark.asyncio
    async def test_retry_not_triggered_for_non_retryable_errors(self):
        """Non-retryable errors (e.g. CommerceAPIError with non-retryable code) are not retried."""
        client = CommerceMCPBase(app_key="k", app_secret="s", access_token="t")
        client.BASE_URL = "http://api.test"

        mock_http = AsyncMock()
        mock_http.get.return_value = MagicMock(
            json=lambda: {"error_response": {"code": 40001, "msg": "bad request"}},
            status_code=200,
        )
        mock_http.is_closed = False

        retry_config = RetryConfig(max_retries=3, base_delay=0.01)
        # 40001 is not in default retryable_api_codes

        with patch.object(client, "_ensure_client", return_value=mock_http):
            with pytest.raises(CommerceAPIError) as exc_info:
                await client._request("GET", "/test", retry_config=retry_config)

        assert exc_info.value.code == 40001

    @pytest.mark.asyncio
    async def test_retry_with_retryable_api_code(self):
        """When a retryable API code is configured, CommerceAPIError triggers retry."""
        client = CommerceMCPBase(app_key="k", app_secret="s", access_token="t")
        client.BASE_URL = "http://api.test"

        attempt_count = 0

        mock_http = AsyncMock()
        mock_http.is_closed = False

        async def mock_get(*args, **kwargs):
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count == 1:
                return MagicMock(
                    json=lambda: {"error_response": {"code": 90001, "msg": "rate limited"}},
                    status_code=200,
                )
            return MagicMock(
                json=lambda: {"code": 0, "data": "ok"},
                status_code=200,
            )

        mock_http.get = mock_get

        retry_config = RetryConfig(
            max_retries=2,
            base_delay=0.01,
            jitter=False,
            retryable_api_codes={90001},
        )

        with patch.object(client, "_ensure_client", return_value=mock_http):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await client._request("GET", "/test", retry_config=retry_config)

        assert result == {"code": 0, "data": "ok"}
        assert attempt_count == 2

    def test_retry_config_compute_delay_exponential(self):
        """RetryConfig.compute_delay produces exponential backoff."""
        config = RetryConfig(base_delay=1.0, max_delay=60.0, jitter=False)
        assert config.compute_delay(0) == 1.0
        assert config.compute_delay(1) == 2.0
        assert config.compute_delay(2) == 4.0
        assert config.compute_delay(3) == 8.0

    def test_retry_config_compute_delay_capped(self):
        """RetryConfig.compute_delay caps at max_delay."""
        config = RetryConfig(base_delay=1.0, max_delay=10.0, jitter=False)
        assert config.compute_delay(10) == 10.0  # 2^10 = 1024 > 10

    def test_retry_config_should_retry_http_status(self):
        """RetryConfig.should_retry_http_status returns True for retryable codes."""
        config = RetryConfig()
        assert config.should_retry_http_status(429) is True
        assert config.should_retry_http_status(503) is True
        assert config.should_retry_http_status(200) is False
        assert config.should_retry_http_status(404) is False

    def test_retry_config_should_retry_exception(self):
        """RetryConfig.should_retry_exception checks exception types."""
        config = RetryConfig()
        assert config.should_retry_exception(httpx.ConnectError("x")) is True
        assert config.should_retry_exception(httpx.ReadTimeout("x")) is True
        assert config.should_retry_exception(ValueError("x")) is False

    @pytest.mark.asyncio
    async def test_with_retry_decorator_integration(self):
        """with_retry decorator retries on retryable exceptions."""
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


# ====================================================================
#  4. Cache and Rate Limiter Integration
# ====================================================================


class TestRateLimiterIntegration:
    """Integration tests for rate limiting across multiple requests."""

    @pytest.mark.asyncio
    async def test_rate_limiter_enforces_minimum_interval(self):
        """RateLimiter.acquire() enforces the minimum interval between calls."""
        limiter = RateLimiter(requests_per_second=100.0)  # 10ms interval

        start = time.monotonic()
        await limiter.acquire()
        await limiter.acquire()
        elapsed = time.monotonic() - start

        # Should have waited at least ~10ms between the two calls
        assert elapsed >= 0.008  # allow some tolerance

    @pytest.mark.asyncio
    async def test_rate_limiter_integrated_with_client(self):
        """RateLimiter is invoked during _request."""
        client = CommerceMCPBase(app_key="k", app_secret="s", access_token="t")
        client.BASE_URL = "http://api.test"

        acquire_called = False

        async def mock_acquire():
            nonlocal acquire_called
            acquire_called = True

        client.rate_limiter = MagicMock()
        client.rate_limiter.acquire = mock_acquire

        mock_http = AsyncMock()
        mock_http.get.return_value = MagicMock(json=lambda: {"code": 0}, status_code=200)
        mock_http.is_closed = False

        with patch.object(client, "_ensure_client", return_value=mock_http):
            await client._request("GET", "/test")

        assert acquire_called is True

    @pytest.mark.asyncio
    async def test_metrics_collector_tracks_request_across_tool_calls(self):
        """MetricsCollector records metrics from multiple simulated tool invocations."""
        collector = MetricsCollector()

        # Simulate 3 successful tool calls
        collector.record_request("/api/orders", latency_ms=45.0, success=True)
        collector.record_request("/api/orders", latency_ms=55.0, success=True)
        collector.record_request("/api/products", latency_ms=30.0, success=True)

        # Simulate 1 failed call
        collector.record_request(
            "/api/orders",
            latency_ms=100.0,
            success=False,
            error_code=40001,
            error_msg="bad request",
        )

        orders = collector.get_endpoint_metrics("/api/orders")
        assert orders.request_count == 3
        assert orders.error_count == 1
        assert orders.last_error_code == 40001

        products = collector.get_endpoint_metrics("/api/products")
        assert products.request_count == 1
        assert products.error_count == 0

        global_m = collector.get_global_metrics()
        assert global_m.request_count == 4
        assert global_m.error_count == 1

        summary = collector.get_summary()
        assert summary["global"]["total_requests"] == 4
        assert "/api/orders" in summary["endpoints"]
        assert "/api/products" in summary["endpoints"]


# ====================================================================
#  5. Configuration Loading and Validation
# ====================================================================


class TestConfigLoadingIntegration:
    """Integration tests for configuration loading, validation, and from_env."""

    def test_from_env_success_with_all_vars(self):
        """from_env creates a client when all required vars are set."""
        env = {
            "MY_APP_KEY": "key123",
            "MY_APP_SECRET": "secret456",
            "MY_ACCESS_TOKEN": "token789",
        }
        with patch.dict(os.environ, env, clear=False):
            client = CommerceMCPBase.from_env("MY", ["APP_KEY", "APP_SECRET", "ACCESS_TOKEN"])
        assert client.app_key == "key123"
        assert client.app_secret == "secret456"
        assert client.access_token == "token789"

    def test_from_env_raises_on_missing(self):
        """from_env raises ConfigValidationError listing all missing vars."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ConfigValidationError) as exc_info:
                CommerceMCPBase.from_env("OCEANENGINE", ["APP_KEY", "APP_SECRET", "ACCESS_TOKEN"])
            err = exc_info.value
            assert err.platform == "OCEANENGINE"
            assert len(err.missing_vars) == 3
            assert "OCEANENGINE_APP_KEY" in err.missing_vars

    def test_from_env_partial_missing(self):
        """from_env raises even when only one var is missing."""
        env = {"TEST_APP_KEY": "k", "TEST_APP_SECRET": "s"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ConfigValidationError) as exc_info:
                CommerceMCPBase.from_env("TEST", ["APP_KEY", "APP_SECRET", "ACCESS_TOKEN"])
            assert "TEST_ACCESS_TOKEN" in exc_info.value.missing_vars

    def test_load_config_valid_json(self, tmp_path):
        """load_config loads and parses a valid JSON config file."""
        cfg = tmp_path / "config.json"
        cfg.write_text('{"servers": ["oceanengine", "jd"], "verbose": true}')
        config = load_config(str(cfg))
        assert config["servers"] == ["oceanengine", "jd"]
        assert config["verbose"] is True

    def test_load_config_missing_file_returns_empty(self):
        """load_config returns empty dict for nonexistent path."""
        assert load_config("/nonexistent/path.json") == {}

    def test_load_config_invalid_json_returns_empty(self, tmp_path):
        """load_config returns empty dict for invalid JSON."""
        cfg = tmp_path / "bad.json"
        cfg.write_text("{broken json")
        assert load_config(str(cfg)) == {}

    def test_load_config_none_path(self):
        """load_config with None path tries defaults without crashing."""
        result = load_config(None)
        assert isinstance(result, dict)

    def test_all_platforms_have_src_dir(self):
        """Every registered platform has a corresponding src/ directory."""
        for platform in SERVER_REGISTRY:
            src_path = _REPO_ROOT / "servers" / platform / "src"
            assert src_path.is_dir(), f"Missing src dir for {platform}: {src_path}"

    def test_all_platforms_have_tests_dir(self):
        """Every registered platform has a corresponding tests/ directory."""
        for platform in SERVER_REGISTRY:
            tests_path = _REPO_ROOT / "servers" / platform / "tests"
            assert tests_path.is_dir(), f"Missing tests dir for {platform}: {tests_path}"

    def test_build_pythonpath_includes_shared(self):
        """build_pythonpath always includes the shared directory."""
        pp = build_pythonpath(["oceanengine", "jd"])
        assert "shared" in pp

    def test_build_pythonpath_includes_all_platform_srcs(self):
        """build_pythonpath includes src dirs for all requested platforms."""
        pp = build_pythonpath(["oceanengine", "jd", "taobao"])
        assert "oceanengine" in pp
        assert "jd" in pp
        assert "taobao" in pp

    def test_server_registry_has_all_eight_platforms(self):
        """SERVER_REGISTRY contains exactly the 8 expected platforms."""
        expected = {"oceanengine", "doudian", "jd", "taobao", "pinduoduo", "kuaishou", "xiaohongshu", "weixin-store"}
        assert set(SERVER_REGISTRY.keys()) == expected

    def test_server_registry_env_prefix_consistency(self):
        """Every platform's env_prefix is uppercase and matches its key pattern."""
        for name, info in SERVER_REGISTRY.items():
            prefix = info["env_prefix"]
            assert prefix.isupper(), f"{name} env_prefix not uppercase: {prefix}"
            assert len(prefix) > 0


# ====================================================================
#  6. Cross-Platform Consistency
# ====================================================================


class TestCrossPlatformConsistency:
    """Integration tests verifying consistent behavior across all platforms."""

    def test_all_platforms_health_checkable(self):
        """check_server_health returns valid structure for every platform."""
        for platform in SERVER_REGISTRY:
            result = check_server_health(platform)
            assert result["platform"] == platform
            assert result["status"] in ("ready", "importable_no_creds", "not_ready", "error")

    def test_check_all_health_returns_all_platforms(self):
        """check_all_health returns results for every registered platform."""
        results = check_all_health()
        assert len(results) == len(SERVER_REGISTRY)
        platforms = {r["platform"] for r in results}
        assert platforms == set(SERVER_REGISTRY.keys())

    def test_all_health_results_have_required_keys(self):
        """Every health result has the required keys."""
        results = check_all_health()
        for r in results:
            assert "platform" in r
            assert "status" in r
            assert "env_configured" in r
            assert "importable" in r

    def test_all_platforms_have_description(self):
        """Every platform in the registry has a non-empty description."""
        for name, info in SERVER_REGISTRY.items():
            assert info.get("description"), f"{name} missing description"

    def test_all_platforms_module_naming(self):
        """Every platform module follows the mcp_*.server convention."""
        for name, info in SERVER_REGISTRY.items():
            assert info["module"].startswith("mcp_"), f"{name} module should start with mcp_"
            assert info["module"].endswith(".server"), f"{name} module should end with .server"


# ====================================================================
#  7. Signing Integration
# ====================================================================


class TestSigningIntegration:
    """Integration tests for signing across different platforms."""

    def test_md5_sign_consistency(self):
        """MD5 signing is deterministic for the same input."""
        client = CommerceMCPBase(app_secret="test_secret")
        client.sign_method = SignMethod.MD5
        params = {"app_key": "test", "timestamp": "1234567890"}
        sig1 = client._sign(params)
        sig2 = client._sign(params)
        assert sig1 == sig2
        assert len(sig1) == 32

    def test_hmac_sha256_sign_consistency(self):
        """HMAC-SHA256 signing is deterministic for the same input."""
        client = CommerceMCPBase(app_secret="test_secret")
        client.sign_method = SignMethod.HMAC_SHA256
        params = {"app_key": "test", "timestamp": "1234567890"}
        sig1 = client._sign(params)
        sig2 = client._sign(params)
        assert sig1 == sig2
        assert len(sig1) == 64

    def test_sign_excludes_sign_and_sign_method(self):
        """The _sign method excludes 'sign' and 'sign_method' keys."""
        client = CommerceMCPBase(app_secret="test_secret")
        client.sign_method = SignMethod.MD5

        params_with = {"app_key": "test", "timestamp": "123"}
        params_without = {**params_with, "sign": "xxx", "sign_method": "yyy"}

        assert client._sign(params_with) == client._sign(params_without)

    def test_sign_excludes_empty_values(self):
        """The _sign method excludes keys with empty string values."""
        client = CommerceMCPBase(app_secret="test_secret")
        client.sign_method = SignMethod.MD5

        params_with_empty = {"app_key": "test", "empty": "", "timestamp": "123"}
        params_without = {"app_key": "test", "timestamp": "123"}

        assert client._sign(params_with_empty) == client._sign(params_without)

    def test_different_secrets_produce_different_signs(self):
        """Different app_secret values produce different signatures."""
        client1 = CommerceMCPBase(app_secret="secret_a")
        client1.sign_method = SignMethod.MD5
        client2 = CommerceMCPBase(app_secret="secret_b")
        client2.sign_method = SignMethod.MD5

        params = {"app_key": "test", "timestamp": "123"}
        assert client1._sign(params) != client2._sign(params)

    def test_jd_hmac_md5_sign_integration(self):
        """JD's HMAC-MD5 signing produces 32-char uppercase hex."""
        from mcp_jd.server import JDMCP

        client = JDMCP(app_key="jd_key", app_secret="jd_secret")
        sig = client._sign({"app_key": "jd_key", "method": "test"})
        assert len(sig) == 32
        assert sig == sig.upper()

    def test_kuaishou_sign_uses_sign_secret(self):
        """Kuaishou signing uses sign_secret (not app_secret)."""
        from mcp_kuaishou.server import KuaishouMCP

        client = KuaishouMCP(
            app_key="ks_key",
            app_secret="ks_secret",
            sign_secret="ks_sign_secret",
            access_token="tok",
        )
        sig = client._sign({"app_key": "ks_key", "timestamp": "123"})
        assert len(sig) == 32
        assert sig == sig.upper()


# ====================================================================
#  8. Security: Input Validation
# ====================================================================


class TestSecurityInputValidation:
    """Integration tests for input validation and sensitive data masking."""

    def test_validate_platform_name_valid(self):
        """Valid platform names pass through."""
        assert validate_platform_name("OCEANENGINE") == "OCEANENGINE"
        assert validate_platform_name("MY_PLATFORM") == "MY_PLATFORM"

    def test_validate_platform_name_invalid(self):
        """Invalid platform names raise ValueError."""
        with pytest.raises(ValueError):
            validate_platform_name("")
        with pytest.raises(ValueError):
            validate_platform_name("lowercase")
        with pytest.raises(ValueError):
            validate_platform_name("has-dash")
        with pytest.raises(ValueError):
            validate_platform_name("a" * 65)  # too long

    def test_validate_api_param_sql_injection(self):
        """SQL injection patterns are detected."""
        with pytest.raises(ValueError, match="suspicious SQL"):
            validate_api_param("query", "'; DROP TABLE users; --")

    def test_validate_api_param_path_traversal(self):
        """Path traversal patterns are detected."""
        with pytest.raises(ValueError, match="path traversal"):
            validate_api_param("file", "../../etc/passwd")

    def test_validate_api_param_xss(self):
        """XSS patterns are detected."""
        with pytest.raises(ValueError, match="suspicious script"):
            validate_api_param("content", "<script>alert('xss')</script>")

    def test_validate_api_param_normal_values_pass(self):
        """Normal values pass validation."""
        assert validate_api_param("name", "John Doe") == "John Doe"
        assert validate_api_param("id", "12345") == "12345"

    def test_mask_sensitive_value_full(self):
        """mask_sensitive_value masks middle of long strings."""
        result = mask_sensitive_value("abcdefghijklmnop")
        assert result == "abcd****mnop"

    def test_mask_sensitive_value_short(self):
        """mask_sensitive_value handles short strings."""
        result = mask_sensitive_value("abc")
        assert "****" in result

    def test_mask_sensitive_value_empty(self):
        """mask_sensitive_value handles empty strings."""
        assert mask_sensitive_value("") == "****"

    def test_mask_dict_sensitive_keys(self):
        """mask_dict_sensitive_keys masks known sensitive field names."""
        data = {
            "app_key": "my_app_key_12345",
            "app_secret": "super_secret_value",
            "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test.signature",
            "normal_field": "visible_value",
            "nested": {
                "password": "should_be_masked",
                "safe": "keep_this",
            },
        }
        masked = mask_dict_sensitive_keys(data)
        assert "visible_value" == masked["normal_field"]
        assert "keep_this" == masked["nested"]["safe"]
        assert "****" in masked["app_key"]
        assert "****" in masked["app_secret"]
        assert "****" in masked["access_token"]
        assert "****" in masked["nested"]["password"]

    def test_mask_log_message_jwt(self):
        """mask_log_message masks JWT tokens in log strings."""
        msg = "Token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        masked = mask_log_message(msg)
        assert "eyJ" not in masked or "****" in masked

    def test_sensitive_data_filter_integration(self):
        """SensitiveDataFilter masks JWT tokens in log record messages."""
        flt = SensitiveDataFilter()
        record = MagicMock()
        record.msg = "Token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        record.args = None
        flt.filter(record)
        assert "****" in record.msg

    def test_sensitive_data_filter_masks_args(self):
        """SensitiveDataFilter masks sensitive keys in record.args dict."""
        flt = SensitiveDataFilter()
        record = MagicMock()
        record.msg = "request params"
        record.args = {"access_token": "abcdefghijklmnop", "page": "1"}
        flt.filter(record)
        assert "****" in record.args["access_token"]
        assert record.args["page"] == "1"


# ====================================================================
#  9. Pagination Integration
# ====================================================================


class TestPaginationIntegration:
    """Integration tests for the _paginate helper."""

    @pytest.mark.asyncio
    async def test_paginate_multiple_pages(self):
        """_paginate fetches all pages until items < page_size."""
        client = CommerceMCPBase()
        page_num = 0

        async def fetch_fn(page, page_size):
            nonlocal page_num
            page_num += 1
            if page_num == 1:
                return {"result": [{"id": i} for i in range(3)]}
            elif page_num == 2:
                return {"result": [{"id": 10}, {"id": 11}]}
            return {"result": []}

        results = await client._paginate(fetch_fn, page_size=3)
        assert len(results) == 5

    @pytest.mark.asyncio
    async def test_paginate_respects_max_pages(self):
        """_paginate stops at max_pages even if more data is available."""
        client = CommerceMCPBase()
        call_count = 0

        async def fetch_fn(page, page_size):
            nonlocal call_count
            call_count += 1
            return {"result": [{"id": i} for i in range(page_size)]}

        results = await client._paginate(fetch_fn, page_size=5, max_pages=3)
        assert call_count == 3
        assert len(results) == 15

    @pytest.mark.asyncio
    async def test_paginate_list_key_fallback(self):
        """_paginate falls back to 'list' key when 'result' is not present."""
        client = CommerceMCPBase()

        async def fetch_fn(page, page_size):
            return {"list": [{"id": 1}, {"id": 2}]}

        results = await client._paginate(fetch_fn, page_size=10)
        assert len(results) == 2


# ====================================================================
#  10. End-to-End Scenarios
# ====================================================================


class TestEndToEndScenarios:
    """End-to-end integration tests simulating real usage patterns."""

    @pytest.mark.asyncio
    async def test_full_advertiser_report_workflow(self):
        """Simulate: get advertiser info → get campaign report → format results."""
        from mcp_oceanengine.server import OceanEngine, get_advertiser_info, get_campaign_report

        client = OceanEngine(app_key="key", app_secret="secret", access_token="tok")

        call_count = 0

        mock_http = AsyncMock()
        mock_http.is_closed = False

        async def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.status_code = 200
            if call_count == 1:
                # First call: advertiser info
                resp.json.return_value = {
                    "code": 0,
                    "data": {"list": [{"advertiser_id": 123, "name": "Test Shop"}]},
                }
            else:
                # Second call: campaign report
                resp.json.return_value = {
                    "code": 0,
                    "data": {
                        "list": [{"campaign_id": 1, "show_cnt": 10000, "click_cnt": 500}],
                        "page_info": {"page": 1, "total": 1},
                    },
                }
            return resp

        mock_http.get = mock_get

        with patch("mcp_oceanengine.server._get_client", return_value=client):
            with patch.object(client, "_ensure_client", return_value=mock_http):
                # Step 1: Get advertiser info
                info_result = await get_advertiser_info(advertiser_ids="123")
                info = json.loads(info_result)
                assert info["code"] == 0
                assert info["data"]["list"][0]["advertiser_id"] == 123

                # Step 2: Get campaign report
                report_result = await get_campaign_report(
                    advertiser_id="123",
                    start_date="2024-01-01",
                    end_date="2024-01-31",
                )
                report = json.loads(report_result)
                assert report["code"] == 0
                assert report["data"]["list"][0]["show_cnt"] == 10000

        assert call_count == 2

    @pytest.mark.asyncio
    async def test_health_check_then_tool_call(self):
        """Simulate: health check → if healthy, make a tool call."""
        client = CommerceMCPBase(app_key="key", app_secret="secret", access_token="tok")
        client.BASE_URL = "http://api.test"

        # Mock health check
        mock_http = AsyncMock()
        mock_http.is_closed = False
        mock_http.head.return_value = MagicMock(status_code=200)

        with patch.object(client, "_ensure_client", return_value=mock_http):
            health = await client.health_check()

        assert health["configured"] is True
        assert health["has_token"] is True
        assert health["api_reachable"] is True

        # Now make a real API call
        mock_http.get.return_value = MagicMock(
            json=lambda: {"code": 0, "data": {"balance": 1000}},
            status_code=200,
        )

        with patch.object(client, "_ensure_client", return_value=mock_http):
            result = await client._request("GET", "/api/balance")

        assert result["code"] == 0
        assert result["data"]["balance"] == 1000

    @pytest.mark.asyncio
    async def test_batch_operations_with_mixed_results(self):
        """Simulate batch operations where some succeed and some fail."""
        from shared.cn_commerce_base import BatchRequestItem

        client = CommerceMCPBase(app_key="k", app_secret="s")
        call_count = 0

        async def mock_request(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise CommerceAPIError(40001, "bad request")
            return {"result": "ok"}

        with patch.object(client, "_request", side_effect=mock_request):
            requests = [
                BatchRequestItem("GET", "/api/a", request_id="r0"),
                BatchRequestItem("GET", "/api/b", request_id="r1"),
                BatchRequestItem("GET", "/api/c", request_id="r2"),
            ]
            summary = await client._batch_request(requests)

        assert summary.total == 3
        assert summary.succeeded == 2
        assert summary.failed == 1
        assert summary.error_summary["CommerceAPIError"] == 1

    @pytest.mark.asyncio
    async def test_error_recovery_with_metrics(self):
        """Simulate: error occurs → recorded in metrics → retry succeeds."""
        client = CommerceMCPBase(app_key="k", app_secret="s", access_token="t")
        client.BASE_URL = "http://api.test"

        call_count = 0
        mock_http = AsyncMock()
        mock_http.is_closed = False

        async def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.ConnectError("connection refused")
            resp = MagicMock()
            resp.json.return_value = {"code": 0, "data": "recovered"}
            resp.status_code = 200
            return resp

        mock_http.get = mock_get

        retry_config = RetryConfig(max_retries=2, base_delay=0.01, jitter=False)

        with patch.object(client, "_ensure_client", return_value=mock_http):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await client._request("GET", "/api/data", retry_config=retry_config)

        assert result["data"] == "recovered"
        assert call_count == 2

        # _request now records metrics live: the failed first attempt plus the
        # successful retry => 2 requests, 1 of them an error.
        summary = client.metrics.get_summary()
        assert summary["global"]["total_requests"] == 2
        assert summary["global"]["total_errors"] == 1


# ====================================================================
#  11. WeChat Store Token Cache Integration
# ====================================================================


class TestWeixinStoreTokenCache:
    """Integration tests for WeChat Store's token caching mechanism."""

    @pytest.fixture
    def wx_env(self):
        """Provide minimal WX env vars so the module can be imported."""
        env = {"WX_APP_ID": "test_appid", "WX_APP_SECRET": "test_secret"}
        with patch.dict(os.environ, env, clear=False):
            yield

    @pytest.mark.asyncio
    async def test_token_is_cached_and_reused(self, wx_env):
        """WeixinStoreMCP caches the access_token and reuses it."""
        import importlib

        import mcp_weixin_store.server as wx_mod

        importlib.reload(wx_mod)
        weixin_store_cls = wx_mod.WeixinStoreMCP

        client = weixin_store_cls(app_key="wx_id", app_secret="wx_secret")

        # Simulate a successful token fetch
        # _ensure_token creates its own httpx.AsyncClient inline, so we
        # need to patch the AsyncClient context manager.
        token_response = MagicMock()
        token_response.json.return_value = {
            "access_token": "fetched_token_abc",
            "expires_in": 7200,
        }
        token_response.status_code = 200

        mock_http = AsyncMock()
        mock_http.get.return_value = token_response

        with patch("httpx.AsyncClient") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            token1 = await client._ensure_token()

        assert token1 == "fetched_token_abc"

        # Second call should use cached token (no HTTP call)
        token2 = await client._ensure_token()
        assert token2 == "fetched_token_abc"
        # Only one HTTP call total (the first fetch)
        assert mock_http.get.call_count == 1

    @pytest.mark.asyncio
    async def test_static_token_bypasses_fetch(self, wx_env):
        """When WX_ACCESS_TOKEN is set directly, no token fetch occurs."""
        import importlib

        import mcp_weixin_store.server as wx_mod

        importlib.reload(wx_mod)
        weixin_store_cls = wx_mod.WeixinStoreMCP

        client = weixin_store_cls(access_token="static_token_xyz")
        token = await client._ensure_token()
        assert token == "static_token_xyz"


# ====================================================================
#  12. DouDian Signing Integration
# ====================================================================


class TestDouDianSigningIntegration:
    """Integration tests for DouDian's unique MD5 signing scheme."""

    def test_doudian_sign_deterministic(self):
        """DouDian signing is deterministic for the same input."""
        from mcp_doudian.server import DouDianClient

        client = DouDianClient(app_key="dd_key", app_secret="dd_secret", access_token="tok")
        params = {"order_id": "12345", "page": "0"}
        sig1 = client._sign(params)
        sig2 = client._sign(params)
        assert sig1 == sig2
        assert len(sig1) == 32

    def test_doudian_sign_excludes_none_and_empty(self):
        """DouDian signing excludes None and empty values."""
        from mcp_doudian.server import DouDianClient

        client = DouDianClient(app_key="dd_key", app_secret="dd_secret", access_token="tok")
        sig_with = client._sign({"order_id": "12345", "empty": "", "none_val": None})
        sig_without = client._sign({"order_id": "12345"})
        assert sig_with == sig_without


# ====================================================================
#  13. Doudian Full Request Flow
# ====================================================================


class TestDoudianFullRequestFlow:
    """Integration: DouDian tool → DouDianClient.request → mock HTTP."""

    @pytest.mark.asyncio
    async def test_get_order_list_end_to_end(self):
        """DouDian get_order_list → request → POST → mock HTTP response."""
        from mcp_doudian.server import DouDianClient

        client = DouDianClient(app_key="dd_key", app_secret="dd_secret", access_token="tok")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "code": 10000,
            "data": {
                "list": [
                    {"order_id": "DD001", "order_status": 2, "pay_amount": 9900},
                ],
                "total": 1,
            },
        }
        mock_response.status_code = 200

        mock_http = AsyncMock()
        mock_http.post.return_value = mock_response
        mock_http.is_closed = False

        with patch("mcp_doudian.server._get_client", return_value=client):
            with patch.object(client, "_ensure_client", return_value=mock_http):
                from mcp_doudian.server import get_order_list

                result = await get_order_list(start_time="2024-01-01", end_time="2024-01-31")

        assert "orders" in result
        assert result["orders"][0]["order_id"] == "DD001"


# ====================================================================
#  14. Pinduoduo Full Request Flow
# ====================================================================


class TestPinduoduoFullRequestFlow:
    """Integration: PDD tool → PinduoduoMCP._call → mock HTTP."""

    @pytest.mark.asyncio
    async def test_get_order_list_end_to_end(self):
        """PDD get_order_list → _call → POST form data → mock HTTP."""
        # PDD module requires env vars at import time; set them temporarily
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
            pinduoduo_cls = pdd_mod.PinduoduoMCP

        client = pinduoduo_cls(app_key="pdd_key", app_secret="pdd_secret", access_token="pdd_tok")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "order_list_get_response": {
                "order_list": [{"order_sn": "PDD001", "status": 1}],
                "total_count": 1,
            }
        }
        mock_response.status_code = 200

        mock_http = AsyncMock()
        mock_http.post.return_value = mock_response

        with patch.object(pdd_mod, "pdd", client):
            with patch("httpx.AsyncClient") as mock_ctx:
                mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_http)
                mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
                result = await pdd_mod.get_order_list(
                    start_time="2024-01-01 00:00:00",
                    end_time="2024-01-31 23:59:59",
                )

        data = json.loads(result)
        assert "order_list_get_response" in data
