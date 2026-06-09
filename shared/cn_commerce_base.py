"""Shared base for Chinese e-commerce platform MCP servers.

Provides unified auth signing, request handling, and error normalization.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import hmac
import json
import logging
import os
import random
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

# ── Security: Sensitive Data Masking ─────────────────────

# Patterns for sensitive fields that should be masked in logs
_SENSITIVE_FIELD_PATTERNS = re.compile(
    r"(app_key|app_secret|access_token|client_id|client_secret|"
    r"refresh_token|api_key|secret_key|password|token|sign)",
    re.IGNORECASE,
)

# Regex patterns to detect sensitive values in strings
_SENSITIVE_VALUE_PATTERNS = [
    # JWT tokens
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    # Bearer tokens
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/-]+=*", re.IGNORECASE),
]


def mask_sensitive_value(value: str, visible_prefix: int = 4, visible_suffix: int = 4) -> str:
    """Mask a sensitive value, showing only prefix and suffix.

    Args:
        value: The sensitive string to mask.
        visible_prefix: Number of characters to show at the start.
        visible_suffix: Number of characters to show at the end.

    Returns:
        Masked string like "abcd****efgh".

    Examples:
        >>> mask_sensitive_value("abcdefghijklmnop")
        'abcd****mnop'
        >>> mask_sensitive_value("short")
        's****t'
        >>> mask_sensitive_value("")
        '****'
    """
    if not value:
        return "****"
    if len(value) <= visible_prefix + visible_suffix:
        return value[0] + "****" + value[-1] if len(value) > 1 else "****"
    return f"{value[:visible_prefix]}****{value[-visible_suffix:]}"


def mask_dict_sensitive_keys(data: dict[str, Any]) -> dict[str, Any]:
    """Create a copy of a dict with sensitive keys masked.

    Recursively processes nested dicts and lists.

    Args:
        data: Dictionary that may contain sensitive keys.

    Returns:
        A new dictionary with sensitive values masked.
    """
    masked: dict[str, Any] = {}
    for key, value in data.items():
        if _SENSITIVE_FIELD_PATTERNS.search(key):
            if isinstance(value, str):
                masked[key] = mask_sensitive_value(value)
            else:
                masked[key] = "***MASKED***"
        elif isinstance(value, dict):
            masked[key] = mask_dict_sensitive_keys(value)
        elif isinstance(value, list):
            masked[key] = [mask_dict_sensitive_keys(item) if isinstance(item, dict) else item for item in value]
        else:
            masked[key] = value
    return masked


def mask_log_message(message: str) -> str:
    """Mask sensitive values that may appear in log message strings.

    Scans for patterns that look like JWTs or Bearer tokens.

    Args:
        message: Log message string.

    Returns:
        Message with sensitive values masked.
    """
    # Mask JWT tokens
    message = _SENSITIVE_VALUE_PATTERNS[0].sub(lambda m: mask_sensitive_value(m.group()), message)
    # Mask Bearer tokens
    message = _SENSITIVE_VALUE_PATTERNS[1].sub(
        lambda m: (
            m.group().split()[0] + " " + mask_sensitive_value(m.group().split()[1])
            if len(m.group().split()) > 1
            else m.group()
        ),
        message,
    )
    return message


class SensitiveDataFilter(logging.Filter):
    """Logging filter that masks sensitive data in log records.

    Usage:
        logger.addFilter(SensitiveDataFilter())
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Filter log record, masking any sensitive data."""
        if isinstance(record.msg, str):
            record.msg = mask_log_message(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = mask_dict_sensitive_keys(record.args)
            elif isinstance(record.args, tuple | list):
                record.args = tuple(mask_log_message(str(a)) if isinstance(a, str) else a for a in record.args)
        return True


# ── Security: Input Validation ────────────────────────────

_SQL_INJECTION_PATTERNS = re.compile(
    r"(\b(UNION|SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|EXEC|EXECUTE)\b"
    r"--|/\*|\*/|;.*\b(DROP|DELETE|UPDATE|INSERT)\b"
    r"|'\s*(OR|AND)\s*'?\d*"
    r"|'\s*;\s*)",
    re.IGNORECASE,
)
_PATH_TRAVERSAL_PATTERN = re.compile(r"(\.\./|\.\.\\|%2e%2e[/\\]|%252e%252e)", re.IGNORECASE)
_XSS_PATTERN = re.compile(
    r"(<script[^>]*>|javascript:|on\w+\s*=|<iframe|<object|<embed|<form)",
    re.IGNORECASE,
)


def validate_platform_name(platform: str) -> str:
    """Validate and sanitize a platform name.

    Platform names must be uppercase alphanumeric with underscores only.

    Args:
        platform: The platform name to validate.

    Returns:
        The validated platform name.

    Raises:
        ValueError: If the platform name contains invalid characters.
    """
    if not platform:
        raise ValueError("Platform name cannot be empty")
    if not re.match(r"^[A-Z][A-Z0-9_]*$", platform):
        raise ValueError(f"Invalid platform name '{platform}': must be uppercase alphanumeric with underscores")
    if len(platform) > 64:
        raise ValueError(f"Platform name too long ({len(platform)} > 64)")
    return platform


def validate_api_param(name: str, value: str, max_length: int = 4096) -> str:
    """Validate an API parameter value for injection attacks.

    Checks for SQL injection, path traversal, and XSS patterns.

    Args:
        name: Parameter name (for error messages).
        value: Parameter value to validate.
        max_length: Maximum allowed length.

    Returns:
        The validated value.

    Raises:
        ValueError: If the value contains suspicious patterns.
    """
    if not isinstance(value, str):
        return value  # type: ignore[return-value]

    if len(value) > max_length:
        raise ValueError(f"Parameter '{name}' exceeds maximum length ({len(value)} > {max_length})")

    if _SQL_INJECTION_PATTERNS.search(value):
        raise ValueError(f"Parameter '{name}' contains suspicious SQL patterns")

    if _PATH_TRAVERSAL_PATTERN.search(value):
        raise ValueError(f"Parameter '{name}' contains path traversal patterns")

    if _XSS_PATTERN.search(value):
        raise ValueError(f"Parameter '{name}' contains suspicious script patterns")

    return value


def validate_env_var_name(name: str) -> str:
    """Validate an environment variable name.

    Env var names must be uppercase alphanumeric with underscores.

    Args:
        name: The environment variable name.

    Returns:
        The validated name.

    Raises:
        ValueError: If the name is invalid.
    """
    if not name:
        raise ValueError("Environment variable name cannot be empty")
    if not re.match(r"^[A-Z][A-Z0-9_]*$", name):
        raise ValueError(f"Invalid env var name '{name}': must be uppercase alphanumeric with underscores")
    return name


def sanitize_log_context(**kwargs: Any) -> dict[str, Any]:
    """Create a sanitized context dict for logging, masking sensitive values.

    Args:
        **kwargs: Key-value pairs to include in the context.

    Returns:
        A dictionary safe for logging with sensitive values masked.
    """
    return mask_dict_sensitive_keys(kwargs)


# Configure logging
logger = logging.getLogger("mcp-cn-commerce")


class SignMethod:
    """Supported signing methods for API authentication."""

    MD5: str = "md5"
    HMAC_SHA256: str = "hmac_sha256"
    HMAC_MD5: str = "hmac_md5"


class ConfigValidationError(Exception):
    """Raised when required configuration is missing."""

    def __init__(self, platform: str, missing_vars: list[str]) -> None:
        self.platform = platform
        self.missing_vars = missing_vars
        msg = f"[{platform}] Missing required environment variables: {', '.join(missing_vars)}"
        super().__init__(msg)


class RateLimiter:
    """Simple rate limiter to prevent API throttling."""

    def __init__(self, requests_per_second: float = 10.0) -> None:
        self.requests_per_second = requests_per_second
        self.min_interval = 1.0 / requests_per_second
        self.last_request_time: float = 0.0

    async def acquire(self) -> None:
        """Wait if necessary to respect rate limit."""
        now = time.time()
        time_since_last = now - self.last_request_time
        if time_since_last < self.min_interval:
            wait_time = self.min_interval - time_since_last
            logger.debug(f"Rate limit: waiting {wait_time:.2f}s")
            await asyncio.sleep(wait_time)
        self.last_request_time = time.time()


# ── Metrics ────────────────────────────────────────────────


@dataclass
class EndpointMetrics:
    """Metrics for a single API endpoint.

    Attributes:
        request_count: Total number of requests.
        error_count: Number of failed requests.
        total_latency_ms: Cumulative latency in milliseconds.
        min_latency_ms: Minimum observed latency.
        max_latency_ms: Maximum observed latency.
        last_error_code: Most recent error code (0 if none).
        last_error_msg: Most recent error message.
    """

    request_count: int = 0
    error_count: int = 0
    total_latency_ms: float = 0.0
    min_latency_ms: float = float("inf")
    max_latency_ms: float = 0.0
    last_error_code: int = 0
    last_error_msg: str = ""

    @property
    def avg_latency_ms(self) -> float:
        """Average latency in milliseconds."""
        if self.request_count == 0:
            return 0.0
        return self.total_latency_ms / self.request_count

    @property
    def error_rate(self) -> float:
        """Error rate as a fraction (0.0 to 1.0)."""
        if self.request_count == 0:
            return 0.0
        return self.error_count / self.request_count


class MetricsCollector:
    """Collects and aggregates request metrics across endpoints.

    Thread-safe via a lock so it can be used from concurrent async tasks.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._endpoints: OrderedDict[str, EndpointMetrics] = OrderedDict()
        self._global = EndpointMetrics()
        self._start_time = time.time()

    def record_request(
        self,
        endpoint: str,
        latency_ms: float,
        success: bool,
        error_code: int = 0,
        error_msg: str = "",
    ) -> None:
        """Record a completed request.

        Args:
            endpoint: The API endpoint path.
            latency_ms: Request duration in milliseconds.
            success: Whether the request succeeded.
            error_code: Platform-specific error code (if failed).
            error_msg: Error message (if failed).
        """
        with self._lock:
            ep = self._endpoints.setdefault(endpoint, EndpointMetrics())
            ep.request_count += 1
            ep.total_latency_ms += latency_ms
            ep.min_latency_ms = min(ep.min_latency_ms, latency_ms)
            ep.max_latency_ms = max(ep.max_latency_ms, latency_ms)
            if not success:
                ep.error_count += 1
                ep.last_error_code = error_code
                ep.last_error_msg = error_msg

            # Global aggregation
            self._global.request_count += 1
            self._global.total_latency_ms += latency_ms
            self._global.min_latency_ms = min(self._global.min_latency_ms, latency_ms)
            self._global.max_latency_ms = max(self._global.max_latency_ms, latency_ms)
            if not success:
                self._global.error_count += 1

    def get_endpoint_metrics(self, endpoint: str) -> EndpointMetrics:
        """Get metrics for a specific endpoint, or a default empty one."""
        with self._lock:
            return self._endpoints.get(endpoint, EndpointMetrics())

    def get_global_metrics(self) -> EndpointMetrics:
        """Get aggregated metrics across all endpoints."""
        with self._lock:
            return self._global

    def get_all_metrics(self) -> dict[str, EndpointMetrics]:
        """Get metrics for all recorded endpoints."""
        with self._lock:
            return dict(self._endpoints)

    def get_summary(self) -> dict[str, Any]:
        """Get a JSON-serializable summary of all metrics.

        Returns:
            Dict with ``uptime_seconds``, ``global``, and ``endpoints`` keys.
        """
        with self._lock:
            uptime = time.time() - self._start_time
            return {
                "uptime_seconds": round(uptime, 2),
                "global": {
                    "total_requests": self._global.request_count,
                    "total_errors": self._global.error_count,
                    "avg_latency_ms": round(self._global.avg_latency_ms, 2),
                    "error_rate": round(self._global.error_rate, 4),
                },
                "endpoints": {
                    ep: {
                        "requests": m.request_count,
                        "errors": m.error_count,
                        "avg_latency_ms": round(m.avg_latency_ms, 2),
                        "min_latency_ms": m.min_latency_ms if m.min_latency_ms != float("inf") else 0.0,
                        "max_latency_ms": m.max_latency_ms,
                        "error_rate": round(m.error_rate, 4),
                    }
                    for ep, m in self._endpoints.items()
                },
            }

    def reset(self) -> None:
        """Reset all collected metrics."""
        with self._lock:
            self._endpoints.clear()
            self._global = EndpointMetrics()
            self._start_time = time.time()


