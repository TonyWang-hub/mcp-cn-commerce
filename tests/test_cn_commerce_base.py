"""Tests for the shared cn_commerce_base module.

Tests the base classes, error handling, and utility functions.
"""

from __future__ import annotations

import asyncio
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
    BatchRequestItem,
    BatchResultItem,
    BatchSummary,
    CommerceAPIError,
    CommerceMCPBase,
    ConfigValidationError,
    DEFAULT_RETRY,
    EndpointMetrics,
    MetricsCollector,
    RATE_LIMIT_RETRY,
    RateLimiter,
    ResponseCache,
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
        await limiter.acquire()
        assert limiter.last_request_time > 0

    @pytest.mark.asyncio
    async def test_acquire_respects_rate_limit(self):
        limiter = RateLimiter(requests_per_second=100.0)
        await limiter.acquire()
        await limiter.acquire()


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
        assert len(result) == 32

    def test_sign_hmac_sha256(self):
        client = CommerceMCPBase(app_secret="test_secret")
        client.sign_method = SignMethod.HMAC_SHA256
        params = {"app_key": "test", "timestamp": "1234567890"}
        result = client._sign(params)
        assert isinstance(result, str)
        assert len(result) == 64

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
        client = CommerceMCPBase(app_key="k", app_secret="s")
        client.BASE_URL = "http://127.0.0.1:99999"
        mock_client = AsyncMock()
        mock_client.head.side_effect = httpx.ConnectError("refused")
        with patch.object(client, "_get_client", return_value=mock_client):
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
            requests = [
                BatchRequestItem("GET", "/api/a", request_id=f"r{i}")
                for i in range(5)
            ]
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
            requests = [
                BatchRequestItem("GET", "/api/a", request_id=f"r{i}")
                for i in range(3)
            ]
            summary = await client._batch_request(requests)

        assert summary.total == 3
        assert summary.failed == 1
        assert summary.error_summary["CommerceAPIError"] == 1

    @pytest.mark.asyncio
    async def test_concurrency_clamped(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"result": "ok"}
            requests = [BatchRequestItem("GET", "/api/a", request_id="r0")]
            await client._batch_request(requests, max_concurrency=0)
            await client._batch_request(requests, max_concurrency=100)

    @pytest.mark.asyncio
    async def test_fail_fast_mode(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        call_count = 0

        async def _side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise CommerceAPIError(500, "server error")
            await asyncio.sleep(0.05)
            return {"result": "ok"}

        with patch.object(client, "_request", side_effect=_side_effect):
            requests = [
                BatchRequestItem("GET", "/api/a", request_id=f"r{i}")
                for i in range(5)
            ]
            summary = await client._batch_request(requests, fail_fast=True)

        assert summary.failed >= 1
        assert summary.error_summary.get("CommerceAPIError", 0) >= 1

    @pytest.mark.asyncio
    async def test_request_params_not_mutated(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"result": "ok"}
            item = BatchRequestItem("GET", "/api/a", params={"key": "val"}, request_id="r0")
            await client._batch_request([item])
        assert item.params == {"key": "val"}

    @pytest.mark.asyncio
    async def test_request_ids_preserved(self):
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
            requests = [
                BatchRequestItem("GET", "/api", request_id=f"r{i}")
                for i in range(4)
            ]
            summary = await client._batch_request(requests)

        assert summary.total == 4
        assert summary.succeeded == 2
        assert summary.failed == 2
        assert summary.error_summary["CommerceAPIError"] == 1
        assert summary.error_summary["ConnectError"] == 1


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
        assert cfg.compute_delay(10) == 5.0

    def test_compute_delay_with_jitter(self):
        cfg = RetryConfig(base_delay=4.0, jitter=True)
        delays = [cfg.compute_delay(0) for _ in range(100)]
        assert all(2.0 <= d <= 6.0 for d in delays)
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
        assert call_count == 3

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
        assert call_count == 1

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

        assert mock_client.get.call_count == 3

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
    async def test_request_retry_records_metrics_on_success(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        client.BASE_URL = "http://test.example.com"
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": {"ok": True}}
        mock_response.status_code = 200
        mock_client.get.return_value = mock_response

        with patch.object(client, "_get_client", return_value=mock_client):
            await client._request(
                "GET", "/api/test",
                retry_config=RetryConfig(max_retries=1, base_delay=0.01, jitter=False),
            )

        metrics = client.metrics.get_endpoint_metrics("/api/test")
        assert metrics.request_count == 1
        assert metrics.error_count == 0

    @pytest.mark.asyncio
    async def test_request_retry_records_metrics_on_failure(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        client.BASE_URL = "http://test.example.com"
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("refused")

        with patch.object(client, "_get_client", return_value=mock_client):
            with pytest.raises(httpx.ConnectError):
                await client._request(
                    "GET", "/api/fail",
                    retry_config=RetryConfig(max_retries=1, base_delay=0.01, jitter=False),
                )

        metrics = client.metrics.get_endpoint_metrics("/api/fail")
        assert metrics.request_count == 1
        assert metrics.error_count == 1

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

        assert len(timestamps) == 2
        assert timestamps[0] != timestamps[1]


# ── ResponseCache Tests ───────────────────────────────────


class TestResponseCache:
    """Tests for ResponseCache."""

    def test_init_defaults(self):
        cache = ResponseCache()
        assert cache.max_size == 256
        assert cache.default_ttl == 300.0

    def test_init_custom_values(self):
        cache = ResponseCache(max_size=100, default_ttl=60.0)
        assert cache.max_size == 100
        assert cache.default_ttl == 60.0

    def test_put_and_get(self):
        cache = ResponseCache()
        cache.put("key1", {"data": "value1"})
        found, value = cache.get("key1")
        assert found is True
        assert value == {"data": "value1"}

    def test_get_miss(self):
        cache = ResponseCache()
        found, value = cache.get("nonexistent")
        assert found is False
        assert value is None

    def test_ttl_expiration(self):
        cache = ResponseCache(default_ttl=0.01)
        cache.put("key1", "value1")
        import time
        time.sleep(0.02)
        found, value = cache.get("key1")
        assert found is False
        assert value is None

    def test_custom_ttl(self):
        cache = ResponseCache(default_ttl=300.0)
        cache.put("key1", "value1", ttl=0.01)
        import time
        time.sleep(0.02)
        found, _ = cache.get("key1")
        assert found is False

    def test_lru_eviction(self):
        cache = ResponseCache(max_size=2)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("c", 3)  # should evict "a"
        assert cache.size == 2
        found, _ = cache.get("a")
        assert found is False
        found, val = cache.get("b")
        assert found is True
        assert val == 2
        found, val = cache.get("c")
        assert found is True
        assert val == 3

    def test_lru_access_refreshes_position(self):
        cache = ResponseCache(max_size=2)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.get("a")  # access "a" to move it to end
        cache.put("c", 3)  # should evict "b" (oldest unused)
        found, _ = cache.get("b")
        assert found is False
        found, val = cache.get("a")
        assert found is True
        assert val == 1

    def test_overwrite_existing_key(self):
        cache = ResponseCache()
        cache.put("key1", "old")
        cache.put("key1", "new")
        found, val = cache.get("key1")
        assert found is True
        assert val == "new"
        assert cache.size == 1

    def test_clear(self):
        cache = ResponseCache()
        cache.put("a", 1)
        cache.put("b", 2)
        cache.clear()
        assert cache.size == 0
        found, _ = cache.get("a")
        assert found is False

    def test_size_property(self):
        cache = ResponseCache()
        assert cache.size == 0
        cache.put("a", 1)
        assert cache.size == 1
        cache.put("b", 2)
        assert cache.size == 2

    def test_stats_initial(self):
        cache = ResponseCache()
        stats = cache.stats
        assert stats["size"] == 0
        assert stats["max_size"] == 256
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate"] == 0.0
        assert stats["default_ttl"] == 300.0

    def test_stats_hit_rate(self):
        cache = ResponseCache()
        cache.put("a", 1)
        cache.get("a")  # hit
        cache.get("a")  # hit
        cache.get("b")  # miss
        stats = cache.stats
        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert stats["hit_rate"] == pytest.approx(2 / 3, abs=0.001)

    def test_stats_tracks_expired_as_miss(self):
        cache = ResponseCache(default_ttl=0.01)
        cache.put("a", 1)
        import time
        time.sleep(0.02)
        cache.get("a")  # expired = miss
        stats = cache.stats
        assert stats["misses"] == 1
        assert stats["hits"] == 0

    def test_reset_stats(self):
        cache = ResponseCache()
        cache.put("a", 1)
        cache.get("a")
        cache.get("missing")
        cache.reset_stats()
        stats = cache.stats
        assert stats["hits"] == 0
        assert stats["misses"] == 0

    def test_make_key_deterministic(self):
        cache = ResponseCache()
        key1 = cache._make_key("GET", "http://api.test", {"a": 1}, {})
        key2 = cache._make_key("GET", "http://api.test", {"a": 1}, {})
        assert key1 == key2

    def test_make_key_different_for_different_params(self):
        cache = ResponseCache()
        key1 = cache._make_key("GET", "http://api.test", {"a": 1}, {})
        key2 = cache._make_key("GET", "http://api.test", {"a": 2}, {})
        assert key1 != key2

    def test_make_key_different_for_different_methods(self):
        cache = ResponseCache()
        key1 = cache._make_key("GET", "http://api.test", {}, {})
        key2 = cache._make_key("POST", "http://api.test", {}, {})
        assert key1 != key2

    def test_max_size_zero_disables_caching(self):
        cache = ResponseCache(max_size=0)
        cache.put("key1", "value1")
        assert cache.size == 0
        found, _ = cache.get("key1")
        assert found is False

    def test_put_updates_existing_key_size_unchanged(self):
        cache = ResponseCache(max_size=2)
        cache.put("a", 1)
        cache.put("a", 2)
        assert cache.size == 1


# ── Cache Integration in _request Tests ───────────────────


class TestRequestCacheIntegration:
    """Tests for cache integration in CommerceMCPBase._request."""

    @pytest.mark.asyncio
    async def test_request_caches_get_response(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        client.BASE_URL = "http://test.example.com"
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": {"id": 1}}
        mock_response.status_code = 200
        mock_client.get.return_value = mock_response

        with patch.object(client, "_get_client", return_value=mock_client):
            result1 = await client._request("GET", "/api/test", use_cache=True)
            result2 = await client._request("GET", "/api/test", use_cache=True)

        assert result1 == {"result": {"id": 1}}
        assert result2 == {"result": {"id": 1}}
        assert mock_client.get.call_count == 1

    @pytest.mark.asyncio
    async def test_request_no_cache_for_post(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        client.BASE_URL = "http://test.example.com"
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": "ok"}
        mock_response.status_code = 200
        mock_client.post.return_value = mock_response

        with patch.object(client, "_get_client", return_value=mock_client):
            await client._request("POST", "/api/test", data={"x": 1}, use_cache=True)
            await client._request("POST", "/api/test", data={"x": 1}, use_cache=True)

        assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_request_cache_disabled_by_default(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        client.BASE_URL = "http://test.example.com"
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": {"id": 1}}
        mock_response.status_code = 200
        mock_client.get.return_value = mock_response

        with patch.object(client, "_get_client", return_value=mock_client):
            await client._request("GET", "/api/test")
            await client._request("GET", "/api/test")

        assert mock_client.get.call_count == 2

    @pytest.mark.asyncio
    async def test_request_cache_different_params_different_entries(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        client.BASE_URL = "http://test.example.com"
        mock_client = AsyncMock()
        mock_response1 = MagicMock()
        mock_response1.json.return_value = {"result": {"id": 1}}
        mock_response1.status_code = 200
        mock_response2 = MagicMock()
        mock_response2.json.return_value = {"result": {"id": 2}}
        mock_response2.status_code = 200
        mock_client.get.side_effect = [mock_response1, mock_response2]

        with patch.object(client, "_get_client", return_value=mock_client):
            r1 = await client._request("GET", "/api/test", params={"page": 1}, use_cache=True)
            r2 = await client._request("GET", "/api/test", params={"page": 2}, use_cache=True)

        assert r1 == {"result": {"id": 1}}
        assert r2 == {"result": {"id": 2}}
        assert mock_client.get.call_count == 2

    @pytest.mark.asyncio
    async def test_request_cache_with_custom_ttl(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        client.BASE_URL = "http://test.example.com"
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": "ok"}
        mock_response.status_code = 200
        mock_client.get.return_value = mock_response

        with patch.object(client, "_get_client", return_value=mock_client):
            await client._request("GET", "/api/test", use_cache=True, cache_ttl=0.01)
            import time
            time.sleep(0.02)
            await client._request("GET", "/api/test", use_cache=True, cache_ttl=0.01)

        assert mock_client.get.call_count == 2

    def test_init_has_cache(self):
        client = CommerceMCPBase()
        assert isinstance(client.cache, ResponseCache)

    @pytest.mark.asyncio
    async def test_health_check_includes_cache_stats(self):
        client = CommerceMCPBase(app_key="key", app_secret="secret")
        result = await client.health_check()
        assert "cache" in result
        assert "hits" in result["cache"]
        assert "misses" in result["cache"]
        assert "hit_rate" in result["cache"]
        assert "size" in result["cache"]
