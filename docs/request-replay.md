# Request Replay & Debug

mcp-cn-commerce provides built-in request replay and debug capabilities for diagnosing API issues, reproducing bugs, and validating API changes.

## Request Recording

### Basic Usage

Record API requests for later replay:

```python
from cn_commerce_base import RequestRecorder, ReplayConfig

# Create a recorder with default config
recorder = RequestRecorder()

# Record a request
record = recorder.record(
    method="GET",
    path="/api/orders",
    params={"page": 1, "status": "paid"},
    response={"result": [{"id": 1}, {"id": 2}]},
    status_code=200,
    latency_ms=123.4,
    platform="OCEANENGINE",
    tags=["orders", "production"],
)
```

### Configuration

```python
config = ReplayConfig(
    max_records=5000,       # Keep up to 5000 records in memory
    record_responses=True,  # Store response data
    auto_record=False,      # Don't auto-record _request() calls
    replay_delay_ms=100,    # 100ms delay between replays
    match_strategy="exact", # "exact" or "fuzzy"
)
recorder = RequestRecorder(config)
```

### Filtering Records

```python
# Filter by method
get_records = recorder.filter(method="GET")

# Filter by path (substring match)
order_records = recorder.filter(path="/api/orders")

# Filter by platform
oceanengine_records = recorder.filter(platform="OCEANENGINE")

# Filter by tags
prod_records = recorder.filter(tags=["production"])

# Filter by time
recent = recorder.filter(since=time.time() - 3600)  # Last hour
```

### Export & Import

```python
# Export to JSON string
json_str = recorder.export_json()

# Import from JSON string
count = recorder.import_json(json_str)

# Export to file
recorder.export_to_file("recordings/session-001.json")

# Import from file
count = recorder.import_from_file("recordings/session-001.json")
```

## Request Replay

### Basic Replay

```python
from cn_commerce_base import RequestReplayer

replayer = RequestReplayer(recorder)

# Define your execute function
async def execute_request(method, path, params, data):
    return await client._request(method, path, params=params, data=data)

# Replay all recorded requests
results = await replayer.replay_all(execute_fn=execute_request)

for result in results:
    if result["success"]:
        print(f"OK: {result['record_id'][:8]} - {result['latency_ms']}ms")
    else:
        print(f"FAIL: {result['record_id'][:8]} - {result['error']}")
```

### Filtered Replay

```python
# Replay only order-related requests
results = await replayer.replay_filtered(
    execute_fn=execute_request,
    path="/api/orders",
)
```

### Validation Replay

```python
validation = await replayer.validate_replay(execute_fn=execute_request)

print(f"Match rate: {validation['match_rate']:.1%}")
print(f"Matched: {validation['matched']}, Mismatched: {validation['mismatched']}")
```

## Request Tracing

### Basic Tracing

```python
from cn_commerce_base import RequestTracer

tracer = RequestTracer(service_name="order-service")

# Start a root span
root = tracer.start_span("fetch_all_orders")

# Create child spans
child = tracer.start_span("api_call", parent=root)
child.set_attribute("http.method", "GET")
child.finish("ok")

root.finish("ok")

# Get trace summary
summary = tracer.get_trace_summary()
```

### Error Tracing

```python
span = tracer.start_span("api_call")
try:
    result = await client._request("GET", "/api/orders")
    span.finish("ok")
except Exception as e:
    span.set_attribute("error.type", type(e).__name__)
    span.finish("error")
```

## Debug Logging

### Basic Usage

```python
from cn_commerce_base import DebugLogger, DebugLogLevel

debug_log = DebugLogger(level=DebugLogLevel.DEBUG)

debug_log.log(DebugLogLevel.INFO, "Request started", {"method": "GET"})
debug_log.log(DebugLogLevel.ERROR, "Request failed", {"error": "timeout"})

# Filter entries
errors = debug_log.get_entries(level=DebugLogLevel.ERROR)
```

### Dynamic Level Control

```python
debug_log.level = DebugLogLevel.WARN  # Only capture warnings and errors
debug_log.level = DebugLogLevel.TRACE  # Capture everything
```

## Debug Breakpoints

### Conditional Breakpoints

```python
from cn_commerce_base import DebugBreakpointManager

bp_mgr = DebugBreakpointManager()

# Breakpoint that triggers on error status codes
bp_mgr.add_breakpoint(
    name="catch_errors",
    action="log",
    condition=lambda status_code, **kw: status_code >= 400,
)

# Check if breakpoint should trigger
if bp_mgr.should_break(status_code=500):
    print("Breakpoint hit!")
```

### Managing Breakpoints

```python
# Enable/disable breakpoints
bp_mgr.disable_breakpoint(bp.breakpoint_id)
bp_mgr.enable_breakpoint(bp.breakpoint_id)

# Get hit history
hits = bp_mgr.get_hit_history(limit=20)
```

## Statistics & Monitoring

All components provide `get_stats()` methods:

```python
print(recorder.get_stats())   # {"record_count": 42, ...}
print(replayer.get_stats())   # {"total_replayed": 42, ...}
print(tracer.get_stats())     # {"total_spans": 5, ...}
print(debug_log.get_stats())  # {"entry_count": 120, ...}
print(bp_mgr.get_stats())     # {"breakpoint_count": 3, ...}
```
