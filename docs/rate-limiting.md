# Rate Limiting Configuration

This document describes the rate limiting system in mcp-cn-commerce, which helps prevent API throttling across all supported e-commerce platforms.

## Overview

The rate limiting system provides:

- **Per-platform configuration**: Different rate limits for each e-commerce platform
- **Per-endpoint configuration**: Fine-grained control over individual API endpoints
- **Dynamic adjustment**: Rate limits can be changed at runtime without restarting
- **Statistics and monitoring**: Track throttling events, wait times, and request counts
- **Burst control**: Configure burst sizes for handling traffic spikes

## Architecture

```
RateLimitConfig
  └── PlatformRateLimitConfig (per platform)
        └── EndpointRateLimit (per endpoint)

ConfigurableRateLimiter
  ├── RateLimitConfig (configuration)
  └── RateLimitStats (monitoring)
```

## Quick Start

### Basic Usage

```python
from cn_commerce_base import (
    RateLimitConfig,
    PlatformRateLimitConfig,
    EndpointRateLimit,
    ConfigurableRateLimiter,
)

# Create configuration
config = RateLimitConfig(
    default_requests_per_second=10.0,
    platforms={
        "OCEANENGINE": PlatformRateLimitConfig(
            platform="OCEANENGINE",
            default_requests_per_second=5.0,
        ),
        "TAOBAO": PlatformRateLimitConfig(
            platform="TAOBAO",
            default_requests_per_second=20.0,
        ),
    },
)

# Create rate limiter
limiter = ConfigurableRateLimiter(config)

# Use in requests
await limiter.acquire("OCEANENGINE", "/api/order/search")
```

### Per-Endpoint Configuration

```python
config = RateLimitConfig(
    platforms={
        "OCEANENGINE": PlatformRateLimitConfig(
            platform="OCEANENGINE",
            default_requests_per_second=10.0,
            endpoints={
                "/api/order/search": EndpointRateLimit(
                    endpoint="/api/order/search",
                    requests_per_second=2.0,  # Slower for heavy endpoints
                    burst_size=5,
                ),
                "/api/product/detail": EndpointRateLimit(
                    endpoint="/api/product/detail",
                    requests_per_second=20.0,  # Faster for lightweight endpoints
                ),
            },
        ),
    },
)
```

### Dynamic Adjustment

Rate limits can be adjusted at runtime:

```python
# Update an entire platform's configuration
limiter.update_platform_config(
    "OCEANENGINE",
    PlatformRateLimitConfig(
        platform="OCEANENGINE",
        default_requests_per_second=15.0,  # Increased from 5.0
    ),
)

# Update a single endpoint's rate limit
limiter.update_endpoint_limit(
    platform="OCEANENGINE",
    endpoint="/api/order/search",
    requests_per_second=5.0,  # Increased from 2.0
)
```

### Monitoring and Statistics

```python
# Get statistics summary
summary = limiter.get_stats_summary()

# Statistics structure:
# {
#     "config": { ... },
#     "stats": {
#         "global": {
#             "total_requests": 150,
#             "total_throttled": 12,
#             "throttle_rate": 0.08,
#             "total_wait_time_ms": 2400.5,
#             "avg_wait_time_ms": 200.04,
#         },
#         "platforms": {
#             "OCEANENGINE": {
#                 "requests": 100,
#                 "throttled": 10,
#                 "throttle_rate": 0.1,
#                 "wait_time_ms": 2000.0,
#             },
#         },
#         "endpoints": {
#             "OCEANENGINE:/api/order/search": {
#                 "requests": 50,
#                 "throttled": 8,
#                 "throttle_rate": 0.16,
#                 "wait_time_ms": 1600.0,
#             },
#         },
#     },
# }

# Reset statistics
limiter.reset_stats()
```

## Configuration Reference

### RateLimitConfig

Top-level configuration for the rate limiting system.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `platforms` | `dict[str, PlatformRateLimitConfig]` | `{}` | Per-platform configurations |
| `default_requests_per_second` | `float` | `10.0` | Global default rate limit |
| `default_burst_size` | `int` | `1` | Global default burst size |
| `enabled` | `bool` | `True` | Global toggle for rate limiting |

### PlatformRateLimitConfig

Platform-specific rate limit configuration.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `platform` | `str` | (required) | Platform name |
| `default_requests_per_second` | `float` | `10.0` | Default rate limit for this platform |
| `endpoints` | `dict[str, EndpointRateLimit]` | `{}` | Per-endpoint overrides |
| `burst_size` | `int` | `1` | Default burst size |
| `enabled` | `bool` | `True` | Whether rate limiting is enabled |

### EndpointRateLimit

Endpoint-specific rate limit configuration.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `endpoint` | `str` | (required) | API endpoint path |
| `requests_per_second` | `float` | `10.0` | Maximum requests per second |
| `burst_size` | `int` | `1` | Maximum burst size |
| `cooldown_seconds` | `float` | `0.0` | Cooldown after hitting limit |

## Serialization

Configuration can be serialized to and from dictionaries for persistence:

```python
# Export to dict (JSON-serializable)
config_dict = config.to_dict()

# Import from dict
config = RateLimitConfig.from_dict(config_dict)
```

## Platform-Specific Defaults

Different platforms have different API rate limits. Here are recommended configurations:

| Platform | Recommended RPS | Notes |
|----------|----------------|-------|
| OCEANENGINE | 5-10 | Qianchuan API has strict limits |
| TAOBAO | 10-20 | Varies by API level |
| DOUDIAN | 5-15 | Douyin e-commerce API |
| JINGDONG | 10-20 | JD Open Platform |
| PINDUODUO | 5-10 | PDD API limits |
| KUAISHOU | 5-10 | Kuaishou e-commerce API |
| XIAOHONGSHU | 5-10 | Xiaohongshu API |
| WEIXIN_STORE | 10-20 | WeChat Store API |

## Best Practices

1. **Start conservative**: Begin with lower rate limits and increase based on observed API behavior
2. **Monitor throttle rate**: Use `get_stats_summary()` to track throttling patterns
3. **Configure per-endpoint**: Heavy operations (search, batch) should have lower limits than lightweight ones (detail, status)
4. **Use dynamic adjustment**: Adjust limits based on time of day or API response patterns
5. **Reset stats periodically**: Clear statistics to track current session performance
