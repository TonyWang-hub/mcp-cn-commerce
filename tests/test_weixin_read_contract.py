"""Official store read routes and cursor contracts, checked 2026-09-10."""

import json
from unittest.mock import AsyncMock

import httpx
import pytest

from shared.platform_clients import create_platform_client, operation_catalog


@pytest.mark.asyncio
async def test_shop_info_is_get_and_has_no_request_body():
    requests = []
    body = {"errcode": 0, "info": {"username": "gh_store_original_id", "nickname": "store"}}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: (requests.append(r), httpx.Response(200, json=body))[1])
    ) as http:
        sdk = create_platform_client("weixin_store", {"access_token": "shop-token"}, http_client=http)
        assert await sdk.call("get_shop_info", {}) == body
        await sdk.close()
        assert not http.is_closed
    request = requests[0]
    assert request.method == "GET" and request.url.path == "/channels/ec/basics/info/get"
    assert not request.content and dict(request.url.params) == {"access_token": "shop-token"}
    assert all(
        op.contract_status == "documented" and not op.live_verified for op in operation_catalog("weixin_store").values()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("time_type", ["create", "update"])
async def test_refunds_use_seconds_cursor_and_do_not_send_page_numbers(monkeypatch, time_type):
    from servers.weixin_store import server

    call = AsyncMock(
        return_value={"errcode": 0, "after_sale_order_id_list": ["r1"], "has_more": True, "next_key": "opaque-next"}
    )
    monkeypatch.setattr(server._wx, "_request", call)
    result = await server.get_refund_list(
        "2026-09-10T00:00:00+08:00", "2026-09-11T00:00:00+08:00", next_key="previous", time_type=time_type
    )
    assert json.loads(result)["next_key"] == "opaque-next"
    call.assert_awaited_once_with(
        "POST",
        "/channels/ec/aftersale/getaftersalelist",
        data={f"begin_{time_type}_time": 1788969600, f"end_{time_type}_time": 1789056000, "next_key": "previous"},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"page": 2},
        {"time_type": "payment"},
        {"end_time": "2026-09-12 00:00:00"},
        {"end_time": "2026-09-09 00:00:00"},
        {"next_key": 10},
    ],
)
async def test_invalid_refund_pagination_fails_before_network(monkeypatch, kwargs):
    from mcp.server.mcpserver.exceptions import ToolError

    from servers.weixin_store import server

    call = AsyncMock()
    monkeypatch.setattr(server._wx, "_request", call)
    args = {"start_time": "2026-09-10 00:00:00", "end_time": "2026-09-11 00:00:00", **kwargs}
    with pytest.raises(ToolError):
        await server.get_refund_list(**args)
    call.assert_not_awaited()


@pytest.mark.asyncio
async def test_cli_shop_info_uses_same_documented_endpoint(monkeypatch):
    from servers.weixin_store import server

    call = AsyncMock(return_value={"errcode": 0, "info": {"username": "gh_store"}})
    monkeypatch.setattr(server._wx, "_request", call)
    await server.get_shop_info()
    call.assert_awaited_once_with("GET", "/channels/ec/basics/info/get")
