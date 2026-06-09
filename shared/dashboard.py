"""Monitoring Dashboard for mcp-cn-commerce.

Aggregates metrics from MetricsCollector, cache statistics, and webhook
delivery stats into a unified dashboard view for real-time monitoring.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

# ── Cache Statistics ───────────────────────────────────────


@dataclass
class CacheStats:
    """Tracks cache hit/miss statistics.

    Attributes:
        hits: Number of cache hits.
        misses: Number of cache misses.
        evictions: Number of cache evictions.
        total_entries: Current number of entries in cache.
        max_entries: Maximum cache capacity.
    """

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    total_entries: int = 0
    max_entries: int = 0

    @property
    def total_lookups(self) -> int:
        """Total cache lookups (hits + misses)."""
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        """Cache hit rate as a fraction (0.0 to 1.0)."""
        total = self.total_lookups
        if total == 0:
            return 0.0
        return self.hits / total

    @property
    def miss_rate(self) -> float:
        """Cache miss rate as a fraction (0.0 to 1.0)."""
        return 1.0 - self.hit_rate


class CacheStatsTracker:
    """Thread-safe cache statistics tracker.

    Can be used standalone or integrated with external cache systems.

    Usage:
        tracker = CacheStatsTracker(max_entries=1000)
        tracker.record_hit()
        tracker.record_miss()
        print(tracker.get_stats())
    """

    def __init__(self, max_entries: int = 0) -> None:
        self._lock = threading.Lock()
        self._stats = CacheStats(max_entries=max_entries)

    def record_hit(self) -> None:
        """Record a cache hit."""
        with self._lock:
            self._stats.hits += 1

    def record_miss(self) -> None:
        """Record a cache miss."""
        with self._lock:
            self._stats.misses += 1

    def record_eviction(self) -> None:
        """Record a cache eviction."""
        with self._lock:
            self._stats.evictions += 1

    def set_entry_count(self, count: int) -> None:
        """Update the current cache entry count."""
        with self._lock:
            self._stats.total_entries = count

    def get_stats(self) -> CacheStats:
        """Get current cache statistics."""
        with self._lock:
            return CacheStats(
                hits=self._stats.hits,
                misses=self._stats.misses,
                evictions=self._stats.evictions,
                total_entries=self._stats.total_entries,
                max_entries=self._stats.max_entries,
            )

    def reset(self) -> None:
        """Reset all cache statistics."""
        with self._lock:
            max_entries = self._stats.max_entries
            self._stats = CacheStats(max_entries=max_entries)


# ── Response Time Histogram ────────────────────────────────


@dataclass
class ResponseTimeBucket:
    """A single histogram bucket for response time distribution.

    Attributes:
        label: Human-readable label (e.g., "0-50ms").
        lower_ms: Lower bound in milliseconds (inclusive).
        upper_ms: Upper bound in milliseconds (exclusive).
        count: Number of requests falling in this bucket.
    """

    label: str
    lower_ms: float
    upper_ms: float
    count: int = 0


class ResponseTimeHistogram:
    """Tracks response time distribution across configurable buckets.

    Default buckets: 0-50ms, 50-100ms, 100-250ms, 250-500ms,
    500-1000ms, 1000ms+.

    Usage:
        histogram = ResponseTimeHistogram()
        histogram.record(42.5)
        histogram.record(150.0)
        print(histogram.get_distribution())
    """

    DEFAULT_BOUNDARIES = [0, 50, 100, 250, 500, 1000, float("inf")]

    def __init__(self, boundaries: list[float] | None = None) -> None:
        self._lock = threading.Lock()
        self._boundaries = boundaries or self.DEFAULT_BOUNDARIES
        self._buckets: list[ResponseTimeBucket] = []
        for i in range(len(self._boundaries) - 1):
            lower = self._boundaries[i]
            upper = self._boundaries[i + 1]
            if upper == float("inf"):
                label = f"{int(lower)}ms+"
            else:
                label = f"{int(lower)}-{int(upper)}ms"
            self._buckets.append(ResponseTimeBucket(label=label, lower_ms=lower, upper_ms=upper))

    def record(self, latency_ms: float) -> None:
        """Record a response time sample."""
        with self._lock:
            for bucket in self._buckets:
                if bucket.lower_ms <= latency_ms < bucket.upper_ms:
                    bucket.count += 1
                    return
            # Edge case: exactly at the last boundary
            if self._buckets:
                self._buckets[-1].count += 1

    def get_distribution(self) -> list[ResponseTimeBucket]:
        """Get the current distribution."""
        with self._lock:
            return [
                ResponseTimeBucket(
                    label=b.label,
                    lower_ms=b.lower_ms,
                    upper_ms=b.upper_ms,
                    count=b.count,
                )
                for b in self._buckets
            ]

    def reset(self) -> None:
        """Reset all histogram data."""
        with self._lock:
            for bucket in self._buckets:
                bucket.count = 0


# ── Dashboard Alert ────────────────────────────────────────


class AlertSeverity(StrEnum):
    """Alert severity levels."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class DashboardAlert:
    """An alert raised by the dashboard.

    Attributes:
        severity: Alert severity level.
        message: Human-readable alert message.
        metric_name: Name of the metric that triggered the alert.
        metric_value: Current value of the metric.
        threshold: Threshold that was exceeded.
        timestamp: When the alert was raised (Unix timestamp).
    """

    severity: AlertSeverity
    message: str
    metric_name: str
    metric_value: float
    threshold: float
    timestamp: float = field(default_factory=time.time)


