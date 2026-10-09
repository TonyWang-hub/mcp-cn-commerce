"""Explicit platform transport; importing this module does not load credentials."""

from __future__ import annotations

from shared.cn_commerce_base import (
    DEFAULT_RETRY,
    CommerceAPIError,
    CommerceMCPBase,
    ConfigValidationError,
    RetryConfig,
    canonicalize_sign_value,
)


class OceanEngine(CommerceMCPBase):
    """Ocean Engine API client authenticated by the Access-Token header."""

    PLATFORM = "OCEANENGINE"
    BASE_URL: str = "https://api.oceanengine.com/open_api/"
    sign_method: str = ""
    _ADVERTISER_READ_PATHS = frozenset({"2/advertiser/info/", "2/advertiser/fund/get/"})

    async def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        data: dict | None = None,
        retry_config: RetryConfig | None = DEFAULT_RETRY,
    ) -> dict:
        if not self.access_token:
            raise ConfigValidationError("OCEANENGINE", ["OCEANENGINE_ACCESS_TOKEN"])
        if self.validate_input:
            self._validate_params(params or {})
            self._validate_params(data or {})
        # The official SDK JSON-encodes array/object query values once.
        values = {**(params or {}), **(data or {})} if method.upper() == "GET" else (params or {})
        query = {k: canonicalize_sign_value(v) for k, v in values.items() if v is not None}

        def parse_response(payload):
            if str(payload.get("code", 0)) != "0":
                raise CommerceAPIError(code=payload["code"], msg=payload.get("message", "unknown"))
            return payload

        # Current official advertiser/fund docs use the advertising gateway.
        base_url = (
            "https://ad.oceanengine.com/open_api/" if path.lstrip("/") in self._ADVERTISER_READ_PATHS else self.BASE_URL
        )
        return await self._send_request(
            method,
            base_url + path.lstrip("/"),
            endpoint=path,
            params=query,
            json_body=data if method.upper() != "GET" else None,
            headers={"Access-Token": self.access_token},
            retry_config=retry_config if method.upper() == "GET" else None,
            parse_response=parse_response,
        )
