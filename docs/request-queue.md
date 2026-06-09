# Request Retry Queue & Deduplication

The `RetryRequestQueue` and `RequestDeduplicator` classes provide robust request retry management and duplicate request prevention for e-commerce API calls.

## Overview

When interacting with e-commerce platform APIs, two common challenges arise:

1. **Transient failures**: Network timeouts, rate limits, and server errors can cause requests to fail temporarily.
2. **Duplicate requests**: Concurrent callers may issue identical API calls, wasting quota and potentially causing side effects.

This module addresses both issues with:

- **RetryRequestQueue**: A managed queue that schedules failed requests for automatic retry with exponential backoff.
- **RequestDeduplicator**: A content-based deduplication layer that prevents identical requests within a configurable time window.

## RetryRequestQueue

### Basic Usage

```python
from cn_commerce_base import RetryRequestQueue, RetryQueueConfig

# Create a queue with custom configuration
config = RetryQueueConfig(
    max_retries=3,
    base_delay=1.0,
    max_delay=60.0,
    dedup_window=30.0,  # 30-second dedup window
)
queue = RetryRequestQueue(config)

# Enqueue a failed request for retry
item = await queue.enqueue(
    method="GET",
    path="/api/order/search",
    params={"order_id": "12345"},
    platform="TAOBAO",
    error="Connection timeout",
)

# Process the queue with your request handler
async def my_request_handler(method, path, params, data):
    return await client._request(method, path, params=params, data=data)

results = await queue.process(my_request_handler)
```

### Auto-Processing

For hands-free retry management, enable automatic background processing:

```python
queue = RetryRequestQueue(RetryQueueConfig(
    auto_process=True,
    process_interval=5.0,  # Process every 5 seconds
))

# Start the background task
task = queue.start_auto_process(my_request_handler)

# Later, stop it
queue.stop_auto_process()
```

### Queue Management

```python
# View pending items without removing them
pending = queue.peek()

# Remove a specific item
queue.remove(request_id)

# Drain all items
items = queue.drain()

# Clean up expired items
expired_count = queue.cleanup_expired()

# Get queue statistics
stats = queue.get_stats()
```

### Retry Lifecycle

Each queue item goes through these states:

1. **pending**: Waiting for the next retry time.
2. **in_flight**: Currently being retried.
3. **succeeded**: Retry completed successfully.
4. **failed**: All retries exhausted; permanent failure.

```python
item = await queue.enqueue(method="GET", path="/api/data", error="timeout")
assert item.status == "pending"

# After processing succeeds
queue.complete(item.request_id, success=True)
# item.status is now "succeeded"
```

## RequestDeduplicator

### Basic Usage

```python
from cn_commerce_base import RequestDeduplicator

dedup = RequestDeduplicator(window_seconds=30.0)

# Recommended: single-call API
if dedup.check_and_record("GET", "/api/order", params={"id": "123"}):
    print("Duplicate request, skipping")
else:
    result = await client._request("GET", "/api/order", params={"id": "123"})
```

### Manual Key Management

For more control, compute and manage keys manually:

```python
dedup = RequestDeduplicator(window_seconds=60.0)

key = dedup.compute_key("POST", "/api/order/create", data={"item_id": "456"})

if dedup.is_duplicate(key):
    # Skip duplicate
    pass
else:
    dedup.record(key)
    # Make the request
    result = await client._request("POST", "/api/order/create", data={"item_id": "456"})
```

### Dedup Window Configuration

```python
# Short window for high-frequency endpoints
dedup = RequestDeduplicator(window_seconds=5.0)

# Longer window for idempotent operations
dedup = RequestDeduplicator(window_seconds=120.0)

# Update window dynamically
dedup.window_seconds = 30.0
```

### Statistics and Maintenance

```python
# Get dedup statistics
stats = dedup.get_stats()
print(f"Dedup rate: {stats['dedup_rate']:.2%}")
print(f"Active hashes: {stats['active_hashes']}")

# Clean up expired hashes
removed = dedup.cleanup()

# Invalidate specific or all entries
dedup.invalidate(key="abc123")
dedup.invalidate()  # Clear all

# Reset statistics
dedup.reset_stats()
```

## Integration with RetryRequestQueue

The `RetryRequestQueue` has built-in deduplication. When you enqueue a request, it automatically checks for duplicates within the configured `dedup_window`:

```python
config = RetryQueueConfig(dedup_window=30.0)
queue = RetryRequestQueue(config)

# First call: enqueued
item1 = await queue.enqueue(method="GET", path="/api/order", params={"id": "1"})
assert item1 is not None

# Duplicate within window: deduplicated
item2 = await queue.enqueue(method="GET", path="/api/order", params={"id": "1"})
assert item2 is None  # Deduplicated

# Force bypass dedup
item3 = await queue.enqueue(
    method="GET", path="/api/order", params={"id": "1"}, force=True
)
assert item3 is not None  # Enqueued despite duplicate
```

## Configuration Reference

### RetryQueueConfig

| Attribute | Type | Default | Description |
|---|---|---|---|
| `max_queue_size` | `int` | `1000` | Maximum items in the queue |
| `max_retries` | `int` | `3` | Default max retry attempts per item |
| `base_delay` | `float` | `1.0` | Base delay for exponential backoff (seconds) |
| `max_delay` | `float` | `60.0` | Maximum delay cap (seconds) |
| `jitter` | `bool` | `True` | Add random jitter to delays |
| `cleanup_interval` | `float` | `60.0` | Seconds between expired item cleanup |
| `item_ttl` | `float` | `300.0` | Max time-to-live for queue items (seconds) |
| `auto_process` | `bool` | `False` | Enable background auto-processing |
| `process_interval` | `float` | `5.0` | Seconds between auto-process cycles |
| `dedup_window` | `float` | `30.0` | Dedup window (seconds, 0 = disabled) |

### RetryQueueItem

| Attribute | Type | Default | Description |
|---|---|---|---|
| `request_id` | `str` | (auto-generated UUID) | Unique item identifier |
| `method` | `str` | `""` | HTTP method |
| `path` | `str` | `""` | API endpoint path |
| `params` | `dict` | `{}` | Query parameters |
| `data` | `dict` | `{}` | Request body |
| `created_at` | `float` | (auto-set) | Creation timestamp |
| `retry_count` | `int` | `0` | Current retry count |
| `max_retries` | `int` | `3` | Max retries for this item |
| `next_retry_at` | `float` | (auto-set) | Next retry timestamp |
| `last_error` | `str` | `""` | Most recent error message |
| `status` | `str` | `"pending"` | Current status |
| `platform` | `str` | `""` | Platform identifier |

## Thread Safety

Both `RetryRequestQueue` and `RequestDeduplicator` use internal threading locks and are safe for concurrent access from multiple async tasks. The `asyncio.Task` management methods (`start_auto_process`, `stop_auto_process`) should be called from the async event loop.

## See Also

- [Rate Limiting](rate-limiting.md) -- API rate limit management
- [Health Check](health-check.md) -- Health check and monitoring
- [Batch Operations](batch-operations.md) -- Concurrent batch requests
