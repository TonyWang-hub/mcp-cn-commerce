"""Fail closed while the documented JD POP contract migration is pending."""

from unittest.mock import AsyncMock

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from shared.platform_clients import create_platform_client, operation_catalog


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation", ["get_order_list", "get_order_detail", "get_refund_list", "get_refund_detail", "get_shop_info"]
)
async def test_unmigrated_jd_business_contract_cannot_send_legacy_requests(operation):
    requests = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: (requests.append(r), httpx.Response(200, json={}))[1])
    ) as http:
        client = create_platform_client(
            "jd", {"app_key": "app", "app_secret": "secret", "access_token": "token"}, http_client=http
        )
        with pytest.raises(ValueError, match="JD POP"):
            await client.call(operation, {})
        assert not requests
        await client.close()
    contract = operation_catalog("jd")[operation]
    assert not contract.supported and not contract.live_verified and contract.contract_status == "partial"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,params",
    [
        ("get_order_list", {"start_time": "2026-09-01", "end_time": "2026-09-02"}),
        ("get_order_detail", {"order_id": "1"}),
        ("get_shop_info", {}),
        ("get_after_sale_list", {"start_time": "2026-09-01", "end_time": "2026-09-02"}),
        ("get_after_sale_detail", {"after_sale_id": "1"}),
    ],
)
async def test_legacy_tool_discovery_keeps_names_and_exposes_unsupported_reason(monkeypatch, name, params):
    from servers.jd import server

    call = AsyncMock()
    monkeypatch.setattr(server.jd, "_call", call)
    with pytest.raises(ToolError, match="JD POP"):
        await getattr(server, name)(**params)
    call.assert_not_awaited()
