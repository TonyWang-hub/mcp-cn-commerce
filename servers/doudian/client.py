"""Explicit platform transport; importing this module does not load credentials."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

from shared.cn_commerce_base import (
    DEFAULT_RETRY,
    CommerceAPIError,
    CommerceMCPBase,
    ConfigValidationError,
)


class DouDianAPIError(CommerceAPIError):
    """Normalized API error for Douyin shop.

    Subclasses the shared :class:`CommerceAPIError` so the base class's
    error handling (and ``handle_tool_errors``) recognises it, while still
    carrying Doudian's ``sub_code``/``sub_msg`` detail.
    """

    def __init__(self, code: int, msg: str, sub_code: str = "", sub_msg: str = ""):
        self.sub_code = sub_code
        self.sub_msg = sub_msg
        super().__init__(code=code, msg=msg)
        # Enrich the rendered message with sub-error detail when present.
        if sub_code:
            self.args = (f"[{code}] {msg} (sub: [{sub_code}] {sub_msg})",)


class ConfigError(ConfigValidationError):
    """Missing required configuration.

    Kept as a thin alias over the shared :class:`ConfigValidationError` so
    existing callers/tests that expect a plain message string continue to work.
    """

    def __init__(self, message: str):  # pylint: disable=super-init-not-called
        # The parent's __init__(platform, missing_vars) signature is intentionally
        # bypassed: ConfigError is a message-based alias for backward compatibility.
        Exception.__init__(self, message)  # pylint: disable=non-parent-init-called
        self.platform = "DOUDIAN"
        self.missing_vars = []


class DouDianClient(CommerceMCPBase):
    """Doudian HMAC-SHA256 adapter using the official API calling guide.

    Protocol source: https://op.jinritemai.com/docs/guide-docs/10/23
    Business JSON is recursively sorted and signed in its exact wire form.
    """

    PLATFORM = "DOUDIAN"
    BASE_URL = "https://openapi-fxg.jinritemai.com/"
    sign_method = "hmac-sha256"

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        access_token: str,
        shop_id: str = "",
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
        self.shop_id = shop_id

    # ── Signing ─────────────────────────────────────────

    @staticmethod
    def _serialize_business(params: dict[str, Any]) -> str:
        # Official examples require integral floats as integers and preserve
        # native nested values, Unicode and HTML punctuation.
        def normalize(value):
            if isinstance(value, dict):
                return {k: normalize(v) for k, v in value.items()}
            if isinstance(value, (list, tuple)):
                return [normalize(v) for v in value]
            if isinstance(value, float) and value.is_integer():
                return int(value)
            return value

        return json.dumps(normalize(params), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)

    def _sign(self, params: dict[str, Any]) -> str:
        """Sign app_key, method, param_json, timestamp and v in that order."""
        raw = (
            self.app_secret
            + "".join(f"{key}{params[key]}" for key in ("app_key", "method", "param_json", "timestamp", "v"))
            + self.app_secret
        )
        return hmac.new(self.app_secret.encode(), raw.encode(), hashlib.sha256).hexdigest()

    # ── Request ─────────────────────────────────────────

    async def request(
        self,
        method: str,
        params: dict | None = None,
    ) -> dict[str, Any]:
        """POST canonical business JSON with OAuth and signed public query fields."""
        missing = [
            name
            for name, value in (
                ("DOUDIAN_APP_KEY", self.app_key),
                ("DOUDIAN_APP_SECRET", self.app_secret),
                ("DOUDIAN_ACCESS_TOKEN", self.access_token),
                ("DOUDIAN_SHOP_ID", self.shop_id),
            )
            if not value
        ]
        if missing:
            raise ConfigError(f"Missing required environment variables: {', '.join(missing)}")
        params = params or {}
        if self.validate_input:
            self._validate_params(params)
        param_json = self._serialize_business(params)
        api_method = method.strip("/").replace("/", ".")

        def prepare_request():
            common = {
                "app_key": self.app_key,
                "method": api_method,
                "timestamp": str(int(time.time())),
                "v": "2",
                "sign_method": self.sign_method,
                "access_token": self.access_token,
            }
            common["sign"] = self._sign({**common, "param_json": param_json})
            return {
                "params": common,
                "content": param_json.encode("utf-8"),
                "headers": {"Content-Type": "application/json"},
            }

        def parse_response(result):
            error_code = result.get("code", 10000)
            if str(error_code) != "10000":
                raise DouDianAPIError(
                    code=error_code,
                    msg=result.get("msg", "unknown error"),
                    sub_code=str(result.get("sub_code", "")),
                    sub_msg=result.get("sub_msg", ""),
                )
            return result.get("data", result)

        return await self._send_request(
            "POST",
            f"{self.BASE_URL.rstrip('/')}/{method.lstrip('/')}",
            endpoint=method,
            prepare_request=prepare_request,
            retry_config=DEFAULT_RETRY,
            parse_response=parse_response,
        )
