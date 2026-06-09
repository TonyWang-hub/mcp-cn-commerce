# Batch Operations

Execute multiple API requests concurrently with controlled concurrency and aggregated error handling.

## Overview

Batch operations allow you to send multiple API requests in parallel while respecting rate limits and concurrency constraints. This is useful for scenarios like:

- Fetching multiple orders by ID in one call
- Updating product listings across a store
- Collecting metrics from multiple endpoints

## Core Types

### `BatchRequestItem`

Represents a single request in a batch:

```python
from shared.cn_commerce_base import BatchRequestItem

item = BatchRequestItem(
    method="GET",
    path="/api/orders",
    params={"order_id": "12345"},
    data={},                    # POST body (for POST requests)
    request_id="order-12345",   # Optional tracking ID
)
```

### `BatchResultItem`

Result of a single request:

```python
result.request_id   # Matches the input request_id
result.success      # bool
result.data         # Response dict (None if failed)
result.error        # Exception (None if succeeded)
result.latency_ms   # Request duration in milliseconds
```

### `BatchSummary`

Aggregated results:

```python
summary.total            # Total requests
summary.succeeded        # Successful count
summary.failed           # Failed count
summary.results          # List[BatchResultItem]
summary.total_latency_ms # Wall-clock time for entire batch
summary.error_summary    # {"CommerceAPIError": 2, "httpx.ConnectError": 1}
```

## Usage

### Basic Batch Request

```python
import asyncio
from shared.cn_commerce_base import CommerceMCPBase, BatchRequestItem

async def fetch_orders(client: CommerceMCPBase, order_ids: list[str]):
    requests = [
        BatchRequestItem(
            method="GET",
            path="/api/orders",
            params={"order_id": oid},
            request_id=oid,
        )
        for oid in order_ids
    ]

    summary = await client._batch_request(requests, max_concurrency=5)

    for result in summary.results:
        if result.success:
            print(f"Order {result.request_id}: {result.data}")
        else:
            print(f"Order {result.request_id} failed: {result.error}")

    print(f"Completed: {summary.succeeded}/{summary.total} in {summary.total_latency_ms:.0f}ms")
```

### With Fail-Fast

Stop submitting new requests when the first error occurs:

```python
summary = await client._batch_request(
    requests,
    max_concurrency=3,
    fail_fast=True,
)
```

With `fail_fast=True`, remaining queued requests are still executed but no new ones are submitted after the first failure.

### Concurrency Control

The `max_concurrency` parameter (1-20, default 5) controls how many requests execute simultaneously:

```python
# Conservative - good for rate-limited APIs
summary = await client._batch_request(requests, max_concurrency=2)

# Aggressive - for APIs with generous limits
summary = await client._batch_request(requests, max_concurrency=10)
```

### Error Handling

Errors are captured per-request and aggregated in the summary:

```python
summary = await client._batch_request(requests)

# Check overall success
if summary.failed > 0:
    print(f"{summary.failed} requests failed:")
    for err_type, count in summary.error_summary.items():
        print(f"  {err_type}: {count}")

# Inspect individual failures
for r in summary.results:
    if not r.success:
        if isinstance(r.error, CommerceAPIError):
            print(f"API error {r.error.code}: {r.error.msg}")
        else:
            print(f"Network error: {r.error}")
```

### Aggregating Results Across Batches

Use `_batch_aggregate` to combine results from multiple batch calls:

```python
from shared.cn_commerce_base import BatchResultItem

all_results: list[BatchResultItem] = []
total_ms = 0.0

for chunk in chunked_requests:
    summary = await client._batch_request(chunk)
    all_results.extend(summary.results)
    total_ms += summary.total_latency_ms

combined = CommerceMCPBase._batch_aggregate(all_results, total_ms)
```

## Error Types

| Error | Cause |
|---|---|
| `CommerceAPIError` | Business logic error from the platform API |
| `httpx.ConnectError` | Network connection failed |
| `httpx.TimeoutException` | Request exceeded timeout |
| `httpx.HTTPStatusError` | HTTP 4xx/5xx status code |
| `ValueError` | Invalid request parameters |

## Best Practices

1. **Use `request_id`** - Always set meaningful request IDs for traceability.
2. **Tune concurrency** - Start with `max_concurrency=3-5` and adjust based on platform limits.
3. **Handle partial failures** - Always check `summary.failed` and process errors gracefully.
4. **Respect rate limits** - The base class rate limiter applies per-request; batch concurrency is an additional control.
5. **Avoid large batches** - For 100+ requests, chunk into smaller batches and aggregate results.

## Platform-Specific Notes

Each platform may have its own rate limits and concurrency restrictions. The batch method respects the `RateLimiter` configured on the client instance. Consult platform documentation for specific limits.
