"""Benchmark tests for mcp-cn-commerce.

Tests performance of cache, batch operations, priority scheduling,
and concurrent request handling.  All benchmarks emit structured
results via the ``benchmark_results`` fixture so that CI pipelines
can capture and compare numbers across runs.

Run with:
    PYTHONPATH=servers/oceanengine/src:servers/doudian/src:servers/jd/src:\
    servers/taobao/src:servers/pinduoduo/src:servers/kuaishou/src:\
    servers/xiaohongshu/src:servers/weixin-store/src \
    pytest tests/test_benchmark.py -v --tb=short
"""

from __future__ import annotations

import asyncio
import statistics
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

# Add the shared directory to the path
_shared_dir = Path(__file__).resolve().parents[1] / "shared"
if str(_shared_dir) not in sys.path:
    sys.path.insert(0, str(_shared_dir))

from cn_commerce_base import (
    BatchRequestItem,
    BatchResultItem,
    BatchSummary,
    CacheWarmer,
    CommerceMCPBase,
    ConfigurableRateLimiter,
    EndpointMetrics,
    HealthCheckCache,
    HealthCheckResult,
    MetricsCollector,
    PrioritizedRequest,
    PriorityQueue,
    PriorityScheduler,
    PriorityStats,
    RateLimitConfig,
    RequestPriority,
)

# ── Benchmark Results Collection ────────────────────────────

# Module-level dict to store benchmark results across all test classes.
# Printed at the end by the TestBenchmarkSummary class.
_BENCHMARK_RESULTS: list[dict[str, Any]] = []


def _record(name: str, value: float, unit: str = "ops/s", detail: str = "") -> None:
    """Record a benchmark result for summary output."""
    _BENCHMARK_RESULTS.append({
        "name": name,
        "value": value,
        "unit": unit,
        "detail": detail,
    })


# ── HealthCheckCache Benchmarks ─────────────────────────────


