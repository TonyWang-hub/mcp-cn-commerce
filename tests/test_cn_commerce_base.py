"""Tests for the shared cn_commerce_base module.

Tests the base classes, error handling, and utility functions.
"""

from __future__ import annotations

import asyncio
import json
import logging
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
    DEFAULT_RETRY,
    RATE_LIMIT_RETRY,
    BatchRequestItem,
    BatchResultItem,
    BatchSummary,
    CircuitBreakerState,
    CommerceAPIError,
    CommerceMCPBase,
    ConfigurableRateLimiter,
    ConfigValidationError,
    EndpointMetrics,
    EndpointNode,
    EndpointRateLimit,
    FailoverConfig,
    FailoverManager,
    LoadBalancer,
    LoadBalancingStrategy,
    MetricsCollector,
    PlatformRateLimitConfig,
    RateLimitConfig,
    RateLimiter,
    RateLimitStats,
    RetryableError,
    RetryConfig,
    SensitiveDataFilter,
    SignMethod,
    format_error_response,
    format_response,
    handle_tool_errors,
    mask_dict_sensitive_keys,
    mask_log_message,
    mask_sensitive_value,
    sanitize_log_context,
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
            result = await client.health_check()
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
            result = await client.health_check()

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
            result = await client.health_check()

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


# ── WarmupTask Tests ──────────────────────────────────────


class TestLoadBalancingStrategy:
    """Tests for LoadBalancingStrategy enum."""

    def test_round_robin(self):
        assert LoadBalancingStrategy.ROUND_ROBIN == "round_robin"

    def test_weighted(self):
        assert LoadBalancingStrategy.WEIGHTED == "weighted"

    def test_least_connections(self):
        assert LoadBalancingStrategy.LEAST_CONNECTIONS == "least_connections"


# ── EndpointNode Tests ─────────────────────────────────────


class TestEndpointNode:
    """Tests for EndpointNode dataclass."""

    def test_default_values(self):
        node = EndpointNode()
        assert node.url == ""
        assert node.weight == 1
        assert node.active_connections == 0
        assert node.is_healthy is True
        assert node.failure_count == 0
        assert node.last_failure_time == 0.0
        assert node.total_requests == 0
        assert node.total_failures == 0
        assert node.avg_latency_ms == 0.0

    def test_custom_values(self):
        node = EndpointNode(
            url="https://api.example.com",
            weight=3,
            active_connections=5,
            is_healthy=False,
            failure_count=2,
        )
        assert node.url == "https://api.example.com"
        assert node.weight == 3
        assert node.active_connections == 5
        assert node.is_healthy is False
        assert node.failure_count == 2


# ── LoadBalancer Tests ─────────────────────────────────────


