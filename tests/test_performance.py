"""Performance tests for mcp-cn-commerce.

Tests performance characteristics of core components:
- HTTP client connection pooling
- Metrics collection throughput
- Rate limiter behavior under load
- Signature computation throughput
- Retry mechanism performance
"""

from __future__ import annotations

import asyncio
import statistics
import sys
import time
from pathlib import Path

import httpx
import pytest

# Add the shared directory to the path
_shared_dir = Path(__file__).resolve().parents[1] / "shared"
if str(_shared_dir) not in sys.path:
    sys.path.insert(0, str(_shared_dir))

from cn_commerce_base import (
    CommerceAPIError,
    CommerceMCPBase,
    EndpointMetrics,
    MetricsCollector,
    RateLimiter,
    RetryConfig,
)

# ── HTTP Client Connection Pool Tests ──────────────────────


class TestHTTPClientConnectionPool:
    """Test HTTP client connection pool performance."""

    def test_client_creation_is_lazy(self):
        """Client should not be created until first use."""
        client = CommerceMCPBase(app_key="k", app_secret="s")
        assert client._client is None

    def test_client_reuse(self):
        """Same client instance should be reused across calls."""
        client = CommerceMCPBase(app_key="k", app_secret="s")
        c1 = client._get_client()
        c2 = client._get_client()
        assert c1 is c2
        assert not c1.is_closed
        # Clean up
        import asyncio

        loop = asyncio.new_event_loop()
        loop.run_until_complete(client.close())
        loop.close()

    def test_client_pool_limits(self):
        """Client should have configured connection pool limits."""
        client = CommerceMCPBase(app_key="k", app_secret="s")
        c = client._get_client()
        # Verify the client was created
        assert c is not None
        assert not c.is_closed
        import asyncio

        loop = asyncio.new_event_loop()
        loop.run_until_complete(client.close())
        loop.close()

    @pytest.mark.asyncio
    async def test_client_close_and_recreate(self):
        """After close, a new client should be created on next use."""
        client = CommerceMCPBase(app_key="k", app_secret="s")
        c1 = client._get_client()
        await client.close()
        assert client._client is None
        c2 = client._get_client()
        assert c1 is not c2
        await client.close()

    @pytest.mark.asyncio
    async def test_client_close_idempotent(self):
        """Closing an already closed client should not raise."""
        client = CommerceMCPBase(app_key="k", app_secret="s")
        client._get_client()
        await client.close()
        await client.close()  # Should not raise

    def test_multiple_clients_independent(self):
        """Multiple CommerceMCPBase instances should have independent clients."""
        a = CommerceMCPBase(app_key="a", app_secret="s")
        b = CommerceMCPBase(app_key="b", app_secret="s")
        ca = a._get_client()
        cb = b._get_client()
        assert ca is not cb
        # Clean up
        import asyncio

        loop = asyncio.new_event_loop()
        loop.run_until_complete(a.close())
        loop.run_until_complete(b.close())
        loop.close()

    @pytest.mark.asyncio
    async def test_client_creation_performance(self):
        """Creating and closing clients should be fast."""
        start = time.perf_counter()
        for _ in range(100):
            client = CommerceMCPBase(app_key="k", app_secret="s")
            client._get_client()
            await client.close()
        elapsed = time.perf_counter() - start

        assert elapsed < 5.0, f"100 client create/close cycles took {elapsed:.3f}s"


# ── Metrics Collection Performance Tests ───────────────────


