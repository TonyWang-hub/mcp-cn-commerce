# Monitoring, Health Checks & Alerting

mcp-cn-commerce provides built-in monitoring, health check, and alerting capabilities in the shared base module.

## MetricsCollector

Tracks request counts, latency, and error rates per endpoint and globally.

### Usage

```python
from cn_commerce_base import CommerceMCPBase, MetricsCollector

client = CommerceMCPBase(app_key="...", app_secret="...", access_token="...")

# Metrics are collected automatically on every _request() call
await client._request("GET", "/api/product/get", params={"item_id": "123"})

# Get global summary
summary = client.metrics.get_summary()
print(summary)
# {
#   "uptime_seconds": 42.1,
#   "global": {
#     "total_requests": 1,
#     "total_errors": 0,
#     "error_rate": 0.0,
#     "avg_latency_ms": 123.45,
#     "min_latency_ms": 123.45,
#     "max_latency_ms": 123.45,
#   },
#   "endpoints": {
#     "/api/product/get": {
#       "requests": 1,
#       "errors": 0,
#       "error_rate": 0.0,
#       "avg_latency_ms": 123.45,
#       "min_latency_ms": 123.45,
#       "max_latency_ms": 123.45,
#     }
#   }
# }

# Per-endpoint metrics
ep = client.metrics.get_endpoint_metrics("/api/product/get")
print(f"Requests: {ep.request_count}, Avg latency: {ep.avg_latency_ms:.1f}ms, Error rate: {ep.error_rate:.2%}")

# Reset all metrics
client.metrics.reset()
```

### EndpointMetrics Fields

| Field | Type | Description |
|---|---|---|
| `request_count` | `int` | Total requests to this endpoint |
| `error_count` | `int` | Requests that returned an error |
| `total_latency_ms` | `float` | Cumulative latency in milliseconds |
| `min_latency_ms` | `float` | Fastest request latency |
| `max_latency_ms` | `float` | Slowest request latency |
| `last_error_code` | `int | None` | Most recent error code |
| `last_error_msg` | `str` | Most recent error message |

Computed properties: `avg_latency_ms`, `error_rate`.

### What Gets Tracked

- **Every `_request()` call** -- success or failure, with millisecond latency.
- **API errors** (`error_response` in JSON) -- recorded with error code and message.
- **Network errors** (timeout, connection refused, etc.) -- recorded with `error_code=-1`.
- **Path as endpoint key** -- e.g., `/api/product/get`, `/api/order/search`.

## Health Check

`health_check()` performs a lightweight HEAD request to verify API connectivity.

### Usage

```python
status = await client.health_check()
print(status)
# {
#   "status": "healthy",
#   "configured": True,
#   "has_token": True,
#   "api_reachable": True,
#   "latency_ms": 45.23,
#   "metrics": { ... }  # full metrics summary
# }

# Check reachability
if status["api_reachable"]:
    print("API is healthy")
else:
    print(f"API unreachable: {status.get('error')}")
```

### Health Check Fields

| Field | Type | Description |
|---|---|---|
| `status` | `str` | Overall status: "healthy", "degraded", or "unhealthy" |
| `configured` | `bool` | Whether `app_key` and `app_secret` are set |
| `has_token` | `bool` | Whether `access_token` is set |
| `api_reachable` | `bool` | Whether the HEAD request succeeded (< 500) |
| `latency_ms` | `float` | Round-trip latency in milliseconds |
| `error` | `str` | Error description (if unreachable) |
| `metrics` | `dict` | Full `MetricsCollector.get_summary()` output |
| `cached` | `bool` | Whether the result was served from cache |

### Deep Health Check

For dependency-aware health checking, use `deep_health_check()`:

```python
result = await client.deep_health_check(
    dependencies=["https://cache.example.com", "https://db.example.com"],
    timeout=10.0,
)
# result includes "dependencies" dict with per-dependency status
```

## Alerting

The alerting system evaluates metrics against configurable rules and fires notifications when thresholds are breached.

### Quick Start

```python
from cn_commerce_base import AlertRule, AlertSeverity

client = CommerceMCPBase(app_key="...", app_secret="...")

# Add a custom alert rule
client.alert_manager.add_rule(AlertRule(
    name="high_error_rate",
    description="Error rate exceeds 20%",
    metric_path="global.error_rate",
    threshold=0.2,
    comparison="gt",
    severity=AlertSeverity.HIGH,
    cooldown_seconds=600.0,
))

# Register a notification callback
def on_alert(alert):
    print(f"ALERT: {alert.message}")

client.alert_manager.notifier.add_callback(on_alert)

# Evaluate and fire alerts
results = await client.check_and_fire_alerts(platform="OCEANENGINE")
```

### Default Alert Rules

mcp-cn-commerce ships with four built-in alert rules:

