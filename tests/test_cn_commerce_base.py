"""Tests for the shared cn_commerce_base module.

Tests the base classes, error handling, and utility functions.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import zlib
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
    AuditEntry,
    AuditLog,
    BatchRequestItem,
    BatchResultItem,
    BatchSummary,
    CacheWarmer,
    CommerceAPIError,
    CommerceMCPBase,
    CompressionConfig,
    CompressionMethod,
    ConfigurableRateLimiter,
    ConfigValidationError,
    DecompressionStats,
    EncryptionConfig,
    EncryptionMethod,
    EndpointMetrics,
    EndpointRateLimit,
    MetricsCollector,
    PlatformRateLimitConfig,
    PrioritizedRequest,
    PriorityQueue,
    PriorityScheduler,
    PriorityStats,
    RateLimitConfig,
    RateLimiter,
    RateLimitStats,
    RequestCacheConfig,
    RequestCacheStats,
    RequestCompressor,
    RequestEncryptor,
    RequestPriority,
    RequestResultCache,
    ResponseDecompressor,
    RetryableError,
    RetryConfig,
    SensitiveDataFilter,
    SignMethod,
    WarmupResult,
    WarmupTask,
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


class TestWarmupTask:
    """Tests for WarmupTask dataclass."""

    def test_basic_creation(self):
        async def fetch():
            return {}

        task = WarmupTask(platform="TEST", cache_key="key1", fetch_fn=fetch)
        assert task.platform == "TEST"
        assert task.cache_key == "key1"
        assert task.priority == 0
        assert task.enabled is True

    def test_custom_priority(self):
        async def fetch():
            return {}

        task = WarmupTask(platform="TEST", cache_key="key1", fetch_fn=fetch, priority=5)
        assert task.priority == 5

    def test_disabled(self):
        async def fetch():
            return {}

        task = WarmupTask(platform="TEST", cache_key="key1", fetch_fn=fetch, enabled=False)
        assert task.enabled is False


# ── WarmupResult Tests ────────────────────────────────────


class TestWarmupResult:
    """Tests for WarmupResult dataclass."""

    def test_default_values(self):
        r = WarmupResult()
        assert r.platform == ""
        assert r.cache_key == ""
        assert r.success is True
        assert r.latency_ms == 0.0
        assert r.error == ""

    def test_with_values(self):
        r = WarmupResult(
            platform="TEST",
            cache_key="key1",
            success=False,
            latency_ms=42.5,
            error="timeout",
        )
        assert r.platform == "TEST"
        assert r.cache_key == "key1"
        assert r.success is False
        assert r.latency_ms == 42.5
        assert r.error == "timeout"


# ── CacheWarmer Tests ─────────────────────────────────────


class TestCacheWarmer:
    """Tests for CacheWarmer."""

    def test_register_task(self):
        warmer = CacheWarmer()

        async def fetch():
            return {"data": 1}

        warmer.register("TEST", "key1", fetch)
        stats = warmer.get_stats()
        assert stats["registered_tasks"] == 1

    def test_register_multiple_tasks(self):
        warmer = CacheWarmer()

        async def fetch1():
            return {}

        async def fetch2():
            return {}

        warmer.register("TEST", "key1", fetch1, priority=1)
        warmer.register("TEST", "key2", fetch2, priority=0)
        stats = warmer.get_stats()
        assert stats["registered_tasks"] == 2

    def test_unregister_task(self):
        warmer = CacheWarmer()

        async def fetch():
            return {}

        warmer.register("TEST", "key1", fetch)
        assert warmer.unregister("TEST", "key1") is True
        stats = warmer.get_stats()
        assert stats["registered_tasks"] == 0

    def test_unregister_nonexistent(self):
        warmer = CacheWarmer()
        assert warmer.unregister("TEST", "missing") is False

    @pytest.mark.asyncio
    async def test_warmup_all(self):
        warmer = CacheWarmer()
        call_count = 0

        async def fetch():
            nonlocal call_count
            call_count += 1
            return {"id": call_count}

        warmer.register("TEST", "key1", fetch)
        warmer.register("TEST", "key2", fetch)
        results = await warmer.warmup_all()
        assert len(results) == 2
        assert all(r.success for r in results)
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_warmup_all_skips_disabled(self):
        warmer = CacheWarmer()

        async def fetch():
            return {}

        warmer.register("TEST", "key1", fetch, enabled=False)
        warmer.register("TEST", "key2", fetch, enabled=True)
        results = await warmer.warmup_all()
        assert len(results) == 1
        assert results[0].cache_key == "key2"

    @pytest.mark.asyncio
    async def test_warmup_all_handles_failure(self):
        warmer = CacheWarmer()

        async def fetch_ok():
            return {"ok": True}

        async def fetch_fail():
            raise ValueError("fetch error")

        warmer.register("TEST", "ok_key", fetch_ok)
        warmer.register("TEST", "fail_key", fetch_fail)
        results = await warmer.warmup_all()
        assert len(results) == 2
        assert results[0].success is True
        assert results[1].success is False
        assert "fetch error" in results[1].error

    @pytest.mark.asyncio
    async def test_warmup_platform(self):
        warmer = CacheWarmer()

        async def fetch1():
            return {"p1": 1}

        async def fetch2():
            return {"p2": 2}

        warmer.register("P1", "key1", fetch1)
        warmer.register("P2", "key2", fetch2)
        results = await warmer.warmup_platform("P1")
        assert len(results) == 1
        assert results[0].platform == "P1"

    @pytest.mark.asyncio
    async def test_warmup_platform_empty(self):
        warmer = CacheWarmer()
        results = await warmer.warmup_platform("UNKNOWN")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_get_cached_after_warmup(self):
        warmer = CacheWarmer()

        async def fetch():
            return {"products": [1, 2, 3]}

        warmer.register("TEST", "products", fetch, ttl_seconds=60)
        await warmer.warmup_all()
        cached = warmer.get_cached("products")
        assert cached == {"products": [1, 2, 3]}

    def test_get_cached_miss(self):
        warmer = CacheWarmer()
        assert warmer.get_cached("missing") is None

    @pytest.mark.asyncio
    async def test_get_cached_expired(self):
        warmer = CacheWarmer()

        async def fetch():
            return {"data": 1}

        warmer.register("TEST", "key1", fetch, ttl_seconds=0)
        await warmer.warmup_all()
        # TTL is 0, so it should be expired immediately
        # (depending on timing, but practically immediate)
        import time as _time

        _time.sleep(0.01)
        assert warmer.get_cached("key1") is None

    def test_set_cached(self):
        warmer = CacheWarmer()
        warmer.set_cached("manual_key", {"value": 42}, ttl_seconds=60)
        assert warmer.get_cached("manual_key") == {"value": 42}

    def test_invalidate_single(self):
        warmer = CacheWarmer()
        warmer.set_cached("key1", "val1")
        warmer.set_cached("key2", "val2")
        warmer.invalidate("key1")
        assert warmer.get_cached("key1") is None
        assert warmer.get_cached("key2") == "val2"

    def test_invalidate_all(self):
        warmer = CacheWarmer()
        warmer.set_cached("key1", "val1")
        warmer.set_cached("key2", "val2")
        warmer.invalidate()
        assert warmer.get_cached("key1") is None
        assert warmer.get_cached("key2") is None

    @pytest.mark.asyncio
    async def test_warmup_latency_tracked(self):
        warmer = CacheWarmer()

        async def fetch():
            import asyncio

            await asyncio.sleep(0.01)
            return {}

        warmer.register("TEST", "key1", fetch)
        results = await warmer.warmup_all()
        assert results[0].latency_ms > 0

    @pytest.mark.asyncio
    async def test_warmup_history(self):
        warmer = CacheWarmer()

        async def fetch_ok():
            return {}

        async def fetch_fail():
            raise RuntimeError("fail")

        warmer.register("TEST", "ok", fetch_ok)
        warmer.register("TEST", "fail", fetch_fail)
        await warmer.warmup_all()
        history = warmer.get_history()
        assert len(history) == 2
        assert history[0]["success"] is True
        assert history[1]["success"] is False

    @pytest.mark.asyncio
    async def test_warmup_history_limit(self):
        warmer = CacheWarmer()

        async def fetch():
            return {}

        for i in range(10):
            warmer.register("TEST", f"key{i}", fetch)
        await warmer.warmup_all()
        history = warmer.get_history(limit=5)
        assert len(history) == 5

    @pytest.mark.asyncio
    async def test_scheduled_warmup_start_stop(self):
        warmer = CacheWarmer()
        assert warmer.is_scheduled is False

        async def fetch():
            return {}

        warmer.register("TEST", "key1", fetch)
        task = warmer.start_scheduled(interval_seconds=0.1)
        assert warmer.is_scheduled is True
        assert task is not None

        warmer.stop_scheduled()
        # Give a moment for cancellation to propagate
        import asyncio

        await asyncio.sleep(0.05)
        assert warmer.is_scheduled is False

    @pytest.mark.asyncio
    async def test_scheduled_warmup_runs(self):
        warmer = CacheWarmer()
        call_count = 0

        async def fetch():
            nonlocal call_count
            call_count += 1
            return {"count": call_count}

        warmer.register("TEST", "key1", fetch)
        warmer.start_scheduled(interval_seconds=0.05)
        import asyncio

        await asyncio.sleep(0.2)  # Let it run a few cycles
        warmer.stop_scheduled()
        # Should have been called at least twice
        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_scheduled_warmup_platforms_filter(self):
        warmer = CacheWarmer()
        p1_count = 0
        p2_count = 0

        async def fetch_p1():
            nonlocal p1_count
            p1_count += 1
            return {}

        async def fetch_p2():
            nonlocal p2_count
            p2_count += 1
            return {}

        warmer.register("P1", "key1", fetch_p1)
        warmer.register("P2", "key2", fetch_p2)
        warmer.start_scheduled(interval_seconds=0.05, warmup_platforms=["P1"])
        import asyncio

        await asyncio.sleep(0.2)
        warmer.stop_scheduled()
        assert p1_count >= 2
        assert p2_count == 0  # P2 should not be warmed

    @pytest.mark.asyncio
    async def test_warmup_stats_after_execution(self):
        warmer = CacheWarmer()

        async def fetch():
            return {}

        warmer.register("TEST", "key1", fetch)
        await warmer.warmup_all()
        stats = warmer.get_stats()
        assert stats["registered_tasks"] == 1
        assert "key1" in stats["cached_keys"]
        assert stats["cached_count"] == 1
        assert stats["history"]["total"] == 1
        assert stats["history"]["succeeded"] == 1


# ── CompressionMethod Tests ───────────────────────────────


class TestCompressionMethod:
    """Tests for CompressionMethod enum."""

    def test_none(self):
        assert CompressionMethod.NONE == "none"

    def test_gzip(self):
        assert CompressionMethod.GZIP == "gzip"

    def test_deflate(self):
        assert CompressionMethod.DEFLATE == "deflate"

    def test_auto(self):
        assert CompressionMethod.AUTO == "auto"


# ── CompressionConfig Tests ───────────────────────────────


class TestCompressionConfig:
    """Tests for CompressionConfig dataclass."""

    def test_default_values(self):
        cfg = CompressionConfig()
        assert cfg.method == CompressionMethod.NONE
        assert cfg.min_size_bytes == 1024
        assert cfg.gzip_level == 6
        assert cfg.include_content_encoding is True

    def test_custom_values(self):
        cfg = CompressionConfig(
            method=CompressionMethod.GZIP,
            min_size_bytes=512,
            gzip_level=9,
            include_content_encoding=False,
        )
        assert cfg.method == CompressionMethod.GZIP
        assert cfg.min_size_bytes == 512
        assert cfg.gzip_level == 9
        assert cfg.include_content_encoding is False

    def test_to_dict(self):
        cfg = CompressionConfig(method=CompressionMethod.GZIP)
        d = cfg.to_dict()
        assert d["method"] == "gzip"
        assert d["min_size_bytes"] == 1024

    def test_from_dict(self):
        data = {
            "method": "deflate",
            "min_size_bytes": 2048,
            "gzip_level": 3,
            "include_content_encoding": False,
        }
        cfg = CompressionConfig.from_dict(data)
        assert cfg.method == CompressionMethod.DEFLATE
        assert cfg.min_size_bytes == 2048
        assert cfg.gzip_level == 3
        assert cfg.include_content_encoding is False

    def test_roundtrip(self):
        original = CompressionConfig(method=CompressionMethod.GZIP, min_size_bytes=512)
        d = original.to_dict()
        restored = CompressionConfig.from_dict(d)
        assert restored.method == original.method
        assert restored.min_size_bytes == original.min_size_bytes


# ── RequestCompressor Tests ───────────────────────────────


class TestRequestCompressor:
    """Tests for RequestCompressor."""

    def test_default_no_compression(self):
        compressor = RequestCompressor()
        body = b'{"data": "test"}'
        result, headers = compressor.compress(body)
        assert result == body
        assert headers == {}

    def test_gzip_compression(self):
        config = CompressionConfig(
            method=CompressionMethod.GZIP,
            min_size_bytes=0,
        )
        compressor = RequestCompressor(config)
        body = b'{"data": "' + b"x" * 2000 + b'"}'
        result, headers = compressor.compress(body)
        assert len(result) < len(body)
        assert headers.get("Content-Encoding") == "gzip"

    def test_deflate_compression(self):
        config = CompressionConfig(
            method=CompressionMethod.DEFLATE,
            min_size_bytes=0,
        )
        compressor = RequestCompressor(config)
        body = b'{"data": "' + b"x" * 2000 + b'"}'
        result, headers = compressor.compress(body)
        assert len(result) < len(body)
        assert headers.get("Content-Encoding") == "deflate"

    def test_min_size_threshold(self):
        config = CompressionConfig(
            method=CompressionMethod.GZIP,
            min_size_bytes=1000,
        )
        compressor = RequestCompressor(config)
        small_body = b"small"
        result, headers = compressor.compress(small_body)
        assert result == small_body
        assert headers == {}

    def test_auto_selects_gzip(self):
        config = CompressionConfig(method=CompressionMethod.AUTO, min_size_bytes=0)
        compressor = RequestCompressor(config)
        body = b'{"data": "' + b"x" * 2000 + b'"}'
        result, headers = compressor.compress(body)
        assert headers.get("Content-Encoding") == "gzip"

    def test_auto_with_accept_encoding_gzip(self):
        config = CompressionConfig(method=CompressionMethod.AUTO, min_size_bytes=0)
        compressor = RequestCompressor(config)
        body = b'{"data": "' + b"x" * 2000 + b'"}'
        result, headers = compressor.compress(body, accept_encoding="gzip, deflate")
        assert headers.get("Content-Encoding") == "gzip"

    def test_auto_with_accept_encoding_deflate_only(self):
        config = CompressionConfig(method=CompressionMethod.AUTO, min_size_bytes=0)
        compressor = RequestCompressor(config)
        body = b'{"data": "' + b"x" * 2000 + b'"}'
        result, headers = compressor.compress(body, accept_encoding="deflate")
        assert headers.get("Content-Encoding") == "deflate"

    def test_no_content_encoding_header_when_disabled(self):
        config = CompressionConfig(
            method=CompressionMethod.GZIP,
            min_size_bytes=0,
            include_content_encoding=False,
        )
        compressor = RequestCompressor(config)
        body = b'{"data": "' + b"x" * 2000 + b'"}'
        result, headers = compressor.compress(body)
        assert len(result) < len(body)
        assert "Content-Encoding" not in headers

    def test_compression_actually_works_gzip(self):
        """Verify gzip-compressed data can be decompressed."""
        import gzip as gzip_mod

        config = CompressionConfig(
            method=CompressionMethod.GZIP,
            min_size_bytes=0,
        )
        compressor = RequestCompressor(config)
        original = b'{"products": ["a", "b", "c"]}' * 100
        compressed, _ = compressor.compress(original)
        decompressed = gzip_mod.decompress(compressed)
        assert decompressed == original

    def test_compression_actually_works_deflate(self):
        """Verify deflate-compressed data can be decompressed."""
        config = CompressionConfig(
            method=CompressionMethod.DEFLATE,
            min_size_bytes=0,
        )
        compressor = RequestCompressor(config)
        original = b'{"products": ["a", "b", "c"]}' * 100
        compressed, _ = compressor.compress(original)
        decompressed = zlib.decompress(compressed)
        assert decompressed == original

    def test_stats_tracking(self):
        config = CompressionConfig(
            method=CompressionMethod.GZIP,
            min_size_bytes=0,
        )
        compressor = RequestCompressor(config)
        compressor.compress(b"x" * 1000)
        compressor.compress(b"y" * 500)
        stats = compressor.get_stats()
        assert stats["total_requests"] == 2
        assert stats["compressed_requests"] == 2
        assert stats["total_original_bytes"] == 1500
        assert stats["bytes_saved"] > 0

    def test_stats_compression_rate(self):
        config = CompressionConfig(
            method=CompressionMethod.GZIP,
            min_size_bytes=500,  # Skip small bodies
        )
        compressor = RequestCompressor(config)
        compressor.compress(b"small")  # Skipped
        compressor.compress(b"x" * 1000)  # Compressed
        stats = compressor.get_stats()
        assert stats["total_requests"] == 2
        assert stats["compressed_requests"] == 1
        assert stats["compression_rate"] == 0.5

    def test_reset_stats(self):
        config = CompressionConfig(method=CompressionMethod.GZIP, min_size_bytes=0)
        compressor = RequestCompressor(config)
        compressor.compress(b"x" * 1000)
        compressor.reset_stats()
        stats = compressor.get_stats()
        assert stats["total_requests"] == 0
        assert stats["total_original_bytes"] == 0

    def test_empty_body(self):
        compressor = RequestCompressor()
        result, headers = compressor.compress(b"")
        assert result == b""
        assert headers == {}


# ── CommerceMCPBase Compression Integration ───────────────


class TestCommerceMCPBaseCompression:
    """Tests for CommerceMCPBase compression integration."""

    def test_default_no_compression(self):
        client = CommerceMCPBase()
        assert client._compressor.config.method == CompressionMethod.NONE

    def test_custom_compression_config(self):
        config = CompressionConfig(method=CompressionMethod.GZIP)
        client = CommerceMCPBase(compression_config=config)
        assert client._compressor.config.method == CompressionMethod.GZIP

    def test_get_compression_stats(self):
        client = CommerceMCPBase()
        stats = client.get_compression_stats()
        assert "total_requests" in stats
        assert "compressed_requests" in stats

    @pytest.mark.asyncio
    async def test_post_with_gzip_compression(self):
        config = CompressionConfig(
            method=CompressionMethod.GZIP,
            min_size_bytes=0,
        )
        client = CommerceMCPBase(app_key="k", app_secret="s", compression_config=config)
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": "ok"}
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.is_closed = False

        with patch.object(client, "_ensure_client", return_value=mock_client):
            await client._request("POST", "/api/test", data={"key": "x" * 100})

        # Verify post was called with compressed content
        call_kwargs = mock_client.post.call_args.kwargs
        assert "content" in call_kwargs
        assert call_kwargs["headers"]["Content-Encoding"] == "gzip"

    @pytest.mark.asyncio
    async def test_post_small_body_not_compressed(self):
        config = CompressionConfig(
            method=CompressionMethod.GZIP,
            min_size_bytes=10000,  # Very high threshold
        )
        client = CommerceMCPBase(app_key="k", app_secret="s", compression_config=config)
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": "ok"}
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.is_closed = False

        with patch.object(client, "_ensure_client", return_value=mock_client):
            await client._request("POST", "/api/test", data={"key": "small"})

        # Verify post was called with json= (not compressed)
        call_kwargs = mock_client.post.call_args.kwargs
        assert "json" in call_kwargs

    @pytest.mark.asyncio
    async def test_get_not_compressed(self):
        config = CompressionConfig(
            method=CompressionMethod.GZIP,
            min_size_bytes=0,
        )
        client = CommerceMCPBase(app_key="k", app_secret="s", compression_config=config)
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": "ok"}
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.is_closed = False

        with patch.object(client, "_ensure_client", return_value=mock_client):
            await client._request("GET", "/api/test")

        # GET should use normal params, not compression
        mock_client.get.assert_called_once()


# ── CommerceMCPBase CacheWarmer Integration ───────────────


class TestCommerceMCPBaseCacheWarmer:
    """Tests for CommerceMCPBase cache_warmer integration."""

    def test_has_cache_warmer(self):
        client = CommerceMCPBase()
        assert isinstance(client.cache_warmer, CacheWarmer)

    @pytest.mark.asyncio
    async def test_warmup_cache_all(self):
        client = CommerceMCPBase()
        call_count = 0

        async def fetch():
            nonlocal call_count
            call_count += 1
            return {"data": call_count}

        client.cache_warmer.register("TEST", "key1", fetch)
        results = await client.warmup_cache()
        assert len(results) == 1
        assert results[0]["success"] is True
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_warmup_cache_specific_platform(self):
        client = CommerceMCPBase()

        async def fetch_p1():
            return {"p1": 1}

        async def fetch_p2():
            return {"p2": 2}

        client.cache_warmer.register("P1", "key1", fetch_p1)
        client.cache_warmer.register("P2", "key2", fetch_p2)
        results = await client.warmup_cache(platforms=["P1"])
        assert len(results) == 1
        assert results[0]["platform"] == "P1"

    @pytest.mark.asyncio
    async def test_warmup_cache_returns_dicts(self):
        """warmup_cache should return JSON-serializable dicts."""
        client = CommerceMCPBase()

        async def fetch():
            return {}

        client.cache_warmer.register("TEST", "key1", fetch)
        results = await client.warmup_cache()
        assert isinstance(results, list)
        assert isinstance(results[0], dict)
        assert "platform" in results[0]
        assert "cache_key" in results[0]
        assert "success" in results[0]
        assert "latency_ms" in results[0]
        assert "error" in results[0]


# ── Concurrency Tests for New Features ────────────────────


class TestCacheWarmerConcurrency:
    """Thread-safety tests for CacheWarmer."""

    def test_concurrent_set_and_get_cached(self):
        import threading

        warmer = CacheWarmer()
        errors = []

        def writer():
            for i in range(100):
                warmer.set_cached(f"key_{i}", f"value_{i}")

        def reader():
            for i in range(100):
                try:
                    warmer.get_cached(f"key_{i}")
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []

    def test_concurrent_invalidate(self):
        import threading

        warmer = CacheWarmer()

        def writer():
            for i in range(50):
                warmer.set_cached(f"k{i}", f"v{i}")

        def invalidator():
            for _ in range(50):
                warmer.invalidate()

        threads = [threading.Thread(target=writer), threading.Thread(target=invalidator)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # Should not raise


class TestRequestCompressorConcurrency:
    """Thread-safety tests for RequestCompressor."""

    def test_concurrent_compress(self):
        import threading

        config = CompressionConfig(method=CompressionMethod.GZIP, min_size_bytes=0)
        compressor = RequestCompressor(config)
        errors = []

        def compress_batch():
            try:
                for _ in range(50):
                    compressor.compress(b"x" * 500)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=compress_batch) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        stats = compressor.get_stats()
        assert stats["total_requests"] == 200


# ── RequestPriority Tests ──────────────────────────────────


class TestRequestPriority:
    """Tests for RequestPriority enum."""

    def test_critical_value(self):
        assert RequestPriority.CRITICAL == "critical"

    def test_high_value(self):
        assert RequestPriority.HIGH == "high"

    def test_normal_value(self):
        assert RequestPriority.NORMAL == "normal"

    def test_low_value(self):
        assert RequestPriority.LOW == "low"

    def test_is_str_enum(self):
        assert isinstance(RequestPriority.CRITICAL, str)


# ── PrioritizedRequest Tests ───────────────────────────────


class TestPrioritizedRequest:
    """Tests for PrioritizedRequest dataclass."""

    def test_default_values(self):
        req = PrioritizedRequest()
        assert req.priority == RequestPriority.NORMAL
        assert req.method == ""
        assert req.path == ""
        assert req.params == {}
        assert req.data == {}
        assert req.request_id == ""
        assert req.platform == ""

    def test_custom_values(self):
        req = PrioritizedRequest(
            priority=RequestPriority.HIGH,
            method="GET",
            path="/api/orders",
            params={"page": 1},
            data={"filter": "active"},
            request_id="req-1",
            platform="OCEANENGINE",
        )
        assert req.priority == RequestPriority.HIGH
        assert req.method == "GET"
        assert req.path == "/api/orders"
        assert req.params == {"page": 1}
        assert req.data == {"filter": "active"}
        assert req.request_id == "req-1"
        assert req.platform == "OCEANENGINE"

    def test_priority_weight_critical(self):
        req = PrioritizedRequest(priority=RequestPriority.CRITICAL)
        assert req.priority_weight == 0

    def test_priority_weight_high(self):
        req = PrioritizedRequest(priority=RequestPriority.HIGH)
        assert req.priority_weight == 1

    def test_priority_weight_normal(self):
        req = PrioritizedRequest(priority=RequestPriority.NORMAL)
        assert req.priority_weight == 2

    def test_priority_weight_low(self):
        req = PrioritizedRequest(priority=RequestPriority.LOW)
        assert req.priority_weight == 3

    def test_created_at_auto_set(self):
        req = PrioritizedRequest()
        assert req.created_at > 0

    def test_params_default_factory(self):
        a = PrioritizedRequest()
        b = PrioritizedRequest()
        a.params["key"] = "val"
        assert "key" not in b.params


# ── PriorityQueue Tests ────────────────────────────────────


class TestPriorityQueue:
    """Tests for PriorityQueue."""

    def test_enqueue_dequeue_order(self):
        pq = PriorityQueue()
        low = PrioritizedRequest(priority=RequestPriority.LOW, path="/low")
        high = PrioritizedRequest(priority=RequestPriority.HIGH, path="/high")
        normal = PrioritizedRequest(priority=RequestPriority.NORMAL, path="/normal")
        critical = PrioritizedRequest(priority=RequestPriority.CRITICAL, path="/critical")

        pq.enqueue(low)
        pq.enqueue(high)
        pq.enqueue(normal)
        pq.enqueue(critical)

        assert pq.dequeue().path == "/critical"
        assert pq.dequeue().path == "/high"
        assert pq.dequeue().path == "/normal"
        assert pq.dequeue().path == "/low"

    def test_fifo_within_same_priority(self):
        pq = PriorityQueue()
        r1 = PrioritizedRequest(priority=RequestPriority.NORMAL, path="/first", created_at=1.0)
        r2 = PrioritizedRequest(priority=RequestPriority.NORMAL, path="/second", created_at=2.0)
        r3 = PrioritizedRequest(priority=RequestPriority.NORMAL, path="/third", created_at=3.0)

        pq.enqueue(r1)
        pq.enqueue(r2)
        pq.enqueue(r3)

        assert pq.dequeue().path == "/first"
        assert pq.dequeue().path == "/second"
        assert pq.dequeue().path == "/third"

    def test_empty_queue_returns_none(self):
        pq = PriorityQueue()
        assert pq.dequeue() is None

    def test_peek_does_not_remove(self):
        pq = PriorityQueue()
        req = PrioritizedRequest(priority=RequestPriority.HIGH, path="/test")
        pq.enqueue(req)
        peeked = pq.peek()
        assert peeked is not None
        assert peeked.path == "/test"
        assert pq.size == 1
        pq.dequeue()

    def test_peek_empty_returns_none(self):
        pq = PriorityQueue()
        assert pq.peek() is None

    def test_size(self):
        pq = PriorityQueue()
        assert pq.size == 0
        pq.enqueue(PrioritizedRequest(path="/a"))
        assert pq.size == 1
        pq.enqueue(PrioritizedRequest(path="/b"))
        assert pq.size == 2
        pq.dequeue()
        assert pq.size == 1

    def test_is_empty(self):
        pq = PriorityQueue()
        assert pq.is_empty is True
        pq.enqueue(PrioritizedRequest(path="/a"))
        assert pq.is_empty is False
        pq.dequeue()
        assert pq.is_empty is True

    def test_max_size_enforced(self):
        pq = PriorityQueue(max_size=2)
        pq.enqueue(PrioritizedRequest(path="/a"))
        pq.enqueue(PrioritizedRequest(path="/b"))
        with pytest.raises(RuntimeError, match="full"):
            pq.enqueue(PrioritizedRequest(path="/c"))

    def test_clear(self):
        pq = PriorityQueue()
        pq.enqueue(PrioritizedRequest(path="/a"))
        pq.enqueue(PrioritizedRequest(path="/b"))
        pq.clear()
        assert pq.size == 0
        assert pq.is_empty is True
        assert pq.dequeue() is None

    def test_get_priority_distribution(self):
        pq = PriorityQueue()
        pq.enqueue(PrioritizedRequest(priority=RequestPriority.HIGH, path="/h"))
        pq.enqueue(PrioritizedRequest(priority=RequestPriority.HIGH, path="/h2"))
        pq.enqueue(PrioritizedRequest(priority=RequestPriority.LOW, path="/l"))
        pq.enqueue(PrioritizedRequest(priority=RequestPriority.NORMAL, path="/n"))
        dist = pq.get_priority_distribution()
        assert dist["high"] == 2
        assert dist["low"] == 1
        assert dist["normal"] == 1
        assert "critical" not in dist


class TestPriorityQueueConcurrency:
    """Thread-safety tests for PriorityQueue."""

    def test_concurrent_enqueue_dequeue(self):
        import threading

        pq = PriorityQueue()
        dequeued = []
        errors = []

        def producer():
            try:
                for i in range(100):
                    pq.enqueue(PrioritizedRequest(priority=RequestPriority.NORMAL, path=f"/{i}"))
            except Exception as e:
                errors.append(e)

        def consumer():
            try:
                for _ in range(100):
                    req = pq.dequeue()
                    if req is not None:
                        dequeued.append(req)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=producer)
        t2 = threading.Thread(target=consumer)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        assert errors == []

    def test_concurrent_multiple_priorities(self):
        import threading

        pq = PriorityQueue()

        def enqueue_batch(priority, count):
            for i in range(count):
                pq.enqueue(PrioritizedRequest(priority=priority, path=f"/{priority.value}_{i}"))

        threads = [
            threading.Thread(target=enqueue_batch, args=(RequestPriority.CRITICAL, 50)),
            threading.Thread(target=enqueue_batch, args=(RequestPriority.HIGH, 50)),
            threading.Thread(target=enqueue_batch, args=(RequestPriority.NORMAL, 50)),
            threading.Thread(target=enqueue_batch, args=(RequestPriority.LOW, 50)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert pq.size == 200
        results = []
        while not pq.is_empty:
            results.append(pq.dequeue())

        critical = [r for r in results if r.priority == RequestPriority.CRITICAL]
        high = [r for r in results if r.priority == RequestPriority.HIGH]
        normal = [r for r in results if r.priority == RequestPriority.NORMAL]
        low = [r for r in results if r.priority == RequestPriority.LOW]
        assert len(critical) == 50
        assert len(high) == 50
        assert len(normal) == 50
        assert len(low) == 50


# ── PriorityStats Tests ────────────────────────────────────


class TestPriorityStats:
    """Tests for PriorityStats dataclass."""

    def test_default_values(self):
        stats = PriorityStats()
        assert stats.total_dispatched == 0
        assert stats.by_priority == {}
        assert stats.total_delayed == 0
        assert stats.total_reordered == 0

    def test_record_dispatch(self):
        stats = PriorityStats()
        stats.record_dispatch("high", queue_time_ms=50.0)
        assert stats.total_dispatched == 1
        assert stats.by_priority["high"] == 1
        assert stats.total_delayed == 1
        assert stats.max_queue_time_ms == 50.0

    def test_record_dispatch_zero_queue_time(self):
        stats = PriorityStats()
        stats.record_dispatch("normal", queue_time_ms=0.0)
        assert stats.total_dispatched == 1
        assert stats.total_delayed == 0

    def test_record_dispatch_reordered(self):
        stats = PriorityStats()
        stats.record_dispatch("critical", queue_time_ms=10.0, reordered=True)
        assert stats.total_reordered == 1

    def test_avg_queue_time_ms(self):
        stats = PriorityStats()
        assert stats.avg_queue_time_ms == 0.0
        stats.record_dispatch("high", queue_time_ms=100.0)
        stats.record_dispatch("high", queue_time_ms=200.0)
        assert stats.avg_queue_time_ms == pytest.approx(150.0)

    def test_max_queue_time_ms(self):
        stats = PriorityStats()
        stats.record_dispatch("high", queue_time_ms=50.0)
        stats.record_dispatch("high", queue_time_ms=200.0)
        stats.record_dispatch("high", queue_time_ms=100.0)
        assert stats.max_queue_time_ms == 200.0

    def test_get_summary(self):
        stats = PriorityStats()
        stats.record_dispatch("high", queue_time_ms=50.0)
        stats.record_dispatch("low", queue_time_ms=100.0, reordered=True)
        summary = stats.get_summary()
        assert summary["total_dispatched"] == 2
        assert summary["by_priority"]["high"] == 1
        assert summary["by_priority"]["low"] == 1
        assert summary["total_delayed"] == 2
        assert summary["total_reordered"] == 1

    def test_reset(self):
        stats = PriorityStats()
        stats.record_dispatch("high", queue_time_ms=50.0, reordered=True)
        stats.reset()
        assert stats.total_dispatched == 0
        assert stats.by_priority == {}
        assert stats.total_delayed == 0
        assert stats.total_reordered == 0

    def test_multiple_priorities_tracked(self):
        stats = PriorityStats()
        stats.record_dispatch("critical", 10.0)
        stats.record_dispatch("high", 20.0)
        stats.record_dispatch("normal", 30.0)
        stats.record_dispatch("low", 40.0)
        assert stats.by_priority["critical"] == 1
        assert stats.by_priority["high"] == 1
        assert stats.by_priority["normal"] == 1
        assert stats.by_priority["low"] == 1


# ── PriorityScheduler Tests ────────────────────────────────


class TestPriorityScheduler:
    """Tests for PriorityScheduler."""

    def test_init(self):
        scheduler = PriorityScheduler()
        assert scheduler.queue_size == 0
        assert scheduler.queue_empty is True

    def test_init_with_rate_limiter(self):
        limiter = ConfigurableRateLimiter()
        scheduler = PriorityScheduler(rate_limiter=limiter)
        assert scheduler._rate_limiter is limiter

    def test_enqueue_dequeue(self):
        scheduler = PriorityScheduler()
        req = PrioritizedRequest(priority=RequestPriority.HIGH, path="/test")
        scheduler.enqueue(req)
        assert scheduler.queue_size == 1
        dequeued = scheduler.dequeue()
        assert dequeued is not None
        assert dequeued.path == "/test"

    @pytest.mark.asyncio
    async def test_schedule_and_execute(self):
        scheduler = PriorityScheduler()
        req = PrioritizedRequest(
            priority=RequestPriority.HIGH,
            method="GET",
            path="/api/orders",
            params={"page": 1},
        )

        async def mock_execute(r):
            return {"result": "ok", "path": r.path}

        result = await scheduler.schedule_and_execute(req, mock_execute)
        assert result["result"] == "ok"
        assert result["path"] == "/api/orders"
        assert scheduler.stats.total_dispatched == 1

    @pytest.mark.asyncio
    async def test_schedule_with_rate_limiter(self):
        limiter = ConfigurableRateLimiter(RateLimitConfig(enabled=False))
        scheduler = PriorityScheduler(rate_limiter=limiter)
        req = PrioritizedRequest(
            priority=RequestPriority.NORMAL,
            method="GET",
            path="/api/test",
            platform="TEST",
        )

        async def mock_execute(r):
            return {"ok": True}

        result = await scheduler.schedule_and_execute(req, mock_execute)
        assert result["ok"] is True

    def test_get_queue_distribution(self):
        scheduler = PriorityScheduler()
        scheduler.enqueue(PrioritizedRequest(priority=RequestPriority.HIGH, path="/h"))
        scheduler.enqueue(PrioritizedRequest(priority=RequestPriority.LOW, path="/l"))
        scheduler.enqueue(PrioritizedRequest(priority=RequestPriority.HIGH, path="/h2"))
        dist = scheduler.get_queue_distribution()
        assert dist["high"] == 2
        assert dist["low"] == 1

    def test_get_stats_summary(self):
        scheduler = PriorityScheduler()
        summary = scheduler.get_stats_summary()
        assert "queue_size" in summary
        assert "queue_distribution" in summary
        assert "stats" in summary

    def test_reset_stats(self):
        scheduler = PriorityScheduler()
        scheduler.stats.record_dispatch("high", 100.0)
        scheduler.reset_stats()
        assert scheduler.stats.total_dispatched == 0

    def test_clear_queue(self):
        scheduler = PriorityScheduler()
        scheduler.enqueue(PrioritizedRequest(path="/a"))
        scheduler.enqueue(PrioritizedRequest(path="/b"))
        scheduler.clear_queue()
        assert scheduler.queue_size == 0


# ── Dynamic Rate Limiting Tests ────────────────────────────


class TestDynamicRateLimiting:
    """Tests for ConfigurableRateLimiter dynamic adjustment methods."""

    def test_set_platform_rps_existing(self):
        config = RateLimitConfig(
            platforms={"TEST": PlatformRateLimitConfig(platform="TEST", default_requests_per_second=10.0)},
        )
        limiter = ConfigurableRateLimiter(config)
        limiter.set_platform_rps("TEST", 25.0)
        assert limiter.config.platforms["TEST"].default_requests_per_second == 25.0

    def test_set_platform_rps_creates_platform(self):
        limiter = ConfigurableRateLimiter()
        limiter.set_platform_rps("NEW", 5.0)
        assert "NEW" in limiter.config.platforms
        assert limiter.config.platforms["NEW"].default_requests_per_second == 5.0

    def test_set_endpoint_rps(self):
        config = RateLimitConfig(
            platforms={"TEST": PlatformRateLimitConfig(platform="TEST", default_requests_per_second=10.0)},
        )
        limiter = ConfigurableRateLimiter(config)
        limiter.set_endpoint_rps("TEST", "/api/slow", 1.0)
        assert limiter.config.platforms["TEST"].endpoints["/api/slow"].requests_per_second == 1.0

    def test_enable_platform(self):
        config = RateLimitConfig(
            platforms={"TEST": PlatformRateLimitConfig(platform="TEST", enabled=False)},
        )
        limiter = ConfigurableRateLimiter(config)
        limiter.enable_platform("TEST")
        assert limiter.config.platforms["TEST"].enabled is True

    def test_disable_platform(self):
        config = RateLimitConfig(
            platforms={"TEST": PlatformRateLimitConfig(platform="TEST", enabled=True)},
        )
        limiter = ConfigurableRateLimiter(config)
        limiter.disable_platform("TEST")
        assert limiter.config.platforms["TEST"].enabled is False

    def test_enable_disable_nonexistent_platform(self):
        limiter = ConfigurableRateLimiter()
        limiter.enable_platform("UNKNOWN")
        limiter.disable_platform("UNKNOWN")

    def test_auto_adjust_scale_down(self):
        config = RateLimitConfig(
            platforms={
                "TEST": PlatformRateLimitConfig(
                    platform="TEST",
                    default_requests_per_second=10.0,
                    endpoints={"/api/slow": EndpointRateLimit(endpoint="/api/slow", requests_per_second=10.0)},
                ),
            },
        )
        limiter = ConfigurableRateLimiter(config)
        for _ in range(8):
            limiter.stats.record_request("TEST", "/api/slow")
        for _ in range(5):
            limiter.stats.record_throttle("TEST", "/api/slow", 100.0)

        adjustments = limiter.auto_adjust_from_stats(throttle_threshold=0.3)
        assert "TEST:/api/slow" in adjustments["endpoints"]
        adj = adjustments["endpoints"]["TEST:/api/slow"]
        assert adj["action"] == "scale_down"
        assert adj["new_rps"] < 10.0

    def test_auto_adjust_scale_up(self):
        config = RateLimitConfig(
            platforms={
                "TEST": PlatformRateLimitConfig(
                    platform="TEST",
                    default_requests_per_second=10.0,
                    endpoints={"/api/fast": EndpointRateLimit(endpoint="/api/fast", requests_per_second=10.0)},
                ),
            },
        )
        limiter = ConfigurableRateLimiter(config)
        for _ in range(30):
            limiter.stats.record_request("TEST", "/api/fast")

        adjustments = limiter.auto_adjust_from_stats(throttle_threshold=0.3)
        if "TEST:/api/fast" in adjustments["endpoints"]:
            adj = adjustments["endpoints"]["TEST:/api/fast"]
            assert adj["action"] == "scale_up"
            assert adj["new_rps"] > 10.0

    def test_auto_adjust_insufficient_data(self):
        limiter = ConfigurableRateLimiter()
        for _ in range(3):
            limiter.stats.record_request("TEST", "/api/test")
        adjustments = limiter.auto_adjust_from_stats()
        assert adjustments["endpoints"] == {}


# ── CommerceMCPBase Priority Integration Tests ─────────────


class TestCommerceMCPBasePriority:
    """Tests for CommerceMCPBase priority and rate limit integration."""

    def test_has_priority_scheduler(self):
        client = CommerceMCPBase()
        assert isinstance(client._priority_scheduler, PriorityScheduler)

    def test_has_configurable_limiter(self):
        client = CommerceMCPBase()
        assert isinstance(client._configurable_limiter, ConfigurableRateLimiter)

    def test_priority_scheduler_property(self):
        client = CommerceMCPBase()
        assert client.priority_scheduler is client._priority_scheduler

    def test_configurable_limiter_property(self):
        client = CommerceMCPBase()
        assert client.configurable_limiter is client._configurable_limiter

    def test_custom_rate_limit_config(self):
        config = RateLimitConfig(default_requests_per_second=5.0)
        client = CommerceMCPBase(rate_limit_config=config)
        assert client._configurable_limiter.config.default_requests_per_second == 5.0

    def test_get_priority_stats(self):
        client = CommerceMCPBase()
        stats = client.get_priority_stats()
        assert "queue_size" in stats
        assert "queue_distribution" in stats
        assert "stats" in stats

    def test_get_rate_limit_stats(self):
        client = CommerceMCPBase()
        stats = client.get_rate_limit_stats()
        assert "config" in stats
        assert "stats" in stats

    def test_auto_adjust_rate_limits(self):
        client = CommerceMCPBase()
        result = client.auto_adjust_rate_limits()
        assert "platforms" in result
        assert "endpoints" in result

    @pytest.mark.asyncio
    async def test_prioritized_request_basic(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": {"id": 1}}
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.is_closed = False

        with patch.object(client, "_ensure_client", return_value=mock_client):
            result = await client.prioritized_request("GET", "/api/test", priority=RequestPriority.HIGH)
        assert result == {"result": {"id": 1}}

    @pytest.mark.asyncio
    async def test_prioritized_request_with_params(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": "ok"}
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.is_closed = False

        with patch.object(client, "_ensure_client", return_value=mock_client):
            result = await client.prioritized_request(
                "GET",
                "/api/orders",
                priority=RequestPriority.CRITICAL,
                params={"order_id": "12345"},
            )
        assert result == {"result": "ok"}

    @pytest.mark.asyncio
    async def test_prioritized_request_tracks_stats(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": "ok"}
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.is_closed = False

        with patch.object(client, "_ensure_client", return_value=mock_client):
            await client.prioritized_request("GET", "/api/test", priority=RequestPriority.HIGH)
        stats = client.get_priority_stats()
        assert stats["stats"]["total_dispatched"] == 1
        assert stats["stats"]["by_priority"]["high"] == 1


# ── RequestCacheConfig Tests ───────────────────────────────


class TestRequestCacheConfig:
    """Tests for RequestCacheConfig dataclass."""

    def test_default_values(self):
        cfg = RequestCacheConfig()
        assert cfg.enabled is True
        assert cfg.max_size == 512
        assert cfg.default_ttl_seconds == 300.0
        assert cfg.cacheable_methods == ("GET",)
        assert cfg.key_include_headers is False
        assert cfg.exclude_error_responses is True

    def test_custom_values(self):
        cfg = RequestCacheConfig(
            enabled=False,
            max_size=128,
            default_ttl_seconds=60.0,
            cacheable_methods=("GET", "POST"),
        )
        assert cfg.enabled is False
        assert cfg.max_size == 128
        assert cfg.default_ttl_seconds == 60.0
        assert cfg.cacheable_methods == ("GET", "POST")

    def test_to_dict(self):
        cfg = RequestCacheConfig(max_size=256)
        d = cfg.to_dict()
        assert d["max_size"] == 256
        assert d["cacheable_methods"] == ["GET"]

    def test_from_dict(self):
        data = {
            "enabled": False,
            "max_size": 64,
            "default_ttl_seconds": 120.0,
            "cacheable_methods": ["GET", "POST"],
        }
        cfg = RequestCacheConfig.from_dict(data)
        assert cfg.enabled is False
        assert cfg.max_size == 64
        assert cfg.cacheable_methods == ("GET", "POST")

    def test_roundtrip(self):
        original = RequestCacheConfig(max_size=100, default_ttl_seconds=60.0)
        d = original.to_dict()
        restored = RequestCacheConfig.from_dict(d)
        assert restored.max_size == original.max_size
        assert restored.default_ttl_seconds == original.default_ttl_seconds


# ── RequestCacheStats Tests ────────────────────────────────


class TestRequestCacheStats:
    """Tests for RequestCacheStats dataclass."""

    def test_default_values(self):
        stats = RequestCacheStats()
        assert stats.total_requests == 0
        assert stats.cache_hits == 0
        assert stats.cache_misses == 0
        assert stats.total_stored == 0
        assert stats.total_evicted == 0

    def test_hit_rate_no_requests(self):
        stats = RequestCacheStats()
        assert stats.hit_rate == 0.0

    def test_hit_rate_with_requests(self):
        stats = RequestCacheStats()
        stats.total_requests = 10
        stats.cache_hits = 7
        assert stats.hit_rate == pytest.approx(0.7)

    def test_to_dict(self):
        stats = RequestCacheStats(total_requests=5, cache_hits=3)
        d = stats.to_dict()
        assert d["total_requests"] == 5
        assert d["cache_hits"] == 3
        assert d["hit_rate"] == pytest.approx(0.6)

    def test_reset(self):
        stats = RequestCacheStats(total_requests=10, cache_hits=5)
        stats.reset()
        assert stats.total_requests == 0
        assert stats.cache_hits == 0


# ── RequestResultCache Tests ───────────────────────────────


class TestRequestResultCache:
    """Tests for RequestResultCache."""

    def test_make_key_deterministic(self):
        key1 = RequestResultCache.make_key("GET", "/api/test", {"page": "1"})
        key2 = RequestResultCache.make_key("GET", "/api/test", {"page": "1"})
        assert key1 == key2

    def test_make_key_different_params(self):
        key1 = RequestResultCache.make_key("GET", "/api/test", {"page": "1"})
        key2 = RequestResultCache.make_key("GET", "/api/test", {"page": "2"})
        assert key1 != key2

    def test_make_key_different_methods(self):
        key1 = RequestResultCache.make_key("GET", "/api/test")
        key2 = RequestResultCache.make_key("POST", "/api/test")
        assert key1 != key2

    def test_set_and_get(self):
        cache = RequestResultCache()
        key = RequestResultCache.make_key("GET", "/api/test")
        cache.set(key, {"result": "ok"})
        assert cache.get(key) == {"result": "ok"}

    def test_get_miss(self):
        cache = RequestResultCache()
        assert cache.get("nonexistent") is None

    def test_ttl_expiry(self):
        config = RequestCacheConfig(default_ttl_seconds=0.0)
        cache = RequestResultCache(config)
        key = RequestResultCache.make_key("GET", "/api/test")
        cache.set(key, {"result": "ok"})
        import time as _time

        _time.sleep(0.01)
        assert cache.get(key) is None

    def test_ttl_override(self):
        cache = RequestResultCache()
        key = RequestResultCache.make_key("GET", "/api/test")
        cache.set(key, {"result": "ok"}, ttl_seconds=60.0)
        assert cache.get(key) == {"result": "ok"}

    def test_lru_eviction(self):
        config = RequestCacheConfig(max_size=2)
        cache = RequestResultCache(config)
        k1 = RequestResultCache.make_key("GET", "/a")
        k2 = RequestResultCache.make_key("GET", "/b")
        k3 = RequestResultCache.make_key("GET", "/c")

        cache.set(k1, {"id": 1})
        cache.set(k2, {"id": 2})
        cache.set(k3, {"id": 3})  # Should evict k1

        assert cache.get(k1) is None
        assert cache.get(k2) == {"id": 2}
        assert cache.get(k3) == {"id": 3}

    def test_lru_access_moves_to_end(self):
        config = RequestCacheConfig(max_size=2)
        cache = RequestResultCache(config)
        k1 = RequestResultCache.make_key("GET", "/a")
        k2 = RequestResultCache.make_key("GET", "/b")

        cache.set(k1, {"id": 1})
        cache.set(k2, {"id": 2})
        cache.get(k1)  # Move k1 to end
        cache.set(RequestResultCache.make_key("GET", "/c"), {"id": 3})  # Evicts k2

        assert cache.get(k1) == {"id": 1}
        assert cache.get(k2) is None

    def test_update_existing_key(self):
        cache = RequestResultCache()
        key = RequestResultCache.make_key("GET", "/api/test")
        cache.set(key, {"v": 1})
        cache.set(key, {"v": 2})
        assert cache.get(key) == {"v": 2}
        assert cache.size == 1

    def test_invalidate_single(self):
        cache = RequestResultCache()
        key = RequestResultCache.make_key("GET", "/api/test")
        cache.set(key, {"result": "ok"})
        assert cache.invalidate(key) == 1
        assert cache.get(key) is None

    def test_invalidate_nonexistent(self):
        cache = RequestResultCache()
        assert cache.invalidate("missing") == 0

    def test_invalidate_all(self):
        cache = RequestResultCache()
        cache.set("k1", {"a": 1})
        cache.set("k2", {"b": 2})
        count = cache.invalidate()
        assert count == 2
        assert cache.size == 0

    def test_cleanup_expired(self):
        config = RequestCacheConfig(default_ttl_seconds=0.0)
        cache = RequestResultCache(config)
        cache.set("k1", {"a": 1})
        cache.set("k2", {"b": 2})
        import time as _time

        _time.sleep(0.01)
        removed = cache.cleanup_expired()
        assert removed == 2
        assert cache.size == 0

    def test_size(self):
        cache = RequestResultCache()
        assert cache.size == 0
        cache.set("k1", {"a": 1})
        assert cache.size == 1

    def test_get_stats(self):
        cache = RequestResultCache()
        key = RequestResultCache.make_key("GET", "/api/test")
        cache.set(key, {"result": "ok"})
        cache.get(key)
        cache.get("missing")
        stats = cache.get_stats()
        assert stats["total_requests"] == 2
        assert stats["cache_hits"] == 1
        assert stats["cache_misses"] == 1
        assert stats["hit_rate"] == pytest.approx(0.5)
        assert stats["current_size"] == 1
        assert stats["max_size"] == 512

    def test_reset_stats(self):
        cache = RequestResultCache()
        cache.set("k1", {"a": 1})
        cache.get("k1")
        cache.reset_stats()
        stats = cache.get_stats()
        assert stats["total_requests"] == 0

    def test_clear(self):
        cache = RequestResultCache()
        cache.set("k1", {"a": 1})
        cache.set("k2", {"b": 2})
        cache.clear()
        assert cache.size == 0
        stats = cache.get_stats()
        assert stats["total_requests"] == 0

    def test_disabled_cache(self):
        config = RequestCacheConfig(enabled=False)
        RequestResultCache(config)
        assert config.enabled is False


class TestRequestResultCacheConcurrency:
    """Thread-safety tests for RequestResultCache."""

    def test_concurrent_set_and_get(self):
        import threading

        cache = RequestResultCache()
        errors = []

        def writer():
            try:
                for i in range(100):
                    cache.set(f"key_{i}", {"val": i})
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for i in range(100):
                    cache.get(f"key_{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []

    def test_concurrent_invalidate(self):
        import threading

        cache = RequestResultCache()

        def writer():
            for i in range(50):
                cache.set(f"k{i}", {"v": i})

        def invalidator():
            for _ in range(50):
                cache.invalidate()

        threads = [threading.Thread(target=writer), threading.Thread(target=invalidator)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()


# ── DecompressionStats Tests ───────────────────────────────


class TestDecompressionStats:
    """Tests for DecompressionStats dataclass."""

    def test_default_values(self):
        stats = DecompressionStats()
        assert stats.total_responses == 0
        assert stats.decompressed_responses == 0
        assert stats.total_compressed_bytes == 0
        assert stats.total_decompressed_bytes == 0
        assert stats.decompression_errors == 0

    def test_decompression_rate_no_responses(self):
        stats = DecompressionStats()
        assert stats.decompression_rate == 0.0

    def test_decompression_rate_with_responses(self):
        stats = DecompressionStats()
        stats.total_responses = 10
        stats.decompressed_responses = 4
        assert stats.decompression_rate == pytest.approx(0.4)

    def test_avg_compression_ratio(self):
        stats = DecompressionStats()
        stats.total_compressed_bytes = 100
        stats.total_decompressed_bytes = 200
        assert stats.avg_compression_ratio == pytest.approx(2.0)

    def test_avg_compression_ratio_no_data(self):
        stats = DecompressionStats()
        assert stats.avg_compression_ratio == 0.0

    def test_to_dict(self):
        stats = DecompressionStats(total_responses=5, decompressed_responses=3)
        d = stats.to_dict()
        assert d["total_responses"] == 5
        assert d["decompressed_responses"] == 3
        assert "decompression_rate" in d
        assert "bytes_saved" in d

    def test_reset(self):
        stats = DecompressionStats(total_responses=10, decompressed_responses=5)
        stats.reset()
        assert stats.total_responses == 0
        assert stats.decompressed_responses == 0


# ── ResponseDecompressor Tests ─────────────────────────────


class TestResponseDecompressor:
    """Tests for ResponseDecompressor."""

    def test_no_encoding(self):
        decompressor = ResponseDecompressor()
        body = b'{"result": "ok"}'
        result = decompressor.decompress(body, content_encoding="")
        assert result == body

    def test_identity_encoding(self):
        decompressor = ResponseDecompressor()
        body = b'{"result": "ok"}'
        result = decompressor.decompress(body, content_encoding="identity")
        assert result == body

    def test_gzip_decompression(self):
        import gzip as gzip_mod

        decompressor = ResponseDecompressor()
        original = b'{"data": "test_value"}'
        compressed = gzip_mod.compress(original)
        result = decompressor.decompress(compressed, content_encoding="gzip")
        assert result == original

    def test_deflate_decompression(self):
        decompressor = ResponseDecompressor()
        original = b'{"data": "test_value"}'
        compressed = zlib.compress(original)
        result = decompressor.decompress(compressed, content_encoding="deflate")
        assert result == original

    def test_x_gzip_decompression(self):
        import gzip as gzip_mod

        decompressor = ResponseDecompressor()
        original = b'{"data": "test_value"}'
        compressed = gzip_mod.compress(original)
        result = decompressor.decompress(compressed, content_encoding="x-gzip")
        assert result == original

    def test_unsupported_encoding_returns_original(self):
        decompressor = ResponseDecompressor()
        body = b"some data"
        result = decompressor.decompress(body, content_encoding="br")
        # brotli likely not installed, should return original
        assert isinstance(result, bytes)

    def test_corrupt_gzip_returns_original(self):
        decompressor = ResponseDecompressor()
        body = b"not gzip data"
        result = decompressor.decompress(body, content_encoding="gzip")
        assert result == body  # Falls back to original on error

    def test_stats_tracking(self):
        import gzip as gzip_mod

        decompressor = ResponseDecompressor()
        original = b"x" * 1000
        compressed = gzip_mod.compress(original)
        decompressor.decompress(compressed, content_encoding="gzip")
        decompressor.decompress(b"plain", content_encoding="identity")

        stats = decompressor.get_stats()
        assert stats["total_responses"] == 2
        assert stats["decompressed_responses"] == 1
        assert stats["total_compressed_bytes"] > 0

    def test_stats_decompression_rate(self):
        decompressor = ResponseDecompressor()
        decompressor.decompress(b"a", content_encoding="gzip")  # Corrupt, error
        decompressor.decompress(b"b", content_encoding="identity")  # No decompression
        stats = decompressor.get_stats()
        assert stats["total_responses"] == 2

    def test_reset_stats(self):
        decompressor = ResponseDecompressor()
        decompressor.decompress(b"test", content_encoding="identity")
        decompressor.reset_stats()
        stats = decompressor.get_stats()
        assert stats["total_responses"] == 0

    def test_multiple_gzip_responses(self):
        import gzip as gzip_mod

        decompressor = ResponseDecompressor()
        for i in range(5):
            original = f'{{"id": {i}}}'.encode()
            compressed = gzip_mod.compress(original)
            result = decompressor.decompress(compressed, content_encoding="gzip")
            assert result == original

        stats = decompressor.get_stats()
        assert stats["total_responses"] == 5
        assert stats["decompressed_responses"] == 5


class TestResponseDecompressorConcurrency:
    """Thread-safety tests for ResponseDecompressor."""

    def test_concurrent_decompress(self):
        import gzip as gzip_mod
        import threading

        decompressor = ResponseDecompressor()
        original = b"x" * 500
        compressed = gzip_mod.compress(original)
        errors = []

        def decompress_batch():
            try:
                for _ in range(50):
                    result = decompressor.decompress(compressed, content_encoding="gzip")
                    assert result == original
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=decompress_batch) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        stats = decompressor.get_stats()
        assert stats["total_responses"] == 200
        assert stats["decompressed_responses"] == 200


# ── CommerceMCPBase Result Cache Integration ───────────────


class TestCommerceMCPBaseResultCache:
    """Tests for CommerceMCPBase result cache integration."""

    def test_has_result_cache(self):
        client = CommerceMCPBase()
        assert isinstance(client._result_cache, RequestResultCache)

    def test_custom_cache_config(self):
        config = RequestCacheConfig(max_size=64, default_ttl_seconds=60.0)
        client = CommerceMCPBase(cache_config=config)
        assert client._result_cache.config.max_size == 64
        assert client._result_cache.config.default_ttl_seconds == 60.0

    def test_get_result_cache_stats(self):
        client = CommerceMCPBase()
        stats = client.get_result_cache_stats()
        assert "total_requests" in stats
        assert "cache_hits" in stats
        assert "hit_rate" in stats
        assert "current_size" in stats

    def test_invalidate_result_cache(self):
        client = CommerceMCPBase()
        client._result_cache.set("k1", {"a": 1})
        count = client.invalidate_result_cache()
        assert count == 1

    def test_invalidate_result_cache_specific_key(self):
        client = CommerceMCPBase()
        client._result_cache.set("k1", {"a": 1})
        client._result_cache.set("k2", {"b": 2})
        count = client.invalidate_result_cache("k1")
        assert count == 1
        assert client._result_cache.size == 1

    @pytest.mark.asyncio
    async def test_get_request_cached(self):
        """Second identical GET request should be served from cache."""
        config = RequestCacheConfig(default_ttl_seconds=60.0)
        client = CommerceMCPBase(app_key="k", app_secret="s", cache_config=config)

        call_count = 0
        mock_response = MagicMock()

        def make_response(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_response.json.return_value = {"result": {"id": call_count}}
            mock_response.status_code = 200
            mock_response.headers = {}
            return mock_response

        mock_client = AsyncMock()
        mock_client.get.side_effect = make_response
        mock_client.is_closed = False

        with patch.object(client, "_ensure_client", return_value=mock_client):
            r1 = await client._request("GET", "/api/test", params={"page": "1"})
            r2 = await client._request("GET", "/api/test", params={"page": "1"})

        assert r1 == {"result": {"id": 1}}
        assert r2 == {"result": {"id": 1}}  # Cached
        assert call_count == 1  # Only one actual HTTP call

    @pytest.mark.asyncio
    async def test_different_params_not_cached(self):
        """Different params should result in different cache entries."""
        config = RequestCacheConfig(default_ttl_seconds=60.0)
        client = CommerceMCPBase(app_key="k", app_secret="s", cache_config=config)

        call_count = 0
        mock_response = MagicMock()

        def make_response(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_response.json.return_value = {"result": {"id": call_count}}
            mock_response.status_code = 200
            mock_response.headers = {}
            return mock_response

        mock_client = AsyncMock()
        mock_client.get.side_effect = make_response
        mock_client.is_closed = False

        with patch.object(client, "_ensure_client", return_value=mock_client):
            r1 = await client._request("GET", "/api/test", params={"page": "1"})
            r2 = await client._request("GET", "/api/test", params={"page": "2"})

        assert r1 != r2
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_cache_disabled(self):
        """When cache is disabled, all requests should go through."""
        config = RequestCacheConfig(enabled=False)
        client = CommerceMCPBase(app_key="k", app_secret="s", cache_config=config)

        call_count = 0
        mock_response = MagicMock()

        def make_response(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_response.json.return_value = {"result": {"id": call_count}}
            mock_response.status_code = 200
            mock_response.headers = {}
            return mock_response

        mock_client = AsyncMock()
        mock_client.get.side_effect = make_response
        mock_client.is_closed = False

        with patch.object(client, "_ensure_client", return_value=mock_client):
            await client._request("GET", "/api/test")
            await client._request("GET", "/api/test")

        assert call_count == 2

    @pytest.mark.asyncio
    async def test_use_cache_false_bypasses(self):
        """use_cache=False should skip caching for that request."""
        config = RequestCacheConfig(default_ttl_seconds=60.0)
        client = CommerceMCPBase(app_key="k", app_secret="s", cache_config=config)

        call_count = 0
        mock_response = MagicMock()

        def make_response(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_response.json.return_value = {"result": {"id": call_count}}
            mock_response.status_code = 200
            mock_response.headers = {}
            return mock_response

        mock_client = AsyncMock()
        mock_client.get.side_effect = make_response
        mock_client.is_closed = False

        with patch.object(client, "_ensure_client", return_value=mock_client):
            await client._request("GET", "/api/test", use_cache=False)
            await client._request("GET", "/api/test", use_cache=False)

        assert call_count == 2

    @pytest.mark.asyncio
    async def test_error_response_not_cached(self):
        """Error responses should not be cached."""
        config = RequestCacheConfig(default_ttl_seconds=60.0)
        client = CommerceMCPBase(app_key="k", app_secret="s", cache_config=config)

        call_count = 0
        mock_response = MagicMock()

        def make_response(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                mock_response.json.return_value = {"error_response": {"code": 40001, "msg": "bad"}}
            else:
                mock_response.json.return_value = {"result": "ok"}
            mock_response.status_code = 200
            mock_response.headers = {}
            return mock_response

        mock_client = AsyncMock()
        mock_client.get.side_effect = make_response
        mock_client.is_closed = False

        with patch.object(client, "_ensure_client", return_value=mock_client):
            with pytest.raises(CommerceAPIError):
                await client._request("GET", "/api/test")

            # Second request should not be served from cache
            result = await client._request("GET", "/api/test")
            assert result == {"result": "ok"}
            assert call_count == 2


# ── CommerceMCPBase Decompression Integration ──────────────


class TestCommerceMCPBaseDecompression:
    """Tests for CommerceMCPBase response decompression integration."""

    def test_has_decompressor(self):
        client = CommerceMCPBase()
        assert isinstance(client._decompressor, ResponseDecompressor)

    def test_get_decompression_stats(self):
        client = CommerceMCPBase()
        stats = client.get_decompression_stats()
        assert "total_responses" in stats
        assert "decompressed_responses" in stats
        assert "decompression_rate" in stats

    @pytest.mark.asyncio
    async def test_gzip_response_decompressed(self):
        """Compressed responses should be transparently decompressed."""
        import gzip as gzip_mod

        client = CommerceMCPBase(app_key="k", app_secret="s")
        original_data = {"result": {"products": list(range(100))}}
        compressed_body = gzip_mod.compress(json.dumps(original_data, ensure_ascii=False).encode())

        mock_response = MagicMock()
        mock_response.content = compressed_body
        mock_response.status_code = 200
        mock_response.headers = {"content-encoding": "gzip"}
        # json() should not be called when decompression succeeds
        mock_response.json.return_value = original_data

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.is_closed = False

        with patch.object(client, "_ensure_client", return_value=mock_client):
            result = await client._request("GET", "/api/test")

        assert result == original_data
        stats = client.get_decompression_stats()
        assert stats["decompressed_responses"] >= 1

    @pytest.mark.asyncio
    async def test_no_compression_header_uses_json(self):
        """Responses without Content-Encoding should use resp.json()."""
        client = CommerceMCPBase(app_key="k", app_secret="s")

        mock_response = MagicMock()
        mock_response.json.return_value = {"result": "ok"}
        mock_response.status_code = 200
        mock_response.headers = {}

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.is_closed = False

        with patch.object(client, "_ensure_client", return_value=mock_client):
            result = await client._request("GET", "/api/test")

        assert result == {"result": "ok"}


# ── CommerceMCPBase Cache + Compression Combined ───────────


class TestCommerceMCPBaseCacheAndCompression:
    """Tests for combined cache and compression features."""

    def test_all_new_features_initialized(self):
        """Client should have result cache, decompressor, and compressor."""
        client = CommerceMCPBase()
        assert isinstance(client._result_cache, RequestResultCache)
        assert isinstance(client._decompressor, ResponseDecompressor)
        assert isinstance(client._compressor, RequestCompressor)

    def test_custom_configs_combined(self):
        """All custom configs should be accepted together."""
        cache_cfg = RequestCacheConfig(max_size=32)
        comp_cfg = CompressionConfig(method=CompressionMethod.GZIP)
        rate_cfg = RateLimitConfig(default_requests_per_second=5.0)
        client = CommerceMCPBase(
            compression_config=comp_cfg,
            rate_limit_config=rate_cfg,
            cache_config=cache_cfg,
        )
        assert client._result_cache.config.max_size == 32
        assert client._compressor.config.method == CompressionMethod.GZIP
        assert client._configurable_limiter.config.default_requests_per_second == 5.0


# ── EncryptionMethod Tests ─────────────────────────────────


class TestEncryptionMethod:
    """Tests for EncryptionMethod enum values."""

    def test_none_value(self):
        assert EncryptionMethod.NONE == "none"

    def test_aes_256_cbc_value(self):
        assert EncryptionMethod.AES_256_CBC == "aes_256_cbc"

    def test_xor_cipher_value(self):
        assert EncryptionMethod.XOR_CIPHER == "xor_cipher"

    def test_all_methods(self):
        methods = list(EncryptionMethod)
        assert len(methods) == 3


# ── EncryptionConfig Tests ─────────────────────────────────


class TestEncryptionConfig:
    """Tests for EncryptionConfig dataclass."""

    def test_default_config(self):
        cfg = EncryptionConfig()
        assert cfg.method == EncryptionMethod.NONE
        assert cfg.encryption_key == ""
        assert cfg.include_encrypted_header is True
        assert cfg.header_name == "X-Encrypted"

    def test_to_dict_masks_key(self):
        cfg = EncryptionConfig(
            method=EncryptionMethod.AES_256_CBC,
            encryption_key="0123456789abcdef" * 4,
        )
        d = cfg.to_dict()
        assert d["method"] == "aes_256_cbc"
        assert "****" in d["encryption_key"]
        assert d["encryption_key"] != "0123456789abcdef" * 4

    def test_to_dict_empty_key(self):
        cfg = EncryptionConfig(encryption_key="")
        d = cfg.to_dict()
        assert d["encryption_key"] == ""

    def test_from_dict(self):
        data = {
            "method": "xor_cipher",
            "encryption_key": "abcdef",
            "include_encrypted_header": False,
            "header_name": "X-Custom",
        }
        cfg = EncryptionConfig.from_dict(data)
        assert cfg.method == EncryptionMethod.XOR_CIPHER
        assert cfg.encryption_key == "abcdef"
        assert cfg.include_encrypted_header is False
        assert cfg.header_name == "X-Custom"

    def test_from_dict_defaults(self):
        cfg = EncryptionConfig.from_dict({})
        assert cfg.method == EncryptionMethod.NONE
        assert cfg.encryption_key == ""


# ── RequestEncryptor Tests ─────────────────────────────────


class TestRequestEncryptor:
    """Tests for RequestEncryptor encrypt/decrypt."""

    def test_none_encryption_passthrough(self):
        enc = RequestEncryptor(EncryptionConfig(method=EncryptionMethod.NONE))
        body = b'{"test": true}'
        result, headers = enc.encrypt(body)
        assert result == body
        assert headers == {}

    def test_none_decryption_passthrough(self):
        enc = RequestEncryptor(EncryptionConfig(method=EncryptionMethod.NONE))
        data = b'{"test": true}'
        result = enc.decrypt(data)
        assert result == data

    def test_xor_encrypt_decrypt_roundtrip(self):
        key = "deadbeef"
        enc = RequestEncryptor(
            EncryptionConfig(
                method=EncryptionMethod.XOR_CIPHER,
                encryption_key=key,
            )
        )
        plaintext = b'{"order_id": "12345", "amount": 100}'
        encrypted, headers = enc.encrypt(plaintext)

        assert encrypted != plaintext
        assert headers["X-Encrypted"] == "xor_cipher"

        decrypted = enc.decrypt(encrypted)
        assert decrypted == plaintext

    def test_xor_empty_body(self):
        enc = RequestEncryptor(
            EncryptionConfig(
                method=EncryptionMethod.XOR_CIPHER,
                encryption_key="ff",
            )
        )
        encrypted, _ = enc.encrypt(b"")
        assert encrypted == b""
        assert enc.decrypt(encrypted) == b""

    def test_xor_custom_header_name(self):
        enc = RequestEncryptor(
            EncryptionConfig(
                method=EncryptionMethod.XOR_CIPHER,
                encryption_key="aa",
                header_name="X-Custom-Encrypt",
            )
        )
        _, headers = enc.encrypt(b"data")
        assert "X-Custom-Encrypt" in headers
        assert "X-Encrypted" not in headers

    def test_xor_no_header_when_disabled(self):
        enc = RequestEncryptor(
            EncryptionConfig(
                method=EncryptionMethod.XOR_CIPHER,
                encryption_key="aa",
                include_encrypted_header=False,
            )
        )
        _, headers = enc.encrypt(b"data")
        assert headers == {}

    def test_missing_key_raises(self):
        enc = RequestEncryptor(
            EncryptionConfig(
                method=EncryptionMethod.XOR_CIPHER,
                encryption_key="",
            )
        )
        with pytest.raises(ValueError, match="Encryption key is required"):
            enc.encrypt(b"data")

    def test_missing_key_decrypt_raises(self):
        enc = RequestEncryptor(
            EncryptionConfig(
                method=EncryptionMethod.XOR_CIPHER,
                encryption_key="",
            )
        )
        with pytest.raises(ValueError, match="Encryption key is required"):
            enc.decrypt(b"data")

    def test_xor_key_cannot_be_empty(self):
        enc = RequestEncryptor(
            EncryptionConfig(
                method=EncryptionMethod.XOR_CIPHER,
                encryption_key="",
            )
        )
        with pytest.raises(ValueError):
            enc._xor_encrypt(b"test", b"")

    def test_xor_large_body(self):
        key = "1234567890abcdef"
        enc = RequestEncryptor(
            EncryptionConfig(
                method=EncryptionMethod.XOR_CIPHER,
                encryption_key=key,
            )
        )
        body = os.urandom(10000)
        encrypted, _ = enc.encrypt(body)
        assert len(encrypted) == len(body)
        assert enc.decrypt(encrypted) == body

    def test_pkcs7_pad_unpad(self):
        data = b"hello"
        padded = RequestEncryptor._pkcs7_pad(data, 16)
        assert len(padded) % 16 == 0
        assert RequestEncryptor._pkcs7_unpad(padded) == data

    def test_pkcs7_pad_full_block(self):
        data = b"0123456789abcdef"  # exactly 16 bytes
        padded = RequestEncryptor._pkcs7_pad(data, 16)
        assert len(padded) == 32  # adds a full padding block
        assert RequestEncryptor._pkcs7_unpad(padded) == data

    def test_pkcs7_unpad_invalid(self):
        with pytest.raises(ValueError, match="Cannot unpad empty data"):
            RequestEncryptor._pkcs7_unpad(b"")

    def test_pkcs7_unpad_bad_length(self):
        with pytest.raises(ValueError, match="Invalid PKCS7 padding length"):
            RequestEncryptor._pkcs7_unpad(b"\x00" + b"\x11" * 15)

    def test_aes_wrong_key_length(self):
        # 8 bytes hex = 4 bytes key (not 32)
        enc = RequestEncryptor(
            EncryptionConfig(
                method=EncryptionMethod.AES_256_CBC,
                encryption_key="aabbccdd",
            )
        )
        with pytest.raises(ValueError, match="32-byte key"):
            enc.encrypt(b"data")

    def test_aes_decrypt_short_data(self):
        enc = RequestEncryptor(
            EncryptionConfig(
                method=EncryptionMethod.AES_256_CBC,
                encryption_key="00" * 32,
            )
        )
        with pytest.raises(ValueError, match="too short"):
            enc.decrypt(b"short")

    def test_aes_encrypt_decrypt_roundtrip(self):
        """Test AES-256-CBC encrypt/decrypt roundtrip (requires pyaes)."""
        pyaes = pytest.importorskip("pyaes")
        key = "0123456789abcdef" * 4  # 32 bytes
        enc = RequestEncryptor(
            EncryptionConfig(
                method=EncryptionMethod.AES_256_CBC,
                encryption_key=key,
            )
        )
        plaintext = b'{"product_id": "SKU-001", "price": 99.99}'
        encrypted, headers = enc.encrypt(plaintext)

        assert encrypted != plaintext
        assert len(encrypted) > len(plaintext)  # IV + padding
        assert headers["X-Encrypted"] == "aes_256_cbc"

        decrypted = enc.decrypt(encrypted)
        assert decrypted == plaintext

    def test_aes_different_iv_each_time(self):
        """Each AES encryption should produce different ciphertext (random IV)."""
        pyaes = pytest.importorskip("pyaes")
        key = "aabbccdd" * 8
        enc = RequestEncryptor(
            EncryptionConfig(
                method=EncryptionMethod.AES_256_CBC,
                encryption_key=key,
            )
        )
        body = b"same plaintext"
        r1, _ = enc.encrypt(body)
        r2, _ = enc.encrypt(body)
        # IVs are different, so ciphertexts differ
        assert r1 != r2
        # But both decrypt to the same plaintext
        assert enc.decrypt(r1) == body
        assert enc.decrypt(r2) == body

    def test_encryption_stats(self):
        enc = RequestEncryptor(
            EncryptionConfig(
                method=EncryptionMethod.XOR_CIPHER,
                encryption_key="ab",
            )
        )
        enc.encrypt(b"hello")
        enc.encrypt(b"world")
        enc.decrypt(b"data")

        stats = enc.get_stats()
        assert stats["total_encrypted"] == 2
        assert stats["total_decrypted"] == 1
        assert stats["total_bytes_encrypted"] == 10
        assert stats["total_bytes_decrypted"] == 4

    def test_encryption_stats_reset(self):
        enc = RequestEncryptor(
            EncryptionConfig(
                method=EncryptionMethod.XOR_CIPHER,
                encryption_key="ab",
            )
        )
        enc.encrypt(b"hello")
        enc.reset_stats()
        stats = enc.get_stats()
        assert stats["total_encrypted"] == 0

    def test_unsupported_method_raises(self):
        enc = RequestEncryptor(
            EncryptionConfig(
                method=EncryptionMethod.NONE,
                encryption_key="ab",
            )
        )
        # Force an invalid method for testing
        enc.config.method = "invalid"
        with pytest.raises(ValueError, match="Unsupported encryption method"):
            enc.encrypt(b"data")


# ── AuditEntry Tests ───────────────────────────────────────


class TestAuditEntry:
    """Tests for AuditEntry dataclass."""

    def test_defaults(self):
        entry = AuditEntry()
        assert entry.audit_id  # auto-generated UUID
        assert entry.timestamp  # auto-generated ISO 8601
        assert entry.method == ""
        assert entry.status_code == 0
        assert entry.encrypted is False

    def test_custom_values(self):
        entry = AuditEntry(
            method="GET",
            path="/api/order",
            platform="TAOBAO",
            status_code=200,
            latency_ms=45.2,
            encrypted=True,
        )
        d = entry.to_dict()
        assert d["method"] == "GET"
        assert d["path"] == "/api/order"
        assert d["platform"] == "TAOBAO"
        assert d["status_code"] == 200
        assert d["latency_ms"] == 45.2
        assert d["encrypted"] is True

    def test_to_dict_structure(self):
        entry = AuditEntry(
            method="POST",
            path="/api/test",
            error="timeout",
        )
        d = entry.to_dict()
        assert "audit_id" in d
        assert "request_id" in d
        assert "timestamp" in d
        assert d["error"] == "timeout"

    def test_metadata(self):
        entry = AuditEntry(metadata={"user_id": "U001", "ip": "10.0.0.1"})
        d = entry.to_dict()
        assert d["metadata"]["user_id"] == "U001"


# ── AuditLog Tests ─────────────────────────────────────────


class TestAuditLog:
    """Tests for AuditLog class."""

    def test_empty_log(self):
        log = AuditLog()
        assert log.entry_count == 0
        assert log.query() == []

    def test_log_single_entry(self):
        log = AuditLog()
        entry = AuditEntry(method="GET", path="/api/test", platform="TAOBAO")
        log.log(entry)
        assert log.entry_count == 1

    def test_query_all(self):
        log = AuditLog()
        for i in range(5):
            log.log(AuditEntry(method="GET", path=f"/api/item/{i}"))
        results = log.query(limit=10)
        assert len(results) == 5

    def test_query_by_platform(self):
        log = AuditLog()
        log.log(AuditEntry(method="GET", path="/a", platform="TAOBAO"))
        log.log(AuditEntry(method="GET", path="/b", platform="DOUDIAN"))
        log.log(AuditEntry(method="GET", path="/c", platform="TAOBAO"))

        results = log.query(platform="TAOBAO")
        assert len(results) == 2

    def test_query_by_method(self):
        log = AuditLog()
        log.log(AuditEntry(method="GET", path="/a"))
        log.log(AuditEntry(method="POST", path="/b"))
        log.log(AuditEntry(method="GET", path="/c"))

        results = log.query(method="POST")
        assert len(results) == 1

    def test_query_by_path(self):
        log = AuditLog()
        log.log(AuditEntry(method="GET", path="/api/order/1"))
        log.log(AuditEntry(method="GET", path="/api/product/2"))
        log.log(AuditEntry(method="GET", path="/api/order/3"))

        results = log.query(path="/api/order")
        assert len(results) == 2

    def test_query_by_status_code(self):
        log = AuditLog()
        log.log(AuditEntry(method="GET", path="/a", status_code=200))
        log.log(AuditEntry(method="GET", path="/b", status_code=500))
        log.log(AuditEntry(method="GET", path="/c", status_code=200))

        results = log.query(status_code=500)
        assert len(results) == 1

    def test_query_errors_only(self):
        log = AuditLog()
        log.log(AuditEntry(method="GET", path="/a"))
        log.log(AuditEntry(method="GET", path="/b", error="timeout"))
        log.log(AuditEntry(method="GET", path="/c"))

        results = log.query(errors_only=True)
        assert len(results) == 1

    def test_query_encrypted_only(self):
        log = AuditLog()
        log.log(AuditEntry(method="POST", path="/a", encrypted=True))
        log.log(AuditEntry(method="POST", path="/b", encrypted=False))
        log.log(AuditEntry(method="POST", path="/c", encrypted=True))

        results = log.query(encrypted_only=True)
        assert len(results) == 2

    def test_query_latency_filter(self):
        log = AuditLog()
        log.log(AuditEntry(method="GET", path="/a", latency_ms=10.0))
        log.log(AuditEntry(method="GET", path="/b", latency_ms=100.0))
        log.log(AuditEntry(method="GET", path="/c", latency_ms=500.0))

        results = log.query(min_latency_ms=50.0)
        assert len(results) == 2

        results = log.query(max_latency_ms=100.0)
        assert len(results) == 2

    def test_query_pagination(self):
        log = AuditLog()
        for i in range(20):
            log.log(AuditEntry(method="GET", path=f"/api/{i}"))

        page1 = log.query(limit=5, offset=0)
        page2 = log.query(limit=5, offset=5)
        assert len(page1) == 5
        assert len(page2) == 5
        # Results are most-recent-first, so different pages have different entries
        assert page1[0]["audit_id"] != page2[0]["audit_id"]

    def test_max_entries_eviction(self):
        log = AuditLog(max_entries=5)
        for i in range(10):
            log.log(AuditEntry(method="GET", path=f"/api/{i}"))
        assert log.entry_count == 5

    def test_combined_filters(self):
        log = AuditLog()
        log.log(AuditEntry(method="POST", path="/api/order", platform="TAOBAO", status_code=200))
        log.log(AuditEntry(method="POST", path="/api/order", platform="DOUDIAN", status_code=200))
        log.log(AuditEntry(method="GET", path="/api/order", platform="TAOBAO", status_code=200))

        results = log.query(platform="TAOBAO", method="POST")
        assert len(results) == 1

    def test_stats_empty(self):
        log = AuditLog()
        stats = log.get_stats()
        assert stats["total_entries"] == 0
        assert stats["error_count"] == 0

    def test_stats_with_entries(self):
        log = AuditLog()
        log.log(AuditEntry(method="GET", path="/a", platform="TAOBAO", encrypted=True))
        log.log(AuditEntry(method="POST", path="/b", platform="TAOBAO", error="fail"))
        log.log(AuditEntry(method="GET", path="/c", platform="DOUDIAN"))

        stats = log.get_stats()
        assert stats["total_entries"] == 3
        assert stats["error_count"] == 1
        assert stats["encrypted_count"] == 1
        assert stats["platforms"]["TAOBAO"] == 2
        assert stats["platforms"]["DOUDIAN"] == 1
        assert stats["methods"]["GET"] == 2
        assert stats["methods"]["POST"] == 1

    def test_export_json(self):
        log = AuditLog()
        log.log(AuditEntry(method="GET", path="/api/test"))
        json_str = log.export_json()
        data = json.loads(json_str)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["method"] == "GET"

    def test_export_json_with_limit(self):
        log = AuditLog()
        for i in range(10):
            log.log(AuditEntry(method="GET", path=f"/api/{i}"))
        json_str = log.export_json(limit=3)
        data = json.loads(json_str)
        assert len(data) == 3

    def test_export_csv(self):
        log = AuditLog()
        log.log(AuditEntry(method="GET", path="/api/test", platform="TAOBAO"))
        csv_str = log.export_csv()
        assert "method" in csv_str
        assert "GET" in csv_str

    def test_export_csv_empty(self):
        log = AuditLog()
        assert log.export_csv() == ""

    def test_export_to_file_json(self, tmp_path):
        log = AuditLog()
        log.log(AuditEntry(method="GET", path="/api/test"))
        file_path = str(tmp_path / "audit.json")
        result = log.export_to_file(file_path, format="json")
        assert result == file_path
        with open(file_path) as f:
            data = json.loads(f.read())
        assert len(data) == 1

    def test_export_to_file_csv(self, tmp_path):
        log = AuditLog()
        log.log(AuditEntry(method="GET", path="/api/test"))
        file_path = str(tmp_path / "audit.csv")
        result = log.export_to_file(file_path, format="csv")
        assert result == file_path
        with open(file_path) as f:
            content = f.read()
        assert "GET" in content

    def test_export_to_file_invalid_format(self, tmp_path):
        log = AuditLog()
        with pytest.raises(ValueError, match="Unsupported export format"):
            log.export_to_file(str(tmp_path / "out.xml"), format="xml")

    def test_clear(self):
        log = AuditLog()
        log.log(AuditEntry(method="GET", path="/a"))
        log.log(AuditEntry(method="GET", path="/b"))
        count = log.clear()
        assert count == 2
        assert log.entry_count == 0


# ── CommerceMCPBase Encryption Integration ──────────────────


class TestCommerceMCPBaseEncryption:
    """Integration tests for encryption in CommerceMCPBase."""

    def test_default_no_encryption(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        assert client._encryptor.config.method == EncryptionMethod.NONE

    def test_custom_encryption_config(self):
        cfg = EncryptionConfig(
            method=EncryptionMethod.XOR_CIPHER,
            encryption_key="aabb",
        )
        client = CommerceMCPBase(app_key="k", app_secret="s", encryption_config=cfg)
        assert client._encryptor.config.method == EncryptionMethod.XOR_CIPHER

    def test_get_encryption_stats(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        stats = client.get_encryption_stats()
        assert "method" in stats
        assert stats["method"] == "none"

    def test_get_encryption_config(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        cfg = client.get_encryption_config()
        assert cfg["method"] == "none"

    @pytest.mark.asyncio
    async def test_xor_encrypted_post_request(self):
        """POST request with XOR encryption should encrypt body and add header."""
        cfg = EncryptionConfig(
            method=EncryptionMethod.XOR_CIPHER,
            encryption_key="abcdef01",
        )
        client = CommerceMCPBase(app_key="k", app_secret="s", encryption_config=cfg)

        mock_response = MagicMock()
        mock_response.json.return_value = {"result": "ok"}
        mock_response.status_code = 200
        mock_response.headers = {}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.is_closed = False

        with patch.object(client, "_ensure_client", return_value=mock_client):
            result = await client._request("POST", "/api/test", data={"key": "value"})

        assert result == {"result": "ok"}
        # Verify post was called (encryption happened)
        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_encrypted_request_logged_in_audit(self):
        """Encrypted requests should be logged with encrypted=True."""
        cfg = EncryptionConfig(
            method=EncryptionMethod.XOR_CIPHER,
            encryption_key="ab",
        )
        client = CommerceMCPBase(app_key="k", app_secret="s", encryption_config=cfg)

        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": True}
        mock_response.status_code = 200
        mock_response.headers = {}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.is_closed = False

        with patch.object(client, "_ensure_client", return_value=mock_client):
            await client._request("POST", "/api/test", data={"a": 1})

        entries = client.query_audit(limit=10)
        assert len(entries) == 1
        assert entries[0]["encrypted"] is True


# ── CommerceMCPBase Audit Integration ───────────────────────


class TestCommerceMCPBaseAudit:
    """Integration tests for audit logging in CommerceMCPBase."""

    def test_default_audit_log(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        assert isinstance(client._audit_log, AuditLog)

    def test_custom_audit_max_entries(self):
        client = CommerceMCPBase(app_key="k", app_secret="s", audit_max_entries=1000)
        assert client._audit_log._max_entries == 1000

    @pytest.mark.asyncio
    async def test_request_logged_in_audit(self):
        """Successful requests should be logged."""
        client = CommerceMCPBase(app_key="k", app_secret="s")

        mock_response = MagicMock()
        mock_response.json.return_value = {"result": "ok"}
        mock_response.status_code = 200
        mock_response.headers = {}

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.is_closed = False

        with patch.object(client, "_ensure_client", return_value=mock_client):
            await client._request("GET", "/api/products")

        stats = client.get_audit_stats()
        assert stats["total_entries"] == 1

    @pytest.mark.asyncio
    async def test_failed_request_logged_with_error(self):
        """Failed requests should include error message."""
        client = CommerceMCPBase(app_key="k", app_secret="s")

        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")
        mock_client.is_closed = False

        with patch.object(client, "_ensure_client", return_value=mock_client):
            with pytest.raises(httpx.ConnectError):
                await client._request("GET", "/api/test")

        entries = client.query_audit(errors_only=True)
        assert len(entries) == 1
        assert "Connection refused" in entries[0]["error"]

    @pytest.mark.asyncio
    async def test_audit_records_platform(self):
        """Audit entries should include the platform name."""
        client = CommerceMCPBase(app_key="k", app_secret="s")

        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": 1}
        mock_response.status_code = 200
        mock_response.headers = {}

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.is_closed = False

        with patch.object(client, "_ensure_client", return_value=mock_client):
            await client._request("GET", "/api/test")

        entries = client.query_audit()
        assert entries[0]["platform"] == "COMMERCEMCPBASE"

    def test_query_audit_convenience(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        # Should not raise
        results = client.query_audit(limit=10)
        assert isinstance(results, list)

    def test_export_audit_json(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        json_str = client.export_audit_json()
        assert json.loads(json_str) == []

    def test_export_audit_csv(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        csv_str = client.export_audit_csv()
        assert csv_str == ""

    def test_get_audit_log(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        log = client.get_audit_log()
        assert isinstance(log, AuditLog)


# ── CommerceMCPBase Encryption + Audit Combined ─────────────


class TestCommerceMCPBaseEncryptionAuditCombined:
    """Tests for combined encryption and audit features."""

    def test_all_new_features_initialized(self):
        """Client should have encryptor and audit log."""
        client = CommerceMCPBase()
        assert isinstance(client._encryptor, RequestEncryptor)
        assert isinstance(client._audit_log, AuditLog)

    def test_custom_configs_combined(self):
        """All custom configs should be accepted together."""
        enc_cfg = EncryptionConfig(
            method=EncryptionMethod.XOR_CIPHER,
            encryption_key="aabb",
        )
        client = CommerceMCPBase(
            app_key="k",
            app_secret="s",
            encryption_config=enc_cfg,
            audit_max_entries=5000,
        )
        assert client._encryptor.config.method == EncryptionMethod.XOR_CIPHER
        assert client._audit_log._max_entries == 5000

    @pytest.mark.asyncio
    async def test_encrypted_request_appears_in_audit_export(self):
        """Encrypted request should appear in JSON export."""
        cfg = EncryptionConfig(
            method=EncryptionMethod.XOR_CIPHER,
            encryption_key="abcd",
        )
        client = CommerceMCPBase(app_key="k", app_secret="s", encryption_config=cfg)

        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": 1}
        mock_response.status_code = 200
        mock_response.headers = {}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.is_closed = False

        with patch.object(client, "_ensure_client", return_value=mock_client):
            await client._request("POST", "/api/order", data={"item": "test"})

        json_str = client.export_audit_json()
        entries = json.loads(json_str)
        assert len(entries) == 1
        assert entries[0]["encrypted"] is True
        assert entries[0]["method"] == "POST"
