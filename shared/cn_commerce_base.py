"""Shared base for Chinese e-commerce platform MCP servers.

Provides unified auth signing, request handling, and error normalization.
"""

from __future__ import annotations

import asyncio
import csv
import functools
import hashlib
import hmac
import io
import json
import logging
import os
import random
import re
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
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
    r"|--|/\*|\*/|;.*\b(DROP|DELETE|UPDATE|INSERT)\b"
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


# ── Rate Limiting Configuration ────────────────────────────


@dataclass
class EndpointRateLimit:
    """Rate limit configuration for a specific API endpoint.

    Attributes:
        endpoint: The API endpoint path (e.g., "/api/order/search").
        requests_per_second: Maximum requests per second for this endpoint.
        burst_size: Maximum burst size (number of requests allowed in a burst).
        cooldown_seconds: Seconds to wait after hitting the limit before resuming.
    """

    endpoint: str
    requests_per_second: float = 10.0
    burst_size: int = 1
    cooldown_seconds: float = 0.0


@dataclass
class PlatformRateLimitConfig:
    """Rate limit configuration for a specific platform.

    Attributes:
        platform: Platform name (e.g., "OCEANENGINE", "TAOBAO").
        default_requests_per_second: Default rate limit for all endpoints on this platform.
        endpoints: Per-endpoint rate limit overrides.
        burst_size: Default burst size for the platform.
        enabled: Whether rate limiting is enabled for this platform.
    """

    platform: str
    default_requests_per_second: float = 10.0
    endpoints: dict[str, EndpointRateLimit] = field(default_factory=dict)
    burst_size: int = 1
    enabled: bool = True

    def get_endpoint_limit(self, endpoint: str) -> EndpointRateLimit:
        """Get the rate limit for a specific endpoint.

        Falls back to the platform default if no endpoint-specific config exists.

        Args:
            endpoint: The API endpoint path.

        Returns:
            EndpointRateLimit for the given endpoint.
        """
        if endpoint in self.endpoints:
            return self.endpoints[endpoint]
        return EndpointRateLimit(
            endpoint=endpoint,
            requests_per_second=self.default_requests_per_second,
            burst_size=self.burst_size,
        )


@dataclass
class RateLimitStats:
    """Statistics and monitoring data for rate limiting.

    Attributes:
        total_requests: Total number of requests processed.
        total_throttled: Number of requests that were throttled (had to wait).
        total_wait_time_ms: Cumulative time spent waiting for rate limits.
        platform_stats: Per-platform statistics.
        endpoint_stats: Per-endpoint statistics.
        last_throttled_at: Timestamp of the last throttling event.
    """

    total_requests: int = 0
    total_throttled: int = 0
    total_wait_time_ms: float = 0.0
    platform_stats: dict[str, dict[str, Any]] = field(default_factory=dict)
    endpoint_stats: dict[str, dict[str, Any]] = field(default_factory=dict)
    last_throttled_at: float = 0.0

    @property
    def throttle_rate(self) -> float:
        """Fraction of requests that were throttled (0.0 to 1.0)."""
        if self.total_requests == 0:
            return 0.0
        return self.total_throttled / self.total_requests

    @property
    def avg_wait_time_ms(self) -> float:
        """Average wait time per throttled request in milliseconds."""
        if self.total_throttled == 0:
            return 0.0
        return self.total_wait_time_ms / self.total_throttled

    def record_throttle(self, platform: str, endpoint: str, wait_ms: float) -> None:
        """Record a throttling event.

        Args:
            platform: Platform name.
            endpoint: Endpoint path.
            wait_ms: Time waited in milliseconds.
        """
        self.total_requests += 1
        self.total_throttled += 1
        self.total_wait_time_ms += wait_ms
        self.last_throttled_at = time.time()

        # Platform stats
        if platform not in self.platform_stats:
            self.platform_stats[platform] = {"requests": 0, "throttled": 0, "wait_ms": 0.0}
        self.platform_stats[platform]["requests"] += 1
        self.platform_stats[platform]["throttled"] += 1
        self.platform_stats[platform]["wait_ms"] += wait_ms

        # Endpoint stats
        key = f"{platform}:{endpoint}"
        if key not in self.endpoint_stats:
            self.endpoint_stats[key] = {"requests": 0, "throttled": 0, "wait_ms": 0.0}
        self.endpoint_stats[key]["requests"] += 1
        self.endpoint_stats[key]["throttled"] += 1
        self.endpoint_stats[key]["wait_ms"] += wait_ms

    def record_request(self, platform: str, endpoint: str) -> None:
        """Record a non-throttled request.

        Args:
            platform: Platform name.
            endpoint: Endpoint path.
        """
        self.total_requests += 1

        if platform not in self.platform_stats:
            self.platform_stats[platform] = {"requests": 0, "throttled": 0, "wait_ms": 0.0}
        self.platform_stats[platform]["requests"] += 1

        key = f"{platform}:{endpoint}"
        if key not in self.endpoint_stats:
            self.endpoint_stats[key] = {"requests": 0, "throttled": 0, "wait_ms": 0.0}
        self.endpoint_stats[key]["requests"] += 1

    def get_summary(self) -> dict[str, Any]:
        """Get a JSON-serializable summary of rate limit statistics.

        Returns:
            Dict with global and per-platform/endpoint breakdowns.
        """
        return {
            "global": {
                "total_requests": self.total_requests,
                "total_throttled": self.total_throttled,
                "throttle_rate": round(self.throttle_rate, 4),
                "total_wait_time_ms": round(self.total_wait_time_ms, 2),
                "avg_wait_time_ms": round(self.avg_wait_time_ms, 2),
            },
            "platforms": {
                p: {
                    "requests": s["requests"],
                    "throttled": s["throttled"],
                    "throttle_rate": round(s["throttled"] / s["requests"], 4) if s["requests"] > 0 else 0.0,
                    "wait_time_ms": round(s["wait_ms"], 2),
                }
                for p, s in self.platform_stats.items()
            },
            "endpoints": {
                e: {
                    "requests": s["requests"],
                    "throttled": s["throttled"],
                    "throttle_rate": round(s["throttled"] / s["requests"], 4) if s["requests"] > 0 else 0.0,
                    "wait_time_ms": round(s["wait_ms"], 2),
                }
                for e, s in self.endpoint_stats.items()
            },
        }

    def reset(self) -> None:
        """Reset all collected statistics."""
        self.total_requests = 0
        self.total_throttled = 0
        self.total_wait_time_ms = 0.0
        self.platform_stats.clear()
        self.endpoint_stats.clear()
        self.last_throttled_at = 0.0