class TestHealthCheckCacheBenchmark:
    """Benchmark HealthCheckCache read/write/invalidation throughput."""

    def _make_result(self, status: str = "healthy") -> HealthCheckResult:
        return HealthCheckResult(
            status=status,
            configured=True,
            has_token=True,
            api_reachable=True,
            latency_ms=42.0,
        )

    def test_cache_write_throughput(self):
        """Writing 10 000 entries should complete in under 2 seconds."""
        cache = HealthCheckCache(ttl_seconds=60.0)
        result = self._make_result()

        start = time.perf_counter()
        for i in range(10_000):
            cache.set(f"platform_{i % 100}", result)
        elapsed = time.perf_counter() - start

        ops = 10_000 / elapsed
        _record("health_cache_write", ops, detail=f"10k writes in {elapsed:.3f}s")
        assert elapsed < 2.0, f"10 000 cache writes took {elapsed:.3f}s"

    def test_cache_read_hit_throughput(self):
        """Reading 10 000 hits should complete in under 2 seconds."""
        cache = HealthCheckCache(ttl_seconds=60.0)
        result = self._make_result()
        for i in range(100):
            cache.set(f"platform_{i}", result)

        start = time.perf_counter()
        for i in range(10_000):
            cache.get(f"platform_{i % 100}")
        elapsed = time.perf_counter() - start

        ops = 10_000 / elapsed
        _record("health_cache_read_hit", ops, detail=f"10k reads in {elapsed:.3f}s")
        assert elapsed < 2.0, f"10 000 cache reads took {elapsed:.3f}s"

    def test_cache_read_miss_throughput(self):
        """Reading 10 000 misses should be very fast (no allocation)."""
        cache = HealthCheckCache(ttl_seconds=60.0)

        start = time.perf_counter()
        for i in range(10_000):
            cache.get(f"nonexistent_{i}")
        elapsed = time.perf_counter() - start

        ops = 10_000 / elapsed
        _record("health_cache_read_miss", ops, detail=f"10k misses in {elapsed:.3f}s")
        assert elapsed < 1.0, f"10 000 cache misses took {elapsed:.3f}s"

    def test_cache_ttl_expiry_accuracy(self):
        """Entries should expire within TTL + 5 ms tolerance."""
        cache = HealthCheckCache(ttl_seconds=0.05)  # 50 ms TTL
        result = self._make_result()
        cache.set("key", result)

        # Should be available immediately
        assert cache.get("key") is not None

        time.sleep(0.06)

        # Should be expired
        assert cache.get("key") is None

    def test_cache_invalidate_single(self):
        """Invalidating one key should leave others intact."""
        cache = HealthCheckCache(ttl_seconds=60.0)
        result = self._make_result()
        for i in range(100):
            cache.set(f"k{i}", result)

        start = time.perf_counter()
        for i in range(0, 100, 2):
            cache.invalidate(f"k{i}")
        elapsed = time.perf_counter() - start

        # Odd keys should still be present
        for i in range(1, 100, 2):
            assert cache.get(f"k{i}") is not None
        # Even keys should be gone
        for i in range(0, 100, 2):
            assert cache.get(f"k{i}") is None

        _record("health_cache_invalidate_single", 50 / elapsed, detail="50 invalidations")

    def test_cache_invalidate_all(self):
        """Bulk invalidation should be fast."""
        cache = HealthCheckCache(ttl_seconds=60.0)
        result = self._make_result()
        for i in range(5000):
            cache.set(f"k{i}", result)

        start = time.perf_counter()
        cache.invalidate()
        elapsed = time.perf_counter() - start

        _record("health_cache_invalidate_all", 5000 / elapsed, detail=f"5k entries in {elapsed:.4f}s")
        assert elapsed < 0.5, f"Bulk invalidation took {elapsed:.3f}s"

    def test_cache_stats_performance(self):
        """get_stats should be fast even with many entries."""
        cache = HealthCheckCache(ttl_seconds=60.0)
        result = self._make_result()
        for i in range(5000):
            cache.set(f"k{i}", result)

        start = time.perf_counter()
        for _ in range(1000):
            cache.get_stats()
        elapsed = time.perf_counter() - start

        ops = 1000 / elapsed
        _record("health_cache_stats", ops, detail=f"1k calls in {elapsed:.3f}s")
        assert elapsed < 2.0, f"1000 get_stats calls took {elapsed:.3f}s"

    def test_cache_concurrent_read_write(self):
        """Concurrent reads and writes from multiple threads should not crash."""
        cache = HealthCheckCache(ttl_seconds=60.0)
        result = self._make_result()
        errors: list[Exception] = []

        def writer(prefix: str, count: int) -> None:
            try:
                for i in range(count):
                    cache.set(f"{prefix}_{i}", result)
            except Exception as e:
                errors.append(e)

        def reader(prefix: str, count: int) -> None:
            try:
                for i in range(count):
                    cache.get(f"{prefix}_{i % 100}")
            except Exception as e:
                errors.append(e)

        threads = []
        for t in range(4):
            threads.append(threading.Thread(target=writer, args=(f"w{t}", 500)))
            threads.append(threading.Thread(target=reader, args=(f"w{t}", 500)))

        start = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        elapsed = time.perf_counter() - start

        assert not errors, f"Concurrent errors: {errors}"
        _record("health_cache_concurrent_rw", 4000 / elapsed, detail=f"4k ops in {elapsed:.3f}s")


# ── CacheWarmer Benchmarks ─────────────────────────────────


