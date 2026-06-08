# Monitoring & Health Checks

mcp-cn-commerce provides built-in monitoring and health check capabilities in the shared base module.

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
| `last_error_code` | `int \| None` | Most recent error code |
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
#   "platform": "https://api.example.com",
#   "configured": True,
#   "has_token": True,
#   "api_reachable": True,
#   "status_code": 200,
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
| `platform` | `str` | The `BASE_URL` being checked |
| `configured` | `bool` | Whether `app_key` and `app_secret` are set |
| `has_token` | `bool` | Whether `access_token` is set |
| `api_reachable` | `bool` | Whether the HEAD request succeeded (< 500) |
| `status_code` | `int` | HTTP status code (if request completed) |
| `latency_ms` | `float` | Round-trip latency in milliseconds |
| `error` | `str` | Error description (if unreachable) |
| `metrics` | `dict` | Full `MetricsCollector.get_summary()` output |

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
```
