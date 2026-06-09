"""Tests for the monitoring dashboard module.

Tests cover:
- CacheStatsTracker: hit/miss tracking, hit_rate calculation, reset
- ResponseTimeHistogram: bucket distribution, custom boundaries
- AlertRule: threshold evaluation, severity filtering
- MonitoringDashboard: snapshot generation, JSON export, alert evaluation
- Integration with MetricsCollector and WebhookManager
"""

from __future__ import annotations

import json
import time

import pytest

from shared.cn_commerce_base import (
    MetricsCollector,
    WebhookManager,
)
from shared.dashboard import (
    AlertRule,
    AlertSeverity,
    CacheStats,
    CacheStatsTracker,
    DashboardAlert,
    MonitoringDashboard,
    ResponseTimeHistogram,
)

# ── CacheStats Tests ───────────────────────────────────────


class TestCacheStats:
    """Test CacheStats dataclass properties."""

    def test_hit_rate_with_no_lookups(self):
        stats = CacheStats()
        assert stats.hit_rate == 0.0
        assert stats.miss_rate == 1.0
        assert stats.total_lookups == 0

    def test_hit_rate_with_hits_and_misses(self):
        stats = CacheStats(hits=75, misses=25)
        assert stats.hit_rate == 0.75
        assert stats.miss_rate == 0.25
        assert stats.total_lookups == 100

    def test_hit_rate_all_hits(self):
        stats = CacheStats(hits=100, misses=0)
        assert stats.hit_rate == 1.0
        assert stats.miss_rate == 0.0

    def test_hit_rate_all_misses(self):
        stats = CacheStats(hits=0, misses=50)
        assert stats.hit_rate == 0.0
        assert stats.miss_rate == 1.0


# ── CacheStatsTracker Tests ────────────────────────────────


class TestCacheStatsTracker:
    """Test CacheStatsTracker thread-safe operations."""

    def test_record_hit(self):
        tracker = CacheStatsTracker()
        tracker.record_hit()
        tracker.record_hit()
        stats = tracker.get_stats()
        assert stats.hits == 2
        assert stats.misses == 0

    def test_record_miss(self):
        tracker = CacheStatsTracker()
        tracker.record_miss()
        stats = tracker.get_stats()
        assert stats.misses == 1

    def test_record_eviction(self):
        tracker = CacheStatsTracker()
        tracker.record_eviction()
        tracker.record_eviction()
        stats = tracker.get_stats()
        assert stats.evictions == 2

    def test_set_entry_count(self):
        tracker = CacheStatsTracker(max_entries=100)
        tracker.set_entry_count(42)
        stats = tracker.get_stats()
        assert stats.total_entries == 42
        assert stats.max_entries == 100

    def test_hit_rate_calculation(self):
        tracker = CacheStatsTracker()
        for _ in range(8):
            tracker.record_hit()
        for _ in range(2):
            tracker.record_miss()
        stats = tracker.get_stats()
        assert stats.hit_rate == pytest.approx(0.8)
        assert stats.miss_rate == pytest.approx(0.2)

    def test_reset(self):
        tracker = CacheStatsTracker(max_entries=100)
        tracker.record_hit()
        tracker.record_miss()
        tracker.set_entry_count(50)
        tracker.reset()
        stats = tracker.get_stats()
        assert stats.hits == 0
        assert stats.misses == 0
        assert stats.evictions == 0
        assert stats.total_entries == 0
        # max_entries should be preserved
        assert stats.max_entries == 100

    def test_get_stats_returns_copy(self):
        tracker = CacheStatsTracker()
        tracker.record_hit()
        stats1 = tracker.get_stats()
        tracker.record_hit()
        stats2 = tracker.get_stats()
        assert stats1.hits == 1
        assert stats2.hits == 2


# ── ResponseTimeHistogram Tests ────────────────────────────