# ── Alert Rules ────────────────────────────────────────────


@dataclass
class AlertRule:
    """Configuration for a dashboard alert rule.

    Attributes:
        metric_name: Dot-separated metric path (e.g., "global.error_rate").
        threshold: Value that triggers the alert.
        severity: Alert severity when threshold is exceeded.
        direction: "above" triggers when metric > threshold,
                   "below" triggers when metric < threshold.
    """

    metric_name: str
    threshold: float
    severity: AlertSeverity = AlertSeverity.WARNING
    direction: str = "above"


# ── Monitoring Dashboard ───────────────────────────────────


class MonitoringDashboard:
    """Unified monitoring dashboard for mcp-cn-commerce.

    Aggregates data from MetricsCollector, CacheStatsTracker, and
    WebhookManager into a single dashboard view.

    Usage:
        from shared.cn_commerce_base import CommerceMCPBase, WebhookManager
        from shared.dashboard import MonitoringDashboard

        client = CommerceMCPBase(app_key="...", app_secret="...")
        webhook_mgr = WebhookManager()
        dashboard = MonitoringDashboard(
            metrics_collector=client.metrics,
            webhook_manager=webhook_mgr,
        )

        # Record cache operations
        dashboard.cache.record_hit()
        dashboard.cache.record_miss()

        # Get full dashboard snapshot
        snapshot = dashboard.get_snapshot()
    """

    def __init__(
        self,
        metrics_collector: Any = None,
        webhook_manager: Any = None,
        cache_max_entries: int = 0,
    ) -> None:
        """Initialize the monitoring dashboard.

        Args:
            metrics_collector: Optional MetricsCollector instance.
            webhook_manager: Optional WebhookManager instance.
            cache_max_entries: Maximum cache entries for CacheStatsTracker.
        """
        self._metrics_collector = metrics_collector
        self._webhook_manager = webhook_manager
        self.cache = CacheStatsTracker(max_entries=cache_max_entries)
        self.response_times = ResponseTimeHistogram()
        self._alert_rules: list[AlertRule] = []
        self._alerts: list[DashboardAlert] = []
        self._lock = threading.Lock()
        self._start_time = time.time()

    @property
    def uptime_seconds(self) -> float:
        """Dashboard uptime in seconds."""
        return time.time() - self._start_time

    def add_alert_rule(self, rule: AlertRule) -> None:
        """Add an alert rule to the dashboard.

        Args:
            rule: AlertRule configuration.
        """
        with self._lock:
            self._alert_rules.append(rule)

    def remove_alert_rules(self, metric_name: str) -> int:
        """Remove all alert rules for a given metric.

        Args:
            metric_name: The metric path to remove rules for.

        Returns:
            Number of rules removed.
        """
        with self._lock:
            before = len(self._alert_rules)
            self._alert_rules = [r for r in self._alert_rules if r.metric_name != metric_name]
            return before - len(self._alert_rules)

    def get_alerts(self, severity: AlertSeverity | None = None) -> list[DashboardAlert]:
        """Get raised alerts, optionally filtered by severity.

        Args:
            severity: If set, only return alerts of this severity.

        Returns:
            List of DashboardAlert instances.
        """
        with self._lock:
            if severity is None:
                return list(self._alerts)
            return [a for a in self._alerts if a.severity == severity]

    def clear_alerts(self) -> None:
        """Clear all raised alerts."""
        with self._lock:
            self._alerts.clear()

    def _resolve_metric_value(self, metric_path: str, snapshot: dict[str, Any]) -> float | None:
        """Resolve a dot-separated metric path against a snapshot dict.

        Args:
            metric_path: Dot-separated path (e.g., "api_calls.total_requests").
            snapshot: The dashboard snapshot dict.

        Returns:
            Numeric value if found, None otherwise.
        """
        parts = metric_path.split(".")
        current: Any = snapshot
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        if isinstance(current, (int, float)):
            return float(current)
        return None

    def _evaluate_alerts(self, snapshot: dict[str, Any]) -> None:
        """Evaluate alert rules against a snapshot and raise alerts."""
        for rule in self._alert_rules:
            value = self._resolve_metric_value(rule.metric_name, snapshot)
            if value is None:
                continue

            triggered = False
            if rule.direction == "above" and value > rule.threshold:
                triggered = True
            elif rule.direction == "below" and value < rule.threshold:
                triggered = True

            if triggered:
                alert = DashboardAlert(
                    severity=rule.severity,
                    message=(
                        f"{rule.metric_name} = {value} "
                        f"{'>' if rule.direction == 'above' else '<'} "
                        f"threshold {rule.threshold}"
                    ),
                    metric_name=rule.metric_name,
                    metric_value=value,
                    threshold=rule.threshold,
                )
                with self._lock:
                    self._alerts.append(alert)

    def get_snapshot(self) -> dict[str, Any]:
        """Get a complete dashboard snapshot.

        Returns:
            Dictionary with all dashboard data sections:
            - timestamp: ISO 8601 timestamp
            - uptime_seconds: Dashboard uptime
            - api_calls: API call statistics from MetricsCollector
            - cache: Cache hit/miss statistics
            - response_times: Response time distribution
            - webhooks: Webhook delivery statistics
            - alerts: Currently raised alerts
        """
        now = time.time()
        snapshot: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "uptime_seconds": round(now - self._start_time, 2),
        }

        # API call statistics
        if self._metrics_collector is not None:
            metrics_summary = self._metrics_collector.get_summary()
            snapshot["api_calls"] = {
                "total_requests": metrics_summary["global"]["total_requests"],
                "total_errors": metrics_summary["global"]["total_errors"],
                "error_rate": metrics_summary["global"]["error_rate"],
                "avg_latency_ms": metrics_summary["global"]["avg_latency_ms"],
                "endpoints": metrics_summary.get("endpoints", {}),
            }
        else:
            snapshot["api_calls"] = {
                "total_requests": 0,
                "total_errors": 0,
                "error_rate": 0.0,
                "avg_latency_ms": 0.0,
                "endpoints": {},
            }

        # Cache statistics
        cache_stats = self.cache.get_stats()
        snapshot["cache"] = {
            "hits": cache_stats.hits,
            "misses": cache_stats.misses,
            "hit_rate": round(cache_stats.hit_rate, 4),
            "miss_rate": round(cache_stats.miss_rate, 4),
            "evictions": cache_stats.evictions,
            "total_entries": cache_stats.total_entries,
            "max_entries": cache_stats.max_entries,
        }

        # Response time distribution
        distribution = self.response_times.get_distribution()
        snapshot["response_times"] = {
            "distribution": [{"label": b.label, "count": b.count} for b in distribution],
            "total_samples": sum(b.count for b in distribution),
        }

        # Webhook statistics
        if self._webhook_manager is not None:
            snapshot["webhooks"] = self._webhook_manager.get_delivery_stats()
        else:
            snapshot["webhooks"] = {
                "total_deliveries": 0,
                "succeeded": 0,
                "failed": 0,
                "success_rate": 0.0,
                "avg_latency_ms": 0.0,
                "active_subscriptions": 0,
                "total_subscriptions": 0,
                "total_events": 0,
            }

        # Evaluate alert rules
        self._evaluate_alerts(snapshot)

        # Include alerts in snapshot
        with self._lock:
            snapshot["alerts"] = [
                {
                    "severity": a.severity,
                    "message": a.message,
                    "metric_name": a.metric_name,
                    "metric_value": a.metric_value,
                    "threshold": a.threshold,
                    "timestamp": a.timestamp,
                }
                for a in self._alerts
            ]

        return snapshot

    def get_snapshot_json(self, indent: int = 2) -> str:
        """Get the dashboard snapshot as a JSON string.

        Args:
            indent: JSON indentation level.

        Returns:
            JSON string of the dashboard snapshot.
        """
        return json.dumps(self.get_snapshot(), indent=indent, default=str)

    def reset(self) -> None:
        """Reset all dashboard state."""
        with self._lock:
            self._alerts.clear()
            self._alert_rules.clear()
        self.cache.reset()
        self.response_times.reset()
        self._start_time = time.time()