class TestLoadBalancer:
    """Tests for LoadBalancer."""

    def test_default_strategy(self):
        lb = LoadBalancer()
        assert lb.strategy == LoadBalancingStrategy.ROUND_ROBIN

    def test_custom_strategy(self):
        lb = LoadBalancer(LoadBalancingStrategy.WEIGHTED)
        assert lb.strategy == LoadBalancingStrategy.WEIGHTED

    def test_add_endpoint(self):
        lb = LoadBalancer()
        node = lb.add_endpoint("https://api1.example.com", weight=2)
        assert node.url == "https://api1.example.com"
        assert node.weight == 2
        assert lb.endpoint_count == 1

    def test_add_endpoint_updates_weight(self):
        lb = LoadBalancer()
        lb.add_endpoint("https://api1.example.com", weight=1)
        node = lb.add_endpoint("https://api1.example.com", weight=5)
        assert node.weight == 5
        assert lb.endpoint_count == 1

    def test_add_endpoint_min_weight(self):
        lb = LoadBalancer()
        node = lb.add_endpoint("https://api1.example.com", weight=0)
        assert node.weight == 1  # Minimum weight is 1

    def test_remove_endpoint(self):
        lb = LoadBalancer()
        lb.add_endpoint("https://api1.example.com")
        assert lb.remove_endpoint("https://api1.example.com") is True
        assert lb.endpoint_count == 0

    def test_remove_nonexistent_endpoint(self):
        lb = LoadBalancer()
        assert lb.remove_endpoint("https://nonexistent.com") is False

    def test_mark_healthy(self):
        lb = LoadBalancer()
        lb.add_endpoint("https://api1.example.com")
        lb.mark_unhealthy("https://api1.example.com")
        lb.mark_healthy("https://api1.example.com")
        node = lb._endpoints["https://api1.example.com"]
        assert node.is_healthy is True
        assert node.failure_count == 0

    def test_mark_unhealthy(self):
        lb = LoadBalancer()
        lb.add_endpoint("https://api1.example.com")
        lb.mark_unhealthy("https://api1.example.com")
        node = lb._endpoints["https://api1.example.com"]
        assert node.is_healthy is False
        assert node.failure_count == 1
        assert node.total_failures == 1
        assert node.last_failure_time > 0

    def test_record_success(self):
        lb = LoadBalancer()
        lb.add_endpoint("https://api1.example.com")
        lb.record_success("https://api1.example.com", latency_ms=50.0)
        node = lb._endpoints["https://api1.example.com"]
        assert node.total_requests == 1
        assert node.avg_latency_ms == 50.0

    def test_record_success_latency_moving_average(self):
        lb = LoadBalancer()
        lb.add_endpoint("https://api1.example.com")
        lb.record_success("https://api1.example.com", latency_ms=100.0)
        lb.record_success("https://api1.example.com", latency_ms=50.0)
        node = lb._endpoints["https://api1.example.com"]
        assert node.total_requests == 2
        # EMA: 0.8 * 100 + 0.2 * 50 = 90
        assert node.avg_latency_ms == pytest.approx(90.0)

    def test_record_failure(self):
        lb = LoadBalancer()
        lb.add_endpoint("https://api1.example.com")
        lb.record_failure("https://api1.example.com")
        node = lb._endpoints["https://api1.example.com"]
        assert node.is_healthy is False
        assert node.failure_count == 1

    def test_get_endpoint_no_endpoints(self):
        lb = LoadBalancer()
        assert lb.get_endpoint() is None

    def test_get_endpoint_all_unhealthy(self):
        lb = LoadBalancer()
        lb.add_endpoint("https://api1.example.com")
        lb.mark_unhealthy("https://api1.example.com")
        assert lb.get_endpoint() is None

    def test_round_robin_distribution(self):
        lb = LoadBalancer(LoadBalancingStrategy.ROUND_ROBIN)
        lb.add_endpoint("https://api1.example.com")
        lb.add_endpoint("https://api2.example.com")
        lb.add_endpoint("https://api3.example.com")

        results = [lb.get_endpoint().url for _ in range(6)]
        assert results == [
            "https://api1.example.com",
            "https://api2.example.com",
            "https://api3.example.com",
            "https://api1.example.com",
            "https://api2.example.com",
            "https://api3.example.com",
        ]

    def test_round_robin_skips_unhealthy(self):
        lb = LoadBalancer(LoadBalancingStrategy.ROUND_ROBIN)
        lb.add_endpoint("https://api1.example.com")
        lb.add_endpoint("https://api2.example.com")
        lb.mark_unhealthy("https://api1.example.com")

        results = [lb.get_endpoint().url for _ in range(3)]
        assert all(r == "https://api2.example.com" for r in results)

    def test_weighted_distribution(self):
        lb = LoadBalancer(LoadBalancingStrategy.WEIGHTED)
        lb.add_endpoint("https://api1.example.com", weight=3)
        lb.add_endpoint("https://api2.example.com", weight=1)

        # With 3:1 weight ratio, api1 should get ~75% of traffic
        results = [lb.get_endpoint().url for _ in range(1000)]
        api1_count = results.count("https://api1.example.com")
        api2_count = results.count("https://api2.example.com")
        # Allow some variance due to randomness
        assert api1_count > 600
        assert api2_count > 100

    def test_least_connections_distribution(self):
        lb = LoadBalancer(LoadBalancingStrategy.LEAST_CONNECTIONS)
        lb.add_endpoint("https://api1.example.com")
        lb.add_endpoint("https://api2.example.com")

        # First call should pick one with 0 connections
        ep1 = lb.get_endpoint()
        lb.increment_connections(ep1.url)

        # Second call should pick the other one
        ep2 = lb.get_endpoint()
        assert ep2.url != ep1.url

    def test_increment_decrement_connections(self):
        lb = LoadBalancer()
        lb.add_endpoint("https://api1.example.com")

        lb.increment_connections("https://api1.example.com")
        assert lb._endpoints["https://api1.example.com"].active_connections == 1

        lb.increment_connections("https://api1.example.com")
        assert lb._endpoints["https://api1.example.com"].active_connections == 2

        lb.decrement_connections("https://api1.example.com")
        assert lb._endpoints["https://api1.example.com"].active_connections == 1

    def test_decrement_connections_minimum_zero(self):
        lb = LoadBalancer()
        lb.add_endpoint("https://api1.example.com")
        lb.decrement_connections("https://api1.example.com")
        assert lb._endpoints["https://api1.example.com"].active_connections == 0

    def test_endpoint_count(self):
        lb = LoadBalancer()
        assert lb.endpoint_count == 0
        lb.add_endpoint("https://api1.example.com")
        assert lb.endpoint_count == 1
        lb.add_endpoint("https://api2.example.com")
        assert lb.endpoint_count == 2

    def test_healthy_count(self):
        lb = LoadBalancer()
        lb.add_endpoint("https://api1.example.com")
        lb.add_endpoint("https://api2.example.com")
        assert lb.healthy_count == 2

        lb.mark_unhealthy("https://api1.example.com")
        assert lb.healthy_count == 1

    def test_get_stats(self):
        lb = LoadBalancer(LoadBalancingStrategy.WEIGHTED)
        lb.add_endpoint("https://api1.example.com", weight=2)
        lb.add_endpoint("https://api2.example.com")

        stats = lb.get_stats()
        assert stats["strategy"] == "weighted"
        assert stats["total_endpoints"] == 2
        assert stats["healthy_endpoints"] == 2
        assert stats["unhealthy_endpoints"] == 0
        assert "https://api1.example.com" in stats["endpoints"]
        assert "https://api2.example.com" in stats["endpoints"]