class ConfigurableRateLimiter:
    """Advanced rate limiter with per-platform and per-endpoint configuration.

    Supports:
    - Per-platform rate limits
    - Per-endpoint rate limits within a platform
    - Dynamic adjustment of rate limits at runtime
    - Burst control
    - Statistics and monitoring

    Usage::

        config = RateLimitConfig(
            platforms={
                "OCEANENGINE": PlatformRateLimitConfig(
                    platform="OCEANENGINE",
                    default_requests_per_second=5.0,
                    endpoints={
                        "/api/order/search": EndpointRateLimit(
                            endpoint="/api/order/search",
                            requests_per_second=2.0,
                        ),
                    },
                ),
            },
        )
        limiter = ConfigurableRateLimiter(config)
        await limiter.acquire("OCEANENGINE", "/api/order/search")
    """

    def __init__(self, config: "RateLimitConfig | None" = None) -> None:
        """Initialize the configurable rate limiter.

        Args:
            config: Rate limit configuration. Uses defaults if not provided.
        """
        self._config = config or RateLimitConfig()
        self._stats = RateLimitStats()
        self._limiters: dict[str, RateLimiter] = {}
        self._lock = threading.Lock()

    @property
    def stats(self) -> RateLimitStats:
        """Get the rate limit statistics collector."""
        return self._stats

    @property
    def config(self) -> "RateLimitConfig":
        """Get the current rate limit configuration."""
        return self._config

    def _get_limiter_key(self, platform: str, endpoint: str) -> str:
        """Generate a cache key for a platform+endpoint limiter."""
        return f"{platform}:{endpoint}"

    def _get_or_create_limiter(self, platform: str, endpoint: str) -> RateLimiter:
        """Get or create a RateLimiter for the given platform+endpoint.

        Args:
            platform: Platform name.
            endpoint: Endpoint path.

        Returns:
            A RateLimiter instance configured for the given platform+endpoint.
        """
        key = self._get_limiter_key(platform, endpoint)
        with self._lock:
            if key not in self._limiters:
                platform_config = self._config.get_platform_config(platform)
                if not platform_config.enabled:
                    # No rate limiting for this platform
                    self._limiters[key] = RateLimiter(requests_per_second=float("inf"))
                else:
                    ep_limit = platform_config.get_endpoint_limit(endpoint)
                    self._limiters[key] = RateLimiter(
                        requests_per_second=ep_limit.requests_per_second
                    )
            return self._limiters[key]

    async def acquire(self, platform: str, endpoint: str) -> None:
        """Acquire a rate limit slot for the given platform and endpoint.

        Will wait if necessary to respect the configured rate limit.
        Records statistics for monitoring.

        Args:
            platform: Platform name.
            endpoint: API endpoint path.
        """
        platform_config = self._config.get_platform_config(platform)
        if not platform_config.enabled:
            self._stats.record_request(platform, endpoint)
            return

        limiter = self._get_or_create_limiter(platform, endpoint)
        start = time.time()
        await limiter.acquire()
        elapsed_ms = (time.time() - start) * 1000

        if elapsed_ms > 1.0:  # Only count meaningful waits
            self._stats.record_throttle(platform, endpoint, elapsed_ms)
        else:
            self._stats.record_request(platform, endpoint)

    def update_platform_config(self, platform: str, config: PlatformRateLimitConfig) -> None:
        """Dynamically update the rate limit configuration for a platform.

        Clears cached limiters for the affected platform so they will be
        recreated with the new configuration on next use.

        Args:
            platform: Platform name to update.
            config: New platform rate limit configuration.
        """
        self._config.platforms[platform] = config
        # Clear cached limiters for this platform
        with self._lock:
            keys_to_remove = [k for k in self._limiters if k.startswith(f"{platform}:")]
            for key in keys_to_remove:
                del self._limiters[key]
        logger.info(f"Rate limit config updated for platform: {platform}")

    def update_endpoint_limit(
        self,
        platform: str,
        endpoint: str,
        requests_per_second: float,
        burst_size: int = 1,
    ) -> None:
        """Dynamically update the rate limit for a specific endpoint.

        Creates the platform config if it doesn't exist.

        Args:
            platform: Platform name.
            endpoint: Endpoint path.
            requests_per_second: New rate limit.
            burst_size: New burst size.
        """
        if platform not in self._config.platforms:
            self._config.platforms[platform] = PlatformRateLimitConfig(platform=platform)
        platform_config = self._config.platforms[platform]
        platform_config.endpoints[endpoint] = EndpointRateLimit(
            endpoint=endpoint,
            requests_per_second=requests_per_second,
            burst_size=burst_size,
        )
        # Clear the cached limiter for this specific endpoint
        key = self._get_limiter_key(platform, endpoint)
        with self._lock:
            self._limiters.pop(key, None)
        logger.info(f"Rate limit updated: {platform}:{endpoint} -> {requests_per_second} rps")

    def get_stats_summary(self) -> dict[str, Any]:
        """Get a summary of rate limiting statistics.

        Returns:
            Dict with configuration and statistics.
        """
        return {
            "config": self._config.to_dict(),
            "stats": self._stats.get_summary(),
        }

    def reset_stats(self) -> None:
        """Reset all rate limiting statistics."""
        self._stats.reset()


