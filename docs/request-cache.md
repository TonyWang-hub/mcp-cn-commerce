# Request Deduplication, Cache Warmup & Compression

This document describes the request-efficiency features that ship in
`shared.cn_commerce_base`: **request deduplication**, **cache warmup**, and
**outgoing request compression**.

> **Scope note.** There is currently no transparent per-request *result* cache or
> response *decompression* layer inside `CommerceMCPBase._request()`. The
> features below are the real, available primitives for avoiding redundant work
> and pre-loading reference data. Deduplication and cache warmup are **opt-in**;
> outgoing compression is configured per client.

## Table of Contents

- [Request Deduplication](#request-deduplication)
- [Cache Warmup](#cache-warmup)
- [Outgoing Request Compression](#outgoing-request-compression)

---

## Request Deduplication

### Overview

`RequestDeduplicator` suppresses identical requests issued within a configurable
time window. It is content-based: the key is a SHA-256 of
`method + path + params + data`. This is useful when several callers (or retries)
would otherwise fire the same call in a short burst.

It is **opt-in** -- the base client does not deduplicate `_request()` calls for
you. You create a deduplicator and consult it before issuing a request.

### Usage

```python
from shared.cn_commerce_base import RequestDeduplicator

dedup = RequestDeduplicator(window_seconds=30.0)

# `check_and_record` returns True if this request was already seen in the window.
if dedup.check_and_record("GET", "/api/order", params={"id": "123"}):
    # Duplicate within the window -- skip the call.
    ...
else:
    result = await client._request("GET", "/api/order", params={"id": "123"})
```

If you need the check and the record as separate steps:

```python
key = dedup.compute_key("GET", "/api/order", params={"id": "123"})
if not dedup.is_duplicate(key):
    result = await client._request("GET", "/api/order", params={"id": "123"})
    dedup.record(key)
```

### Maintenance & statistics

```python
dedup.cleanup()              # drop hashes older than the window; returns count removed
dedup.invalidate()           # clear all tracked hashes
dedup.invalidate(key)        # clear a single key
dedup.window_seconds = 60.0  # adjust the window at runtime

stats = dedup.get_stats()
# {
#   "total_requests": 2,
#   "total_deduplicated": 1,
#   "total_unique": 1,
#   "dedup_rate": 0.5,
#   "dedup_window_seconds": 30.0,
#   "active_hashes": 1,
# }
```

### Built-in dedup in the retry queue

`RetryRequestQueue` (see [request-queue.md](request-queue.md)) has its own
deduplication, controlled by `RetryQueueConfig.dedup_window`. When you `enqueue`
a failed request that matches a recently-enqueued one, it is skipped and
`stats.total_deduplicated` is incremented (pass `force=True` to bypass).

```python
from shared.cn_commerce_base import RetryRequestQueue, RetryQueueConfig

queue = RetryRequestQueue(RetryQueueConfig(dedup_window=30.0))
await queue.enqueue(method="GET", path="/api/order", params={"id": "1"})
await queue.enqueue(method="GET", path="/api/order", params={"id": "1"})  # deduplicated
```

---

## Cache Warmup

### Overview

`CacheWarmer` pre-loads reference data (categories, hot products, etc.) so the
first real request doesn't pay the cold-start cost. Every `CommerceMCPBase`
instance owns one as `client.cache_warmer`, and the base exposes a
`warmup_cache()` convenience.

It is **opt-in** in the sense that nothing is warmed until you register tasks and
trigger a warmup.

### Usage

```python
from shared.cn_commerce_base import CommerceMCPBase


class MyPlatformClient(CommerceMCPBase):
    BASE_URL = "https://api.example.com/"

    def __init__(self) -> None:
        super().__init__(app_key="...", app_secret="...")
        # Register warmup tasks (priority: lower runs first).
        self.cache_warmer.register(
            platform="MY_PLATFORM",
            cache_key="categories",
            fetch_fn=self._fetch_categories,
            priority=0,
            ttl_seconds=600.0,
        )

    async def _fetch_categories(self):
        return await self._request("GET", "/api/categories")


client = MyPlatformClient()

# Warm everything (or pass platforms=[...] to warm a subset).
results = await client.warmup_cache()
for r in results:
    print(r["platform"], r["cache_key"], r["success"], f"{r['latency_ms']}ms")
```

You can also drive the `CacheWarmer` directly:

```python
warmer = client.cache_warmer
await warmer.warmup_all()                 # run all registered tasks
await warmer.warmup_platform("TAOBAO")    # run tasks for one platform
task = warmer.start_scheduled(interval_seconds=300)  # periodic re-warm (asyncio.Task)
warmer.stop_scheduled()
```

---

## Outgoing Request Compression

### Overview

`RequestCompressor` compresses **outgoing POST bodies** before they are sent.
This is configured per client via `compression_config`; the base applies it
inside `_request()` for POST requests whose body exceeds the configured minimum
size.

### Supported methods

| Method (`CompressionMethod`) | Description |
|---|---|
| `NONE` (`"none"`) | No compression (default) |
| `GZIP` (`"gzip"`) | gzip compression |
| `DEFLATE` (`"deflate"`) | deflate compression |
| `AUTO` (`"auto"`) | Pick a method automatically |

### Usage

```python
from shared.cn_commerce_base import (
    CommerceMCPBase,
    CompressionConfig,
    CompressionMethod,
)

client = CommerceMCPBase(
    app_key="...",
    app_secret="...",
    compression_config=CompressionConfig(
        method=CompressionMethod.GZIP,
        min_size_bytes=1024,   # only compress bodies larger than 1 KiB
    ),
)

# POST bodies are now compressed automatically when they exceed min_size_bytes.
await client._request("POST", "/api/batch", data={"items": [...]})
```

### Statistics

```python
stats = client.get_compression_stats()
# {
#   "total_requests": 100,
#   "compressed_requests": 45,
#   "compression_rate": 0.45,
#   "total_original_bytes": 2097152,
#   "total_compressed_bytes": 1048576,
#   "bytes_saved": 1048576,
#   "avg_compression_ratio": 2.0,
# }
```