class TestCacheWarmerBenchmark:
    """Benchmark CacheWarmer registration, warmup, and cache access."""

    @pytest.mark.asyncio
    async def test_warmup_all_throughput(self):
        """Warming 50 tasks should complete in under 5 seconds."""
        warmer = CacheWarmer()

        async def fake_fetch() -> dict[str, str]:
            return {"data": "test"}

        for i in range(50):
            warmer.register(
                platform=f"PLATFORM_{i % 8}",
                cache_key=f"key_{i}",
                fetch_fn=fake_fetch,
                priority=i,
                ttl_seconds=300.0,
            )

        start = time.perf_counter()
        results = await warmer.warmup_all()
        elapsed = time.perf_counter() - start

        assert len(results) == 50
        assert all(r.success for r in results)
        ops = 50 / elapsed
        _record("cache_warmer_warmup_all", ops, detail=f"50 tasks in {elapsed:.3f}s")
        assert elapsed < 5.0, f"Warming 50 tasks took {elapsed:.3f}s"

    @pytest.mark.asyncio
    async def test_warmup_platform_selective(self):
        """Warming a single platform should be fast."""
        warmer = CacheWarmer()

        async def fake_fetch() -> dict[str, str]:
            return {"data": "test"}

        for i in range(30):
            warmer.register(
                platform=f"P{i % 5}",
                cache_key=f"k{i}",
                fetch_fn=fake_fetch,
            )

        start = time.perf_counter()
        results = await warmer.warmup_platform("P0")
        elapsed = time.perf_counter() - start

        assert len(results) == 6  # 30 / 5 = 6 tasks per platform
        _record("cache_warmer_warmup_platform", len(results) / elapsed, detail=f"6 tasks in {elapsed:.3f}s")

    def test_get_cached_hit_throughput(self):
        """Reading from warmup cache should be very fast."""
        warmer = CacheWarmer()
        for i in range(100):
            warmer.set_cached(f"k{i}", {"data": i}, ttl_seconds=60.0)

        start = time.perf_counter()
        for i in range(10_000):
            warmer.get_cached(f"k{i % 100}")
        elapsed = time.perf_counter() - start

        ops = 10_000 / elapsed
        _record("cache_warmer_get_cached", ops, detail=f"10k reads in {elapsed:.3f}s")
        assert elapsed < 2.0, f"10 000 cache reads took {elapsed:.3f}s"

    def test_register_unregister_throughput(self):
        """Registering and unregistering many tasks should be fast."""
        warmer = CacheWarmer()

        async def fake_fetch() -> dict[str, str]:
            return {"data": "test"}

        start = time.perf_counter()
        for i in range(1000):
            warmer.register(platform=f"P{i}", cache_key=f"k{i}", fetch_fn=fake_fetch)
        elapsed_register = time.perf_counter() - start

        start = time.perf_counter()
        for i in range(1000):
            warmer.unregister(platform=f"P{i}", cache_key=f"k{i}")
        elapsed_unregister = time.perf_counter() - start

        _record(
            "cache_warmer_register",
            1000 / elapsed_register,
            detail=f"1000 registrations in {elapsed_register:.3f}s",
        )
        _record(
            "cache_warmer_unregister",
            1000 / elapsed_unregister,
            detail=f"1000 unregistrations in {elapsed_unregister:.3f}s",
        )
        assert elapsed_register < 2.0
        assert elapsed_unregister < 2.0

    def test_invalidate_performance(self):
        """Cache invalidation should be fast."""
        warmer = CacheWarmer()
        for i in range(5000):
            warmer.set_cached(f"k{i}", {"data": i}, ttl_seconds=60.0)

        start = time.perf_counter()
        warmer.invalidate()
        elapsed = time.perf_counter() - start

        _record("cache_warmer_invalidate_all", 5000 / elapsed, detail=f"5k entries in {elapsed:.4f}s")
        assert elapsed < 0.5

    def test_get_stats_performance(self):
        """get_stats should be fast with many cached entries."""
        warmer = CacheWarmer()
        for i in range(1000):
            warmer.set_cached(f"k{i}", {"data": i}, ttl_seconds=60.0)

        start = time.perf_counter()
        for _ in range(1000):
            warmer.get_stats()
        elapsed = time.perf_counter() - start

        ops = 1000 / elapsed
        _record("cache_warmer_stats", ops, detail=f"1k calls in {elapsed:.3f}s")
        assert elapsed < 2.0


# ── PriorityQueue Benchmarks ───────────────────────────────