@dataclass
class RateLimitConfig:
    """Top-level rate limit configuration.

    Manages per-platform rate limit settings and provides defaults.

    Attributes:
        platforms: Per-platform rate limit configurations.
        default_requests_per_second: Global default rate limit.
        default_burst_size: Global default burst size.
        enabled: Global toggle for rate limiting.
    """

    platforms: dict[str, PlatformRateLimitConfig] = field(default_factory=dict)
    default_requests_per_second: float = 10.0
    default_burst_size: int = 1
    enabled: bool = True

    def get_platform_config(self, platform: str) -> PlatformRateLimitConfig:
        """Get the rate limit config for a platform.

        Returns the platform-specific config if it exists, otherwise
        creates a default config for the platform.

        Args:
            platform: Platform name.

        Returns:
            PlatformRateLimitConfig for the given platform.
        """
        if platform in self.platforms:
            return self.platforms[platform]
        return PlatformRateLimitConfig(
            platform=platform,
            default_requests_per_second=self.default_requests_per_second,
            burst_size=self.default_burst_size,
            enabled=self.enabled,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert config to a JSON-serializable dictionary.

        Returns:
            Dictionary representation of the configuration.
        """
        return {
            "enabled": self.enabled,
            "default_requests_per_second": self.default_requests_per_second,
            "default_burst_size": self.default_burst_size,
            "platforms": {
                name: {
                    "platform": p.platform,
                    "default_requests_per_second": p.default_requests_per_second,
                    "burst_size": p.burst_size,
                    "enabled": p.enabled,
                    "endpoints": {
                        ep: {
                            "endpoint": e.endpoint,
                            "requests_per_second": e.requests_per_second,
                            "burst_size": e.burst_size,
                            "cooldown_seconds": e.cooldown_seconds,
                        }
                        for ep, e in p.endpoints.items()
                    },
                }
                for name, p in self.platforms.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RateLimitConfig":
        """Create a RateLimitConfig from a dictionary.

        Args:
            data: Dictionary with configuration values.

        Returns:
            A new RateLimitConfig instance.
        """
        platforms: dict[str, PlatformRateLimitConfig] = {}
        for name, p_data in data.get("platforms", {}).items():
            endpoints: dict[str, EndpointRateLimit] = {}
            for ep, e_data in p_data.get("endpoints", {}).items():
                endpoints[ep] = EndpointRateLimit(
                    endpoint=e_data.get("endpoint", ep),
                    requests_per_second=e_data.get("requests_per_second", 10.0),
                    burst_size=e_data.get("burst_size", 1),
                    cooldown_seconds=e_data.get("cooldown_seconds", 0.0),
                )
            platforms[name] = PlatformRateLimitConfig(
                platform=p_data.get("platform", name),
                default_requests_per_second=p_data.get("default_requests_per_second", 10.0),
                endpoints=endpoints,
                burst_size=p_data.get("burst_size", 1),
                enabled=p_data.get("enabled", True),
            )

        return cls(
            platforms=platforms,
            default_requests_per_second=data.get("default_requests_per_second", 10.0),
            default_burst_size=data.get("default_burst_size", 1),
            enabled=data.get("enabled", True),
        )


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

    # ── Batch Operations ──────────────────────────────────

    @staticmethod
    def _batch_aggregate(
        results: list[BatchResultItem],
        total_latency_ms: float,
    ) -> BatchSummary:
        """Aggregate individual batch results into a summary.

        Args:
            results: List of individual result items.
            total_latency_ms: Wall-clock time for the entire batch.

        Returns:
            A BatchSummary with counts and error breakdown.
        """
        succeeded = sum(1 for r in results if r.success)
        failed = len(results) - succeeded
        error_summary: dict[str, int] = {}
        for r in results:
            if r.error is not None:
                key = type(r.error).__name__
                error_summary[key] = error_summary.get(key, 0) + 1
        return BatchSummary(
            total=len(results),
            succeeded=succeeded,
            failed=failed,
            results=results,
            total_latency_ms=total_latency_ms,
            error_summary=error_summary,
        )

    async def _batch_request(
        self,
        requests: list[BatchRequestItem],
        max_concurrency: int = 5,
        fail_fast: bool = False,
    ) -> BatchSummary:
        """Execute multiple API requests concurrently.

        Args:
            requests: List of batch request items to execute.
            max_concurrency: Maximum concurrent requests (clamped to 1-20).
            fail_fast: If True, stop submitting new requests after the first error.

        Returns:
            A BatchSummary with all individual results.

        Raises:
            ValueError: If the request list is empty.
        """
        if not requests:
            raise ValueError("Request list cannot be empty")

        max_concurrency = max(1, min(max_concurrency, 20))
        semaphore = asyncio.Semaphore(max_concurrency)
        batch_start = time.time()
        results: list[BatchResultItem] = []
        cancelled = asyncio.Event()

        async def _execute_one(item: BatchRequestItem) -> BatchResultItem:
            if fail_fast and cancelled.is_set():
                return BatchResultItem(
                    request_id=item.request_id,
                    success=False,
                    error=RuntimeError("Cancelled due to fail_fast"),
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
                    elapsed = (time.time() - start) * 1000
                    return BatchResultItem(
                        request_id=item.request_id,
                        success=True,
                        data=data,
                        latency_ms=elapsed,
                    )
                except Exception as exc:
                    elapsed = (time.time() - start) * 1000
                    if fail_fast:
                        cancelled.set()
                    return BatchResultItem(
                        request_id=item.request_id,
                        success=False,
                        error=exc,
                        latency_ms=elapsed,
                    )

        tasks = [_execute_one(item) for item in requests]
        results = list(await asyncio.gather(*tasks))
        total_latency = (time.time() - batch_start) * 1000
        return self._batch_aggregate(results, total_latency_ms=total_latency)


# ── Batch Operations ──────────────────────────────────────


@dataclass
class BatchRequestItem:
    """A single request within a batch operation.

    Attributes:
        method: HTTP method ("GET" or "POST").
        path: API endpoint path.
        params: Query parameters.
        data: Request body data.
        request_id: Caller-assigned identifier for correlation.
    """

    method: str = ""
    path: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)
    request_id: str = ""


@dataclass
class BatchResultItem:
    """Result of a single request within a batch.

    Attributes:
        request_id: Matches the request_id from BatchRequestItem.
        success: Whether the request succeeded.
        data: Response data (None on failure).
        error: The exception that caused the failure (None on success).
        latency_ms: Request duration in milliseconds.
    """

    request_id: str = ""
    success: bool = True
    data: Any = None
    error: Exception | None = None
    latency_ms: float = 0.0


@dataclass
class BatchSummary:
    """Aggregated summary of a batch operation.

    Attributes:
        total: Total number of requests.
        succeeded: Number of successful requests.
        failed: Number of failed requests.
        results: Individual result items.
        total_latency_ms: Wall-clock time for the entire batch.
        error_summary: Count of errors grouped by exception type name.
    """

    total: int = 0
    succeeded: int = 0
    failed: int = 0
    results: list[BatchResultItem] = field(default_factory=list)
    total_latency_ms: float = 0.0
    error_summary: dict[str, int] = field(default_factory=dict)


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


# ── Webhook Support ─────────────────────────────────────────


class WebhookEventType(StrEnum):
    """Supported webhook event types for e-commerce platforms.

    Attributes:
        ORDER_UPDATE: Order status changes (created, paid, shipped, completed, cancelled).
        INVENTORY_CHANGE: Stock level updates (low stock, out of stock, restocked).
        PRODUCT_UPDATE: Product information changes (price, description, images).
        REFUND_REQUEST: Refund initiated or processed.
        PAYMENT_RECEIVED: Payment confirmed for an order.
        SHIPPING_UPDATE: Shipping status changes (shipped, in transit, delivered).
        REVIEW_SUBMITTED: New customer review submitted.
        COUPON_USED: Coupon or promotion code used.
        CUSTOM: User-defined custom event type.
    """

    ORDER_UPDATE = "order_update"
    INVENTORY_CHANGE = "inventory_change"
    PRODUCT_UPDATE = "product_update"
    REFUND_REQUEST = "refund_request"
    PAYMENT_RECEIVED = "payment_received"
    SHIPPING_UPDATE = "shipping_update"
    REVIEW_SUBMITTED = "review_submitted"
    COUPON_USED = "coupon_used"
    CUSTOM = "custom"


@dataclass
class WebhookSubscription:
    """Represents a registered webhook subscription.

    Attributes:
        subscription_id: Unique identifier for the subscription.
        url: Callback URL where webhook events will be delivered.
        event_types: List of event types this subscription listens to.
        secret: Shared secret used for HMAC signature verification.
        platform: Platform name this subscription belongs to.
        is_active: Whether the subscription is currently active.
        created_at: ISO 8601 timestamp when the subscription was created.
        last_triggered_at: ISO 8601 timestamp of last event delivery.
        failure_count: Number of consecutive delivery failures.
        metadata: Optional key-value pairs for additional configuration.
    """

    subscription_id: str
    url: str
    event_types: list[str]
    secret: str
    platform: str = ""
    is_active: bool = True
    created_at: str = ""
    last_triggered_at: str = ""
    failure_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()
        if not self.subscription_id:
            self.subscription_id = str(uuid.uuid4())
        if not self.secret:
            self.secret = hashlib.sha256(f"{self.subscription_id}:{self.url}:{time.time()}".encode()).hexdigest()


@dataclass
class WebhookEvent:
    """Represents a webhook event to be delivered.

    Attributes:
        event_id: Unique identifier for this event instance.
        event_type: Type of the event (must match WebhookEventType values).
        platform: Platform that generated the event.
        payload: Event data as a dictionary.
        timestamp: ISO 8601 timestamp of when the event occurred.
        source: Source identifier (e.g., order_id, product_id).
        version: API version for the event format.
    """

    event_id: str = ""
    event_type: str = ""
    platform: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    source: str = ""
    version: str = "1.0"

    def __post_init__(self) -> None:
        if not self.event_id:
            self.event_id = str(uuid.uuid4())
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        """Convert event to a dictionary for JSON serialization."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "platform": self.platform,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "source": self.source,
            "version": self.version,
        }


