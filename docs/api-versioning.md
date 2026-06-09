# API Versioning

mcp-cn-commerce provides a comprehensive API versioning system that supports multi-version coexistence, version negotiation, and deprecation management.

## Overview

The versioning system consists of four main components:

| Component | Description |
|-----------|-------------|
| `APIVersion` | Semantic version representation with comparison support |
| `APIVersionRegistry` | Central registry for versions, endpoints, and lifecycle status |
| `VersionNegotiator` | Negotiates the best version from client requests |
| `DeprecationWarningManager` | Manages deprecation warnings and response headers |

## Quick Start

```python
from cn_commerce_base import (
    APIVersion,
    APIVersionRegistry,
    VersionNegotiator,
    VersionStatus,
    VersionedEndpoint,
    DeprecationWarningManager,
)

# 1. Create a registry
registry = APIVersionRegistry()
registry.register_version(APIVersion(1), VersionStatus.ACTIVE)
registry.register_version(APIVersion(2), VersionStatus.ACTIVE)

# 2. Register versioned endpoints
def orders_v1(page=1):
    return {"version": 1, "orders": [...]}

def orders_v2(page=1, include_tracking=False):
    return {"version": 2, "orders": [...], "tracking": [...]}

endpoint = VersionedEndpoint(path="/orders")
endpoint.add_version(APIVersion(1), orders_v1)
endpoint.add_version(APIVersion(2), orders_v2)
registry.register_endpoint(endpoint)

# 3. Negotiate version from request
negotiator = VersionNegotiator(registry)
version, warnings = negotiator.negotiate(
    headers={"X-API-Version": "1"},
)

# 4. Route to correct handler
handler = endpoint.get_handler(version)
result = handler(page=1)
```

## Version Format

Versions follow semantic versioning: `MAJOR.MINOR.PATCH`

```
1      -> 1.0.0
2.1    -> 2.1.0
2.1.3  -> 2.1.3
```

### Parsing

```python
v1 = APIVersion.parse("2")       # APIVersion(2, 0, 0)
v2 = APIVersion.parse("2.1")     # APIVersion(2, 1, 0)
v3 = APIVersion.parse("2.1.3")   # APIVersion(2, 1, 3)
```

### Comparison

Versions support full comparison operators:

```python
APIVersion(1) < APIVersion(2)           # True
APIVersion(2, 1) > APIVersion(2, 0)     # True
APIVersion(1, 0, 0) == APIVersion(1)    # True
```

### Compatibility

Two versions are compatible if they share the same major version:

```python
APIVersion(2, 0).is_compatible_with(APIVersion(2, 1))  # True
APIVersion(1, 0).is_compatible_with(APIVersion(2, 0))  # False
```

## Version Lifecycle

Each version goes through a lifecycle managed by `VersionStatus`:

```
ACTIVE -> DEPRECATED -> SUNSET
```

| Status | Behavior |
|--------|----------|
| `ACTIVE` | Fully supported, recommended for new integrations |
| `DEPRECATED` | Still works, but returns deprecation warnings |
| `SUNSET` | Requests are rejected with `APIVersionError` |

### Managing Lifecycle

```python
registry = APIVersionRegistry()

# Register as active
registry.register_version(APIVersion(1), VersionStatus.ACTIVE)

# Deprecate with sunset date
registry.register_version(
    APIVersion(1),
    VersionStatus.DEPRECATED,
    sunset_date="2026-12-01",
    deprecation_message="Please upgrade to v2",
)

# Sunset (rejects requests)
registry.set_version_status(APIVersion(1), VersionStatus.SUNSET)
```

## Version Negotiation

The `VersionNegotiator` resolves the best version using the following priority order:

1. **URL path prefix**: `/v2/orders`
2. **Header**: `X-API-Version: 2`
3. **Query parameter**: `?api_version=2`
4. **Accept header**: `Accept: application/vnd.api+json;version=2`
5. **Default version**: Latest active version in the registry

### Negotiation Examples

