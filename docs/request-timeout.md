# Request Timeout & Cancellation

This document describes the request timeout and cancellation system in mcp-cn-commerce, which provides fine-grained control over API request lifecycles.

## Overview

The timeout and cancellation system provides:

- **Global timeout configuration**: Default timeouts applied to all requests
- **Per-platform timeouts**: Different timeouts for each e-commerce platform
- **Per-endpoint timeouts**: Fine-grained control over individual API endpoints
- **Request cancellation**: Cancel individual requests, batches, or all in-flight requests
- **Cancel callbacks**: Execute cleanup logic when a request is cancelled

## Architecture

```
TimeoutConfig
  └── PlatformTimeoutConfig (per platform)
        └── EndpointTimeout (per endpoint)

RequestCancelManager
  └── CancelToken (per request or batch)

CommerceMCPBase
  ├── TimeoutConfig (timeout settings)
  ├── RequestCancelManager (cancellation management)
  └── _request(cancel_token=..., request_id=...)
```

## Quick Start

### Timeout Configuration

```python
from cn_commerce_base import (
    TimeoutConfig,
    PlatformTimeoutConfig,
    EndpointTimeout,
    CommerceMCPBase,
)

# Create configuration
config = TimeoutConfig(
    default_connect_timeout=10.0,
    default_read_timeout=30.0,
    default_write_timeout=10.0,
    default_total_timeout=60.0,
    platforms={
        "OCEANENGINE": PlatformTimeoutConfig(
            platform="OCEANENGINE",
            default_read_timeout=45.0,  # Slower API
            endpoints={
                "/api/order/search": EndpointTimeout(
                    endpoint="/api/order/search",
                    read_timeout=60.0,  # Even slower for search
                    total_timeout=90.0,
                ),
            },
        ),
        "TAOBAO": PlatformTimeoutConfig(
            platform="TAOBAO",
            default_read_timeout=20.0,  # Faster API
        ),
    },
)

# Use with CommerceMCPBase
client = CommerceMCPBase(
    app_key="your_key",
    app_secret="your_secret",
    timeout_config=config,
)
```

### Request Cancellation

```python
from cn_commerce_base import CommerceMCPBase

client = CommerceMCPBase(
    app_key="your_key",
    app_secret="your_secret",
)

# Create a cancel token
token = client.create_cancel_token()

# Make a request with cancellation support
try:
    result = await client._request(
        "GET",
        "/api/order/detail",
        params={"order_id": "12345"},
        cancel_token=token,
        request_id="req-001",
    )
except asyncio.CancelledError:
    print("Request was cancelled")

# Cancel a specific request
token.request_cancel(reason="user abort")

# Cancel all tracked requests
client.cancel_all_requests(reason="shutdown")

# Cancel specific requests by ID
client.cancel_requests_batch({"req-001", "req-002"}, reason="partial abort")
```

## Timeout Configuration Details

### Global Defaults

```python
config = TimeoutConfig(
    default_connect_timeout=10.0,   # Connection establishment timeout
    default_read_timeout=30.0,      # Response read timeout
    default_write_timeout=10.0,     # Request body write timeout
    default_total_timeout=60.0,     # Total request lifecycle timeout
    enabled=True,                   # Enable/disable custom timeouts
)
```

### Per-Platform Configuration

```python
config = TimeoutConfig(
    platforms={
        "OCEANENGINE": PlatformTimeoutConfig(
            platform="OCEANENGINE",
            default_connect_timeout=15.0,
            default_read_timeout=45.0,
            default_write_timeout=15.0,
            default_total_timeout=90.0,
        ),
    },
)
```

### Per-Endpoint Configuration

```python
config = TimeoutConfig(
    platforms={
        "OCEANENGINE": PlatformTimeoutConfig(
            platform="OCEANENGINE",
            endpoints={
                "/api/order/search": EndpointTimeout(
                    endpoint="/api/order/search",
                    connect_timeout=20.0,
                    read_timeout=60.0,
                    write_timeout=15.0,
                    total_timeout=120.0,
                ),
            },
        ),
    },
)
```