# ── FailoverConfig Tests ───────────────────────────────────


class TestFailoverConfig:
    """Tests for FailoverConfig dataclass."""

    def test_default_values(self):
        config = FailoverConfig()
        assert config.max_failures == 3
        assert config.recovery_check_interval == 30.0
        assert config.recovery_timeout == 5.0
        assert config.enable_auto_recovery is True
        assert config.circuit_breaker_threshold == 0.5
        assert config.circuit_breaker_reset_seconds == 60.0

    def test_custom_values(self):
        config = FailoverConfig(
            max_failures=5,
            recovery_check_interval=10.0,
            recovery_timeout=3.0,
            enable_auto_recovery=False,
            circuit_breaker_threshold=0.7,
            circuit_breaker_reset_seconds=30.0,
        )
        assert config.max_failures == 5
        assert config.recovery_check_interval == 10.0
        assert config.recovery_timeout == 3.0
        assert config.enable_auto_recovery is False
        assert config.circuit_breaker_threshold == 0.7
        assert config.circuit_breaker_reset_seconds == 30.0


# ── CircuitBreakerState Tests ──────────────────────────────


class TestCircuitBreakerState:
    """Tests for CircuitBreakerState dataclass."""

    def test_default_values(self):
        cb = CircuitBreakerState()
        assert cb.url == ""
        assert cb.is_open is False
        assert cb.failure_count == 0
        assert cb.success_count == 0
        assert cb.last_failure_time == 0.0
        assert cb.opened_at == 0.0

    def test_custom_values(self):
        cb = CircuitBreakerState(
            url="https://api.example.com",
            is_open=True,
            failure_count=5,
        )
        assert cb.url == "https://api.example.com"
        assert cb.is_open is True
        assert cb.failure_count == 5


# ── FailoverManager Tests ──────────────────────────────────