# ── Retry Mechanism ────────────────────────────────────────


class RetryableError(Exception):
    """Exception that signals the operation should be retried.

    Wraps the original exception so callers can distinguish between
    retryable and non-retryable failures.
    """

    def __init__(self, original: Exception, attempt: int) -> None:
        self.original = original
        self.attempt = attempt
        super().__init__(f"Retryable error on attempt {attempt}: {original}")


@dataclass
class RetryConfig:
    """Configuration for the retry mechanism.

    Attributes:
        max_retries: Maximum number of retry attempts (0 = no retries).
        base_delay: Base delay in seconds for exponential backoff.
        max_delay: Maximum delay cap in seconds.
        jitter: Whether to add random jitter to the delay.
        retryable_exceptions: Tuple of exception types that should be retried.
        retryable_status_codes: Set of HTTP status codes that should be retried.
        retryable_api_codes: Set of platform API error codes that should be retried.
    """

    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    jitter: bool = True
    retryable_exceptions: tuple[type[Exception], ...] = (
        httpx.ConnectError,
        httpx.ReadTimeout,
        httpx.WriteTimeout,
        httpx.PoolTimeout,
    )
    retryable_status_codes: set[int] = field(default_factory=lambda: {429, 500, 502, 503, 504})
    retryable_api_codes: set[int] = field(default_factory=lambda: set())

    def compute_delay(self, attempt: int) -> float:
        """Compute the delay before the next retry using exponential backoff.

        Args:
            attempt: The current attempt number (0-indexed).

        Returns:
            Delay in seconds.
        """
        delay = min(self.base_delay * (2**attempt), self.max_delay)
        if self.jitter:
            delay = delay * (0.5 + random.random())
        return delay

    def should_retry_http_status(self, status_code: int) -> bool:
        """Check if an HTTP status code should trigger a retry."""
        return status_code in self.retryable_status_codes

    def should_retry_api_code(self, api_code: int) -> bool:
        """Check if a platform API error code should trigger a retry."""
        return api_code in self.retryable_api_codes

    def should_retry_exception(self, exc: Exception) -> bool:
        """Check if an exception should trigger a retry."""
        if isinstance(exc, CommerceAPIError):
            return self.should_retry_api_code(exc.code)
        return isinstance(exc, self.retryable_exceptions)


