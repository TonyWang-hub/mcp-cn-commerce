# Async Request Queue & Connection Pool

This document describes the connection reuse and async request queue features added to `shared/cn_commerce_base.py`.

## Connection Pool

The `ConnectionPool` class manages HTTP connections with connection reuse, health checks, and optional HTTP/2 support.

### Features

- **HTTP/2 Support**: Enable with `ConnectionPoolConfig(http2=True)` for multiplexed connections.
- **Connection Reuse**: Acquire/release pattern reuses existing connections, avoiding repeated TLS handshakes.
- **Health Checks**: Periodic background health checks with automatic reconnection.
- **Statistics**: Track connection reuse ratio, health check results, and connection lifecycle metrics.

### Basic Usage

```python
from cn_commerce_base import ConnectionPool, ConnectionPoolConfig

# Create a pool with HTTP/2 and custom limits
config = ConnectionPoolConfig(
    max_connections=20,
    max_keepalive_connections=10,
    keepalive_expiry=60.0,
    http2=True,
    health_check_interval=30.0,
    health_check_url="https://api.example.com/health",
)
pool = ConnectionPool(config)

# Acquire a client (reuses existing if healthy)
client = await pool.acquire()
response = await client.get("https://api.example.com/data")

# Check connection health
is_healthy = await pool.health_check()

# View pool statistics
stats = pool.get_stats()
print(f"Reuse ratio: {stats.reuse_ratio:.1%}")
print(f"Health checks passed: {stats.health_checks_passed}")

# Start background health monitoring
pool.start_health_monitor()

# Clean up
await pool.close()
```

### Configuration

| Parameter | Default | Description |
|---|---|---|
| `max_connections` | 20 | Maximum total connections in the pool |
| `max_keepalive_connections` | 10 | Maximum idle keep-alive connections |
| `keepalive_expiry` | 60.0 | Seconds before idle connections are closed |
| `connect_timeout` | 10.0 | Timeout for establishing new connections |
| `http2` | False | Enable HTTP/2 protocol support |
| `health_check_interval` | 30.0 | Seconds between background health checks (0 = disabled) |
| `health_check_timeout` | 5.0 | Timeout for health check probes |
| `health_check_url` | "" | URL to probe (empty = skip probe, just check client state) |

### Statistics

`ConnectionPoolStats` tracks:

- `connections_reused` / `connections_created` / `connections_closed`
- `reuse_ratio` (property): fraction of requests that reused an existing connection
- `health_checks_passed` / `health_checks_failed`
- `active_connections` / `idle_connections`
- `avg_connection_age_ms`

## Async Request Queue

The `AsyncRequestQueue` provides priority-based request queuing with concurrent workers.

### Features

- **Priority Levels**: CRITICAL (0) > HIGH (1) > NORMAL (2) > LOW (3)
- **FIFO Within Priority**: Requests at the same priority are processed in order.
- **Concurrent Workers**: Configurable number of worker tasks (1-20).
- **Queue Size Limit**: Optional cap on queue depth.
- **Monitoring**: Detailed statistics including wait times, error counts, and priority distribution.

### Basic Usage

```python
from cn_commerce_base import AsyncRequestQueue, QueuePriority

queue = AsyncRequestQueue(max_workers=5)

# Set the processor function
async def handle_request(method, path, params, data):
    # Your API call logic here
    return {"result": "ok"}

queue.set_processor(handle_request)

# Enqueue and wait for result
result = await queue.enqueue(
    "GET",
    "/api/orders",
    params={"page": 1},
    priority=QueuePriority.HIGH,
)

# Or enqueue without waiting (returns a Future)
future = queue.enqueue_nowait(
    "POST",
    "/api/orders",
    data={"item_id": 123},
    priority=QueuePriority.CRITICAL,
)
# ... do other work ...
result = await future

# View queue statistics
stats = queue.get_stats()
print(f"Depth: {stats.current_depth}")
print(f"Processed: {stats.total_processed}")
print(f"Avg wait: {stats.avg_wait_time_ms:.1f}ms")

# Clean up
await queue.close()
```

### Priority Levels

| Level | Value | Use Case |
|---|---|---|
| `QueuePriority.CRITICAL` | 0 | Payment callbacks, error recovery |
| `QueuePriority.HIGH` | 1 | Order creation, inventory updates |
| `QueuePriority.NORMAL` | 2 | Standard API calls (default) |
| `QueuePriority.LOW` | 3 | Analytics, background sync |

### Queue Size Limits

```python
# Limit queue to 100 items (raises RuntimeError when full)
queue = AsyncRequestQueue(max_workers=5, max_queue_size=100)
```

### Statistics

`AsyncQueueStats` tracks:

- `total_enqueued` / `total_processed` / `total_failed` / `total_cancelled`
- `current_depth` / `max_depth`
- `avg_wait_time_ms`: average time requests spend in the queue
- `priority_counts`: number of requests per priority level
- `processing_errors`: error counts grouped by exception type

## Integration with CommerceMCPBase

Both features can be used alongside the existing `CommerceMCPBase` class:

```python
from cn_commerce_base import (
    CommerceMCPBase,
    ConnectionPool,
    ConnectionPoolConfig,
    AsyncRequestQueue,
    QueuePriority,
)

class MyPlatformClient(CommerceMCPBase):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.pool = ConnectionPool(ConnectionPoolConfig(http2=True))
        self.queue = AsyncRequestQueue(max_workers=3)
        self.queue.set_processor(self._process_request)

    async def _process_request(self, method, path, params, data):
        client = await self.pool.acquire()
        return await self._request(method, path, params=params, data=data)

    async def close(self):
        await self.queue.close()
        await self.pool.close()
        await super().close()
```
