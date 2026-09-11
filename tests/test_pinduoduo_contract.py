"""Public PDD transport evidence and explicit blocked business contracts."""

import asyncio
import importlib
import json
from urllib.parse import parse_qs

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from servers.pinduoduo.client import PinduoduoMCP
from shared.cn_commerce_base import CommerceAPIError
from shared.platform_clients import create_platform_client, operation_catalog


@pytest.mark.asyncio
async def test_timestamp_is_seconds_and_official_signing_vector(monkeypatch):
    monkeypatch.setattr("servers.pinduoduo.client.time.time", lambda: 1480411125.123)
    requests = []

    def receive(request):
        requests.append(request)
        return httpx.Response(200, json={"transport_test_response": {}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(receive)) as http:
        client = PinduoduoMCP(
            app_key="1", app_secret="testSecret", access_token="asd78172s8ds9a921j9qqwda12312w1w21211", http_client=http
        )
        await client._call("pdd.order.number.list.get", {"order_status": 1, "page": 1, "page_size": 10})
        await client.close()
        assert not http.is_closed
    body = parse_qs(requests[0].content.decode())
    assert body["timestamp"] == ["1480411125"]
    # Official guide signing example, with this client's JSON response format.
    assert body["sign"] == ["92A61361F6F8FDECCF611A19D1CE9F16"]
    assert requests[0].url.host == "gw-api.pinduoduo.com"


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["type", "client_id", "access_token", "sign", "timestamp", "data_type"])
async def test_transport_cannot_replace_protocol_credentials_or_operation(field):
    def fail(request):
        pytest.fail("protocol override reached HTTP")

    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as http:
        client = PinduoduoMCP(app_key="app", app_secret="secret", access_token="token", http_client=http)
        with pytest.raises(ValueError):
            await client._call("pdd.test", {field: "replacement"})
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [[], None, {"error_response": []}, {"error_response": None}])
async def test_malformed_response_is_not_success(body):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=json.dumps(body)))
    ) as http:
        client = PinduoduoMCP(app_key="app", app_secret="secret", access_token="token", http_client=http)
        with pytest.raises(CommerceAPIError):
            await client._call("pdd.test", {})
        await client.close()


PDD_READS = {
    "get_order_list": "pdd.order.list.get",
    "get_increment_orders": "pdd.order.number.list.increment.get",
    "get_order_detail": "pdd.order.information.get",
    "get_refund_list": "pdd.refund.list.increment.get",
    "get_refund_detail": "pdd.refund.information.get",
    "get_shop_info": "pdd.mall.info.get",
}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,endpoint", PDD_READS.items())
async def test_partial_business_contract_never_sends(operation, endpoint):
    calls = []

    async def forbidden(request):
        calls.append(request)
        return httpx.Response(200, json={})

    catalog = operation_catalog("pinduoduo")
    assert catalog[operation].endpoint == endpoint
    assert catalog[operation].contract_status == "partial"
    assert not catalog[operation].supported and not catalog[operation].live_verified
    assert "schema" in catalog[operation].reason
    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as http:
        async with create_platform_client(
            "pinduoduo", {"app_key": "app", "app_secret": "secret", "access_token": "token"}, http_client=http
        ) as client:
            with pytest.raises(ValueError, match="Unsupported"):
                await client.call(operation, {})
    assert not calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,params",
    [
        ("get_order_list", {"start_time": "2026-09-09 00:00:00", "end_time": "2026-09-10 00:00:00"}),
        ("get_order_detail", {"order_sn": "example"}),
        ("get_refund_list", {"start_time": "2026-09-09 00:00:00", "end_time": "2026-09-10 00:00:00"}),
        ("get_refund_detail", {"refund_id": "example"}),
        ("get_shop_info", {}),
    ],
)
async def test_cli_does_not_use_invented_parameters(operation, params, monkeypatch):
    server = importlib.import_module("servers.pinduoduo.server")

    async def fail(*args):
        pytest.fail("unverified CLI contract reached transport")

    monkeypatch.setattr(server.pdd, "_call", fail)
    with pytest.raises(ToolError, match="schema"):
        await getattr(server, operation)(**params)


@pytest.mark.asyncio
async def test_two_shop_transport_snapshots_are_independent():
    entered = asyncio.Event()
    requests = []

    async def receive(request):
        requests.append(parse_qs(request.content.decode()))
        if len(requests) == 2:
            entered.set()
        await asyncio.wait_for(entered.wait(), 1)
        return httpx.Response(200, json={"transport_test_response": {}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(receive)) as http:
        a = PinduoduoMCP(app_key="app-a", app_secret="secret-a", access_token="shop-a", http_client=http)
        b = PinduoduoMCP(app_key="app-b", app_secret="secret-b", access_token="shop-b", http_client=http)
        await asyncio.gather(a._call("pdd.test"), b._call("pdd.test"))
        await a.close()
        await b.close()
        assert not http.is_closed
    assert {(r["client_id"][0], r["access_token"][0]) for r in requests} == {("app-a", "shop-a"), ("app-b", "shop-b")}
    assert requests[0]["sign"] != requests[1]["sign"]