class TestMetricsCollectionPerformance:
    """Test metrics collection throughput and correctness."""

    def test_single_endpoint_throughput(self):
        """Recording 1000 requests to one endpoint should be fast."""
        collector = MetricsCollector()
        start = time.perf_counter()
        for i in range(1000):
            collector.record_request("/api/test", latency_ms=float(i), success=True)
        elapsed = time.perf_counter() - start

        ep = collector.get_endpoint_metrics("/api/test")
        assert ep.request_count == 1000
        assert elapsed < 1.0, f"1000 recordings took {elapsed:.3f}s, expected < 1.0s"

    def test_many_endpoints_throughput(self):
        """Recording to 100 different endpoints should be fast."""
        collector = MetricsCollector()
        start = time.perf_counter()
        for i in range(100):
            for j in range(10):
                collector.record_request(f"/api/ep{i}", latency_ms=float(j), success=True)
        elapsed = time.perf_counter() - start

        all_metrics = collector.get_all_metrics()
        assert len(all_metrics) == 100
        assert elapsed < 1.0, f"1000 recordings across 100 endpoints took {elapsed:.3f}s"

    def test_global_metrics_consistency(self):
        """Global metrics should be sum of all endpoint metrics."""
        collector = MetricsCollector()
        for i in range(50):
            collector.record_request(f"/api/{i}", latency_ms=10.0, success=True)
            collector.record_request(f"/api/{i}", latency_ms=20.0, success=False, error_code=i, error_msg="e")

        global_m = collector.get_global_metrics()
        assert global_m.request_count == 100
        assert global_m.error_count == 50
        assert global_m.total_latency_ms == pytest.approx(1500.0)

    def test_summary_generation_performance(self):
        """Summary generation should be fast even with many endpoints."""
        collector = MetricsCollector()
        for i in range(100):
            collector.record_request(f"/api/{i}", latency_ms=float(i), success=True)

        start = time.perf_counter()
        for _ in range(100):
            collector.get_summary()
        elapsed = time.perf_counter() - start

        assert elapsed < 1.0, f"100 summary generations took {elapsed:.3f}s"

    def test_reset_performance(self):
        """Reset should be fast."""
        collector = MetricsCollector()
        for i in range(1000):
            collector.record_request(f"/api/{i % 50}", latency_ms=float(i), success=True)

        start = time.perf_counter()
        collector.reset()
        elapsed = time.perf_counter() - start

        assert elapsed < 0.1, f"Reset took {elapsed:.3f}s"
        assert collector.get_global_metrics().request_count == 0

    def test_endpoint_metrics_latency_statistics(self):
        """Verify latency tracking produces correct statistics."""
        collector = MetricsCollector()
        latencies = [10.0, 20.0, 30.0, 40.0, 50.0]
        for lat in latencies:
            collector.record_request("/api/test", latency_ms=lat, success=True)

        ep = collector.get_endpoint_metrics("/api/test")
        assert ep.min_latency_ms == 10.0
        assert ep.max_latency_ms == 50.0
        assert ep.avg_latency_ms == pytest.approx(statistics.mean(latencies))
        assert ep.error_rate == 0.0


# ── Rate Limiter Performance Tests ─────────────────────────


class TestRateLimiterPerformance:
    """Test rate limiter behavior under load."""

    @pytest.mark.asyncio
    async def test_rate_limiter_first_call_immediate(self):
        """First request should be immediate."""
        limiter = RateLimiter(requests_per_second=100.0)
        start = time.perf_counter()
        await limiter.acquire()
        first_elapsed = time.perf_counter() - start
        assert first_elapsed < 0.01  # Should be nearly instant

    @pytest.mark.asyncio
    async def test_rate_limiter_interval_accuracy(self):
        """Rate limiter should enforce minimum interval between requests."""
        rps = 50.0
        limiter = RateLimiter(requests_per_second=rps)
        expected_interval = 1.0 / rps

        timestamps = []
        for _ in range(5):
            await limiter.acquire()
            timestamps.append(time.perf_counter())

        # Check intervals between consecutive requests
        intervals = [timestamps[i + 1] - timestamps[i] for i in range(len(timestamps) - 1)]
        avg_interval = statistics.mean(intervals)
        # Allow some tolerance for async scheduling
        assert (
            avg_interval >= expected_interval * 0.5
        ), f"Average interval {avg_interval:.4f}s < expected {expected_interval:.4f}s"

    @pytest.mark.asyncio
    async def test_rate_limiter_high_throughput(self):
        """Rate limiter should handle high request rates without drift."""
        rps = 200.0
        limiter = RateLimiter(requests_per_second=rps)
        count = 20

        start = time.perf_counter()
        for _ in range(count):
            await limiter.acquire()
        elapsed = time.perf_counter() - start

        expected_min = (count - 1) / rps  # Minimum expected time
        assert elapsed >= expected_min * 0.8, f"Elapsed {elapsed:.3f}s < expected minimum {expected_min:.3f}s"

    def test_rate_limiter_min_interval_calculation(self):
        """Verify min_interval calculation for various rates."""
        test_cases = [
            (1.0, 1.0),
            (10.0, 0.1),
            (100.0, 0.01),
            (0.5, 2.0),
        ]
        for rps, expected_interval in test_cases:
            limiter = RateLimiter(requests_per_second=rps)
            assert limiter.min_interval == pytest.approx(expected_interval)

    @pytest.mark.asyncio
    async def test_concurrent_rate_limiter(self):
        """Concurrent access to rate limiter should be safe."""
        limiter = RateLimiter(requests_per_second=1000.0)

        async def acquire_n(n: int):
            for _ in range(n):
                await limiter.acquire()

        tasks = [acquire_n(10) for _ in range(10)]
        # Should not raise or deadlock
        await asyncio.gather(*tasks)