class TestPriorityQueueBenchmark:
    """Benchmark PriorityQueue enqueue/dequeue throughput."""

    def test_enqueue_throughput(self):
        """Enqueuing 10 000 items should be fast."""
        pq = PriorityQueue(max_size=50_000)
        req = PrioritizedRequest(
            priority=RequestPriority.NORMAL,
            method="GET",
            path="/api/test",
        )

        start = time.perf_counter()
        for _ in range(10_000):
            pq.enqueue(req)
        elapsed = time.perf_counter() - start

        ops = 10_000 / elapsed
        _record("pq_enqueue", ops, detail=f"10k enqueues in {elapsed:.3f}s")
        assert elapsed < 2.0, f"10 000 enqueues took {elapsed:.3f}s"
        assert pq.size == 10_000

    def test_dequeue_throughput(self):
        """Dequeuing 10 000 items should be fast."""
        pq = PriorityQueue(max_size=50_000)
        req = PrioritizedRequest(priority=RequestPriority.NORMAL, method="GET", path="/api/test")
        for _ in range(10_000):
            pq.enqueue(req)

        start = time.perf_counter()
        for _ in range(10_000):
            pq.dequeue()
        elapsed = time.perf_counter() - start

        ops = 10_000 / elapsed
        _record("pq_dequeue", ops, detail=f"10k dequeues in {elapsed:.3f}s")
        assert elapsed < 2.0, f"10 000 dequeues took {elapsed:.3f}s"
        assert pq.is_empty

    def test_priority_ordering_correctness(self):
        """Highest-priority items should come out first."""
        pq = PriorityQueue(max_size=1000)

        priorities = [
            RequestPriority.LOW,
            RequestPriority.HIGH,
            RequestPriority.NORMAL,
            RequestPriority.CRITICAL,
            RequestPriority.LOW,
            RequestPriority.HIGH,
        ]
        for p in priorities:
            pq.enqueue(PrioritizedRequest(priority=p, method="GET", path=f"/{p.value}"))

        results = []
        while not pq.is_empty:
            item = pq.dequeue()
            results.append(item.priority)

        # CRITICAL < HIGH < NORMAL < LOW
        assert results[0] == RequestPriority.CRITICAL
        assert results[1] == RequestPriority.HIGH
        assert results[-1] == RequestPriority.LOW

    def test_mixed_priority_throughput(self):
        """Enqueue/dequeue with mixed priorities should still be fast."""
        pq = PriorityQueue(max_size=50_000)
        all_priorities = list(RequestPriority)

        start = time.perf_counter()
        for i in range(10_000):
            p = all_priorities[i % len(all_priorities)]
            pq.enqueue(PrioritizedRequest(priority=p, method="GET", path=f"/api/{i}"))
        enqueue_elapsed = time.perf_counter() - start

        start = time.perf_counter()
        results = []
        while not pq.is_empty:
            results.append(pq.dequeue())
        dequeue_elapsed = time.perf_counter() - start

        assert len(results) == 10_000
        _record("pq_mixed_enqueue", 10_000 / enqueue_elapsed, detail="10k mixed enqueues")
        _record("pq_mixed_dequeue", 10_000 / dequeue_elapsed, detail="10k mixed dequeues")

    def test_queue_full_raises(self):
        """Enqueuing beyond max_size should raise RuntimeError."""
        pq = PriorityQueue(max_size=10)
        req = PrioritizedRequest(priority=RequestPriority.NORMAL, method="GET", path="/api/test")
        for _ in range(10):
            pq.enqueue(req)

        with pytest.raises(RuntimeError, match="Priority queue full"):
            pq.enqueue(req)

    def test_clear_performance(self):
        """Clearing a full queue should be fast."""
        pq = PriorityQueue(max_size=50_000)
        req = PrioritizedRequest(priority=RequestPriority.NORMAL, method="GET", path="/api/test")
        for _ in range(10_000):
            pq.enqueue(req)

        start = time.perf_counter()
        pq.clear()
        elapsed = time.perf_counter() - start

        _record("pq_clear", 10_000 / elapsed, detail=f"10k items cleared in {elapsed:.4f}s")
        assert elapsed < 0.1
        assert pq.is_empty

    def test_concurrent_enqueue_dequeue(self):
        """Concurrent enqueue/dequeue from multiple threads should not crash."""
        pq = PriorityQueue(max_size=100_000)
        errors: list[Exception] = []

        def producer(n: int) -> None:
            try:
                for i in range(n):
                    pq.enqueue(PrioritizedRequest(
                        priority=RequestPriority.NORMAL,
                        method="GET",
                        path=f"/api/{i}",
                    ))
            except Exception as e:
                errors.append(e)

        def consumer(n: int) -> None:
            try:
                consumed = 0
                while consumed < n:
                    item = pq.dequeue()
                    if item is not None:
                        consumed += 1
            except Exception as e:
                errors.append(e)

        threads = []
        for _ in range(3):
            threads.append(threading.Thread(target=producer, args=(2000,)))
        for _ in range(3):
            threads.append(threading.Thread(target=consumer, args=(2000,)))

        start = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        elapsed = time.perf_counter() - start

        assert not errors, f"Concurrent errors: {errors}"
        _record("pq_concurrent", 12_000 / elapsed, detail=f"12k ops in {elapsed:.3f}s")