# Default retry config for common transient errors
DEFAULT_RETRY = RetryConfig()

# Aggressive retry config for rate-limited endpoints
RATE_LIMIT_RETRY = RetryConfig(
    max_retries=5,
    base_delay=2.0,
    max_delay=120.0,
    retryable_status_codes={429, 500, 502, 503, 504},
)


def with_retry(config: RetryConfig | None = None) -> Callable[..., Any]:
    """Decorator that adds retry with exponential backoff to an async function.

    Usage::

        @with_retry(RetryConfig(max_retries=3))
        async def fetch_data(self, ...):
            ...

    Args:
        config: Retry configuration. Uses DEFAULT_RETRY if not provided.

    Returns:
        A decorator that wraps the async function with retry logic.
    """
    retry_config = config or DEFAULT_RETRY

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Exception | None = None
            for attempt in range(retry_config.max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as exc:
                    last_exc = exc
                    if not retry_config.should_retry_exception(exc):
                        raise
                    if attempt == retry_config.max_retries:
                        logger.error(f"Max retries ({retry_config.max_retries}) exhausted for {func.__name__}")
                        raise
                    delay = retry_config.compute_delay(attempt)
                    logger.warning(
                        f"Retry {attempt + 1}/{retry_config.max_retries} for {func.__name__} "
                        f"after {delay:.2f}s: {exc}"
                    )
                    await asyncio.sleep(delay)
            # Should not reach here, but safety net
            if last_exc:
                raise last_exc

        return wrapper

    return decorator


# ── Batch Operations ───────────────────────────────────────


@dataclass
class BatchRequestItem:
    """A single request item for batch execution.

    Attributes:
        method: HTTP method ("GET" or "POST").
        path: API endpoint path.
        params: Query parameters.
        data: Request body data.
        request_id: Optional identifier for correlating results.
    """

    method: str
    path: str
    params: dict[str, Any] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)
    request_id: str = ""


