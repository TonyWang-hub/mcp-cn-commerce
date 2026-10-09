"""Explicit fixed-token Youzan read client; the host owns token lifecycle."""

from typing import Any

from servers.youzan.schema import validate_data, validate_params
from shared.cn_commerce_base import DEFAULT_RETRY, CommerceAPIError, CommerceMCPBase, ConfigValidationError


class YouzanClient(CommerceMCPBase):
    """POST native JSON using the authorization snapshot's access_token."""

    PLATFORM = "YOUZAN"
    BASE_URL = "https://open.youzanyun.com/api/"

    async def _call(self, endpoint: str, biz_params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.access_token:
            raise ConfigValidationError("YOUZAN", ["YOUZAN_ACCESS_TOKEN"])
        params = biz_params or {}
        validate_params(endpoint, params)

        def prepare():
            return {"params": {"access_token": self.access_token}, "json": params}

        def parse(payload):
            if not isinstance(payload, dict):
                raise ValueError("Youzan response must be an object")
            if payload.get("success") is not True or payload.get("code") not in (200, "200"):
                raise CommerceAPIError(payload.get("code", -1), "Youzan read request was not successful")
            validate_data(endpoint, payload.get("data"))
            return payload

        return await self._send_request(
            "POST",
            self.BASE_URL + endpoint,
            endpoint=endpoint,
            prepare_request=prepare,
            parse_response=parse,
            retry_config=DEFAULT_RETRY,
        )
