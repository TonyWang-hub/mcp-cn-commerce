"""Tests for the shared cn_commerce_base module.

Tests the base classes, error handling, and utility functions.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# Add the shared directory to the path
_shared_dir = Path(__file__).resolve().parents[1] / "shared"
if str(_shared_dir) not in sys.path:
    sys.path.insert(0, str(_shared_dir))

from cn_commerce_base import (
    CommerceAPIError,
    CommerceMCPBase,
    ConfigValidationError,
    DEFAULT_RETRY,
    EndpointMetrics,
    MetricsCollector,
    RATE_LIMIT_RETRY,
    RateLimiter,
    RetryConfig,
    RetryableError,
    SignMethod,
    format_error_response,
    with_retry,
)

# ── SignMethod Tests ──────────────────────────────────────


class TestSignMethod:
    """Tests for SignMethod constants."""

    def test_md5_constant(self):
        assert SignMethod.MD5 == "md5"

    def test_hmac_sha256_constant(self):
        assert SignMethod.HMAC_SHA256 == "hmac_sha256"

    def test_hmac_md5_constant(self):
        assert SignMethod.HMAC_MD5 == "hmac_md5"


# ── ConfigValidationError Tests ───────────────────────────


class TestConfigValidationError:
    """Tests for ConfigValidationError."""

    def test_single_missing_var(self):
        err = ConfigValidationError("TEST", ["APP_KEY"])
        assert err.platform == "TEST"
        assert err.missing_vars == ["APP_KEY"]
        assert "APP_KEY" in str(err)

    def test_multiple_missing_vars(self):
        err = ConfigValidationError("TEST", ["APP_KEY", "APP_SECRET"])
        assert err.platform == "TEST"
        assert err.missing_vars == ["APP_KEY", "APP_SECRET"]
        assert "APP_KEY" in str(err)
        assert "APP_SECRET" in str(err)

    def test_is_exception(self):
        err = ConfigValidationError("TEST", ["VAR"])
        assert isinstance(err, Exception)


# ── CommerceAPIError Tests ────────────────────────────────


class TestCommerceAPIError:
    """Tests for CommerceAPIError."""

    def test_error_attributes(self):
        err = CommerceAPIError(40001, "Invalid parameters")
        assert err.code == 40001
        assert err.msg == "Invalid parameters"

    def test_error_message_format(self):
        err = CommerceAPIError(40001, "Invalid parameters")
        assert "[40001] Invalid parameters" in str(err)

    def test_is_exception(self):
        err = CommerceAPIError(1, "test")
        assert isinstance(err, Exception)


# ── RateLimiter Tests ─────────────────────────────────────


class TestRateLimiter:
    """Tests for RateLimiter."""

    def test_default_rate(self):
        limiter = RateLimiter()
        assert limiter.requests_per_second == 10.0

    def test_custom_rate(self):
        limiter = RateLimiter(requests_per_second=5.0)
        assert limiter.requests_per_second == 5.0

    def test_min_interval(self):
        limiter = RateLimiter(requests_per_second=10.0)
        assert limiter.min_interval == 0.1

    @pytest.mark.asyncio
    async def test_acquire_first_call(self):
        limiter = RateLimiter()
        # First call should not wait
        await limiter.acquire()
        assert limiter.last_request_time > 0

    @pytest.mark.asyncio
    async def test_acquire_respects_rate_limit(self):
        limiter = RateLimiter(requests_per_second=100.0)
        # First call
        await limiter.acquire()
        # Second call should wait
        await limiter.acquire()
        # Both calls should complete without error


# ── format_error_response Tests ───────────────────────────


class TestFormatErrorResponse:
    """Tests for format_error_response."""

    def test_commerce_api_error(self):
        err = CommerceAPIError(40001, "Invalid parameters")
        result = json.loads(format_error_response(err))
        assert result["error"]["code"] == 40001
        assert result["error"]["message"] == "Invalid parameters"

    def test_generic_exception(self):
        err = ValueError("Something went wrong")
        result = json.loads(format_error_response(err))
        assert result["error"]["message"] == "Something went wrong"

    def test_returns_valid_json(self):
        err = CommerceAPIError(1, "test")
        result = format_error_response(err)
        # Should not raise
        json.loads(result)


# ── CommerceMCPBase Tests ─────────────────────────────────


class TestCommerceMCPBase:
    """Tests for CommerceMCPBase."""

    def test_init_default_values(self):
        client = CommerceMCPBase()
        assert client.app_key == ""
        assert client.app_secret == ""
        assert client.access_token == ""

    def test_init_with_values(self):
        client = CommerceMCPBase(
            app_key="test_key",
            app_secret="test_secret",
            access_token="test_token",
        )
        assert client.app_key == "test_key"
        assert client.app_secret == "test_secret"
        assert client.access_token == "test_token"

    def test_has_rate_limiter(self):
        client = CommerceMCPBase()
        assert client.rate_limiter is not None
        assert isinstance(client.rate_limiter, RateLimiter)

    def test_from_env_success(self):
        with patch.dict(
            os.environ,
            {
                "TEST_APP_KEY": "key",
                "TEST_APP_SECRET": "secret",
                "TEST_ACCESS_TOKEN": "token",
            },
        ):
            client = CommerceMCPBase.from_env("TEST", ["APP_KEY", "APP_SECRET", "ACCESS_TOKEN"])
            assert client.app_key == "key"
            assert client.app_secret == "secret"
            assert client.access_token == "token"

    def test_from_env_missing_vars(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ConfigValidationError) as exc_info:
                CommerceMCPBase.from_env("TEST", ["APP_KEY", "APP_SECRET"])
            assert "TEST" in str(exc_info.value)
            assert "TEST_APP_KEY" in str(exc_info.value)
            assert "TEST_APP_SECRET" in str(exc_info.value)

    def test_from_env_partial_vars(self):
        with patch.dict(os.environ, {"TEST_APP_KEY": "key"}, clear=True):
            with pytest.raises(ConfigValidationError):
                CommerceMCPBase.from_env("TEST", ["APP_KEY", "APP_SECRET"])

    def test_sign_md5(self):
        client = CommerceMCPBase(app_secret="test_secret")
        client.sign_method = SignMethod.MD5
        params = {"app_key": "test", "timestamp": "1234567890"}
        result = client._sign(params)
        assert isinstance(result, str)
        assert len(result) == 32  # MD5 hex length

    def test_sign_hmac_sha256(self):
        client = CommerceMCPBase(app_secret="test_secret")
        client.sign_method = SignMethod.HMAC_SHA256
        params = {"app_key": "test", "timestamp": "1234567890"}
        result = client._sign(params)
        assert isinstance(result, str)
        assert len(result) == 64  # SHA256 hex length

    def test_sign_excludes_sign_params(self):
        client = CommerceMCPBase(app_secret="test_secret")
        client.sign_method = SignMethod.MD5
        params = {
            "app_key": "test",
            "timestamp": "1234567890",
            "sign": "should_be_excluded",
            "sign_method": "should_be_excluded",
        }
        result = client._sign(params)
        assert isinstance(result, str)

    def test_sign_empty_values_excluded(self):
        client = CommerceMCPBase(app_secret="test_secret")
        client.sign_method = SignMethod.MD5
        params = {"app_key": "test", "empty_param": ""}
        result = client._sign(params)
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_paginate_single_page(self):
        client = CommerceMCPBase()
        mock_fetch = AsyncMock(return_value={"result": [{"id": 1}, {"id": 2}]})
        result = await client._paginate(mock_fetch, page_size=10)
        assert len(result) == 2
        mock_fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_paginate_multiple_pages(self):
        client = CommerceMCPBase()
        mock_fetch = AsyncMock(
            side_effect=[
                {"result": [{"id": 1}, {"id": 2}]},
                {"result": [{"id": 3}]},
            ]
        )
        result = await client._paginate(mock_fetch, page_size=2)
        assert len(result) == 3
        assert mock_fetch.call_count == 2

    @pytest.mark.asyncio
    async def test_paginate_empty_result(self):
        client = CommerceMCPBase()
        mock_fetch = AsyncMock(return_value={"result": []})
        result = await client._paginate(mock_fetch)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_paginate_uses_list_key(self):
        client = CommerceMCPBase()
        mock_fetch = AsyncMock(return_value={"list": [{"id": 1}]})
        result = await client._paginate(mock_fetch)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_paginate_max_pages(self):
        client = CommerceMCPBase()
        mock_fetch = AsyncMock(return_value={"result": [{"id": 1}]})
        result = await client._paginate(mock_fetch, page_size=1, max_pages=3)
        assert len(result) == 3
        assert mock_fetch.call_count == 3

    def test_init_has_metrics_collector(self):
        client = CommerceMCPBase()
        assert isinstance(client.metrics, MetricsCollector)


# ── EndpointMetrics Tests ────────────────────────────────


class TestEndpointMetrics:
    """Tests for EndpointMetrics dataclass."""

    def test_default_values(self):
        m = EndpointMetrics()
        assert m.request_count == 0
        assert m.error_count == 0
        assert m.total_latency_ms == 0.0
        assert m.min_latency_ms == float("inf")
        assert m.max_latency_ms == 0.0

    def test_avg_latency_no_requests(self):
        m = EndpointMetrics()
        assert m.avg_latency_ms == 0.0

    def test_avg_latency_with_requests(self):
        m = EndpointMetrics(request_count=3, total_latency_ms=300.0)
        assert m.avg_latency_ms == 100.0

    def test_error_rate_no_requests(self):
        m = EndpointMetrics()
        assert m.error_rate == 0.0

    def test_error_rate_with_requests(self):
        m = EndpointMetrics(request_count=10, error_count=3)
        assert m.error_rate == 0.3


# ── MetricsCollector Tests ───────────────────────────────


class TestMetricsCollector:
    """Tests for MetricsCollector."""

    def test_record_successful_request(self):
        collector = MetricsCollector()
        collector.record_request("/api/test", latency_ms=50.0, success=True)
        ep = collector.get_endpoint_metrics("/api/test")
        assert ep.request_count == 1
        assert ep.error_count == 0
        assert ep.total_latency_ms == 50.0
        assert ep.min_latency_ms == 50.0
        assert ep.max_latency_ms == 50.0

    def test_record_failed_request(self):
        collector = MetricsCollector()
        collector.record_request(
            "/api/test",
            latency_ms=100.0,
            success=False,
            error_code=40001,
            error_msg="bad",
        )
        ep = collector.get_endpoint_metrics("/api/test")
        assert ep.request_count == 1
        assert ep.error_count == 1
        assert ep.last_error_code == 40001
        assert ep.last_error_msg == "bad"

    def test_record_multiple_requests(self):
        collector = MetricsCollector()
        collector.record_request("/api/a", latency_ms=10.0, success=True)
        collector.record_request("/api/a", latency_ms=20.0, success=True)
        collector.record_request("/api/b", latency_ms=5.0, success=False, error_code=500, error_msg="err")
        ep_a = collector.get_endpoint_metrics("/api/a")
        ep_b = collector.get_endpoint_metrics("/api/b")
        assert ep_a.request_count == 2
        assert ep_b.request_count == 1
        assert ep_b.error_count == 1

    def test_global_metrics(self):
        collector = MetricsCollector()
        collector.record_request("/api/a", latency_ms=10.0, success=True)
        collector.record_request("/api/b", latency_ms=30.0, success=False, error_code=1, error_msg="e")
        g = collector.get_global_metrics()
        assert g.request_count == 2
        assert g.error_count == 1
        assert g.total_latency_ms == 40.0

    def test_get_all_metrics(self):
        collector = MetricsCollector()
        collector.record_request("/api/a", latency_ms=10.0, success=True)
        collector.record_request("/api/b", latency_ms=20.0, success=True)
        all_m = collector.get_all_metrics()
        assert "/api/a" in all_m
        assert "/api/b" in all_m

    def test_get_endpoint_metrics_unknown_returns_default(self):
        collector = MetricsCollector()
        m = collector.get_endpoint_metrics("/unknown")
        assert m.request_count == 0

    def test_min_max_latency_tracking(self):
        collector = MetricsCollector()
        collector.record_request("/api", latency_ms=5.0, success=True)
        collector.record_request("/api", latency_ms=100.0, success=True)
        collector.record_request("/api", latency_ms=50.0, success=True)
        ep = collector.get_endpoint_metrics("/api")
        assert ep.min_latency_ms == 5.0
        assert ep.max_latency_ms == 100.0
        assert ep.avg_latency_ms == pytest.approx(155.0 / 3)

    def test_summary_structure(self):
        collector = MetricsCollector()
        collector.record_request("/api/test", latency_ms=42.0, success=True)
        summary = collector.get_summary()
        assert "uptime_seconds" in summary
        assert "global" in summary
        assert "endpoints" in summary
        assert summary["global"]["total_requests"] == 1
        assert "/api/test" in summary["endpoints"]

    def test_summary_empty_collector(self):
        collector = MetricsCollector()
        summary = collector.get_summary()
        assert summary["global"]["total_requests"] == 0
        assert summary["global"]["total_errors"] == 0
        assert summary["endpoints"] == {}

    def test_reset(self):
        collector = MetricsCollector()
        collector.record_request("/api", latency_ms=10.0, success=True)
        collector.reset()
        g = collector.get_global_metrics()
        assert g.request_count == 0
        assert collector.get_all_metrics() == {}


# ── Health Check Tests ────────────────────────────────────


class TestHealthCheck:
    """Tests for CommerceMCPBase.health_check."""

    @pytest.mark.asyncio
    async def test_health_check_no_base_url(self):
        client = CommerceMCPBase()
        result = await client.health_check()
        assert result["api_reachable"] is False
        assert result["configured"] is False

    @pytest.mark.asyncio
    async def test_health_check_configured_no_token(self):
        client = CommerceMCPBase(app_key="key", app_secret="secret")
        result = await client.health_check()
        assert result["configured"] is True
        assert result["has_token"] is False

    @pytest.mark.asyncio
    async def test_health_check_includes_metrics(self):
        client = CommerceMCPBase(app_key="key", app_secret="secret")
        result = await client.health_check()
        assert "metrics" in result
        assert "global" in result["metrics"]
        assert "uptime_seconds" in result["metrics"]

    @pytest.mark.asyncio
    async def test_health_check_connection_error(self):
        from unittest.mock import AsyncMock
        from unittest.mock import patch as mock_patch

        client = CommerceMCPBase(app_key="k", app_secret="s")
        client.BASE_URL = "http://127.0.0.1:99999"
        mock_client = AsyncMock()
        mock_client.head.side_effect = httpx.ConnectError("refused")
        with mock_patch.object(client, "_get_client", return_value=mock_client):
            result = await client.health_check()
        assert result["api_reachable"] is False
        assert "error" in result


# ── RetryConfig Tests ─────────────────────────────────────


class TestRetryConfig:
    """Tests for RetryConfig dataclass."""

    def test_default_values(self):
        cfg = RetryConfig()
        assert cfg.max_retries == 3
        assert cfg.base_delay == 1.0
        assert cfg.max_delay == 60.0
        assert cfg.jitter is True
        assert 429 in cfg.retryable_status_codes
        assert 500 in cfg.retryable_status_codes
        assert 502 in cfg.retryable_status_codes
        assert 503 in cfg.retryable_status_codes
        assert 504 in cfg.retryable_status_codes
        assert cfg.retryable_api_codes == set()

    def test_custom_values(self):
        cfg = RetryConfig(
            max_retries=5,
            base_delay=2.0,
            max_delay=120.0,
            jitter=False,
            retryable_status_codes={429},
            retryable_api_codes={40001, 40002},
        )
        assert cfg.max_retries == 5
        assert cfg.base_delay == 2.0
        assert cfg.max_delay == 120.0
        assert cfg.jitter is False
        assert cfg.retryable_status_codes == {429}
        assert cfg.retryable_api_codes == {40001, 40002}

    def test_compute_delay_exponential(self):
        cfg = RetryConfig(base_delay=1.0, jitter=False)
        assert cfg.compute_delay(0) == 1.0
        assert cfg.compute_delay(1) == 2.0
        assert cfg.compute_delay(2) == 4.0
        assert cfg.compute_delay(3) == 8.0

    def test_compute_delay_capped_at_max(self):
        cfg = RetryConfig(base_delay=1.0, max_delay=5.0, jitter=False)
        assert cfg.compute_delay(10) == 5.0  # 2^10 = 1024, capped to 5.0

    def test_compute_delay_with_jitter(self):
        cfg = RetryConfig(base_delay=4.0, jitter=True)
        delays = [cfg.compute_delay(0) for _ in range(100)]
        # With jitter, delay should be in [2.0, 6.0] (4.0 * [0.5, 1.5])
        assert all(2.0 <= d <= 6.0 for d in delays)
        # Should have some variation (not all the same)
        assert len(set(delays)) > 1

    def test_should_retry_http_status(self):
        cfg = RetryConfig()
        assert cfg.should_retry_http_status(429) is True
        assert cfg.should_retry_http_status(500) is True
        assert cfg.should_retry_http_status(503) is True
        assert cfg.should_retry_http_status(200) is False
        assert cfg.should_retry_http_status(400) is False
        assert cfg.should_retry_http_status(404) is False

    def test_should_retry_api_code(self):
        cfg = RetryConfig(retryable_api_codes={40001, 50001})
        assert cfg.should_retry_api_code(40001) is True
        assert cfg.should_retry_api_code(50001) is True
        assert cfg.should_retry_api_code(40002) is False

    def test_should_retry_exception_connect_error(self):
        cfg = RetryConfig()
        assert cfg.should_retry_exception(httpx.ConnectError("timeout")) is True

    def test_should_retry_exception_read_timeout(self):
        cfg = RetryConfig()
        assert cfg.should_retry_exception(httpx.ReadTimeout("timeout")) is True

    def test_should_retry_exception_write_timeout(self):
        cfg = RetryConfig()
        assert cfg.should_retry_exception(httpx.WriteTimeout("timeout")) is True

    def test_should_retry_exception_pool_timeout(self):
        cfg = RetryConfig()
        assert cfg.should_retry_exception(httpx.PoolTimeout("timeout")) is True

    def test_should_retry_exception_http_status_error(self):
        cfg = RetryConfig()
        # HTTPStatusError is NOT in default retryable_exceptions
        assert cfg.should_retry_exception(httpx.HTTPStatusError("400", request=AsyncMock(), response=AsyncMock())) is False

    def test_should_retry_exception_commerce_api_error_retryable(self):
        cfg = RetryConfig(retryable_api_codes={40001})
        assert cfg.should_retry_exception(CommerceAPIError(40001, "rate limited")) is True

    def test_should_retry_exception_commerce_api_error_not_retryable(self):
        cfg = RetryConfig(retryable_api_codes={40001})
        assert cfg.should_retry_exception(CommerceAPIError(40002, "bad request")) is False

    def test_should_retry_exception_generic_error(self):
        cfg = RetryConfig()
        assert cfg.should_retry_exception(ValueError("bad")) is False

    def test_retryable_exceptions_custom(self):
        cfg = RetryConfig(retryable_exceptions=(ValueError,))
        assert cfg.should_retry_exception(ValueError("test")) is True
        assert cfg.should_retry_exception(httpx.ConnectError("test")) is False


class TestRetryableError:
    """Tests for RetryableError."""

    def test_attributes(self):
        original = httpx.ConnectError("timeout")
        err = RetryableError(original, attempt=2)
        assert err.original is original
        assert err.attempt == 2
        assert "attempt 2" in str(err)

    def test_is_exception(self):
        err = RetryableError(ValueError("test"), 0)
        assert isinstance(err, Exception)


class TestDefaultRetryConfigs:
    """Tests for DEFAULT_RETRY and RATE_LIMIT_RETRY presets."""

    def test_default_retry(self):
        assert DEFAULT_RETRY.max_retries == 3
        assert DEFAULT_RETRY.base_delay == 1.0
        assert DEFAULT_RETRY.max_delay == 60.0

    def test_rate_limit_retry(self):
        assert RATE_LIMIT_RETRY.max_retries == 5
        assert RATE_LIMIT_RETRY.base_delay == 2.0
        assert RATE_LIMIT_RETRY.max_delay == 120.0
        assert 429 in RATE_LIMIT_RETRY.retryable_status_codes


# ── with_retry Decorator Tests ────────────────────────────


class TestWithRetryDecorator:
    """Tests for the with_retry async decorator."""

    @pytest.mark.asyncio
    async def test_no_retry_on_success(self):
        call_count = 0

        @with_retry(RetryConfig(max_retries=3, base_delay=0.01, jitter=False))
        async def succeed():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await succeed()
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_retryable_exception(self):
        call_count = 0

        @with_retry(RetryConfig(max_retries=3, base_delay=0.01, jitter=False))
        async def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise httpx.ConnectError("connection refused")
            return "ok"

        result = await fail_then_succeed()
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self):
        call_count = 0

        @with_retry(RetryConfig(max_retries=2, base_delay=0.01, jitter=False))
        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise httpx.ReadTimeout("timeout")

        with pytest.raises(httpx.ReadTimeout):
            await always_fail()
        assert call_count == 3  # 1 initial + 2 retries

    @pytest.mark.asyncio
    async def test_no_retry_on_non_retryable_exception(self):
        call_count = 0

        @with_retry(RetryConfig(max_retries=3, base_delay=0.01, jitter=False))
        async def fail_non_retryable():
            nonlocal call_count
            call_count += 1
            raise ValueError("not retryable")

        with pytest.raises(ValueError, match="not retryable"):
            await fail_non_retryable()
        assert call_count == 1  # No retries

    @pytest.mark.asyncio
    async def test_preserves_function_name(self):
        @with_retry(RetryConfig(max_retries=0))
        async def my_function():
            return True

        assert my_function.__name__ == "my_function"

    @pytest.mark.asyncio
    async def test_passes_args_and_kwargs(self):
        received_args = []

        @with_retry(RetryConfig(max_retries=0))
        async def capture_args(a, b, c=None):
            received_args.append((a, b, c))
            return "ok"

        await capture_args(1, 2, c=3)
        assert received_args == [(1, 2, 3)]

    @pytest.mark.asyncio
    async def test_uses_default_retry_when_no_config(self):
        call_count = 0

        @with_retry()
        async def fail_once():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.ConnectError("fail")
            return "done"

        result = await fail_once()
        assert result == "done"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_max_retries_zero_no_retry(self):
        call_count = 0

        @with_retry(RetryConfig(max_retries=0, base_delay=0.01))
        async def fail():
            nonlocal call_count
            call_count += 1
            raise httpx.ConnectError("fail")

        with pytest.raises(httpx.ConnectError):
            await fail()
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_with_commerce_api_error(self):
        call_count = 0

        @with_retry(RetryConfig(
            max_retries=2,
            base_delay=0.01,
            jitter=False,
            retryable_api_codes={40001},
        ))
        async def api_fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise CommerceAPIError(40001, "rate limited")
            return "ok"

        result = await api_fail_then_succeed()
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retry_does_not_catch_non_retryable_api_code(self):
        call_count = 0

        @with_retry(RetryConfig(
            max_retries=3,
            base_delay=0.01,
            retryable_api_codes={40001},
        ))
        async def api_fail_wrong_code():
            nonlocal call_count
            call_count += 1
            raise CommerceAPIError(50001, "not retryable")

        with pytest.raises(CommerceAPIError):
            await api_fail_wrong_code()
        assert call_count == 1


# ── _request Retry Integration Tests ──────────────────────


class TestRequestRetry:
    """Tests for retry integration in CommerceMCPBase._request."""

    @pytest.mark.asyncio
    async def test_request_with_retry_success_first_try(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        client.BASE_URL = "http://test.example.com"
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": {"id": 1}}
        mock_response.status_code = 200
        mock_client.get.return_value = mock_response

        with patch.object(client, "_get_client", return_value=mock_client):
            result = await client._request(
                "GET", "/api/test",
                retry_config=RetryConfig(max_retries=2, base_delay=0.01, jitter=False),
            )

        assert result == {"result": {"id": 1}}
        assert mock_client.get.call_count == 1

    @pytest.mark.asyncio
    async def test_request_with_retry_on_connect_error(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        client.BASE_URL = "http://test.example.com"
        mock_client = AsyncMock()
        success_response = MagicMock()
        success_response.json.return_value = {"result": {"ok": True}}
        success_response.status_code = 200

        mock_client.get.side_effect = [
            httpx.ConnectError("connection refused"),
            success_response,
        ]

        with patch.object(client, "_get_client", return_value=mock_client):
            result = await client._request(
                "GET", "/api/test",
                retry_config=RetryConfig(max_retries=3, base_delay=0.01, jitter=False),
            )

        assert result == {"result": {"ok": True}}
        assert mock_client.get.call_count == 2

    @pytest.mark.asyncio
    async def test_request_with_retry_exhausted_raises(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        client.BASE_URL = "http://test.example.com"
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("connection refused")

        with patch.object(client, "_get_client", return_value=mock_client):
            with pytest.raises(httpx.ConnectError):
                await client._request(
                    "GET", "/api/test",
                    retry_config=RetryConfig(max_retries=2, base_delay=0.01, jitter=False),
                )

        assert mock_client.get.call_count == 3  # 1 initial + 2 retries

    @pytest.mark.asyncio
    async def test_request_no_retry_config_raises_immediately(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        client.BASE_URL = "http://test.example.com"
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("connection refused")

        with patch.object(client, "_get_client", return_value=mock_client):
            with pytest.raises(httpx.ConnectError):
                await client._request("GET", "/api/test")

        assert mock_client.get.call_count == 1

    @pytest.mark.asyncio
    async def test_request_retry_on_api_error_with_retryable_code(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        client.BASE_URL = "http://test.example.com"
        mock_client = AsyncMock()

        error_response = MagicMock()
        error_response.json.return_value = {"error_response": {"code": 40001, "msg": "rate limited"}}
        error_response.status_code = 200

        success_response = MagicMock()
        success_response.json.return_value = {"result": {"ok": True}}
        success_response.status_code = 200

        mock_client.get.side_effect = [error_response, success_response]

        with patch.object(client, "_get_client", return_value=mock_client):
            result = await client._request(
                "GET", "/api/test",
                retry_config=RetryConfig(
                    max_retries=2, base_delay=0.01, jitter=False,
                    retryable_api_codes={40001},
                ),
            )

        assert result == {"result": {"ok": True}}
        assert mock_client.get.call_count == 2

    @pytest.mark.asyncio
    async def test_request_retry_on_api_error_non_retryable_raises(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        client.BASE_URL = "http://test.example.com"
        mock_client = AsyncMock()
        error_response = MagicMock()
        error_response.json.return_value = {"error_response": {"code": 40002, "msg": "bad request"}}
        error_response.status_code = 200
        mock_client.get.return_value = error_response

        with patch.object(client, "_get_client", return_value=mock_client):
            with pytest.raises(CommerceAPIError) as exc_info:
                await client._request(
                    "GET", "/api/test",
                    retry_config=RetryConfig(
                        max_retries=3, base_delay=0.01, jitter=False,
                        retryable_api_codes={40001},
                    ),
                )

        assert exc_info.value.code == 40002
        assert mock_client.get.call_count == 1

    @pytest.mark.asyncio
    async def test_request_retry_regenerates_timestamp(self):
        """Each retry attempt should generate a fresh timestamp."""
        client = CommerceMCPBase(app_key="k", app_secret="s")
        client.BASE_URL = "http://test.example.com"
        timestamps = []
        mock_client = AsyncMock()

        error_response = MagicMock()
        error_response.json.return_value = {"result": "ok"}
        error_response.status_code = 200

        call_count = 0

        async def capture_get(url, params=None):
            nonlocal call_count
            call_count += 1
            if params:
                timestamps.append(params.get("timestamp"))
            if call_count == 1:
                raise httpx.ConnectError("fail")
            return error_response

        mock_client.get.side_effect = capture_get

        with patch.object(client, "_get_client", return_value=mock_client):
            await client._request(
                "GET", "/api/test",
                retry_config=RetryConfig(max_retries=2, base_delay=0.1, jitter=False),
            )

        # Should have 2 different timestamps (one per attempt)
        assert len(timestamps) == 2
        # Timestamps should be different (time advances between retries)
        assert timestamps[0] != timestamps[1]