class TestResponseTimeHistogram:
    """Test ResponseTimeHistogram bucket distribution."""

    def test_default_buckets(self):
        histogram = ResponseTimeHistogram()
        distribution = histogram.get_distribution()
        labels = [b.label for b in distribution]
        assert labels == ["0-50ms", "50-100ms", "100-250ms", "250-500ms", "500-1000ms", "1000ms+"]

    def test_record_sample(self):
        histogram = ResponseTimeHistogram()
        histogram.record(25.0)  # 0-50ms
        histogram.record(75.0)  # 50-100ms
        histogram.record(25.0)  # 0-50ms
        distribution = histogram.get_distribution()
        counts = {b.label: b.count for b in distribution}
        assert counts["0-50ms"] == 2
        assert counts["50-100ms"] == 1
        assert counts["100-250ms"] == 0

    def test_record_boundary_value(self):
        histogram = ResponseTimeHistogram()
        histogram.record(50.0)  # Exactly at 50ms boundary -> 50-100ms bucket
        distribution = histogram.get_distribution()
        counts = {b.label: b.count for b in distribution}
        assert counts["50-100ms"] == 1
        assert counts["0-50ms"] == 0

    def test_record_high_latency(self):
        histogram = ResponseTimeHistogram()
        histogram.record(5000.0)  # Should go to 1000ms+ bucket
        distribution = histogram.get_distribution()
        counts = {b.label: b.count for b in distribution}
        assert counts["1000ms+"] == 1

    def test_custom_boundaries(self):
        histogram = ResponseTimeHistogram(boundaries=[0, 100, 500, float("inf")])
        distribution = histogram.get_distribution()
        labels = [b.label for b in distribution]
        assert labels == ["0-100ms", "100-500ms", "500ms+"]
        histogram.record(80.0)
        histogram.record(200.0)
        histogram.record(600.0)
        distribution = histogram.get_distribution()
        counts = {b.label: b.count for b in distribution}
        assert counts["0-100ms"] == 1
        assert counts["100-500ms"] == 1
        assert counts["500ms+"] == 1

    def test_reset(self):
        histogram = ResponseTimeHistogram()
        histogram.record(25.0)
        histogram.record(75.0)
        histogram.reset()
        distribution = histogram.get_distribution()
        assert all(b.count == 0 for b in distribution)

    def test_total_samples(self):
        histogram = ResponseTimeHistogram()
        for latency in [10, 60, 120, 300, 600, 1500]:
            histogram.record(latency)
        distribution = histogram.get_distribution()
        total = sum(b.count for b in distribution)
        assert total == 6


# ── AlertRule Tests ────────────────────────────────────────


class TestAlertRule:
    """Test AlertRule configuration."""

    def test_default_severity(self):
        rule = AlertRule(metric_name="api_calls.error_rate", threshold=0.1)
        assert rule.severity == AlertSeverity.WARNING
        assert rule.direction == "above"

    def test_custom_severity(self):
        rule = AlertRule(
            metric_name="cache.hit_rate",
            threshold=0.5,
            severity=AlertSeverity.CRITICAL,
            direction="below",
        )
        assert rule.severity == AlertSeverity.CRITICAL
        assert rule.direction == "below"


# ── MonitoringDashboard Tests ──────────────────────────────


