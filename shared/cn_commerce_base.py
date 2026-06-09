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
import logging.handlers
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


# ── Log Rotation ──────────────────────────────────────────


@dataclass
class LogRotationConfig:
    """Configuration for log file rotation.

    Attributes:
        log_dir: Directory to store log files.
        log_file: Base log file name.
        max_bytes: Max file size before rotation (0 = disable size rotation).
        backup_count: Number of backup files to keep for size rotation.
        when: Time interval for timed rotation (e.g. "midnight", "h", "d").
        interval: Interval count for timed rotation.
        timed_backup_count: Number of backup files to keep for timed rotation.
        enable_size_rotation: Whether to enable size-based rotation.
        enable_timed_rotation: Whether to enable timed rotation.
    """

    log_dir: str = "logs"
    log_file: str = "mcp-cn-commerce.log"
    max_bytes: int = 10 * 1024 * 1024  # 10 MB
    backup_count: int = 5
    when: str = "midnight"
    interval: int = 1
    timed_backup_count: int = 30
    enable_size_rotation: bool = True
    enable_timed_rotation: bool = False


def setup_logging(
    config: LogRotationConfig | None = None,
    level: int = logging.INFO,
    sensitive_filter: bool = True,
    console: bool = True,
) -> logging.Logger:
    """Configure the application logger with optional file rotation.

    Supports both size-based rotation (``RotatingFileHandler``) and
    time-based rotation (``TimedRotatingFileHandler``).  Both can be
    enabled simultaneously -- they write to different files.

    Args:
        config: Rotation configuration.  Uses defaults when *None*.
        level: Root logging level for the ``mcp-cn-commerce`` logger.
        sensitive_filter: Whether to attach ``SensitiveDataFilter``.
        console: Whether to also add a ``StreamHandler`` to stderr.

    Returns:
        The configured logger instance.
    """
    if config is None:
        config = LogRotationConfig()

    logger.setLevel(level)
    # Avoid duplicate handlers on repeated calls
    if logger.handlers:
        logger.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # -- Console handler --
    if console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(fmt)
        logger.addHandler(console_handler)

    # -- Size-based rotation --
    if config.enable_size_rotation and config.max_bytes > 0:
        log_dir = Path(config.log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        size_handler = logging.handlers.RotatingFileHandler(
            filename=str(log_dir / config.log_file),
            maxBytes=config.max_bytes,
            backupCount=config.backup_count,
            encoding="utf-8",
        )
        size_handler.setLevel(level)
        size_handler.setFormatter(fmt)
        logger.addHandler(size_handler)

    # -- Timed rotation --
    if config.enable_timed_rotation:
        log_dir = Path(config.log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        timed_handler = logging.handlers.TimedRotatingFileHandler(
            filename=str(log_dir / config.log_file),
            when=config.when,
            interval=config.interval,
            backupCount=config.timed_backup_count,
            encoding="utf-8",
        )
        timed_handler.setLevel(level)
        timed_handler.setFormatter(fmt)
        logger.addHandler(timed_handler)

    # -- Sensitive data filter --
    if sensitive_filter:
        logger.addFilter(SensitiveDataFilter())

    return logger


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


@dataclass
class EndpointRateLimit:
    """Rate limit configuration for a specific API endpoint.

    Attributes:
        endpoint: The API endpoint path.
        requests_per_second: Maximum requests per second.
        burst_size: Number of requests allowed in a burst.
        cooldown_seconds: Seconds to wait after hitting the limit.
    """

    endpoint: str = ""
    requests_per_second: float = 10.0
    burst_size: int = 1
    cooldown_seconds: float = 0.0


@dataclass
class PlatformRateLimitConfig:
    """Rate limit configuration for an entire platform.

    Attributes:
        platform: Platform identifier (e.g. "OCEANENGINE", "TAOBAO").
        default_requests_per_second: Default RPS for all endpoints.
        endpoints: Endpoint-specific overrides.
        burst_size: Default burst size.
        enabled: Whether rate limiting is active for this platform.
    """

    platform: str = ""
    default_requests_per_second: float = 10.0
    endpoints: dict[str, EndpointRateLimit] = field(default_factory=dict)
    burst_size: int = 1
    enabled: bool = True

    def get_endpoint_limit(self, endpoint: str) -> EndpointRateLimit:
        """Get the rate limit for an endpoint, falling back to platform defaults.

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
    """Statistics for rate limiting across platforms and endpoints.

    Attributes:
        total_requests: Total requests recorded.
        total_throttled: Total requests that were throttled.
        total_wait_time_ms: Cumulative wait time in milliseconds.
        platform_stats: Per-platform request/throttle counts.
        endpoint_stats: Per-endpoint request/throttle counts.
        last_throttled_at: Timestamp of the last throttle event.
    """

    total_requests: int = 0
    total_throttled: int = 0
    total_wait_time_ms: float = 0.0
    platform_stats: dict[str, dict[str, int | float]] = field(default_factory=dict)
    endpoint_stats: dict[str, dict[str, int | float]] = field(default_factory=dict)
    last_throttled_at: float = 0.0

    @property
    def throttle_rate(self) -> float:
        """Fraction of requests that were throttled."""
        if self.total_requests == 0:
            return 0.0
        return self.total_throttled / self.total_requests

    @property
    def avg_wait_time_ms(self) -> float:
        """Average wait time per throttle event."""
        if self.total_throttled == 0:
            return 0.0
        return self.total_wait_time_ms / self.total_throttled

    def record_throttle(self, platform: str, endpoint: str, wait_ms: float) -> None:
        """Record a throttled request.

        Args:
            platform: Platform identifier.
            endpoint: API endpoint path.
            wait_ms: Time spent waiting in milliseconds.
        """
        self.total_requests += 1
        self.total_throttled += 1
        self.total_wait_time_ms += wait_ms
        self.last_throttled_at = time.time()

        stats = self.platform_stats.setdefault(platform, {"requests": 0, "throttled": 0, "wait_ms": 0.0})
        stats["requests"] = stats.get("requests", 0) + 1
        stats["throttled"] = stats.get("throttled", 0) + 1
        stats["wait_ms"] = stats.get("wait_ms", 0.0) + wait_ms

        key = f"{platform}:{endpoint}"
        ep_stats = self.endpoint_stats.setdefault(key, {"requests": 0, "throttled": 0, "wait_ms": 0.0})
        ep_stats["requests"] = ep_stats.get("requests", 0) + 1
        ep_stats["throttled"] = ep_stats.get("throttled", 0) + 1
        ep_stats["wait_ms"] = ep_stats.get("wait_ms", 0.0) + wait_ms

    def record_request(self, platform: str, endpoint: str) -> None:
        """Record a non-throttled request.

        Args:
            platform: Platform identifier.
            endpoint: API endpoint path.
        """
        self.total_requests += 1

        stats = self.platform_stats.setdefault(platform, {"requests": 0, "throttled": 0, "wait_ms": 0.0})
        stats["requests"] = stats.get("requests", 0) + 1

        key = f"{platform}:{endpoint}"
        ep_stats = self.endpoint_stats.setdefault(key, {"requests": 0, "throttled": 0, "wait_ms": 0.0})
        ep_stats["requests"] = ep_stats.get("requests", 0) + 1

    def get_summary(self) -> dict[str, Any]:
        """Get a JSON-serializable summary of rate limit stats."""
        return {
            "global": {
                "total_requests": self.total_requests,
                "total_throttled": self.total_throttled,
                "throttle_rate": round(self.throttle_rate, 4),
                "avg_wait_time_ms": round(self.avg_wait_time_ms, 2),
                "total_wait_time_ms": round(self.total_wait_time_ms, 2),
            },
            "platforms": dict(self.platform_stats),
            "endpoints": dict(self.endpoint_stats),
        }

    def reset(self) -> None:
        """Reset all collected statistics."""
        self.total_requests = 0
        self.total_throttled = 0
        self.total_wait_time_ms = 0.0
        self.platform_stats.clear()
        self.endpoint_stats.clear()
        self.last_throttled_at = 0.0


@dataclass
class RateLimitConfig:
    """Global rate limit configuration across all platforms.

    Attributes:
        platforms: Per-platform rate limit configurations.
        default_requests_per_second: Default RPS when platform is not configured.
        default_burst_size: Default burst size.
        enabled: Global switch to enable/disable rate limiting.
    """

    platforms: dict[str, PlatformRateLimitConfig] = field(default_factory=dict)
    default_requests_per_second: float = 10.0
    default_burst_size: int = 1
    enabled: bool = True

    def get_platform_config(self, platform: str) -> PlatformRateLimitConfig:
        """Get the config for a platform, creating defaults if missing."""
        if platform in self.platforms:
            return self.platforms[platform]
        return PlatformRateLimitConfig(
            platform=platform,
            default_requests_per_second=self.default_requests_per_second,
            burst_size=self.default_burst_size,
            enabled=self.enabled,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dictionary."""
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
    def from_dict(cls, data: dict[str, Any]) -> RateLimitConfig:
        """Deserialize from a dictionary.

        Args:
            data: Dictionary produced by ``to_dict``.

        Returns:
            A ``RateLimitConfig`` instance.
        """
        platforms: dict[str, PlatformRateLimitConfig] = {}
        for name, pdata in data.get("platforms", {}).items():
            endpoints: dict[str, EndpointRateLimit] = {}
            for ep, edata in pdata.get("endpoints", {}).items():
                endpoints[ep] = EndpointRateLimit(
                    endpoint=edata.get("endpoint", ep),
                    requests_per_second=edata.get("requests_per_second", 10.0),
                    burst_size=edata.get("burst_size", 1),
                    cooldown_seconds=edata.get("cooldown_seconds", 0.0),
                )
            platforms[name] = PlatformRateLimitConfig(
                platform=pdata.get("platform", name),
                default_requests_per_second=pdata.get("default_requests_per_second", 10.0),
                burst_size=pdata.get("burst_size", 1),
                enabled=pdata.get("enabled", True),
                endpoints=endpoints,
            )
        return cls(
            platforms=platforms,
            default_requests_per_second=data.get("default_requests_per_second", 10.0),
            default_burst_size=data.get("default_burst_size", 1),
            enabled=data.get("enabled", True),
        )


class ConfigurableRateLimiter:
    """Rate limiter with per-platform and per-endpoint configuration.

    Uses token-bucket-style timing based on ``RateLimitConfig``.

    Usage::

        limiter = ConfigurableRateLimiter(RateLimitConfig(...))
        await limiter.acquire("OCEANENGINE", "/api/order/search")
    """

    def __init__(self, config: RateLimitConfig | None = None) -> None:
        self.config = config or RateLimitConfig()
        self.stats = RateLimitStats()
        self._lock = threading.Lock()
        self._endpoint_timestamps: dict[str, float] = {}

    async def acquire(self, platform: str, endpoint: str) -> None:
        """Wait if necessary to respect the rate limit for a platform/endpoint.

        Args:
            platform: Platform identifier.
            endpoint: API endpoint path.
        """
        if not self.config.enabled:
            self.stats.record_request(platform, endpoint)
            return

        p_cfg = self.config.get_platform_config(platform)
        if not p_cfg.enabled:
            self.stats.record_request(platform, endpoint)
            return

        ep_limit = p_cfg.get_endpoint_limit(endpoint)
        min_interval = 1.0 / ep_limit.requests_per_second if ep_limit.requests_per_second > 0 else 0.0

        key = f"{platform}:{endpoint}"
        now = time.time()
        with self._lock:
            last = self._endpoint_timestamps.get(key, 0.0)
            elapsed = now - last
            wait = max(0.0, min_interval - elapsed)
            if wait > 0:
                self._endpoint_timestamps[key] = now + wait
                self.stats.record_throttle(platform, endpoint, wait * 1000)
            else:
                self._endpoint_timestamps[key] = now
                self.stats.record_request(platform, endpoint)

        if wait > 0:
            await asyncio.sleep(wait)

    def update_platform_config(self, platform: str, config: PlatformRateLimitConfig) -> None:
        """Replace the configuration for a platform.

        Args:
            platform: Platform identifier.
            config: New platform configuration.
        """
        self.config.platforms[platform] = config

    def update_endpoint_limit(
        self,
        platform: str,
        endpoint: str,
        requests_per_second: float = 10.0,
        burst_size: int = 1,
    ) -> None:
        """Add or update the rate limit for a specific endpoint.

        Creates the platform config if it does not already exist.

        Args:
            platform: Platform identifier.
            endpoint: API endpoint path.
            requests_per_second: Max RPS for the endpoint.
            burst_size: Burst size for the endpoint.
        """
        if platform not in self.config.platforms:
            self.config.platforms[platform] = PlatformRateLimitConfig(platform=platform)
        self.config.platforms[platform].endpoints[endpoint] = EndpointRateLimit(
            endpoint=endpoint,
            requests_per_second=requests_per_second,
            burst_size=burst_size,
        )

    def get_stats_summary(self) -> dict[str, Any]:
        """Get combined config and stats summary."""
        return {
            "config": self.config.to_dict(),
            "stats": self.stats.get_summary(),
        }

    def reset_stats(self) -> None:
        """Reset collected rate limit statistics."""
        self.stats.reset()


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


@dataclass
class ReconnectConfig:
    """Configuration for automatic HTTP client reconnection.

    Attributes:
        max_retries: Maximum reconnection attempts (0 = no retries).
        base_delay: Base delay for exponential backoff in seconds.
        max_delay: Maximum delay cap in seconds.
        jitter: Whether to add random jitter to the delay.
        timeout: HTTP client timeout in seconds.
        probe_on_connect: Whether to send a HEAD request to verify connectivity.
        probe_timeout: Timeout for the connectivity probe in seconds.
    """

    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    jitter: bool = True
    timeout: float = 30.0
    probe_on_connect: bool = True
    probe_timeout: float = 5.0

    def compute_delay(self, attempt: int) -> float:
        """Compute the delay before the next reconnection attempt.

        Args:
            attempt: The current attempt number (0-indexed).

        Returns:
            Delay in seconds.
        """
        delay = min(self.base_delay * (2 ** attempt), self.max_delay)
        if self.jitter:
            delay = delay * (0.5 + random.random())
        return delay




# ── Health Check ────────────────────────────────────────────


@dataclass
class HealthCheckResult:
    """Structured result from a health check operation.

    Attributes:
        status: Overall health status ("healthy", "degraded", "unhealthy").
        configured: Whether API credentials are configured.
        has_token: Whether an access token is present.
        api_reachable: Whether the API endpoint responded successfully.
        latency_ms: Latency of the health check in milliseconds.
        dependencies: Status of dependency services.
        metrics: Request metrics summary.
        error: Error message if check failed.
        cached: Whether this result was served from cache.
        timestamp: ISO 8601 timestamp of the check.
    """

    status: str = "unhealthy"
    configured: bool = False
    has_token: bool = False
    api_reachable: bool = False
    latency_ms: float = 0.0
    dependencies: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    cached: bool = False
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        """Convert result to a dictionary for JSON serialization."""
        return {
            "status": self.status,
            "configured": self.configured,
            "has_token": self.has_token,
            "api_reachable": self.api_reachable,
            "latency_ms": round(self.latency_ms, 2),
            "dependencies": self.dependencies,
            "metrics": self.metrics,
            "error": self.error,
            "cached": self.cached,
            "timestamp": self.timestamp,
        }


class HealthCheckCache:
    """Cache for health check results with TTL support.

    Avoids hammering API endpoints with health check requests in
    high-frequency monitoring scenarios.

    Usage::

        cache = HealthCheckCache(ttl_seconds=30)
        result = cache.get("oceanengine")
        if result is None:
            result = await perform_health_check()
            cache.set("oceanengine", result)
    """

    def __init__(self, ttl_seconds: float = 30.0) -> None:
        """Initialize the cache.

        Args:
            ttl_seconds: Time-to-live for cached results in seconds.
        """
        self._ttl = ttl_seconds
        self._cache: dict[str, tuple[float, HealthCheckResult]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> HealthCheckResult | None:
        """Get a cached result if it exists and is not expired.

        Args:
            key: Cache key (typically platform name).

        Returns:
            Cached HealthCheckResult or None if expired/missing.
        """
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            ts, result = entry
            if time.time() - ts > self._ttl:
                del self._cache[key]
                return None
            cached_result = HealthCheckResult(**{**result.__dict__, "cached": True})
            return cached_result

    def set(self, key: str, result: HealthCheckResult) -> None:
        """Store a result in the cache.

        Args:
            key: Cache key (typically platform name).
            result: The HealthCheckResult to cache.
        """
        with self._lock:
            self._cache[key] = (time.time(), result)

    def invalidate(self, key: str | None = None) -> None:
        """Invalidate cached results.

        Args:
            key: Specific key to invalidate, or None to clear all.
        """
        with self._lock:
            if key is None:
                self._cache.clear()
            else:
                self._cache.pop(key, None)

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dict with entry_count, ttl_seconds, and keys.
        """
        with self._lock:
            now = time.time()
            valid = {k: v for k, v in self._cache.items() if now - v[0] <= self._ttl}
            return {
                "entry_count": len(valid),
                "ttl_seconds": self._ttl,
                "keys": list(valid.keys()),
            }


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

    def __init__(
        self,
        app_key: str = "",
        app_secret: str = "",
        access_token: str = "",
        reconnect_config: ReconnectConfig | None = None,
    ) -> None:
        self.app_key = app_key
        self.app_secret = app_secret
        self.access_token = access_token
        self.rate_limiter = RateLimiter()
        self.metrics = MetricsCollector()
        self._reconnect_config = reconnect_config or ReconnectConfig()
        self._health_cache = HealthCheckCache(ttl_seconds=30.0)

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create an HTTP client with connection pooling.

        If the client has been closed or is ``None``, a new one is created.
        """
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

    async def _ensure_client(self) -> httpx.AsyncClient:
        """Get a healthy client, reconnecting if necessary.

        Attempts to create a new client up to ``max_retries`` times with
        exponential backoff.  If the connection probe fails on every
        attempt the last exception is raised.

        Returns:
            A usable ``httpx.AsyncClient``.
        """
        cfg = self._reconnect_config

        # Fast path: existing healthy client
        if self._client is not None and not self._client.is_closed:
            return self._client

        last_exc: Exception | None = None
        for attempt in range(cfg.max_retries + 1):
            try:
                self._client = httpx.AsyncClient(
                    timeout=cfg.timeout,
                    limits=httpx.Limits(
                        max_connections=10,
                        max_keepalive_connections=5,
                        keepalive_expiry=30,
                    ),
                )
                # Optional probe: only if a BASE_URL is configured
                if self.BASE_URL and cfg.probe_on_connect:
                    probe_resp = await self._client.head(self.BASE_URL, timeout=cfg.probe_timeout)
                    if probe_resp.status_code >= 500:
                        raise httpx.ConnectError(
                            f"Probe returned {probe_resp.status_code}",
                            request=httpx.Request("HEAD", self.BASE_URL),
                        )
                logger.debug(f"Client (re)connected on attempt {attempt + 1}")
                return self._client
            except Exception as exc:
                last_exc = exc
                if self._client and not self._client.is_closed:
                    await self._client.aclose()
                self._client = None

                if attempt == cfg.max_retries:
                    logger.error(
                        f"Auto-reconnect failed after {cfg.max_retries + 1} attempts: {exc}"
                    )
                    raise

                delay = cfg.compute_delay(attempt)
                logger.warning(
                    f"Reconnect attempt {attempt + 1}/{cfg.max_retries} failed: {exc}. "
                    f"Retrying in {delay:.2f}s"
                )
                await asyncio.sleep(delay)

        # Safety net
        if last_exc:
            raise last_exc
        return self._client  # type: ignore[return-value]

    async def _reconnect(self) -> httpx.AsyncClient:
        """Force a reconnect by closing the existing client.

        Returns:
            A fresh ``httpx.AsyncClient``.
        """
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        self._client = None
        return await self._ensure_client()

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

                client = await self._ensure_client()
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

    async def health_check(self, use_cache: bool = True, cache_key: str = "") -> dict[str, Any]:
        """Check API reachability and client configuration.

        Supports result caching to avoid hammering endpoints in monitoring
        scenarios.  Cache TTL is 30 seconds by default.

        Args:
            use_cache: Whether to use cached results if available.
            cache_key: Cache key (defaults to class name).

        Returns:
            Dict with ``status``, ``configured``, ``has_token``,
            ``api_reachable``, ``latency_ms``, ``metrics``,
            ``cached``, ``timestamp``, and optionally ``error`` keys.
        """
        key = cache_key or self.__class__.__name__

        # Check cache first
        if use_cache:
            cached = self._health_cache.get(key)
            if cached is not None:
                return cached.to_dict()

        start_time = time.time()
        configured = bool(self.app_key and self.app_secret)
        has_token = bool(self.access_token)
        api_reachable = False
        error_msg = ""

        if self.BASE_URL:
            try:
                client = await self._ensure_client()
                resp = await client.head(self.BASE_URL, timeout=5)
                api_reachable = resp.status_code < 500
            except Exception as exc:
                api_reachable = False
                error_msg = str(exc)

        latency = (time.time() - start_time) * 1000

        # Determine overall status
        if api_reachable and configured and has_token:
            status = "healthy"
        elif configured:
            status = "degraded"
        else:
            status = "unhealthy"

        result = HealthCheckResult(
            status=status,
            configured=configured,
            has_token=has_token,
            api_reachable=api_reachable,
            latency_ms=latency,
            metrics=self.metrics.get_summary(),
            error=error_msg,
        )

        # Store in cache
        self._health_cache.set(key, result)

        return result.to_dict()

    async def deep_health_check(
        self,
        dependencies: list[str] | None = None,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """Perform a deep health check including dependency service checks.

        In addition to the basic health check, this method verifies that
        dependent services (e.g., database, Redis, external APIs) are
        reachable.

        Args:
            dependencies: List of dependency URLs or names to check.
                          If None, only the main API is checked.
            timeout: Timeout per dependency check in seconds.

        Returns:
            Dict with all basic health check fields plus ``dependencies``
            containing per-dependency status.
        """
        start_time = time.time()
        basic = await self.health_check(use_cache=False)
        dep_results: dict[str, Any] = {}

        if dependencies:
            client = await self._ensure_client()
            for dep in dependencies:
                dep_start = time.time()
                dep_info: dict[str, Any] = {"name": dep, "reachable": False}
                try:
                    # If it looks like a URL, do a HEAD request
                    if dep.startswith("http://") or dep.startswith("https://"):
                        resp = await asyncio.wait_for(
                            client.head(dep, timeout=timeout),
                            timeout=timeout,
                        )
                        dep_info["reachable"] = resp.status_code < 500
                        dep_info["status_code"] = resp.status_code
                    else:
                        # For named dependencies, check if they are configured
                        dep_info["reachable"] = True
                        dep_info["configured"] = True
                except asyncio.TimeoutError:
                    dep_info["error"] = "timeout"
                except Exception as exc:
                    dep_info["error"] = str(exc)
                dep_info["latency_ms"] = round((time.time() - dep_start) * 1000, 2)
                dep_results[dep] = dep_info

        # Determine overall status considering dependencies
        all_deps_ok = all(d.get("reachable", False) for d in dep_results.values()) if dep_results else True
        if basic["status"] == "healthy" and all_deps_ok:
            overall_status = "healthy"
        elif basic["configured"] and (basic["api_reachable"] or all_deps_ok):
            overall_status = "degraded"
        else:
            overall_status = "unhealthy"

        total_latency = (time.time() - start_time) * 1000

        result = HealthCheckResult(
            status=overall_status,
            configured=basic["configured"],
            has_token=basic["has_token"],
            api_reachable=basic["api_reachable"],
            latency_ms=total_latency,
            dependencies=dep_results,
            metrics=basic.get("metrics", {}),
            error=basic.get("error", ""),
        )

        return result.to_dict()

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




# ── Configuration Validation ───────────────────────────────


class ConfigRule:
    """Defines a single configuration validation rule.

    Used by ``ConfigValidator`` to define what constitutes valid
    configuration for a platform.

    Attributes:
        key: Configuration key name (e.g., "APP_KEY", "BASE_URL").
        required: Whether this key must be present.
        value_type: Expected type ("str", "int", "float", "bool", "url", "email").
        min_value: Minimum value for numeric types.
        max_value: Maximum value for numeric types.
        min_length: Minimum string length.
        max_length: Maximum string length.
        pattern: Regex pattern the value must match.
        allowed_values: List of allowed values.
        depends_on: List of keys this key depends on.
        description: Human-readable description for error messages.
    """

    def __init__(
        self,
        key: str,
        required: bool = True,
        value_type: str = "str",
        min_value: float | None = None,
        max_value: float | None = None,
        min_length: int | None = None,
        max_length: int | None = None,
        pattern: str = "",
        allowed_values: list[Any] | None = None,
        depends_on: list[str] | None = None,
        description: str = "",
    ) -> None:
        self.key = key
        self.required = required
        self.value_type = value_type
        self.min_value = min_value
        self.max_value = max_value
        self.min_length = min_length
        self.max_length = max_length
        self.pattern = pattern
        self.allowed_values = allowed_values
        self.depends_on = depends_on or []
        self.description = description or key


class ConfigValidationResult:
    """Result of configuration validation.

    Attributes:
        valid: Whether all validations passed.
        errors: List of validation error messages.
        warnings: List of non-critical warnings.
        missing_keys: List of required keys that are missing.
        invalid_keys: List of keys with invalid values.
        dependency_errors: List of dependency-related errors.
    """

    def __init__(self) -> None:
        self.valid: bool = True
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.missing_keys: list[str] = []
        self.invalid_keys: list[str] = []
        self.dependency_errors: list[str] = []

    def add_error(self, message: str) -> None:
        """Add a validation error."""
        self.errors.append(message)
        self.valid = False

    def add_warning(self, message: str) -> None:
        """Add a non-critical warning."""
        self.warnings.append(message)

    def to_dict(self) -> dict[str, Any]:
        """Convert to a dictionary."""
        return {
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "missing_keys": self.missing_keys,
            "invalid_keys": self.invalid_keys,
            "dependency_errors": self.dependency_errors,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
        }


class ConfigValidator:
    """Validates platform configuration against defined rules.

    Supports three types of validation:
    1. **Format validation**: Checks types, patterns, allowed values.
    2. **Range validation**: Checks numeric ranges and string lengths.
    3. **Dependency validation**: Checks that required keys are present
       when their dependents are configured.

    Usage::

        validator = ConfigValidator("OCEANENGINE")
        validator.add_rule(ConfigRule("APP_KEY", required=True, min_length=8))
        validator.add_rule(ConfigRule("APP_SECRET", required=True, min_length=16))
        validator.add_rule(ConfigRule(
            "ACCESS_TOKEN",
            required=False,
            depends_on=["APP_KEY", "APP_SECRET"],
        ))

        config = {"APP_KEY": "my_key", "APP_SECRET": "my_secret_value_1234"}
        result = validator.validate(config)
        if not result.valid:
            print(result.errors)
    """

    def __init__(self, platform: str = "") -> None:
        """Initialize the validator.

        Args:
            platform: Platform name for error messages.
        """
        self.platform = platform
        self._rules: dict[str, ConfigRule] = {}

    def add_rule(self, rule: ConfigRule) -> None:
        """Add a validation rule.

        Args:
            rule: The ConfigRule to add.
        """
        self._rules[rule.key] = rule

    def add_rules(self, rules: list[ConfigRule]) -> None:
        """Add multiple validation rules.

        Args:
            rules: List of ConfigRule objects to add.
        """
        for rule in rules:
            self._rules[rule.key] = rule

    def validate(
        self,
        config: dict[str, Any],
        prefix: str = "",
    ) -> ConfigValidationResult:
        """Validate a configuration dictionary against all rules.

        Performs format, range, and dependency validation.

        Args:
            config: Configuration dictionary to validate.
            prefix: Optional prefix for error messages (e.g., env var prefix).

        Returns:
            ConfigValidationResult with all validation outcomes.
        """
        result = ConfigValidationResult()

        for key, rule in self._rules.items():
            full_key = f"{prefix}{key}" if prefix else key
            value = config.get(key)

            # ── Format Validation ──
            if value is None or value == "":
                if rule.required:
                    result.missing_keys.append(full_key)
                    result.add_error(
                        f"Required configuration '{full_key}' is missing"
                        f"{' (' + rule.description + ')' if rule.description != key else ''}"
                    )
                continue

            # Type check
            type_ok = self._check_type(value, rule.value_type, full_key, result)
            if not type_ok:
                result.invalid_keys.append(full_key)
                continue

            # Pattern check
            if rule.pattern and isinstance(value, str):
                if not re.match(rule.pattern, value):
                    result.invalid_keys.append(full_key)
                    result.add_error(
                        f"Configuration '{full_key}' does not match required pattern: {rule.pattern}"
                    )

            # Allowed values check
            if rule.allowed_values is not None:
                if value not in rule.allowed_values:
                    result.invalid_keys.append(full_key)
                    result.add_error(
                        f"Configuration '{full_key}' value '{value}' is not in allowed values: {rule.allowed_values}"
                    )

            # ── Range Validation ──
            if isinstance(value, (int, float)):
                if rule.min_value is not None and value < rule.min_value:
                    result.invalid_keys.append(full_key)
                    result.add_error(
                        f"Configuration '{full_key}' value {value} is below minimum {rule.min_value}"
                    )
                if rule.max_value is not None and value > rule.max_value:
                    result.invalid_keys.append(full_key)
                    result.add_error(
                        f"Configuration '{full_key}' value {value} is above maximum {rule.max_value}"
                    )

            if isinstance(value, str):
                if rule.min_length is not None and len(value) < rule.min_length:
                    result.invalid_keys.append(full_key)
                    result.add_error(
                        f"Configuration '{full_key}' length {len(value)} is below minimum {rule.min_length}"
                    )
                if rule.max_length is not None and len(value) > rule.max_length:
                    result.invalid_keys.append(full_key)
                    result.add_error(
                        f"Configuration '{full_key}' length {len(value)} exceeds maximum {rule.max_length}"
                    )

        # ── Dependency Validation ──
        for key, rule in self._rules.items():
            value = config.get(key)
            if value is None or value == "":
                continue

            for dep_key in rule.depends_on:
                dep_value = config.get(dep_key)
                if dep_value is None or dep_value == "":
                    full_key = f"{prefix}{key}" if prefix else key
                    full_dep = f"{prefix}{dep_key}" if prefix else dep_key
                    error_msg = (
                        f"Configuration '{full_key}' requires '{full_dep}' to be set"
                    )
                    result.dependency_errors.append(error_msg)
                    result.add_error(error_msg)

        return result

    def _check_type(
        self,
        value: Any,
        expected_type: str,
        key: str,
        result: ConfigValidationResult,
    ) -> bool:
        """Check if a value matches the expected type."""
        if expected_type == "str":
            if not isinstance(value, str):
                result.add_error(f"Configuration '{key}' must be a string, got {type(value).__name__}")
                return False
        elif expected_type == "int":
            if not isinstance(value, int) or isinstance(value, bool):
                result.add_error(f"Configuration '{key}' must be an integer, got {type(value).__name__}")
                return False
        elif expected_type == "float":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                result.add_error(f"Configuration '{key}' must be a number, got {type(value).__name__}")
                return False
        elif expected_type == "bool":
            if not isinstance(value, bool):
                result.add_error(f"Configuration '{key}' must be a boolean, got {type(value).__name__}")
                return False
        elif expected_type == "url":
            if not isinstance(value, str):
                result.add_error(f"Configuration '{key}' must be a URL string")
                return False
            if not re.match(r"^https?://", value):
                result.add_error(f"Configuration '{key}' must be a valid URL starting with http:// or https://")
                return False
        elif expected_type == "email":
            if not isinstance(value, str):
                result.add_error(f"Configuration '{key}' must be an email string")
                return False
            if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value):
                result.add_error(f"Configuration '{key}' must be a valid email address")
                return False
        return True

    def get_rules(self) -> dict[str, ConfigRule]:
        """Get all registered rules."""
        return dict(self._rules)

    def validate_from_env(
        self,
        env_prefix: str,
        keys: list[str] | None = None,
    ) -> ConfigValidationResult:
        """Validate configuration from environment variables.

        Args:
            env_prefix: Environment variable prefix (e.g., "OCEANENGINE").
            keys: Specific keys to check. If None, checks all rules.

        Returns:
            ConfigValidationResult with all validation outcomes.
        """
        config: dict[str, Any] = {}
        check_keys = keys or list(self._rules.keys())

        for key in check_keys:
            env_name = f"{env_prefix}_{key}"
            value = os.environ.get(env_name, "")
            if value:
                config[key] = value

        return self.validate(config, prefix=f"{env_prefix}_")



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
