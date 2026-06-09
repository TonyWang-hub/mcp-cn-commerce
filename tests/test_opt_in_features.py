"""Integration tests for opt-in advanced capabilities.

These tests prove that the opt-in helpers implemented in
``shared.cn_commerce_base`` are reachable and functional. They focus on
"the integration path works", not on platform-specific business
correctness:

- WebhookManager / WebhookSignatureVerifier (HMAC-SHA256, constant-time)
- LoadBalancer + FailoverManager (selection, failover, circuit breaker)
- CacheWarmer (cache warmup path via base ``warmup_cache``)
- RequestRecorder / RequestReplayer (record then replay)
- RequestDeduplicator (dedup within a window)
- PriorityScheduler (priority-aware scheduling)
- AlertManager (add rule, evaluate_metrics, fire, get_alerts)

Each capability is exercised both directly and, where the base now exposes
a thin accessor, from a ``CommerceMCPBase`` instance.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from shared.cn_commerce_base import (
    Alert,
    AlertManager,
    AlertRule,
    AlertSeverity,
    CommerceMCPBase,
    FailoverConfig,
    FailoverManager,
    LoadBalancer,
    LoadBalancingStrategy,
    PrioritizedRequest,
    PriorityScheduler,
    RequestDeduplicator,
    RequestPriority,
    RequestRecorder,
    RequestReplayer,
    WebhookEvent,
    WebhookManager,
    WebhookSignatureVerifier,
)

# ── 1. Webhook signature verification ─────────────────────


class TestWebhookSignatureVerifier:
    """HMAC-SHA256 signature signing and verification."""

    def test_sign_returns_hex_sha256(self):
        verifier = WebhookSignatureVerifier(secret="topsecret")
        sig = verifier.sign(b'{"event":"order_update"}')
        assert isinstance(sig, str)
        assert len(sig) == 64  # SHA256 hex length

    def test_verify_correct_signature(self):
        verifier = WebhookSignatureVerifier(secret="topsecret")
        payload = b'{"event":"order_update","id":42}'
        sig = verifier.sign(payload)
        assert verifier.verify(payload, sig) is True

    def test_verify_wrong_signature(self):
        verifier = WebhookSignatureVerifier(secret="topsecret")
        payload = b'{"event":"order_update"}'
        assert verifier.verify(payload, "deadbeef" * 8) is False

    def test_verify_tampered_payload(self):
        verifier = WebhookSignatureVerifier(secret="topsecret")
        sig = verifier.sign(b'{"amount":100}')
        # Same signature, mutated payload -> must not verify.
        assert verifier.verify(b'{"amount":999}', sig) is False

    def test_verify_empty_signature(self):
        verifier = WebhookSignatureVerifier(secret="s")
        assert verifier.verify(b"payload", "") is False

    def test_wrong_secret_does_not_verify(self):
        signer = WebhookSignatureVerifier(secret="secret-a")
        checker = WebhookSignatureVerifier(secret="secret-b")
        payload = b"data"
        assert checker.verify(payload, signer.sign(payload)) is False

    def test_extract_signature_strips_prefix(self):
        raw = "sha256=abc123"
        assert WebhookSignatureVerifier.extract_signature(raw, prefix="sha256=") == "abc123"


class TestWebhookManager:
    """Subscribe, verify, and trigger delivery via WebhookManager."""

    def test_subscribe_and_get(self):
        manager = WebhookManager()
        sub = manager.subscribe(
            url="https://example.com/hook",
            event_types=["order_update"],
            secret="sek",
        )
        assert manager.get_subscription(sub.subscription_id) is sub
        assert "order_update" in sub.event_types

    def test_manager_verify_signature_roundtrip(self):
        manager = WebhookManager()
        payload = b'{"x":1}'
        verifier = WebhookSignatureVerifier(secret="sek")
        good = verifier.sign(payload)
        assert manager.verify_signature(payload, good, secret="sek") is True
        assert manager.verify_signature(payload, good, secret="other") is False

    @pytest.mark.asyncio
    async def test_trigger_delivers_to_matching_subscription(self):
        manager = WebhookManager()
        sub = manager.subscribe(
            url="https://example.com/hook",
            event_types=["order_update"],
            secret="sek",
        )

        received: list[tuple] = []

        async def _callback(subscription, event, payload_bytes, signature):
            from shared.cn_commerce_base import WebhookDeliveryResult

            # Prove the manager signs the delivered payload with the sub secret.
            verifier = WebhookSignatureVerifier(secret=subscription.secret)
            assert verifier.verify(payload_bytes, signature) is True
            received.append((subscription.subscription_id, event.event_type))
            return WebhookDeliveryResult(
                subscription_id=subscription.subscription_id,
                event_id=event.event_id,
                success=True,
                status_code=200,
            )

        manager.add_delivery_callback(_callback)
        results = await manager.trigger(WebhookEvent(event_type="order_update", payload={"id": 1}))

        assert len(results) == 1
        assert results[0].success is True
        assert received == [(sub.subscription_id, "order_update")]

    def test_reachable_from_base_instance(self):
        client = CommerceMCPBase()
        assert isinstance(client.webhook_manager, WebhookManager)
        # Lazy singleton: same instance on repeated access.
        assert client.webhook_manager is client.webhook_manager


# ── 2. LoadBalancer + FailoverManager ─────────────────────


class TestLoadBalancer:
    """Endpoint selection by strategy."""

    def test_round_robin_cycles_endpoints(self):
        lb = LoadBalancer(LoadBalancingStrategy.ROUND_ROBIN)
        lb.add_endpoint("https://a.example.com")
        lb.add_endpoint("https://b.example.com")
        picked = [lb.get_endpoint().url for _ in range(4)]
        # Both endpoints should appear, alternating.
        assert set(picked) == {"https://a.example.com", "https://b.example.com"}
        assert picked[0] != picked[1]

    def test_no_endpoints_returns_none(self):
        lb = LoadBalancer()
        assert lb.get_endpoint() is None

    def test_least_connections_picks_idle(self):
        lb = LoadBalancer(LoadBalancingStrategy.LEAST_CONNECTIONS)
        lb.add_endpoint("https://busy.example.com")
        lb.add_endpoint("https://idle.example.com")
        lb.increment_connections("https://busy.example.com")
        assert lb.get_endpoint().url == "https://idle.example.com"

    def test_unhealthy_endpoint_skipped(self):
        lb = LoadBalancer(LoadBalancingStrategy.ROUND_ROBIN)
        lb.add_endpoint("https://a.example.com")
        lb.add_endpoint("https://b.example.com")
        lb.mark_unhealthy("https://a.example.com")
        picked = {lb.get_endpoint().url for _ in range(5)}
        assert picked == {"https://b.example.com"}

    def test_reachable_from_base_instance(self):
        client = CommerceMCPBase()
        assert isinstance(client.load_balancer, LoadBalancer)
        assert client.load_balancer is client.load_balancer


class TestFailoverManager:
    """Failover marking and circuit breaker path."""

    def test_failure_marks_unhealthy_after_max(self):
        lb = LoadBalancer()
        lb.add_endpoint("https://a.example.com")
        fm = FailoverManager(lb, config=FailoverConfig(max_failures=2))

        fm.report_failure("https://a.example.com")
        assert lb._endpoints["https://a.example.com"].is_healthy is True
        fm.report_failure("https://a.example.com")
        assert lb._endpoints["https://a.example.com"].is_healthy is False

    def test_success_recovers_endpoint(self):
        lb = LoadBalancer()
        lb.add_endpoint("https://a.example.com")
        fm = FailoverManager(lb, config=FailoverConfig(max_failures=1))
        fm.report_failure("https://a.example.com")
        assert lb._endpoints["https://a.example.com"].is_healthy is False
        fm.report_success("https://a.example.com")
        assert lb._endpoints["https://a.example.com"].is_healthy is True

    def test_circuit_breaker_opens_on_high_failure_rate(self):
        lb = LoadBalancer()
        lb.add_endpoint("https://a.example.com")
        # Large max_failures so unhealthy-marking is driven by the breaker.
        fm = FailoverManager(
            lb,
            config=FailoverConfig(max_failures=100, circuit_breaker_threshold=0.5),
        )
        # 5+ requests with a >50% failure rate trips the breaker.
        for _ in range(6):
            fm.report_failure("https://a.example.com")
        assert fm.is_circuit_open("https://a.example.com") is True

    def test_failover_routes_around_failed_endpoint(self):
        lb = LoadBalancer()
        lb.add_endpoint("https://a.example.com")
        lb.add_endpoint("https://b.example.com")
        fm = FailoverManager(lb, config=FailoverConfig(max_failures=1))
        # After the failure the load balancer should only hand out the
        # remaining healthy endpoint.
        fm.report_failure("https://a.example.com")
        picked = {lb.get_endpoint().url for _ in range(5)}
        assert picked == {"https://b.example.com"}

    def test_get_stats_reports_failover_state(self):
        lb = LoadBalancer()
        lb.add_endpoint("https://a.example.com")
        fm = FailoverManager(lb, config=FailoverConfig(max_failures=1))
        fm.report_failure("https://a.example.com", error="timeout")
        stats = fm.get_stats()
        assert stats["total_failure_events"] == 1
        assert stats["recent_failures"][-1]["url"] == "https://a.example.com"

    def test_create_from_base_instance(self):
        client = CommerceMCPBase()
        client.load_balancer.add_endpoint("https://a.example.com")
        fm = client.create_failover_manager()
        assert isinstance(fm, FailoverManager)
        # Bound to the same load balancer the base exposes.
        fm.report_success("https://a.example.com")
        assert client.load_balancer.get_endpoint().url == "https://a.example.com"


# ── 3. CacheWarmer ─────────────────────────────────────────


class TestCacheWarmer:
    """Cache warmup path via the base ``warmup_cache`` convenience."""

    @pytest.mark.asyncio
    async def test_warmup_cache_all_via_base(self):
        client = CommerceMCPBase()

        async def fetch_products():
            return [{"id": 1}, {"id": 2}]

        client.cache_warmer.register("OCEANENGINE", "hot_products", fetch_products)
        results = await client.warmup_cache()

        assert len(results) == 1
        assert results[0]["success"] is True
        assert results[0]["cache_key"] == "hot_products"
        # The fetched data should now be cached and retrievable.
        assert client.cache_warmer.get_cached("hot_products") == [{"id": 1}, {"id": 2}]

    @pytest.mark.asyncio
    async def test_warmup_cache_specific_platform(self):
        client = CommerceMCPBase()

        async def fetch_a():
            return "A"

        async def fetch_b():
            return "B"

        client.cache_warmer.register("PLAT_A", "key_a", fetch_a)
        client.cache_warmer.register("PLAT_B", "key_b", fetch_b)

        results = await client.warmup_cache(platforms=["PLAT_A"])
        assert [r["cache_key"] for r in results] == ["key_a"]
        assert client.cache_warmer.get_cached("key_a") == "A"
        assert client.cache_warmer.get_cached("key_b") is None

    @pytest.mark.asyncio
    async def test_warmup_records_failure(self):
        client = CommerceMCPBase()

        async def fetch_boom():
            raise RuntimeError("upstream down")

        client.cache_warmer.register("PLAT", "bad_key", fetch_boom)
        results = await client.warmup_cache()
        assert results[0]["success"] is False
        assert "upstream down" in results[0]["error"]


# ── 4. RequestRecorder / RequestReplayer ──────────────────


class TestRequestRecordAndReplay:
    """Record a request, then replay it through an executor."""

    @pytest.mark.asyncio
    async def test_record_then_replay(self):
        recorder = RequestRecorder()
        recorder.record(
            method="GET",
            path="/api/order",
            params={"id": "1"},
            response={"result": {"id": "1"}},
            status_code=200,
            latency_ms=12.0,
        )
        assert len(recorder.get_records()) == 1

        replayer = RequestReplayer(recorder)
        execute_fn = AsyncMock(return_value={"result": {"id": "1"}})
        results = await replayer.replay_all(execute_fn)

        assert len(results) == 1
        assert results[0]["success"] is True
        assert results[0]["new_response"] == {"result": {"id": "1"}}
        # Executor invoked with the recorded method/path.
        call = execute_fn.call_args
        assert call.kwargs["method"] == "GET"
        assert call.kwargs["path"] == "/api/order"

    @pytest.mark.asyncio
    async def test_replay_captures_executor_error(self):
        recorder = RequestRecorder()
        recorder.record(method="POST", path="/api/x", response={"ok": True})
        replayer = RequestReplayer(recorder)

        execute_fn = AsyncMock(side_effect=RuntimeError("boom"))
        results = await replayer.replay_all(execute_fn)
        assert results[0]["success"] is False
        assert "boom" in results[0]["error"]

    @pytest.mark.asyncio
    async def test_validate_replay_matches_structure(self):
        recorder = RequestRecorder()
        recorder.record(method="GET", path="/api/y", response={"a": 1, "b": 2})
        replayer = RequestReplayer(recorder)

        # Same key structure -> matched.
        execute_fn = AsyncMock(return_value={"a": 9, "b": 8})
        report = await replayer.validate_replay(execute_fn)
        assert report["total"] == 1
        assert report["matched"] == 1
        assert report["mismatched"] == 0

    def test_export_import_roundtrip(self):
        recorder = RequestRecorder()
        recorder.record(method="GET", path="/api/z", response={"v": 1})
        exported = recorder.export_json()

        fresh = RequestRecorder()
        imported = fresh.import_json(exported)
        assert imported == 1
        assert fresh.get_records()[0].path == "/api/z"

    @pytest.mark.asyncio
    async def test_reachable_from_base_instance(self):
        client = CommerceMCPBase()
        assert isinstance(client.request_recorder, RequestRecorder)
        client.request_recorder.record(method="GET", path="/api/order", response={"ok": 1})

        replayer = client.create_replayer()
        assert isinstance(replayer, RequestReplayer)
        execute_fn = AsyncMock(return_value={"ok": 1})
        results = await replayer.replay_all(execute_fn)
        assert results[0]["success"] is True


# ── 5. RequestDeduplicator ─────────────────────────────────


class TestRequestDeduplicator:
    """Identical requests within the window are deduplicated."""

    def test_first_request_is_unique(self):
        dedup = RequestDeduplicator(window_seconds=30.0)
        is_dup = dedup.check_and_record("GET", "/api/order", params={"id": "1"})
        assert is_dup is False

    def test_duplicate_within_window(self):
        dedup = RequestDeduplicator(window_seconds=30.0)
        dedup.check_and_record("GET", "/api/order", params={"id": "1"})
        is_dup = dedup.check_and_record("GET", "/api/order", params={"id": "1"})
        assert is_dup is True

    def test_different_params_not_duplicate(self):
        dedup = RequestDeduplicator(window_seconds=30.0)
        dedup.check_and_record("GET", "/api/order", params={"id": "1"})
        assert dedup.check_and_record("GET", "/api/order", params={"id": "2"}) is False

    def test_expired_window_not_duplicate(self):
        dedup = RequestDeduplicator(window_seconds=0.0)
        dedup.check_and_record("GET", "/api/order", params={"id": "1"})
        # Window of 0 means nothing is ever still "within" the window.
        assert dedup.check_and_record("GET", "/api/order", params={"id": "1"}) is False

    def test_stats_track_dedup(self):
        dedup = RequestDeduplicator(window_seconds=30.0)
        dedup.check_and_record("GET", "/api/a")
        dedup.check_and_record("GET", "/api/a")
        stats = dedup.get_stats()
        assert stats["total_requests"] == 2
        assert stats["total_deduplicated"] == 1

    def test_reachable_from_base_instance(self):
        client = CommerceMCPBase()
        assert isinstance(client.deduplicator, RequestDeduplicator)
        assert client.deduplicator.check_and_record("GET", "/api/x") is False
        assert client.deduplicator.check_and_record("GET", "/api/x") is True


# ── 6. PriorityScheduler ───────────────────────────────────


class TestPriorityScheduler:
    """Priority-aware scheduling and queue ordering."""

    @pytest.mark.asyncio
    async def test_schedule_and_execute_runs_fn(self):
        scheduler = PriorityScheduler()
        req = PrioritizedRequest(
            priority=RequestPriority.HIGH,
            method="GET",
            path="/api/order",
            platform="OCEANENGINE",
        )

        async def execute_fn(r):
            return {"ran": r.path}

        result = await scheduler.schedule_and_execute(req, execute_fn)
        assert result == {"ran": "/api/order"}
        summary = scheduler.get_stats_summary()
        assert summary["stats"]["total_dispatched"] == 1
        assert summary["stats"]["by_priority"]["high"] == 1

    def test_queue_orders_by_priority(self):
        scheduler = PriorityScheduler()
        scheduler.enqueue(PrioritizedRequest(priority=RequestPriority.LOW, path="/low"))
        scheduler.enqueue(PrioritizedRequest(priority=RequestPriority.CRITICAL, path="/crit"))
        scheduler.enqueue(PrioritizedRequest(priority=RequestPriority.NORMAL, path="/norm"))

        # Highest priority (CRITICAL) dequeues first.
        assert scheduler.dequeue().path == "/crit"
        assert scheduler.dequeue().path == "/norm"
        assert scheduler.dequeue().path == "/low"

    @pytest.mark.asyncio
    async def test_prioritized_request_via_base(self):
        client = CommerceMCPBase(app_key="k", app_secret="s")
        client._request = AsyncMock(return_value={"result": "ok"})

        result = await client.prioritized_request(
            "GET",
            "/api/order",
            priority=RequestPriority.CRITICAL,
            params={"id": "1"},
        )
        assert result == {"result": "ok"}
        client._request.assert_awaited_once()
        # The base scheduler recorded the dispatch.
        assert client.get_priority_stats()["stats"]["total_dispatched"] == 1

    def test_base_exposes_scheduler(self):
        client = CommerceMCPBase()
        assert isinstance(client.priority_scheduler, PriorityScheduler)


# ── 7. AlertManager ────────────────────────────────────────


class TestAlertManager:
    """Add a rule, evaluate metrics, and fire alerts."""

    def test_add_rule_and_evaluate_triggers(self):
        manager = AlertManager(include_default_rules=False)
        manager.add_rule(
            AlertRule(
                name="high_errors",
                metric_path="global.error_rate",
                threshold=0.1,
                comparison="gt",
                severity=AlertSeverity.HIGH,
                cooldown_seconds=0.0,
            )
        )
        metrics = {"global": {"error_rate": 0.5}}
        alerts = manager.evaluate_metrics(metrics)
        assert len(alerts) == 1
        assert isinstance(alerts[0], Alert)
        assert alerts[0].severity == AlertSeverity.HIGH

    def test_evaluate_no_trigger_below_threshold(self):
        manager = AlertManager(include_default_rules=False)
        manager.add_rule(
            AlertRule(
                name="high_errors",
                metric_path="global.error_rate",
                threshold=0.5,
                comparison="gt",
                cooldown_seconds=0.0,
            )
        )
        alerts = manager.evaluate_metrics({"global": {"error_rate": 0.1}})
        assert alerts == []

    @pytest.mark.asyncio
    async def test_fire_alert_notifies_callbacks(self):
        manager = AlertManager(include_default_rules=False)
        manager.add_rule(
            AlertRule(
                name="crit",
                metric_path="global.error_rate",
                threshold=0.0,
                comparison="gt",
                cooldown_seconds=0.0,
            )
        )
        delivered: list[Alert] = []
        manager.notifier.add_callback(lambda a: delivered.append(a))

        alerts = manager.evaluate_metrics({"global": {"error_rate": 0.9}})
        assert len(alerts) == 1
        await manager.fire_alert(alerts[0])

        assert len(delivered) == 1
        assert manager.get_stats()["total_alerts_fired"] == 1
        assert len(manager.get_firing_alerts()) == 1

    def test_get_alerts_via_base(self):
        client = CommerceMCPBase()
        # Drive a high error rate through the base metrics collector.
        for _ in range(10):
            client.metrics.record_request("/api/x", latency_ms=10.0, success=False, error_code=1, error_msg="e")

        result = client.get_alerts()
        assert "firing" in result
        assert "stats" in result
        # Default rules include "high_error_rate" (>10%); error_rate is 1.0.
        fired_paths = {a["metric_path"] for a in result["firing"]}
        assert "global.error_rate" in fired_paths

    def test_evaluate_alerts_via_base(self):
        client = CommerceMCPBase()
        for _ in range(10):
            client.metrics.record_request("/api/x", latency_ms=10.0, success=False, error_code=1, error_msg="e")
        alerts = client.evaluate_alerts(platform="TESTPLAT")
        assert all(isinstance(a, Alert) for a in alerts)
        assert any(a.metric_path == "global.error_rate" for a in alerts)
