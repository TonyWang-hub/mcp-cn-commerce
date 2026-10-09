"""Current official TOP field-selection, pagination and response contracts."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from servers.taobao import server
from shared.platform_clients import create_platform_client

CREDS = {"app_key": "app", "app_secret": "secret", "access_token": "seller-token"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,args,identifier",
    [
        ("get_order_list", ("2026-09-10 00:00:00", "2026-09-10 01:00:00"), "tid"),
        ("get_order_detail", ("123",), "tid"),
        ("get_increment_orders", ("2026-09-10 00:00:00", "2026-09-10 01:00:00"), "tid"),
        ("get_refund_list", ("2026-09-10 00:00:00", "2026-09-10 01:00:00"), "refund_id"),
        ("get_refund_detail", ("123",), "refund_id"),
    ],
)
async def test_business_tools_supply_required_identity_money_time_fields(name, args, identifier):
    with patch.object(server.taobao, "_call", new=AsyncMock(return_value={})) as call:
        await getattr(server, name)(*args)
    fields = set(call.call_args.args[1].get("fields", "").split(","))
    assert identifier in fields
    assert ("payment" if identifier == "tid" else "refund_fee") in fields
    assert ("pay_time" if identifier == "tid" else "end_time") in fields
    assert not fields & {"receiver_name", "receiver_mobile", "receiver_address"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,params",
    [
        ("get_order_list", {"page_no": 1}),
        ("get_order_detail", {"fields": "tid"}),
        ("get_order_list", {"fields": "tid", "page_no": 0}),
        ("get_order_list", {"fields": "tid", "page_size": 101}),
        (
            "get_increment_orders",
            {"fields": "tid", "start_modified": "2026-09-08 00:00:00", "end_modified": "2026-09-10 00:00:00"},
        ),
        ("get_increment_orders", {"fields": "tid"}),
        ("get_refund_detail", {"fields": "refund_id", "refund_id": ""}),
    ],
)
async def test_invalid_contract_is_rejected_before_http(operation, params):
    def forbidden(request):
        pytest.fail("invalid TOP business params reached network")

    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as http:
        async with create_platform_client("taobao", CREDS, http_client=http) as client:
            with pytest.raises(ValueError):
                await client.call(operation, params)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        {},
        {"trades_sold_get_response": {"total_results": 0}},
        {"trades_sold_get_response": {"total_results": 1, "trades": {"trade": [{}]}}},
    ],
)
async def test_missing_envelope_or_identity_never_means_empty_success(response):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response))
    ) as http:
        async with create_platform_client("taobao", CREDS, http_client=http) as client:
            with pytest.raises(ValueError):
                await client.call("get_order_list", {"fields": "tid"})


@pytest.mark.asyncio
async def test_has_next_pagination_preserves_absent_total_and_native_trade_container():
    response = {"trades_sold_get_response": {"has_next": False, "trades": {"trade": [{"tid": 123, "payment": "1.01"}]}}}

    def handle(request):
        assert request.url.params["use_has_next"] == "true"
        assert request.url.params["fields"] == "tid,payment"
        return httpx.Response(200, json=response)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        async with create_platform_client("taobao", CREDS, http_client=http) as client:
            result = await client.call("get_order_list", {"fields": "tid,payment", "use_has_next": True})
    assert result == response
    assert "total_results" not in result["trades_sold_get_response"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "platform,params,response",
    [
        (
            "taobao",
            {"fields": "tid", "type": "tmall_i18n"},
            {"trades_sold_get_response": {"total_results": 0, "trades": {"trade": []}}},
        ),
        (
            "youzan",
            {"type": "NORMAL"},
            {"success": True, "code": 200, "data": {"full_order_info_list": [], "total_results": 0}},
        ),
    ],
)
async def test_type_is_a_business_filter_for_top_and_youzan(platform, params, response):
    def handle(request):
        import json

        business = dict(request.url.params) if platform == "taobao" else json.loads(request.content)
        assert business["type"] == params["type"]
        return httpx.Response(200, json=response)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        async with create_platform_client(platform, CREDS, http_client=http) as client:
            assert await client.call("get_order_list", params) == response