class WebhookSignatureVerifier:
    """Verifies webhook signatures using HMAC-SHA256.

    Used to ensure webhook payloads are authentic and have not been tampered with.
    Implements the standard HMAC-based signature verification used by major platforms.

    Usage:
        verifier = WebhookSignatureVerifier(secret="your_secret")
        is_valid = verifier.verify(payload_bytes, signature_header)
    """

    def __init__(self, secret: str, algorithm: str = "sha256") -> None:
        """Initialize the verifier with a shared secret.

        Args:
            secret: The shared secret key for HMAC computation.
            algorithm: Hash algorithm to use (default: sha256).
        """
        self.secret = secret
        self.algorithm = algorithm

    def sign(self, payload: bytes) -> str:
        """Generate HMAC signature for a payload.

        Args:
            payload: Raw payload bytes to sign.

        Returns:
            Hex-encoded HMAC signature string.
        """
        hash_func = getattr(hashlib, self.algorithm)
        return hmac.new(self.secret.encode(), payload, hash_func).hexdigest()

    def verify(self, payload: bytes, signature: str) -> bool:
        """Verify a payload signature.

        Args:
            payload: Raw payload bytes.
            signature: Signature to verify (hex-encoded string).

        Returns:
            True if signature is valid, False otherwise.
        """
        if not signature:
            return False
        expected = self.sign(payload)
        return hmac.compare_digest(expected, signature)

    @staticmethod
    def extract_signature(signature_header: str, prefix: str = "") -> str:
        """Extract signature value from a header string.

        Many platforms prefix signatures (e.g., "sha256=abc123").
        This method strips such prefixes.

        Args:
            signature_header: Raw signature header value.
            prefix: Optional prefix to strip (e.g., "sha256=").

        Returns:
            Cleaned signature string.
        """
        if prefix and signature_header.startswith(prefix):
            return signature_header[len(prefix) :]
        return signature_header


class WebhookDeliveryError(Exception):
    """Raised when webhook delivery fails.

    Attributes:
        subscription_id: ID of the failed subscription.
        url: Target URL that failed.
        status_code: HTTP status code (0 if connection failed).
        message: Error description.
    """

    def __init__(
        self,
        subscription_id: str,
        url: str,
        status_code: int = 0,
        message: str = "",
    ) -> None:
        self.subscription_id = subscription_id
        self.url = url
        self.status_code = status_code
        self.message = message or f"Failed to deliver webhook to {url}"
        super().__init__(self.message)


@dataclass
class WebhookDeliveryResult:
    """Result of a webhook delivery attempt.

    Attributes:
        subscription_id: ID of the subscription.
        event_id: ID of the event that was delivered.
        success: Whether delivery succeeded.
        status_code: HTTP response status code.
        latency_ms: Delivery time in milliseconds.
        error: Error message if delivery failed.
        attempt: Which attempt number this was (1-based).
    """

    subscription_id: str
    event_id: str
    success: bool
    status_code: int = 0
    latency_ms: float = 0.0
    error: str = ""
    attempt: int = 1


