"""Explicit JOS client; imports never read credentials from the environment."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from servers.jd.schema import READ_METHODS, validate_params, validate_response
from shared.cn_commerce_base import (
    DEFAULT_RETRY,
    CommerceMCPBase,
    ConfigValidationError,
    SignMethod,
    canonicalize_sign_value,
)


class JDMCP(CommerceMCPBase):
    """JOS form protocol with MD5 signatures and a fixed authorization snapshot."""

    PLATFORM = "JD"
    BASE_URL = "https://api.jd.com/routerjson"
    sign_method = SignMethod.MD5

    def _sign(self, params: dict) -> str:
        """Sign decoded values before form encoding; only sign itself is excluded."""
        raw = (
            self.app_secret
            + "".join(key + canonicalize_sign_value(value) for key, value in sorted(params.items()) if key != "sign")
            + self.app_secret
        )
        return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()

    async def _call(self, api_method: str, biz_params: dict | None = None) -> dict:
        """Send flat business JSON inside 360buy_param_json, as the JOS SDK does."""
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
        business = biz_params or {}
        validate_params(api_method, business)
        if self.validate_input:
            self._validate_params(business)
        encoded = json.dumps(business, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)

        def prepare():
            form = {
                "method": api_method,
                "app_key": self.app_key,
                "access_token": self.access_token,
                "timestamp": datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S"),
                "v": "2.0",
                "360buy_param_json": encoded,
            }
            form["sign"] = self._sign(form)
            return {"data": form}

        return await self._send_request(
            "POST",
            self.BASE_URL,
            endpoint=api_method,
            prepare_request=prepare,
            parse_response=lambda value: validate_response(api_method, value),
            retry_config=DEFAULT_RETRY if api_method in READ_METHODS else None,
        )
