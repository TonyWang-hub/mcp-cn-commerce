# Monitoring Dashboard

The `MonitoringDashboard` provides a unified view of API call statistics, cache performance, response time distribution, and webhook delivery status.

## Quick Start

```python
from dashboard import MonitoringDashboard
from cn_commerce_base import CommerceMCPBase, WebhookManager

# Create dashboard with optional integrations
client = CommerceMCPBase(app_key="...", app_secret="...")
webhook_mgr = WebhookManager()

dashboard = MonitoringDashboard(
    metrics_collector=client.metrics,
    webhook_manager=webhook_mgr,
)
```

## Dashboard Sections

### API Call Statistics

Automatically populated from `MetricsCollector` if provided. Shows total requests, error counts, error rate, and per-endpoint breakdown.

```python
snapshot = dashboard.get_snapshot()
api = snapshot["api_calls"]
print(f"Total: {api['total_requests']}, Errors: {api['total_errors']}, Rate: {api['error_rate']:.2%}")
```

### Cache Statistics

Track cache hit/miss rates using `CacheStatsTracker` (accessible as `dashboard.cache`).

```python
dashboard.cache.record_hit()
dashboard.cache.record_miss()
dashboard.cache.record_miss()

stats = dashboard.cache.get_stats()
print(f"Hit rate: {stats.hit_rate:.2%}")  # 33.33%
print(f"Total lookups: {stats.total_lookups}")  # 3
```

#### CacheStatsTracker Methods

| Method | Description |
|---|---|
| `record_hit()` | Record a cache hit |
| `record_miss()` | Record a cache miss |
| `record_eviction()` | Record a cache eviction |
| `set_entry_count(n)` | Update current cache entry count |
| `get_stats()` | Get `CacheStats` object |
| `reset()` | Reset all statistics |

#### CacheStats Fields

| Field | Type | Description |
|---|---|---|
| `hits` | `int` | Total cache hits |
| `misses` | `int` | Total cache misses |
| `hit_rate` | `float` | Hits / total lookups (0.0 to 1.0) |
| `miss_rate` | `float` | 1 - hit_rate |
| `evictions` | `int` | Total evictions |
| `total_entries` | `int` | Current cache size |
| `max_entries` | `int` | Maximum cache capacity |

### Response Time Distribution

Records latency samples and groups them into histogram buckets.

```python
dashboard.response_times.record(42.5)
dashboard.response_times.record(150.0)
dashboard.response_times.record(750.0)

distribution = dashboard.response_times.get_distribution()
for bucket in distribution:
    if bucket.count > 0:
        print(f"  {bucket.label}: {bucket.count}")
# 0-50ms: 1
# 100-250ms: 1
# 500-1000ms: 1
```

Default buckets: `0-50ms`, `50-100ms`, `100-250ms`, `250-500ms`, `500-1000ms`, `1000ms+`.

Custom boundaries:

```python
from dashboard import ResponseTimeHistogram

histogram = ResponseTimeHistogram(boundaries=[0, 100, 500, float("inf")])
```

### Webhook Status

Automatically populated from `WebhookManager` if provided. Shows delivery success rate, latency, subscription counts.

```python
webhooks = snapshot["webhooks"]
print(f"Deliveries: {webhooks['total_deliveries']}")
print(f"Success rate: {webhooks['success_rate']:.2%}")
print(f"Active subscriptions: {webhooks['active_subscriptions']}")
```

## Alert Rules

Configure threshold-based alerts that are evaluated on each `get_snapshot()` call.

```python
from dashboard import AlertRule, AlertSeverity

# Alert when error rate exceeds 10%
dashboard.add_alert_rule(AlertRule(
    metric_name="api_calls.error_rate",
    threshold=0.10,
    severity=AlertSeverity.WARNING,
    direction="above",
))

# Alert when cache hit rate drops below 50%
dashboard.add_alert_rule(AlertRule(
    metric_name="cache.hit_rate",
    threshold=0.50,
    severity=AlertSeverity.WARNING,
    direction="below",
))

# Alert on critical error rate
dashboard.add_alert_rule(AlertRule(
    metric_name="api_calls.error_rate",
    threshold=0.50,
    severity=AlertSeverity.CRITICAL,
    direction="above",
))

# Alerts are evaluated and included in snapshot
snapshot = dashboard.get_snapshot()
for alert in snapshot["alerts"]:
    print(f"[{alert['severity']}] {alert['message']}")
```

### AlertRule Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `metric_name` | `str` | required | Dot-separated metric path |
| `threshold` | `float` | required | Trigger value |
| `severity` | `AlertSeverity` | `WARNING` | Alert severity level |
| `direction` | `str` | `"above"` | `"above"` or `"below"` |

### AlertSeverity Levels

| Level | Description |
|---|---|
| `info` | Informational |
| `warning` | Requires attention |
| `critical` | Immediate action needed |

## Full Snapshot

```python
snapshot = dashboard.get_snapshot()
# {
#   "timestamp": "2026-06-09T10:30:00+00:00",
#   "uptime_seconds": 120.5,
#   "api_calls": {
#     "total_requests": 100,
#     "total_errors": 5,
#     "error_rate": 0.05,
#     "avg_latency_ms": 123.45,
#     "endpoints": { ... }
#   },
#   "cache": {
#     "hits": 80,
#     "misses": 20,
#     "hit_rate": 0.80,
#     "miss_rate": 0.20,
#     "evictions": 0,
#     "total_entries": 50,
#     "max_entries": 100
#   },
#   "response_times": {
#     "distribution": [
#       {"label": "0-50ms", "count": 30},
#       {"label": "50-100ms", "count": 40},
#       ...
#     ],
#     "total_samples": 100
#   },
#   "webhooks": {
#     "total_deliveries": 10,
#     "succeeded": 9,
#     "failed": 1,
#     "success_rate": 0.90,
#     "avg_latency_ms": 50.0,
#     "active_subscriptions": 3,
#     "total_subscriptions": 3,
#     "total_events": 10
#   },
#   "alerts": [ ... ]
# }
```

## JSON Export

```python
json_str = dashboard.get_snapshot_json(indent=2)
print(json_str)
```

## Integration with External Monitoring

```python
import asyncio

async def periodic_export(dashboard: MonitoringDashboard):
    """Export dashboard snapshot to external monitoring every 30 seconds."""
    while True:
        snapshot = dashboard.get_snapshot()
        # Push to Prometheus, Grafana, Datadog, etc.
        await push_to_monitoring(snapshot)
        await asyncio.sleep(30)
```
