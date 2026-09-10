"""Explicit platform transport; importing this module does not load credentials."""

from __future__ import annotations

import hashlib
from typing import Any

from shared.cn_commerce_base import (
    DEFAULT_RETRY,
    CommerceMCPBase,
    ConfigValidationError,
    SignMethod,
    canonicalize_sign_value,
)


class KuaishouMCP(CommerceMCPBase):
    """Kuaishou-specific client.

    Kuaishou uses a separate `sign_secret` for request signing (distinct from
    `app_secret`).  The base class MD5 signing is overridden to use
    `sign_secret` in the canonical format:
        sign_secret + sorted(k+v) + sign_secret  →  MD5  →  uppercase.

    API calls are made via GET to individual REST paths under BASE_URL.
    """

    PLATFORM = "KUAISHOU"
    BASE_URL = "https://openapi.kwaixiaodian.com"
    sign_method = SignMethod.MD5

    def __init__(
        self,
        app_key: str = "",
        app_secret: str = "",
        sign_secret: str = "",
        access_token: str = "",
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
        self.sign_secret = sign_secret

    # ── Override signing to use sign_secret ───────────────────────────────

    def _sign(self, params: dict) -> str:
        """Generate MD5 signature using sign_secret."""

        to_sign = {k: v for k, v in params.items() if k not in ("sign", "sign_method") and v != ""}
        sorted_keys = sorted(to_sign.keys())
        raw = (
            self.sign_secret
            + "".join(f"{k}{canonicalize_sign_value(to_sign[k])}" for k in sorted_keys)
            + self.sign_secret
        )
        return hashlib.md5(raw.encode()).hexdigest().upper()

    # ── Convenience wrapper ───────────────────────────────────────────────

    async def _call(self, path: str, params: dict | None = None) -> dict[str, Any]:
        """Make a signed GET request to a Kuaishou API path."""
        missing = [
            f"KUAISHOU_{name.upper()}"
            for name in ("app_key", "app_secret", "sign_secret", "access_token")
            if not getattr(self, name)
        ]
        if missing:
            raise ConfigValidationError("KUAISHOU", missing)
        return await self._request("GET", path, params=params, retry_config=DEFAULT_RETRY)
