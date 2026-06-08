"""Shared base for Chinese e-commerce platform MCP servers.

Provides unified auth signing, request handling, and error normalization.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
import urllib.parse
from typing import Any

import httpx

# Configure logging
logger = logging.getLogger("mcp-cn-commerce")


class SignMethod:
    MD5 = "md5"
    HMAC_SHA256 = "hmac_sha256"
    HMAC_MD5 = "hmac_md5"


class ConfigValidationError(Exception):
    """Raised when required configuration is missing."""

    def __init__(self, platform: str, missing_vars: list[str]):
        self.platform = platform
        self.missing_vars = missing_vars
        msg = f"[{platform}] Missing required environment variables: {', '.join(missing_vars)}"
        super().__init__(msg)


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

    def __init__(self, app_key: str = "", app_secret: str = "", access_token: str = ""):
        self.app_key = app_key
        self.app_secret = app_secret
        self.access_token = access_token

    @classmethod
    def from_env(cls, platform: str, required_vars: list[str]) -> "CommerceMCPBase":
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

    async def _request(self, method: str, path: str, params: dict | None = None, data: dict | None = None) -> dict[str, Any]:
        """Make a signed API request."""
        params = params or {}
        data = data or {}

        # Inject auth params
        params["app_key"] = self.app_key
        params["timestamp"] = str(int(time.time() * 1000))
        if self.access_token:
            params["access_token"] = self.access_token

        # Sign
        params["sign"] = self._sign(params)
        params["sign_method"] = self.sign_method

        url = f"{self.BASE_URL}{path}"
        logger.debug(f"Request: {method} {url}")

        async with httpx.AsyncClient(timeout=30) as client:
            if method == "GET":
                resp = await client.get(url, params={**params, **data})
            else:
                resp = await client.post(url, params=params, json=data)

        result = resp.json()
        if "error_response" in result:
            error_code = result["error_response"].get("code", -1)
            error_msg = result["error_response"].get("msg", "unknown")
            logger.warning(f"API error: [{error_code}] {error_msg}")
            raise CommerceAPIError(code=error_code, msg=error_msg)

        logger.debug(f"Response: {resp.status_code}")
        return result

    # ── Signing ───────────────────────────────────────────

    def _sign(self, params: dict) -> str:
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

    async def _paginate(self, fetch_fn, page_key: str = "page", page_size: int = 50, max_pages: int = 50) -> list[dict]:
        """Generic pagination helper."""
        results = []
        for page in range(1, max_pages + 1):
            data = await fetch_fn(page=page, page_size=page_size)
            items = data.get("result", data.get("list", []))
            results.extend(items)
            logger.debug(f"Pagination: page {page}, got {len(items)} items")
            if len(items) < page_size:
                break
        logger.info(f"Pagination complete: {len(results)} total items")
        return results


class CommerceAPIError(Exception):
    """Normalized API error across all platforms."""

    def __init__(self, code: int, msg: str):
        self.code = code
        self.msg = msg
        super().__init__(f"[{code}] {msg}")
