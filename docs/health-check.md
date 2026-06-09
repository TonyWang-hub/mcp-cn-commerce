# Health Check & Configuration Validation

## Overview

`cn_commerce_base` provides built-in health check APIs and configuration
validation for all platform MCP servers.  These features help operators
monitor service status and catch configuration errors before they cause
runtime failures.

---

## Health Check API

### Basic Health Check

Every `CommerceMCPBase` subclass inherits a `health_check()` method:

```python
client = OceanEngineMCP(app_key="...", app_secret="...", access_token="...")
result = await client.health_check()
```

**Response fields:**

| Field           | Type   | Description                                    |
|-----------------|--------|------------------------------------------------|
| `status`        | str    | `"healthy"`, `"degraded"`, or `"unhealthy"`    |
| `configured`    | bool   | Whether API credentials are set                |
| `has_token`     | bool   | Whether an access token is present             |
| `api_reachable` | bool   | Whether the API endpoint responded (< 500)     |
| `latency_ms`    | float  | Latency of the check in milliseconds           |
| `metrics`       | dict   | Request metrics summary                        |
| `pool`          | dict   | Connection pool health                         |
| `cached`        | bool   | Whether the result was served from cache       |
| `timestamp`     | str    | ISO 8601 timestamp                             |
| `error`         | str    | Error message (only when check failed)         |

### Deep Health Check

For production monitoring, use `deep_health_check()` to also verify
dependency services:

```python
result = await client.deep_health_check(
    dependencies=[
        "https://redis.internal:6379",
        "https://db.internal:5432",
        "OCEANENGINE_AUTH_SERVICE",
    ],
    timeout=10.0,
)
```

Each dependency is checked and reported in the `dependencies` dict:

```json
{
  "status": "healthy",
  "dependencies": {
    "https://redis.internal:6379": {
      "name": "https://redis.internal:6379",
      "reachable": true,
      "status_code": 200,
      "latency_ms": 12.5
    }
  }
}
```

### HTTP Endpoint Support

To expose a health check via HTTP (e.g., for load balancer probes),
call `health_check()` from your HTTP handler:

```python
from aiohttp import web

async def health_handler(request):
    result = await client.health_check()
    status = 200 if result["status"] == "healthy" else 503
    return web.json_response(result, status=status)

app = web.Application()
app.router.add_get("/health", health_handler)
```

### Caching

Health check results are cached for 30 seconds by default to avoid
hammering API endpoints in high-frequency monitoring scenarios.

```python
# Force a fresh check (skip cache)
result = await client.health_check(use_cache=False)

# Use a custom cache key (e.g., per-instance)
result = await client.health_check(cache_key="instance-1")

# Invalidate the cache
client._health_cache.invalidate()
```

A global cache (`_global_health_cache`) is also available for
cross-instance sharing.

---

## Configuration Validation

### Basic Usage

Use `ConfigValidator` to validate platform configuration:

```python
from cn_commerce_base import ConfigValidator, ConfigRule

validator = ConfigValidator("OCEANENGINE")
validator.add_rules([
    ConfigRule("APP_KEY", required=True, min_length=8, max_length=64),
    ConfigRule("APP_SECRET", required=True, min_length=16),
    ConfigRule("ACCESS_TOKEN", required=False, depends_on=["APP_KEY", "APP_SECRET"]),
    ConfigRule("API_TIMEOUT", required=False, value_type="int", min_value=1, max_value=300),
])

config = {
    "APP_KEY": "my_key_123",
    "APP_SECRET": "my_secret_value_12345678",
    "API_TIMEOUT": 30,
}
result = validator.validate(config)

if not result.valid:
    for error in result.errors:
        print(f"  ERROR: {error}")
```

### Validation Types

#### Format Validation

Checks that values match their expected type and constraints:

```python
ConfigRule("BASE_URL", value_type="url")         # Must start with http(s)://
ConfigRule("CONTACT_EMAIL", value_type="email")   # Must be valid email
ConfigRule("MODE", allowed_values=["prod", "dev", "staging"])
ConfigRule("VERSION", pattern=r"^\d+\.\d+\.\d+$") # Semver pattern
```

#### Range Validation

Checks numeric ranges and string lengths:

```python
ConfigRule("PORT", value_type="int", min_value=1, max_value=65535)
ConfigRule("APP_KEY", min_length=8, max_length=64)
ConfigRule("RATE_LIMIT", value_type="float", min_value=0.1, max_value=1000.0)
```

#### Dependency Validation

Ensures required keys are present when dependent keys are configured:

```python
ConfigRule("REFRESH_TOKEN", required=False, depends_on=["APP_KEY", "APP_SECRET"])
ConfigRule("WEBHOOK_URL", required=False, depends_on=["ACCESS_TOKEN"])
```

If `REFRESH_TOKEN` is set but `APP_KEY` is missing, the validator
reports an error.

### Validation from Environment Variables

```python
result = validator.validate_from_env("OCEANENGINE")
```

This reads `OCEANENGINE_APP_KEY`, `OCEANENGINE_APP_SECRET`, etc. from
the environment and validates them.

### Result Structure

`ConfigValidationResult` contains:

| Field               | Type  | Description                           |
|---------------------|-------|---------------------------------------|
| `valid`             | bool  | True if all validations passed        |
| `errors`            | list  | List of error messages                |
| `warnings`          | list  | Non-critical warnings                 |
| `missing_keys`      | list  | Required keys that are missing        |
| `invalid_keys`      | list  | Keys with invalid values              |
| `dependency_errors` | list  | Dependency relationship errors        |
| `error_count`       | int   | Number of errors                      |
| `warning_count`     | int   | Number of warnings                    |

---

## Status Levels

| Status      | Meaning                                                      |
|-------------|--------------------------------------------------------------|
| `healthy`   | API reachable, credentials valid, all dependencies OK        |
| `degraded`  | Credentials configured but API unreachable or deps failing   |
| `unhealthy` | Missing credentials or completely unreachable                |
