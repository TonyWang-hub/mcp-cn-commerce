# Request Priority & Dynamic Rate Limiting

## Overview

The request priority system allows you to classify API requests by importance and
ensure that high-priority operations are served first, even under heavy load.
Combined with dynamic rate limiting, you can build self-tuning e-commerce
integrations that adapt to platform throttling in real time.

## Status: opt-in

Every `CommerceMCPBase` instance already owns a `PriorityScheduler` and a
`ConfigurableRateLimiter` (accessible via `client.priority_scheduler` and
`client.configurable_limiter`). However, the **plain `_request()` path does not
go through the priority scheduler** -- to get priority-aware dispatch you must
explicitly call `client.prioritized_request(...)` (shown
[below](#using-priority-with-commercemcpbase)). All the APIs on this page are
reachable today; none of them are exposed as MCP tools.

## Request Priority Levels

Four priority levels are available, ordered from highest to lowest:

| Priority   | Weight | Use Cases                                  |
|------------|--------|--------------------------------------------|
| `CRITICAL` | 0      | Payment callbacks, order confirmations     |
| `HIGH`     | 1      | Order creation, inventory updates          |
| `NORMAL`   | 2      | Standard product queries, listing requests |
| `LOW`      | 3      | Report generation, bulk data sync          |

```python
from cn_commerce_base import RequestPriority, PrioritizedRequest

request = PrioritizedRequest(
    priority=RequestPriority.HIGH,
    method="POST",
    path="/api/order/create",
    data={"product_id": "SKU-001", "quantity": 1},
)
```

## Priority Queue

The `PriorityQueue` is a thread-safe, heap-backed queue that always dequeues the
highest-priority item first.  Requests with equal priority are served in FIFO
order.

```python
from cn_commerce_base import PriorityQueue, PrioritizedRequest, RequestPriority

pq = PriorityQueue(max_size=5000)

pq.enqueue(PrioritizedRequest(priority=RequestPriority.LOW, path="/report"))
pq.enqueue(PrioritizedRequest(priority=RequestPriority.HIGH, path="/order"))
pq.enqueue(PrioritizedRequest(priority=RequestPriority.CRITICAL, path="/payment"))

next_request = pq.dequeue()  # Returns the CRITICAL payment request
```

### Queue Operations

| Method                         | Description                                    |
|--------------------------------|------------------------------------------------|
| `enqueue(request)`             | Add a request to the queue                     |
| `dequeue()`                    | Remove and return the highest-priority request |
| `peek()`                       | View the next request without removing it      |
| `clear()`                      | Remove all items                               |
| `get_priority_distribution()`  | Count of requests per priority level           |

### Properties

| Property    | Description                    |
|-------------|--------------------------------|
| `size`      | Current number of items        |
| `is_empty`  | Whether the queue is empty     |

## Priority Scheduler

The `PriorityScheduler` combines a priority queue with a rate limiter to provide
end-to-end priority-aware request scheduling.

```python
from cn_commerce_base import (
    PriorityScheduler,
    ConfigurableRateLimiter,
    RateLimitConfig,
    PrioritizedRequest,
    RequestPriority,
)

# Create with rate limiting
config = RateLimitConfig(default_requests_per_second=10.0)
limiter = ConfigurableRateLimiter(config)
scheduler = PriorityScheduler(rate_limiter=limiter)

# Enqueue requests
scheduler.enqueue(PrioritizedRequest(
    priority=RequestPriority.HIGH,
    method="POST",
    path="/api/order",
    platform="OCEANENGINE",
))

# Or use schedule_and_execute for immediate dispatch
result = await scheduler.schedule_and_execute(
    request=PrioritizedRequest(
        priority=RequestPriority.CRITICAL,
        method="POST",
        path="/api/payment/callback",
        platform="OCEANENGINE",
    ),
    execute_fn=lambda r: client._request(r.method, r.path, params=r.params, data=r.data),
)
```

### Scheduler Stats

```python
stats = scheduler.get_stats_summary()
# {
#     "queue_size": 5,
#     "queue_distribution": {"high": 2, "normal": 3},
#     "stats": {
#         "total_dispatched": 100,
#         "by_priority": {"critical": 10, "high": 30, "normal": 50, "low": 10},
#         "total_delayed": 25,
#         "total_reordered": 8,
#         "avg_queue_time_ms": 12.5,
#         "max_queue_time_ms": 85.0,
#     }
# }
```

## Using Priority with CommerceMCPBase

The `CommerceMCPBase` class integrates priority scheduling and dynamic rate
limiting out of the box.

```python
from cn_commerce_base import CommerceMCPBase, RateLimitConfig, RequestPriority

# Create with custom rate limits
config = RateLimitConfig(default_requests_per_second=5.0)
client = CommerceMCPBase(
    app_key="your_key",
    app_secret="your_secret",
    rate_limit_config=config,
)

# Priority-aware request
result = await client.prioritized_request(
    method="POST",
    path="/api/order/create",
    priority=RequestPriority.HIGH,
    data={"product_id": "SKU-001"},
)

# Check priority stats
print(client.get_priority_stats())

# Check rate limit stats
print(client.get_rate_limit_stats())
```

## Dynamic Rate Limiting

### Manual Adjustment

Adjust rate limits at runtime without restarting:

```python
# Adjust platform-level RPS
client.configurable_limiter.set_platform_rps("OCEANENGINE", 20.0)

# Adjust endpoint-level RPS
client.configurable_limiter.set_endpoint_rps("OCEANENGINE", "/api/order/search", 2.0)

# Enable/disable a platform
client.configurable_limiter.enable_platform("OCEANENGINE")
client.configurable_limiter.disable_platform("OCEANENGINE")
```

### Auto-Adjustment

The auto-adjustment feature analyzes throttle statistics and tunes rate limits
automatically:

```python
# Run auto-adjustment (typically on a timer)
adjustments = client.auto_adjust_rate_limits(
    throttle_threshold=0.3,    # Scale down when >30% requests throttled
    scale_down_factor=0.8,     # Reduce RPS by 20%
    scale_up_factor=1.1,       # Increase RPS by 10%
    min_rps=0.5,               # Never go below 0.5 RPS
    max_rps=100.0,             # Never exceed 100 RPS
)

print(adjustments)
# {
#     "platforms": {},
#     "endpoints": {
#         "OCEANENGINE:/api/order/search": {
#             "action": "scale_down",
#             "old_rps": 10.0,
#             "new_rps": 8.0,
#             "throttle_rate": 0.45,
#         }
#     }
# }
```

### Auto-Adjustment Logic

- **Scale down**: When a platform/endpoint's throttle rate exceeds the threshold,
  its RPS is reduced by `scale_down_factor`.
- **Scale up**: When the throttle rate is below 30% of the threshold *and* there
  are enough data points (20+ requests), RPS is increased by `scale_up_factor`.
- **Minimum data**: At least 5 requests are needed before any adjustment is made.

## API Reference

### `RequestPriority`

Enum with values: `CRITICAL`, `HIGH`, `NORMAL`, `LOW`.

### `PrioritizedRequest`

| Field        | Type              | Default           | Description                       |
|--------------|-------------------|-------------------|-----------------------------------|
| `priority`   | `RequestPriority` | `NORMAL`          | Priority level                    |
| `method`     | `str`             | `""`              | HTTP method                       |
| `path`       | `str`             | `""`              | API endpoint path                 |
| `params`     | `dict`            | `{}`              | Query parameters                  |
| `data`       | `dict`            | `{}`              | Request body                      |
| `request_id` | `str`             | `""`              | Caller-assigned identifier        |
| `created_at` | `float`           | `time.time()`     | Enqueue timestamp                 |
| `platform`   | `str`             | `""`              | Platform identifier               |
| `metadata`   | `dict`            | `{}`              | Arbitrary metadata                |

### `PriorityQueue(max_size=10000)`

| Method/Property              | Returns                         |
|------------------------------|---------------------------------|
| `enqueue(request)`           | `None`                          |
| `dequeue()`                  | `PrioritizedRequest | None`     |
| `peek()`                     | `PrioritizedRequest | None`     |
| `clear()`                    | `None`                          |
| `get_priority_distribution()`| `dict[str, int]`                |
| `size`                       | `int`                           |
| `is_empty`                   | `bool`                          |

### `PriorityScheduler(rate_limiter=None, max_queue_size=10000)`

| Method/Property                       | Returns              |
|---------------------------------------|----------------------|
| `enqueue(request)`                    | `None`               |
| `dequeue()`                           | `PrioritizedRequest` |
| `schedule_and_execute(request, fn)`   | `Any`                |
| `get_queue_distribution()`            | `dict[str, int]`     |
| `get_stats_summary()`                 | `dict[str, Any]`     |
| `reset_stats()`                       | `None`               |
| `clear_queue()`                       | `None`               |

### `ConfigurableRateLimiter` (Dynamic Methods)

| Method                                     | Description                             |
|--------------------------------------------|-----------------------------------------|
| `set_platform_rps(platform, rps)`          | Set RPS for an entire platform          |
| `set_endpoint_rps(platform, endpoint, rps)`| Set RPS for a specific endpoint         |
| `enable_platform(platform)`                | Enable rate limiting for a platform     |
| `disable_platform(platform)`               | Disable rate limiting for a platform    |
| `auto_adjust_from_stats(**kwargs)`         | Auto-tune RPS based on throttle stats   |