# ── Batch Operations Benchmarks ────────────────────────────


class TestBatchOperationsBenchmark:
    """Benchmark batch aggregation and result creation."""

    def test_batch_aggregate_throughput(self):
        """Aggregating 1000 results should be fast."""
        results = [
            BatchResultItem(
                request_id=f"req_{i}",
                success=i % 10 != 0,
                data={"id": i} if i % 10 != 0 else None,
                error=Exception("fail") if i % 10 == 0 else None,
                latency_ms=float(i % 100),
            )
            for i in range(1000)
        ]

        start = time.perf_counter()
        for _ in range(100):
            summary = CommerceMCPBase._batch_aggregate(results, total_latency_ms=5000.0)
        elapsed = time.perf_counter() - start

        ops = 100 / elapsed
        _record("batch_aggregate", ops, detail=f"100 aggregations (1k results each) in {elapsed:.3f}s")
        assert elapsed < 2.0, f"100 batch aggregations took {elapsed:.3f}s"
        assert summary.total == 1000
        assert summary.succeeded == 900
        assert summary.failed == 100

    def test_batch_result_item_creation_speed(self):
        """Creating BatchResultItem instances should be fast."""
        start = time.perf_counter()
        items = [
            BatchResultItem(
                request_id=f"req_{i}",
                success=True,
                data={"id": i},
                latency_ms=float(i),
            )
            for i in range(10_000)
        ]
        elapsed = time.perf_counter() - start

        ops = 10_000 / elapsed
        _record("batch_result_creation", ops, detail=f"10k items in {elapsed:.3f}s")
        assert elapsed < 1.0
        assert len(items) == 10_000

    def test_batch_request_item_creation_speed(self):
        """Creating BatchRequestItem instances should be fast."""
        start = time.perf_counter()
        items = [
            BatchRequestItem(
                method="GET",
                path=f"/api/test/{i}",
                params={"page": str(i)},
                request_id=f"req_{i}",
            )
            for i in range(10_000)
        ]
        elapsed = time.perf_counter() - start

        ops = 10_000 / elapsed
        _record("batch_request_creation", ops, detail=f"10k items in {elapsed:.3f}s")
        assert elapsed < 1.0

    def test_batch_summary_access_speed(self):
        """Accessing BatchSummary properties should be fast."""
        results = [
            BatchResultItem(
                request_id=f"req_{i}",
                success=i % 5 != 0,
                latency_ms=float(i % 200),
            )
            for i in range(500)
        ]
        summary = BatchSummary(
            total=500,
            succeeded=400,
            failed=100,
            results=results,
            total_latency_ms=10_000.0,
        )

        start = time.perf_counter()
        for _ in range(10_000):
            _ = summary.total
            _ = summary.succeeded
            _ = summary.failed
            _ = summary.total_latency_ms
        elapsed = time.perf_counter() - start

        ops = 10_000 / elapsed
        _record("batch_summary_access", ops, detail=f"10k accesses in {elapsed:.3f}s")
        assert elapsed < 1.0

    def test_error_summary_aggregation(self):
        """Error summary should correctly group by exception type."""
        results = [
            BatchResultItem(request_id="1", success=False, error=ValueError("v")),
            BatchResultItem(request_id="2", success=False, error=ValueError("v")),
            BatchResultItem(request_id="3", success=False, error=TimeoutError("t")),
            BatchResultItem(request_id="4", success=True),
        ]
        summary = CommerceMCPBase._batch_aggregate(results, total_latency_ms=100.0)

        assert summary.total == 4
        assert summary.succeeded == 1
        assert summary.failed == 3
        assert summary.error_summary["ValueError"] == 2
        assert summary.error_summary["TimeoutError"] == 1