class TestFailoverManager:
    """Tests for FailoverManager."""

    def test_init(self):
        lb = LoadBalancer()
        fm = FailoverManager(load_balancer=lb)
        assert fm.config.max_failures == 3

    def test_init_custom_config(self):
        lb = LoadBalancer()
        config = FailoverConfig(max_failures=5)
        fm = FailoverManager(load_balancer=lb, config=config)
        assert fm.config.max_failures == 5

    def test_report_success(self):
        lb = LoadBalancer()
        lb.add_endpoint("https://api1.example.com")
        fm = FailoverManager(load_balancer=lb)

        fm.report_success("https://api1.example.com", latency_ms=50.0)
        node = lb._endpoints["https://api1.example.com"]
        assert node.total_requests == 1
        assert node.is_healthy is True

    def test_report_success_resets_circuit_breaker(self):
        lb = LoadBalancer()
        lb.add_endpoint("https://api1.example.com")
        fm = FailoverManager(load_balancer=lb)

        # Simulate failures to open circuit breaker
        for _ in range(10):
            fm.report_failure("https://api1.example.com", error="test")

        # Report success should close circuit
        fm.report_success("https://api1.example.com")
        assert fm.is_circuit_open("https://api1.example.com") is False

    def test_report_failure_increments_count(self):
        lb = LoadBalancer()
        lb.add_endpoint("https://api1.example.com")
        fm = FailoverManager(load_balancer=lb)

        fm.report_failure("https://api1.example.com", error="connection refused")
        node = lb._endpoints["https://api1.example.com"]
        assert node.failure_count == 1
        assert node.total_failures == 1

    def test_report_failure_marks_unhealthy_after_threshold(self):
        lb = LoadBalancer()
        lb.add_endpoint("https://api1.example.com")
        fm = FailoverManager(load_balancer=lb, config=FailoverConfig(max_failures=3))

        fm.report_failure("https://api1.example.com")
        fm.report_failure("https://api1.example.com")
        assert lb._endpoints["https://api1.example.com"].is_healthy is True

        fm.report_failure("https://api1.example.com")
        assert lb._endpoints["https://api1.example.com"].is_healthy is False

    def test_report_failure_records_history(self):
        lb = LoadBalancer()
        lb.add_endpoint("https://api1.example.com")
        fm = FailoverManager(load_balancer=lb)

        fm.report_failure("https://api1.example.com", error="timeout")
        assert len(fm._failure_history) == 1
        assert fm._failure_history[0]["url"] == "https://api1.example.com"
        assert fm._failure_history[0]["error"] == "timeout"

    def test_report_failure_history_bounded(self):
        lb = LoadBalancer()
        lb.add_endpoint("https://api1.example.com")
        fm = FailoverManager(load_balancer=lb)

        # Add more than 1000 entries
        for i in range(1100):
            fm.report_failure("https://api1.example.com", error=f"error {i}")

        assert len(fm._failure_history) <= 500

    def test_report_failure_ignores_unknown_url(self):
        lb = LoadBalancer()
        fm = FailoverManager(load_balancer=lb)

        # Should not raise
        fm.report_failure("https://unknown.com", error="test")

    def test_circuit_breaker_opens_on_high_failure_rate(self):
        lb = LoadBalancer()
        lb.add_endpoint("https://api1.example.com")
        fm = FailoverManager(
            load_balancer=lb,
            config=FailoverConfig(
                max_failures=3,
                circuit_breaker_threshold=0.5,
            ),
        )

        # Need at least 5 requests to evaluate circuit breaker
        for _ in range(3):
            fm.report_failure("https://api1.example.com")
        for _ in range(2):
            fm.report_success("https://api1.example.com")

        # 3 failures out of 5 = 60% > 50% threshold
        assert fm.is_circuit_open("https://api1.example.com") is True

    def test_circuit_breaker_stays_closed_on_low_failure_rate(self):
        lb = LoadBalancer()
        lb.add_endpoint("https://api1.example.com")
        fm = FailoverManager(load_balancer=lb, config=FailoverConfig(circuit_breaker_threshold=0.5))

        # 2 failures out of 5 = 40% < 50% threshold
        for _ in range(2):
            fm.report_failure("https://api1.example.com")
        for _ in range(3):
            fm.report_success("https://api1.example.com")

        assert fm.is_circuit_open("https://api1.example.com") is False

    def test_circuit_breaker_resets_after_timeout(self):
        lb = LoadBalancer()
        lb.add_endpoint("https://api1.example.com")
        fm = FailoverManager(
            load_balancer=lb,
            config=FailoverConfig(
                circuit_breaker_threshold=0.5,
                circuit_breaker_reset_seconds=0.01,  # Very short timeout
            ),
        )

        # Open the circuit breaker
        for _ in range(5):
            fm.report_failure("https://api1.example.com")

        assert fm.is_circuit_open("https://api1.example.com") is True

        # Wait for reset timeout
        import time as _time

        _time.sleep(0.02)

        # Should be closed now
        assert fm.is_circuit_open("https://api1.example.com") is False

    def test_get_healthy_endpoint(self):
        lb = LoadBalancer()
        lb.add_endpoint("https://api1.example.com")
        lb.add_endpoint("https://api2.example.com")
        fm = FailoverManager(load_balancer=lb)

        endpoint = fm.get_healthy_endpoint()
        assert endpoint is not None
        assert endpoint.url in ["https://api1.example.com", "https://api2.example.com"]

    def test_get_healthy_endpoint_skips_open_circuit(self):
        lb = LoadBalancer()
        lb.add_endpoint("https://api1.example.com")
        lb.add_endpoint("https://api2.example.com")
        fm = FailoverManager(load_balancer=lb, config=FailoverConfig(circuit_breaker_threshold=0.5))

        # Open circuit for api1
        for _ in range(5):
            fm.report_failure("https://api1.example.com")

        # Should get api2
        endpoint = fm.get_healthy_endpoint()
        assert endpoint is not None
        assert endpoint.url == "https://api2.example.com"

    def test_get_healthy_endpoint_none_when_all_unhealthy(self):
        lb = LoadBalancer()
        lb.add_endpoint("https://api1.example.com")
        fm = FailoverManager(load_balancer=lb)

        lb.mark_unhealthy("https://api1.example.com")
        assert fm.get_healthy_endpoint() is None

    @pytest.mark.asyncio
    async def test_check_recovery_success(self):
        lb = LoadBalancer()
        lb.add_endpoint("https://api1.example.com")
        lb.mark_unhealthy("https://api1.example.com")
        fm = FailoverManager(load_balancer=lb)

        mock_response = AsyncMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.head.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await fm.check_recovery("https://api1.example.com")

        assert result is True
        assert lb._endpoints["https://api1.example.com"].is_healthy is True

    @pytest.mark.asyncio
    async def test_check_recovery_failure(self):
        lb = LoadBalancer()
        lb.add_endpoint("https://api1.example.com")
        lb.mark_unhealthy("https://api1.example.com")
        fm = FailoverManager(load_balancer=lb)

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.head.side_effect = httpx.ConnectError("refused")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await fm.check_recovery("https://api1.example.com")

        assert result is False
        assert lb._endpoints["https://api1.example.com"].is_healthy is False

    @pytest.mark.asyncio
    async def test_recovery_monitor_disabled(self):
        lb = LoadBalancer()
        fm = FailoverManager(load_balancer=lb, config=FailoverConfig(enable_auto_recovery=False))

        await fm.start_recovery_monitor()
        assert fm._recovery_task is None

    @pytest.mark.asyncio
    async def test_recovery_monitor_start_stop(self):
        lb = LoadBalancer()
        fm = FailoverManager(
            load_balancer=lb,
            config=FailoverConfig(
                enable_auto_recovery=True,
                recovery_check_interval=0.05,
            ),
        )

        await fm.start_recovery_monitor()
        assert fm._recovery_task is not None

        fm.stop_recovery_monitor()
        await asyncio.sleep(0.05)
        assert fm._recovery_task is None

    def test_get_stats(self):
        lb = LoadBalancer()
        lb.add_endpoint("https://api1.example.com")
        fm = FailoverManager(load_balancer=lb)

        fm.report_failure("https://api1.example.com", error="test")
        stats = fm.get_stats()

        assert "config" in stats
        assert "circuit_breakers" in stats
        assert "recent_failures" in stats
        assert "total_failure_events" in stats
        assert "load_balancer" in stats
        assert stats["total_failure_events"] == 1

    def test_reset(self):
        lb = LoadBalancer()
        lb.add_endpoint("https://api1.example.com")
        fm = FailoverManager(load_balancer=lb)

        fm.report_failure("https://api1.example.com", error="test")
        fm.reset()

        assert len(fm._failure_history) == 0
        assert len(fm._circuit_breakers) == 0
        assert lb._endpoints["https://api1.example.com"].is_healthy is True
        assert lb._endpoints["https://api1.example.com"].failure_count == 0


