"""Explicit platform transport; importing this module does not load credentials."""

from __future__ import annotations

import hashlib
import hmac

from shared.cn_commerce_base import (
    DEFAULT_RETRY,
    CommerceMCPBase,
    ConfigValidationError,
    SignMethod,
    canonicalize_sign_value,
)


class JDMCP(CommerceMCPBase):
    """JD-specific client that overrides signing for HMAC-MD5."""

    PLATFORM = "JD"
    BASE_URL = "https://api.jd.com/routerjson"
    sign_method = SignMethod.HMAC_MD5

    def _sign(self, params: dict) -> str:
        """JD HMAC-MD5 signing.

        Builds: app_secret + sorted_kv_string + app_secret
        Then HMAC-MD5 with app_secret as key.
        """
        to_sign = {k: v for k, v in params.items() if k not in ("sign", "sign_method") and v != ""}
        sorted_keys = sorted(to_sign.keys())
        raw = (
            self.app_secret
            + "".join(f"{k}{canonicalize_sign_value(to_sign[k])}" for k in sorted_keys)
            + self.app_secret
        )
        return hmac.new(self.app_secret.encode(), raw.encode(), hashlib.md5).hexdigest().upper()

    async def _call(self, api_method: str, biz_params: dict | None = None) -> dict:
        """Make a JD API call.

        system params (method, format, v, plus auth) go in query string;
        business params go in JSON body.
        """
        missing = [
            name
            for name, value in (
                ("JD_APP_KEY", self.app_key),
                ("JD_APP_SECRET", self.app_secret),
                ("JD_ACCESS_TOKEN", self.access_token),
            )
            if not value
        ]
        if missing:
            raise ConfigValidationError("JD", missing)
        params = {
            "method": api_method,
            "format": "json",
            "v": "2.0",
        }
        return await self._request("POST", "", params=params, data=biz_params or {}, retry_config=DEFAULT_RETRY)