# ── PriorityScheduler Benchmarks ───────────────────────────


class TestPrioritySchedulerBenchmark:
    """Benchmark PriorityScheduler dispatch and stats."""

    @pytest.mark.asyncio
    async def test_schedule_and_execute_throughput(self):
        """Dispatching 1000 requests should be fast."""
        scheduler = PriorityScheduler()

        async def noop_execute(req: PrioritizedRequest) -> str:
            return f"done_{req.request_id}"

        start = time.perf_counter()
        tasks = []
        for i in range(1000):
            req = PrioritizedRequest(
                priority=RequestPriority.NORMAL,
                method="GET",
                path=f"/api/{i}",
                request_id=f"r{i}",
            )
            tasks.append(scheduler.schedule_and_execute(req, noop_execute))

        results = await asyncio.gather(*tasks)
        elapsed = time.perf_counter() - start

        ops = 1000 / elapsed
        _record("scheduler_execute", ops, detail=f"1000 dispatches in {elapsed:.3f}s")
        assert elapsed < 5.0, f"1000 dispatches took {elapsed:.3f}s"
        assert len(results) == 1000
        assert scheduler.stats.total_dispatched == 1000

    @pytest.mark.asyncio
    async def test_schedule_with_mixed_priorities(self):
        """Mixed priority dispatch should maintain stats correctly."""
        scheduler = PriorityScheduler()
        all_priorities = list(RequestPriority)

        async def noop_execute(req: PrioritizedRequest) -> str:
            return "ok"

        tasks = []
        for i in range(500):
            p = all_priorities[i % len(all_priorities)]
            req = PrioritizedRequest(priority=p, method="GET", path=f"/api/{i}", request_id=f"r{i}")
            tasks.append(scheduler.schedule_and_execute(req, noop_execute))

        await asyncio.gather(*tasks)

        assert scheduler.stats.total_dispatched == 500
        summary = scheduler.stats.get_summary()
        assert summary["total_dispatched"] == 500
        # Each priority should have been used
        assert len(summary["by_priority"]) == len(all_priorities)

    def test_priority_stats_record_performance(self):
        """Recording 10 000 dispatch stats should be fast."""
        stats = PriorityStats()

        start = time.perf_counter()
        for i in range(10_000):
            stats.record_dispatch(
                priority="NORMAL",
                queue_time_ms=float(i % 100),
                reordered=i % 5 == 0,
            )
        elapsed = time.perf_counter() - start

        ops = 10_000 / elapsed
        _record("priority_stats_record", ops, detail=f"10k records in {elapsed:.3f}s")
        assert elapsed < 1.0
        assert stats.total_dispatched == 10_000

    def test_priority_stats_summary_performance(self):
        """get_summary should be fast."""
        stats = PriorityStats()
        for i in range(1000):
            stats.record_dispatch(priority="NORMAL", queue_time_ms=float(i))

        start = time.perf_counter()
        for _ in range(10_000):
            stats.get_summary()
        elapsed = time.perf_counter() - start

        ops = 10_000 / elapsed
        _record("priority_stats_summary", ops, detail=f"10k summaries in {elapsed:.3f}s")
        assert elapsed < 1.0


# ── Concurrent Request Benchmarks ──────────────────────────