class WebhookManager:
    """Manages webhook subscriptions and event delivery.

    Provides a complete webhook lifecycle management system:
    - Register and unregister webhook subscriptions
    - Trigger events to matching subscriptions
    - Verify webhook signatures
    - Track delivery metrics and failures
    - Automatic retry with exponential backoff

    Usage:
        manager = WebhookManager()
        sub = manager.subscribe(
            url="https://example.com/webhook",
            event_types=["order_update", "inventory_change"],
        )
        await manager.trigger(WebhookEvent(event_type="order_update", payload={...}))
    """

    def __init__(
        self,
        max_delivery_retries: int = 3,
        delivery_timeout: float = 30.0,
        max_consecutive_failures: int = 10,
    ) -> None:
        """Initialize the webhook manager.

        Args:
            max_delivery_retries: Max retry attempts for failed deliveries.
            delivery_timeout: HTTP request timeout in seconds.
            max_consecutive_failures: Auto-disable subscription after this many failures.
        """
        self._subscriptions: dict[str, WebhookSubscription] = {}
        self._event_history: list[WebhookEvent] = []
        self._delivery_results: list[WebhookDeliveryResult] = []
        self._delivery_callbacks: list[Callable[..., Awaitable[WebhookDeliveryResult]]] = []
        self._max_delivery_retries = max_delivery_retries
        self._delivery_timeout = delivery_timeout
        self._max_consecutive_failures = max_consecutive_failures
        self._lock = threading.Lock()

    def subscribe(
        self,
        url: str,
        event_types: list[str],
        secret: str = "",
        platform: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> WebhookSubscription:
        """Register a new webhook subscription.

        Args:
            url: Callback URL for event delivery.
            event_types: List of event type strings to subscribe to.
            secret: Shared secret for signature verification (auto-generated if empty).
            platform: Platform identifier.
            metadata: Optional metadata for the subscription.

        Returns:
            The created WebhookSubscription.

        Raises:
            ValueError: If url is empty or event_types is empty.
        """
        if not url:
            raise ValueError("Webhook URL cannot be empty")
        if not event_types:
            raise ValueError("At least one event type must be specified")

        # Validate event types
        valid_types = {e.value for e in WebhookEventType}
        for et in event_types:
            if et not in valid_types:
                raise ValueError(f"Invalid event type: {et}")

        subscription = WebhookSubscription(
            subscription_id=str(uuid.uuid4()),
            url=url,
            event_types=event_types,
            secret=secret,
            platform=platform,
            metadata=metadata or {},
        )

        with self._lock:
            self._subscriptions[subscription.subscription_id] = subscription

        logger.info(f"Webhook subscription created: {subscription.subscription_id} " f"for events {event_types}")
        return subscription

    def unsubscribe(self, subscription_id: str) -> bool:
        """Remove a webhook subscription.

        Args:
            subscription_id: ID of the subscription to remove.

        Returns:
            True if subscription was found and removed, False otherwise.
        """
        with self._lock:
            if subscription_id in self._subscriptions:
                del self._subscriptions[subscription_id]
                logger.info(f"Webhook subscription removed: {subscription_id}")
                return True
        return False

    def get_subscription(self, subscription_id: str) -> WebhookSubscription | None:
        """Get a subscription by ID.

        Args:
            subscription_id: ID of the subscription.

        Returns:
            The WebhookSubscription if found, None otherwise.
        """
        return self._subscriptions.get(subscription_id)

    def list_subscriptions(
        self,
        event_type: str | None = None,
        platform: str | None = None,
        active_only: bool = True,
    ) -> list[WebhookSubscription]:
        """List subscriptions with optional filtering.

        Args:
            event_type: Filter by event type.
            platform: Filter by platform.
            active_only: Only return active subscriptions.

        Returns:
            List of matching subscriptions.
        """
        results = []
        for sub in self._subscriptions.values():
            if active_only and not sub.is_active:
                continue
            if event_type and event_type not in sub.event_types:
                continue
            if platform and sub.platform != platform:
                continue
            results.append(sub)
        return results

    def update_subscription(
        self,
        subscription_id: str,
        url: str | None = None,
        event_types: list[str] | None = None,
        is_active: bool | None = None,
        secret: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WebhookSubscription | None:
        """Update an existing subscription.

        Args:
            subscription_id: ID of the subscription to update.
            url: New callback URL.
            event_types: New event types list.
            is_active: New active status.
            secret: New shared secret.
            metadata: New metadata dict.

        Returns:
            Updated WebhookSubscription if found, None otherwise.
        """
        with self._lock:
            sub = self._subscriptions.get(subscription_id)
            if not sub:
                return None
            if url is not None:
                sub.url = url
            if event_types is not None:
                sub.event_types = event_types
            if is_active is not None:
                sub.is_active = is_active
            if secret is not None:
                sub.secret = secret
            if metadata is not None:
                sub.metadata = metadata
            return sub

    def add_delivery_callback(self, callback: Callable[..., Awaitable[WebhookDeliveryResult]]) -> None:
        """Register a callback for webhook delivery.

        This allows custom HTTP client injection for actual delivery.

        Args:
            callback: Async function that takes (subscription, event, payload_bytes, signature)
                     and returns a WebhookDeliveryResult.
        """
        self._delivery_callbacks.append(callback)

    def _prepare_delivery(self, subscription: WebhookSubscription, event: WebhookEvent) -> tuple[bytes, str]:
        """Prepare payload and signature for delivery.

        Args:
            subscription: Target subscription.
            event: Event to deliver.

        Returns:
            Tuple of (payload_bytes, signature_hex).
        """
        payload_dict = {
            "event": event.to_dict(),
            "subscription_id": subscription.subscription_id,
            "delivery_timestamp": datetime.now(UTC).isoformat(),
        }
        payload_bytes = json.dumps(payload_dict, ensure_ascii=False, sort_keys=True).encode()
        verifier = WebhookSignatureVerifier(secret=subscription.secret)
        signature = verifier.sign(payload_bytes)
        return payload_bytes, signature

    async def _deliver_with_retry(
        self,
        subscription: WebhookSubscription,
        event: WebhookEvent,
    ) -> WebhookDeliveryResult:
        """Attempt delivery with retry logic.

        Args:
            subscription: Target subscription.
            event: Event to deliver.

        Returns:
            WebhookDeliveryResult with delivery status.
        """
        payload_bytes, signature = self._prepare_delivery(subscription, event)
        last_error = ""

        for attempt in range(1, self._max_delivery_retries + 1):
            start_time = time.time()
            result: WebhookDeliveryResult | None = None

            for callback in self._delivery_callbacks:
                try:
                    result = await callback(subscription, event, payload_bytes, signature)
                    result.attempt = attempt
                    if result.success:
                        with self._lock:
                            subscription.last_triggered_at = datetime.now(UTC).isoformat()
                            subscription.failure_count = 0
                        return result
                    last_error = result.error or f"HTTP {result.status_code}"
                except Exception as exc:
                    last_error = str(exc)
                    result = WebhookDeliveryResult(
                        subscription_id=subscription.subscription_id,
                        event_id=event.event_id,
                        success=False,
                        error=last_error,
                        attempt=attempt,
                        latency_ms=(time.time() - start_time) * 1000,
                    )

            if attempt < self._max_delivery_retries:
                delay = min(2**attempt, 30)
                await asyncio.sleep(delay)

        # All retries exhausted
        with self._lock:
            subscription.failure_count += 1
            if subscription.failure_count >= self._max_consecutive_failures:
                subscription.is_active = False
                logger.warning(
                    f"Webhook subscription {subscription.subscription_id} auto-disabled "
                    f"after {subscription.failure_count} consecutive failures"
                )

        return WebhookDeliveryResult(
            subscription_id=subscription.subscription_id,
            event_id=event.event_id,
            success=False,
            status_code=0,
            error=f"Max retries ({self._max_delivery_retries}) exhausted: {last_error}",
            attempt=self._max_delivery_retries,
        )

    async def trigger(self, event: WebhookEvent) -> list[WebhookDeliveryResult]:
        """Trigger a webhook event to all matching subscriptions.

        Finds all active subscriptions matching the event type and delivers
        the event to each one.

        Args:
            event: The WebhookEvent to deliver.

        Returns:
            List of WebhookDeliveryResult for each subscription.
        """
        if not event.event_type:
            raise ValueError("Event type cannot be empty")

        # Record event
        self._event_history.append(event)

        # Find matching subscriptions
        matching = self.list_subscriptions(event_type=event.event_type, active_only=True)

        if not matching:
            logger.debug(f"No subscriptions for event type: {event.event_type}")
            return []

        # Deliver to all matching subscriptions
        results: list[WebhookDeliveryResult] = []
        for sub in matching:
            result = await self._deliver_with_retry(sub, event)
            results.append(result)
            self._delivery_results.append(result)

        succeeded = sum(1 for r in results if r.success)
        logger.info(f"Webhook event {event.event_id} delivered: " f"{succeeded}/{len(results)} succeeded")
        return results

    def verify_signature(
        self,
        payload: bytes,
        signature: str,
        secret: str,
        algorithm: str = "sha256",
    ) -> bool:
        """Verify a webhook payload signature.

        Args:
            payload: Raw request body bytes.
            signature: Signature from the request header.
            secret: Shared secret for verification.
            algorithm: Hash algorithm (default: sha256).

        Returns:
            True if signature is valid.
        """
        verifier = WebhookSignatureVerifier(secret=secret, algorithm=algorithm)
        return verifier.verify(payload, signature)

    def get_delivery_stats(self) -> dict[str, Any]:
        """Get webhook delivery statistics.

        Returns:
            Dictionary with delivery metrics.
        """
        total = len(self._delivery_results)
        succeeded = sum(1 for r in self._delivery_results if r.success)
        failed = total - succeeded
        avg_latency = sum(r.latency_ms for r in self._delivery_results) / total if total > 0 else 0.0

        return {
            "total_deliveries": total,
            "succeeded": succeeded,
            "failed": failed,
            "success_rate": round(succeeded / total, 4) if total > 0 else 0.0,
            "avg_latency_ms": round(avg_latency, 2),
            "active_subscriptions": len(self.list_subscriptions(active_only=True)),
            "total_subscriptions": len(self._subscriptions),
            "total_events": len(self._event_history),
        }

    def clear_history(self) -> None:
        """Clear event history and delivery results."""
        self._event_history.clear()
        self._delivery_results.clear()


# ── Batch Operations ──────────────────────────────────────


@dataclass
class ExportFormat(StrEnum):
    """Supported export formats."""

    CSV = "csv"
    JSON = "json"
    EXCEL = "excel"


@dataclass
class ExportConfig:
    """Configuration for data export.

    Attributes:
        format: Export format (csv, json, excel).
        fields: List of field names to include (None = all fields).
        filename: Output filename (without extension).
        output_dir: Directory to write the file.
        page: Page number for paginated export (1-indexed, 0 = all data).
        page_size: Number of items per page.
        flatten_nested: Whether to flatten nested dicts (dot notation).
        encoding: Character encoding for CSV output.
    """

    format: ExportFormat = field(default_factory=lambda: ExportFormat.CSV)
    fields: list[str] | None = None
    filename: str = "export"
    output_dir: str = "."
    page: int = 0
    page_size: int = 1000
    flatten_nested: bool = True
    encoding: str = "utf-8"


class DataExporter:
    """Export e-commerce data to CSV, JSON, or Excel formats.

    Supports custom field selection, pagination, and nested dict flattening.

    Usage:
        exporter = DataExporter()
        result = exporter.export(data, ExportConfig(format=ExportFormat.CSV, fields=["id", "name"]))
    """

    @staticmethod
    def _flatten_dict(d: dict[str, Any], parent_key: str = "", sep: str = ".") -> dict[str, Any]:
        """Flatten a nested dictionary using dot notation.

        Args:
            d: Dictionary to flatten.
            parent_key: Prefix for keys (used in recursion).
            sep: Separator between nested keys.

        Returns:
            Flattened dictionary.
        """
        items: list[tuple[str, Any]] = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(DataExporter._flatten_dict(v, new_key, sep=sep).items())
            elif isinstance(v, list):
                # Convert lists to JSON string for flat representation
                items.append((new_key, json.dumps(v, ensure_ascii=False)))
            else:
                items.append((new_key, v))
        return dict(items)

    @staticmethod
    def _select_fields(data: list[dict[str, Any]], fields: list[str] | None) -> list[dict[str, Any]]:
        """Select specific fields from data records.

        Args:
            data: List of data records.
            fields: List of field names to keep (None = keep all).

        Returns:
            List of records with only the selected fields.
        """
        if fields is None:
            return data
        return [{k: row.get(k) for k in fields} for row in data]

    @staticmethod
    def _paginate_data(
        data: list[dict[str, Any]], page: int, page_size: int
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Apply pagination to data.

        Args:
            data: Full dataset.
            page: Page number (1-indexed, 0 = return all).
            page_size: Items per page.

        Returns:
            Tuple of (paginated_data, pagination_info).
        """
        total = len(data)
        if page <= 0:
            return data, {
                "total": total,
                "page": 0,
                "page_size": total,
                "total_pages": 1,
                "has_next": False,
                "has_prev": False,
            }

        total_pages = max(1, (total + page_size - 1) // page_size)
        start = (page - 1) * page_size
        end = start + page_size
        page_data = data[start:end]

        return page_data, {
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        }

    @classmethod
    def export(
        cls,
        data: list[dict[str, Any]],
        config: ExportConfig | None = None,
    ) -> dict[str, Any]:
        """Export data to the specified format.

        Args:
            data: List of data records to export.
            config: Export configuration. Uses defaults if not provided.

        Returns:
            Dict with ``file_path``, ``format``, ``record_count``,
            ``fields``, and ``pagination`` keys.
        """
        if config is None:
            config = ExportConfig()

        # Flatten nested dicts if requested
        if config.flatten_nested:
            data = [cls._flatten_dict(row) for row in data]

        # Apply pagination
        page_data, pagination = cls._paginate_data(data, config.page, config.page_size)

        # Select fields
        page_data = cls._select_fields(page_data, config.fields)

        # Determine fields used
        if page_data:
            actual_fields = list(page_data[0].keys())
        else:
            actual_fields = config.fields or []

        # Build output path
        ext = config.format.value
        output_dir = Path(config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        file_path = output_dir / f"{config.filename}.{ext}"

        # Export based on format
        if config.format == ExportFormat.CSV:
            cls._export_csv(page_data, actual_fields, file_path, config.encoding)
        elif config.format == ExportFormat.JSON:
            cls._export_json(page_data, file_path)
        elif config.format == ExportFormat.EXCEL:
            cls._export_excel(page_data, actual_fields, file_path)

        logger.info(f"Exported {len(page_data)} records to {file_path}")

        return {
            "file_path": str(file_path),
            "format": config.format.value,
            "record_count": len(page_data),
            "fields": actual_fields,
            "pagination": pagination,
        }

    @staticmethod
    def _export_csv(
        data: list[dict[str, Any]],
        fields: list[str],
        file_path: Path,
        encoding: str = "utf-8",
    ) -> None:
        """Export data to CSV file."""
        with open(file_path, "w", newline="", encoding=encoding) as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(data)

    @staticmethod
    def _export_json(data: list[dict[str, Any]], file_path: Path) -> None:
        """Export data to JSON file."""
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)

    @staticmethod
    def _export_excel(
        data: list[dict[str, Any]],
        fields: list[str],
        file_path: Path,
    ) -> None:
        """Export data to Excel (.xlsx) file."""
        try:
            import openpyxl
        except ImportError:
            raise ImportError("openpyxl is required for Excel export. Install it with: pip install openpyxl")

        wb = openpyxl.Workbook()
        ws = wb.active
        if ws is None:
            ws = wb.create_sheet()

        # Write header
        ws.append(fields)

        # Write data rows
        for row in data:
            ws.append([row.get(f) for f in fields])

        wb.save(str(file_path))

    @classmethod
    def export_to_string(
        cls,
        data: list[dict[str, Any]],
        format: ExportFormat = ExportFormat.JSON,
        fields: list[str] | None = None,
        flatten_nested: bool = True,
    ) -> str:
        """Export data to an in-memory string (no file written).

        Args:
            data: List of data records.
            format: Export format (csv or json; excel not supported for strings).
            fields: Fields to include (None = all).
            flatten_nested: Whether to flatten nested dicts.

        Returns:
            Exported data as a string.
        """
        if flatten_nested:
            data = [cls._flatten_dict(row) for row in data]

        data = cls._select_fields(data, fields)

        if format == ExportFormat.CSV:
            if not data:
                return ""
            actual_fields = list(data[0].keys())
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=actual_fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(data)
            return output.getvalue()
        elif format == ExportFormat.JSON:
            return json.dumps(data, ensure_ascii=False, indent=2, default=str)
        else:
            raise ValueError("export_to_string does not support Excel format")


# ── API Versioning ────────────────────────────────────────


class VersionStatus(StrEnum):
    """Lifecycle status of an API version.

    Attributes:
        ACTIVE: The version is fully supported and recommended for use.
        DEPRECATED: The version still works but will be removed in a future release.
        SUNSET: The version is no longer available; requests are rejected.
    """

    ACTIVE = "active"
    DEPRECATED = "deprecated"
    SUNSET = "sunset"


@dataclass(order=True, frozen=True)
class APIVersion:
    """Represents a semantic API version.

    Supports comparison operators so versions can be sorted and compared.

    Attributes:
        major: Major version number (breaking changes).
        minor: Minor version number (backwards-compatible features).
        patch: Patch version number (backwards-compatible fixes).
    """

    major: int
    minor: int = 0
    patch: int = 0

    def __str__(self) -> str:
        if self.patch:
            return f"{self.major}.{self.minor}.{self.patch}"
        if self.minor:
            return f"{self.major}.{self.minor}"
        return str(self.major)

    @classmethod
    def parse(cls, version_str: str) -> APIVersion:
        """Parse a version string like '2', '2.1', or '2.1.3' into an APIVersion.

        Args:
            version_str: Version string to parse.

        Returns:
            An APIVersion instance.

        Raises:
            ValueError: If the version string is invalid.
        """
        if not version_str or not version_str.strip():
            raise ValueError("Version string cannot be empty")
        parts = version_str.strip().split(".")
        if len(parts) > 3:
            raise ValueError(f"Invalid version string '{version_str}': too many segments")
        try:
            nums = [int(p) for p in parts]
        except ValueError:
            raise ValueError(f"Invalid version string '{version_str}': non-numeric segment")
        if any(n < 0 for n in nums):
            raise ValueError(f"Invalid version string '{version_str}': negative segment")
        # Pad to 3 components
        while len(nums) < 3:
            nums.append(0)
        return cls(major=nums[0], minor=nums[1], patch=nums[2])

    @property
    def is_stable(self) -> bool:
        """Check if this is a stable release (major >= 1)."""
        return self.major >= 1

    def is_compatible_with(self, other: APIVersion) -> bool:
        """Check if this version is backwards-compatible with another.

        Two versions are compatible if they share the same major version.

        Args:
            other: The version to compare against.

        Returns:
            True if both versions share the same major number.
        """
        return self.major == other.major


@dataclass
class VersionedEndpoint:
    """Maps an API endpoint path to its versioned handlers.

    Attributes:
        path: The endpoint path (e.g., '/orders/list').
        handlers: Dict mapping APIVersion to the handler function.
        default_version: The default version to use when none is specified.
    """

    path: str
    handlers: dict[APIVersion, Callable[..., Any]] = field(default_factory=dict)
    default_version: APIVersion | None = None

    def add_version(self, version: APIVersion, handler: Callable[..., Any]) -> None:
        """Register a handler for a specific version.

        Args:
            version: The API version.
            handler: The callable that handles requests for this version.
        """
        self.handlers[version] = handler
        if self.default_version is None or version > self.default_version:
            self.default_version = version

    def get_handler(self, version: APIVersion) -> Callable[..., Any] | None:
        """Get the handler for a specific version.

        Args:
            version: The requested API version.

        Returns:
            The handler if found, None otherwise.
        """
        return self.handlers.get(version)

    def get_best_match(self, requested: APIVersion) -> tuple[APIVersion, Callable[..., Any]] | None:
        """Find the best matching version for a request.

        Returns the highest version that is <= requested and shares the same
        major version. Returns None if no compatible version exists.

        Args:
            requested: The version requested by the client.

        Returns:
            Tuple of (version, handler) or None.
        """
        candidates = [
            (v, h) for v, h in self.handlers.items()
            if v <= requested and v.is_compatible_with(requested)
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda x: x[0])

    @property
    def supported_versions(self) -> list[APIVersion]:
        """List all supported versions, sorted ascending."""
        return sorted(self.handlers.keys())


class APIVersionError(Exception):
    """Raised when a version-related error occurs.

    Attributes:
        code: Error code for programmatic handling.
        message: Human-readable error description.
        supported_versions: List of available versions (if applicable).
    """

    def __init__(
        self,
        code: str,
        message: str,
        supported_versions: list[APIVersion] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.supported_versions = supported_versions or []
        super().__init__(f"[{code}] {message}")


class APIVersionRegistry:
    """Central registry for API versions, endpoints, and their lifecycle status.

    Manages version registration, status tracking, and deprecation policies.

    Usage:
        registry = APIVersionRegistry()
        registry.register_version(APIVersion(1), status=VersionStatus.ACTIVE)
        registry.register_version(APIVersion(2), status=VersionStatus.ACTIVE)
        registry.register_endpoint(VersionedEndpoint(path="/orders", handlers={...}))
    """

    def __init__(self) -> None:
        self._versions: dict[APIVersion, VersionStatus] = {}
        self._endpoints: dict[str, VersionedEndpoint] = {}
        self._sunset_dates: dict[APIVersion, str] = {}
        self._deprecation_messages: dict[APIVersion, str] = {}
        self._default_version: APIVersion | None = None

    def register_version(
        self,
        version: APIVersion,
        status: VersionStatus = VersionStatus.ACTIVE,
        sunset_date: str = "",
        deprecation_message: str = "",
    ) -> None:
        """Register an API version with its lifecycle status.

        Args:
            version: The API version to register.
            status: Current lifecycle status.
            sunset_date: ISO 8601 date when the version will be sunset (for deprecated).
            deprecation_message: Custom deprecation message.
        """
        self._versions[version] = status
        if sunset_date:
            self._sunset_dates[version] = sunset_date
        if deprecation_message:
            self._deprecation_messages[version] = deprecation_message
        # Auto-set default to the latest active version
        if status == VersionStatus.ACTIVE:
            if self._default_version is None or version > self._default_version:
                self._default_version = version

    def get_version_status(self, version: APIVersion) -> VersionStatus | None:
        """Get the lifecycle status of a version.

        Args:
            version: The API version to query.

        Returns:
            The VersionStatus, or None if not registered.
        """
        return self._versions.get(version)

    def set_version_status(self, version: APIVersion, status: VersionStatus) -> None:
        """Update the lifecycle status of a registered version.

        Args:
            version: The API version to update.
            status: New status.

        Raises:
            APIVersionError: If the version is not registered.
        """
        if version not in self._versions:
            raise APIVersionError("VERSION_NOT_FOUND", f"Version {version} is not registered")
        self._versions[version] = status
        # Recalculate default if needed
        if status != VersionStatus.ACTIVE and self._default_version == version:
            active = [v for v, s in self._versions.items() if s == VersionStatus.ACTIVE]
            self._default_version = max(active) if active else None

    def register_endpoint(self, endpoint: VersionedEndpoint) -> None:
        """Register a versioned endpoint.

        Args:
            endpoint: The VersionedEndpoint to register.
        """
        self._endpoints[endpoint.path] = endpoint

    def get_endpoint(self, path: str) -> VersionedEndpoint | None:
        """Get a registered endpoint by path.

        Args:
            path: The endpoint path.

        Returns:
            The VersionedEndpoint if found, None otherwise.
        """
        return self._endpoints.get(path)

    @property
    def default_version(self) -> APIVersion | None:
        """The default API version (latest active)."""
        return self._default_version

    @property
    def active_versions(self) -> list[APIVersion]:
        """List all active versions, sorted ascending."""
        return sorted(v for v, s in self._versions.items() if s == VersionStatus.ACTIVE)

    @property
    def deprecated_versions(self) -> list[APIVersion]:
        """List all deprecated versions, sorted ascending."""
        return sorted(v for v, s in self._versions.items() if s == VersionStatus.DEPRECATED)

    @property
    def sunset_versions(self) -> list[APIVersion]:
        """List all sunset versions, sorted ascending."""
        return sorted(v for v, s in self._versions.items() if s == VersionStatus.SUNSET)

    def get_all_versions(self) -> dict[APIVersion, VersionStatus]:
        """Get all registered versions with their statuses."""
        return dict(self._versions)

    def get_deprecation_info(self, version: APIVersion) -> dict[str, Any] | None:
        """Get deprecation information for a version.

        Args:
            version: The API version to query.

        Returns:
            Dict with deprecation info if deprecated, None otherwise.
        """
        status = self._versions.get(version)
        if status != VersionStatus.DEPRECATED:
            return None
        info: dict[str, Any] = {
            "version": str(version),
            "status": status.value,
            "message": self._deprecation_messages.get(
                version,
                f"API version {version} is deprecated. Please upgrade to {self._default_version}.",
            ),
        }
        if version in self._sunset_dates:
            info["sunset_date"] = self._sunset_dates[version]
        if self._default_version:
            info["recommended_version"] = str(self._default_version)
        return info


class VersionNegotiator:
    """Negotiates the best API version between client request and server capabilities.

    Supports multiple negotiation strategies:
    - Explicit version in request header or parameter
    - Content-Type versioning (e.g., application/vnd.api+json;version=2)
    - URL path versioning (e.g., /v2/orders)
    - Accept header quality-value preferences

    Usage:
        negotiator = VersionNegotiator(registry)
        version, warnings = negotiator.negotiate(headers={'X-API-Version': '2'})
    """

    # Common header/param names for version specification
    VERSION_HEADER = "X-API-Version"
    VERSION_PARAM = "api_version"
    ACCEPT_HEADER = "Accept"

    def __init__(self, registry: APIVersionRegistry) -> None:
        """Initialize with an API version registry.

        Args:
            registry: The registry containing available versions.
        """
        self._registry = registry

    def negotiate(
        self,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        url_path: str = "",
    ) -> tuple[APIVersion, list[str]]:
        """Negotiate the best API version from a request.

        Resolution order:
        1. URL path prefix (/v2/...)
        2. X-API-Version header
        3. api_version query parameter
        4. Accept header version parameter
        5. Default version from registry

        Args:
            headers: Request headers dict.
            params: Request query parameters dict.
            url_path: The request URL path.

        Returns:
            Tuple of (negotiated_version, list_of_warnings).

        Raises:
            APIVersionError: If the requested version is sunset or not found.
        """
        headers = headers or {}
        params = params or {}
        warnings: list[str] = []

        # 1. Try URL path versioning (/v2/orders)
        path_version = self._extract_path_version(url_path)
        if path_version is not None:
            return self._resolve_version(path_version, warnings)

        # 2. Try header
        header_version_str = headers.get(self.VERSION_HEADER, "")
        if header_version_str:
            return self._resolve_version_str(header_version_str, warnings)

        # 3. Try query parameter
        param_version_str = params.get(self.VERSION_PARAM, "")
        if param_version_str:
            return self._resolve_version_str(param_version_str, warnings)

        # 4. Try Accept header
        accept_version = self._extract_accept_version(headers.get(self.ACCEPT_HEADER, ""))
        if accept_version is not None:
            return self._resolve_version(accept_version, warnings)

        # 5. Use default
        default = self._registry.default_version
        if default is None:
            raise APIVersionError("NO_VERSIONS", "No API versions are registered")
        return default, warnings

    def _extract_path_version(self, url_path: str) -> APIVersion | None:
        """Extract version from URL path like /v2/orders.

        Args:
            url_path: The request URL path.

        Returns:
            Extracted APIVersion or None.
        """
        if not url_path:
            return None
        match = re.match(r"^/v(\d+)(?:\.(\d+))?(?:\.(\d+))?/", url_path)
        if match:
            major = int(match.group(1))
            minor = int(match.group(2)) if match.group(2) else 0
            patch = int(match.group(3)) if match.group(3) else 0
            return APIVersion(major, minor, patch)
        return None

    def _extract_accept_version(self, accept: str) -> APIVersion | None:
        """Extract version from Accept header like 'application/vnd.api+json;version=2'.

        Args:
            accept: The Accept header value.

        Returns:
            Extracted APIVersion or None.
        """
        if not accept:
            return None
        match = re.search(r"version=(\d+(?:\.\d+(?:\.\d+)?)?)", accept)
        if match:
            try:
                return APIVersion.parse(match.group(1))
            except ValueError:
                return None
        return None

    def _resolve_version_str(
        self,
        version_str: str,
        warnings: list[str],
    ) -> tuple[APIVersion, list[str]]:
        """Resolve a version string to an APIVersion with validation.

        Args:
            version_str: Version string to parse and resolve.
            warnings: List to append warnings to.

        Returns:
            Tuple of (resolved_version, warnings).

        Raises:
            APIVersionError: If the version string is invalid or version is sunset.
        """
        try:
            version = APIVersion.parse(version_str)
        except ValueError as e:
            raise APIVersionError("INVALID_VERSION", str(e))
        return self._resolve_version(version, warnings)

    def _resolve_version(
        self,
        requested: APIVersion,
        warnings: list[str],
    ) -> tuple[APIVersion, list[str]]:
        """Resolve a requested version against the registry.

        Args:
            requested: The requested APIVersion.
            warnings: List to append warnings to.

        Returns:
            Tuple of (resolved_version, warnings).

        Raises:
            APIVersionError: If the version is sunset or not found.
        """
        status = self._registry.get_version_status(requested)

        if status is None:
            # Version not registered; try best-match
            active = self._registry.active_versions
            if not active:
                raise APIVersionError(
                    "NO_VERSIONS",
                    "No API versions are registered",
                )
            # Find closest compatible version
            compatible = [v for v in active if v.is_compatible_with(requested)]
            if compatible:
                best = max(compatible)
                warnings.append(
                    f"Version {requested} is not available. "
                    f"Using compatible version {best}."
                )
                return best, warnings
            raise APIVersionError(
                "VERSION_NOT_FOUND",
                f"API version {requested} is not available. "
                f"Available versions: {', '.join(str(v) for v in active)}",
                supported_versions=active,
            )

        if status == VersionStatus.SUNSET:
            raise APIVersionError(
                "VERSION_SUNSET",
                f"API version {requested} has been sunset and is no longer available.",
                supported_versions=self._registry.active_versions,
            )

        if status == VersionStatus.DEPRECATED:
            deprecation = self._registry.get_deprecation_info(requested)
            if deprecation:
                warnings.append(deprecation["message"])
                if "sunset_date" in deprecation:
                    warnings.append(f"This version will be sunset on {deprecation['sunset_date']}.")
            else:
                warnings.append(
                    f"API version {requested} is deprecated. "
                    f"Please upgrade to {self._registry.default_version}."
                )

        return requested, warnings


class DeprecationWarningManager:
    """Manages and formats deprecation warnings for API responses.

    Collects deprecation warnings and produces standardized response headers
    and log messages.

    Usage:
        manager = DeprecationWarningManager()
        manager.add_warning("Version 1 is deprecated")
        headers = manager.get_response_headers()
    """

    HEADER_DEPRECATED = "X-API-Deprecated"
    HEADER_SUNSET = "X-API-Sunset"
    HEADER_UPGRADE = "X-API-Upgrade"

    def __init__(self) -> None:
        self._warnings: list[str] = []
        self._deprecation_info: dict[str, Any] = {}

    def add_warning(self, message: str) -> None:
        """Add a deprecation warning message.

        Args:
            message: The warning message.
        """
        self._warnings.append(message)

    def set_deprecation_info(
        self,
        version: APIVersion,
        sunset_date: str = "",
        recommended_version: APIVersion | None = None,
    ) -> None:
        """Set structured deprecation information.

        Args:
            version: The deprecated version.
            sunset_date: ISO 8601 sunset date.
            recommended_version: The recommended upgrade version.
        """
        self._deprecation_info = {
            "version": str(version),
            "sunset_date": sunset_date,
            "recommended_version": str(recommended_version) if recommended_version else None,
        }

    @property
    def has_warnings(self) -> bool:
        """Check if any deprecation warnings exist."""
        return len(self._warnings) > 0

    @property
    def warnings(self) -> list[str]:
        """Get all collected warnings."""
        return list(self._warnings)

    def get_response_headers(self) -> dict[str, str]:
        """Generate HTTP response headers for deprecation warnings.

        Returns:
            Dict of header name to header value.
        """
        headers: dict[str, str] = {}
        if not self._warnings:
            return headers

        headers[self.HEADER_DEPRECATED] = "true"

        info = self._deprecation_info
        if info.get("sunset_date"):
            headers[self.HEADER_SUNSET] = info["sunset_date"]
        if info.get("recommended_version"):
            headers[self.HEADER_UPGRADE] = info["recommended_version"]

        return headers

    def get_log_message(self) -> str:
        """Generate a log-friendly deprecation message.

        Returns:
            Formatted warning string, or empty string if no warnings.
        """
        if not self._warnings:
            return ""
        return " | ".join(self._warnings)

    def clear(self) -> None:
        """Clear all collected warnings."""
        self._warnings.clear()
        self._deprecation_info.clear()

    def to_dict(self) -> dict[str, Any]:
        """Export warnings as a JSON-serializable dict.

        Returns:
            Dict with ``has_warnings``, ``warnings``, and ``deprecation_info`` keys.
        """
        return {
            "has_warnings": self.has_warnings,
            "warnings": self._warnings,
            "deprecation_info": self._deprecation_info,
        }
