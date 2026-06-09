# Distributed Tracing & Connection Pool Monitoring

mcp-cn-commerce includes built-in distributed tracing and connection pool monitoring for all platform API calls.

## Distributed Tracing

### Core Concepts

- **Trace**: A complete request flow across one or more services, identified by a `trace_id`.
- **Span**: A single unit of work within a trace (e.g., one API call), identified by a `span_id`.
- **TraceContext**: Propagated across service boundaries via HTTP headers.

### Basic Usage

Every `CommerceMCPBase` instance has a built-in `Tracer`:

```python
from cn_commerce_base import CommerceMCPBase, span_scope

client = CommerceMCPBase(app_key="...", app_secret="...")
tracer = client.tracer

# All _request() calls automatically create spans
# Access the trace summary after requests
summary = tracer.get_trace_summary()
print(summary)
# {
#   "trace_id": "abc123...",
#   "span_count": 3,
#   "active_span_count": 0,
#   "total_duration_ms": 245.32,
#   "root_span": "GET /api/orders",
#   "status": "ok",
#   "service_name": "CommerceMCPBase"
# }
```

### Creating Custom Spans

```python
from cn_commerce_base import Tracer, span_scope

tracer = Tracer(service_name="order-service")

# Using start_span / finish_span
span = tracer.start_span("process_order")
span.set_attribute("order_id", "12345")
span.add_event("validation_complete")
# ... do work ...
span.set_status("ok")
tracer.finish_span(span)

# Using the span_scope context manager (recommended)
with span_scope(tracer, "process_order") as span:
    span.set_attribute("order_id", "12345")
    # span is automatically finished on block exit
    # errors are automatically captured
```

### Parent-Child Spans

```python
parent = tracer.start_span("fetch_all_orders")

with span_scope(tracer, "fetch_page_1", parent=parent) as child:
    child.set_attribute("page", 1)
    # ... fetch first page ...

with span_scope(tracer, "fetch_page_2", parent=parent) as child:
    child.set_attribute("page", 2)
    # ... fetch second page ...

tracer.finish_span(parent)
```

### Trace Context Propagation

Inject and extract trace context across HTTP boundaries:

```python
# Sender: inject trace context into headers
headers = {"Content-Type": "application/json"}
tracer.inject_headers(headers)
# headers now contains: X-Trace-Id, X-Span-Id

# Receiver: extract trace context from headers
context = tracer.extract_context(incoming_headers)
```

#### W3C Trace Context Support

```python
from cn_commerce_base import TraceContext

# Parse W3C traceparent header
context = TraceContext.from_w3c(
    traceparent="00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
    tracestate="vendor=value",
)

# Convert back to W3C format
traceparent, tracestate = context.to_w3c()
```

### Exporting Traces

```python
# Export all spans as structured JSON
trace_data = tracer.export_trace()
# {
#   "trace_id": "...",
#   "service_name": "taobao-api",
#   "span_count": 5,
#   "spans": [
#     {
#       "trace_id": "...",
#       "span_id": "...",
#       "parent_id": null,
#       "name": "GET /api/orders",
#       "start_time": 1717800000.0,
#       "end_time": 1717800000.25,
#       "duration_ms": 250.0,
#       "status": "ok",
#       "attributes": {"http.method": "GET"},
#       "events": []
#     },
#     ...
#   ]
# }
```

### Clearing Traces

```python
tracer.clear()  # Removes all recorded spans
```

## Connection Pool Monitoring

### Basic Usage

Every `CommerceMCPBase` instance has a built-in `ConnectionPoolMonitor`:

```python
client = CommerceMCPBase(app_key="...", app_secret="...")

# Get current pool metrics
metrics = client.pool_monitor.get_metrics()
print(metrics)
# PoolMetrics(
#   total_connections=3,
#   active_connections=3,
#   idle_connections=7,
#   pool_utilization=0.3,
#   max_connections=10,
#   ...
# )
```

### Health Status

```python
health = client.pool_monitor.get_health_status()
# {
#   "status": "healthy",          # "healthy", "warning", or "critical"
#   "utilization": 0.3,
#   "peak_active": 5,
#   "total_requests": 42,
#   "avg_wait_time_ms": 1.23,
#   "warning": None               # or a warning message
# }
```

### Health Status Thresholds

| Utilization | Status   | Description |
|------------|----------|-------------|
| < 70%      | healthy  | Normal operation |
| 70% - 90%  | warning  | Monitor for saturation |
| > 90%      | critical | Consider increasing max_connections |

### Manual Monitoring

```python
from cn_commerce_base import ConnectionPoolMonitor

monitor = ConnectionPoolMonitor(max_connections=20)

# Record connection lifecycle
monitor.record_acquire(latency_ms=5.2)
# ... use connection ...
monitor.record_release()

# Reset metrics
monitor.reset()
```

## Integration with Health Check

The `health_check()` method includes both pool and metrics data:

```python
result = await client.health_check()
# {
#   "configured": true,
#   "has_token": true,
#   "api_reachable": true,
#   "metrics": { ... },          # API endpoint metrics
#   "pool": {                    # Connection pool status
#     "status": "healthy",
#     "utilization": 0.1,
#     ...
#   }
# }
```