class TestConcurrentRequestBenchmark:
    """Benchmark concurrent operations across multiple components."""

    @pytest.mark.asyncio
    async def test_concurrent_cache_and_metrics(self):
        """Concurrent cache writes and metric recordings should not conflict."""
        cache = HealthCheckCache(ttl_seconds=60.0)
        collector = MetricsCollector()
        result = HealthCheckResult(status="healthy", configured=True)

        async def cache_writer(n: int) -> None:
            for i in range(n):
                cache.set(f"key_{i}", result)

        async def metrics_recorder(prefix: str, n: int) -> None:
            for i in range(n):
                collector.record_request(f"/api/{prefix}_{i}", latency_ms=float(i), success=True)

        start = time.perf_counter()
        await asyncio.gather(
            cache_writer(2000),
            cache_writer(2000),
            metrics_recorder("a", 2000),
            metrics_recorder("b", 2000),
        )
        elapsed = time.perf_counter() - start

        total_ops = 8000
        ops = total_ops / elapsed
        _record("concurrent_cache_metrics", ops, detail=f"8k mixed ops in {elapsed:.3f}s")
        assert elapsed < 5.0
        assert collector.get_global_metrics().request_count == 4000

    @pytest.mark.asyncio
    async def test_concurrent_priority_queue_and_scheduler(self):
        """Concurrent enqueue and schedule operations should be safe."""
        scheduler = PriorityScheduler()

        async def noop_execute(req: PrioritizedRequest) -> str:
            return "ok"

        async def enqueue_and_execute(n: int, prefix: str) -> int:
            tasks = []
            for i in range(n):
                req = PrioritizedRequest(
                    priority=RequestPriority.NORMAL,
                    method="GET",
                    path=f"/api/{prefix}/{i}",
                    request_id=f"{prefix}_{i}",
                )
                tasks.append(scheduler.schedule_and_execute(req, noop_execute))
            await asyncio.gather(*tasks)
            return n

        start = time.perf_counter()
        counts = await asyncio.gather(
            enqueue_and_execute(200, "a"),
            enqueue_and_execute(200, "b"),
            enqueue_and_execute(200, "c"),
        )
        elapsed = time.perf_counter() - start

        total = sum(counts)
        ops = total / elapsed
        _record("concurrent_scheduler", ops, detail=f"{total} dispatches in {elapsed:.3f}s")
        assert total == 600
        assert scheduler.stats.total_dispatched == 600

    @pytest.mark.asyncio
    async def test_concurrent_batch_aggregation(self):
        """Multiple concurrent batch aggregations should be safe."""
        results_lists = [
            [
                BatchResultItem(
                    request_id=f"r{j}",
                    success=j % 3 != 0,
                    latency_ms=float(j),
                )
                for j in range(100)
            ]
            for _ in range(20)
        ]

        start = time.perf_counter()
        summaries = await asyncio.gather(*[
            asyncio.to_thread(CommerceMCPBase._batch_aggregate, r, 5000.0)
            for r in results_lists
        ])
        elapsed = time.perf_counter() - start

        ops = 20 / elapsed
        _record("concurrent_batch_aggregate", ops, detail=f"20 aggregations in {elapsed:.3f}s")
        assert len(summaries) == 20
        assert all(s.total == 100 for s in summaries)

    @pytest.mark.asyncio
    async def test_concurrent_warmup_and_read(self):
        """CacheWarmer warmup and reads should be safe concurrently."""
        warmer = CacheWarmer()

        async def fake_fetch() -> dict[str, str]:
            await asyncio.sleep(0.001)  # Simulate small latency
            return {"data": "warmed"}

        for i in range(10):
            warmer.register(platform=f"P{i % 3}", cache_key=f"k{i}", fetch_fn=fake_fetch)

        # Pre-populate some cache entries
        for i in range(10):
            warmer.set_cached(f"k{i}", {"data": "pre"}, ttl_seconds=60.0)

        async def reader() -> int:
            hits = 0
            for _ in range(100):
                for i in range(10):
                    if warmer.get_cached(f"k{i}") is not None:
                        hits += 1
            return hits

        start = time.perf_counter()
        warmup_results, read_hits = await asyncio.gather(
            warmer.warmup_all(),
            reader(),
        )
        elapsed = time.perf_counter() - start

        _record("concurrent_warmup_read", 1010 / elapsed, detail=f"10 warmup + 1000 reads in {elapsed:.3f}s")
        assert len(warmup_results) == 10
        assert read_hits > 0


# ── End-to-End Pipeline Benchmark ──────────────────────────