# ── LoadBalancer Concurrency Tests ─────────────────────────


class TestLoadBalancerConcurrency:
    """Thread-safety tests for LoadBalancer."""

    def test_concurrent_add_remove(self):
        import threading

        lb = LoadBalancer()
        errors = []

        def add_endpoints():
            try:
                for i in range(50):
                    lb.add_endpoint(f"https://api{i}.example.com")
            except Exception as e:
                errors.append(e)

        def remove_endpoints():
            try:
                for i in range(50):
                    lb.remove_endpoint(f"https://api{i}.example.com")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_endpoints), threading.Thread(target=remove_endpoints)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []

    def test_concurrent_get_endpoint(self):
        import threading

        lb = LoadBalancer(LoadBalancingStrategy.ROUND_ROBIN)
        for i in range(5):
            lb.add_endpoint(f"https://api{i}.example.com")

        results = []
        errors = []

        def get_endpoints():
            try:
                for _ in range(100):
                    ep = lb.get_endpoint()
                    if ep:
                        results.append(ep.url)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=get_endpoints) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert len(results) == 400

    def test_concurrent_health_status_changes(self):
        import threading

        lb = LoadBalancer()
        lb.add_endpoint("https://api1.example.com")
        errors = []

        def toggle_health():
            try:
                for _ in range(100):
                    lb.mark_unhealthy("https://api1.example.com")
                    lb.mark_healthy("https://api1.example.com")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=toggle_health) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []


# ── FailoverManager Concurrency Tests ──────────────────────


class TestFailoverManagerConcurrency:
    """Thread-safety tests for FailoverManager."""

    def test_concurrent_report_success_failure(self):
        import threading

        lb = LoadBalancer()
        lb.add_endpoint("https://api1.example.com")
        fm = FailoverManager(load_balancer=lb)
        errors = []

        def report_successes():
            try:
                for _ in range(100):
                    fm.report_success("https://api1.example.com", latency_ms=10.0)
            except Exception as e:
                errors.append(e)

        def report_failures():
            try:
                for _ in range(100):
                    fm.report_failure("https://api1.example.com", error="test")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=report_successes),
            threading.Thread(target=report_failures),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []

    def test_concurrent_circuit_breaker_checks(self):
        import threading

        lb = LoadBalancer()
        lb.add_endpoint("https://api1.example.com")
        fm = FailoverManager(load_balancer=lb)
        errors = []

        def check_circuit():
            try:
                for _ in range(100):
                    fm.is_circuit_open("https://api1.example.com")
            except Exception as e:
                errors.append(e)

        def report_failures():
            try:
                for _ in range(50):
                    fm.report_failure("https://api1.example.com", error="test")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=check_circuit),
            threading.Thread(target=report_failures),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []


# ── ConnectionPool Tests ──────────────────────────────────


class TestConnectionPoolStats:
    """Tests for ConnectionPoolStats."""

    def test_default_values(self):
        from cn_commerce_base import ConnectionPoolStats

        stats = ConnectionPoolStats()
        assert stats.total_connections == 0
        assert stats.active_connections == 0
        assert stats.connections_reused == 0

    def test_reuse_ratio_no_data(self):
        from cn_commerce_base import ConnectionPoolStats

        stats = ConnectionPoolStats()
        assert stats.reuse_ratio == 0.0

    def test_reuse_ratio_with_data(self):
        from cn_commerce_base import ConnectionPoolStats

        stats = ConnectionPoolStats(connections_reused=8, connections_created=2)
        assert stats.reuse_ratio == 0.8

    def test_to_dict(self):
        from cn_commerce_base import ConnectionPoolStats

        stats = ConnectionPoolStats(connections_reused=5, connections_created=5)
        d = stats.to_dict()
        assert d["connections_reused"] == 5
        assert d["reuse_ratio"] == 0.5
        assert "avg_connection_age_ms" in d

    def test_reset(self):
        from cn_commerce_base import ConnectionPoolStats

        stats = ConnectionPoolStats(
            total_connections=10,
            connections_reused=5,
            health_checks_passed=3,
        )
        stats.reset()
        assert stats.total_connections == 0
        assert stats.connections_reused == 0
        assert stats.health_checks_passed == 0


