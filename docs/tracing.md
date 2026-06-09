# Request Tracing

mcp-cn-commerce records a lightweight span trace for every platform API call.
Tracing is **enabled by default** -- there is nothing to turn on.

## What's wired in (always on)

Every `CommerceMCPBase` instance creates a `RequestTracer` named after its class
(e.g. `"JDMCP"`). On every `_request()` call the base:

1. Starts one span (`"<METHOD> <path>"`, e.g. `"GET /api/orders"`) covering the
   whole logical request, including any retries.
2. Finishes the span with status `"ok"` on success or `"error"` on failure.

The trace summary is surfaced two ways:

- **In code:** `client.get_trace_summary()`.
- **As an MCP tool:** every platform server registers a `get_traces` tool
  (via `register_common_tools`) that returns the same summary as JSON.

```python
from shared.cn_commerce_base import CommerceMCPBase

client = CommerceMCPBase(app_key="...", app_secret="...", access_token="...")

# Spans are created automatically on each request.
await client._request("GET", "/api/orders", params={"page": "1"})

summary = client.get_trace_summary()
print(summary)
# {
#   "trace_id": "e78ca20649b14e4e94aa4b15eaf35995",
#   "span_count": 1,
#   "active_span_count": 0,
#   "total_duration_ms": 101.13,
#   "root_span": "GET /api/orders",
#   "status": "ok",            # "error" if any span failed
#   "service_name": "CommerceMCPBase"
# }
```

A runnable, offline demo is in
[`examples/best-practices/observability_demo.py`](../examples/best-practices/observability_demo.py).

### Trace summary fields

| Field | Type | Description |
|---|---|---|
| `trace_id` | `str` | ID of the first recorded trace |
| `span_count` | `int` | Total spans recorded so far |
| `active_span_count` | `int` | Spans not yet finished |
| `total_duration_ms` | `float` | Sum of finished span durations |
| `root_span` | `str` | Name of the first root (parentless) span |
| `status` | `str` | `"error"` if any span errored, else `"ok"` |
| `service_name` | `str` | Tracer service name (the client class name) |

## Direct access to the tracer

The underlying tracer is available as `client._tracer` for callers that want raw
span access:

```python
tracer = client._tracer

tracer.get_spans()         # list[TraceSpan]  -- all recorded spans (copy)
tracer.get_active_spans()  # list[TraceSpan]  -- unfinished spans
tracer.get_stats()         # {"service_name", "total_spans", "active_spans", "current_trace_id"}
tracer.clear()             # drop all spans (e.g. between logical operations)
```

## Creating custom spans

`RequestTracer` can be used standalone to trace your own operations, with
optional parent/child relationships.

```python
from shared.cn_commerce_base import RequestTracer

tracer = RequestTracer(service_name="order-service")

# Root span
root = tracer.start_span("fetch_all_orders", attributes={"shop_id": "123"})

# Child span -- pass the parent to inherit its trace_id
child = tracer.start_span("api_call", parent=root, attributes={"method": "GET"})
child.set_attribute("page", 1)
child.add_event("response_received", {"status_code": 200})
tracer.finish_span(child, status="ok")

tracer.finish_span(root, status="ok")

print(tracer.get_trace_summary())
```

### TraceSpan

Each span exposes:

| Member | Description |
|---|---|
| `span_id` / `trace_id` / `parent_id` | Identity (auto-generated) |
| `name` | Span name |
| `start_time` / `end_time` / `duration_ms` | Timing (ms once finished) |
| `status` | `"unset"`, `"ok"`, or `"error"` |
| `attributes` | `dict` of key/value metadata |
| `events` | List of timestamped events |
| `set_attribute(key, value)` | Add/update an attribute |
| `add_event(name, attributes=None)` | Append a timestamped event |
| `finish(status="ok")` | Mark the span finished |
| `is_active` | `True` until the span is finished |
| `to_dict()` | JSON-serializable representation |

### Error spans

Mark a span as errored when an operation fails:

```python
span = tracer.start_span("api_call")
try:
    result = await client._request("GET", "/api/orders")
    tracer.finish_span(span, status="ok")
except Exception as exc:
    span.set_attribute("error.type", type(exc).__name__)
    tracer.finish_span(span, status="error")
    raise
```

> Note: the tracer is an in-process span recorder. It does not propagate
> context across HTTP boundaries or export to an external collector
> (OpenTelemetry/Jaeger). To ship traces externally, periodically read
> `tracer.get_spans()` (each has `.to_dict()`) and forward them yourself.