# ── Signature Computation Performance Tests ────────────────


class TestSignaturePerformance:
    """Test signature computation performance."""

    def test_sign_performance_md5(self):
        """MD5 signing should be fast."""
        client = CommerceMCPBase(app_secret="test_secret_key_12345")
        client.sign_method = "md5"
        params = {
            "app_key": "test_key",
            "timestamp": "1234567890",
            "access_token": "test_token_value",
            "method": "api.test.method",
        }

        start = time.perf_counter()
        for _ in range(10000):
            client._sign(params)
        elapsed = time.perf_counter() - start

        assert elapsed < 2.0, f"10000 MD5 signs took {elapsed:.3f}s"
        ops_per_sec = 10000 / elapsed
        assert ops_per_sec > 5000, f"MD5 sign rate {ops_per_sec:.0f} ops/s < 5000"

    def test_sign_performance_hmac_sha256(self):
        """HMAC-SHA256 signing should be fast."""
        client = CommerceMCPBase(app_secret="test_secret_key_12345")
        client.sign_method = "hmac_sha256"
        params = {
            "app_key": "test_key",
            "timestamp": "1234567890",
            "access_token": "test_token_value",
            "method": "api.test.method",
        }

        start = time.perf_counter()
        for _ in range(10000):
            client._sign(params)
        elapsed = time.perf_counter() - start

        assert elapsed < 5.0, f"10000 HMAC-SHA256 signs took {elapsed:.3f}s"
        ops_per_sec = 10000 / elapsed
        assert ops_per_sec > 2000, f"HMAC-SHA256 sign rate {ops_per_sec:.0f} ops/s < 2000"

    def test_sign_with_many_params(self):
        """Signing with many parameters should still be fast."""
        client = CommerceMCPBase(app_secret="test_secret")
        client.sign_method = "md5"
        params = {f"param_{i}": f"value_{i}" for i in range(50)}
        params["app_key"] = "test_key"
        params["timestamp"] = "1234567890"

        start = time.perf_counter()
        for _ in range(5000):
            client._sign(params)
        elapsed = time.perf_counter() - start

        assert elapsed < 2.0, f"5000 signs with 50 params took {elapsed:.3f}s"

    def test_sign_result_consistency(self):
        """Same params should always produce same signature."""
        client = CommerceMCPBase(app_secret="test_secret")
        client.sign_method = "md5"
        params = {"app_key": "test", "timestamp": "1234567890"}

        results = [client._sign(params) for _ in range(100)]
        assert len(set(results)) == 1, "Signature should be deterministic"

    def test_sign_different_secrets_produce_different_results(self):
        """Different secrets should produce different signatures."""
        params = {"app_key": "test", "timestamp": "1234567890"}

        client1 = CommerceMCPBase(app_secret="secret1")
        client1.sign_method = "md5"
        client2 = CommerceMCPBase(app_secret="secret2")
        client2.sign_method = "md5"

        assert client1._sign(params) != client2._sign(params)