class TestMonitoringDashboard:
    """Test MonitoringDashboard core functionality."""

    def test_init_defaults(self):
        dashboard = MonitoringDashboard()
        assert dashboard._metrics_collector is None
        assert dashboard._webhook_manager is None

    def test_init_with_collector(self):
        collector = MetricsCollector()
        dashboard = MonitoringDashboard(metrics_collector=collector)
        assert dashboard._metrics_collector is collector

    def test_uptime_increases(self):
        dashboard = MonitoringDashboard()
        t1 = dashboard.uptime_seconds
        time.sleep(0.01)
        t2 = dashboard.uptime_seconds
        assert t2 > t1

    def test_snapshot_structure(self):
        dashboard = MonitoringDashboard()
        snapshot = dashboard.get_snapshot()
        assert "timestamp" in snapshot
        assert "uptime_seconds" in snapshot
        assert "api_calls" in snapshot
        assert "cache" in snapshot
        assert "response_times" in snapshot
        assert "webhooks" in snapshot
        assert "alerts" in snapshot

    def test_snapshot_without_integrations(self):
        dashboard = MonitoringDashboard()
        snapshot = dashboard.get_snapshot()
        assert snapshot["api_calls"]["total_requests"] == 0
        assert snapshot["api_calls"]["total_errors"] == 0
        assert snapshot["cache"]["hits"] == 0
        assert snapshot["webhooks"]["total_deliveries"] == 0

    def test_snapshot_with_metrics_collector(self):
        collector = MetricsCollector()
        collector.record_request("/api/test", 100.0, True)
        collector.record_request("/api/test", 200.0, False, error_code=500, error_msg="Server Error")
        dashboard = MonitoringDashboard(metrics_collector=collector)
        snapshot = dashboard.get_snapshot()
        assert snapshot["api_calls"]["total_requests"] == 2
        assert snapshot["api_calls"]["total_errors"] == 1
        assert snapshot["api_calls"]["error_rate"] == pytest.approx(0.5)

    def test_snapshot_with_cache_data(self):
        dashboard = MonitoringDashboard()
        for _ in range(8):
            dashboard.cache.record_hit()
        for _ in range(2):
            dashboard.cache.record_miss()
        snapshot = dashboard.get_snapshot()
        assert snapshot["cache"]["hits"] == 8
        assert snapshot["cache"]["misses"] == 2
        assert snapshot["cache"]["hit_rate"] == pytest.approx(0.8)

    def test_snapshot_with_response_times(self):
        dashboard = MonitoringDashboard()
        dashboard.response_times.record(25.0)
        dashboard.response_times.record(75.0)
        dashboard.response_times.record(150.0)
        snapshot = dashboard.get_snapshot()
        dist = snapshot["response_times"]["distribution"]
        total = sum(d["count"] for d in dist)
        assert total == 3
        assert snapshot["response_times"]["total_samples"] == 3

    def test_snapshot_with_webhook_manager(self):
        wm = WebhookManager()
        wm.subscribe(url="https://example.com/hook", event_types=["order_update"])
        dashboard = MonitoringDashboard(webhook_manager=wm)
        snapshot = dashboard.get_snapshot()
        assert snapshot["webhooks"]["total_subscriptions"] == 1
        assert snapshot["webhooks"]["active_subscriptions"] == 1

    def test_get_snapshot_json(self):
        dashboard = MonitoringDashboard()
        json_str = dashboard.get_snapshot_json()
        data = json.loads(json_str)
        assert "timestamp" in data
        assert "api_calls" in data

    def test_reset(self):
        dashboard = MonitoringDashboard()
        dashboard.cache.record_hit()
        dashboard.response_times.record(50.0)
        dashboard.add_alert_rule(AlertRule(metric_name="cache.hit_rate", threshold=0.5))
        dashboard.reset()
        snapshot = dashboard.get_snapshot()
        assert snapshot["cache"]["hits"] == 0
        assert snapshot["alerts"] == []


# ── Alert System Tests ─────────────────────────────────────