class TestEndToEndPipelineBenchmark:
    """Benchmark a realistic pipeline: cache warmup -> priority queue -> batch -> metrics."""

    @pytest.mark.asyncio
    async def test_full_pipeline(self):
        """Full pipeline: warm cache -> enqueue priorities -> execute -> record metrics."""
        # Setup
        warmer = CacheWarmer()
        scheduler = PriorityScheduler()
        collector = MetricsCollector()
        cache = HealthCheckCache(ttl_seconds=60.0)

        async def fake_fetch() -> dict[str, Any]:
            return {"items": list(range(10))}

        # 1. Register and warm cache
        for i in range(8):
            warmer.register(platform=f"P{i % 4}", cache_key=f"products_{i}", fetch_fn=fake_fetch)

        start = time.perf_counter()
        warmup_results = await warmer.warmup_all()
        warmup_elapsed = time.perf_counter() - start

        # 2. Enqueue prioritized requests
        async def execute_and_record(req: PrioritizedRequest) -> dict[str, Any]:
            start_inner = time.perf_counter()
            # Simulate work: read from warmup cache
            data = warmer.get_cached(f"products_{req.request_id.split('_')[-1]}")
            latency = (time.perf_counter() - start_inner) * 1000
            collector.record_request(req.path, latency_ms=latency, success=True)
            return {"data": data, "cached": data is not None}

        start = time.perf_counter()
        tasks = []
        priorities = list(RequestPriority)
        for i in range(200):
            p = priorities[i % len(priorities)]
            req = PrioritizedRequest(
                priority=p,
                method="GET",
                path=f"/api/products/{i}",
                request_id=f"prod_{i % 8}",
                platform=f"P{i % 4}",
            )
            tasks.append(scheduler.schedule_and_execute(req, execute_and_record))

        results = await asyncio.gather(*tasks)
        pipeline_elapsed = time.perf_counter() - start

        # 3. Verify
        global_m = collector.get_global_metrics()
        summary = collector.get_summary()

        assert len(warmup_results) == 8
        assert len(results) == 200
        assert global_m.request_count == 200

        total_elapsed = warmup_elapsed + pipeline_elapsed
        ops = 200 / pipeline_elapsed
        _record("e2e_pipeline", ops, detail=f"200 requests in {pipeline_elapsed:.3f}s (warmup {warmup_elapsed:.3f}s)")
        _record(
            "e2e_pipeline_cache_hit_rate",
            global_m.request_count / 200 * 100,
            unit="%",
            detail=f"{global_m.request_count} requests recorded",
        )

        assert total_elapsed < 10.0, f"Full pipeline took {total_elapsed:.3f}s"


# ── Benchmark Summary Output ───────────────────────────────


class TestBenchmarkSummary:
    """Output a formatted benchmark results table after all tests run.

    This class is intentionally ordered last (alphabetically) so its
    test runs after all benchmarks have recorded their results.
    """

    def test_print_benchmark_results(self):
        """Print the collected benchmark results as a formatted table."""
        # Force this to run last by checking if results exist
        if not _BENCHMARK_RESULTS:
            pytest.skip("No benchmark results collected")

        print("\n")
        print("=" * 80)
        print("  BENCHMARK RESULTS SUMMARY")
        print("=" * 80)
        print(f"{'Benchmark':<40} {'Value':>12} {'Unit':<8} {'Detail'}")
        print("-" * 80)

        for r in _BENCHMARK_RESULTS:
            name = r["name"]
            value = r["value"]
            unit = r["unit"]
            detail = r.get("detail", "")
            print(f"{name:<40} {value:>12,.1f} {unit:<8} {detail}")

        print("-" * 80)

        # Group by category
        categories: dict[str, list[dict[str, Any]]] = {}
        for r in _BENCHMARK_RESULTS:
            cat = r["name"].split("_")[0]
            categories.setdefault(cat, []).append(r)

        print(f"\nTotal benchmarks: {len(_BENCHMARK_RESULTS)}")
        print(f"Categories: {', '.join(sorted(categories.keys()))}")

        # Find fastest/slowest
        ops_results = [r for r in _BENCHMARK_RESULTS if r["unit"] == "ops/s"]
        if ops_results:
            fastest = max(ops_results, key=lambda r: r["value"])
            slowest = min(ops_results, key=lambda r: r["value"])
            print(f"Fastest: {fastest['name']} @ {fastest['value']:,.1f} {fastest['unit']}")
            print(f"Slowest: {slowest['name']} @ {slowest['value']:,.1f} {slowest['unit']}")

        print("=" * 80)