@dataclass
class BatchResultItem:
    """Result of a single batch request.

    Attributes:
        request_id: Identifier matching the input BatchRequestItem.
        success: Whether the request succeeded.
        data: Response data (if successful).
        error: Exception (if failed).
        latency_ms: Request duration in milliseconds.
    """

    request_id: str
    success: bool
    data: Any = None
    error: Exception | None = None
    latency_ms: float = 0.0


@dataclass
class BatchSummary:
    """Aggregated summary of a batch request execution.

    Attributes:
        total: Total number of requests.
        succeeded: Number of successful requests.
        failed: Number of failed requests.
        results: Individual result items.
        total_latency_ms: Total wall-clock time for the batch.
        error_summary: Count of errors grouped by exception type name.
    """

    total: int
    succeeded: int
    failed: int
    results: list[BatchResultItem]
    total_latency_ms: float
    error_summary: dict[str, int] = field(default_factory=dict)


# ── MCP Base ───────────────────────────────────────────────


class CommerceMCPBase:
    """Base class for Chinese e-commerce platform MCP servers.

    Each platform server inherits this and defines:
      - BASE_URL
      - sign_method
      - FIELD_MAP (platform field -> internal field)
    """

    BASE_URL: str = ""
    sign_method: str = SignMethod.MD5
    app_key: str = ""
    app_secret: str = ""
    access_token: str = ""
    rate_limiter: RateLimiter | None = None
    _client: httpx.AsyncClient | None = None

    def __init__(self, app_key: str = "", app_secret: str = "", access_token: str = "") -> None:
        self.app_key = app_key
        self.app_secret = app_secret
        self.access_token = access_token
        self.rate_limiter = RateLimiter()
        self.metrics = MetricsCollector()

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create an HTTP client with connection pooling."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=30,
                limits=httpx.Limits(
                    max_connections=10,
                    max_keepalive_connections=5,
                    keepalive_expiry=30,
                ),
            )
        return self._client

    @classmethod
    def from_env(cls, platform: str, required_vars: list[str]) -> CommerceMCPBase:
        """Create client from environment variables with validation.

        Args:
            platform: Platform name (e.g., "OCEANENGINE", "TAOBAO")
            required_vars: List of required env var suffixes (e.g., ["APP_KEY", "APP_SECRET", "ACCESS_TOKEN"])

        Raises:
            ConfigValidationError: If any required variable is missing.
        """
        missing = []
        values = {}
        for var in required_vars:
            env_name = f"{platform}_{var}"
            value = os.environ.get(env_name, "")
            if not value:
                missing.append(env_name)
            values[var] = value

        if missing:
            logger.error(f"Missing config for {platform}: {missing}")
            raise ConfigValidationError(platform, missing)

        logger.info(f"Client initialized for {platform}")
        return cls(
            app_key=values.get("APP_KEY", values.get("CLIENT_ID", "")),
            app_secret=values.get("APP_SECRET", values.get("CLIENT_SECRET", "")),
            access_token=values.get("ACCESS_TOKEN", ""),
        )

    # ── HTTP ──────────────────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        data: dict | None = None,
        retry_config: RetryConfig | None = None,
    ) -> dict[str, Any]:
        """Make a signed API request with optional retry support.

        Args:
            method: HTTP method ("GET" or "POST").
            path: API endpoint path (appended to BASE_URL).
            params: Query parameters.
            data: Request body (JSON).
            retry_config: If provided, retry failed requests according to this config.

        Returns:
            Parsed JSON response as a dict.

        Raises:
            CommerceAPIError: If the API returns an error response.
            httpx.HTTPError: For non-retryable network errors.
        """
        params = params or {}
        data = data or {}

        # Snapshot auth params for retry (timestamp must be regenerated each attempt)
        auth_params: dict[str, str] = {}
        auth_params["app_key"] = self.app_key
        if self.access_token:
            auth_params["access_token"] = self.access_token

        last_exc: Exception | None = None
        max_attempts = (retry_config.max_retries + 1) if retry_config else 1

        for attempt in range(max_attempts):
            try:
                # Rate limiting
                if self.rate_limiter:
                    await self.rate_limiter.acquire()

                # Build fresh params each attempt (timestamp changes)
                attempt_params = {**params, **auth_params}
                attempt_params["timestamp"] = str(int(time.time() * 1000))
                attempt_params["sign"] = self._sign(attempt_params)
                attempt_params["sign_method"] = self.sign_method

                url = f"{self.BASE_URL}{path}"
                logger.debug(f"Request: {method} {url} (attempt {attempt + 1}/{max_attempts})")

                client = self._get_client()
                if method == "GET":
                    resp = await client.get(url, params={**attempt_params, **data})
                else:
                    resp = await client.post(url, params=attempt_params, json=data)

                result = resp.json()
                if "error_response" in result:
                    error_code = result["error_response"].get("code", -1)
                    error_msg = result["error_response"].get("msg", "unknown")
                    logger.warning(f"API error: [{error_code}] {error_msg}")
                    raise CommerceAPIError(code=error_code, msg=error_msg)

                logger.debug(f"Response: {resp.status_code}")
                return result

            except Exception as exc:
                last_exc = exc
                # If no retry config or not retryable, re-raise immediately
                if not retry_config or not retry_config.should_retry_exception(exc):
                    raise

                # If this was the last attempt, re-raise
                if attempt == max_attempts - 1:
                    logger.error(f"Max retries ({retry_config.max_retries}) exhausted for {path}")
                    raise

                delay = retry_config.compute_delay(attempt)
                logger.warning(
                    f"Retry {attempt + 1}/{retry_config.max_retries} for {path} " f"after {delay:.2f}s: {exc}"
                )
                await asyncio.sleep(delay)

        # Should not reach here
        if last_exc:
            raise last_exc  # type: ignore[misc]
        return {}  # type: ignore[return-value]

    # ── Signing ───────────────────────────────────────────

    def _sign(self, params: dict[str, Any]) -> str:
        """Generate signature for request params."""
        # Remove sign and sign_method, sort by key
        to_sign = {k: v for k, v in params.items() if k not in ("sign", "sign_method") and v != ""}
        sorted_keys = sorted(to_sign.keys())
        raw = self.app_secret + "".join(f"{k}{to_sign[k]}" for k in sorted_keys) + self.app_secret

        if self.sign_method == SignMethod.MD5:
            return hashlib.md5(raw.encode()).hexdigest().upper()
        elif self.sign_method == SignMethod.HMAC_SHA256:
            return hmac.HMAC(self.app_secret.encode(), raw.encode(), hashlib.sha256).hexdigest().upper()
        raise ValueError(f"Unknown sign method: {self.sign_method}")

    # ── Pagination ────────────────────────────────────────

    async def _paginate(
        self,
        fetch_fn: Callable[..., Awaitable[dict[str, Any]]],
        page_key: str = "page",
        page_size: int = 50,
        max_pages: int = 50,
    ) -> list[dict[str, Any]]:
        """Generic pagination helper."""
        results: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            data = await fetch_fn(page=page, page_size=page_size)
            items = data.get("result", data.get("list", []))
            results.extend(items)
            logger.debug(f"Pagination: page {page}, got {len(items)} items")
            if len(items) < page_size:
                break
        logger.info(f"Pagination complete: {len(results)} total items")
        return results

    # ── Batch Operations ──────────────────────────────────

    @staticmethod
    def _batch_aggregate(
        results: list[BatchResultItem], total_latency_ms: float
    ) -> BatchSummary:
        """Aggregate batch results into a summary.

        Args:
            results: Individual batch result items.
            total_latency_ms: Total wall-clock time for the batch.

        Returns:
            A BatchSummary with counts and error breakdown.
        """
        total = len(results)
        succeeded = sum(1 for r in results if r.success)
        failed = total - succeeded
        error_summary: dict[str, int] = {}
        for r in results:
            if r.error is not None:
                error_type = type(r.error).__name__
                error_summary[error_type] = error_summary.get(error_type, 0) + 1
        return BatchSummary(
            total=total,
            succeeded=succeeded,
            failed=failed,
            results=results,
            total_latency_ms=total_latency_ms,
            error_summary=error_summary,
        )

    async def _batch_request(
        self,
        requests: list[BatchRequestItem],
        max_concurrency: int = 10,
        fail_fast: bool = False,
    ) -> BatchSummary:
        """Execute multiple requests concurrently with rate limiting.

        Args:
            requests: List of batch request items.
            max_concurrency: Maximum concurrent requests (clamped to 1-20).
            fail_fast: If True, cancel remaining tasks after first failure.

        Returns:
            A BatchSummary with all results.

        Raises:
            ValueError: If requests list is empty.
        """
        if not requests:
            raise ValueError("Batch requests cannot be empty")

        max_concurrency = max(1, min(max_concurrency, 20))
        semaphore = asyncio.Semaphore(max_concurrency)
        cancel_event = asyncio.Event() if fail_fast else None

        async def _execute_one(item: BatchRequestItem) -> BatchResultItem:
            if cancel_event and cancel_event.is_set():
                return BatchResultItem(
                    request_id=item.request_id,
                    success=False,
                    error=CommerceAPIError(0, "cancelled by fail_fast"),
                )
            async with semaphore:
                start = time.time()
                try:
                    data = await self._request(
                        method=item.method,
                        path=item.path,
                        params=dict(item.params),
                        data=dict(item.data),
                    )
                    latency = (time.time() - start) * 1000
                    return BatchResultItem(
                        request_id=item.request_id,
                        success=True,
                        data=data,
                        latency_ms=latency,
                    )
                except Exception as exc:
                    latency = (time.time() - start) * 1000
                    if cancel_event:
                        cancel_event.set()
                    return BatchResultItem(
                        request_id=item.request_id,
                        success=False,
                        error=exc,
                        latency_ms=latency,
                    )

        batch_start = time.time()
        tasks = [asyncio.create_task(_execute_one(item)) for item in requests]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        batch_latency = (time.time() - batch_start) * 1000

        return self._batch_aggregate(list(results), total_latency_ms=batch_latency)

    # ── Health & Lifecycle ────────────────────────────────

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def health_check(self) -> dict[str, Any]:
        """Check API reachability and client configuration.

        Returns:
            Dict with ``configured``, ``has_token``, ``api_reachable``,
            ``metrics``, and optionally ``error`` keys.
        """
        result: dict[str, Any] = {
            "configured": bool(self.app_key and self.app_secret),
            "has_token": bool(self.access_token),
            "api_reachable": False,
            "metrics": self.metrics.get_summary(),
        }
        if not self.BASE_URL:
            return result
        try:
            client = self._get_client()
            resp = await client.head(self.BASE_URL, timeout=5)
            result["api_reachable"] = resp.status_code < 500
        except Exception as exc:
            result["api_reachable"] = False
            result["error"] = str(exc)
        return result


