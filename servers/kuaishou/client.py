"""Explicit platform transport; importing this module does not load credentials."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from servers.kuaishou.schema import READ_METHODS, validate_params, validate_response
from shared.cn_commerce_base import (
    DEFAULT_RETRY,
    CommerceMCPBase,
    ConfigValidationError,
    SignMethod,
    canonicalize_sign_value,
)


class KuaishouMCP(CommerceMCPBase):
    """Merchant GET protocol with a separate OAuth secret and signing secret."""

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

        raw = (
            "&".join(
                key + "=" + canonicalize_sign_value(value) for key, value in sorted(params.items()) if key != "sign"
            )
            + "&signSecret="
            + self.sign_secret
        )
        algorithm = params.get("signMethod", "MD5")
        if algorithm == "MD5":
            return hashlib.md5(raw.encode("utf-8")).hexdigest()
        if algorithm == "HMAC_SHA256":
            return base64.b64encode(
                hmac.new(self.sign_secret.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).digest()
            ).decode("ascii")
        raise ValueError("Kuaishou signMethod must be MD5 or HMAC_SHA256")

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
        if path not in READ_METHODS:
            # Other historical CLI methods remain outside this verified contract.
            return await self._request("GET", path, params=params, retry_config=DEFAULT_RETRY)
        business = params or {}
        validate_params(path, business)
        if self.validate_input:
            self._validate_params(business)
        encoded = json.dumps(business, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)

        def prepare():
            query = {
                "appkey": self.app_key,
                "access_token": self.access_token,
                "method": path,
                "version": "1",
                "timestamp": str(int(time.time() * 1000)),
                "signMethod": "MD5",
                "param": encoded,
            }
            query["sign"] = self._sign(query)
            return {"params": query}

        return await self._send_request(
            "GET",
            self.BASE_URL + "/" + path.replace(".", "/"),
            endpoint=path,
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
            retry_config=DEFAULT_RETRY,
            prepare_request=prepare,
            parse_response=lambda value: validate_response(path, value),
        )