class TestConnectionPoolConfig:
    """Tests for ConnectionPoolConfig."""

    def test_defaults(self):
        from cn_commerce_base import ConnectionPoolConfig

        config = ConnectionPoolConfig()
        assert config.max_connections == 20
        assert config.max_keepalive_connections == 10
        assert config.http2 is False
        assert config.health_check_interval == 30.0

    def test_custom_values(self):
        from cn_commerce_base import ConnectionPoolConfig

        config = ConnectionPoolConfig(
            http2=True,
            max_connections=50,
            health_check_interval=60.0,
        )
        assert config.http2 is True
        assert config.max_connections == 50
        assert config.health_check_interval == 60.0


class TestConnectionPool:
    """Tests for ConnectionPool."""

    @pytest.mark.asyncio
    async def test_acquire_creates_client(self):
        from cn_commerce_base import ConnectionPool, ConnectionPoolConfig

        pool = ConnectionPool(ConnectionPoolConfig(http2=False))
        client = await pool.acquire()
        assert isinstance(client, httpx.AsyncClient)
        assert not client.is_closed
        await pool.close()

    @pytest.mark.asyncio
    async def test_acquire_reuses_client(self):
        from cn_commerce_base import ConnectionPool

        pool = ConnectionPool()
        client1 = await pool.acquire()
        client2 = await pool.acquire()
        assert client1 is client2
        stats = pool.get_stats()
        assert stats.connections_reused == 1
        assert stats.connections_created == 1
        await pool.close()

    @pytest.mark.asyncio
    async def test_acquire_after_close_creates_new(self):
        from cn_commerce_base import ConnectionPool

        pool = ConnectionPool()
        client1 = await pool.acquire()
        await pool.close()
        client2 = await pool.acquire()
        assert client1 is not client2
        assert not client2.is_closed
        await pool.close()

    @pytest.mark.asyncio
    async def test_release_same_client(self):
        from cn_commerce_base import ConnectionPool

        pool = ConnectionPool()
        client = await pool.acquire()
        await pool.release(client)
        # Same client should still be in the pool
        client2 = await pool.acquire()
        assert client is client2
        await pool.close()

    @pytest.mark.asyncio
    async def test_release_different_client_closes_it(self):
        from cn_commerce_base import ConnectionPool

        pool = ConnectionPool()
        await pool.acquire()
        client2 = httpx.AsyncClient()
        await pool.release(client2)
        assert client2.is_closed
        stats = pool.get_stats()
        assert stats.connections_closed == 1
        await pool.close()

    @pytest.mark.asyncio
    async def test_health_check_no_client(self):
        from cn_commerce_base import ConnectionPool

        pool = ConnectionPool()
        result = await pool.health_check()
        assert result is False
        assert pool.is_healthy is False
        stats = pool.get_stats()
        assert stats.health_checks_failed == 1
        await pool.close()

    @pytest.mark.asyncio
    async def test_health_check_no_url(self):
        from cn_commerce_base import ConnectionPool, ConnectionPoolConfig

        pool = ConnectionPool(ConnectionPoolConfig(health_check_url=""))
        await pool.acquire()
        result = await pool.health_check()
        assert result is True
        assert pool.is_healthy is True
        stats = pool.get_stats()
        assert stats.health_checks_passed == 1
        await pool.close()

    @pytest.mark.asyncio
    async def test_health_check_with_url_success(self):
        from cn_commerce_base import ConnectionPool, ConnectionPoolConfig

        config = ConnectionPoolConfig(health_check_url="https://api.example.com/health")
        pool = ConnectionPool(config)
        await pool.acquire()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        pool._client.head = AsyncMock(return_value=mock_resp)

        result = await pool.health_check()
        assert result is True
        assert pool.is_healthy is True
        await pool.close()

    @pytest.mark.asyncio
    async def test_health_check_with_url_failure(self):
        from cn_commerce_base import ConnectionPool, ConnectionPoolConfig

        config = ConnectionPoolConfig(
            health_check_url="https://api.example.com/health",
            health_check_timeout=5.0,
        )
        pool = ConnectionPool(config)
        await pool.acquire()

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        pool._client.head = AsyncMock(return_value=mock_resp)

        result = await pool.health_check()
        assert result is False
        assert pool.is_healthy is False
        await pool.close()

    @pytest.mark.asyncio
    async def test_get_stats(self):
        from cn_commerce_base import ConnectionPool

        pool = ConnectionPool()
        stats = pool.get_stats()
        assert stats.active_connections == 0
        assert stats.connections_created == 0

        await pool.acquire()
        stats = pool.get_stats()
        assert stats.active_connections == 1
        assert stats.connections_created == 1
        await pool.close()

    @pytest.mark.asyncio
    async def test_close(self):
        from cn_commerce_base import ConnectionPool

        pool = ConnectionPool()
        await pool.acquire()
        await pool.close()
        stats = pool.get_stats()
        assert stats.active_connections == 0
        assert stats.connections_closed == 1

    @pytest.mark.asyncio
    async def test_close_idempotent(self):
        from cn_commerce_base import ConnectionPool

        pool = ConnectionPool()
        await pool.acquire()
        await pool.close()
        await pool.close()  # Should not raise

    @pytest.mark.asyncio
    async def test_http2_config(self):
        from cn_commerce_base import ConnectionPool, ConnectionPoolConfig

        config = ConnectionPoolConfig(http2=True)
        pool = ConnectionPool(config)
        client = await pool.acquire()
        # httpx.AsyncClient with http2=True should be created
        assert isinstance(client, httpx.AsyncClient)
        await pool.close()

    def test_start_health_monitor_no_loop(self):
        """start_health_monitor should not raise outside an event loop."""
        from cn_commerce_base import ConnectionPool, ConnectionPoolConfig

        config = ConnectionPoolConfig(health_check_interval=10.0)
        pool = ConnectionPool(config)
        pool.start_health_monitor()  # Should not raise

    def test_stop_health_monitor_no_task(self):
        """stop_health_monitor should be a no-op when no task exists."""
        from cn_commerce_base import ConnectionPool

        pool = ConnectionPool()
        pool.stop_health_monitor()  # Should not raise