# ── Error & Response Formatting ────────────────────────────


class CommerceAPIError(Exception):
    """Normalized API error across all platforms."""

    def __init__(self, code: int, msg: str) -> None:
        self.code = code
        self.msg = msg
        super().__init__(f"[{code}] {msg}")


def format_error_response(error: Exception) -> str:
    """Format an error into a standardized JSON response string.

    Args:
        error: The exception to format.

    Returns:
        A JSON string with error details.
    """
    if isinstance(error, CommerceAPIError):
        return json.dumps(
            {"error": {"code": error.code, "message": error.msg}},
            ensure_ascii=False,
        )
    return json.dumps(
        {"error": {"message": str(error)}},
        ensure_ascii=False,
    )


def format_response(result: Any) -> str:
    """Format a successful API response as a pretty-printed JSON string.

    Args:
        result: The response data to format (dict, list, or any JSON-serializable type).

    Returns:
        A pretty-printed JSON string.
    """
    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False, indent=2)


def handle_tool_errors(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[str]]:
    """Decorator to handle common MCP tool errors and format responses.

    This decorator wraps an async tool function to:
    - Catch CommerceAPIError and format it as a structured error response
    - Catch any other exceptions and format them as generic error responses
    - Automatically format successful dict/list results as pretty-printed JSON

    Usage:
        @handle_tool_errors
        async def my_tool(param: str) -> str:
            result = await client._request("GET", "path/", params={...})
            return result  # Will be auto-formatted as JSON

    Args:
        func: The async tool function to wrap.

    Returns:
        Wrapped function with error handling and response formatting.
    """

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> str:
        try:
            result = await func(*args, **kwargs)
            return format_response(result)
        except CommerceAPIError as e:
            return format_error_response(e)
        except json.JSONDecodeError as e:
            return json.dumps(
                {"error": {"message": f"Invalid JSON: {e}"}},
                ensure_ascii=False,
            )
        except Exception as e:
            return json.dumps(
                {"error": {"message": str(e)}},
                ensure_ascii=False,
            )

    return wrapper


