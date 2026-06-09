# Cache Configuration

This document describes the cache warmup and request compression features available in `mcp-cn-commerce`.

## Table of Contents

- [Cache Warmup](#cache-warmup)
  - [Overview](#overview)
  - [Registering Warmup Tasks](#registering-warmup-tasks)
  - [Startup Warmup](#startup-warmup)
  - [Per-Platform Warmup](#per-platform-warmup)
  - [Scheduled Warmup](#scheduled-warmup)
  - [Cache Access](#cache-access)
  - [Statistics](#warmup-statistics)
- [Request Compression](#request-compression)
  - [Overview](#overview-1)
  - [Compression Methods](#compression-methods)
  - [Configuration](#compression-configuration)
  - [Auto Selection](#auto-selection)
  - [Statistics](#compression-statistics)
- [Integration Example](#integration-example)

---

## Cache Warmup

### Overview

The `CacheWarmer` class provides a way to pre-load frequently accessed data into memory
at startup or on a schedule. This reduces cold-start latency for API calls that depend
on reference data (product categories, shipping methods, platform configs, etc.).

### Registering Warmup Tasks

Register an async fetch function for each data item you want to warm:

```python
from shared.cn_commerce_base import CacheWarmer

warmer = CacheWarmer()

# Register tasks -- lower priority runs first
warmer.register(
    platform="OCEANENGINE",
    cache_key="hot_products",
    fetch_fn=lambda: client.get_hot_products(),
    priority=0,
    ttl_seconds=600,
)

warmer.register(
    platform="TAOBAO",
    cache_key="categories",
    fetch_fn=lambda: client.get_categories(),
    priority=1,
    ttl_seconds=300,
)
```

**Parameters:**

| Parameter     | Type     | Default | Description                                  |
| ------------- | -------- | ------- | -------------------------------------------- |
| `platform`    | `str`    | -       | Platform identifier                          |
| `cache_key`   | `str`    | -       | Key for storing cached data                  |
| `fetch_fn`    | `callable` | -    | Async callable returning data to cache       |
| `priority`    | `int`    | `0`     | Execution order (lower = earlier)            |
| `ttl_seconds` | `float`  | `300`   | How long cached data remains valid           |

### Startup Warmup

Warm all registered tasks at once, typically called during application startup:

```python
results = await warmer.warmup_all()
# results is a list of WarmupResult with success/failure details
```

### Per-Platform Warmup

Warm tasks for a specific platform only:

```python
results = await warmer.warmup_platform("OCEANENGINE")
```

### Scheduled Warmup

Start a background task that periodically re-warms the cache:

```python
# Warm all tasks every 5 minutes
task = warmer.start_scheduled(interval_seconds=300)

# Or warm only specific platforms
task = warmer.start_scheduled(
    interval_seconds=600,
    warmup_platforms=["OCEANENGINE", "TAOBAO"],
)

# Stop when done
warmer.stop_scheduled()
```

The scheduled task runs as an `asyncio.Task` and can be cancelled at any time.

### Cache Access

Retrieve warmed data from the cache:

```python
data = warmer.get_cached("hot_products")
if data is None:
    # Cache miss -- fetch directly
    data = await client.get_hot_products()
```

You can also manually set or invalidate cache entries:

```python
warmer.set_cached("key", value, ttl_seconds=120)
warmer.invalidate("key")       # Remove one entry
warmer.invalidate()             # Clear all entries
```

### Warmup Statistics

```python
stats = warmer.get_stats()
# {
#     "registered_tasks": 2,
#     "cached_keys": ["hot_products", "categories"],
#     "cached_count": 2,
#     "scheduled": True,
#     "history": {"total": 10, "succeeded": 9, "failed": 1},
# }

history = warmer.get_history(limit=20)  # Recent warmup results
```

---

## Request Compression

### Overview

Request compression reduces the size of POST request bodies sent to API endpoints.
This is particularly useful for batch operations or requests with large payloads.

### Compression Methods

| Method    | Description                                            |
| --------- | ------------------------------------------------------ |
| `NONE`    | No compression (default).                              |
| `GZIP`    | gzip compression (RFC 1952). Widely supported.         |
| `DEFLATE` | deflate compression (RFC 1951).                        |
| `AUTO`    | Automatically select based on `Accept-Encoding` header |

### Configuration

Create a `CompressionConfig` and pass it when initializing the client:

```python
from shared.cn_commerce_base import CompressionConfig, CompressionMethod, CommerceMCPBase

config = CompressionConfig(
    method=CompressionMethod.GZIP,
    min_size_bytes=1024,     # Only compress bodies >= 1 KB
    gzip_level=6,            # Compression level 1-9
    include_content_encoding=True,  # Set Content-Encoding header
)

client = CommerceMCPBase(
    app_key="...",
    app_secret="...",
    compression_config=config,
)
```

**Parameters:**

| Parameter               | Type                | Default  | Description                                       |
| ----------------------- | ------------------- | -------- | ------------------------------------------------- |
| `method`                | `CompressionMethod` | `NONE`   | Compression method to use                         |
| `min_size_bytes`        | `int`               | `1024`   | Minimum body size to trigger compression          |
| `gzip_level`            | `int`               | `6`      | gzip/deflate level (1=fast, 9=best compression)   |
| `include_content_encoding` | `bool`           | `True`   | Whether to set the `Content-Encoding` header      |

### Auto Selection

When `CompressionMethod.AUTO` is used, the compressor inspects the server's
`Accept-Encoding` header to determine the best method:

1. If the server accepts `gzip` or `x-gzip`, gzip is used.
2. If the server accepts `deflate`, deflate is used.
3. If neither is advertised, gzip is used as the default.

```python
config = CompressionConfig(method=CompressionMethod.AUTO)
```

### Compression Statistics

```python
stats = client.get_compression_stats()
# {
#     "total_requests": 100,
#     "compressed_requests": 45,
#     "compression_rate": 0.45,
#     "total_original_bytes": 1048576,
#     "total_compressed_bytes": 524288,
#     "bytes_saved": 524288,
#     "avg_compression_ratio": 0.5,
# }
```

---

## Integration Example

Complete example combining cache warmup with request compression:

```python
import asyncio
from shared.cn_commerce_base import (
    CommerceMCPBase,
    CompressionConfig,
    CompressionMethod,
)

class MyPlatformClient(CommerceMCPBase):
    BASE_URL = "https://api.example.com"

    def __init__(self) -> None:
        super().__init__(
            app_key="my_key",
            app_secret="my_secret",
            compression_config=CompressionConfig(
                method=CompressionMethod.AUTO,
                min_size_bytes=512,
            ),
        )
        # Register warmup tasks
        self.cache_warmer.register(
            platform="MY_PLATFORM",
            cache_key="categories",
            fetch_fn=self._fetch_categories,
            ttl_seconds=600,
        )
        self.cache_warmer.register(
            platform="MY_PLATFORM",
            cache_key="config",
            fetch_fn=self._fetch_config,
            ttl_seconds=1200,
        )

    async def _fetch_categories(self):
        return await self._request("GET", "/api/categories")

    async def _fetch_config(self):
        return await self._request("GET", "/api/config")


async def main():
    client = MyPlatformClient()

    # 1. Warm cache at startup
    results = await client.warmup_cache()
    print(f"Warmed {len(results)} items")

    # 2. Start periodic warmup (every 10 minutes)
    client.cache_warmer.start_scheduled(interval_seconds=600)

    # 3. Use cached data
    categories = client.cache_warmer.get_cached("categories")
    if categories is None:
        categories = await client._fetch_categories()

    # 4. Check stats
    print("Compression:", client.get_compression_stats())
    print("Warmup:", client.cache_warmer.get_stats())

    # 5. Cleanup
    client.cache_warmer.stop_scheduled()
    await client.close()

asyncio.run(main())
```
