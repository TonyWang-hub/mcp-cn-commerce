# Security Best Practices

This document outlines security best practices for deploying and using mcp-cn-commerce in production environments.

## Table of Contents

- [Credential Management](#credential-management)
- [Logging Security](#logging-security)
- [Input Validation](#input-validation)
- [Network Security](#network-security)
- [Deployment Security](#deployment-security)
- [Incident Response](#incident-response)

---

## Credential Management

### Environment Variables

Always store API credentials in environment variables, never in code or configuration files.

```bash
# Good: Use environment variables
export OCEANENGINE_APP_KEY="your_key"
export OCEANENGINE_APP_SECRET="your_secret"
export OCEANENGINE_ACCESS_TOKEN="your_token"

# Bad: Hardcoded credentials
app_key = "abc123"  # NEVER do this
```

### Credential Rotation

Rotate API tokens regularly according to your organization's security policy:

| Token Type | Recommended Rotation |
|------------|---------------------|
| Access Tokens | Every 30-90 days |
| App Secrets | Every 90-180 days |
| API Keys | Every 180-365 days |

### Secure Storage

For production deployments, use a secrets manager:

- **AWS**: Secrets Manager or Parameter Store
- **Azure**: Key Vault
- **GCP**: Secret Manager
- **HashiCorp Vault**: Recommended for multi-cloud

### .env Files

If using `.env` files for local development:

1. Add `.env` to `.gitignore`
2. Set restrictive file permissions: `chmod 600 .env`
3. Never commit `.env` files to version control
4. Use `.env.example` as a template without real values

---

## Logging Security

### Sensitive Data Filtering

The `SensitiveDataFilter` automatically masks sensitive data in logs:

```python
from cn_commerce_base import SensitiveDataFilter
import logging

logger = logging.getLogger("mcp-cn-commerce")
logger.addFilter(SensitiveDataFilter())
```

### What Gets Masked

The filter masks:

- **API keys and secrets**: Shows only first 4 and last 4 characters
- **Access tokens**: Partially visible for debugging
- **JWT tokens**: Completely masked
- **Bearer tokens**: Token value masked

### Log Levels

Use appropriate log levels:

| Level | Use Case |
|-------|----------|
| DEBUG | Detailed debugging (disable in production) |
| INFO | Normal operations |
| WARNING | Recoverable issues |
| ERROR | Failures requiring attention |

### Production Logging

In production:

1. Set log level to `INFO` or higher
2. Enable `SensitiveDataFilter`
3. Use structured logging for analysis
4. Forward logs to a secure SIEM system

---

## Input Validation

### API Parameter Validation

All API parameters are validated against injection attacks:

```python
from cn_commerce_base import validate_api_param

# Automatically checks for SQL injection, path traversal, XSS
safe_value = validate_api_param("keyword", user_input)
```

### Platform Name Validation

Platform names must follow strict naming conventions:

```python
from cn_commerce_base import validate_platform_name

# Valid: OCEANENGINE, TAOBAO, JD
# Invalid: oceanengine (lowercase), TA OBAO (space), TAOBAO;DROP TABLE
```

### Environment Variable Validation

Environment variable names are validated:

```python
from cn_commerce_base import validate_env_var_name

# Valid: OCEANENGINE_APP_KEY
# Invalid: oceanengine_app_key, OCEANENGINE APP KEY
```

### Custom Validation

For custom parameters, use the validation functions:

```python
from cn_commerce_base import validate_api_param

def process_search(keyword: str, page: int) -> dict:
    # Validate user input
    safe_keyword = validate_api_param("keyword", keyword, max_length=200)

    # Validate numeric ranges
    if not 1 <= page <= 100:
        raise ValueError("Page must be between 1 and 100")

    return {"keyword": safe_keyword, "page": page}
```

---

## Network Security

### TLS/SSL

All API communications use HTTPS:

- Platform APIs enforce TLS 1.2+
- Certificate validation is enabled by default
- No self-signed certificates in production

### Rate Limiting

Built-in rate limiting prevents abuse:

```python
from cn_commerce_base import RateLimiter

# Default: 10 requests per second
limiter = RateLimiter(requests_per_second=10.0)

# Custom rate for specific platforms
limiter = RateLimiter(requests_per_second=5.0)
```

### Connection Pooling

HTTP clients use connection pooling with limits:

```python
# Default limits
max_connections = 10
max_keepalive_connections = 5
keepalive_expiry = 30  # seconds
```

### Timeout Configuration

Set appropriate timeouts:

```python
# Default timeout: 30 seconds
client = httpx.AsyncClient(timeout=30)

# Custom timeout for slow APIs
client = httpx.AsyncClient(timeout=60)
```

---

## Deployment Security

### Container Security

When deploying with Docker:

```dockerfile
# Use minimal base image
FROM python:3.11-slim

# Run as non-root user
RUN useradd -m appuser
USER appuser

# Set read-only filesystem
RUN chmod -R 555 /app
```

### Environment Isolation

Separate credentials by environment:

```bash
# Development
export OCEANENGINE_APP_KEY="dev_key"

# Staging
export OCEANENGINE_APP_KEY="staging_key"

# Production
export OCEANENGINE_APP_KEY="prod_key"
```

### Access Control

Implement least privilege:

1. Use read-only API scopes when available
2. Limit API key permissions to required operations
3. Monitor API usage for anomalies

### Secret Rotation Automation

Automate secret rotation:

```bash
#!/bin/bash
# rotate_secrets.sh

# Generate new token
NEW_TOKEN=$(openssl rand -hex 32)

# Update in secrets manager
aws secretsmanager update-secret \
  --secret-id "mcp-cn-commerce/prod/access-token" \
  --secret-string "$NEW_TOKEN"

# Restart service
kubectl rollout restart deployment/mcp-cn-commerce
```

---

## Incident Response

### Credential Compromise

If credentials are compromised:

1. **Immediately rotate** all affected credentials
2. **Audit logs** for unauthorized access
3. **Review permissions** granted to compromised credentials
4. **Notify stakeholders** according to your incident response plan

### Log Analysis

Check for suspicious patterns:

```bash
# Search for failed authentication
grep "API error.*40001" /var/log/mcp-cn-commerce.log

# Check for unusual request patterns
grep "Request:" /var/log/mcp-cn-commerce.log | \
  awk '{print $4}' | sort | uniq -c | sort -rn
```

### Forensic Data

Preserve evidence:

1. Export logs for the affected time period
2. Document timeline of events
3. Capture API access logs from platform providers
4. Maintain chain of custody for evidence

---

## Security Checklist

Before deploying to production:

- [ ] Credentials stored in environment variables or secrets manager
- [ ] `.env` files excluded from version control
- [ ] `SensitiveDataFilter` enabled for logging
- [ ] Log level set to `INFO` or higher
- [ ] Rate limiting configured appropriately
- [ ] TLS/SSL enabled for all connections
- [ ] Input validation enabled for all user inputs
- [ ] Access logs monitored for anomalies
- [ ] Incident response plan documented
- [ ] Regular credential rotation scheduled

---

## Reporting Security Issues

For security vulnerabilities, please see [SECURITY.md](../SECURITY.md) for reporting instructions.

**Do NOT** open public issues for security vulnerabilities.
