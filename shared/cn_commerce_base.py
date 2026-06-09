"""Shared base for Chinese e-commerce platform MCP servers.

Provides unified auth signing, request handling, and error normalization.
"""

from __future__ import annotations

import asyncio
import csv
import functools
import gzip
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
import zlib
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


def canonicalize_sign_value(value: Any) -> str:
    """Canonicalize a parameter value for stable signing.

    Signatures must be reproducible: the same logical value must always
    serialize to the same string, regardless of Python object identity or
    dict ordering. Naively interpolating arbitrary values (``f"{v}"``) makes
    ``dict``/``list`` values stringify non-deterministically, producing
    signatures that intermittently fail server-side verification.

    Args:
        value: Any parameter value.

    Returns:
        A deterministic string representation.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(value)


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

    def set_platform_rps(self, platform: str, requests_per_second: float) -> None:
        """Dynamically adjust the RPS for a platform at runtime.

        Creates the platform config if it does not exist.

        Args:
            platform: Platform identifier.
            requests_per_second: New RPS value.
        """
        if platform not in self.config.platforms:
            self.config.platforms[platform] = PlatformRateLimitConfig(platform=platform)
        self.config.platforms[platform].default_requests_per_second = requests_per_second
        logger.debug(f"Rate limit: {platform} RPS set to {requests_per_second}")

    def set_endpoint_rps(self, platform: str, endpoint: str, requests_per_second: float) -> None:
        """Dynamically adjust the RPS for a specific endpoint at runtime.

        Args:
            platform: Platform identifier.
            endpoint: API endpoint path.
            requests_per_second: New RPS value.
        """
        self.update_endpoint_limit(platform, endpoint, requests_per_second=requests_per_second)
        logger.debug(f"Rate limit: {platform}:{endpoint} RPS set to {requests_per_second}")

    def enable_platform(self, platform: str) -> None:
        """Enable rate limiting for a platform."""
        if platform in self.config.platforms:
            self.config.platforms[platform].enabled = True

    def disable_platform(self, platform: str) -> None:
        """Disable rate limiting for a platform (requests pass through without delay)."""
        if platform in self.config.platforms:
            self.config.platforms[platform].enabled = False

    def auto_adjust_from_stats(
        self,
        throttle_threshold: float = 0.3,
        scale_down_factor: float = 0.8,
        scale_up_factor: float = 1.1,
        min_rps: float = 0.5,
        max_rps: float = 100.0,
    ) -> dict[str, Any]:
        """Auto-adjust rate limits based on collected throttle statistics.

        Args:
            throttle_threshold: Throttle rate above which RPS is reduced.
            scale_down_factor: Multiplier to reduce RPS when throttled.
            scale_up_factor: Multiplier to increase RPS when under-utilised.
            min_rps: Minimum RPS floor.
            max_rps: Maximum RPS ceiling.

        Returns:
            Dict describing what adjustments were made.
        """
        adjustments: dict[str, Any] = {"platforms": {}, "endpoints": {}}

        for key, ep_stats in self.stats.endpoint_stats.items():
            total = ep_stats.get("requests", 0)
            throttled = ep_stats.get("throttled", 0)
            if total < 5:
                continue

            rate = throttled / total
            platform, endpoint = key.split(":", 1) if ":" in key else (key, "")

            if rate > throttle_threshold:
                p_cfg = self.config.get_platform_config(platform)
                ep_limit = p_cfg.get_endpoint_limit(endpoint)
                new_rps = max(min_rps, ep_limit.requests_per_second * scale_down_factor)
                self.set_endpoint_rps(platform, endpoint, new_rps)
                adjustments["endpoints"][key] = {
                    "action": "scale_down",
                    "old_rps": ep_limit.requests_per_second,
                    "new_rps": round(new_rps, 2),
                    "throttle_rate": round(rate, 4),
                }
            elif rate < throttle_threshold * 0.3 and total > 20:
                p_cfg = self.config.get_platform_config(platform)
                ep_limit = p_cfg.get_endpoint_limit(endpoint)
                new_rps = min(max_rps, ep_limit.requests_per_second * scale_up_factor)
                if new_rps != ep_limit.requests_per_second:
                    self.set_endpoint_rps(platform, endpoint, new_rps)
                    adjustments["endpoints"][key] = {
                        "action": "scale_up",
                        "old_rps": ep_limit.requests_per_second,
                        "new_rps": round(new_rps, 2),
                        "throttle_rate": round(rate, 4),
                    }

        return adjustments


# ── Request Priority ──────────────────────────────────────


class RequestPriority(StrEnum):
    """Priority levels for API requests.

    Attributes:
        CRITICAL: Must be served immediately (e.g. payment callbacks).
        HIGH: Time-sensitive business operations (e.g. order creation).
        NORMAL: Standard read/write requests (default).
        LOW: Background or bulk operations (e.g. report generation).
    """

    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


_PRIORITY_WEIGHTS: dict[str, int] = {
    RequestPriority.CRITICAL: 0,
    RequestPriority.HIGH: 1,
    RequestPriority.NORMAL: 2,
    RequestPriority.LOW: 3,
}


@dataclass
class PrioritizedRequest:
    """A request wrapper that carries priority metadata."""

    priority: RequestPriority = RequestPriority.NORMAL
    method: str = ""
    path: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)
    request_id: str = ""
    created_at: float = field(default_factory=time.time)
    platform: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def priority_weight(self) -> int:
        """Numeric weight for sorting (lower = higher priority)."""
        return _PRIORITY_WEIGHTS.get(self.priority, 2)


class PriorityQueue:
    """Thread-safe priority queue for API requests.

    Uses a heap so that the highest-priority (lowest weight) item is
    always dequeued first.  Requests with equal priority are served in
    FIFO order based on ``created_at``.
    """

    def __init__(self, max_size: int = 10000) -> None:

        self._heap: list[tuple[int, float, int, PrioritizedRequest]] = []
        self._counter = 0
        self._max_size = max_size
        self._lock = threading.Lock()
        self._size = 0

    def enqueue(self, request: PrioritizedRequest) -> None:
        """Add a request to the queue.  Raises RuntimeError when full."""
        import heapq

        with self._lock:
            if self._size >= self._max_size:
                raise RuntimeError(f"Priority queue full (max_size={self._max_size})")
            heapq.heappush(self._heap, (request.priority_weight, request.created_at, self._counter, request))
            self._counter += 1
            self._size += 1

    def dequeue(self) -> PrioritizedRequest | None:
        """Remove and return the highest-priority request."""
        import heapq

        with self._lock:
            if not self._heap:
                return None
            _, _, _, request = heapq.heappop(self._heap)
            self._size -= 1
            return request

    def peek(self) -> PrioritizedRequest | None:
        """View the next request without removing it."""
        with self._lock:
            return self._heap[0][3] if self._heap else None

    @property
    def size(self) -> int:
        return self._size

    @property
    def is_empty(self) -> bool:
        return self._size == 0

    def clear(self) -> None:
        with self._lock:
            self._heap.clear()
            self._size = 0
            self._counter = 0

    def get_priority_distribution(self) -> dict[str, int]:
        """Count of queued requests per priority level."""
        with self._lock:
            dist: dict[str, int] = {}
            for _, _, _, req in self._heap:
                name = req.priority.value if isinstance(req.priority, RequestPriority) else str(req.priority)
                dist[name] = dist.get(name, 0) + 1
            return dist


@dataclass
class PriorityStats:
    """Statistics for priority-based request scheduling."""

    total_dispatched: int = 0
    by_priority: dict[str, int] = field(default_factory=dict)
    total_delayed: int = 0
    total_reordered: int = 0
    total_queue_time_ms: float = 0.0
    max_queue_time_ms: float = 0.0

    @property
    def avg_queue_time_ms(self) -> float:
        if self.total_dispatched == 0:
            return 0.0
        return self.total_queue_time_ms / self.total_dispatched

    def record_dispatch(self, priority: str, queue_time_ms: float, reordered: bool = False) -> None:
        self.total_dispatched += 1
        self.by_priority[priority] = self.by_priority.get(priority, 0) + 1
        self.total_queue_time_ms += queue_time_ms
        self.max_queue_time_ms = max(self.max_queue_time_ms, queue_time_ms)
        if queue_time_ms > 0:
            self.total_delayed += 1
        if reordered:
            self.total_reordered += 1

    def get_summary(self) -> dict[str, Any]:
        return {
            "total_dispatched": self.total_dispatched,
            "by_priority": dict(self.by_priority),
            "total_delayed": self.total_delayed,
            "total_reordered": self.total_reordered,
            "avg_queue_time_ms": round(self.avg_queue_time_ms, 2),
            "max_queue_time_ms": round(self.max_queue_time_ms, 2),
        }

    def reset(self) -> None:
        self.total_dispatched = 0
        self.by_priority.clear()
        self.total_delayed = 0
        self.total_reordered = 0
        self.total_queue_time_ms = 0.0
        self.max_queue_time_ms = 0.0


class PriorityScheduler:
    """Dispatches prioritized requests with queue management and statistics."""

    def __init__(
        self,
        rate_limiter: ConfigurableRateLimiter | None = None,
        max_queue_size: int = 10000,
    ) -> None:
        self._queue = PriorityQueue(max_size=max_queue_size)
        self._rate_limiter = rate_limiter
        self.stats = PriorityStats()
        self._lock = threading.Lock()

    @property
    def queue_size(self) -> int:
        return self._queue.size

    @property
    def queue_empty(self) -> bool:
        return self._queue.is_empty

    def enqueue(self, request: PrioritizedRequest) -> None:
        self._queue.enqueue(request)

    def dequeue(self) -> PrioritizedRequest | None:
        return self._queue.dequeue()

    async def schedule_and_execute(
        self,
        request: PrioritizedRequest,
        execute_fn: Callable[..., Awaitable[Any]],
    ) -> Any:
        """Schedule a request respecting priority and rate limits, then execute."""
        enqueued_at = time.time()

        if self._rate_limiter and request.platform:
            await self._rate_limiter.acquire(request.platform, request.path)

        queue_time_ms = (time.time() - enqueued_at) * 1000

        self.stats.record_dispatch(
            priority=request.priority.value if isinstance(request.priority, RequestPriority) else str(request.priority),
            queue_time_ms=queue_time_ms,
        )

        return await execute_fn(request)

    def get_queue_distribution(self) -> dict[str, int]:
        return self._queue.get_priority_distribution()

    def get_stats_summary(self) -> dict[str, Any]:
        return {
            "queue_size": self.queue_size,
            "queue_distribution": self.get_queue_distribution(),
            "stats": self.stats.get_summary(),
        }

    def reset_stats(self) -> None:
        self.stats.reset()

    def clear_queue(self) -> None:
        self._queue.clear()


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


# ── Request Retry Queue ──────────────────────────────────


@dataclass
class RetryQueueItem:
    """A single item in the retry queue.

    Attributes:
        request_id: Unique identifier for this queued request.
        method: HTTP method ("GET" or "POST").
        path: API endpoint path.
        params: Query parameters.
        data: Request body data.
        created_at: Timestamp when the item was first queued.
        retry_count: Number of retry attempts so far.
        max_retries: Maximum allowed retries for this item.
        next_retry_at: Timestamp when the next retry should be attempted.
        last_error: Error message from the most recent failure.
        status: Current status of the queue item.
        platform: Platform identifier for logging/tracking.
    """

    request_id: str = ""
    method: str = ""
    path: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    retry_count: int = 0
    max_retries: int = 3
    next_retry_at: float = 0.0
    last_error: str = ""
    status: str = "pending"
    platform: str = ""

    def __post_init__(self) -> None:
        if not self.request_id:
            self.request_id = str(uuid.uuid4())
        if self.created_at == 0.0:
            self.created_at = time.time()


@dataclass
class RetryQueueConfig:
    """Configuration for the request retry queue.

    Attributes:
        max_queue_size: Maximum number of items in the queue.
        max_retries: Default maximum retry attempts per item.
        base_delay: Base delay in seconds for exponential backoff.
        max_delay: Maximum delay cap in seconds.
        jitter: Whether to add random jitter to retry delays.
        cleanup_interval: Seconds between cleanup of expired items.
        item_ttl: Maximum time-to-live for a queue item in seconds.
        auto_process: Whether to automatically process the queue in background.
        process_interval: Seconds between automatic queue processing cycles.
        dedup_window: Time window in seconds for request deduplication.
            If 0, deduplication is disabled.
    """

    max_queue_size: int = 1000
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    jitter: bool = True
    cleanup_interval: float = 60.0
    item_ttl: float = 300.0
    auto_process: bool = False
    process_interval: float = 5.0
    dedup_window: float = 30.0

    def compute_delay(self, attempt: int) -> float:
        """Compute delay for a retry attempt using exponential backoff.

        Args:
            attempt: Current attempt number (0-indexed).

        Returns:
            Delay in seconds.
        """
        delay = min(self.base_delay * (2**attempt), self.max_delay)
        if self.jitter:
            delay = delay * (0.5 + random.random())
        return delay


@dataclass
class RetryQueueStats:
    """Statistics for the retry queue.

    Attributes:
        total_enqueued: Total items ever added to the queue.
        total_retried: Total retry attempts executed.
        total_succeeded: Items that eventually succeeded after retry.
        total_failed: Items that exhausted all retries and failed permanently.
        total_expired: Items that expired (TTL exceeded) before completion.
        total_deduplicated: Requests that were deduplicated (not re-enqueued).
        current_pending: Number of items currently pending retry.
        current_in_flight: Number of items currently being retried.
    """

    total_enqueued: int = 0
    total_retried: int = 0
    total_succeeded: int = 0
    total_failed: int = 0
    total_expired: int = 0
    total_deduplicated: int = 0
    current_pending: int = 0
    current_in_flight: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert stats to a dictionary."""
        return {
            "total_enqueued": self.total_enqueued,
            "total_retried": self.total_retried,
            "total_succeeded": self.total_succeeded,
            "total_failed": self.total_failed,
            "total_expired": self.total_expired,
            "total_deduplicated": self.total_deduplicated,
            "current_pending": self.current_pending,
            "current_in_flight": self.current_in_flight,
        }


