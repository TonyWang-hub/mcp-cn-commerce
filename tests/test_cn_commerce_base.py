"""Tests for the shared cn_commerce_base module.

Tests the base classes, error handling, and utility functions.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

# Add the shared directory to the path
_shared_dir = Path(__file__).resolve().parents[1] / "shared"
if str(_shared_dir) not in sys.path:
    sys.path.insert(0, str(_shared_dir))

from cn_commerce_base import (
    BatchRequestItem,
    BatchResultItem,
    BatchSummary,
    CommerceAPIError,
    CommerceMCPBase,
    ConfigValidationError,
    DataExporter,
    EndpointMetrics,
    ExportConfig,
    ExportFormat,
    MetricsCollector,
    RateLimiter,
    SignMethod,
    WebhookDeliveryError,
    WebhookDeliveryResult,
    WebhookEvent,
    WebhookEventType,
    WebhookManager,
    WebhookSignatureVerifier,
    WebhookSubscription,
    format_error_response,
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


# ── ExportFormat Tests ─────────────────────────────────────


class TestExportFormat:
    """Tests for ExportFormat enum."""

    def test_csv_value(self):
        assert ExportFormat.CSV == "csv"

    def test_json_value(self):
        assert ExportFormat.JSON == "json"

    def test_excel_value(self):
        assert ExportFormat.EXCEL == "excel"

    def test_is_string_enum(self):
        assert isinstance(ExportFormat.CSV, str)


# ── ExportConfig Tests ────────────────────────────────────


class TestExportConfig:
    """Tests for ExportConfig dataclass."""

    def test_default_values(self):
        config = ExportConfig()
        assert config.format == ExportFormat.CSV
        assert config.fields is None
        assert config.filename == "export"
        assert config.output_dir == "."
        assert config.page == 0
        assert config.page_size == 1000
        assert config.flatten_nested is True
        assert config.encoding == "utf-8"

    def test_custom_values(self):
        config = ExportConfig(
            format=ExportFormat.JSON,
            fields=["id", "name"],
            filename="orders",
            output_dir="/tmp",
            page=2,
            page_size=50,
            flatten_nested=False,
            encoding="gbk",
        )
        assert config.format == ExportFormat.JSON
        assert config.fields == ["id", "name"]
        assert config.filename == "orders"
        assert config.output_dir == "/tmp"
        assert config.page == 2
        assert config.page_size == 50
        assert config.flatten_nested is False
        assert config.encoding == "gbk"


# ── DataExporter._flatten_dict Tests ─────────────────────


class TestDataExporterFlattenDict:
    """Tests for DataExporter._flatten_dict."""

    def test_flat_dict_unchanged(self):
        d = {"id": 1, "name": "test"}
        result = DataExporter._flatten_dict(d)
        assert result == {"id": 1, "name": "test"}

    def test_nested_dict_flattened(self):
        d = {"id": 1, "address": {"city": "Beijing", "zip": "100000"}}
        result = DataExporter._flatten_dict(d)
        assert result == {"id": 1, "address.city": "Beijing", "address.zip": "100000"}

    def test_deeply_nested(self):
        d = {"a": {"b": {"c": "deep"}}}
        result = DataExporter._flatten_dict(d)
        assert result == {"a.b.c": "deep"}

    def test_list_values_json_stringified(self):
        d = {"id": 1, "tags": ["a", "b"]}
        result = DataExporter._flatten_dict(d)
        assert result["id"] == 1
        assert result["tags"] == '["a", "b"]'

    def test_empty_dict(self):
        result = DataExporter._flatten_dict({})
        assert result == {}

    def test_custom_separator(self):
        d = {"a": {"b": 1}}
        result = DataExporter._flatten_dict(d, sep="__")
        assert result == {"a__b": 1}


# ── DataExporter._select_fields Tests ─────────────────────


class TestDataExporterSelectFields:
    """Tests for DataExporter._select_fields."""

    def test_select_specific_fields(self):
        data = [{"id": 1, "name": "a", "extra": "x"}, {"id": 2, "name": "b", "extra": "y"}]
        result = DataExporter._select_fields(data, ["id", "name"])
        assert result == [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]

    def test_none_fields_returns_all(self):
        data = [{"id": 1, "name": "a"}]
        result = DataExporter._select_fields(data, None)
        assert result == [{"id": 1, "name": "a"}]

    def test_missing_field_returns_none(self):
        data = [{"id": 1}]
        result = DataExporter._select_fields(data, ["id", "name"])
        assert result == [{"id": 1, "name": None}]

    def test_empty_data(self):
        result = DataExporter._select_fields([], ["id"])
        assert result == []


# ── DataExporter._paginate_data Tests ─────────────────────


class TestDataExporterPaginateData:
    """Tests for DataExporter._paginate_data."""

    def test_page_zero_returns_all(self):
        data = [{"id": i} for i in range(10)]
        page_data, info = DataExporter._paginate_data(data, page=0, page_size=3)
        assert len(page_data) == 10
        assert info["total"] == 10
        assert info["page"] == 0

    def test_first_page(self):
        data = [{"id": i} for i in range(10)]
        page_data, info = DataExporter._paginate_data(data, page=1, page_size=3)
        assert len(page_data) == 3
        assert page_data[0]["id"] == 0
        assert info["page"] == 1
        assert info["total_pages"] == 4
        assert info["has_next"] is True
        assert info["has_prev"] is False

    def test_last_page(self):
        data = [{"id": i} for i in range(10)]
        page_data, info = DataExporter._paginate_data(data, page=4, page_size=3)
        assert len(page_data) == 1
        assert page_data[0]["id"] == 9
        assert info["has_next"] is False
        assert info["has_prev"] is True

    def test_empty_data(self):
        page_data, info = DataExporter._paginate_data([], page=1, page_size=10)
        assert page_data == []
        assert info["total"] == 0


# ── DataExporter.export Tests ─────────────────────────────


class TestDataExporterExport:
    """Tests for DataExporter.export (file-based export)."""

    def test_export_csv(self, tmp_path):
        data = [{"id": 1, "name": "Item A"}, {"id": 2, "name": "Item B"}]
        config = ExportConfig(format=ExportFormat.CSV, output_dir=str(tmp_path), filename="test")
        result = DataExporter.export(data, config)
        assert result["format"] == "csv"
        assert result["record_count"] == 2
        assert "id" in result["fields"]
        assert "name" in result["fields"]
        content = (tmp_path / "test.csv").read_text(encoding="utf-8")
        assert "id,name" in content
        assert "Item A" in content

    def test_export_json(self, tmp_path):
        data = [{"id": 1, "name": "Item A"}]
        config = ExportConfig(format=ExportFormat.JSON, output_dir=str(tmp_path), filename="test")
        result = DataExporter.export(data, config)
        assert result["format"] == "json"
        assert result["record_count"] == 1
        content = json.loads((tmp_path / "test.json").read_text(encoding="utf-8"))
        assert content[0]["id"] == 1

    def test_export_excel(self, tmp_path):
        data = [{"id": 1, "name": "Item A"}, {"id": 2, "name": "Item B"}]
        config = ExportConfig(format=ExportFormat.EXCEL, output_dir=str(tmp_path), filename="test")
        result = DataExporter.export(data, config)
        assert result["format"] == "excel"
        assert result["record_count"] == 2
        assert (tmp_path / "test.excel").exists()

    def test_export_with_custom_fields(self, tmp_path):
        data = [{"id": 1, "name": "A", "secret": "hidden"}]
        config = ExportConfig(
            format=ExportFormat.JSON,
            fields=["id", "name"],
            output_dir=str(tmp_path),
            filename="filtered",
        )
        result = DataExporter.export(data, config)
        content = json.loads((tmp_path / "filtered.json").read_text(encoding="utf-8"))
        assert "secret" not in content[0]
        assert content[0]["id"] == 1

    def test_export_with_pagination(self, tmp_path):
        data = [{"id": i} for i in range(10)]
        config = ExportConfig(
            format=ExportFormat.JSON,
            output_dir=str(tmp_path),
            filename="paged",
            page=2,
            page_size=3,
        )
        result = DataExporter.export(data, config)
        assert result["record_count"] == 3
        assert result["pagination"]["page"] == 2
        assert result["pagination"]["total"] == 10

    def test_export_with_nested_flattening(self, tmp_path):
        data = [{"id": 1, "address": {"city": "Beijing"}}]
        config = ExportConfig(
            format=ExportFormat.JSON,
            output_dir=str(tmp_path),
            filename="flat",
            flatten_nested=True,
        )
        result = DataExporter.export(data, config)
        content = json.loads((tmp_path / "flat.json").read_text(encoding="utf-8"))
        assert "address.city" in content[0]

    def test_export_creates_output_dir(self, tmp_path):
        nested_dir = tmp_path / "subdir" / "exports"
        config = ExportConfig(
            format=ExportFormat.JSON,
            output_dir=str(nested_dir),
            filename="test",
        )
        DataExporter.export([{"id": 1}], config)
        assert (nested_dir / "test.json").exists()

    def test_export_empty_data(self, tmp_path):
        config = ExportConfig(
            format=ExportFormat.JSON,
            output_dir=str(tmp_path),
            filename="empty",
        )
        result = DataExporter.export([], config)
        assert result["record_count"] == 0

    def test_export_default_config(self, tmp_path):
        config = ExportConfig(output_dir=str(tmp_path))
        result = DataExporter.export([{"id": 1}], config)
        assert result["format"] == "csv"
        assert (tmp_path / "export.csv").exists()


# ── DataExporter.export_to_string Tests ───────────────────


class TestDataExporterExportToString:
    """Tests for DataExporter.export_to_string."""

    def test_json_string(self):
        data = [{"id": 1, "name": "test"}]
        result = DataExporter.export_to_string(data, format=ExportFormat.JSON)
        parsed = json.loads(result)
        assert parsed[0]["id"] == 1

    def test_csv_string(self):
        data = [{"id": 1, "name": "test"}]
        result = DataExporter.export_to_string(data, format=ExportFormat.CSV)
        assert "id,name" in result
        assert "1,test" in result

    def test_with_fields(self):
        data = [{"id": 1, "name": "test", "secret": "hidden"}]
        result = DataExporter.export_to_string(
            data, format=ExportFormat.JSON, fields=["id", "name"]
        )
        parsed = json.loads(result)
        assert "secret" not in parsed[0]

    def test_excel_raises(self):
        with pytest.raises(ValueError, match="does not support Excel"):
            DataExporter.export_to_string([{"id": 1}], format=ExportFormat.EXCEL)

    def test_empty_data_json(self):
        result = DataExporter.export_to_string([], format=ExportFormat.JSON)
        assert json.loads(result) == []

    def test_empty_data_csv(self):
        result = DataExporter.export_to_string([], format=ExportFormat.CSV)
        assert result == ""

    def test_flatten_nested(self):
        data = [{"id": 1, "meta": {"key": "val"}}]
        result = DataExporter.export_to_string(data, format=ExportFormat.JSON, flatten_nested=True)
        parsed = json.loads(result)
        assert "meta.key" in parsed[0]
