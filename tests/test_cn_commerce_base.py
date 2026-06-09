"""Tests for the shared cn_commerce_base module.

Tests the base classes, error handling, and utility functions.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# Add the shared directory to the path
_shared_dir = Path(__file__).resolve().parents[1] / "shared"
if str(_shared_dir) not in sys.path:
    sys.path.insert(0, str(_shared_dir))

from cn_commerce_base import (
    DEFAULT_RETRY,
    RATE_LIMIT_RETRY,
    BatchRequestItem,
    BatchResultItem,
    BatchSummary,
    CommerceAPIError,
    CommerceMCPBase,
    ConfigRule,
    ConfigValidationResult,
    ConfigValidator,
    ConfigurableRateLimiter,
    ConfigValidationError,
    ConnectionPoolMonitor,
    EndpointMetrics,
    EndpointRateLimit,
    HealthCheckCache,
    HealthCheckResult,
    MetricsCollector,
    PlatformRateLimitConfig,
    PoolMetrics,
    RateLimitConfig,
    RateLimiter,
    RateLimitStats,
    RetryableError,
    RetryConfig,
    SensitiveDataFilter,
    SignMethod,
    Span,
    SpanEvent,
    TraceContext,
    Tracer,
    format_error_response,
    format_response,
    handle_tool_errors,
    mask_dict_sensitive_keys,
    mask_log_message,
    mask_sensitive_value,
    sanitize_log_context,
    span_scope,
    validate_api_param,
    validate_env_var_name,
    validate_platform_name,
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
        with mock_patch.object(client, "_ensure_client", return_value=mock_client):
            result = await client.health_check(use_cache=False)
        assert result["api_reachable"] is False
        assert "error" in result


# ── BatchRequestItem Tests ───────────────────────────────


class TestBatchRequestItem:
    """Tests for BatchRequestItem dataclass."""

    def test_basic_creation(self):
        item = BatchRequestItem(method="GET", path="/api/test")
        assert item.method == "GET"
        assert item.path == "/api/test"
        assert item.params == {}
        assert item.data == {}
        assert item.request_id == ""

    def test_with_all_fields(self):
        item = BatchRequestItem(
            method="POST",
            path="/api/orders",
            params={"page": 1},
            data={"name": "test"},
            request_id="req-1",
        )
        assert item.method == "POST"
        assert item.params == {"page": 1}
        assert item.data == {"name": "test"}
        assert item.request_id == "req-1"

    def test_params_default_factory(self):
        """Each instance should have independent default dicts."""
        a = BatchRequestItem(method="GET", path="/a")
        b = BatchRequestItem(method="GET", path="/b")
        a.params["key"] = "val"
        assert "key" not in b.params


# ── BatchResultItem Tests ────────────────────────────────


class TestBatchResultItem:
    """Tests for BatchResultItem dataclass."""

    def test_success_result(self):
        r = BatchResultItem(request_id="r1", success=True, data={"ok": 1}, latency_ms=42.5)
        assert r.success is True
        assert r.data == {"ok": 1}
        assert r.error is None
        assert r.latency_ms == 42.5

    def test_failure_result(self):
        err = CommerceAPIError(40001, "bad")
        r = BatchResultItem(request_id="r2", success=False, error=err)
        assert r.success is False
        assert r.data is None
        assert isinstance(r.error, CommerceAPIError)

    def test_defaults(self):
        r = BatchResultItem(request_id="", success=True)
        assert r.data is None
        assert r.error is None
        assert r.latency_ms == 0.0


# ── BatchSummary Tests ───────────────────────────────────


class TestBatchSummary:
    """Tests for BatchSummary dataclass."""

    def test_basic_creation(self):
        results = [
            BatchResultItem(request_id="1", success=True),
            BatchResultItem(request_id="2", success=False, error=CommerceAPIError(1, "e")),
        ]
        summary = BatchSummary(
            total=2,
            succeeded=1,
            failed=1,
            results=results,
            total_latency_ms=100.0,
            error_summary={"CommerceAPIError": 1},
        )
        assert summary.total == 2
        assert summary.succeeded == 1
        assert summary.failed == 1
        assert len(summary.results) == 2
        assert summary.error_summary == {"CommerceAPIError": 1}

    def test_error_summary_default_factory(self):
        """Each instance should have independent default error_summary."""
        a = BatchSummary(total=0, succeeded=0, failed=0, results=[], total_latency_ms=0.0)
        b = BatchSummary(total=0, succeeded=0, failed=0, results=[], total_latency_ms=0.0)
        a.error_summary["X"] = 1
        assert "X" not in b.error_summary


# ── _batch_aggregate Tests ───────────────────────────────


class TestBatchAggregate:
    """Tests for CommerceMCPBase._batch_aggregate static method."""

    def test_all_success(self):
        results = [
            BatchResultItem(request_id="1", success=True, latency_ms=10.0),
            BatchResultItem(request_id="2", success=True, latency_ms=20.0),
        ]
        summary = CommerceMCPBase._batch_aggregate(results, total_latency_ms=25.0)
        assert summary.total == 2
        assert summary.succeeded == 2
        assert summary.failed == 0
        assert summary.error_summary == {}

    def test_mixed_results(self):
        results = [
            BatchResultItem(request_id="1", success=True),
            BatchResultItem(request_id="2", success=False, error=CommerceAPIError(1, "e")),
            BatchResultItem(request_id="3", success=False, error=ValueError("v")),
        ]
        summary = CommerceMCPBase._batch_aggregate(results, total_latency_ms=50.0)
        assert summary.total == 3
        assert summary.succeeded == 1
        assert summary.failed == 2
        assert summary.error_summary["CommerceAPIError"] == 1
        assert summary.error_summary["ValueError"] == 1

    def test_empty_results(self):
        summary = CommerceMCPBase._batch_aggregate([], total_latency_ms=0.0)
        assert summary.total == 0
        assert summary.succeeded == 0
        assert summary.failed == 0

    def test_same_error_type_counted(self):
        err = CommerceAPIError(1, "e")
        results = [
            BatchResultItem(request_id="a", success=False, error=err),
            BatchResultItem(request_id="b", success=False, error=err),
        ]
        summary = CommerceMCPBase._batch_aggregate(results, total_latency_ms=10.0)
        assert summary.error_summary["CommerceAPIError"] == 2


# ── _batch_request Tests ─────────────────────────────────


class TestBatchRequest:
    """Tests for CommerceMCPBase._batch_request."""

    @pytest.mark.asyncio
    async def test_empty_requests_raises(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        with pytest.raises(ValueError, match="cannot be empty"):
            await client._batch_request([])

    @pytest.mark.asyncio
    async def test_single_request_success(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"result": {"id": 1}}
            summary = await client._batch_request(
                [BatchRequestItem("GET", "/api/test", request_id="t1")],
            )
        assert summary.total == 1
        assert summary.succeeded == 1
        assert summary.failed == 0
        assert summary.results[0].data == {"result": {"id": 1}}
        assert summary.results[0].latency_ms > 0

    @pytest.mark.asyncio
    async def test_multiple_requests_all_success(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"result": "ok"}
            requests = [BatchRequestItem("GET", "/api/a", request_id=f"r{i}") for i in range(5)]
            summary = await client._batch_request(requests, max_concurrency=3)
        assert summary.total == 5
        assert summary.succeeded == 5
        assert summary.failed == 0
        assert mock_req.call_count == 5

    @pytest.mark.asyncio
    async def test_partial_failure(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        call_count = 0

        async def _side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise CommerceAPIError(40001, "bad request")
            return {"result": "ok"}

        with patch.object(client, "_request", side_effect=_side_effect):
            requests = [BatchRequestItem("GET", "/api/a", request_id=f"r{i}") for i in range(3)]
            summary = await client._batch_request(requests)

        assert summary.total == 3
        assert summary.failed == 1
        assert summary.error_summary["CommerceAPIError"] == 1

    @pytest.mark.asyncio
    async def test_concurrency_clamped(self):
        """max_concurrency is clamped to 1-20."""
        client = CommerceMCPBase(app_key="k", app_secret="s")
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"result": "ok"}
            requests = [BatchRequestItem("GET", "/api/a", request_id="r0")]
            # Should not raise even with out-of-range values
            await client._batch_request(requests, max_concurrency=0)
            await client._batch_request(requests, max_concurrency=100)

    @pytest.mark.asyncio
    async def test_fail_fast_mode(self):
        """fail_fast stops submitting after first error."""
        client = CommerceMCPBase(app_key="k", app_secret="s")
        call_count = 0

        async def _side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise CommerceAPIError(500, "server error")
            # Slow down subsequent calls to ensure fail_fast has time to trigger
            await asyncio.sleep(0.05)
            return {"result": "ok"}

        with patch.object(client, "_request", side_effect=_side_effect):
            requests = [BatchRequestItem("GET", "/api/a", request_id=f"r{i}") for i in range(5)]
            summary = await client._batch_request(requests, fail_fast=True)

        assert summary.failed >= 1
        assert summary.error_summary.get("CommerceAPIError", 0) >= 1

    @pytest.mark.asyncio
    async def test_request_params_not_mutated(self):
        """Original request params should not be mutated by batch execution."""
        client = CommerceMCPBase(app_key="k", app_secret="s")
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"result": "ok"}
            item = BatchRequestItem("GET", "/api/a", params={"key": "val"}, request_id="r0")
            await client._batch_request([item])
        # Original params unchanged
        assert item.params == {"key": "val"}

    @pytest.mark.asyncio
    async def test_request_ids_preserved(self):
        """request_id should match between input and results."""
        client = CommerceMCPBase(app_key="k", app_secret="s")
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"result": "ok"}
            requests = [
                BatchRequestItem("GET", "/api", request_id="alpha"),
                BatchRequestItem("GET", "/api", request_id="beta"),
                BatchRequestItem("GET", "/api", request_id="gamma"),
            ]
            summary = await client._batch_request(requests)
        result_ids = {r.request_id for r in summary.results}
        assert result_ids == {"alpha", "beta", "gamma"}

    @pytest.mark.asyncio
    async def test_latency_tracked(self):
        """Each result and the summary should have latency > 0."""
        client = CommerceMCPBase(app_key="k", app_secret="s")
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"result": "ok"}
            summary = await client._batch_request(
                [BatchRequestItem("GET", "/api", request_id="r0")],
            )
        assert summary.total_latency_ms > 0
        assert summary.results[0].latency_ms > 0

    @pytest.mark.asyncio
    async def test_mixed_success_and_failure_types(self):
        """Multiple error types in a single batch."""
        client = CommerceMCPBase(app_key="k", app_secret="s")
        call_count = 0

        async def _side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise CommerceAPIError(40001, "api error")
            if call_count == 3:
                raise httpx.ConnectError("connection refused")
            return {"result": "ok"}

        with patch.object(client, "_request", side_effect=_side_effect):
            requests = [BatchRequestItem("GET", "/api", request_id=f"r{i}") for i in range(4)]
            summary = await client._batch_request(requests)

        assert summary.total == 4
        assert summary.succeeded == 2
        assert summary.failed == 2
        assert summary.error_summary["CommerceAPIError"] == 1
        assert summary.error_summary["ConnectError"] == 1


# ── mask_sensitive_value Tests ─────────────────────────────


class TestMaskSensitiveValue:
    """Tests for mask_sensitive_value function."""

    def test_normal_value(self):
        assert mask_sensitive_value("abcdefghijklmnop") == "abcd****mnop"

    def test_short_value(self):
        result = mask_sensitive_value("short")
        assert "****" in result
        assert result.startswith("s")
        assert result.endswith("t")

    def test_empty_value(self):
        assert mask_sensitive_value("") == "****"

    def test_single_char(self):
        assert mask_sensitive_value("x") == "****"

    def test_two_chars(self):
        result = mask_sensitive_value("ab")
        assert "****" in result
        assert result == "a****b"

    def test_exact_boundary_length(self):
        """Value length equals prefix + suffix: should mask."""
        result = mask_sensitive_value("abcdefgh", visible_prefix=4, visible_suffix=4)
        # len == 8 == prefix + suffix, so it goes to the short path
        assert "****" in result

    def test_just_above_boundary(self):
        result = mask_sensitive_value("abcdefghi", visible_prefix=4, visible_suffix=4)
        assert result == "abcd****fghi"

    def test_custom_visible_lengths(self):
        result = mask_sensitive_value("abcdefghij", visible_prefix=2, visible_suffix=2)
        assert result == "ab****ij"

    def test_none_like_falsy(self):
        # mask_sensitive_value expects str, but let's check empty string edge
        assert mask_sensitive_value("") == "****"


# ── mask_dict_sensitive_keys Tests ─────────────────────────


class TestMaskDictSensitiveKeys:
    """Tests for mask_dict_sensitive_keys function."""

    def test_no_sensitive_keys(self):
        data = {"name": "test", "count": 42}
        result = mask_dict_sensitive_keys(data)
        assert result == {"name": "test", "count": 42}

    def test_sensitive_string_key(self):
        data = {"app_key": "abcdefghijklmnop", "name": "test"}
        result = mask_dict_sensitive_keys(data)
        assert result["name"] == "test"
        assert "****" in result["app_key"]

    def test_sensitive_non_string_key(self):
        data = {"access_token": 12345}
        result = mask_dict_sensitive_keys(data)
        assert result["access_token"] == "***MASKED***"

    def test_nested_dict(self):
        data = {"outer": {"app_secret": "verysecretvalue", "safe": "ok"}}
        result = mask_dict_sensitive_keys(data)
        assert result["outer"]["safe"] == "ok"
        assert "****" in result["outer"]["app_secret"]

    def test_list_of_dicts(self):
        data = {"items": [{"app_key": "key1"}, {"app_key": "key2"}]}
        result = mask_dict_sensitive_keys(data)
        assert "****" in result["items"][0]["app_key"]

    def test_list_of_non_dicts_unchanged(self):
        data = {"items": [1, 2, "three"]}
        result = mask_dict_sensitive_keys(data)
        assert result["items"] == [1, 2, "three"]

    def test_sign_key_masked(self):
        data = {"sign": "abcdef123456"}
        result = mask_dict_sensitive_keys(data)
        assert "****" in result["sign"]

    def test_password_key_masked(self):
        data = {"password": "mysecretpw"}
        result = mask_dict_sensitive_keys(data)
        assert "****" in result["password"]

    def test_refresh_token_key_masked(self):
        data = {"refresh_token": "tok_1234567890abcdef"}
        result = mask_dict_sensitive_keys(data)
        assert "****" in result["refresh_token"]


# ── mask_log_message Tests ────────────────────────────────


class TestMaskLogMessage:
    """Tests for mask_log_message function."""

    def test_no_sensitive_data(self):
        msg = "Normal log message"
        assert mask_log_message(msg) == msg

    def test_jwt_masked(self):
        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        result = mask_log_message(jwt)
        assert "eyJ" in result  # first few chars visible
        assert "****" in result

    def test_bearer_token_masked(self):
        msg = "Using Bearer abcdefghijklmnop1234"
        result = mask_log_message(msg)
        assert "Bearer" in result
        assert "****" in result

    def test_mixed_text(self):
        msg = "Request failed with Bearer abcdefghijklmnop, retrying"
        result = mask_log_message(msg)
        assert "Request failed" in result
        assert "Bearer" in result

    def test_empty_string(self):
        assert mask_log_message("") == ""


# ── SensitiveDataFilter Tests ─────────────────────────────


class TestSensitiveDataFilter:
    """Tests for SensitiveDataFilter logging filter."""

    def test_filter_masks_string_message(self):
        f = SensitiveDataFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Using Bearer abcdefghijklmnop",
            args=None,
            exc_info=None,
        )
        result = f.filter(record)
        assert result is True
        assert "****" in record.msg

    def test_filter_masks_dict_args(self):
        f = SensitiveDataFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test %s",
            args=({"app_key": "secretkey12345"},),
            exc_info=None,
        )
        result = f.filter(record)
        assert result is True

    def test_filter_masks_tuple_args_with_strings(self):
        f = SensitiveDataFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test %s %s",
            args=("normal", "Bearer abcdefghijklmnop"),
            exc_info=None,
        )
        result = f.filter(record)
        assert result is True

    def test_filter_non_string_msg_passthrough(self):
        f = SensitiveDataFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=42,
            args=None,
            exc_info=None,
        )
        result = f.filter(record)
        assert result is True
        assert record.msg == 42


# ── validate_platform_name Tests ───────────────────────────


class TestValidatePlatformName:
    """Tests for validate_platform_name function."""

    def test_valid_name(self):
        assert validate_platform_name("OCEANENGINE") == "OCEANENGINE"

    def test_valid_with_underscores(self):
        assert validate_platform_name("WEIXIN_STORE") == "WEIXIN_STORE"

    def test_valid_with_numbers(self):
        assert validate_platform_name("API2") == "API2"

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_platform_name("")

    def test_lowercase_raises(self):
        with pytest.raises(ValueError, match="uppercase"):
            validate_platform_name("oceanengine")

    def test_special_chars_raises(self):
        with pytest.raises(ValueError, match="uppercase"):
            validate_platform_name("OCEAN-ENGINE")

    def test_starts_with_number_raises(self):
        with pytest.raises(ValueError, match="uppercase"):
            validate_platform_name("1PLATFORM")

    def test_too_long_raises(self):
        with pytest.raises(ValueError, match="too long"):
            validate_platform_name("A" * 65)

    def test_exactly_64_chars(self):
        name = "A" * 64
        assert validate_platform_name(name) == name


# ── validate_api_param Tests ───────────────────────────────


class TestValidateApiParam:
    """Tests for validate_api_param function."""

    def test_valid_param(self):
        assert validate_api_param("page", "1") == "1"

    def test_normal_string(self):
        assert validate_api_param("name", "hello world") == "hello world"

    def test_non_string_passthrough(self):
        assert validate_api_param("count", 42) == 42

    def test_too_long_raises(self):
        with pytest.raises(ValueError, match="maximum length"):
            validate_api_param("data", "x" * 4097)

    def test_custom_max_length(self):
        with pytest.raises(ValueError, match="maximum length"):
            validate_api_param("data", "x" * 100, max_length=50)

    def test_sql_injection_union(self):
        with pytest.raises(ValueError, match="SQL"):
            validate_api_param("q", "1 UNION SELECT * FROM users")

    def test_sql_injection_comment(self):
        with pytest.raises(ValueError, match="SQL"):
            validate_api_param("q", "test' OR '1'='1")

    def test_sql_injection_drop(self):
        with pytest.raises(ValueError, match="SQL"):
            validate_api_param("q", "test; DROP TABLE users")

    def test_path_traversal(self):
        with pytest.raises(ValueError, match="path traversal"):
            validate_api_param("file", "../../etc/passwd")

    def test_path_traversal_encoded(self):
        with pytest.raises(ValueError, match="path traversal"):
            validate_api_param("file", "%2e%2e/etc/passwd")

    def test_xss_script_tag(self):
        with pytest.raises(ValueError, match="script"):
            validate_api_param("html", "<script>alert(1)</script>")

    def test_xss_javascript_uri(self):
        with pytest.raises(ValueError, match="script"):
            validate_api_param("url", "javascript:alert(1)")

    def test_xss_event_handler(self):
        with pytest.raises(ValueError, match="script"):
            validate_api_param("html", '<img onerror="alert(1)">')

    def test_xss_iframe(self):
        with pytest.raises(ValueError, match="script"):
            validate_api_param("html", "<iframe src='evil'>")

    def test_at_boundary_length(self):
        value = "a" * 4096
        assert validate_api_param("data", value) == value


# ── validate_env_var_name Tests ────────────────────────────


class TestValidateEnvVarName:
    """Tests for validate_env_var_name function."""

    def test_valid_name(self):
        assert validate_env_var_name("APP_KEY") == "APP_KEY"

    def test_simple_name(self):
        assert validate_env_var_name("HOME") == "HOME"

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_env_var_name("")

    def test_lowercase_raises(self):
        with pytest.raises(ValueError, match="uppercase"):
            validate_env_var_name("app_key")

    def test_starts_with_number_raises(self):
        with pytest.raises(ValueError, match="uppercase"):
            validate_env_var_name("1VAR")

    def test_hyphen_raises(self):
        with pytest.raises(ValueError, match="uppercase"):
            validate_env_var_name("APP-KEY")


# ── sanitize_log_context Tests ────────────────────────────


class TestSanitizeLogContext:
    """Tests for sanitize_log_context function."""

    def test_basic_context(self):
        result = sanitize_log_context(action="test", page=1)
        assert result["action"] == "test"
        assert result["page"] == 1

    def test_masks_sensitive_keys(self):
        result = sanitize_log_context(app_key="secretkey12345", name="test")
        assert result["name"] == "test"
        assert "****" in result["app_key"]

    def test_empty_context(self):
        result = sanitize_log_context()
        assert result == {}


# ── RetryableError Tests ──────────────────────────────────


class TestRetryableError:
    """Tests for RetryableError exception."""

    def test_attributes(self):
        original = ValueError("original error")
        err = RetryableError(original, attempt=2)
        assert err.original is original
        assert err.attempt == 2

    def test_message_format(self):
        original = ValueError("bad")
        err = RetryableError(original, attempt=1)
        assert "attempt 1" in str(err)
        assert "bad" in str(err)

    def test_is_exception(self):
        err = RetryableError(ValueError("x"), attempt=0)
        assert isinstance(err, Exception)


# ── RetryConfig Tests ─────────────────────────────────────


class TestRetryConfig:
    """Tests for RetryConfig dataclass."""

    def test_default_values(self):
        cfg = RetryConfig()
        assert cfg.max_retries == 3
        assert cfg.base_delay == 1.0
        assert cfg.max_delay == 60.0
        assert cfg.jitter is True

    def test_compute_delay_exponential(self):
        cfg = RetryConfig(base_delay=1.0, jitter=False)
        assert cfg.compute_delay(0) == 1.0
        assert cfg.compute_delay(1) == 2.0
        assert cfg.compute_delay(2) == 4.0

    def test_compute_delay_capped(self):
        cfg = RetryConfig(base_delay=1.0, max_delay=5.0, jitter=False)
        assert cfg.compute_delay(10) == 5.0

    def test_compute_delay_with_jitter(self):
        cfg = RetryConfig(base_delay=1.0, jitter=True)
        delays = [cfg.compute_delay(0) for _ in range(100)]
        # With jitter, delays should vary (not all be 1.0)
        assert len(set(delays)) > 1
        # But all should be between 0.5 and 1.5 (base_delay * (0.5 + random))
        for d in delays:
            assert 0.5 <= d <= 1.5

    def test_should_retry_http_status(self):
        cfg = RetryConfig()
        assert cfg.should_retry_http_status(429) is True
        assert cfg.should_retry_http_status(500) is True
        assert cfg.should_retry_http_status(502) is True
        assert cfg.should_retry_http_status(503) is True
        assert cfg.should_retry_http_status(504) is True
        assert cfg.should_retry_http_status(200) is False
        assert cfg.should_retry_http_status(400) is False
        assert cfg.should_retry_http_status(404) is False

    def test_should_retry_api_code(self):
        cfg = RetryConfig(retryable_api_codes={10001, 10002})
        assert cfg.should_retry_api_code(10001) is True
        assert cfg.should_retry_api_code(10002) is True
        assert cfg.should_retry_api_code(99999) is False

    def test_should_retry_exception_connect_error(self):
        cfg = RetryConfig()
        assert cfg.should_retry_exception(httpx.ConnectError("fail")) is True

    def test_should_retry_exception_read_timeout(self):
        cfg = RetryConfig()
        assert cfg.should_retry_exception(httpx.ReadTimeout("timeout")) is True

    def test_should_retry_exception_write_timeout(self):
        cfg = RetryConfig()
        assert cfg.should_retry_exception(httpx.WriteTimeout("timeout")) is True

    def test_should_retry_exception_pool_timeout(self):
        cfg = RetryConfig()
        assert cfg.should_retry_exception(httpx.PoolTimeout("timeout")) is True

    def test_should_not_retry_generic_exception(self):
        cfg = RetryConfig()
        assert cfg.should_retry_exception(ValueError("bad")) is False

    def test_should_retry_commerce_api_error_by_code(self):
        cfg = RetryConfig(retryable_api_codes={40001})
        err = CommerceAPIError(40001, "rate limited")
        assert cfg.should_retry_exception(err) is True

    def test_should_not_retry_commerce_api_error_unknown_code(self):
        cfg = RetryConfig(retryable_api_codes={40001})
        err = CommerceAPIError(99999, "unknown")
        assert cfg.should_retry_exception(err) is False

    def test_default_retry_config(self):
        assert DEFAULT_RETRY.max_retries == 3
        assert DEFAULT_RETRY.jitter is True

    def test_rate_limit_retry_config(self):
        assert RATE_LIMIT_RETRY.max_retries == 5
        assert RATE_LIMIT_RETRY.base_delay == 2.0
        assert RATE_LIMIT_RETRY.max_delay == 120.0

    def test_custom_retryable_exceptions(self):
        cfg = RetryConfig(retryable_exceptions=(ValueError,))
        assert cfg.should_retry_exception(ValueError("bad")) is True
        assert cfg.should_retry_exception(TypeError("bad")) is False


# ── with_retry Decorator Tests ────────────────────────────


class TestWithRetry:
    """Tests for with_retry decorator."""

    @pytest.mark.asyncio
    async def test_success_on_first_try(self):
        call_count = 0

        @with_retry(RetryConfig(max_retries=3, jitter=False))
        async def succeed():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await succeed()
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_retryable_error(self):
        call_count = 0

        @with_retry(RetryConfig(max_retries=3, base_delay=0.01, jitter=False))
        async def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise httpx.ConnectError("fail")
            return "ok"

        result = await fail_then_succeed()
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_raises_on_non_retryable_error(self):
        @with_retry(RetryConfig(max_retries=3, jitter=False))
        async def always_fail():
            raise ValueError("not retryable")

        with pytest.raises(ValueError, match="not retryable"):
            await always_fail()

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self):
        @with_retry(RetryConfig(max_retries=2, base_delay=0.01, jitter=False))
        async def always_connect_error():
            raise httpx.ConnectError("always fail")

        with pytest.raises(httpx.ConnectError):
            await always_connect_error()

    @pytest.mark.asyncio
    async def test_uses_default_config_when_none(self):
        call_count = 0

        @with_retry()
        async def succeed():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await succeed()
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_preserves_function_name(self):
        @with_retry(RetryConfig(max_retries=0))
        async def my_function():
            return "ok"

        assert my_function.__name__ == "my_function"


# ── CommerceMCPBase._get_client Tests ─────────────────────


class TestGetClient:
    """Tests for CommerceMCPBase._get_client."""

    def test_creates_client(self):
        client = CommerceMCPBase()
        http_client = client._get_client()
        assert isinstance(http_client, httpx.AsyncClient)
        assert not http_client.is_closed

    def test_reuses_existing_client(self):
        client = CommerceMCPBase()
        c1 = client._get_client()
        c2 = client._get_client()
        assert c1 is c2

    def test_recreates_closed_client(self):
        client = CommerceMCPBase()
        # Pre-set a mock closed client
        closed_client = MagicMock()
        closed_client.is_closed = True
        client._client = closed_client
        c2 = client._get_client()
        assert c2 is not closed_client
        assert isinstance(c2, httpx.AsyncClient)


# ── CommerceMCPBase.close Tests ────────────────────────────


class TestClose:
    """Tests for CommerceMCPBase.close."""

    @pytest.mark.asyncio
    async def test_close_with_active_client(self):
        client = CommerceMCPBase()
        _ = client._get_client()
        assert client._client is not None
        await client.close()
        assert client._client is None

    @pytest.mark.asyncio
    async def test_close_without_client(self):
        client = CommerceMCPBase()
        # Should not raise
        await client.close()
        assert client._client is None

    @pytest.mark.asyncio
    async def test_close_idempotent(self):
        client = CommerceMCPBase()
        _ = client._get_client()
        await client.close()
        # Second close should be safe
        await client.close()


# ── CommerceMCPBase._request Tests ────────────────────────


class TestRequest:
    """Tests for CommerceMCPBase._request."""

    @pytest.mark.asyncio
    async def test_successful_get_request(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": {"id": 1}}
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.is_closed = False

        with patch.object(client, "_ensure_client", return_value=mock_client):
            result = await client._request("GET", "/api/test")

        assert result == {"result": {"id": 1}}
        mock_client.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_successful_post_request(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": {"ok": True}}
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.is_closed = False

        with patch.object(client, "_ensure_client", return_value=mock_client):
            result = await client._request("POST", "/api/test", data={"key": "val"})

        assert result == {"result": {"ok": True}}
        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_api_error_response(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        mock_response = MagicMock()
        mock_response.json.return_value = {"error_response": {"code": 40001, "msg": "bad params"}}
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.is_closed = False

        with patch.object(client, "_ensure_client", return_value=mock_client):
            with pytest.raises(CommerceAPIError) as exc_info:
                await client._request("GET", "/api/test")
            assert exc_info.value.code == 40001
            assert exc_info.value.msg == "bad params"

    @pytest.mark.asyncio
    async def test_request_includes_auth_params(self):
        client = CommerceMCPBase(app_key="mykey", app_secret="mysecret", access_token="mytoken")
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": "ok"}
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.is_closed = False

        with patch.object(client, "_ensure_client", return_value=mock_client):
            await client._request("GET", "/api/test", params={"extra": "value"})

        # Check that auth params were included
        call_kwargs = mock_client.get.call_args
        passed_params = call_kwargs.kwargs.get("params", call_kwargs.args[1] if len(call_kwargs.args) > 1 else {})
        assert passed_params.get("app_key") == "mykey"
        assert passed_params.get("access_token") == "mytoken"
        assert passed_params.get("sign") is not None
        assert passed_params.get("timestamp") is not None

    @pytest.mark.asyncio
    async def test_request_without_access_token(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": "ok"}
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.is_closed = False

        with patch.object(client, "_ensure_client", return_value=mock_client):
            await client._request("GET", "/api/test")

        call_kwargs = mock_client.get.call_args
        passed_params = call_kwargs.kwargs.get("params", {})
        assert "access_token" not in passed_params

    @pytest.mark.asyncio
    async def test_request_with_retry_on_connect_error(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": "ok"}
        mock_response.status_code = 200
        mock_client = AsyncMock()
        call_count = 0

        async def get_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.ConnectError("connection refused")
            return mock_response

        mock_client.get.side_effect = get_side_effect
        mock_client.is_closed = False

        retry_config = RetryConfig(max_retries=2, base_delay=0.01, jitter=False)
        with patch.object(client, "_ensure_client", return_value=mock_client):
            result = await client._request("GET", "/api/test", retry_config=retry_config)

        assert result == {"result": "ok"}
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_request_no_retry_on_non_retryable_error(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        mock_client = AsyncMock()
        mock_client.get.side_effect = ValueError("not retryable")
        mock_client.is_closed = False

        retry_config = RetryConfig(max_retries=3, base_delay=0.01, jitter=False)
        with patch.object(client, "_ensure_client", return_value=mock_client):
            with pytest.raises(ValueError, match="not retryable"):
                await client._request("GET", "/api/test", retry_config=retry_config)

    @pytest.mark.asyncio
    async def test_request_retry_exhausted(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("always fail")
        mock_client.is_closed = False

        retry_config = RetryConfig(max_retries=2, base_delay=0.01, jitter=False)
        with patch.object(client, "_ensure_client", return_value=mock_client):
            with pytest.raises(httpx.ConnectError):
                await client._request("GET", "/api/test", retry_config=retry_config)

    @pytest.mark.asyncio
    async def test_request_retry_on_api_error_with_retryable_code(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        call_count = 0

        def make_response(data):
            resp = MagicMock()
            resp.json.return_value = data
            resp.status_code = 200
            return resp

        async def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return make_response({"error_response": {"code": 40001, "msg": "retryable"}})
            return make_response({"result": "ok"})

        mock_client = AsyncMock()
        mock_client.get.side_effect = mock_get
        mock_client.is_closed = False

        retry_config = RetryConfig(
            max_retries=2,
            base_delay=0.01,
            jitter=False,
            retryable_api_codes={40001},
        )
        with patch.object(client, "_ensure_client", return_value=mock_client):
            result = await client._request("GET", "/api/test", retry_config=retry_config)

        assert result == {"result": "ok"}
        assert call_count == 2


# ── CommerceMCPBase._sign Unknown Method Test ─────────────


class TestSignUnknownMethod:
    """Tests for _sign with unknown sign method."""

    def test_sign_unknown_method_raises(self):
        client = CommerceMCPBase(app_secret="s")
        client.sign_method = "unknown_method"
        with pytest.raises(ValueError, match="Unknown sign method"):
            client._sign({"app_key": "k"})


# ── format_response Tests ─────────────────────────────────


class TestFormatResponse:
    """Tests for format_response function."""

    def test_dict_response(self):
        result = format_response({"key": "value"})
        parsed = json.loads(result)
        assert parsed["key"] == "value"

    def test_list_response(self):
        result = format_response([1, 2, 3])
        parsed = json.loads(result)
        assert parsed == [1, 2, 3]

    def test_string_passthrough(self):
        result = format_response("already a string")
        assert result == "already a string"

    def test_pretty_printed(self):
        result = format_response({"key": "value"})
        assert "\n" in result
        assert "  " in result

    def test_none_value(self):
        result = format_response(None)
        assert result == "null"

    def test_nested_structure(self):
        data = {"a": {"b": [1, 2, {"c": 3}]}}
        result = format_response(data)
        parsed = json.loads(result)
        assert parsed == data


# ── handle_tool_errors Tests ──────────────────────────────


class TestHandleToolErrors:
    """Tests for handle_tool_errors decorator."""

    @pytest.mark.asyncio
    async def test_success_dict(self):
        @handle_tool_errors
        async def my_tool():
            return {"key": "value"}

        result = await my_tool()
        parsed = json.loads(result)
        assert parsed["key"] == "value"

    @pytest.mark.asyncio
    async def test_success_string(self):
        @handle_tool_errors
        async def my_tool():
            return "raw string"

        result = await my_tool()
        assert result == "raw string"

    @pytest.mark.asyncio
    async def test_commerce_api_error(self):
        @handle_tool_errors
        async def my_tool():
            raise CommerceAPIError(40001, "Invalid params")

        result = await my_tool()
        parsed = json.loads(result)
        assert parsed["error"]["code"] == 40001
        assert parsed["error"]["message"] == "Invalid params"

    @pytest.mark.asyncio
    async def test_json_decode_error(self):
        @handle_tool_errors
        async def my_tool():
            raise json.JSONDecodeError("bad json", "", 0)

        result = await my_tool()
        parsed = json.loads(result)
        assert "Invalid JSON" in parsed["error"]["message"]

    @pytest.mark.asyncio
    async def test_generic_exception(self):
        @handle_tool_errors
        async def my_tool():
            raise RuntimeError("something broke")

        result = await my_tool()
        parsed = json.loads(result)
        assert parsed["error"]["message"] == "something broke"

    @pytest.mark.asyncio
    async def test_preserves_function_name(self):
        @handle_tool_errors
        async def my_named_tool():
            return "ok"

        assert my_named_tool.__name__ == "my_named_tool"

    @pytest.mark.asyncio
    async def test_preserves_function_doc(self):
        """Docstring should be preserved by functools.wraps."""

        @handle_tool_errors
        async def my_documented_tool():
            """This is my doc."""
            return "ok"

        assert my_documented_tool.__doc__ == "This is my doc."


# ── Concurrency Tests ─────────────────────────────────────


class TestMetricsCollectorConcurrency:
    """Thread-safety tests for MetricsCollector."""

    def test_concurrent_record_requests(self):
        """Multiple threads recording requests should not lose data."""
        import threading

        collector = MetricsCollector()
        num_threads = 10
        requests_per_thread = 100

        def record_batch():
            for _ in range(requests_per_thread):
                collector.record_request("/api/test", latency_ms=10.0, success=True)

        threads = [threading.Thread(target=record_batch) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        g = collector.get_global_metrics()
        assert g.request_count == num_threads * requests_per_thread

    def test_concurrent_record_with_errors(self):
        """Mixing successes and failures across threads."""
        import threading

        collector = MetricsCollector()

        def record_success():
            for _ in range(50):
                collector.record_request("/api/test", latency_ms=10.0, success=True)

        def record_failure():
            for _ in range(50):
                collector.record_request("/api/test", latency_ms=10.0, success=False, error_code=500, error_msg="err")

        threads = [
            threading.Thread(target=record_success),
            threading.Thread(target=record_failure),
            threading.Thread(target=record_success),
            threading.Thread(target=record_failure),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        g = collector.get_global_metrics()
        assert g.request_count == 200
        assert g.error_count == 100

    def test_concurrent_get_summary(self):
        """get_summary while recording should not raise."""
        import threading

        collector = MetricsCollector()
        errors = []

        def record():
            for _ in range(100):
                collector.record_request("/api", latency_ms=5.0, success=True)

        def summarize():
            for _ in range(100):
                try:
                    collector.get_summary()
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=record), threading.Thread(target=summarize)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []


# ── Health Check Success Path ──────────────────────────────


class TestHealthCheckSuccess:
    """Tests for health_check when API is reachable."""

    @pytest.mark.asyncio
    async def test_health_check_api_reachable(self):
        client = CommerceMCPBase(app_key="k", app_secret="s", access_token="t")
        client.BASE_URL = "http://api.example.com"

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.head.return_value = mock_response

        with patch.object(client, "_ensure_client", return_value=mock_client):
            result = await client.health_check(use_cache=False)

        assert result["configured"] is True
        assert result["has_token"] is True
        assert result["api_reachable"] is True
        assert "metrics" in result

    @pytest.mark.asyncio
    async def test_health_check_server_error(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        client.BASE_URL = "http://api.example.com"

        mock_response = AsyncMock()
        mock_response.status_code = 500
        mock_client = AsyncMock()
        mock_client.head.return_value = mock_response

        with patch.object(client, "_ensure_client", return_value=mock_client):
            result = await client.health_check(use_cache=False)

        assert result["api_reachable"] is False


# ── _sign Deterministic Tests ─────────────────────────────


class TestSignDeterministic:
    """Verify that signing is deterministic for the same input."""

    def test_md5_deterministic(self):
        client = CommerceMCPBase(app_secret="secret")
        client.sign_method = SignMethod.MD5
        params = {"app_key": "k", "timestamp": "123"}
        sig1 = client._sign(params)
        sig2 = client._sign(params)
        assert sig1 == sig2

    def test_hmac_sha256_deterministic(self):
        client = CommerceMCPBase(app_secret="secret")
        client.sign_method = SignMethod.HMAC_SHA256
        params = {"app_key": "k", "timestamp": "123"}
        sig1 = client._sign(params)
        sig2 = client._sign(params)
        assert sig1 == sig2

    def test_different_secrets_produce_different_sigs(self):
        c1 = CommerceMCPBase(app_secret="secret1")
        c1.sign_method = SignMethod.MD5
        c2 = CommerceMCPBase(app_secret="secret2")
        c2.sign_method = SignMethod.MD5
        params = {"app_key": "k", "timestamp": "123"}
        assert c1._sign(params) != c2._sign(params)

    def test_sign_uppercase_hex(self):
        client = CommerceMCPBase(app_secret="s")
        client.sign_method = SignMethod.MD5
        sig = client._sign({"app_key": "k"})
        assert sig == sig.upper()
        assert all(c in "0123456789ABCDEF" for c in sig)

    def test_sign_sorts_keys(self):
        """Params with different key orders should produce the same signature."""
        client = CommerceMCPBase(app_secret="s")
        client.sign_method = SignMethod.MD5
        sig1 = client._sign({"b": "2", "a": "1"})
        sig2 = client._sign({"a": "1", "b": "2"})
        assert sig1 == sig2

    def test_sign_excludes_empty_values(self):
        """Empty string values should be excluded from signing."""
        client = CommerceMCPBase(app_secret="s")
        client.sign_method = SignMethod.MD5
        sig1 = client._sign({"a": "1", "b": ""})
        sig2 = client._sign({"a": "1"})
        assert sig1 == sig2


# ── EndpointRateLimit Tests ─────────────────────────────────


class TestEndpointRateLimit:
    """Tests for EndpointRateLimit dataclass."""

    def test_default_values(self):
        ep = EndpointRateLimit(endpoint="/api/test")
        assert ep.endpoint == "/api/test"
        assert ep.requests_per_second == 10.0
        assert ep.burst_size == 1
        assert ep.cooldown_seconds == 0.0

    def test_custom_values(self):
        ep = EndpointRateLimit(
            endpoint="/api/order/search",
            requests_per_second=2.0,
            burst_size=5,
            cooldown_seconds=1.0,
        )
        assert ep.endpoint == "/api/order/search"
        assert ep.requests_per_second == 2.0
        assert ep.burst_size == 5
        assert ep.cooldown_seconds == 1.0


# ── PlatformRateLimitConfig Tests ───────────────────────────


class TestPlatformRateLimitConfig:
    """Tests for PlatformRateLimitConfig dataclass."""

    def test_default_values(self):
        cfg = PlatformRateLimitConfig(platform="OCEANENGINE")
        assert cfg.platform == "OCEANENGINE"
        assert cfg.default_requests_per_second == 10.0
        assert cfg.endpoints == {}
        assert cfg.burst_size == 1
        assert cfg.enabled is True

    def test_get_endpoint_limit_fallback(self):
        """Should return platform default when endpoint is not configured."""
        cfg = PlatformRateLimitConfig(
            platform="TAOBAO",
            default_requests_per_second=5.0,
            burst_size=3,
        )
        ep = cfg.get_endpoint_limit("/api/unknown")
        assert ep.endpoint == "/api/unknown"
        assert ep.requests_per_second == 5.0
        assert ep.burst_size == 3

    def test_get_endpoint_limit_specific(self):
        """Should return endpoint-specific config when available."""
        cfg = PlatformRateLimitConfig(
            platform="TAOBAO",
            default_requests_per_second=10.0,
            endpoints={
                "/api/order/search": EndpointRateLimit(
                    endpoint="/api/order/search",
                    requests_per_second=2.0,
                ),
            },
        )
        ep = cfg.get_endpoint_limit("/api/order/search")
        assert ep.requests_per_second == 2.0

    def test_disabled_platform(self):
        cfg = PlatformRateLimitConfig(platform="TEST", enabled=False)
        assert cfg.enabled is False


# ── RateLimitStats Tests ────────────────────────────────────


class TestRateLimitStats:
    """Tests for RateLimitStats dataclass."""

    def test_default_values(self):
        stats = RateLimitStats()
        assert stats.total_requests == 0
        assert stats.total_throttled == 0
        assert stats.total_wait_time_ms == 0.0
        assert stats.platform_stats == {}
        assert stats.endpoint_stats == {}

    def test_throttle_rate_no_requests(self):
        stats = RateLimitStats()
        assert stats.throttle_rate == 0.0

    def test_throttle_rate_with_requests(self):
        stats = RateLimitStats()
        stats.record_throttle("TEST", "/api", 100.0)
        stats.record_request("TEST", "/api")
        stats.record_request("TEST", "/api")
        assert stats.throttle_rate == pytest.approx(1 / 3)

    def test_avg_wait_time_ms(self):
        stats = RateLimitStats()
        assert stats.avg_wait_time_ms == 0.0
        stats.record_throttle("TEST", "/api", 100.0)
        stats.record_throttle("TEST", "/api", 200.0)
        assert stats.avg_wait_time_ms == pytest.approx(150.0)

    def test_record_throttle(self):
        stats = RateLimitStats()
        stats.record_throttle("OCEANENGINE", "/api/order", 50.0)
        assert stats.total_requests == 1
        assert stats.total_throttled == 1
        assert stats.total_wait_time_ms == 50.0
        assert stats.last_throttled_at > 0
        assert "OCEANENGINE" in stats.platform_stats
        assert "OCEANENGINE:/api/order" in stats.endpoint_stats

    def test_record_request(self):
        stats = RateLimitStats()
        stats.record_request("TAOBAO", "/api/product")
        assert stats.total_requests == 1
        assert stats.total_throttled == 0
        assert "TAOBAO" in stats.platform_stats
        assert "TAOBAO:/api/product" in stats.endpoint_stats

    def test_get_summary_structure(self):
        stats = RateLimitStats()
        stats.record_throttle("TEST", "/api", 100.0)
        stats.record_request("TEST", "/api")
        summary = stats.get_summary()
        assert "global" in summary
        assert "platforms" in summary
        assert "endpoints" in summary
        assert summary["global"]["total_requests"] == 2
        assert summary["global"]["total_throttled"] == 1

    def test_reset(self):
        stats = RateLimitStats()
        stats.record_throttle("TEST", "/api", 100.0)
        stats.record_request("TEST", "/api")
        stats.reset()
        assert stats.total_requests == 0
        assert stats.total_throttled == 0
        assert stats.total_wait_time_ms == 0.0
        assert stats.platform_stats == {}
        assert stats.endpoint_stats == {}
        assert stats.last_throttled_at == 0.0

    def test_platform_stats_accumulation(self):
        stats = RateLimitStats()
        stats.record_request("P1", "/a")
        stats.record_request("P1", "/b")
        stats.record_throttle("P1", "/a", 50.0)
        stats.record_request("P2", "/a")
        assert stats.platform_stats["P1"]["requests"] == 3
        assert stats.platform_stats["P1"]["throttled"] == 1
        assert stats.platform_stats["P2"]["requests"] == 1


# ── RateLimitConfig Tests ───────────────────────────────────


class TestRateLimitConfig:
    """Tests for RateLimitConfig dataclass."""

    def test_default_values(self):
        cfg = RateLimitConfig()
        assert cfg.platforms == {}
        assert cfg.default_requests_per_second == 10.0
        assert cfg.default_burst_size == 1
        assert cfg.enabled is True

    def test_get_platform_config_existing(self):
        p_cfg = PlatformRateLimitConfig(platform="TEST", default_requests_per_second=5.0)
        cfg = RateLimitConfig(platforms={"TEST": p_cfg})
        result = cfg.get_platform_config("TEST")
        assert result is p_cfg
        assert result.default_requests_per_second == 5.0

    def test_get_platform_config_default(self):
        """Should create default config for unknown platforms."""
        cfg = RateLimitConfig(default_requests_per_second=15.0, default_burst_size=3)
        result = cfg.get_platform_config("UNKNOWN")
        assert result.platform == "UNKNOWN"
        assert result.default_requests_per_second == 15.0
        assert result.burst_size == 3
        assert result.enabled is True

    def test_get_platform_config_global_enabled(self):
        cfg = RateLimitConfig(enabled=False)
        result = cfg.get_platform_config("TEST")
        assert result.enabled is False

    def test_to_dict(self):
        cfg = RateLimitConfig(
            default_requests_per_second=5.0,
            platforms={
                "TEST": PlatformRateLimitConfig(
                    platform="TEST",
                    default_requests_per_second=3.0,
                    endpoints={
                        "/api": EndpointRateLimit(
                            endpoint="/api",
                            requests_per_second=1.0,
                        ),
                    },
                ),
            },
        )
        d = cfg.to_dict()
        assert d["enabled"] is True
        assert d["default_requests_per_second"] == 5.0
        assert "TEST" in d["platforms"]
        assert d["platforms"]["TEST"]["default_requests_per_second"] == 3.0
        assert "/api" in d["platforms"]["TEST"]["endpoints"]

    def test_from_dict(self):
        data = {
            "enabled": True,
            "default_requests_per_second": 10.0,
            "default_burst_size": 2,
            "platforms": {
                "OCEANENGINE": {
                    "platform": "OCEANENGINE",
                    "default_requests_per_second": 5.0,
                    "burst_size": 3,
                    "enabled": True,
                    "endpoints": {
                        "/api/order": {
                            "endpoint": "/api/order",
                            "requests_per_second": 2.0,
                            "burst_size": 1,
                            "cooldown_seconds": 0.5,
                        },
                    },
                },
            },
        }
        cfg = RateLimitConfig.from_dict(data)
        assert cfg.default_requests_per_second == 10.0
        assert cfg.default_burst_size == 2
        assert "OCEANENGINE" in cfg.platforms
        p = cfg.platforms["OCEANENGINE"]
        assert p.default_requests_per_second == 5.0
        assert p.burst_size == 3
        assert "/api/order" in p.endpoints
        ep = p.endpoints["/api/order"]
        assert ep.requests_per_second == 2.0
        assert ep.cooldown_seconds == 0.5

    def test_from_dict_empty(self):
        cfg = RateLimitConfig.from_dict({})
        assert cfg.default_requests_per_second == 10.0
        assert cfg.platforms == {}

    def test_roundtrip(self):
        """to_dict -> from_dict should preserve configuration."""
        original = RateLimitConfig(
            default_requests_per_second=7.0,
            platforms={
                "TEST": PlatformRateLimitConfig(
                    platform="TEST",
                    default_requests_per_second=3.0,
                    endpoints={
                        "/api": EndpointRateLimit(endpoint="/api", requests_per_second=1.5),
                    },
                ),
            },
        )
        d = original.to_dict()
        restored = RateLimitConfig.from_dict(d)
        assert restored.default_requests_per_second == 7.0
        assert "TEST" in restored.platforms
        assert restored.platforms["TEST"].default_requests_per_second == 3.0
        assert restored.platforms["TEST"].endpoints["/api"].requests_per_second == 1.5


# ── ConfigurableRateLimiter Tests ───────────────────────────


class TestConfigurableRateLimiter:
    """Tests for ConfigurableRateLimiter."""

    def test_default_init(self):
        limiter = ConfigurableRateLimiter()
        assert limiter.config is not None
        assert limiter.stats is not None

    def test_custom_config(self):
        config = RateLimitConfig(default_requests_per_second=5.0)
        limiter = ConfigurableRateLimiter(config)
        assert limiter.config.default_requests_per_second == 5.0

    @pytest.mark.asyncio
    async def test_acquire_basic(self):
        limiter = ConfigurableRateLimiter()
        await limiter.acquire("TEST", "/api/test")
        assert limiter.stats.total_requests >= 1

    @pytest.mark.asyncio
    async def test_acquire_disabled_platform(self):
        config = RateLimitConfig(
            platforms={
                "TEST": PlatformRateLimitConfig(platform="TEST", enabled=False),
            },
        )
        limiter = ConfigurableRateLimiter(config)
        await limiter.acquire("TEST", "/api/test")
        assert limiter.stats.total_requests == 1
        assert limiter.stats.total_throttled == 0

    @pytest.mark.asyncio
    async def test_acquire_disabled_global(self):
        config = RateLimitConfig(enabled=False)
        limiter = ConfigurableRateLimiter(config)
        await limiter.acquire("TEST", "/api/test")
        assert limiter.stats.total_requests == 1
        assert limiter.stats.total_throttled == 0

    @pytest.mark.asyncio
    async def test_acquire_multiple_platforms(self):
        config = RateLimitConfig(
            platforms={
                "P1": PlatformRateLimitConfig(platform="P1", default_requests_per_second=100.0),
                "P2": PlatformRateLimitConfig(platform="P2", default_requests_per_second=100.0),
            },
        )
        limiter = ConfigurableRateLimiter(config)
        await limiter.acquire("P1", "/api")
        await limiter.acquire("P2", "/api")
        assert limiter.stats.total_requests >= 2

    def test_update_platform_config(self):
        config = RateLimitConfig(
            platforms={
                "TEST": PlatformRateLimitConfig(platform="TEST", default_requests_per_second=5.0),
            },
        )
        limiter = ConfigurableRateLimiter(config)
        new_config = PlatformRateLimitConfig(platform="TEST", default_requests_per_second=20.0)
        limiter.update_platform_config("TEST", new_config)
        assert limiter.config.platforms["TEST"].default_requests_per_second == 20.0

    def test_update_endpoint_limit(self):
        config = RateLimitConfig(
            platforms={
                "TEST": PlatformRateLimitConfig(platform="TEST", default_requests_per_second=10.0),
            },
        )
        limiter = ConfigurableRateLimiter(config)
        limiter.update_endpoint_limit("TEST", "/api/slow", requests_per_second=1.0)
        assert limiter.config.platforms["TEST"].endpoints["/api/slow"].requests_per_second == 1.0

    def test_update_endpoint_limit_creates_platform(self):
        """update_endpoint_limit should create platform config if missing."""
        limiter = ConfigurableRateLimiter()
        limiter.update_endpoint_limit("NEW_PLATFORM", "/api", requests_per_second=5.0)
        assert "NEW_PLATFORM" in limiter.config.platforms
        assert limiter.config.platforms["NEW_PLATFORM"].endpoints["/api"].requests_per_second == 5.0

    def test_get_stats_summary(self):
        limiter = ConfigurableRateLimiter()
        summary = limiter.get_stats_summary()
        assert "config" in summary
        assert "stats" in summary

    def test_reset_stats(self):
        limiter = ConfigurableRateLimiter()
        limiter.stats.record_throttle("TEST", "/api", 100.0)
        limiter.reset_stats()
        assert limiter.stats.total_requests == 0

    @pytest.mark.asyncio
    async def test_acquire_with_endpoint_config(self):
        config = RateLimitConfig(
            platforms={
                "TEST": PlatformRateLimitConfig(
                    platform="TEST",
                    default_requests_per_second=100.0,
                    endpoints={
                        "/api/slow": EndpointRateLimit(
                            endpoint="/api/slow",
                            requests_per_second=100.0,
                        ),
                    },
                ),
            },
        )
        limiter = ConfigurableRateLimiter(config)
        await limiter.acquire("TEST", "/api/slow")
        await limiter.acquire("TEST", "/api/fast")
        assert limiter.stats.total_requests >= 2


# ── HealthCheckResult Tests ────────────────────────────────


class TestHealthCheckResult:
    """Tests for HealthCheckResult dataclass."""

    def test_default_values(self):
        result = HealthCheckResult()
        assert result.status == "unhealthy"
        assert result.configured is False
        assert result.has_token is False
        assert result.api_reachable is False
        assert result.latency_ms == 0.0
        assert result.dependencies == {}
        assert result.cached is False
        assert result.error == ""

    def test_timestamp_auto_generated(self):
        result = HealthCheckResult()
        assert result.timestamp != ""
        assert "T" in result.timestamp  # ISO 8601

    def test_custom_values(self):
        result = HealthCheckResult(
            status="healthy",
            configured=True,
            has_token=True,
            api_reachable=True,
            latency_ms=42.5,
        )
        assert result.status == "healthy"
        assert result.configured is True
        assert result.latency_ms == 42.5

    def test_to_dict(self):
        result = HealthCheckResult(status="healthy", configured=True)
        d = result.to_dict()
        assert d["status"] == "healthy"
        assert d["configured"] is True
        assert "timestamp" in d
        assert "latency_ms" in d
        assert isinstance(d["latency_ms"], float)

    def test_to_dict_latency_rounded(self):
        result = HealthCheckResult(latency_ms=42.567)
        d = result.to_dict()
        assert d["latency_ms"] == 42.57


# ── HealthCheckCache Tests ─────────────────────────────────


class TestHealthCheckCache:
    """Tests for HealthCheckCache."""

    def test_get_miss(self):
        cache = HealthCheckCache(ttl_seconds=30)
        assert cache.get("nonexistent") is None

    def test_set_and_get(self):
        cache = HealthCheckCache(ttl_seconds=30)
        result = HealthCheckResult(status="healthy", configured=True)
        cache.set("test", result)
        cached = cache.get("test")
        assert cached is not None
        assert cached.status == "healthy"
        assert cached.cached is True

    def test_get_expired(self):
        cache = HealthCheckCache(ttl_seconds=0)
        result = HealthCheckResult(status="healthy")
        cache.set("test", result)
        time.sleep(0.01)
        assert cache.get("test") is None

    def test_invalidate_specific(self):
        cache = HealthCheckCache(ttl_seconds=30)
        cache.set("a", HealthCheckResult(status="healthy"))
        cache.set("b", HealthCheckResult(status="degraded"))
        cache.invalidate("a")
        assert cache.get("a") is None
        assert cache.get("b") is not None

    def test_invalidate_all(self):
        cache = HealthCheckCache(ttl_seconds=30)
        cache.set("a", HealthCheckResult(status="healthy"))
        cache.set("b", HealthCheckResult(status="degraded"))
        cache.invalidate()
        assert cache.get("a") is None
        assert cache.get("b") is None

    def test_invalidate_nonexistent(self):
        cache = HealthCheckCache(ttl_seconds=30)
        cache.invalidate("nonexistent")

    def test_get_stats(self):
        cache = HealthCheckCache(ttl_seconds=30)
        cache.set("a", HealthCheckResult())
        cache.set("b", HealthCheckResult())
        stats = cache.get_stats()
        assert stats["entry_count"] == 2
        assert stats["ttl_seconds"] == 30
        assert "a" in stats["keys"]
        assert "b" in stats["keys"]

    def test_get_stats_excludes_expired(self):
        cache = HealthCheckCache(ttl_seconds=0)
        cache.set("a", HealthCheckResult())
        time.sleep(0.01)
        stats = cache.get_stats()
        assert stats["entry_count"] == 0


# ── Enhanced Health Check Tests ────────────────────────────


class TestEnhancedHealthCheck:
    """Tests for the enhanced health_check method."""

    @pytest.mark.asyncio
    async def test_health_check_returns_status_field(self):
        client = CommerceMCPBase(app_key="k", app_secret="s", access_token="t")
        client.BASE_URL = "http://api.example.com"
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.head.return_value = mock_response
        with patch.object(client, "_ensure_client", return_value=mock_client):
            result = await client.health_check(use_cache=False)
        assert "status" in result
        assert result["status"] in ("healthy", "degraded", "unhealthy")

    @pytest.mark.asyncio
    async def test_health_check_healthy_status(self):
        client = CommerceMCPBase(app_key="k", app_secret="s", access_token="t")
        client.BASE_URL = "http://api.example.com"
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.head.return_value = mock_response
        with patch.object(client, "_ensure_client", return_value=mock_client):
            result = await client.health_check(use_cache=False)
        assert result["status"] == "healthy"
        assert result["configured"] is True
        assert result["has_token"] is True
        assert result["api_reachable"] is True

    @pytest.mark.asyncio
    async def test_health_check_degraded_status(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        client.BASE_URL = "http://api.example.com"
        mock_response = AsyncMock()
        mock_response.status_code = 500
        mock_client = AsyncMock()
        mock_client.head.return_value = mock_response
        with patch.object(client, "_ensure_client", return_value=mock_client):
            result = await client.health_check(use_cache=False)
        assert result["status"] == "degraded"

    @pytest.mark.asyncio
    async def test_health_check_unhealthy_status(self):
        client = CommerceMCPBase()
        result = await client.health_check(use_cache=False)
        assert result["status"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_health_check_with_cache(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        client.BASE_URL = "http://api.example.com"
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.head.return_value = mock_response
        with patch.object(client, "_ensure_client", return_value=mock_client):
            result1 = await client.health_check(use_cache=True, cache_key="test")
            result2 = await client.health_check(use_cache=True, cache_key="test")
        assert result2.get("cached") is True

    @pytest.mark.asyncio
    async def test_health_check_latency_ms(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        result = await client.health_check(use_cache=False)
        assert "latency_ms" in result
        assert isinstance(result["latency_ms"], float)

    @pytest.mark.asyncio
    async def test_health_check_connection_error(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        client.BASE_URL = "http://127.0.0.1:99999"
        mock_client = AsyncMock()
        mock_client.head.side_effect = httpx.ConnectError("refused")
        with patch.object(client, "_ensure_client", return_value=mock_client):
            result = await client.health_check(use_cache=False)
        assert result["api_reachable"] is False
        assert result["status"] == "degraded"
        assert "error" in result


# ── Deep Health Check Tests ────────────────────────────────


class TestDeepHealthCheck:
    """Tests for deep_health_check method."""

    @pytest.mark.asyncio
    async def test_deep_health_check_no_deps(self):
        client = CommerceMCPBase(app_key="k", app_secret="s", access_token="t")
        client.BASE_URL = "http://api.example.com"
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.head.return_value = mock_response
        with patch.object(client, "_ensure_client", return_value=mock_client):
            result = await client.deep_health_check()
        assert result["status"] == "healthy"
        assert result["dependencies"] == {}

    @pytest.mark.asyncio
    async def test_deep_health_check_with_url_dep(self):
        client = CommerceMCPBase(app_key="k", app_secret="s", access_token="t")
        client.BASE_URL = "http://api.example.com"
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.head.return_value = mock_response
        with patch.object(client, "_ensure_client", return_value=mock_client):
            result = await client.deep_health_check(
                dependencies=["https://dep.example.com"]
            )
        assert "https://dep.example.com" in result["dependencies"]
        dep = result["dependencies"]["https://dep.example.com"]
        assert dep["reachable"] is True
        assert dep["status_code"] == 200

    @pytest.mark.asyncio
    async def test_deep_health_check_with_named_dep(self):
        client = CommerceMCPBase(app_key="k", app_secret="s", access_token="t")
        client.BASE_URL = "http://api.example.com"
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.head.return_value = mock_response
        with patch.object(client, "_ensure_client", return_value=mock_client):
            result = await client.deep_health_check(
                dependencies=["AUTH_SERVICE"]
            )
        assert "AUTH_SERVICE" in result["dependencies"]
        dep = result["dependencies"]["AUTH_SERVICE"]
        assert dep["reachable"] is True

    @pytest.mark.asyncio
    async def test_deep_health_check_dep_error(self):
        client = CommerceMCPBase(app_key="k", app_secret="s", access_token="t")
        client.BASE_URL = "http://api.example.com"
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_client = AsyncMock()

        async def head_side_effect(url, **kwargs):
            if "dep.example.com" in str(url):
                raise httpx.ConnectError("dep unreachable")
            return mock_response

        mock_client.head.side_effect = head_side_effect
        with patch.object(client, "_ensure_client", return_value=mock_client):
            result = await client.deep_health_check(
                dependencies=["https://dep.example.com"]
            )
        dep = result["dependencies"]["https://dep.example.com"]
        assert dep["reachable"] is False
        assert "error" in dep

    @pytest.mark.asyncio
    async def test_deep_health_check_degraded_when_dep_fails(self):
        client = CommerceMCPBase(app_key="k", app_secret="s", access_token="t")
        client.BASE_URL = "http://api.example.com"
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_client = AsyncMock()

        async def head_side_effect(url, **kwargs):
            if "dep.example.com" in str(url):
                raise httpx.ConnectError("dep unreachable")
            return mock_response

        mock_client.head.side_effect = head_side_effect
        with patch.object(client, "_ensure_client", return_value=mock_client):
            result = await client.deep_health_check(
                dependencies=["https://dep.example.com"]
            )
        assert result["status"] == "degraded"

    @pytest.mark.asyncio
    async def test_deep_health_check_has_latency(self):
        client = CommerceMCPBase(app_key="k", app_secret="s", access_token="t")
        client.BASE_URL = "http://api.example.com"
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.head.return_value = mock_response
        with patch.object(client, "_ensure_client", return_value=mock_client):
            result = await client.deep_health_check()
        assert "latency_ms" in result
        assert result["latency_ms"] > 0


# ── ConfigRule Tests ───────────────────────────────────────


class TestConfigRule:
    """Tests for ConfigRule dataclass."""

    def test_basic_creation(self):
        rule = ConfigRule("APP_KEY", required=True)
        assert rule.key == "APP_KEY"
        assert rule.required is True
        assert rule.value_type == "str"
        assert rule.depends_on == []

    def test_all_options(self):
        rule = ConfigRule(
            "PORT",
            required=True,
            value_type="int",
            min_value=1,
            max_value=65535,
            depends_on=["HOST"],
            description="Server port",
        )
        assert rule.key == "PORT"
        assert rule.value_type == "int"
        assert rule.min_value == 1
        assert rule.max_value == 65535
        assert rule.depends_on == ["HOST"]
        assert rule.description == "Server port"

    def test_default_description(self):
        rule = ConfigRule("APP_KEY")
        assert rule.description == "APP_KEY"

    def test_allowed_values(self):
        rule = ConfigRule("MODE", allowed_values=["prod", "dev", "staging"])
        assert rule.allowed_values == ["prod", "dev", "staging"]

    def test_pattern(self):
        rule = ConfigRule("VERSION", pattern=r"^\d+\.\d+\.\d+$")
        assert rule.pattern == r"^\d+\.\d+\.\d+$"


# ── ConfigValidationResult Tests ───────────────────────────


class TestConfigValidationResult:
    """Tests for ConfigValidationResult."""

    def test_default_valid(self):
        result = ConfigValidationResult()
        assert result.valid is True
        assert result.errors == []
        assert result.warnings == []

    def test_add_error(self):
        result = ConfigValidationResult()
        result.add_error("Something is wrong")
        assert result.valid is False
        assert "Something is wrong" in result.errors

    def test_add_warning(self):
        result = ConfigValidationResult()
        result.add_warning("Consider updating")
        assert result.valid is True
        assert "Consider updating" in result.warnings

    def test_to_dict(self):
        result = ConfigValidationResult()
        result.add_error("err1")
        result.add_warning("warn1")
        d = result.to_dict()
        assert d["valid"] is False
        assert d["error_count"] == 1
        assert d["warning_count"] == 1
        assert "err1" in d["errors"]


# ── ConfigValidator Tests ──────────────────────────────────


class TestConfigValidator:
    """Tests for ConfigValidator."""

    def test_add_rule(self):
        validator = ConfigValidator("TEST")
        validator.add_rule(ConfigRule("APP_KEY", required=True))
        assert "APP_KEY" in validator.get_rules()

    def test_add_rules(self):
        validator = ConfigValidator("TEST")
        validator.add_rules([
            ConfigRule("APP_KEY"),
            ConfigRule("APP_SECRET"),
        ])
        assert len(validator.get_rules()) == 2

    def test_validate_required_present(self):
        validator = ConfigValidator("TEST")
        validator.add_rule(ConfigRule("APP_KEY", required=True))
        result = validator.validate({"APP_KEY": "my_key"})
        assert result.valid is True

    def test_validate_required_missing(self):
        validator = ConfigValidator("TEST")
        validator.add_rule(ConfigRule("APP_KEY", required=True))
        result = validator.validate({})
        assert result.valid is False
        assert len(result.missing_keys) == 1

    def test_validate_optional_missing_ok(self):
        validator = ConfigValidator("TEST")
        validator.add_rule(ConfigRule("OPTIONAL_KEY", required=False))
        result = validator.validate({})
        assert result.valid is True

    def test_validate_type_str(self):
        validator = ConfigValidator("TEST")
        validator.add_rule(ConfigRule("NAME", value_type="str"))
        assert validator.validate({"NAME": "hello"}).valid is True
        result = validator.validate({"NAME": 123})
        assert result.valid is False

    def test_validate_type_int(self):
        validator = ConfigValidator("TEST")
        validator.add_rule(ConfigRule("PORT", value_type="int"))
        assert validator.validate({"PORT": 8080}).valid is True
        result = validator.validate({"PORT": "not_int"})
        assert result.valid is False

    def test_validate_type_int_rejects_bool(self):
        validator = ConfigValidator("TEST")
        validator.add_rule(ConfigRule("FLAG", value_type="int"))
        result = validator.validate({"FLAG": True})
        assert result.valid is False

    def test_validate_type_url(self):
        validator = ConfigValidator("TEST")
        validator.add_rule(ConfigRule("WEBHOOK_URL", value_type="url"))
        assert validator.validate({"WEBHOOK_URL": "https://example.com"}).valid is True
        result = validator.validate({"WEBHOOK_URL": "not_a_url"})
        assert result.valid is False

    def test_validate_type_email(self):
        validator = ConfigValidator("TEST")
        validator.add_rule(ConfigRule("EMAIL", value_type="email"))
        assert validator.validate({"EMAIL": "test@example.com"}).valid is True
        result = validator.validate({"EMAIL": "not_an_email"})
        assert result.valid is False

    def test_validate_range_min_value(self):
        validator = ConfigValidator("TEST")
        validator.add_rule(ConfigRule("PORT", value_type="int", min_value=1))
        assert validator.validate({"PORT": 8080}).valid is True
        result = validator.validate({"PORT": 0})
        assert result.valid is False
        assert "below minimum" in result.errors[0]

    def test_validate_range_max_value(self):
        validator = ConfigValidator("TEST")
        validator.add_rule(ConfigRule("PORT", value_type="int", max_value=65535))
        assert validator.validate({"PORT": 8080}).valid is True
        result = validator.validate({"PORT": 70000})
        assert result.valid is False
        assert "above maximum" in result.errors[0]

    def test_validate_range_min_length(self):
        validator = ConfigValidator("TEST")
        validator.add_rule(ConfigRule("KEY", min_length=8))
        assert validator.validate({"KEY": "12345678"}).valid is True
        result = validator.validate({"KEY": "short"})
        assert result.valid is False
        assert "below minimum" in result.errors[0]

    def test_validate_range_max_length(self):
        validator = ConfigValidator("TEST")
        validator.add_rule(ConfigRule("KEY", max_length=64))
        assert validator.validate({"KEY": "ok"}).valid is True
        result = validator.validate({"KEY": "x" * 65})
        assert result.valid is False
        assert "exceeds maximum" in result.errors[0]

    def test_validate_pattern(self):
        validator = ConfigValidator("TEST")
        validator.add_rule(ConfigRule("VERSION", pattern=r"^\d+\.\d+\.\d+$"))
        assert validator.validate({"VERSION": "1.2.3"}).valid is True
        result = validator.validate({"VERSION": "not_semver"})
        assert result.valid is False

    def test_validate_allowed_values(self):
        validator = ConfigValidator("TEST")
        validator.add_rule(ConfigRule("MODE", allowed_values=["prod", "dev"]))
        assert validator.validate({"MODE": "prod"}).valid is True
        result = validator.validate({"MODE": "staging"})
        assert result.valid is False
        assert "not in allowed values" in result.errors[0]

    def test_validate_dependency_present(self):
        validator = ConfigValidator("TEST")
        validator.add_rule(ConfigRule("APP_KEY", required=True))
        validator.add_rule(ConfigRule("TOKEN", depends_on=["APP_KEY"]))
        result = validator.validate({"APP_KEY": "key", "TOKEN": "tok"})
        assert result.valid is True
        assert len(result.dependency_errors) == 0

    def test_validate_dependency_missing(self):
        validator = ConfigValidator("TEST")
        validator.add_rule(ConfigRule("APP_KEY", required=True))
        validator.add_rule(ConfigRule("TOKEN", depends_on=["APP_KEY"]))
        result = validator.validate({"TOKEN": "tok"})
        assert result.valid is False
        assert len(result.dependency_errors) == 1
        assert "APP_KEY" in result.dependency_errors[0]

    def test_validate_dependency_not_set_ok(self):
        validator = ConfigValidator("TEST")
        validator.add_rule(ConfigRule("TOKEN", required=False, depends_on=["APP_KEY"]))
        result = validator.validate({})
        assert result.valid is True

    def test_validate_with_prefix(self):
        validator = ConfigValidator("TEST")
        validator.add_rule(ConfigRule("APP_KEY", required=True))
        result = validator.validate({}, prefix="OCEANENGINE_")
        assert result.valid is False
        assert "OCEANENGINE_APP_KEY" in result.missing_keys[0]

    def test_validate_multiple_rules(self):
        validator = ConfigValidator("TEST")
        validator.add_rules([
            ConfigRule("APP_KEY", required=True, min_length=8),
            ConfigRule("APP_SECRET", required=True, min_length=16),
            ConfigRule("TIMEOUT", required=False, value_type="int", min_value=1, max_value=300),
        ])
        result = validator.validate({
            "APP_KEY": "my_key_123",
            "APP_SECRET": "my_secret_value_12345678",
            "TIMEOUT": 30,
        })
        assert result.valid is True

    def test_validate_from_env_success(self):
        validator = ConfigValidator("TEST")
        validator.add_rule(ConfigRule("APP_KEY", required=True))
        validator.add_rule(ConfigRule("APP_SECRET", required=True))
        with patch.dict(os.environ, {"TEST_APP_KEY": "key", "TEST_APP_SECRET": "secret"}):
            result = validator.validate_from_env("TEST")
        assert result.valid is True

    def test_validate_from_env_missing(self):
        validator = ConfigValidator("TEST")
        validator.add_rule(ConfigRule("APP_KEY", required=True))
        with patch.dict(os.environ, {}, clear=True):
            result = validator.validate_from_env("TEST")
        assert result.valid is False

    def test_validate_from_env_specific_keys(self):
        validator = ConfigValidator("TEST")
        validator.add_rule(ConfigRule("APP_KEY", required=True))
        validator.add_rule(ConfigRule("APP_SECRET", required=True))
        with patch.dict(os.environ, {"TEST_APP_KEY": "key"}):
            result = validator.validate_from_env("TEST", keys=["APP_KEY"])
        assert result.valid is True


# ── ConnectionPoolMonitor Tests ────────────────────────────


class TestConnectionPoolMonitor:
    """Tests for ConnectionPoolMonitor."""

    def test_default_init(self):
        monitor = ConnectionPoolMonitor()
        assert monitor._max_connections == 10

    def test_custom_max_connections(self):
        monitor = ConnectionPoolMonitor(max_connections=20)
        assert monitor._max_connections == 20

    def test_record_acquire(self):
        monitor = ConnectionPoolMonitor()
        monitor.record_acquire(latency_ms=5.0)
        metrics = monitor.get_metrics()
        assert metrics.active_connections == 1
        assert metrics.total_requests == 1
        assert metrics.pool_utilization == 0.1

    def test_record_release(self):
        monitor = ConnectionPoolMonitor()
        monitor.record_acquire()
        monitor.record_release()
        metrics = monitor.get_metrics()
        assert metrics.active_connections == 0

    def test_record_release_no_negative(self):
        monitor = ConnectionPoolMonitor()
        monitor.record_release()
        metrics = monitor.get_metrics()
        assert metrics.active_connections == 0

    def test_pool_utilization(self):
        monitor = ConnectionPoolMonitor(max_connections=10)
        for _ in range(5):
            monitor.record_acquire()
        metrics = monitor.get_metrics()
        assert metrics.pool_utilization == 0.5

    def test_health_status_healthy(self):
        monitor = ConnectionPoolMonitor(max_connections=10)
        monitor.record_acquire()
        health = monitor.get_health_status()
        assert health["status"] == "healthy"

    def test_health_status_warning(self):
        monitor = ConnectionPoolMonitor(max_connections=10)
        for _ in range(8):
            monitor.record_acquire()
        health = monitor.get_health_status()
        assert health["status"] == "warning"

    def test_health_status_critical(self):
        monitor = ConnectionPoolMonitor(max_connections=10)
        for _ in range(10):
            monitor.record_acquire()
        health = monitor.get_health_status()
        assert health["status"] == "critical"

    def test_reset(self):
        monitor = ConnectionPoolMonitor()
        monitor.record_acquire()
        monitor.reset()
        metrics = monitor.get_metrics()
        assert metrics.total_requests == 0


class TestPoolMetrics:
    def test_default_values(self):
        m = PoolMetrics()
        assert m.max_connections == 10


class TestSpan:
    def test_creation(self):
        span = Span(trace_id="t1", span_id="s1", name="test")
        assert span.trace_id == "t1"

    def test_finish(self):
        span = Span(trace_id="t1", span_id="s1", name="test", start_time=1.0)
        assert span.is_active is True
        span.finish()
        assert span.is_active is False

    def test_to_dict(self):
        span = Span(trace_id="t1", span_id="s1", name="test", start_time=1.0, end_time=1.1)
        d = span.to_dict()
        assert d["trace_id"] == "t1"


class TestTraceContext:
    def test_to_headers(self):
        ctx = TraceContext(trace_id="t1", span_id="s1")
        headers = ctx.to_headers()
        assert headers["X-Trace-Id"] == "t1"

    def test_from_headers(self):
        ctx = TraceContext.from_headers({"X-Trace-Id": "t1", "X-Span-Id": "s1"})
        assert ctx.trace_id == "t1"

    def test_from_w3c(self):
        ctx = TraceContext.from_w3c("00-abc-def-01")
        assert ctx.trace_id == "abc"

    def test_to_w3c(self):
        ctx = TraceContext(trace_id="abc", span_id="def")
        tp, _ = ctx.to_w3c()
        assert tp == "00-abc-def-01"

    def test_roundtrip(self):
        original = TraceContext(trace_id="t1", span_id="s1", parent_span_id="p1")
        headers = original.to_headers()
        restored = TraceContext.from_headers(headers)
        assert restored.trace_id == original.trace_id


class TestTracer:
    def test_init(self):
        tracer = Tracer(service_name="test")
        assert tracer.service_name == "test"

    def test_start_span(self):
        tracer = Tracer()
        span = tracer.start_span("op")
        assert span.name == "op"

    def test_start_span_with_parent(self):
        tracer = Tracer()
        parent = tracer.start_span("parent")
        child = tracer.start_span("child", parent=parent)
        assert child.trace_id == parent.trace_id

    def test_finish_span(self):
        tracer = Tracer()
        span = tracer.start_span("op")
        tracer.finish_span(span)
        assert span not in tracer.get_active_spans()

    def test_get_all_spans(self):
        tracer = Tracer()
        tracer.start_span("op1")
        tracer.start_span("op2")
        assert len(tracer.get_all_spans()) == 2

    def test_get_current_context(self):
        tracer = Tracer()
        span = tracer.start_span("op")
        ctx = tracer.get_current_context()
        assert ctx is not None
        assert ctx.trace_id == span.trace_id

    def test_export_trace(self):
        tracer = Tracer(service_name="test")
        tracer.start_span("op")
        data = tracer.export_trace()
        assert data["span_count"] == 1

    def test_clear(self):
        tracer = Tracer()
        tracer.start_span("op")
        tracer.clear()
        assert tracer.get_all_spans() == []

    def test_context_manager(self):
        with Tracer(service_name="test") as tracer:
            tracer.start_span("op")
            assert len(tracer.get_active_spans()) == 1
        assert len(tracer.get_active_spans()) == 0


class TestSpanScope:
    def test_basic_usage(self):
        tracer = Tracer()
        with span_scope(tracer, "my_op") as span:
            assert span.name == "my_op"
        assert span.status == "ok"

    def test_error_captured(self):
        tracer = Tracer()
        with pytest.raises(ValueError):
            with span_scope(tracer, "my_op"):
                raise ValueError("test error")


class TestCommerceMCPBasePoolTracer:
    def test_init_has_pool_monitor(self):
        client = CommerceMCPBase()
        assert isinstance(client.pool_monitor, ConnectionPoolMonitor)

    def test_init_has_tracer(self):
        client = CommerceMCPBase()
        assert isinstance(client.tracer, Tracer)

    @pytest.mark.asyncio
    async def test_request_creates_span(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": {"id": 1}}
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.is_closed = False

        with patch.object(client, "_ensure_client", return_value=mock_client):
            await client._request("GET", "/api/test")

        spans = client.tracer.get_all_spans()
        assert len(spans) == 1
        assert spans[0].name == "GET /api/test"
        assert spans[0].status == "ok"

    @pytest.mark.asyncio
    async def test_health_check_includes_pool(self):
        client = CommerceMCPBase(app_key="key", app_secret="secret")
        result = await client.health_check(use_cache=False)
        assert "pool" in result
        assert "status" in result["pool"]

    def test_request_tracks_pool_metrics(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        client._get_client()
        pool_metrics = client.pool_monitor.get_metrics()
        assert pool_metrics.total_requests >= 1