class RetryRequestQueue:
    """Manages a queue of failed requests for automatic retry with deduplication.

    Provides:
    - Automatic retry scheduling with exponential backoff
    - Request deduplication within a configurable time window
    - Queue management (add, remove, process, drain)
    - Background auto-processing via asyncio task
    - Statistics tracking

    Usage::

        config = RetryQueueConfig(max_retries=3, dedup_window=30.0)
        queue = RetryRequestQueue(config)

        # Enqueue a failed request
        item = await queue.enqueue(method="GET", path="/api/order", params={...})

        # Process the queue (call from your retry handler)
        results = await queue.process(request_fn)
    """

    def __init__(self, config: RetryQueueConfig | None = None) -> None:
        """Initialize the retry request queue.

        Args:
            config: Queue configuration. Uses defaults if None.
        """
        self.config = config or RetryQueueConfig()
        self.stats = RetryQueueStats()
        self._queue: list[RetryQueueItem] = []
        self._in_flight: dict[str, RetryQueueItem] = {}
        self._dedup_hashes: dict[str, float] = {}
        self._lock = threading.Lock()
        self._process_task: asyncio.Task[None] | None = None

    def _compute_request_hash(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None,
        data: dict[str, Any] | None,
    ) -> str:
        """Compute a hash for request deduplication."""
        key_parts = [
            method.upper(),
            path,
            json.dumps(params or {}, sort_keys=True, ensure_ascii=False),
            json.dumps(data or {}, sort_keys=True, ensure_ascii=False),
        ]
        raw = "|".join(key_parts)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _is_duplicate(self, request_hash: str) -> bool:
        """Check if a request is a duplicate within the dedup window."""
        if self.config.dedup_window <= 0:
            return False
        now = time.time()
        last_seen = self._dedup_hashes.get(request_hash)
        if last_seen is not None and (now - last_seen) < self.config.dedup_window:
            return True
        return False

    def _record_hash(self, request_hash: str) -> None:
        """Record a request hash for deduplication tracking."""
        self._dedup_hashes[request_hash] = time.time()

    def _cleanup_hashes(self) -> None:
        """Remove expired dedup hashes."""
        now = time.time()
        expired = [h for h, ts in self._dedup_hashes.items() if (now - ts) >= self.config.dedup_window]
        for h in expired:
            del self._dedup_hashes[h]

    async def enqueue(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        max_retries: int | None = None,
        platform: str = "",
        error: str = "",
        force: bool = False,
    ) -> RetryQueueItem | None:
        """Add a failed request to the retry queue.

        If the request is a duplicate within the dedup window and ``force``
        is False, the request is skipped and dedup stats are incremented.
        """
        request_hash = self._compute_request_hash(method, path, params, data)

        if not force and self._is_duplicate(request_hash):
            with self._lock:
                self.stats.total_deduplicated += 1
            logger.debug(f"Request deduplicated: {method} {path}")
            return None

        with self._lock:
            if len(self._queue) >= self.config.max_queue_size:
                raise ValueError(
                    f"Retry queue full ({self.config.max_queue_size}). "
                    "Process or drain the queue before adding more items."
                )

            now = time.time()
            delay = self.config.compute_delay(0)
            item = RetryQueueItem(
                method=method,
                path=path,
                params=params or {},
                data=data or {},
                created_at=now,
                max_retries=max_retries or self.config.max_retries,
                next_retry_at=now + delay,
                last_error=error,
                platform=platform,
            )
            self._queue.append(item)
            self._record_hash(request_hash)
            self.stats.total_enqueued += 1
            self.stats.current_pending = len(self._queue)

        logger.debug(f"Enqueued retry request: {item.request_id} {method} {path}")
        return item

    async def dequeue_ready(self) -> list[RetryQueueItem]:
        """Remove and return all items that are ready for retry."""
        now = time.time()
        with self._lock:
            ready = [item for item in self._queue if item.next_retry_at <= now]
            self._queue = [item for item in self._queue if item.next_retry_at > now]
            for item in ready:
                item.status = "in_flight"
                self._in_flight[item.request_id] = item
            self.stats.current_pending = len(self._queue)
            self.stats.current_in_flight = len(self._in_flight)
        return ready

    def complete(
        self,
        request_id: str,
        success: bool,
        error: str = "",
    ) -> RetryQueueItem | None:
        """Mark an in-flight request as completed.

        If the request failed and retries remain, it is re-enqueued with
        an incremented retry count and updated delay.
        """
        with self._lock:
            item = self._in_flight.pop(request_id, None)
            if item is None:
                return None

            if success:
                item.status = "succeeded"
                self.stats.total_succeeded += 1
                self.stats.current_in_flight = len(self._in_flight)
                return item

            item.retry_count += 1
            self.stats.total_retried += 1

            if item.retry_count >= item.max_retries:
                item.status = "failed"
                item.last_error = error
                self.stats.total_failed += 1
                self.stats.current_in_flight = len(self._in_flight)
                return item

            now = time.time()
            delay = self.config.compute_delay(item.retry_count)
            item.next_retry_at = now + delay
            item.last_error = error
            item.status = "pending"
            self._queue.append(item)
            self.stats.current_pending = len(self._queue)
            self.stats.current_in_flight = len(self._in_flight)
            return item

    def remove(self, request_id: str) -> bool:
        """Remove an item from the queue by request ID."""
        with self._lock:
            before = len(self._queue)
            self._queue = [item for item in self._queue if item.request_id != request_id]
            removed = len(self._queue) < before
            if removed:
                self.stats.current_pending = len(self._queue)
            return removed

    def drain(self) -> list[RetryQueueItem]:
        """Remove and return all items from the queue."""
        with self._lock:
            items = list(self._queue)
            self._queue.clear()
            self.stats.current_pending = 0
            return items

    def cleanup_expired(self) -> int:
        """Remove items that have exceeded their TTL."""
        now = time.time()
        with self._lock:
            before = len(self._queue)
            self._queue = [item for item in self._queue if (now - item.created_at) < self.config.item_ttl]
            removed = before - len(self._queue)
            if removed:
                self.stats.total_expired += removed
                self.stats.current_pending = len(self._queue)
            self._cleanup_hashes()
            return removed

    async def process(
        self,
        request_fn: Callable[..., Awaitable[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        """Process all ready items in the queue."""
        ready = await self.dequeue_ready()
        results: list[dict[str, Any]] = []

        for item in ready:
            try:
                data = await request_fn(
                    method=item.method,
                    path=item.path,
                    params=item.params,
                    data=item.data,
                )
                self.complete(item.request_id, success=True)
                results.append(
                    {
                        "request_id": item.request_id,
                        "success": True,
                        "data": data,
                    }
                )
            except Exception as exc:
                completed = self.complete(
                    item.request_id,
                    success=False,
                    error=str(exc),
                )
                results.append(
                    {
                        "request_id": item.request_id,
                        "success": False,
                        "error": str(exc),
                        "retry_count": completed.retry_count if completed else 0,
                        "status": completed.status if completed else "unknown",
                    }
                )

        return results

    async def _auto_process_loop(
        self,
        request_fn: Callable[..., Awaitable[dict[str, Any]]],
    ) -> None:
        """Background loop for automatic queue processing."""
        logger.info(f"Retry queue auto-process started (interval={self.config.process_interval}s)")
        while True:
            try:
                self.cleanup_expired()
                if self._queue:
                    results = await self.process(request_fn)
                    succeeded = sum(1 for r in results if r.get("success"))
                    if results:
                        logger.info(f"Auto-process: {succeeded}/{len(results)} succeeded")
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Retry queue auto-process error: {exc}")
            await asyncio.sleep(self.config.process_interval)

    def start_auto_process(
        self,
        request_fn: Callable[..., Awaitable[dict[str, Any]]],
    ) -> asyncio.Task[None]:
        """Start background automatic queue processing."""
        self.stop_auto_process()
        self._process_task = asyncio.ensure_future(self._auto_process_loop(request_fn))
        return self._process_task

    def stop_auto_process(self) -> None:
        """Stop the background auto-process task."""
        if self._process_task is not None and not self._process_task.done():
            self._process_task.cancel()
            self._process_task = None

    @property
    def is_auto_processing(self) -> bool:
        """Whether the auto-process task is active."""
        return self._process_task is not None and not self._process_task.done()

    @property
    def pending_count(self) -> int:
        """Number of items currently pending in the queue."""
        return len(self._queue)

    @property
    def in_flight_count(self) -> int:
        """Number of items currently being retried."""
        return len(self._in_flight)

    def peek(self) -> list[RetryQueueItem]:
        """View all pending items without removing them."""
        with self._lock:
            return list(self._queue)

    def get_stats(self) -> dict[str, Any]:
        """Get queue statistics."""
        with self._lock:
            return {
                "stats": self.stats.to_dict(),
                "queue_size": len(self._queue),
                "in_flight_count": len(self._in_flight),
                "dedup_hashes_count": len(self._dedup_hashes),
                "config": {
                    "max_queue_size": self.config.max_queue_size,
                    "max_retries": self.config.max_retries,
                    "base_delay": self.config.base_delay,
                    "max_delay": self.config.max_delay,
                    "dedup_window": self.config.dedup_window,
                    "item_ttl": self.config.item_ttl,
                },
                "auto_processing": self.is_auto_processing,
            }

    def reset(self) -> None:
        """Reset all queue state and statistics."""
        with self._lock:
            self._queue.clear()
            self._in_flight.clear()
            self._dedup_hashes.clear()
            self.stats = RetryQueueStats()


# ── Request Deduplicator ─────────────────────────────────


@dataclass
class DedupStats:
    """Statistics for request deduplication.

    Attributes:
        total_requests: Total requests checked for deduplication.
        total_deduplicated: Requests that were deduplicated.
        total_unique: Requests that passed dedup (were unique).
        dedup_window_seconds: Configured dedup window.
        active_hashes: Number of currently tracked request hashes.
    """

    total_requests: int = 0
    total_deduplicated: int = 0
    total_unique: int = 0
    dedup_window_seconds: float = 0.0
    active_hashes: int = 0

    @property
    def dedup_rate(self) -> float:
        """Deduplication rate as a fraction."""
        if self.total_requests == 0:
            return 0.0
        return self.total_deduplicated / self.total_requests

    def to_dict(self) -> dict[str, Any]:
        """Convert stats to a dictionary."""
        return {
            "total_requests": self.total_requests,
            "total_deduplicated": self.total_deduplicated,
            "total_unique": self.total_unique,
            "dedup_rate": round(self.dedup_rate, 4),
            "dedup_window_seconds": self.dedup_window_seconds,
            "active_hashes": self.active_hashes,
        }


class RequestDeduplicator:
    """Deduplicates identical API requests within a configurable time window.

    Prevents redundant API calls when multiple callers issue the same request
    concurrently. Uses content-based hashing for identification.

    Usage::

        dedup = RequestDeduplicator(window_seconds=30.0)

        if dedup.check_and_record("GET", "/api/order", params={"id": "123"}):
            # Duplicate, skip
            pass
        else:
            result = await client._request("GET", "/api/order", params={"id": "123"})
    """

    def __init__(self, window_seconds: float = 30.0) -> None:
        """Initialize the deduplicator."""
        self._window = window_seconds
        self._hashes: dict[str, float] = {}
        self._stats = DedupStats(dedup_window_seconds=window_seconds)
        self._lock = threading.Lock()

    @property
    def window_seconds(self) -> float:
        """The configured dedup window in seconds."""
        return self._window

    @window_seconds.setter
    def window_seconds(self, value: float) -> None:
        """Update the dedup window."""
        self._window = value
        self._stats.dedup_window_seconds = value

    def compute_key(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> str:
        """Compute a deduplication key for a request."""
        key_parts = [
            method.upper(),
            path,
            json.dumps(params or {}, sort_keys=True, ensure_ascii=False),
            json.dumps(data or {}, sort_keys=True, ensure_ascii=False),
        ]
        raw = "|".join(key_parts)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def is_duplicate(self, key: str) -> bool:
        """Check if a request key is a duplicate within the window."""
        with self._lock:
            self._stats.total_requests += 1
            now = time.time()
            last_seen = self._hashes.get(key)
            if last_seen is not None and (now - last_seen) < self._window:
                self._stats.total_deduplicated += 1
                return True
            self._stats.total_unique += 1
            return False

    def record(self, key: str) -> None:
        """Record a request key for future deduplication."""
        with self._lock:
            self._hashes[key] = time.time()

    def check_and_record(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> bool:
        """Check for duplicate and record in one atomic operation.

        This is the recommended single-call API for most use cases.

        Returns:
            True if the request is a duplicate (should be skipped).
        """
        key = self.compute_key(method, path, params, data)
        is_dup = self.is_duplicate(key)
        if not is_dup:
            self.record(key)
        return is_dup

    def cleanup(self) -> int:
        """Remove expired dedup hashes."""
        now = time.time()
        with self._lock:
            before = len(self._hashes)
            self._hashes = {h: ts for h, ts in self._hashes.items() if (now - ts) < self._window}
            removed = before - len(self._hashes)
            self._stats.active_hashes = len(self._hashes)
            return removed

    def invalidate(self, key: str | None = None) -> None:
        """Invalidate dedup entries."""
        with self._lock:
            if key is None:
                self._hashes.clear()
            else:
                self._hashes.pop(key, None)
            self._stats.active_hashes = len(self._hashes)

    def get_stats(self) -> dict[str, Any]:
        """Get deduplication statistics."""
        with self._lock:
            self._stats.active_hashes = len(self._hashes)
            return self._stats.to_dict()

    def reset_stats(self) -> None:
        """Reset collected statistics."""
        with self._lock:
            self._stats = DedupStats(dedup_window_seconds=self._window)


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
        delay = min(self.base_delay * (2**attempt), self.max_delay)
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


# ── Cache Warmup ───────────────────────────────────────────


@dataclass
class WarmupTask:
    """A registered cache warmup task.

    Attributes:
        platform: Platform identifier (e.g. "OCEANENGINE", "TAOBAO").
        cache_key: Key used to store the warmed data.
        fetch_fn: Async callable that fetches the data to cache.
        priority: Lower values are warmed first (default 0).
        enabled: Whether this task is active.
    """

    platform: str
    cache_key: str
    fetch_fn: Callable[..., Awaitable[Any]]
    priority: int = 0
    enabled: bool = True


@dataclass
class WarmupResult:
    """Result of a single warmup execution.

    Attributes:
        platform: Platform identifier.
        cache_key: Cache key that was warmed.
        success: Whether the warmup succeeded.
        latency_ms: Duration of the warmup in milliseconds.
        error: Error message if warmup failed.
    """

    platform: str = ""
    cache_key: str = ""
    success: bool = True
    latency_ms: float = 0.0
    error: str = ""


class CacheWarmer:
    """Manages cache warmup tasks for e-commerce platforms.

    Supports three warmup modes:
    1. **Startup warmup**: Warm all registered tasks at once.
    2. **Per-platform warmup**: Warm tasks for a specific platform.
    3. **Scheduled warmup**: Periodically re-warm tasks via an asyncio task.

    Usage::

        warmer = CacheWarmer()
        warmer.register("OCEANENGINE", "hot_products", fetch_hot_products)
        warmer.register("TAOBAO", "categories", fetch_categories)

        # Startup warmup
        results = await warmer.warmup_all()

        # Per-platform
        results = await warmer.warmup_platform("OCEANENGINE")

        # Scheduled (returns an asyncio.Task)
        task = warmer.start_scheduled(interval_seconds=300)
        # ... later ...
        warmer.stop_scheduled()
    """

    def __init__(self) -> None:
        self._tasks: list[WarmupTask] = []
        self._cache: dict[str, Any] = {}
        self._cache_timestamps: dict[str, float] = {}
        self._cache_ttl: dict[str, float] = {}
        self._scheduled_task: asyncio.Task[None] | None = None
        self._lock = threading.Lock()
        self._history: list[WarmupResult] = []

    def register(
        self,
        platform: str,
        cache_key: str,
        fetch_fn: Callable[..., Awaitable[Any]],
        priority: int = 0,
        ttl_seconds: float = 300.0,
        enabled: bool = True,
    ) -> None:
        """Register a warmup task.

        Args:
            platform: Platform identifier.
            cache_key: Key for caching the fetched result.
            fetch_fn: Async callable that returns the data to cache.
            priority: Execution priority (lower = earlier).
            ttl_seconds: TTL for the cached data in seconds.
            enabled: Whether the task is active.
        """
        task = WarmupTask(
            platform=platform,
            cache_key=cache_key,
            fetch_fn=fetch_fn,
            priority=priority,
            enabled=enabled,
        )
        self._tasks.append(task)
        self._cache_ttl[cache_key] = ttl_seconds
        self._tasks.sort(key=lambda t: t.priority)
        logger.debug(f"Registered warmup task: {platform}/{cache_key}")

    def unregister(self, platform: str, cache_key: str) -> bool:
        """Remove a warmup task.

        Args:
            platform: Platform identifier.
            cache_key: Cache key of the task to remove.

        Returns:
            True if the task was found and removed.
        """
        before = len(self._tasks)
        self._tasks = [t for t in self._tasks if not (t.platform == platform and t.cache_key == cache_key)]
        removed = len(self._tasks) < before
        if removed:
            self._cache_ttl.pop(cache_key, None)
        return removed

    async def warmup_all(self) -> list[WarmupResult]:
        """Execute all registered warmup tasks.

        Tasks are executed in priority order. Failed tasks are logged
        but do not prevent subsequent tasks from running.

        Returns:
            List of WarmupResult for each task.
        """
        results: list[WarmupResult] = []
        for task in self._tasks:
            if not task.enabled:
                continue
            result = await self._execute_task(task)
            results.append(result)
        succeeded = sum(1 for r in results if r.success)
        logger.info(f"Warmup complete: {succeeded}/{len(results)} succeeded")
        return results

    async def warmup_platform(self, platform: str) -> list[WarmupResult]:
        """Execute warmup tasks for a specific platform.

        Args:
            platform: Platform identifier.

        Returns:
            List of WarmupResult for matching tasks.
        """
        tasks = [t for t in self._tasks if t.platform == platform and t.enabled]
        results: list[WarmupResult] = []
        for task in tasks:
            result = await self._execute_task(task)
            results.append(result)
        succeeded = sum(1 for r in results if r.success)
        logger.info(f"Warmup for {platform}: {succeeded}/{len(results)} succeeded")
        return results

    async def _execute_task(self, task: WarmupTask) -> WarmupResult:
        """Execute a single warmup task.

        Args:
            task: The WarmupTask to execute.

        Returns:
            WarmupResult with execution details.
        """
        start = time.time()
        try:
            data = await task.fetch_fn()
            elapsed_ms = (time.time() - start) * 1000
            with self._lock:
                self._cache[task.cache_key] = data
                self._cache_timestamps[task.cache_key] = time.time()
            result = WarmupResult(
                platform=task.platform,
                cache_key=task.cache_key,
                success=True,
                latency_ms=elapsed_ms,
            )
            logger.debug(f"Warmed {task.platform}/{task.cache_key} in {elapsed_ms:.1f}ms")
        except Exception as exc:
            elapsed_ms = (time.time() - start) * 1000
            result = WarmupResult(
                platform=task.platform,
                cache_key=task.cache_key,
                success=False,
                latency_ms=elapsed_ms,
                error=str(exc),
            )
            logger.warning(f"Warmup failed for {task.platform}/{task.cache_key}: {exc}")

        self._history.append(result)
        return result

    def get_cached(self, cache_key: str) -> Any | None:
        """Get a value from the warmup cache.

        Args:
            cache_key: The cache key to look up.

        Returns:
            Cached value or None if missing/expired.
        """
        with self._lock:
            ts = self._cache_timestamps.get(cache_key)
            if ts is None:
                return None
            ttl = self._cache_ttl.get(cache_key, 300.0)
            if time.time() - ts > ttl:
                # Expired
                return None
            return self._cache.get(cache_key)

    def set_cached(self, cache_key: str, value: Any, ttl_seconds: float | None = None) -> None:
        """Manually set a value in the warmup cache.

        Args:
            cache_key: Cache key.
            value: Value to store.
            ttl_seconds: TTL override (uses registered TTL if None).
        """
        with self._lock:
            self._cache[cache_key] = value
            self._cache_timestamps[cache_key] = time.time()
            if ttl_seconds is not None:
                self._cache_ttl[cache_key] = ttl_seconds

    def invalidate(self, cache_key: str | None = None) -> None:
        """Invalidate warmup cache entries.

        Args:
            cache_key: Specific key to invalidate, or None to clear all.
        """
        with self._lock:
            if cache_key is None:
                self._cache.clear()
                self._cache_timestamps.clear()
            else:
                self._cache.pop(cache_key, None)
                self._cache_timestamps.pop(cache_key, None)

    def start_scheduled(
        self,
        interval_seconds: float = 300.0,
        warmup_platforms: list[str] | None = None,
    ) -> asyncio.Task[None]:
        """Start a background task that periodically warms the cache.

        Args:
            interval_seconds: Seconds between warmup cycles.
            warmup_platforms: If provided, only warm these platforms.
                             Otherwise, warm all registered tasks.

        Returns:
            The asyncio.Task running the scheduled warmup.
        """
        self.stop_scheduled()

        async def _warmup_loop() -> None:
            logger.info(f"Scheduled warmup started (interval={interval_seconds}s)")
            while True:
                try:
                    if warmup_platforms:
                        for platform in warmup_platforms:
                            await self.warmup_platform(platform)
                    else:
                        await self.warmup_all()
                except Exception as exc:
                    logger.error(f"Scheduled warmup error: {exc}")
                await asyncio.sleep(interval_seconds)

        self._scheduled_task = asyncio.ensure_future(_warmup_loop())
        return self._scheduled_task

    def stop_scheduled(self) -> None:
        """Stop the scheduled warmup task if running."""
        if self._scheduled_task is not None and not self._scheduled_task.done():
            self._scheduled_task.cancel()
            self._scheduled_task = None
            logger.info("Scheduled warmup stopped")

    @property
    def is_scheduled(self) -> bool:
        """Whether a scheduled warmup task is active."""
        return self._scheduled_task is not None and not self._scheduled_task.done()

    def get_stats(self) -> dict[str, Any]:
        """Get warmup cache statistics.

        Returns:
            Dict with registered_tasks, cached_keys, and history summary.
        """
        with self._lock:
            now = time.time()
            valid_keys = [k for k, ts in self._cache_timestamps.items() if now - ts <= self._cache_ttl.get(k, 300.0)]
            total = len(self._history)
            succeeded = sum(1 for r in self._history if r.success)
            return {
                "registered_tasks": len(self._tasks),
                "cached_keys": valid_keys,
                "cached_count": len(valid_keys),
                "scheduled": self.is_scheduled,
                "history": {
                    "total": total,
                    "succeeded": succeeded,
                    "failed": total - succeeded,
                },
            }

    def get_history(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get recent warmup history.

        Args:
            limit: Maximum number of entries to return.

        Returns:
            List of warmup result dicts.
        """
        recent = self._history[-limit:] if limit > 0 else self._history
        return [
            {
                "platform": r.platform,
                "cache_key": r.cache_key,
                "success": r.success,
                "latency_ms": round(r.latency_ms, 2),
                "error": r.error,
            }
            for r in recent
        ]


# ── Request Compression ────────────────────────────────────


class CompressionMethod(StrEnum):
    """Supported request body compression methods.

    Attributes:
        NONE: No compression.
        GZIP: gzip compression (RFC 1952).
        DEFLATE: deflate compression (RFC 1951).
        AUTO: Automatically choose the best method based on
              Accept-Encoding headers or default to gzip.
    """

    NONE = "none"
    GZIP = "gzip"
    DEFLATE = "deflate"
    AUTO = "auto"


@dataclass
class CompressionConfig:
    """Configuration for request body compression.

    Attributes:
        method: Compression method to use.
        min_size_bytes: Minimum body size in bytes to trigger compression.
            Bodies smaller than this are sent uncompressed.
        gzip_level: gzip compression level (1-9). Higher = smaller but slower.
        include_content_encoding: Whether to set the Content-Encoding header.
    """

    method: CompressionMethod = CompressionMethod.NONE
    min_size_bytes: int = 1024  # 1 KB
    gzip_level: int = 6
    include_content_encoding: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dictionary."""
        return {
            "method": self.method.value,
            "min_size_bytes": self.min_size_bytes,
            "gzip_level": self.gzip_level,
            "include_content_encoding": self.include_content_encoding,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CompressionConfig:
        """Deserialize from a dictionary."""
        return cls(
            method=CompressionMethod(data.get("method", "none")),
            min_size_bytes=data.get("min_size_bytes", 1024),
            gzip_level=data.get("gzip_level", 6),
            include_content_encoding=data.get("include_content_encoding", True),
        )


class RequestCompressor:
    """Compresses request bodies for API calls.

    Supports gzip and deflate compression with configurable thresholds.
    Automatically selects the best compression method when set to AUTO.

    Usage::

        compressor = RequestCompressor(CompressionConfig(method=CompressionMethod.GZIP))
        body, headers = compressor.compress(b'{"data": "..."}')
    """

    def __init__(self, config: CompressionConfig | None = None) -> None:
        """Initialize the compressor.

        Args:
            config: Compression configuration. Uses defaults if None.
        """
        self.config = config or CompressionConfig()
        self._stats_lock = threading.Lock()
        self._total_requests = 0
        self._compressed_requests = 0
        self._total_original_bytes = 0
        self._total_compressed_bytes = 0

    def compress(
        self,
        body: bytes,
        accept_encoding: str = "",
    ) -> tuple[bytes, dict[str, str]]:
        """Compress a request body.

        Args:
            body: Raw request body bytes.
            accept_encoding: The Accept-Encoding header value from the server
                to determine the best compression method (used with AUTO).

        Returns:
            Tuple of (compressed_body, extra_headers).
            If compression is skipped, returns (original_body, {}).
        """
        method = self._resolve_method(accept_encoding)

        # Track stats
        with self._stats_lock:
            self._total_requests += 1
            self._total_original_bytes += len(body)

        # Skip compression for small bodies or NONE method
        if method == CompressionMethod.NONE or len(body) < self.config.min_size_bytes:
            with self._stats_lock:
                self._total_compressed_bytes += len(body)
            return body, {}

        compressed, encoding = self._do_compress(body, method)

        # Only use compression if it actually reduces size
        if len(compressed) >= len(body):
            with self._stats_lock:
                self._total_compressed_bytes += len(body)
            return body, {}

        headers: dict[str, str] = {}
        if self.config.include_content_encoding:
            headers["Content-Encoding"] = encoding

        with self._stats_lock:
            self._compressed_requests += 1
            self._total_compressed_bytes += len(compressed)

        logger.debug(
            f"Compressed {len(body)} -> {len(compressed)} bytes "
            f"({100 - len(compressed) * 100 // len(body)}% reduction) using {encoding}"
        )
        return compressed, headers

    def _resolve_method(self, accept_encoding: str) -> CompressionMethod:
        """Resolve the actual compression method to use.

        Args:
            accept_encoding: Accept-Encoding header value.

        Returns:
            The resolved CompressionMethod (never AUTO).
        """
        if self.config.method != CompressionMethod.AUTO:
            return self.config.method

        # Parse Accept-Encoding to find supported methods
        supported = {m.strip().lower() for m in accept_encoding.split(",")}
        if "gzip" in supported or "x-gzip" in supported:
            return CompressionMethod.GZIP
        if "deflate" in supported:
            return CompressionMethod.DEFLATE
        # Default to gzip when AUTO and nothing specified
        return CompressionMethod.GZIP

    def _do_compress(self, body: bytes, method: CompressionMethod) -> tuple[bytes, str]:
        """Perform the actual compression.

        Args:
            body: Body bytes to compress.
            method: Compression method (must not be NONE or AUTO).

        Returns:
            Tuple of (compressed_bytes, encoding_name).
        """
        if method == CompressionMethod.GZIP:
            return gzip.compress(body, compresslevel=self.config.gzip_level), "gzip"
        elif method == CompressionMethod.DEFLATE:
            return zlib.compress(body, level=self.config.gzip_level), "deflate"
        else:
            return body, ""

    def get_stats(self) -> dict[str, Any]:
        """Get compression statistics.

        Returns:
            Dict with compression counts, ratios, and bytes saved.
        """
        with self._stats_lock:
            ratio = 0.0
            if self._total_original_bytes > 0:
                ratio = 1.0 - (self._total_compressed_bytes / self._total_original_bytes)
            return {
                "total_requests": self._total_requests,
                "compressed_requests": self._compressed_requests,
                "compression_rate": (
                    round(self._compressed_requests / self._total_requests, 4) if self._total_requests > 0 else 0.0
                ),
                "total_original_bytes": self._total_original_bytes,
                "total_compressed_bytes": self._total_compressed_bytes,
                "bytes_saved": self._total_original_bytes - self._total_compressed_bytes,
                "avg_compression_ratio": round(ratio, 4),
            }

    def reset_stats(self) -> None:
        """Reset all collected statistics."""
        with self._stats_lock:
            self._total_requests = 0
            self._compressed_requests = 0
            self._total_original_bytes = 0
            self._total_compressed_bytes = 0


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
        compression_config: CompressionConfig | None = None,
        rate_limit_config: RateLimitConfig | None = None,
        validate_input: bool = True,
    ) -> None:
        self.app_key = app_key
        self.app_secret = app_secret
        self.access_token = access_token
        self.validate_input = validate_input
        self.rate_limiter = RateLimiter()
        self.metrics = MetricsCollector()
        self._reconnect_config = reconnect_config or ReconnectConfig()
        self._health_cache = HealthCheckCache(ttl_seconds=30.0)
        self.cache_warmer = CacheWarmer()
        self._compressor = RequestCompressor(compression_config)
        self._configurable_limiter = ConfigurableRateLimiter(rate_limit_config)
        self._priority_scheduler = PriorityScheduler(rate_limiter=self._configurable_limiter)
        self._alert_manager = AlertManager()
        # Live request observability: every _request is traced and metered.
        self._tracer = RequestTracer(self.__class__.__name__)
        # Opt-in capabilities, lazily constructed on first access (see properties).
        self._webhook_manager: WebhookManager | None = None
        self._load_balancer: LoadBalancer | None = None
        self._request_recorder: RequestRecorder | None = None
        self._deduplicator: RequestDeduplicator | None = None

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
                    logger.error(f"Auto-reconnect failed after {cfg.max_retries + 1} attempts: {exc}")
                    raise

                delay = cfg.compute_delay(attempt)
                logger.warning(
                    f"Reconnect attempt {attempt + 1}/{cfg.max_retries} failed: {exc}. " f"Retrying in {delay:.2f}s"
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

        # Reject injection-style payloads before they reach the upstream API.
        if self.validate_input:
            self._validate_params(params)
            self._validate_params(data)

        # Snapshot auth params for retry (timestamp must be regenerated each attempt)
        auth_params: dict[str, str] = {}
        auth_params["app_key"] = self.app_key
        if self.access_token:
            auth_params["access_token"] = self.access_token

        last_exc: Exception | None = None
        max_attempts = (retry_config.max_retries + 1) if retry_config else 1

        # One trace span per logical request (covers all retry attempts).
        span = self._tracer.start_span(f"{method} {path}", attributes={"method": method, "path": path})

        for attempt in range(max_attempts):
            attempt_start = time.time()
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
                    # Compress POST body if configured
                    extra_headers: dict[str, str] = {}
                    if self._compressor.config.method != CompressionMethod.NONE and data:
                        body_bytes = json.dumps(data, ensure_ascii=False).encode("utf-8")
                        compressed_body, extra_headers = self._compressor.compress(body_bytes)
                        if extra_headers:
                            resp = await client.post(
                                url,
                                params=attempt_params,
                                content=compressed_body,
                                headers={**extra_headers, "Content-Type": "application/json"},
                            )
                        else:
                            resp = await client.post(url, params=attempt_params, json=data)
                    else:
                        resp = await client.post(url, params=attempt_params, json=data)

                result = resp.json()
                if "error_response" in result:
                    error_code = result["error_response"].get("code", -1)
                    error_msg = result["error_response"].get("msg", "unknown")
                    logger.warning(f"API error: [{error_code}] {error_msg}")
                    raise CommerceAPIError(code=error_code, msg=error_msg)

                logger.debug(f"Response: {resp.status_code}")
                self.metrics.record_request(path, (time.time() - attempt_start) * 1000, success=True)
                self._tracer.finish_span(span, status="ok")
                return result

            except Exception as exc:
                last_exc = exc
                err_code = exc.code if isinstance(exc, CommerceAPIError) else 0
                self.metrics.record_request(
                    path, (time.time() - attempt_start) * 1000, success=False, error_code=err_code, error_msg=str(exc)
                )
                # If no retry config or not retryable, re-raise immediately
                if not retry_config or not retry_config.should_retry_exception(exc):
                    self._tracer.finish_span(span, status="error")
                    raise

                # If this was the last attempt, re-raise
                if attempt == max_attempts - 1:
                    logger.error(f"Max retries ({retry_config.max_retries}) exhausted for {path}")
                    self._tracer.finish_span(span, status="error")
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

    # ── Input validation ──────────────────────────────────

    def _validate_params(self, params: dict[str, Any]) -> None:
        """Validate string parameter values for injection patterns.

        Only string values are checked; numeric/bool values are inherently
        safe. Raises ``ValueError`` on the first suspicious value.
        """
        for name, value in params.items():
            if isinstance(value, str):
                validate_api_param(name, value)

    # ── Common observability / data accessors ─────────────
    # These surface the always-on middleware to callers; register_common_tools()
    # exposes them as MCP tools shared by every platform server.

    def get_metrics_summary(self) -> dict[str, Any]:
        """Return a snapshot of per-endpoint request metrics (latency, errors)."""
        return self.metrics.get_summary()

    def get_trace_summary(self) -> dict[str, Any]:
        """Return a summary of recent request traces (spans, durations, status)."""
        return self._tracer.get_trace_summary()

    def get_alerts(self) -> dict[str, Any]:
        """Evaluate alert rules against current metrics and report firing alerts."""
        summary = self.metrics.get_summary()
        fired = self._alert_manager.evaluate_metrics(summary, platform=self.__class__.__name__)
        return {
            "firing": [a.to_dict() for a in fired],
            "stats": self._alert_manager.get_stats(),
        }

    def export_data(self, records: list[dict[str, Any]], fmt: str = "json") -> str:
        """Export a list of records to a CSV or JSON string."""
        export_format = ExportFormat.CSV if str(fmt).lower() == "csv" else ExportFormat.JSON
        return DataExporter.export_to_string(records, format=export_format)

    # ── Signing ───────────────────────────────────────────

    def _sign(self, params: dict[str, Any]) -> str:
        """Generate signature for request params."""
        # Remove sign and sign_method, sort by key
        to_sign = {k: v for k, v in params.items() if k not in ("sign", "sign_method") and v != ""}
        sorted_keys = sorted(to_sign.keys())
        raw = (
            self.app_secret
            + "".join(f"{k}{canonicalize_sign_value(to_sign[k])}" for k in sorted_keys)
            + self.app_secret
        )

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
                except TimeoutError:
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

    # ── Cache Warmup Convenience ────────────────────────────

    async def warmup_cache(self, platforms: list[str] | None = None) -> list[dict[str, Any]]:
        """Warm cache for specified platforms or all registered tasks.

        Args:
            platforms: List of platform identifiers. If None, warm all.

        Returns:
            List of warmup result dicts.
        """
        if platforms:
            results: list[WarmupResult] = []
            for platform in platforms:
                results.extend(await self.cache_warmer.warmup_platform(platform))
        else:
            results = await self.cache_warmer.warmup_all()
        return [
            {
                "platform": r.platform,
                "cache_key": r.cache_key,
                "success": r.success,
                "latency_ms": round(r.latency_ms, 2),
                "error": r.error,
            }
            for r in results
        ]

    def get_compression_stats(self) -> dict[str, Any]:
        """Get request compression statistics.

        Returns:
            Dict with compression metrics.
        """
        return self._compressor.get_stats()

    # ── Priority Scheduling Convenience ────────────────────

    async def prioritized_request(
        self,
        method: str,
        path: str,
        priority: RequestPriority = RequestPriority.NORMAL,
        params: dict | None = None,
        data: dict | None = None,
        request_id: str = "",
    ) -> dict[str, Any]:
        """Make a priority-aware API request."""
        request = PrioritizedRequest(
            priority=priority,
            method=method,
            path=path,
            params=params or {},
            data=data or {},
            request_id=request_id,
            platform=self.__class__.__name__.upper(),
        )
        return await self._priority_scheduler.schedule_and_execute(
            request,
            execute_fn=lambda r: self._request(r.method, r.path, params=dict(r.params), data=dict(r.data)),
        )

    @property
    def priority_scheduler(self) -> PriorityScheduler:
        """Access the priority scheduler."""
        return self._priority_scheduler

    @property
    def configurable_limiter(self) -> ConfigurableRateLimiter:
        """Access the configurable rate limiter."""
        return self._configurable_limiter

    def get_priority_stats(self) -> dict[str, Any]:
        """Get priority scheduling statistics."""
        return self._priority_scheduler.get_stats_summary()

    def get_rate_limit_stats(self) -> dict[str, Any]:
        """Get configurable rate limiter statistics."""
        return self._configurable_limiter.get_stats_summary()

    def auto_adjust_rate_limits(self, **kwargs: Any) -> dict[str, Any]:
        """Auto-adjust rate limits based on throttle statistics."""
        return self._configurable_limiter.auto_adjust_from_stats(**kwargs)

    # ── Alerting Convenience ───────────────────────────────

    @property
    def alert_manager(self) -> AlertManager:
        """Access the alert manager."""
        return self._alert_manager

    def evaluate_alerts(
        self,
        platform: str = "",
        endpoint: str = "",
    ) -> list[Alert]:
        """Evaluate current metrics against alert rules.

        Args:
            platform: Current platform context.
            endpoint: Current endpoint context.

        Returns:
            List of triggered Alert instances.
        """
        summary = self.metrics.get_summary()
        return self._alert_manager.evaluate_metrics(summary, platform=platform, endpoint=endpoint)

    async def check_and_fire_alerts(
        self,
        platform: str = "",
        endpoint: str = "",
    ) -> list[dict[str, Any]]:
        """Evaluate metrics and fire any triggered alerts.

        Combines evaluate_alerts and fire_alert in a single call.

        Args:
            platform: Current platform context.
            endpoint: Current endpoint context.

        Returns:
            List of notification results for fired alerts.
        """
        alerts = self.evaluate_alerts(platform=platform, endpoint=endpoint)
        results: list[dict[str, Any]] = []
        for alert in alerts:
            result = await self._alert_manager.fire_alert(alert)
            results.append(result)
        return results

    def get_alert_stats(self) -> dict[str, Any]:
        """Get alert manager statistics."""
        return self._alert_manager.get_stats()

    # ── Opt-in Advanced Capabilities (lazy accessors) ──────
    #
    # These wrappers make standalone opt-in helpers reachable from a base
    # instance without changing any request behaviour. Each is lazily
    # constructed on first access so the common path stays lightweight.

    @property
    def webhook_manager(self) -> WebhookManager:
        """Access a lazily-created webhook manager for this instance."""
        existing = getattr(self, "_webhook_manager", None)
        if existing is None:
            existing = WebhookManager()
            self._webhook_manager = existing
        return existing

    @property
    def load_balancer(self) -> LoadBalancer:
        """Access a lazily-created load balancer for this instance."""
        existing = getattr(self, "_load_balancer", None)
        if existing is None:
            existing = LoadBalancer()
            self._load_balancer = existing
        return existing

    def create_failover_manager(self, config: FailoverConfig | None = None) -> FailoverManager:
        """Create a failover manager bound to this instance's load balancer."""
        return FailoverManager(self.load_balancer, config=config)

    @property
    def request_recorder(self) -> RequestRecorder:
        """Access a lazily-created request recorder for this instance."""
        existing = getattr(self, "_request_recorder", None)
        if existing is None:
            existing = RequestRecorder()
            self._request_recorder = existing
        return existing

    def create_replayer(self, config: ReplayConfig | None = None) -> RequestReplayer:
        """Create a replayer bound to this instance's request recorder."""
        return RequestReplayer(self.request_recorder, config=config)

    @property
    def deduplicator(self) -> RequestDeduplicator:
        """Access a lazily-created request deduplicator for this instance."""
        existing = getattr(self, "_deduplicator", None)
        if existing is None:
            existing = RequestDeduplicator()
            self._deduplicator = existing
        return existing

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
                    result.add_error(f"Configuration '{full_key}' does not match required pattern: {rule.pattern}")

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
                    result.add_error(f"Configuration '{full_key}' value {value} is below minimum {rule.min_value}")
                if rule.max_value is not None and value > rule.max_value:
                    result.invalid_keys.append(full_key)
                    result.add_error(f"Configuration '{full_key}' value {value} is above maximum {rule.max_value}")

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
                    error_msg = f"Configuration '{full_key}' requires '{full_dep}' to be set"
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


# ── Load Balancing ─────────────────────────────────────────


class LoadBalancingStrategy(StrEnum):
    """Supported load balancing strategies.

    Attributes:
        ROUND_ROBIN: Distributes requests sequentially across endpoints.
        WEIGHTED: Distributes requests based on endpoint weights.
        LEAST_CONNECTIONS: Routes to the endpoint with fewest active connections.
    """

    ROUND_ROBIN = "round_robin"
    WEIGHTED = "weighted"
    LEAST_CONNECTIONS = "least_connections"


@dataclass
class EndpointNode:
    """Represents a single endpoint in a load balancing pool.

    Attributes:
        url: The endpoint URL.
        weight: Relative weight for weighted load balancing (higher = more traffic).
        active_connections: Current number of active connections.
        is_healthy: Whether the endpoint is currently considered healthy.
        failure_count: Number of consecutive failures.
        last_failure_time: Timestamp of the last failure (0.0 if never failed).
        total_requests: Total requests routed to this endpoint.
        total_failures: Total failures for this endpoint.
        avg_latency_ms: Rolling average latency in milliseconds.
    """

    url: str = ""
    weight: int = 1
    active_connections: int = 0
    is_healthy: bool = True
    failure_count: int = 0
    last_failure_time: float = 0.0
    total_requests: int = 0
    total_failures: int = 0
    avg_latency_ms: float = 0.0


class LoadBalancer:
    """Distributes requests across multiple endpoints using configurable strategies.

    Supports round-robin, weighted, and least-connections load balancing.
    Integrates with failover to automatically skip unhealthy endpoints.

    Usage::

        lb = LoadBalancer(LoadBalancingStrategy.WEIGHTED)
        lb.add_endpoint("https://api1.example.com", weight=3)
        lb.add_endpoint("https://api2.example.com", weight=1)
        endpoint = lb.get_endpoint()
    """

    def __init__(self, strategy: LoadBalancingStrategy = LoadBalancingStrategy.ROUND_ROBIN) -> None:
        """Initialize the load balancer.

        Args:
            strategy: The load balancing strategy to use.
        """
        self.strategy = strategy
        self._endpoints: dict[str, EndpointNode] = {}
        self._round_robin_index: int = 0
        self._lock = threading.Lock()

    def add_endpoint(self, url: str, weight: int = 1) -> EndpointNode:
        """Add an endpoint to the pool.

        Args:
            url: The endpoint URL.
            weight: Relative weight for weighted load balancing.

        Returns:
            The created EndpointNode.
        """
        with self._lock:
            if url in self._endpoints:
                existing = self._endpoints[url]
                existing.weight = weight
                return existing
            node = EndpointNode(url=url, weight=max(1, weight))
            self._endpoints[url] = node
            logger.info(f"Load balancer: added endpoint {url} (weight={weight})")
            return node

    def remove_endpoint(self, url: str) -> bool:
        """Remove an endpoint from the pool.

        Args:
            url: The endpoint URL to remove.

        Returns:
            True if the endpoint was found and removed.
        """
        with self._lock:
            if url in self._endpoints:
                del self._endpoints[url]
                logger.info(f"Load balancer: removed endpoint {url}")
                return True
            return False

    def mark_healthy(self, url: str) -> None:
        """Mark an endpoint as healthy.

        Args:
            url: The endpoint URL.
        """
        with self._lock:
            node = self._endpoints.get(url)
            if node:
                was_unhealthy = not node.is_healthy
                node.is_healthy = True
                node.failure_count = 0
                if was_unhealthy:
                    logger.info(f"Load balancer: endpoint {url} recovered")

    def mark_unhealthy(self, url: str) -> None:
        """Mark an endpoint as unhealthy.

        Args:
            url: The endpoint URL.
        """
        with self._lock:
            node = self._endpoints.get(url)
            if node:
                node.is_healthy = False
                node.failure_count += 1
                node.total_failures += 1
                node.last_failure_time = time.time()
                logger.warning(f"Load balancer: endpoint {url} marked unhealthy " f"(failures={node.failure_count})")

    def record_success(self, url: str, latency_ms: float = 0.0) -> None:
        """Record a successful request to an endpoint.

        Args:
            url: The endpoint URL.
            latency_ms: Request latency in milliseconds.
        """
        with self._lock:
            node = self._endpoints.get(url)
            if node:
                node.total_requests += 1
                # Exponential moving average for latency
                if node.avg_latency_ms == 0.0:
                    node.avg_latency_ms = latency_ms
                else:
                    node.avg_latency_ms = 0.8 * node.avg_latency_ms + 0.2 * latency_ms

    def record_failure(self, url: str) -> None:
        """Record a failed request to an endpoint.

        Args:
            url: The endpoint URL.
        """
        self.mark_unhealthy(url)

    def _get_healthy_endpoints(self) -> list[EndpointNode]:
        """Get all healthy endpoints."""
        return [n for n in self._endpoints.values() if n.is_healthy]

    def get_endpoint(self) -> EndpointNode | None:
        """Select the next endpoint based on the load balancing strategy.

        Returns:
            The selected EndpointNode, or None if no healthy endpoints are available.
        """
        with self._lock:
            healthy = self._get_healthy_endpoints()
            if not healthy:
                logger.warning("Load balancer: no healthy endpoints available")
                return None

            if self.strategy == LoadBalancingStrategy.ROUND_ROBIN:
                return self._round_robin(healthy)
            elif self.strategy == LoadBalancingStrategy.WEIGHTED:
                return self._weighted(healthy)
            elif self.strategy == LoadBalancingStrategy.LEAST_CONNECTIONS:
                return self._least_connections(healthy)
            else:
                return self._round_robin(healthy)

    def _round_robin(self, endpoints: list[EndpointNode]) -> EndpointNode:
        """Select endpoint using round-robin.

        Args:
            endpoints: List of healthy endpoints.

        Returns:
            Selected endpoint.
        """
        idx = self._round_robin_index % len(endpoints)
        self._round_robin_index += 1
        return endpoints[idx]

    def _weighted(self, endpoints: list[EndpointNode]) -> EndpointNode:
        """Select endpoint using weighted random selection.

        Args:
            endpoints: List of healthy endpoints.

        Returns:
            Selected endpoint.
        """
        total_weight = sum(e.weight for e in endpoints)
        if total_weight <= 0:
            return endpoints[0]

        r = random.random() * total_weight
        cumulative = 0.0
        for endpoint in endpoints:
            cumulative += endpoint.weight
            if r <= cumulative:
                return endpoint
        return endpoints[-1]

    def _least_connections(self, endpoints: list[EndpointNode]) -> EndpointNode:
        """Select the endpoint with the fewest active connections.

        Args:
            endpoints: List of healthy endpoints.

        Returns:
            Selected endpoint.
        """
        return min(endpoints, key=lambda e: e.active_connections)

    def increment_connections(self, url: str) -> None:
        """Increment active connection count for an endpoint.

        Args:
            url: The endpoint URL.
        """
        with self._lock:
            node = self._endpoints.get(url)
            if node:
                node.active_connections += 1

    def decrement_connections(self, url: str) -> None:
        """Decrement active connection count for an endpoint.

        Args:
            url: The endpoint URL.
        """
        with self._lock:
            node = self._endpoints.get(url)
            if node:
                node.active_connections = max(0, node.active_connections - 1)

    def get_stats(self) -> dict[str, Any]:
        """Get load balancer statistics.

        Returns:
            Dict with strategy, endpoint count, healthy count, and per-endpoint stats.
        """
        with self._lock:
            total = len(self._endpoints)
            healthy = sum(1 for n in self._endpoints.values() if n.is_healthy)
            return {
                "strategy": self.strategy.value,
                "total_endpoints": total,
                "healthy_endpoints": healthy,
                "unhealthy_endpoints": total - healthy,
                "endpoints": {
                    url: {
                        "url": n.url,
                        "weight": n.weight,
                        "active_connections": n.active_connections,
                        "is_healthy": n.is_healthy,
                        "failure_count": n.failure_count,
                        "total_requests": n.total_requests,
                        "total_failures": n.total_failures,
                        "avg_latency_ms": round(n.avg_latency_ms, 2),
                    }
                    for url, n in self._endpoints.items()
                },
            }

    @property
    def endpoint_count(self) -> int:
        """Number of endpoints in the pool."""
        return len(self._endpoints)

    @property
    def healthy_count(self) -> int:
        """Number of healthy endpoints."""
        return sum(1 for n in self._endpoints.values() if n.is_healthy)


# ── Failover ──────────────────────────────────────────────


@dataclass
class FailoverConfig:
    """Configuration for the failover mechanism.

    Attributes:
        max_failures: Number of consecutive failures before marking endpoint unhealthy.
        recovery_check_interval: Seconds between recovery probe attempts.
        recovery_timeout: Timeout for recovery probes in seconds.
        enable_auto_recovery: Whether to automatically attempt recovery of failed endpoints.
        circuit_breaker_threshold: Failure rate (0.0-1.0) to trip circuit breaker.
        circuit_breaker_reset_seconds: Seconds before resetting a tripped circuit breaker.
    """

    max_failures: int = 3
    recovery_check_interval: float = 30.0
    recovery_timeout: float = 5.0
    enable_auto_recovery: bool = True
    circuit_breaker_threshold: float = 0.5
    circuit_breaker_reset_seconds: float = 60.0


@dataclass
class CircuitBreakerState:
    """State of a circuit breaker for an endpoint.

    Attributes:
        url: The endpoint URL.
        is_open: Whether the circuit is open (requests blocked).
        failure_count: Number of failures since last reset.
        success_count: Number of successes since last reset.
        last_failure_time: Timestamp of last failure.
        opened_at: Timestamp when the circuit was opened.
    """

    url: str = ""
    is_open: bool = False
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: float = 0.0
    opened_at: float = 0.0


class FailoverManager:
    """Manages automatic failover and recovery for API endpoints.

    Works with ``LoadBalancer`` to detect failures, mark endpoints unhealthy,
    and periodically probe them for recovery.

    Features:
    - Automatic failure detection and endpoint marking
    - Circuit breaker pattern to prevent cascading failures
    - Background recovery probing
    - Configurable thresholds and timeouts

    Usage::

        lb = LoadBalancer()
        lb.add_endpoint("https://api1.example.com")
        lb.add_endpoint("https://api2.example.com")

        fm = FailoverManager(load_balancer=lb, config=FailoverConfig(max_failures=3))
        endpoint = fm.get_healthy_endpoint()
        fm.report_success("https://api1.example.com")
        fm.report_failure("https://api1.example.com")
    """

    def __init__(
        self,
        load_balancer: LoadBalancer,
        config: FailoverConfig | None = None,
    ) -> None:
        """Initialize the failover manager.

        Args:
            load_balancer: The load balancer to manage.
            config: Failover configuration. Uses defaults if not provided.
        """
        self._lb = load_balancer
        self.config = config or FailoverConfig()
        self._circuit_breakers: dict[str, CircuitBreakerState] = {}
        # Reentrant: get_healthy_endpoint() holds the lock and calls
        # is_circuit_open(), which re-acquires it.
        self._lock = threading.RLock()
        self._recovery_task: asyncio.Task | None = None
        self._failure_history: list[dict[str, Any]] = []

    def report_success(self, url: str, latency_ms: float = 0.0) -> None:
        """Report a successful request to an endpoint.

        Resets the failure count and closes the circuit breaker if applicable.

        Args:
            url: The endpoint URL.
            latency_ms: Request latency in milliseconds.
        """
        with self._lock:
            self._lb.record_success(url, latency_ms)
            self._lb.mark_healthy(url)

            # Reset circuit breaker
            cb = self._circuit_breakers.get(url)
            if cb:
                cb.failure_count = 0
                cb.success_count += 1
                if cb.is_open:
                    cb.is_open = False
                    logger.info(f"Failover: circuit breaker closed for {url}")

    def report_failure(self, url: str, error: str = "") -> None:
        """Report a failed request to an endpoint.

        Increments the failure count and may mark the endpoint unhealthy
        or open the circuit breaker.

        Args:
            url: The endpoint URL.
            error: Error message for logging.
        """
        with self._lock:
            node = self._lb._endpoints.get(url)
            if not node:
                return

            node.failure_count += 1
            node.total_failures += 1
            node.last_failure_time = time.time()
            node.total_requests += 1

            # Record in history
            self._failure_history.append(
                {
                    "url": url,
                    "error": error,
                    "timestamp": time.time(),
                    "failure_count": node.failure_count,
                }
            )
            # Keep history bounded
            if len(self._failure_history) > 1000:
                self._failure_history = self._failure_history[-500:]

            # Mark unhealthy if max failures exceeded
            if node.failure_count >= self.config.max_failures:
                self._lb.mark_unhealthy(url)

            # Check circuit breaker
            self._check_circuit_breaker(url)

            logger.warning(f"Failover: failure reported for {url} " f"(count={node.failure_count}, error={error})")

    def _check_circuit_breaker(self, url: str) -> None:
        """Check and update circuit breaker state.

        Args:
            url: The endpoint URL.
        """
        node = self._lb._endpoints.get(url)
        if not node:
            return

        cb = self._circuit_breakers.get(url)
        if cb is None:
            cb = CircuitBreakerState(url=url)
            self._circuit_breakers[url] = cb

        cb.failure_count = node.failure_count
        cb.last_failure_time = time.time()

        total = cb.failure_count + cb.success_count
        if total >= 5:  # Need at least 5 requests to evaluate
            failure_rate = cb.failure_count / total
            if failure_rate >= self.config.circuit_breaker_threshold and not cb.is_open:
                cb.is_open = True
                cb.opened_at = time.time()
                self._lb.mark_unhealthy(url)
                logger.warning(f"Failover: circuit breaker OPENED for {url} " f"(failure_rate={failure_rate:.2f})")

    def is_circuit_open(self, url: str) -> bool:
        """Check if the circuit breaker is open for an endpoint.

        Args:
            url: The endpoint URL.

        Returns:
            True if the circuit is open (endpoint should not receive traffic).
        """
        with self._lock:
            cb = self._circuit_breakers.get(url)
            if cb is None or not cb.is_open:
                return False

            # Check if circuit breaker should be reset
            elapsed = time.time() - cb.opened_at
            if elapsed >= self.config.circuit_breaker_reset_seconds:
                cb.is_open = False
                cb.failure_count = 0
                cb.success_count = 0
                logger.info(f"Failover: circuit breaker reset for {url}")
                return False

            return True

    def get_healthy_endpoint(self) -> EndpointNode | None:
        """Get a healthy endpoint from the load balancer, respecting circuit breakers.

        Returns:
            A healthy EndpointNode, or None if none available.
        """
        with self._lock:
            # Try up to the number of endpoints to find one without an open circuit
            for _ in range(self._lb.endpoint_count):
                endpoint = self._lb.get_endpoint()
                if endpoint is None:
                    return None
                if not self.is_circuit_open(endpoint.url):
                    return endpoint
            return None

    async def check_recovery(self, url: str) -> bool:
        """Probe a failed endpoint to check if it has recovered.

        Args:
            url: The endpoint URL to probe.

        Returns:
            True if the endpoint responded successfully.
        """
        try:
            async with httpx.AsyncClient(timeout=self.config.recovery_timeout) as client:
                resp = await client.head(url)
                if resp.status_code < 500:
                    self._lb.mark_healthy(url)
                    # Reset circuit breaker
                    with self._lock:
                        cb = self._circuit_breakers.get(url)
                        if cb:
                            cb.is_open = False
                            cb.failure_count = 0
                    logger.info(f"Failover: endpoint {url} recovered via probe")
                    return True
        except Exception as exc:
            logger.debug(f"Failover: recovery probe failed for {url}: {exc}")
        return False

    async def start_recovery_monitor(self) -> None:
        """Start background task to periodically probe failed endpoints.

        Probes unhealthy endpoints at the configured interval.
        """
        if not self.config.enable_auto_recovery:
            return

        async def _recovery_loop() -> None:
            while True:
                try:
                    await asyncio.sleep(self.config.recovery_check_interval)
                    unhealthy = [url for url, node in self._lb._endpoints.items() if not node.is_healthy]
                    for url in unhealthy:
                        await self.check_recovery(url)
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    logger.error(f"Failover: recovery loop error: {exc}")

        self._recovery_task = asyncio.create_task(_recovery_loop())
        logger.info("Failover: recovery monitor started")

    def stop_recovery_monitor(self) -> None:
        """Stop the background recovery monitor."""
        if self._recovery_task and not self._recovery_task.done():
            self._recovery_task.cancel()
            self._recovery_task = None
            logger.info("Failover: recovery monitor stopped")

    def get_stats(self) -> dict[str, Any]:
        """Get failover manager statistics.

        Returns:
            Dict with circuit breaker states, failure history, and config.
        """
        with self._lock:
            return {
                "config": {
                    "max_failures": self.config.max_failures,
                    "recovery_check_interval": self.config.recovery_check_interval,
                    "enable_auto_recovery": self.config.enable_auto_recovery,
                    "circuit_breaker_threshold": self.config.circuit_breaker_threshold,
                    "circuit_breaker_reset_seconds": self.config.circuit_breaker_reset_seconds,
                },
                "circuit_breakers": {
                    url: {
                        "is_open": cb.is_open,
                        "failure_count": cb.failure_count,
                        "success_count": cb.success_count,
                        "opened_at": cb.opened_at,
                    }
                    for url, cb in self._circuit_breakers.items()
                },
                "recent_failures": self._failure_history[-20:],
                "total_failure_events": len(self._failure_history),
                "load_balancer": self._lb.get_stats(),
            }

    def reset(self) -> None:
        """Reset all failover state."""
        with self._lock:
            self._circuit_breakers.clear()
            self._failure_history.clear()
            for node in self._lb._endpoints.values():
                node.is_healthy = True
                node.failure_count = 0
            logger.info("Failover: all state reset")


# ── Batch Operations ──────────────────────────────────────


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


# ── Request Replay & Debug ──────────────────────────────────


@dataclass
class RequestRecord:
    """A single recorded request for replay.

    Attributes:
        record_id: Unique identifier for this record.
        method: HTTP method ("GET" or "POST").
        path: API endpoint path.
        params: Query parameters.
        data: Request body data.
        response: Captured response data.
        status_code: HTTP status code of the response.
        latency_ms: Request duration in milliseconds.
        timestamp: Unix timestamp when the request was made.
        platform: Platform identifier.
        tags: User-defined tags for filtering.
    """

    record_id: str = ""
    method: str = ""
    path: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)
    response: dict[str, Any] | None = None
    status_code: int = 0
    latency_ms: float = 0.0
    timestamp: float = 0.0
    platform: str = ""
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.record_id:
            self.record_id = str(uuid.uuid4())
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-serializable dictionary."""
        return {
            "record_id": self.record_id,
            "method": self.method,
            "path": self.path,
            "params": self.params,
            "data": self.data,
            "response": self.response,
            "status_code": self.status_code,
            "latency_ms": round(self.latency_ms, 2),
            "timestamp": self.timestamp,
            "platform": self.platform,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RequestRecord:
        """Reconstruct a RequestRecord from a dictionary."""
        return cls(
            record_id=data.get("record_id", ""),
            method=data.get("method", ""),
            path=data.get("path", ""),
            params=data.get("params", {}),
            data=data.get("data", {}),
            response=data.get("response"),
            status_code=data.get("status_code", 0),
            latency_ms=data.get("latency_ms", 0.0),
            timestamp=data.get("timestamp", 0.0),
            platform=data.get("platform", ""),
            tags=data.get("tags", []),
        )


@dataclass
class ReplayConfig:
    """Configuration for request replay behaviour.

    Attributes:
        max_records: Maximum number of records to keep in memory.
        record_responses: Whether to store response data in records.
        auto_record: Whether to automatically record all _request() calls.
        replay_delay_ms: Artificial delay between replayed requests (0 = none).
        match_strategy: How to match replay requests ("exact" or "fuzzy").
    """

    max_records: int = 1000
    record_responses: bool = True
    auto_record: bool = False
    replay_delay_ms: float = 0.0
    match_strategy: str = "exact"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dictionary."""
        return {
            "max_records": self.max_records,
            "record_responses": self.record_responses,
            "auto_record": self.auto_record,
            "replay_delay_ms": self.replay_delay_ms,
            "match_strategy": self.match_strategy,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReplayConfig:
        """Deserialize from a dictionary."""
        return cls(
            max_records=data.get("max_records", 1000),
            record_responses=data.get("record_responses", True),
            auto_record=data.get("auto_record", False),
            replay_delay_ms=data.get("replay_delay_ms", 0.0),
            match_strategy=data.get("match_strategy", "exact"),
        )


class RequestRecorder:
    """Records API requests for later replay and debugging.

    Supports recording, filtering, exporting, and importing request records.
    Thread-safe for concurrent access.
    """

    def __init__(self, config: ReplayConfig | None = None) -> None:
        self.config = config or ReplayConfig()
        self._records: list[RequestRecord] = []
        self._lock = threading.Lock()
        self._stats = {
            "total_recorded": 0,
            "total_exported": 0,
            "total_imported": 0,
        }

    def record(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        response: dict[str, Any] | None = None,
        status_code: int = 0,
        latency_ms: float = 0.0,
        platform: str = "",
        tags: list[str] | None = None,
    ) -> RequestRecord:
        """Record a request."""
        rec = RequestRecord(
            method=method.upper(),
            path=path,
            params=params or {},
            data=data or {},
            response=response if self.config.record_responses else None,
            status_code=status_code,
            latency_ms=latency_ms,
            platform=platform,
            tags=tags or [],
        )

        with self._lock:
            self._records.append(rec)
            if len(self._records) > self.config.max_records:
                self._records = self._records[-self.config.max_records :]
            self._stats["total_recorded"] += 1

        logger.debug(f"Recorded request: {rec.method} {rec.path} [{rec.record_id[:8]}]")
        return rec

    def get_records(self) -> list[RequestRecord]:
        """Get all recorded records (copy)."""
        with self._lock:
            return list(self._records)

    def get_record(self, record_id: str) -> RequestRecord | None:
        """Get a specific record by ID."""
        with self._lock:
            for rec in self._records:
                if rec.record_id == record_id:
                    return rec
        return None

    def filter(
        self,
        method: str | None = None,
        path: str | None = None,
        platform: str | None = None,
        tags: list[str] | None = None,
        since: float | None = None,
    ) -> list[RequestRecord]:
        """Filter records by criteria."""
        with self._lock:
            results = list(self._records)

        if method:
            method_upper = method.upper()
            results = [r for r in results if r.method == method_upper]
        if path:
            results = [r for r in results if path in r.path]
        if platform:
            results = [r for r in results if r.platform == platform]
        if tags:
            tag_set = set(tags)
            results = [r for r in results if tag_set & set(r.tags)]
        if since is not None:
            results = [r for r in results if r.timestamp >= since]

        return results

    def clear(self) -> int:
        """Remove all records. Returns count."""
        with self._lock:
            count = len(self._records)
            self._records.clear()
            return count

    def export_json(self) -> str:
        """Export all records as a JSON string."""
        with self._lock:
            data = [r.to_dict() for r in self._records]
            self._stats["total_exported"] += 1
        return json.dumps(data, ensure_ascii=False, indent=2)

    def import_json(self, json_str: str) -> int:
        """Import records from a JSON string."""
        data = json.loads(json_str)
        records = [RequestRecord.from_dict(d) for d in data]
        with self._lock:
            self._records.extend(records)
            if len(self._records) > self.config.max_records:
                self._records = self._records[-self.config.max_records :]
            self._stats["total_imported"] += len(records)
        logger.debug(f"Imported {len(records)} request records")
        return len(records)

    def export_to_file(self, file_path: str) -> int:
        """Export records to a JSON file."""
        json_str = self.export_json()
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(json_str)
        with self._lock:
            count = len(self._records)
        logger.info(f"Exported {count} records to {file_path}")
        return count

    def import_from_file(self, file_path: str) -> int:
        """Import records from a JSON file."""
        with open(file_path, encoding="utf-8") as f:
            json_str = f.read()
        return self.import_json(json_str)

    def get_stats(self) -> dict[str, Any]:
        """Get recorder statistics."""
        with self._lock:
            return {
                "record_count": len(self._records),
                "max_records": self.config.max_records,
                "config": self.config.to_dict(),
                **self._stats,
            }

    def reset_stats(self) -> None:
        """Reset collected statistics (not records)."""
        self._stats = {
            "total_recorded": 0,
            "total_exported": 0,
            "total_imported": 0,
        }


class RequestReplayer:
    """Replays previously recorded requests."""

    def __init__(
        self,
        recorder: RequestRecorder,
        config: ReplayConfig | None = None,
    ) -> None:
        self._recorder = recorder
        self.config = config or recorder.config
        self._stats = {
            "total_replayed": 0,
            "total_matched": 0,
            "total_mismatched": 0,
            "total_errors": 0,
        }

    async def replay(
        self,
        record: RequestRecord,
        execute_fn: Callable[..., Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        """Replay a single recorded request."""
        if self.config.replay_delay_ms > 0:
            await asyncio.sleep(self.config.replay_delay_ms / 1000.0)

        start = time.time()
        try:
            new_response = await execute_fn(
                method=record.method,
                path=record.path,
                params=dict(record.params),
                data=dict(record.data),
            )
            latency_ms = (time.time() - start) * 1000
            self._stats["total_replayed"] += 1

            return {
                "record_id": record.record_id,
                "success": True,
                "original_response": record.response,
                "new_response": new_response,
                "latency_ms": round(latency_ms, 2),
                "original_latency_ms": round(record.latency_ms, 2),
            }
        except Exception as exc:
            latency_ms = (time.time() - start) * 1000
            self._stats["total_replayed"] += 1
            self._stats["total_errors"] += 1
            return {
                "record_id": record.record_id,
                "success": False,
                "error": str(exc),
                "latency_ms": round(latency_ms, 2),
                "original_latency_ms": round(record.latency_ms, 2),
            }

    async def replay_all(
        self,
        execute_fn: Callable[..., Awaitable[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        """Replay all recorded requests sequentially."""
        records = self._recorder.get_records()
        results: list[dict[str, Any]] = []
        for record in records:
            result = await self.replay(record, execute_fn)
            results.append(result)
        return results

    async def replay_filtered(
        self,
        execute_fn: Callable[..., Awaitable[dict[str, Any]]],
        method: str | None = None,
        path: str | None = None,
        platform: str | None = None,
        tags: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Replay filtered recorded requests."""
        records = self._recorder.filter(
            method=method,
            path=path,
            platform=platform,
            tags=tags,
        )
        results: list[dict[str, Any]] = []
        for record in records:
            result = await self.replay(record, execute_fn)
            results.append(result)
        return results

    async def validate_replay(
        self,
        execute_fn: Callable[..., Awaitable[dict[str, Any]]],
        records: list[RequestRecord] | None = None,
    ) -> dict[str, Any]:
        """Replay requests and validate responses against recordings."""
        if records is None:
            records = self._recorder.get_records()

        matched = 0
        mismatched = 0
        details: list[dict[str, Any]] = []

        for record in records:
            result = await self.replay(record, execute_fn)
            if not result["success"]:
                mismatched += 1
                details.append(
                    {
                        "record_id": record.record_id,
                        "status": "error",
                        "error": result.get("error", ""),
                    }
                )
                continue

            original = record.response or {}
            new = result.get("new_response", {})

            if self._responses_match(original, new):
                matched += 1
                details.append(
                    {
                        "record_id": record.record_id,
                        "status": "matched",
                    }
                )
            else:
                mismatched += 1
                details.append(
                    {
                        "record_id": record.record_id,
                        "status": "mismatched",
                        "original_keys": sorted(original.keys()) if isinstance(original, dict) else [],
                        "new_keys": sorted(new.keys()) if isinstance(new, dict) else [],
                    }
                )

        self._stats["total_matched"] += matched
        self._stats["total_mismatched"] += mismatched

        return {
            "total": len(records),
            "matched": matched,
            "mismatched": mismatched,
            "match_rate": round(matched / len(records), 4) if records else 0.0,
            "details": details,
        }

    @staticmethod
    def _responses_match(original: Any, new: Any) -> bool:
        """Check if two responses have matching structure."""
        if isinstance(original, dict) and isinstance(new, dict):
            return set(original.keys()) == set(new.keys())
        return original == new

    def get_stats(self) -> dict[str, Any]:
        """Get replayer statistics."""
        return dict(self._stats)

    def reset_stats(self) -> None:
        """Reset collected statistics."""
        self._stats = {
            "total_replayed": 0,
            "total_matched": 0,
            "total_mismatched": 0,
            "total_errors": 0,
        }


# ── Request Tracing (Debug) ─────────────────────────────────


@dataclass
class TraceSpan:
    """A single span within a request trace."""

    span_id: str = ""
    trace_id: str = ""
    parent_id: str | None = None
    name: str = ""
    start_time: float = 0.0
    end_time: float = 0.0
    duration_ms: float = 0.0
    status: str = "unset"
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.span_id:
            self.span_id = uuid.uuid4().hex[:16]
        if not self.trace_id:
            self.trace_id = uuid.uuid4().hex[:32]
        if self.start_time == 0.0:
            self.start_time = time.time()

    def set_attribute(self, key: str, value: Any) -> None:
        """Add or update a span attribute."""
        self.attributes[key] = value

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        """Add a timestamped event to the span."""
        self.events.append(
            {
                "name": name,
                "timestamp": time.time(),
                "attributes": attributes or {},
            }
        )

    def finish(self, status: str = "ok") -> None:
        """Mark the span as finished."""
        self.end_time = time.time()
        self.duration_ms = (self.end_time - self.start_time) * 1000
        self.status = status

    @property
    def is_active(self) -> bool:
        """Whether the span is still active (not finished)."""
        return self.end_time == 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-serializable dictionary."""
        return {
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "parent_id": self.parent_id,
            "name": self.name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": round(self.duration_ms, 2),
            "status": self.status,
            "attributes": self.attributes,
            "events": self.events,
        }


class RequestTracer:
    """Traces requests through the system with parent-child span support."""

    def __init__(self, service_name: str = "") -> None:
        self.service_name = service_name
        self._spans: list[TraceSpan] = []
        self._active_spans: dict[str, TraceSpan] = {}
        self._current_trace_id: str = ""
        self._lock = threading.Lock()

    def start_span(
        self,
        name: str,
        parent: TraceSpan | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> TraceSpan:
        """Start a new span."""
        span = TraceSpan(
            name=name,
            parent_id=parent.span_id if parent else None,
            trace_id=parent.trace_id if parent else "",
            attributes=attributes or {},
        )

        with self._lock:
            self._spans.append(span)
            self._active_spans[span.span_id] = span
            if parent is None:
                self._current_trace_id = span.trace_id

        return span

    def finish_span(self, span: TraceSpan, status: str = "ok") -> None:
        """Finish an active span."""
        span.finish(status)
        with self._lock:
            self._active_spans.pop(span.span_id, None)

    def get_spans(self) -> list[TraceSpan]:
        """Get all spans (copy)."""
        with self._lock:
            return list(self._spans)

    def get_active_spans(self) -> list[TraceSpan]:
        """Get currently active (unfinished) spans."""
        with self._lock:
            return list(self._active_spans.values())

    def get_trace_summary(self) -> dict[str, Any]:
        """Get a summary of the current trace."""
        with self._lock:
            spans = list(self._spans)
            active = list(self._active_spans.values())

        if not spans:
            return {
                "trace_id": "",
                "span_count": 0,
                "active_span_count": 0,
                "total_duration_ms": 0.0,
                "root_span": "",
                "status": "unset",
                "service_name": self.service_name,
            }

        trace_id = spans[0].trace_id
        root_spans = [s for s in spans if s.parent_id is None]
        root_name = root_spans[0].name if root_spans else ""

        total_duration = sum(s.duration_ms for s in spans if not s.is_active)
        has_error = any(s.status == "error" for s in spans)
        status = "error" if has_error else "ok"

        return {
            "trace_id": trace_id,
            "span_count": len(spans),
            "active_span_count": len(active),
            "total_duration_ms": round(total_duration, 2),
            "root_span": root_name,
            "status": status,
            "service_name": self.service_name,
        }

    def clear(self) -> None:
        """Remove all spans."""
        with self._lock:
            self._spans.clear()
            self._active_spans.clear()
            self._current_trace_id = ""

    def get_stats(self) -> dict[str, Any]:
        """Get tracer statistics."""
        with self._lock:
            return {
                "service_name": self.service_name,
                "total_spans": len(self._spans),
                "active_spans": len(self._active_spans),
                "current_trace_id": self._current_trace_id,
            }


# ── Debug Logging ───────────────────────────────────────────


class DebugLogLevel(StrEnum):
    """Debug log levels."""

    TRACE = "trace"
    DEBUG = "debug"
    INFO = "info"
    WARN = "warn"
    ERROR = "error"


_DEBUG_LEVEL_ORDER: dict[str, int] = {
    DebugLogLevel.TRACE: 0,
    DebugLogLevel.DEBUG: 1,
    DebugLogLevel.INFO: 2,
    DebugLogLevel.WARN: 3,
    DebugLogLevel.ERROR: 4,
}


@dataclass
class DebugLogEntry:
    """A single debug log entry."""

    entry_id: str = ""
    level: str = DebugLogLevel.DEBUG
    message: str = ""
    timestamp: float = 0.0
    context: dict[str, Any] = field(default_factory=dict)
    trace_id: str = ""
    span_id: str = ""

    def __post_init__(self) -> None:
        if not self.entry_id:
            self.entry_id = uuid.uuid4().hex[:12]
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-serializable dictionary."""
        return {
            "entry_id": self.entry_id,
            "level": self.level,
            "message": self.message,
            "timestamp": self.timestamp,
            "context": self.context,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
        }


class DebugLogger:
    """Structured debug logger for request debugging."""

    def __init__(
        self,
        level: DebugLogLevel | str = DebugLogLevel.DEBUG,
        max_entries: int = 5000,
    ) -> None:
        self._level = level if isinstance(level, str) else level.value
        self._max_entries = max_entries
        self._entries: list[DebugLogEntry] = []
        self._lock = threading.Lock()
        self._stats = {"total_logged": 0, "total_filtered": 0}

    @property
    def level(self) -> str:
        """Current minimum log level."""
        return self._level

    @level.setter
    def level(self, value: str | DebugLogLevel) -> None:
        """Update the minimum log level."""
        self._level = value if isinstance(value, str) else value.value

    def _should_log(self, level: str) -> bool:
        """Check if a message at this level should be captured."""
        return _DEBUG_LEVEL_ORDER.get(level, 0) >= _DEBUG_LEVEL_ORDER.get(self._level, 0)

    def log(
        self,
        level: str | DebugLogLevel,
        message: str,
        context: dict[str, Any] | None = None,
        trace_id: str = "",
        span_id: str = "",
    ) -> DebugLogEntry | None:
        """Log a debug entry."""
        level_str = level if isinstance(level, str) else level.value

        if not self._should_log(level_str):
            with self._lock:
                self._stats["total_filtered"] += 1
            return None

        entry = DebugLogEntry(
            level=level_str,
            message=message,
            context=context or {},
            trace_id=trace_id,
            span_id=span_id,
        )

        with self._lock:
            self._entries.append(entry)
            if len(self._entries) > self._max_entries:
                self._entries = self._entries[-self._max_entries :]
            self._stats["total_logged"] += 1

        return entry

    def get_entries(
        self,
        level: str | None = None,
        trace_id: str | None = None,
        limit: int = 100,
    ) -> list[DebugLogEntry]:
        """Get log entries with optional filtering."""
        with self._lock:
            entries = list(self._entries)

        if level:
            min_order = _DEBUG_LEVEL_ORDER.get(level, 0)
            entries = [e for e in entries if _DEBUG_LEVEL_ORDER.get(e.level, 0) >= min_order]
        if trace_id:
            entries = [e for e in entries if e.trace_id == trace_id]

        return entries[-limit:]

    def export_json(self) -> str:
        """Export all entries as JSON string."""
        with self._lock:
            data = [e.to_dict() for e in self._entries]
        return json.dumps(data, ensure_ascii=False, indent=2)

    def clear(self) -> int:
        """Remove all entries. Returns count."""
        with self._lock:
            count = len(self._entries)
            self._entries.clear()
            return count

    def get_stats(self) -> dict[str, Any]:
        """Get logger statistics."""
        with self._lock:
            return {
                "entry_count": len(self._entries),
                "max_entries": self._max_entries,
                "level": self._level,
                **self._stats,
            }


# ── Debug Breakpoints ───────────────────────────────────────


@dataclass
class DebugBreakpoint:
    """A configurable debug breakpoint for request debugging."""

    breakpoint_id: str = ""
    name: str = ""
    enabled: bool = True
    condition: Callable[..., bool] | None = field(default=None, repr=False)
    hit_count: int = 0
    action: str = "log"
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.breakpoint_id:
            self.breakpoint_id = uuid.uuid4().hex[:12]

    def evaluate(self, **kwargs: Any) -> bool:
        """Evaluate whether this breakpoint should trigger."""
        if not self.enabled:
            return False
        if self.condition is None:
            return True
        try:
            return self.condition(**kwargs)
        except Exception:
            return False

    def hit(self) -> None:
        """Record a breakpoint hit."""
        self.hit_count += 1

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-serializable dictionary (excludes condition callable)."""
        return {
            "breakpoint_id": self.breakpoint_id,
            "name": self.name,
            "enabled": self.enabled,
            "hit_count": self.hit_count,
            "action": self.action,
            "tags": self.tags,
            "has_condition": self.condition is not None,
        }


class DebugBreakpointManager:
    """Manages debug breakpoints for request debugging."""

    def __init__(self) -> None:
        self._breakpoints: dict[str, DebugBreakpoint] = {}
        self._lock = threading.Lock()
        self._stats = {"total_checks": 0, "total_hits": 0}
        self._hit_history: list[dict[str, Any]] = []

    def add_breakpoint(
        self,
        name: str = "",
        action: str = "log",
        condition: Callable[..., bool] | None = None,
        tags: list[str] | None = None,
    ) -> DebugBreakpoint:
        """Add a new breakpoint."""
        bp = DebugBreakpoint(
            name=name,
            action=action,
            condition=condition,
            tags=tags or [],
        )
        with self._lock:
            self._breakpoints[bp.breakpoint_id] = bp
        logger.debug(f"Breakpoint added: {bp.name} [{bp.breakpoint_id}]")
        return bp

    def remove_breakpoint(self, breakpoint_id: str) -> bool:
        """Remove a breakpoint by ID."""
        with self._lock:
            if breakpoint_id in self._breakpoints:
                del self._breakpoints[breakpoint_id]
                return True
        return False

    def enable_breakpoint(self, breakpoint_id: str) -> bool:
        """Enable a breakpoint."""
        with self._lock:
            bp = self._breakpoints.get(breakpoint_id)
            if bp:
                bp.enabled = True
                return True
        return False

    def disable_breakpoint(self, breakpoint_id: str) -> bool:
        """Disable a breakpoint."""
        with self._lock:
            bp = self._breakpoints.get(breakpoint_id)
            if bp:
                bp.enabled = False
                return True
        return False

    def get_breakpoint(self, breakpoint_id: str) -> DebugBreakpoint | None:
        """Get a breakpoint by ID."""
        with self._lock:
            return self._breakpoints.get(breakpoint_id)

    def list_breakpoints(
        self,
        enabled_only: bool = False,
        tags: list[str] | None = None,
    ) -> list[DebugBreakpoint]:
        """List breakpoints with optional filtering."""
        with self._lock:
            bps = list(self._breakpoints.values())
        if enabled_only:
            bps = [bp for bp in bps if bp.enabled]
        if tags:
            tag_set = set(tags)
            bps = [bp for bp in bps if tag_set & set(bp.tags)]
        return bps

    def should_break(self, **kwargs: Any) -> DebugBreakpoint | None:
        """Check if any breakpoint should trigger."""
        with self._lock:
            self._stats["total_checks"] += 1
            bps = [bp for bp in self._breakpoints.values() if bp.enabled]

        for bp in bps:
            if bp.evaluate(**kwargs):
                bp.hit()
                self._record_hit(bp, kwargs)
                with self._lock:
                    self._stats["total_hits"] += 1
                return bp

        return None

    def _record_hit(self, bp: DebugBreakpoint, context: dict[str, Any]) -> None:
        """Record a breakpoint hit in history."""
        self._hit_history.append(
            {
                "breakpoint_id": bp.breakpoint_id,
                "name": bp.name,
                "timestamp": time.time(),
                "context": context,
            }
        )
        if len(self._hit_history) > 1000:
            self._hit_history = self._hit_history[-500:]

    def get_hit_history(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get recent breakpoint hit history."""
        return self._hit_history[-limit:]

    def clear(self) -> None:
        """Remove all breakpoints and clear history."""
        with self._lock:
            self._breakpoints.clear()
            self._hit_history.clear()

    def get_stats(self) -> dict[str, Any]:
        """Get breakpoint manager statistics."""
        with self._lock:
            return {
                "breakpoint_count": len(self._breakpoints),
                "enabled_count": sum(1 for bp in self._breakpoints.values() if bp.enabled),
                **self._stats,
                "hit_history_count": len(self._hit_history),
            }

    def reset_stats(self) -> None:
        """Reset collected statistics."""
        self._stats = {"total_checks": 0, "total_hits": 0}
        self._hit_history.clear()


# ── Alerting ────────────────────────────────────────────────


class AlertSeverity(StrEnum):
    """Severity levels for monitoring alerts.

    Attributes:
        CRITICAL: Immediate action required. Service down or data loss.
        HIGH: Urgent attention needed. Significant degradation.
        MEDIUM: Warning condition. May escalate if unaddressed.
        LOW: Informational. Track but no immediate action.
    """

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


_ALERT_SEVERITY_ORDER: dict[str, int] = {
    AlertSeverity.LOW: 0,
    AlertSeverity.MEDIUM: 1,
    AlertSeverity.HIGH: 2,
    AlertSeverity.CRITICAL: 3,
}


@dataclass
class AlertRule:
    """Defines a monitoring alert rule.

    Attributes:
        rule_id: Unique identifier for the rule.
        name: Human-readable rule name.
        description: What condition triggers this alert.
        metric_path: Dot-separated path to the metric value
            (e.g., "global.error_rate", "global.avg_latency_ms").
        threshold: Numeric threshold that triggers the alert.
        comparison: Comparison operator ("gt", "gte", "lt", "lte", "eq").
        severity: Alert severity level.
        cooldown_seconds: Minimum seconds between consecutive alerts for this rule.
        enabled: Whether the rule is active.
        tags: User-defined tags for filtering and grouping.
        platform: Platform filter (empty = all platforms).
        endpoint: Endpoint filter (empty = all endpoints).
    """

    rule_id: str = ""
    name: str = ""
    description: str = ""
    metric_path: str = ""
    threshold: float = 0.0
    comparison: str = "gt"
    severity: str = AlertSeverity.MEDIUM
    cooldown_seconds: float = 300.0
    enabled: bool = True
    tags: list[str] = field(default_factory=list)
    platform: str = ""
    endpoint: str = ""

    def __post_init__(self) -> None:
        if not self.rule_id:
            self.rule_id = uuid.uuid4().hex[:12]
        if not self.name:
            self.name = f"rule_{self.rule_id}"

    def evaluate(self, value: float) -> bool:
        """Evaluate if the metric value triggers this rule.

        Args:
            value: The current metric value.

        Returns:
            True if the alert should fire.
        """
        if self.comparison == "gt":
            return value > self.threshold
        elif self.comparison == "gte":
            return value >= self.threshold
        elif self.comparison == "lt":
            return value < self.threshold
        elif self.comparison == "lte":
            return value <= self.threshold
        elif self.comparison == "eq":
            return value == self.threshold
        return False

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dictionary."""
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "description": self.description,
            "metric_path": self.metric_path,
            "threshold": self.threshold,
            "comparison": self.comparison,
            "severity": self.severity,
            "cooldown_seconds": self.cooldown_seconds,
            "enabled": self.enabled,
            "tags": self.tags,
            "platform": self.platform,
            "endpoint": self.endpoint,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AlertRule:
        """Deserialize from a dictionary."""
        return cls(
            rule_id=data.get("rule_id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            metric_path=data.get("metric_path", ""),
            threshold=data.get("threshold", 0.0),
            comparison=data.get("comparison", "gt"),
            severity=data.get("severity", AlertSeverity.MEDIUM),
            cooldown_seconds=data.get("cooldown_seconds", 300.0),
            enabled=data.get("enabled", True),
            tags=data.get("tags", []),
            platform=data.get("platform", ""),
            endpoint=data.get("endpoint", ""),
        )


@dataclass
class Alert:
    """Represents a fired alert instance.

    Attributes:
        alert_id: Unique identifier for this alert instance.
        rule_id: ID of the rule that triggered this alert.
        rule_name: Name of the rule for quick reference.
        severity: Alert severity level.
        message: Human-readable alert message.
        metric_value: The metric value that triggered the alert.
        threshold: The threshold that was exceeded.
        metric_path: The metric path that was evaluated.
        platform: Platform where the alert was triggered (if applicable).
        endpoint: Endpoint where the alert was triggered (if applicable).
        fired_at: ISO 8601 timestamp of when the alert fired.
        resolved_at: ISO 8601 timestamp of when the alert was resolved.
        status: Alert status ("firing", "resolved", "silenced").
    """

    alert_id: str = ""
    rule_id: str = ""
    rule_name: str = ""
    severity: str = AlertSeverity.MEDIUM
    message: str = ""
    metric_value: float = 0.0
    threshold: float = 0.0
    metric_path: str = ""
    platform: str = ""
    endpoint: str = ""
    fired_at: str = ""
    resolved_at: str = ""
    status: str = "firing"

    def __post_init__(self) -> None:
        if not self.alert_id:
            self.alert_id = uuid.uuid4().hex[:16]
        if not self.fired_at:
            self.fired_at = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        """Convert alert to a dictionary."""
        return {
            "alert_id": self.alert_id,
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "severity": self.severity,
            "message": self.message,
            "metric_value": round(self.metric_value, 4),
            "threshold": self.threshold,
            "metric_path": self.metric_path,
            "platform": self.platform,
            "endpoint": self.endpoint,
            "fired_at": self.fired_at,
            "resolved_at": self.resolved_at,
            "status": self.status,
        }


class AlertNotifier:
    """Base class for alert notification delivery.

    Supports registering multiple notification channels (callbacks).
    Each callback receives an Alert and returns None.

    Usage::

        notifier = AlertNotifier()
        notifier.add_callback(lambda alert: print(f"ALERT: {alert.message}"))
        await notifier.notify(alert)
    """

    def __init__(self) -> None:
        self._callbacks: list[Callable[..., Any]] = []
        self._lock = threading.Lock()
        self._stats = {
            "total_notifications": 0,
            "total_success": 0,
            "total_failed": 0,
        }

    def add_callback(self, callback: Callable[..., Any]) -> None:
        """Register a notification callback.

        Args:
            callback: Function that receives an Alert instance.
                      Can be sync or async.
        """
        with self._lock:
            self._callbacks.append(callback)

    def remove_callback(self, callback: Callable[..., Any]) -> bool:
        """Remove a registered callback.

        Args:
            callback: The callback to remove.

        Returns:
            True if found and removed.
        """
        with self._lock:
            if callback in self._callbacks:
                self._callbacks.remove(callback)
                return True
        return False

    async def notify(self, alert: Alert) -> dict[str, Any]:
        """Send alert to all registered notification callbacks.

        Args:
            alert: The Alert to deliver.

        Returns:
            Dict with notification results.
        """
        with self._lock:
            callbacks = list(self._callbacks)

        results: list[dict[str, Any]] = []
        for callback in callbacks:
            try:
                result = callback(alert)
                if asyncio.iscoroutine(result) or asyncio.isfuture(result):
                    await result
                self._stats["total_success"] += 1
                results.append({"callback": callback.__name__, "success": True})
            except Exception as exc:
                self._stats["total_failed"] += 1
                results.append({"callback": callback.__name__, "success": False, "error": str(exc)})
                logger.warning(f"Alert notification failed: {exc}")

        self._stats["total_notifications"] += 1
        return {
            "alert_id": alert.alert_id,
            "channels_notified": len(callbacks),
            "results": results,
        }

    def get_stats(self) -> dict[str, Any]:
        """Get notifier statistics."""
        with self._lock:
            return {
                "registered_callbacks": len(self._callbacks),
                **self._stats,
            }

    def reset_stats(self) -> None:
        """Reset notification statistics."""
        self._stats = {
            "total_notifications": 0,
            "total_success": 0,
            "total_failed": 0,
        }


# Default alert rules for common e-commerce monitoring scenarios
DEFAULT_ALERT_RULES: list[AlertRule] = [
    AlertRule(
        name="high_error_rate",
        description="Global error rate exceeds 10%",
        metric_path="global.error_rate",
        threshold=0.1,
        comparison="gt",
        severity=AlertSeverity.HIGH,
        cooldown_seconds=300.0,
    ),
    AlertRule(
        name="critical_error_rate",
        description="Global error rate exceeds 50%",
        metric_path="global.error_rate",
        threshold=0.5,
        comparison="gt",
        severity=AlertSeverity.CRITICAL,
        cooldown_seconds=60.0,
    ),
    AlertRule(
        name="high_latency",
        description="Average latency exceeds 5000ms",
        metric_path="global.avg_latency_ms",
        threshold=5000.0,
        comparison="gt",
        severity=AlertSeverity.MEDIUM,
        cooldown_seconds=600.0,
    ),
    AlertRule(
        name="critical_latency",
        description="Average latency exceeds 30000ms",
        metric_path="global.avg_latency_ms",
        threshold=30000.0,
        comparison="gt",
        severity=AlertSeverity.HIGH,
        cooldown_seconds=120.0,
    ),
]


class AlertManager:
    """Manages alert rules, evaluates metrics, and fires alerts.

    Integrates with MetricsCollector to periodically evaluate metrics
    against configured rules and trigger notifications via AlertNotifier.

    Usage::

        manager = AlertManager()
        manager.add_rule(AlertRule(
            name="high_error_rate",
            metric_path="global.error_rate",
            threshold=0.1,
            comparison="gt",
            severity="high",
        ))
        alerts = manager.evaluate_metrics(metrics_summary)
        for alert in alerts:
            await manager.fire_alert(alert)
    """

    def __init__(
        self,
        notifier: AlertNotifier | None = None,
        include_default_rules: bool = True,
    ) -> None:
        """Initialize the alert manager.

        Args:
            notifier: AlertNotifier for delivering alerts. Creates one if None.
            include_default_rules: Whether to include built-in default rules.
        """
        self._notifier = notifier or AlertNotifier()
        self._rules: dict[str, AlertRule] = {}
        self._firing_alerts: dict[str, Alert] = {}
        self._alert_history: list[Alert] = []
        self._cooldown_tracker: dict[str, float] = {}
        self._lock = threading.Lock()
        self._stats = {
            "total_evaluations": 0,
            "total_alerts_fired": 0,
            "total_alerts_resolved": 0,
        }

        if include_default_rules:
            for rule in DEFAULT_ALERT_RULES:
                self.add_rule(rule)

    @property
    def notifier(self) -> AlertNotifier:
        """Access the alert notifier."""
        return self._notifier

    def add_rule(self, rule: AlertRule) -> None:
        """Add an alert rule.

        Args:
            rule: The AlertRule to add.
        """
        with self._lock:
            self._rules[rule.rule_id] = rule
        logger.debug(f"Alert rule added: {rule.name} [{rule.rule_id}]")

    def remove_rule(self, rule_id: str) -> bool:
        """Remove an alert rule by ID.

        Args:
            rule_id: The rule ID to remove.

        Returns:
            True if found and removed.
        """
        with self._lock:
            if rule_id in self._rules:
                del self._rules[rule_id]
                return True
        return False

    def get_rule(self, rule_id: str) -> AlertRule | None:
        """Get a rule by ID."""
        with self._lock:
            return self._rules.get(rule_id)

    def list_rules(
        self,
        enabled_only: bool = False,
        severity: str | None = None,
        tags: list[str] | None = None,
    ) -> list[AlertRule]:
        """List rules with optional filtering.

        Args:
            enabled_only: Only return enabled rules.
            severity: Filter by severity level.
            tags: Filter by tags (any match).

        Returns:
            List of matching rules.
        """
        with self._lock:
            rules = list(self._rules.values())

        if enabled_only:
            rules = [r for r in rules if r.enabled]
        if severity:
            rules = [r for r in rules if r.severity == severity]
        if tags:
            tag_set = set(tags)
            rules = [r for r in rules if tag_set & set(r.tags)]
        return rules

    @staticmethod
    def _resolve_metric_path(metrics_summary: dict[str, Any], path: str) -> float | None:
        """Resolve a dot-separated metric path to a numeric value.

        Args:
            metrics_summary: The metrics summary dict.
            path: Dot-separated path (e.g., "global.error_rate").

        Returns:
            The numeric value, or None if path is invalid.
        """
        parts = path.split(".")
        current: Any = metrics_summary
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        if isinstance(current, (int, float)):
            return float(current)
        return None

    def evaluate_metrics(
        self,
        metrics_summary: dict[str, Any],
        platform: str = "",
        endpoint: str = "",
    ) -> list[Alert]:
        """Evaluate all rules against the given metrics summary.

        Args:
            metrics_summary: Output of MetricsCollector.get_summary().
            platform: Current platform context for platform-specific rules.
            endpoint: Current endpoint context for endpoint-specific rules.

        Returns:
            List of Alert instances that should be fired.
        """
        now = time.time()
        alerts: list[Alert] = []

        with self._lock:
            rules = [r for r in self._rules.values() if r.enabled]
            self._stats["total_evaluations"] += 1

        for rule in rules:
            # Platform/endpoint filter
            if rule.platform and platform and rule.platform != platform:
                continue
            if rule.endpoint and endpoint and rule.endpoint != endpoint:
                continue

            # Resolve metric value
            value = self._resolve_metric_path(metrics_summary, rule.metric_path)
            if value is None:
                continue

            # Evaluate the rule
            if not rule.evaluate(value):
                continue

            # Check cooldown
            with self._lock:
                last_fired = self._cooldown_tracker.get(rule.rule_id, 0.0)
                if (now - last_fired) < rule.cooldown_seconds:
                    continue
                self._cooldown_tracker[rule.rule_id] = now

            # Create alert
            alert = Alert(
                rule_id=rule.rule_id,
                rule_name=rule.name,
                severity=rule.severity,
                message=(
                    f"[{rule.severity.upper()}] {rule.description}: "
                    f"{rule.metric_path}={value:.4f} (threshold={rule.threshold})"
                ),
                metric_value=value,
                threshold=rule.threshold,
                metric_path=rule.metric_path,
                platform=platform,
                endpoint=endpoint,
            )
            alerts.append(alert)

        return alerts

    async def fire_alert(self, alert: Alert) -> dict[str, Any]:
        """Fire an alert and deliver notifications.

        Args:
            alert: The Alert to fire.

        Returns:
            Notification delivery result.
        """
        with self._lock:
            self._firing_alerts[alert.alert_id] = alert
            self._alert_history.append(alert)
            # Keep history bounded
            if len(self._alert_history) > 1000:
                self._alert_history = self._alert_history[-500:]
            self._stats["total_alerts_fired"] += 1

        logger.warning(f"Alert fired: {alert.message}")
        return await self._notifier.notify(alert)

    def resolve_alert(self, alert_id: str) -> bool:
        """Mark a firing alert as resolved.

        Args:
            alert_id: ID of the alert to resolve.

        Returns:
            True if found and resolved.
        """
        with self._lock:
            alert = self._firing_alerts.pop(alert_id, None)
            if alert:
                alert.status = "resolved"
                alert.resolved_at = datetime.now(UTC).isoformat()
                self._stats["total_alerts_resolved"] += 1
                logger.info(f"Alert resolved: {alert.rule_name} [{alert.alert_id}]")
                return True
        return False

    def silence_rule(self, rule_id: str, duration_seconds: float = 3600.0) -> bool:
        """Silence a rule by setting its cooldown to a long duration.

        Args:
            rule_id: ID of the rule to silence.
            duration_seconds: How long to silence (updates cooldown_seconds).

        Returns:
            True if found and silenced.
        """
        with self._lock:
            rule = self._rules.get(rule_id)
            if rule:
                rule.cooldown_seconds = duration_seconds
                logger.info(f"Alert rule silenced: {rule.name} for {duration_seconds}s")
                return True
        return False

    def get_firing_alerts(self, severity: str | None = None) -> list[Alert]:
        """Get currently firing alerts.

        Args:
            severity: Filter by severity level.

        Returns:
            List of firing Alert instances.
        """
        with self._lock:
            alerts = list(self._firing_alerts.values())
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        return alerts

    def get_alert_history(
        self,
        severity: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get alert history.

        Args:
            severity: Filter by severity level.
            limit: Maximum entries to return.

        Returns:
            List of alert dicts.
        """
        with self._lock:
            history = list(self._alert_history)
        if severity:
            history = [a for a in history if a.severity == severity]
        return [a.to_dict() for a in history[-limit:]]

    def get_stats(self) -> dict[str, Any]:
        """Get alert manager statistics.

        Returns:
            Dict with rule counts, firing alerts, and evaluation stats.
        """
        with self._lock:
            return {
                "rule_count": len(self._rules),
                "enabled_rules": sum(1 for r in self._rules.values() if r.enabled),
                "firing_alerts": len(self._firing_alerts),
                "alert_history_count": len(self._alert_history),
                "notifier_stats": self._notifier.get_stats(),
                **self._stats,
            }

    def export_rules(self) -> list[dict[str, Any]]:
        """Export all rules as a list of dictionaries.

        Returns:
            List of rule dicts suitable for JSON serialization.
        """
        with self._lock:
            return [r.to_dict() for r in self._rules.values()]

    def import_rules(self, rules_data: list[dict[str, Any]]) -> int:
        """Import rules from a list of dictionaries.

        Args:
            rules_data: List of rule dicts (from export_rules or JSON).

        Returns:
            Number of rules imported.
        """
        count = 0
        for data in rules_data:
            rule = AlertRule.from_dict(data)
            self.add_rule(rule)
            count += 1
        logger.info(f"Imported {count} alert rules")
        return count

    def reset(self) -> None:
        """Reset all alert manager state."""
        with self._lock:
            self._firing_alerts.clear()
            self._alert_history.clear()
            self._cooldown_tracker.clear()
            self._stats = {
                "total_evaluations": 0,
                "total_alerts_fired": 0,
                "total_alerts_resolved": 0,
            }
            self._notifier.reset_stats()
        logger.info("Alert manager reset")


# ── Cross-platform MCP tool registration ──────────────────────


def register_common_tools(mcp: Any, client: Any) -> None:
    """Register cross-platform observability/data tools on a FastMCP server.

    Every platform server gets the same operational tools without duplicating
    them. ``client`` may be a :class:`CommerceMCPBase` instance or a zero-arg
    callable returning one (for servers that build their client lazily).

    Registered tools: ``get_metrics``, ``get_traces``, ``get_alerts``,
    ``export_data``. Uses duck-typed ``mcp.tool()`` so this module stays free
    of any MCP framework import.

    Args:
        mcp: A FastMCP instance exposing a ``tool()`` decorator.
        client: A ``CommerceMCPBase`` instance or a callable returning one.
    """

    def _resolve() -> Any:
        return client() if callable(client) else client

    @mcp.tool()
    async def get_metrics() -> str:
        """Return request metrics (per-endpoint latency, success/error counts)."""
        return json.dumps(_resolve().get_metrics_summary(), ensure_ascii=False)

    @mcp.tool()
    async def get_traces() -> str:
        """Return a summary of recent request traces (spans, durations, status)."""
        return json.dumps(_resolve().get_trace_summary(), ensure_ascii=False)

    @mcp.tool()
    async def get_alerts() -> str:
        """Evaluate alert rules against current metrics; return firing alerts."""
        return json.dumps(_resolve().get_alerts(), ensure_ascii=False)

    @mcp.tool()
    async def export_data(records_json: str, fmt: str = "json") -> str:
        """Export a JSON array of records to a CSV or JSON string."""
        records = json.loads(records_json)
        return _resolve().export_data(records, fmt=fmt)