### Timeout Resolution Order

1. Endpoint-specific timeout (if configured)
2. Platform default timeout (if platform is configured)
3. Global default timeout (fallback)

## Cancellation Features

### CancelToken

The `CancelToken` class represents a cancellation signal for one or more requests.

```python
from cn_commerce_base import CancelToken

token = CancelToken()

# Request cancellation for all requests using this token
token.request_cancel(reason="user abort")

# Cancel specific request IDs
token.request_cancel(request_ids={"req-001", "req-002"}, reason="partial")

# Check if a request is cancelled
if token.is_cancelled("req-001"):
    print("Request req-001 is cancelled")

# Set a callback for when cancellation occurs
async def on_cancel():
    print("Request was cancelled, cleaning up...")

token.on_cancel = on_cancel

# Reset the token
token.reset()
```

### RequestCancelManager

The `RequestCancelManager` tracks multiple cancel tokens and provides batch operations.

```python
from cn_commerce_base import RequestCancelManager

manager = RequestCancelManager()

# Create tokens
token1 = manager.create_token()
token2 = manager.create_token(token_id="my-token")

# Cancel all
count = manager.cancel(reason="shutdown")

# Cancel specific request IDs across all tokens
count = manager.cancel_batch({"req-001", "req-002"}, reason="partial")

# Get statistics
stats = manager.get_stats()
print(stats["total_tokens"], stats["cancelled_tokens"])

# Remove a token
manager.remove_token("my-token")

# Reset all tokens
manager.reset()
```

## Integration with CommerceMCPBase

### Constructor Parameters

```python
client = CommerceMCPBase(
    app_key="key",
    app_secret="secret",
    timeout_config=TimeoutConfig(...),  # Optional
)
```

### Convenience Methods

```python
# Get/set timeout config
config = client.get_timeout_config()
client.set_timeout_config(new_config)

# Create cancel tokens
token = client.create_cancel_token()

# Cancel requests
client.cancel_all_requests(reason="shutdown")
client.cancel_requests_batch({"req-1", "req-2"}, reason="abort")

# Get cancel manager
manager = client.get_cancel_manager()
```

### Using with _request

```python
# Create a cancel token
token = client.create_cancel_token()

# Make request with cancellation support
try:
    result = await client._request(
        "GET",
        "/api/test",
        cancel_token=token,
        request_id="my-request",
    )
except asyncio.CancelledError:
    print("Request cancelled")

# Cancel the request
token.request_cancel(reason="timeout exceeded")
```

## Serialization

Timeout configurations can be serialized and deserialized:

```python
# Serialize
config = TimeoutConfig(...)
data = config.to_dict()

# Deserialize
restored = TimeoutConfig.from_dict(data)
```

## Monitoring

### Cancel Token Stats

```python
token = client.create_cancel_token()
stats = token.get_stats()
# {
#     "cancelled": False,
#     "reason": "",
#     "cancelled_at": 0.0,
#     "pending_cancel_ids": [],
# }
```

### Cancel Manager Stats

```python
manager = client.get_cancel_manager()
stats = manager.get_stats()
# {
#     "total_tokens": 5,
#     "cancelled_tokens": 2,
#     "active_tokens": 3,
#     "cancel_history_count": 10,
#     "recent_history": [...],
# }
```

## Best Practices

1. **Set appropriate timeouts**: Different endpoints may have different latency characteristics. Use per-endpoint timeouts for slow operations.

2. **Use cancel tokens for long-running operations**: When making multiple related requests, use a single cancel token to cancel them all at once.

3. **Implement cancel callbacks**: Use `on_cancel` to clean up resources when a request is cancelled.

4. **Monitor cancellation patterns**: Use `get_stats()` to track cancellation patterns and identify problematic endpoints.

5. **Reset tokens after use**: Call `token.reset()` when you're done with a token to free resources.