```python
negotiator = VersionNegotiator(registry)

# By header
version, warnings = negotiator.negotiate(
    headers={"X-API-Version": "2"},
)

# By query parameter
version, warnings = negotiator.negotiate(
    params={"api_version": "2"},
)

# By URL path
version, warnings = negotiator.negotiate(
    url_path="/v2/orders/list",
)

# By Accept header
version, warnings = negotiator.negotiate(
    headers={"Accept": "application/vnd.api+json;version=2"},
)
```

### Fallback Behavior

- **Compatible fallback**: If version `2.1` is requested but only `2.0` is registered, `2.0` is returned with a warning.
- **Incompatible request**: If version `3` is requested but only `1.x` and `2.x` exist, an `APIVersionError` is raised.

## Deprecation Warnings

When a deprecated version is requested, the negotiator returns warnings. Use `DeprecationWarningManager` to format these into HTTP response headers.

```python
manager = DeprecationWarningManager()

version, warnings = negotiator.negotiate(headers={"X-API-Version": "1"})
for w in warnings:
    manager.add_warning(w)

# Set structured deprecation info
deprecation_info = registry.get_deprecation_info(version)
if deprecation_info:
    manager.set_deprecation_info(
        version=version,
        sunset_date=deprecation_info.get("sunset_date", ""),
        recommended_version=APIVersion(2),
    )

# Generate response headers
headers = manager.get_response_headers()
# {
#     "X-API-Deprecated": "true",
#     "X-API-Sunset": "2026-12-01",
#     "X-API-Upgrade": "2",
# }
```

### Response Headers

| Header | Description |
|--------|-------------|
| `X-API-Deprecated` | Always `"true"` when warnings exist |
| `X-API-Sunset` | ISO 8601 date when the version will be removed |
| `X-API-Upgrade` | Recommended version to upgrade to |

## Versioned Endpoints

`VersionedEndpoint` maps an API path to version-specific handlers:

```python
endpoint = VersionedEndpoint(path="/orders")
endpoint.add_version(APIVersion(1), handler_v1)
endpoint.add_version(APIVersion(2), handler_v2)

# Get specific version handler
handler = endpoint.get_handler(APIVersion(1))

# Get best match (falls back to highest compatible version)
version, handler = endpoint.get_best_match(APIVersion(2))

# List all supported versions
versions = endpoint.supported_versions  # [APIVersion(1), APIVersion(2)]
```

## Error Handling

`APIVersionError` is raised for version-related issues:

```python
from cn_commerce_base import APIVersionError

try:
    version, warnings = negotiator.negotiate(headers={"X-API-Version": "99"})
except APIVersionError as e:
    print(e.code)              # "VERSION_NOT_FOUND"
    print(e.message)           # "API version 99 is not available..."
    print(e.supported_versions)  # [APIVersion(1), APIVersion(2)]
```

### Error Codes

| Code | Description |
|------|-------------|
| `VERSION_NOT_FOUND` | Requested version is not registered and no compatible fallback |
| `VERSION_SUNSET` | Requested version has been sunset |
| `INVALID_VERSION` | Version string could not be parsed |
| `NO_VERSIONS` | No versions are registered in the registry |

## Integration with CommerceMCPBase

Integrate versioning into your platform server:

```python
class MyPlatformServer(CommerceMCPBase):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.version_registry = APIVersionRegistry()
        self.version_registry.register_version(APIVersion(1), VersionStatus.ACTIVE)
        self.version_registry.register_version(APIVersion(2), VersionStatus.ACTIVE)
        self.negotiator = VersionNegotiator(self.version_registry)

    async def handle_request(self, path, headers, params, data):
        # Negotiate version
        version, warnings = self.negotiator.negotiate(
            headers=headers,
            params=params,
            url_path=path,
        )

        # Add deprecation warnings to response
        if warnings:
            manager = DeprecationWarningManager()
            for w in warnings:
                manager.add_warning(w)
            response_headers = manager.get_response_headers()

        # Route to versioned handler
        endpoint = self.version_registry.get_endpoint(path)
        handler = endpoint.get_handler(version)
        return handler(**data)
```