# ── AsyncRequestQueue Tests ───────────────────────────────


class TestQueuePriority:
    """Tests for QueuePriority enum."""

    def test_critical_value(self):
        from cn_commerce_base import QueuePriority

        assert QueuePriority.CRITICAL == "critical"

    def test_high_value(self):
        from cn_commerce_base import QueuePriority

        assert QueuePriority.HIGH == "high"

    def test_normal_value(self):
        from cn_commerce_base import QueuePriority

        assert QueuePriority.NORMAL == "normal"

    def test_low_value(self):
        from cn_commerce_base import QueuePriority

        assert QueuePriority.LOW == "low"


class TestAsyncQueueStats:
    """Tests for AsyncQueueStats."""

    def test_default_values(self):
        from cn_commerce_base import AsyncQueueStats

        stats = AsyncQueueStats()
        assert stats.total_enqueued == 0
        assert stats.total_processed == 0
        assert stats.total_failed == 0
        assert stats.current_depth == 0

    def test_to_dict(self):
        from cn_commerce_base import AsyncQueueStats

        stats = AsyncQueueStats(
            total_enqueued=10,
            total_processed=8,
            total_failed=2,
            avg_wait_time_ms=15.5,
            priority_counts={"high": 3, "normal": 7},
        )
        d = stats.to_dict()
        assert d["total_enqueued"] == 10
        assert d["total_processed"] == 8
        assert d["priority_counts"]["high"] == 3

    def test_reset(self):
        from cn_commerce_base import AsyncQueueStats

        stats = AsyncQueueStats(
            total_enqueued=10,
            total_processed=8,
            priority_counts={"high": 3},
        )
        stats.reset()
        assert stats.total_enqueued == 0
        assert stats.total_processed == 0
        assert len(stats.priority_counts) == 0