# ── Concurrent Operations Performance Tests ────────────────


class TestConcurrentPerformance:
    """Test concurrent operations performance."""

    @pytest.mark.asyncio
    async def test_concurrent_metric_recording(self):
        """Multiple concurrent tasks recording metrics should not corrupt data."""
        collector = MetricsCollector()

        async def record_requests(prefix: str, count: int):
            for i in range(count):
                collector.record_request(f"/api/{prefix}", latency_ms=float(i), success=True)

        tasks = [record_requests(f"ep{i}", 100) for i in range(10)]
        await asyncio.gather(*tasks)

        global_m = collector.get_global_metrics()
        assert global_m.request_count == 1000

    @pytest.mark.asyncio
    async def test_concurrent_metric_recording_mixed_success(self):
        """Concurrent recording with mixed success/failure should be consistent."""
        collector = MetricsCollector()

        async def record_requests(prefix: str, count: int):
            for i in range(count):
                success = i % 3 != 0
                collector.record_request(
                    f"/api/{prefix}",
                    latency_ms=float(i),
                    success=success,
                    error_code=500 if not success else 0,
                    error_msg="err" if not success else "",
                )

        tasks = [record_requests(f"ep{i}", 50) for i in range(10)]
        await asyncio.gather(*tasks)

        global_m = collector.get_global_metrics()
        assert global_m.request_count == 500
        # Every 3rd request fails: 50/3 ≈ 17 per endpoint, 10 endpoints ≈ 170
        expected_failures = sum(1 for i in range(50) if i % 3 == 0) * 10
        assert global_m.error_count == expected_failures

    @pytest.mark.asyncio
    async def test_concurrent_health_checks(self):
        """Multiple concurrent health checks should work correctly."""
        clients = [CommerceMCPBase(app_key=f"k{i}", app_secret=f"s{i}") for i in range(5)]

        async def check_health(client):
            return await client.health_check()

        results = await asyncio.gather(*[check_health(c) for c in clients])
        assert len(results) == 5
        for result in results:
            assert "configured" in result
            assert "metrics" in result

        # Clean up
        for c in clients:
            await c.close()


# ── Metrics Collector High Volume Benchmark ────────────────


class TestMetricsBenchmark:
    """Benchmark tests for MetricsCollector under high volume."""

    def test_high_volume_recording(self):
        """MetricsCollector should handle 50000 recordings efficiently."""
        collector = MetricsCollector()

        start = time.perf_counter()
        for i in range(50000):
            collector.record_request(
                f"/api/endpoint{i % 100}",
                latency_ms=float(i % 1000),
                success=i % 10 != 0,
                error_code=500 if i % 10 == 0 else 0,
                error_msg="error" if i % 10 == 0 else "",
            )
        elapsed = time.perf_counter() - start

        ops_per_sec = 50000 / elapsed
        assert ops_per_sec > 10000, f"Metrics recording rate {ops_per_sec:.0f} ops/s < 10000"
        assert collector.get_global_metrics().request_count == 50000

    def test_summary_with_many_endpoints(self):
        """Summary with 500 endpoints should still be fast."""
        collector = MetricsCollector()
        for i in range(500):
            collector.record_request(f"/api/ep{i}", latency_ms=float(i), success=True)

        start = time.perf_counter()
        summary = collector.get_summary()
        elapsed = time.perf_counter() - start

        assert elapsed < 0.5, f"Summary of 500 endpoints took {elapsed:.3f}s"
        assert len(summary["endpoints"]) == 500

    def test_get_all_metrics_performance(self):
        """get_all_metrics should be fast with many endpoints."""
        collector = MetricsCollector()
        for i in range(200):
            collector.record_request(f"/api/ep{i}", latency_ms=float(i), success=True)

        start = time.perf_counter()
        for _ in range(100):
            all_m = collector.get_all_metrics()
        elapsed = time.perf_counter() - start

        assert elapsed < 1.0, f"100 get_all_metrics calls took {elapsed:.3f}s"
        assert len(all_m) == 200


# ── EndpointMetrics Dataclass Performance ──────────────────