| Name | Metric | Threshold | Severity | Cooldown |
|---|---|---|---|---|
| `high_error_rate` | `global.error_rate` | > 0.10 | HIGH | 300s |
| `critical_error_rate` | `global.error_rate` | > 0.50 | CRITICAL | 60s |
| `high_latency` | `global.avg_latency_ms` | > 5000ms | MEDIUM | 600s |
| `critical_latency` | `global.avg_latency_ms` | > 30000ms | HIGH | 120s |

### AlertRule

Defines when an alert should fire.

| Field | Type | Description |
|---|---|---|
| `rule_id` | `str` | Auto-generated unique ID |
| `name` | `str` | Human-readable name |
| `description` | `str` | What triggers this alert |
| `metric_path` | `str` | Dot-separated path to metric (e.g., `global.error_rate`) |
| `threshold` | `float` | Numeric threshold value |
| `comparison` | `str` | Operator: `gt`, `gte`, `lt`, `lte`, `eq` |
| `severity` | `str` | `critical`, `high`, `medium`, or `low` |
| `cooldown_seconds` | `float` | Minimum seconds between consecutive alerts |
| `enabled` | `bool` | Whether the rule is active |
| `tags` | `list[str]` | User-defined tags for filtering |
| `platform` | `str` | Platform filter (empty = all) |
| `endpoint` | `str` | Endpoint filter (empty = all) |

### Alert Severity Levels

| Level | Description |
|---|---|
| `CRITICAL` | Immediate action required. Service down or data loss. |
| `HIGH` | Urgent attention needed. Significant degradation. |
| `MEDIUM` | Warning condition. May escalate if unaddressed. |
| `LOW` | Informational. Track but no immediate action. |

### Alert (Fired Instance)

Represents a single alert that was triggered.

| Field | Type | Description |
|---|---|---|
| `alert_id` | `str` | Auto-generated unique ID |
| `rule_id` | `str` | ID of the rule that triggered |
| `rule_name` | `str` | Name of the rule |
| `severity` | `str` | Alert severity level |
| `message` | `str` | Human-readable alert message |
| `metric_value` | `float` | The metric value that triggered the alert |
| `threshold` | `float` | The threshold that was exceeded |
| `metric_path` | `str` | The metric path that was evaluated |
| `fired_at` | `str` | ISO 8601 timestamp of when the alert fired |
| `resolved_at` | `str` | ISO 8601 timestamp of resolution (if resolved) |
| `status` | `str` | `firing`, `resolved`, or `silenced` |

### AlertNotifier

Manages notification delivery channels.

```python
# Add notification callbacks (sync or async)
client.alert_manager.notifier.add_callback(lambda alert: print(alert.message))

async def send_to_webhook(alert):
    await httpx.AsyncClient().post("https://hooks.slack.com/...", json=alert.to_dict())

client.alert_manager.notifier.add_callback(send_to_webhook)
```

### AlertManager

The central component that ties rules, metrics, and notifications together.

```python
manager = client.alert_manager

# List current rules
rules = manager.list_rules(enabled_only=True)

# Get firing alerts
firing = manager.get_firing_alerts(severity=AlertSeverity.CRITICAL)

# Resolve an alert
manager.resolve_alert(alert_id)

# Silence a rule temporarily
manager.silence_rule(rule_id, duration_seconds=3600)

# Get alert history
history = manager.get_alert_history(severity=AlertSeverity.HIGH, limit=100)

# Export/import rules
rules_json = manager.export_rules()
manager.import_rules(rules_json)

# Get stats
stats = manager.get_alert_stats()
```

### Metric Paths

Use dot-separated paths to reference metrics from the MetricsCollector summary:

| Path | Description |
|---|---|
| `global.error_rate` | Global error rate (0.0 - 1.0) |
| `global.avg_latency_ms` | Global average latency |
| `global.total_requests` | Total request count |
| `global.total_errors` | Total error count |
| `endpoints.<path>.error_rate` | Per-endpoint error rate |
| `endpoints.<path>.avg_latency_ms` | Per-endpoint average latency |

## Integrating with External Monitoring

Export metrics to Prometheus, Grafana, or any monitoring system:

```python
from your_platform_server import YourPlatformServer

server = YourPlatformServer(app_key="...", app_secret="...")

# Periodic metrics export
async def export_metrics():
    summary = server.metrics.get_summary()
    # Push to Prometheus, Datadog, etc.
    await push_to_monitoring(summary)

# Health endpoint for load balancer
async def health_endpoint():
    status = await server.health_check()
    if status["api_reachable"]:
        return {"status": "healthy"}, 200
    return {"status": "unhealthy", "error": status.get("error")}, 503

# Alert endpoint for monitoring dashboard
async def alert_endpoint():
    alerts = server.alert_manager.get_firing_alerts()
    return {
        "firing_count": len(alerts),
        "alerts": [a.to_dict() for a in alerts],
        "stats": server.get_alert_stats(),
    }
```