class TestDashboardAlerts:
    """Test dashboard alert rules and evaluation."""

    def test_add_alert_rule(self):
        dashboard = MonitoringDashboard()
        rule = AlertRule(metric_name="api_calls.error_rate", threshold=0.1)
        dashboard.add_alert_rule(rule)
        assert len(dashboard._alert_rules) == 1

    def test_remove_alert_rules(self):
        dashboard = MonitoringDashboard()
        dashboard.add_alert_rule(AlertRule(metric_name="api_calls.error_rate", threshold=0.1))
        dashboard.add_alert_rule(AlertRule(metric_name="api_calls.error_rate", threshold=0.5))
        dashboard.add_alert_rule(AlertRule(metric_name="cache.hit_rate", threshold=0.5))
        removed = dashboard.remove_alert_rules("api_calls.error_rate")
        assert removed == 2
        assert len(dashboard._alert_rules) == 1

    def test_alert_triggered_above_threshold(self):
        collector = MetricsCollector()
        for _ in range(10):
            collector.record_request("/api/test", 100.0, False, error_code=500)
        dashboard = MonitoringDashboard(metrics_collector=collector)
        dashboard.add_alert_rule(
            AlertRule(
                metric_name="api_calls.error_rate",
                threshold=0.05,
                severity=AlertSeverity.WARNING,
            )
        )
        snapshot = dashboard.get_snapshot()
        assert len(snapshot["alerts"]) >= 1
        assert snapshot["alerts"][0]["severity"] == "warning"

    def test_alert_triggered_below_threshold(self):
        dashboard = MonitoringDashboard()
        dashboard.cache.record_miss()
        dashboard.add_alert_rule(
            AlertRule(
                metric_name="cache.hit_rate",
                threshold=0.5,
                severity=AlertSeverity.WARNING,
                direction="below",
            )
        )
        snapshot = dashboard.get_snapshot()
        # hit_rate is 0.0 (no hits), which is below 0.5
        assert len(snapshot["alerts"]) >= 1

    def test_alert_not_triggered_when_within_bounds(self):
        collector = MetricsCollector()
        collector.record_request("/api/test", 100.0, True)
        dashboard = MonitoringDashboard(metrics_collector=collector)
        dashboard.add_alert_rule(
            AlertRule(
                metric_name="api_calls.error_rate",
                threshold=0.5,
            )
        )
        snapshot = dashboard.get_snapshot()
        error_alerts = [a for a in snapshot["alerts"] if a["metric_name"] == "api_calls.error_rate"]
        assert len(error_alerts) == 0

    def test_get_alerts_filter_by_severity(self):
        dashboard = MonitoringDashboard()
        dashboard._alerts = [
            DashboardAlert(
                severity=AlertSeverity.INFO,
                message="info alert",
                metric_name="test",
                metric_value=1.0,
                threshold=0.5,
            ),
            DashboardAlert(
                severity=AlertSeverity.CRITICAL,
                message="critical alert",
                metric_name="test",
                metric_value=1.0,
                threshold=0.5,
            ),
        ]
        info_alerts = dashboard.get_alerts(severity=AlertSeverity.INFO)
        critical_alerts = dashboard.get_alerts(severity=AlertSeverity.CRITICAL)
        assert len(info_alerts) == 1
        assert len(critical_alerts) == 1

    def test_clear_alerts(self):
        dashboard = MonitoringDashboard()
        dashboard._alerts = [
            DashboardAlert(
                severity=AlertSeverity.WARNING,
                message="test",
                metric_name="test",
                metric_value=1.0,
                threshold=0.5,
            ),
        ]
        dashboard.clear_alerts()
        assert len(dashboard.get_alerts()) == 0

    def test_multiple_alert_rules_same_snapshot(self):
        collector = MetricsCollector()
        for _ in range(10):
            collector.record_request("/api/test", 100.0, False, error_code=500)
        dashboard = MonitoringDashboard(metrics_collector=collector)
        dashboard.cache.record_miss()
        dashboard.add_alert_rule(
            AlertRule(
                metric_name="api_calls.error_rate",
                threshold=0.05,
            )
        )
        dashboard.add_alert_rule(
            AlertRule(
                metric_name="cache.hit_rate",
                threshold=0.5,
                direction="below",
            )
        )
        snapshot = dashboard.get_snapshot()
        metric_names = {a["metric_name"] for a in snapshot["alerts"]}
        assert "api_calls.error_rate" in metric_names
        assert "cache.hit_rate" in metric_names


# ── Integration Tests ──────────────────────────────────────


class TestDashboardIntegration:
    """Test dashboard integration with real MetricsCollector and WebhookManager."""

    def test_full_lifecycle(self):
        collector = MetricsCollector()
        wm = WebhookManager()
        dashboard = MonitoringDashboard(
            metrics_collector=collector,
            webhook_manager=wm,
        )

        # Simulate API calls
        collector.record_request("/api/product/get", 50.0, True)
        collector.record_request("/api/product/get", 75.0, True)
        collector.record_request("/api/order/search", 200.0, False, error_code=1001, error_msg="Invalid param")

        # Simulate cache operations
        dashboard.cache.record_hit()
        dashboard.cache.record_hit()
        dashboard.cache.record_miss()
        dashboard.cache.set_entry_count(10)

        # Simulate response times
        dashboard.response_times.record(50.0)
        dashboard.response_times.record(75.0)
        dashboard.response_times.record(200.0)

        # Register webhook
        wm.subscribe(url="https://example.com/hook", event_types=["order_update"])

        # Get snapshot
        snapshot = dashboard.get_snapshot()

        assert snapshot["api_calls"]["total_requests"] == 3
        assert snapshot["api_calls"]["total_errors"] == 1
        assert snapshot["cache"]["hits"] == 2
        assert snapshot["cache"]["misses"] == 1
        assert snapshot["cache"]["hit_rate"] == pytest.approx(2 / 3, abs=0.001)
        assert snapshot["cache"]["total_entries"] == 10
        assert snapshot["response_times"]["total_samples"] == 3
        assert snapshot["webhooks"]["total_subscriptions"] == 1

    def test_snapshot_json_roundtrip(self):
        dashboard = MonitoringDashboard()
        dashboard.cache.record_hit()
        json_str = dashboard.get_snapshot_json()
        data = json.loads(json_str)
        assert data["cache"]["hits"] == 1
        assert isinstance(data["uptime_seconds"], float)
