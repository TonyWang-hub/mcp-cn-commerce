# Request Result Cache & Response Decompression

This document describes the request result caching and response decompression features available in `mcp-cn-commerce`.

## Table of Contents

- [Request Result Cache](#request-result-cache)
  - [Overview](#overview)
  - [Configuration](#configuration)
  - [Usage](#usage)
  - [Cache Invalidation](#cache-invalidation)
  - [Statistics](#cache-statistics)
- [Response Decompression](#response-decompression)
  - [Overview](#overview-1)
  - [Supported Encodings](#supported-encodings)
  - [Usage](#usage-1)
  - [Statistics](#decompression-statistics)
- [Integration Example](#integration-example)

---

## Request Result Cache

### Overview

The `RequestResultCache` provides an LRU + TTL cache for API request results. When enabled, identical GET requests return cached responses without hitting the API, reducing latency and API call volume.

Key features:
- **LRU eviction**: When the cache reaches `max_size`, the least-recently-used entry is evicted.
- **Per-entry TTL**: Each cached entry expires after a configurable duration.
- **Thread-safe**: All operations are protected by a lock for concurrent access.
- **Deterministic cache keys**: Generated from method + path + params + data using SHA-256.

### Configuration

Create a `RequestCacheConfig` and pass it when initializing the client:

```python
from shared.cn_commerce_base import (
    RequestCacheConfig,
    CommerceMCPBase,
)

cache_config = RequestCacheConfig(
    enabled=True,               # Enable/disable caching
    max_size=512,               # Max cached entries (LRU eviction)
    default_ttl_seconds=300.0,  # Default TTL (5 minutes)
    cacheable_methods=("GET",), # HTTP methods to cache
)

client = CommerceMCPBase(
    app_key="...",
    app_secret="...",
    cache_config=cache_config,
)
```

**Parameters:**

| Parameter                | Type              | Default   | Description                                    |
| ------------------------ | ----------------- | --------- | ---------------------------------------------- |
| `enabled`                | `bool`            | `True`    | Whether request result caching is active        |
| `max_size`               | `int`             | `512`     | Maximum number of cached entries                |
| `default_ttl_seconds`    | `float`           | `300.0`   | Default time-to-live for cached entries         |
| `cacheable_methods`      | `tuple[str, ...]` | `("GET",)`| HTTP methods eligible for caching               |
| `exclude_error_responses`| `bool`            | `True`    | Skip caching error responses                    |

### Usage

Result caching is integrated into `CommerceMCPBase._request()`. When enabled, GET requests automatically check the cache before making an API call, and store successful responses:

```python
# First call -- hits the API
result = await client._request("GET", "/api/products", params={"page": "1"})

# Second identical call -- served from cache
result = await client._request("GET", "/api/products", params={"page": "1"})
```

You can bypass the cache for specific requests:

```python
# Skip cache for this request
result = await client._request("GET", "/api/orders", use_cache=False)

# Override TTL for this specific entry
result = await client._request("GET", "/api/config", cache_ttl=60.0)
```

For standalone use outside `CommerceMCPBase`:

```python
from shared.cn_commerce_base import RequestResultCache, RequestCacheConfig

cache = RequestResultCache(RequestCacheConfig(max_size=256))
key = RequestResultCache.make_key("GET", "/api/products", params={"page": "1"})

cached = cache.get(key)
if cached is None:
    result = await fetch_data()
    cache.set(key, result, ttl_seconds=120)
else:
    result = cached
```

### Cache Invalidation

```python
# Invalidate a specific entry by key
key = RequestResultCache.make_key("GET", "/api/products")
client.invalidate_result_cache(key)

# Invalidate all cached entries
client.invalidate_result_cache()

# Direct cache access
client._result_cache.clear()
client._result_cache.cleanup_expired()  # Remove expired entries only
```

### Cache Statistics

```python
stats = client.get_result_cache_stats()
# {
#     "total_requests": 100,
#     "cache_hits": 75,
#     "cache_misses": 25,
#     "hit_rate": 0.75,
#     "total_stored": 25,
#     "total_evicted": 3,
#     "total_invalidated": 0,
#     "total_bytes_cached": 524288,
#     "current_size": 22,
#     "max_size": 512,
#     "config": { ... },
# }
```

---

## Response Decompression

### Overview

The `ResponseDecompressor` transparently decompresses HTTP response bodies based on the `Content-Encoding` header. This is integrated into `CommerceMCPBase._request()` and works automatically -- no configuration needed.

### Supported Encodings

| Encoding      | Description                    |
| ------------- | ------------------------------ |
| `gzip`        | gzip compression (RFC 1952)    |
| `x-gzip`      | Alias for gzip                 |
| `deflate`     | deflate compression (RFC 1951) |
| `br`          | Brotli (requires `brotli` package) |
| `identity`    | No compression (passthrough)   |

### Usage

Response decompression is automatic in `CommerceMCPBase._request()`. If the API returns a `Content-Encoding: gzip` header, the response body is decompressed before parsing JSON.

For standalone use:

```python
from shared.cn_commerce_base import ResponseDecompressor

decompressor = ResponseDecompressor()

# Decompress a gzip response
body = decompressor.decompress(compressed_bytes, content_encoding="gzip")

# No encoding -- returns as-is
body = decompressor.decompress(plain_bytes, content_encoding="identity")
```

### Decompression Statistics

```python
stats = client.get_decompression_stats()
# {
#     "total_responses": 100,
#     "decompressed_responses": 45,
#     "decompression_rate": 0.45,
#     "total_compressed_bytes": 1048576,
#     "total_decompressed_bytes": 2097152,
#     "bytes_saved": 1048576,
#     "avg_compression_ratio": 2.0,
#     "decompression_errors": 0,
# }
```

---

## Integration Example

Complete example combining all features:

```python
import asyncio
from shared.cn_commerce_base import (
    CommerceMCPBase,
    CompressionConfig,
    CompressionMethod,
    RequestCacheConfig,
)


class MyPlatformClient(CommerceMCPBase):
    BASE_URL = "https://api.example.com"

    def __init__(self) -> None:
        super().__init__(
            app_key="my_key",
            app_secret="my_secret",
            # Request body compression (outgoing)
            compression_config=CompressionConfig(
                method=CompressionMethod.GZIP,
                min_size_bytes=1024,
            ),
            # Result caching
            cache_config=RequestCacheConfig(
                max_size=256,
                default_ttl_seconds=120.0,
            ),
        )
        # Cache warmup tasks
        self.cache_warmer.register(
            platform="MY_PLATFORM",
            cache_key="categories",
            fetch_fn=self._fetch_categories,
            ttl_seconds=600,
        )


    async def _fetch_categories(self):
        return await self._request("GET", "/api/categories")


async def main():
    client = MyPlatformClient()

    # 1. Warm reference data cache
    await client.warmup_cache()

    # 2. Make requests (result cache is automatic)
    products = await client._request("GET", "/api/products", params={"page": "1"})
    products_again = await client._request("GET", "/api/products", params={"page": "1"})
    # ^ Second call served from cache

    # 3. Check all stats
    print("Compression:", client.get_compression_stats())
    print("Decompression:", client.get_decompression_stats())
    print("Result Cache:", client.get_result_cache_stats())

    # 4. Invalidate when data changes
    client.invalidate_result_cache()

    # 5. Cleanup
    await client.close()


asyncio.run(main())
```