class TestAsyncRequestQueue:
    """Tests for AsyncRequestQueue."""

    @pytest.mark.asyncio
    async def test_enqueue_and_process(self):
        from cn_commerce_base import AsyncRequestQueue

        queue = AsyncRequestQueue(max_workers=2)

        async def processor(method, path, params, data):
            return {"method": method, "path": path}

        queue.set_processor(processor)
        result = await queue.enqueue("GET", "/test")
        assert result == {"method": "GET", "path": "/test"}
        await queue.close()

    @pytest.mark.asyncio
    async def test_priority_ordering(self):
        from cn_commerce_base import AsyncRequestQueue, QueuePriority

        processed_order = []
        queue = AsyncRequestQueue(max_workers=1)

        async def processor(method, path, params, data):
            processed_order.append(path)
            return path

        queue.set_processor(processor)
        await queue.start()

        # Add a blocker to ensure items queue up before being processed

        blocker_done = asyncio.Event()
        asyncio.get_event_loop()

        async def blocking_processor(method, path, params, data):
            if path == "/blocker":
                await blocker_done.wait()
            processed_order.append(path)
            return path

        queue._processor = blocking_processor

        # Enqueue blocker first
        blocker_f = queue.enqueue_nowait("GET", "/blocker")
        await asyncio.sleep(0.05)  # Let worker pick up blocker

        # Now enqueue rest while blocker is held
        f_low = queue.enqueue_nowait("GET", "/low", priority=QueuePriority.LOW)
        f_normal = queue.enqueue_nowait("GET", "/normal", priority=QueuePriority.NORMAL)
        f_critical = queue.enqueue_nowait("GET", "/critical", priority=QueuePriority.CRITICAL)
        f_high = queue.enqueue_nowait("GET", "/high", priority=QueuePriority.HIGH)

        # Release the blocker
        blocker_done.set()

        # Wait for all
        await asyncio.gather(blocker_f, f_low, f_normal, f_critical, f_high)

        # After blocker, critical and high should come before normal and low
        assert "/blocker" == processed_order[0]
        assert "/critical" == processed_order[1]
        assert "/high" == processed_order[2]
        await queue.close()

    @pytest.mark.asyncio
    async def test_enqueue_nowait(self):
        from cn_commerce_base import AsyncRequestQueue

        queue = AsyncRequestQueue(max_workers=2)

        async def processor(method, path, params, data):
            return {"result": "ok"}

        queue.set_processor(processor)
        await queue.start()
        future = queue.enqueue_nowait("GET", "/test")
        result = await future
        assert result == {"result": "ok"}
        await queue.close()

    @pytest.mark.asyncio
    async def test_stats_tracking(self):
        from cn_commerce_base import AsyncRequestQueue, QueuePriority

        queue = AsyncRequestQueue(max_workers=2)

        async def processor(method, path, params, data):
            return "ok"

        queue.set_processor(processor)
        await queue.enqueue("GET", "/1", priority=QueuePriority.HIGH)
        await queue.enqueue("GET", "/2", priority=QueuePriority.NORMAL)

        stats = queue.get_stats()
        assert stats.total_enqueued == 2
        assert stats.total_processed == 2
        assert stats.priority_counts.get("high") == 1
        assert stats.priority_counts.get("normal") == 1
        await queue.close()

    @pytest.mark.asyncio
    async def test_error_handling(self):
        from cn_commerce_base import AsyncRequestQueue

        queue = AsyncRequestQueue(max_workers=2)

        async def failing_processor(method, path, params, data):
            raise ValueError("test error")

        queue.set_processor(failing_processor)
        with pytest.raises(ValueError, match="test error"):
            await queue.enqueue("GET", "/fail")

        stats = queue.get_stats()
        assert stats.total_failed == 1
        assert stats.processing_errors.get("ValueError") == 1
        await queue.close()

    @pytest.mark.asyncio
    async def test_no_processor_raises(self):
        from cn_commerce_base import AsyncRequestQueue

        queue = AsyncRequestQueue(max_workers=2)
        with pytest.raises(RuntimeError, match="No processor"):
            await queue.enqueue("GET", "/test")
        await queue.close()

    @pytest.mark.asyncio
    async def test_queue_size_limit(self):
        from cn_commerce_base import AsyncRequestQueue

        async def processor(method, path, params, data):
            return "ok"

        queue = AsyncRequestQueue(max_workers=1, max_queue_size=2)
        queue.set_processor(processor)

        # Don't start the queue (no auto-start), put items directly
        queue._running = True  # Prevent auto-start in enqueue
        # Manually put items to fill the queue
        from cn_commerce_base import QueuedRequest

        for i in range(2):
            loop = asyncio.get_event_loop()
            future = loop.create_future()
            req = QueuedRequest(priority_num=2, sequence=i, method="GET", path=f"/{i}", future=future)
            queue._queue.put_nowait(req)

        # Queue should be full now
        with pytest.raises(RuntimeError, match="Queue is full"):
            queue.enqueue_nowait("GET", "/overflow")

        queue._running = False
        await queue.close()

    @pytest.mark.asyncio
    async def test_close(self):
        from cn_commerce_base import AsyncRequestQueue

        queue = AsyncRequestQueue(max_workers=2)
        assert queue.is_running is False
        await queue.start()
        assert queue.is_running is True
        await queue.close()
        assert queue.is_running is False

    @pytest.mark.asyncio
    async def test_depth(self):
        from cn_commerce_base import AsyncRequestQueue

        queue = AsyncRequestQueue(max_workers=2)

        async def processor(method, path, params, data):
            return "ok"

        queue.set_processor(processor)
        assert queue.depth == 0
        await queue.enqueue("GET", "/test")
        assert queue.depth == 0  # Processed immediately
        await queue.close()

    @pytest.mark.asyncio
    async def test_start_idempotent(self):
        from cn_commerce_base import AsyncRequestQueue

        queue = AsyncRequestQueue(max_workers=2)
        await queue.start()
        await queue.start()  # Should not create duplicate workers
        assert queue.is_running is True
        await queue.close()

    @pytest.mark.asyncio
    async def test_enqueue_with_params_and_data(self):
        from cn_commerce_base import AsyncRequestQueue

        captured = {}
        queue = AsyncRequestQueue(max_workers=2)

        async def processor(method, path, params, data):
            captured["method"] = method
            captured["path"] = path
            captured["params"] = params
            captured["data"] = data
            return "ok"

        queue.set_processor(processor)
        await queue.enqueue(
            "POST",
            "/api/orders",
            params={"page": 1},
            data={"item_id": 123},
            request_id="req-1",
        )
        assert captured["method"] == "POST"
        assert captured["path"] == "/api/orders"
        assert captured["params"]["page"] == 1
        assert captured["data"]["item_id"] == 123
        await queue.close()

    @pytest.mark.asyncio
    async def test_multiple_workers_concurrent(self):
        from cn_commerce_base import AsyncRequestQueue

        results_log = []
        queue = AsyncRequestQueue(max_workers=3)

        async def processor(method, path, params, data):
            results_log.append(path)
            return f"ok-{path}"

        queue.set_processor(processor)
        # enqueue auto-starts the queue
        r1 = await queue.enqueue("GET", "/1")
        r2 = await queue.enqueue("GET", "/2")
        r3 = await queue.enqueue("GET", "/3")
        assert r1 == "ok-/1"
        assert r2 == "ok-/2"
        assert r3 == "ok-/3"
        assert len(results_log) == 3
        await queue.close()
