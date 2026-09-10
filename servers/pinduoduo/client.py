"""Explicit platform transport; importing this module does not load credentials."""

from __future__ import annotations

import time

from shared.cn_commerce_base import (
    DEFAULT_RETRY,
    CommerceAPIError,
    CommerceMCPBase,
    ConfigValidationError,
    SignMethod,
    canonicalize_sign_value,
)


class PinduoduoMCP(CommerceMCPBase):
    """Pinduoduo-specific client.

    PDD uses 'type' param for the API method name, 'client_id' for app key,
    and sends all params as POST form data to a single router endpoint.
    Signing is standard MD5 (provided by the base class).
    """

    PLATFORM = "PINDUODUO"
    BASE_URL = "https://gw-api.pinduoduo.com/api/router"
    sign_method = SignMethod.MD5

    async def _call(self, api_type: str, biz_params: dict | None = None) -> dict:
        """Make a PDD API call.

        Builds system params (type, client_id, timestamp, data_type,
        access_token), merges business params, signs with MD5, and POSTs
        as form data.
        """
        missing = [
            name
            for name, value in (
                ("PINDUODUO_CLIENT_ID", self.app_key),
                ("PINDUODUO_CLIENT_SECRET", self.app_secret),
                ("PINDUODUO_ACCESS_TOKEN", self.access_token),
            )
            if not value
        ]
        if missing:
            raise ConfigValidationError("PINDUODUO", missing)
        if self.validate_input:
            self._validate_params(biz_params or {})
        params: dict[str, str] = {
            "type": api_type,
            "client_id": self.app_key,
            "timestamp": str(int(time.time() * 1000)),
            "data_type": "JSON",
        }
        if self.access_token:
            params["access_token"] = self.access_token

        # Merge business params (convert all values to strings)
        if biz_params:
            for k, v in biz_params.items():
                params[k] = canonicalize_sign_value(v)

        def prepare_request():
            signed = dict(params)
            signed["timestamp"] = str(int(time.time() * 1000))
            signed["sign"] = self._sign(signed)
            return {"data": signed}

        def parse_response(result):
            if "error_response" in result:
                error = result["error_response"]
                raise CommerceAPIError(
                    code=error.get("error_code", error.get("code", -1)),
                    msg=error.get("error_msg", error.get("msg", "unknown")),
                )
            return result

        return await self._send_request(
            "POST",
            self.BASE_URL,
            endpoint=api_type,
            prepare_request=prepare_request,
            retry_config=DEFAULT_RETRY,
            parse_response=parse_response,
        )
