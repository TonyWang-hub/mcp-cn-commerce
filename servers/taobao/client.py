"""Explicit platform transport; importing this module does not load credentials."""

from __future__ import annotations

import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo

from servers.taobao.schema import validate_params, validate_response
from shared.cn_commerce_base import (
    DEFAULT_RETRY,
    CommerceAPIError,
    CommerceMCPBase,
    ConfigValidationError,
    SignMethod,
    canonicalize_sign_value,
)


class TaobaoMCP(CommerceMCPBase):
    """Taobao Open Platform (TOP) client.

    Signs with MD5 (not HMAC-MD5). All parameters (system + business) go
    together as query-string params in a POST to the single router endpoint.
    """

    PLATFORM = "TAOBAO"
    BASE_URL = "https://eco.taobao.com/router/rest"
    sign_method = SignMethod.MD5

    async def _call(self, api_method: str, biz_params: dict | None = None) -> dict:
        """Make a Taobao API call.

        Merges system params (method, format, v) with business params and
        sends everything through _request as query-string parameters.

        Returns the API response dict, or an error_response dict on failure.
        """
        missing = [
            name
            for name, value in (
                ("TAOBAO_APP_KEY", self.app_key),
                ("TAOBAO_APP_SECRET", self.app_secret),
                ("TAOBAO_ACCESS_TOKEN", self.access_token),
            )
            if not value
        ]
        if missing:
            raise ConfigValidationError("TAOBAO", missing)
        validate_params(api_method, biz_params or {})
        params = {"method": api_method, "format": "json", "v": "2.0", **(biz_params or {})}
        return await self._request("POST", "", params=params, retry_config=DEFAULT_RETRY)

    def _sign(self, params: dict) -> str:
        """TOP signs all nonempty fields except sign, including sign_method."""
        raw = (
            self.app_secret
            + "".join(
                key + canonicalize_sign_value(value)
                for key, value in sorted(params.items())
                if key != "sign" and value != ""
            )
            + self.app_secret
        )
        return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()

    async def _request(self, method, path, params=None, data=None, retry_config=None):
        """TOP uses seller session and GMT+8 timestamps, not generic auth."""
        business = {**(params or {}), **(data or {})}
        if self.validate_input:
            self._validate_params(business)

        def prepare():
            signed = {key: canonicalize_sign_value(value) for key, value in business.items()}
            signed.update(
                app_key=self.app_key,
                session=self.access_token,
                timestamp=datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S"),
                sign_method="md5",
            )
            signed["sign"] = self._sign(signed)
            return {"params": signed}

        def parse(payload):
            if not isinstance(payload, dict):
                raise ValueError("Expected a JSON object from TOP")
            if "error_response" in payload:
                error = payload["error_response"]
                raise CommerceAPIError(error.get("code", -1), error.get("msg", "unknown"))
            validate_response(business.get("method", ""), business, payload)
            return payload

        return await self._send_request(
            method,
            self.BASE_URL + path,
            endpoint=business.get("method", path),
            prepare_request=prepare,
            parse_response=parse,
            retry_config=retry_config,
        )
