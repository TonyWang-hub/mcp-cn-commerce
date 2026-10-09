"""Explicit platform transport; importing this module does not load credentials."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from shared.cn_commerce_base import (
    DEFAULT_RETRY,
    CommerceAPIError,
    CommerceMCPBase,
    ConfigValidationError,
    RetryConfig,
)

STATIC_MODE = "static"
MANAGED_MODE = "managed"


class WeixinStoreMCP(CommerceMCPBase):
    """WeChat Store (微信小店) client.

    WeChat Store uses OAuth 2.0 with an access_token that is passed as a
    query-string parameter on every request.  No per-request signing is needed.

    If WX_ACCESS_TOKEN is set in the environment, it is used directly.
    Otherwise, WX_APP_ID + WX_APP_SECRET are used to fetch a new token via
    GET /cgi-bin/token, which is cached in-memory (valid for ~2 hours).
    """

    PLATFORM = "WEIXIN_STORE"
    BASE_URL = "https://api.weixin.qq.com"
    sign_method = ""  # No signing for WeChat Store

    def __init__(
        self,
        app_key: str = "",
        app_secret: str = "",
        access_token: str = "",
        token_mode: str | None = None,
        *,
        http_client=None,
        rate_limiter=None,
    ):
        super().__init__(
            app_key=app_key,
            app_secret=app_secret,
            access_token=access_token,
            http_client=http_client,
            rate_limiter=rate_limiter,
        )
        self.token_mode = token_mode or ("static" if access_token else "managed")
        if self.token_mode not in {"static", "managed"}:
            raise ValueError("WX_TOKEN_MODE must be static or managed")
        self._access_token = access_token if self.token_mode == STATIC_MODE else ""
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()

    @staticmethod
    def _parse_response(payload: dict) -> dict:
        if str(payload.get("errcode", 0)) != "0":
            raise CommerceAPIError(code=payload["errcode"], msg=payload.get("errmsg", "unknown"))
        return payload

    async def _ensure_token(self) -> str:
        """Use an explicit token unchanged or serialize managed token refreshes."""
        if self.token_mode == STATIC_MODE:
            if not self._access_token:
                raise ConfigValidationError("WX", ["WX_ACCESS_TOKEN"])
            return self._access_token
        missing = [
            name for name, value in (("WX_APP_ID", self.app_key), ("WX_APP_SECRET", self.app_secret)) if not value
        ]
        if missing:
            raise ConfigValidationError("WX", missing)
        async with self._token_lock:
            if self._access_token and time.monotonic() < self._token_expires_at:
                return self._access_token
            payload = await self._send_request(
                "GET",
                f"{self.BASE_URL}/cgi-bin/token",
                endpoint="/cgi-bin/token",
                params={"grant_type": "client_credential", "appid": self.app_key, "secret": self.app_secret},
                parse_response=self._parse_response,
            )
            if not payload.get("access_token"):
                raise CommerceAPIError(code=-1, msg="Token response is missing access_token")
            lifetime = float(payload.get("expires_in", 7200))
            if lifetime <= 0:
                raise CommerceAPIError(code=-1, msg="Token response has invalid expires_in")
            self._access_token = payload["access_token"]
            self._token_expires_at = time.monotonic() + lifetime - min(300.0, lifetime * 0.1)
            return self._access_token

    async def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        data: dict | None = None,
        retry_config: RetryConfig | None = DEFAULT_RETRY,
    ) -> dict[str, Any]:
        """Use the shared pool, limits and metrics for read-only store APIs."""
        if self.validate_input:
            self._validate_params(data or params or {})
        token = await self._ensure_token()
        query = dict(params or {})
        query["access_token"] = token
        try:
            return await self._send_request(
                method,
                f"{self.BASE_URL}{path}",
                endpoint=path,
                params=query,
                json_body=(data or {}) if method.upper() != "GET" else None,
                retry_config=retry_config,
                parse_response=self._parse_response,
            )
        except CommerceAPIError as exc:
            # Only managed tokens can be refreshed automatically. Retry once.
            if self.token_mode != MANAGED_MODE or str(exc.code) not in {"40001", "40014", "42001"}:
                raise
            async with self._token_lock:
                if self._access_token == token:
                    self._token_expires_at = 0.0
            query["access_token"] = await self._ensure_token()
            return await self._send_request(
                method,
                f"{self.BASE_URL}{path}",
                endpoint=path,
                params=query,
                json_body=(data or {}) if method.upper() != "GET" else None,
                retry_config=retry_config,
                parse_response=self._parse_response,
            )