class TestEndpointMetricsPerformance:
    """Test EndpointMetrics dataclass performance."""

    def test_endpoint_metrics_creation_speed(self):
        """Creating EndpointMetrics instances should be fast."""
        start = time.perf_counter()
        metrics = [EndpointMetrics() for _ in range(10000)]
        elapsed = time.perf_counter() - start

        assert elapsed < 1.0, f"10000 EndpointMetrics creations took {elapsed:.3f}s"
        assert len(metrics) == 10000

    def test_endpoint_metrics_update_speed(self):
        """Updating EndpointMetrics should be fast."""
        m = EndpointMetrics()
        start = time.perf_counter()
        for i in range(10000):
            m.request_count += 1
            m.total_latency_ms += float(i)
            m.min_latency_ms = min(m.min_latency_ms, float(i))
            m.max_latency_ms = max(m.max_latency_ms, float(i))
        elapsed = time.perf_counter() - start

        assert elapsed < 1.0, f"10000 updates took {elapsed:.3f}s"
        assert m.request_count == 10000

    def test_endpoint_metrics_property_access(self):
        """Property access should be fast."""
        m = EndpointMetrics(request_count=1000, error_count=100, total_latency_ms=50000.0)

        start = time.perf_counter()
        for _ in range(10000):
            _ = m.avg_latency_ms
            _ = m.error_rate
        elapsed = time.perf_counter() - start

        assert elapsed < 1.0, f"10000 property accesses took {elapsed:.3f}s"


# ── RetryConfig Performance Tests ─────────────────────────


class TestRetryConfigPerformance:
    """Test RetryConfig computation performance."""

    def test_compute_delay_performance(self):
        """Delay computation should be fast."""
        config = RetryConfig(max_retries=10, base_delay=1.0, max_delay=60.0, jitter=False)

        start = time.perf_counter()
        for _ in range(10000):
            for attempt in range(10):
                config.compute_delay(attempt)
        elapsed = time.perf_counter() - start

        assert elapsed < 1.0, f"100000 delay computations took {elapsed:.3f}s"

    def test_compute_delay_exponential_backoff(self):
        """Delay should follow exponential backoff pattern."""
        config = RetryConfig(max_retries=5, base_delay=1.0, max_delay=60.0, jitter=False)

        delays = [config.compute_delay(i) for i in range(6)]
        # Without jitter: 1, 2, 4, 8, 16, 32
        assert delays[0] == pytest.approx(1.0)
        assert delays[1] == pytest.approx(2.0)
        assert delays[2] == pytest.approx(4.0)
        assert delays[3] == pytest.approx(8.0)
        assert delays[4] == pytest.approx(16.0)
        assert delays[5] == pytest.approx(32.0)

    def test_compute_delay_respects_max(self):
        """Delay should not exceed max_delay."""
        config = RetryConfig(max_retries=10, base_delay=1.0, max_delay=10.0, jitter=False)

        for attempt in range(10):
            delay = config.compute_delay(attempt)
            assert delay <= 10.0, f"Delay {delay} > max_delay 10.0 at attempt {attempt}"

    def test_should_retry_exception_performance(self):
        """Exception checking should be fast."""
        config = RetryConfig()
        exceptions = [
            httpx.ConnectError("test"),
            httpx.ReadTimeout("test"),
            httpx.WriteTimeout("test"),
            ValueError("test"),
            CommerceAPIError(500, "test"),
        ]

        start = time.perf_counter()
        for _ in range(10000):
            for exc in exceptions:
                config.should_retry_exception(exc)
        elapsed = time.perf_counter() - start

        assert elapsed < 1.0, f"50000 exception checks took {elapsed:.3f}s"

    def test_should_retry_http_status_performance(self):
        """HTTP status checking should be fast."""
        config = RetryConfig()
        statuses = [200, 301, 400, 404, 429, 500, 502, 503, 504]

        start = time.perf_counter()
        for _ in range(10000):
            for status in statuses:
                config.should_retry_http_status(status)
        elapsed = time.perf_counter() - start

        assert elapsed < 1.0, f"90000 status checks took {elapsed:.3f}s"