# ── Configuration Loader ───────────────────────────────────


class ConfigLoader:
    """Load and validate configuration from YAML/JSON files with env var overrides.

    Supports hierarchical config with environment variable overrides.
    Config values can be accessed via dot-notation for nested keys.

    Priority (highest to lowest):
        1. Environment variables (with optional prefix)
        2. Config file values
        3. Default values

    Usage::

        loader = ConfigLoader("config.yaml", env_prefix="MYAPP_")
        db_host = loader.get_nested("database.host", default="localhost")

        # Or load without a file, just env vars
        loader = ConfigLoader(env_prefix="MYAPP_")
        val = loader.get("some_key", default="fallback")

    Args:
        config_path: Path to a YAML (.yaml/.yml) or JSON (.json) config file.
            If None, only environment variables and defaults are used.
        env_prefix: Prefix for environment variable overrides.
            E.g., prefix "MYAPP_" means env var MYAPP_DATABASE_HOST
            overrides config key "database.host".

    Raises:
        FileNotFoundError: If config_path is given but does not exist.
        ValueError: If the file extension is unsupported.
        ImportError: If YAML file is given but PyYAML is not installed.
    """

    def __init__(self, config_path: str | Path | None = None, env_prefix: str = "") -> None:
        self._config_path: Path | None = Path(config_path) if config_path else None
        self._env_prefix = env_prefix
        self._config: dict[str, Any] = {}

        if self._config_path:
            self._config = self.load_file(self._config_path)

    # ── File Loading ──────────────────────────────────────

    @staticmethod
    def load_file(path: str | Path) -> dict[str, Any]:
        """Load config from a file, auto-detecting format by extension.

        Args:
            path: Path to a .yaml, .yml, or .json file.

        Returns:
            Parsed configuration as a dict.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the file extension is not supported.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        suffix = path.suffix.lower()
        if suffix in (".yaml", ".yml"):
            return ConfigLoader.load_yaml(path)
        elif suffix == ".json":
            return ConfigLoader.load_json(path)
        else:
            raise ValueError(f"Unsupported config format '{suffix}': use .yaml, .yml, or .json")

    @staticmethod
    def load_json(path: str | Path) -> dict[str, Any]:
        """Load configuration from a JSON file.

        Args:
            path: Path to a JSON file.

        Returns:
            Parsed configuration as a dict.
        """
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}

    @staticmethod
    def load_yaml(path: str | Path) -> dict[str, Any]:
        """Load configuration from a YAML file.

        Requires PyYAML (``pip install pyyaml``).

        Args:
            path: Path to a YAML file.

        Returns:
            Parsed configuration as a dict.

        Raises:
            ImportError: If PyYAML is not installed.
        """
        try:
            import yaml
        except ImportError:
            raise ImportError(
                "PyYAML is required for YAML config support. "
                "Install it with: pip install pyyaml"
            ) from None
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}

    # ── Value Access ──────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        """Get a top-level config value with env var override.

        Checks for an environment variable named ``{env_prefix}{key}`` (uppercased).
        If not found, falls back to the config file value.

        Args:
            key: Top-level config key.
            default: Default value if key is not found anywhere.

        Returns:
            The resolved config value.
        """
        env_key = f"{self._env_prefix}{key}".upper()
        env_val = os.environ.get(env_key)
        if env_val is not None:
            return env_val
        return self._config.get(key, default)

    def get_nested(self, dotted_key: str, default: Any = None) -> Any:
        """Get a nested config value using dot notation.

        E.g., ``get_nested("database.host")`` accesses ``config["database"]["host"]``.
        Environment variable override: ``PREFIX_DATABASE_HOST``.

        Args:
            dotted_key: Dot-separated key path (e.g., "database.host").
            default: Default value if key path is not found.

        Returns:
            The resolved config value.
        """
        env_key = f"{self._env_prefix}{dotted_key}".upper().replace(".", "_")
        env_val = os.environ.get(env_key)
        if env_val is not None:
            return env_val

        keys = dotted_key.split(".")
        current: Any = self._config
        for k in keys:
            if isinstance(current, dict):
                current = current.get(k)
            else:
                return default
            if current is None:
                return default
        return current

    def apply_env_overrides(self, config: dict[str, Any] | None = None) -> dict[str, Any]:
        """Apply environment variable overrides to a config dict.

        Scans ``os.environ`` for keys starting with ``env_prefix`` and sets
        corresponding nested values in the config dict. Underscores in env
        var names are converted to dots for nesting.

        Args:
            config: Config dict to modify. If None, uses the internal config.

        Returns:
            The modified config dict (same object as input).
        """
        target = config if config is not None else self._config
        prefix = self._env_prefix.upper()

        for env_key, env_val in os.environ.items():
            if not env_key.startswith(prefix) or env_key == prefix:
                continue
            key_part = env_key[len(prefix):].lower()
            if not key_part:
                continue
            self._set_nested(target, key_part, env_val)

        return target

    # ── Merging & Validation ──────────────────────────────

    @staticmethod
    def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        """Deep merge two config dicts. Override values take precedence.

        Nested dicts are merged recursively; non-dict values in ``override``
        replace those in ``base``.

        Args:
            base: The base configuration.
            override: Values to merge on top of base.

        Returns:
            A new merged dict.
        """
        result = dict(base)
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = ConfigLoader.deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    @staticmethod
    def validate_required(config: dict[str, Any], required_keys: list[str]) -> list[str]:
        """Validate that required keys exist in a config dict.

        Supports dot-notation for nested keys (e.g., "database.host").

        Args:
            config: The configuration dict to validate.
            required_keys: List of required key paths.

        Returns:
            List of missing key paths (empty if all present).
        """
        missing: list[str] = []
        for key in required_keys:
            if "." in key:
                keys = key.split(".")
                current: Any = config
                found = True
                for k in keys:
                    if isinstance(current, dict) and k in current:
                        current = current[k]
                    else:
                        found = False
                        break
                if not found:
                    missing.append(key)
            elif key not in config:
                missing.append(key)
        return missing

    # ── Properties ────────────────────────────────────────

    @property
    def config(self) -> dict[str, Any]:
        """Get the loaded configuration dict (read-only copy)."""
        return dict(self._config)

    @property
    def env_prefix(self) -> str:
        """Get the environment variable prefix."""
        return self._env_prefix

    @property
    def config_path(self) -> Path | None:
        """Get the config file path, or None if no file was loaded."""
        return self._config_path

    # ── Internal ──────────────────────────────────────────

    @staticmethod
    def _set_nested(d: dict[str, Any], key: str, value: Any) -> None:
        """Set a value in the config dict.

        The key is set as-is at the top level of the dict.

        Args:
            d: The dict to modify.
            key: The key to set (e.g., "new_key").
            value: The value to set.
        """
        d[key] = value
