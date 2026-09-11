"""Current official read contracts through the public SDK and real HTTP serialization."""

import hashlib
import json

import httpx
import pytest

from shared.cn_commerce_base import CommerceAPIError
from shared.platform_clients import create_platform_client

CREDS = {"app_key": "xhs-app", "app_secret": "xhs-secret", "access_token": "xhs-shop-token"}


async def exchange(operation, params, response):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=response)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        async with create_platform_client("xiaohongshu", CREDS, http_client=http) as client:
            result = await client.call(operation, params)
            assert client.operations[operation].live_verified is False
    assert len(requests) == 1
    request = requests[0]
    payload = json.loads(request.content)
    assert request.method == "POST"
    assert str(request.url) == "https://ark.xiaohongshu.com/ark/open_api/v3/common_controller"
    assert request.headers["content-type"] == "application/json;charset=utf-8"
    raw = f"{payload['method']}?appId=xhs-app&timestamp={payload['timestamp']}&version=2.0xhs-secret"
    assert payload["sign"] == hashlib.md5(raw.encode()).hexdigest()
    assert payload["accessToken"] == CREDS["access_token"]
    return result, {
        k: v for k, v in payload.items() if k not in {"appId", "accessToken", "timestamp", "version", "sign", "method"}
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("start", [1788969600, 1788969600000])
async def test_order_native_integers_are_not_rescaled_and_reverse_page_metadata_survives(start):
    params = {
        "startTime": start,
        "endTime": start + 1000,
        "timeType": 2,
        "pageNo": 7,
        "pageSize": 50,
        "orderStatus": 0,
        "orderType": 4,
    }
    response = {
        "success": True,
        "error_code": 0,
        "data": {
            "total": 301,
            "maxPageNo": 7,
            "pageNo": 7,
            "pageSize": 50,
            "orderList": [{"orderId": "order-301", "paidTime": 1788969600123}],
        },
    }
    result, sent = await exchange("get_order_list", params, response)
    assert sent == params
    assert result == response


@pytest.mark.asyncio
async def test_numeric_aliases_preserve_native_units_and_explicit_update_mode():
    _, sent = await exchange(
        "get_order_list",
        {
            "start_time": "1788969600000",
            "end_time": "1788971400000",
            "time_type": "2",
            "page": "100",
            "page_size": "100",
            "order_status": "0",
            "order_type": "0",
        },
        {"success": True, "code": "0", "data": {}},
    )
    assert sent == {
        "startTime": 1788969600000,
        "endTime": 1788971400000,
        "timeType": 2,
        "pageNo": 100,
        "pageSize": 100,
        "orderStatus": 0,
        "orderType": 0,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("time_type,window", [(1, 86_400_000), (2, 1_800_000)])
async def test_refund_native_window_edges_and_filters_survive(time_type, window):
    params = {
        "startTime": 1788969600000,
        "endTime": 1788969600000 + window,
        "timeType": time_type,
        "pageNo": 500,
        "pageSize": 100,
        "statuses": [4, 9001],
        "returnTypes": [1, 2, 6],
    }
    response = {
        "success": True,
        "error_code": 0,
        "data": {
            "success": True,
            "code": 0,
            "data": {
                "afterSaleBasicInfos": [{"returnsId": "return-1", "orderId": "order-1"}],
                "totalCount": 50000,
                "pageNo": 500,
                "pageSize": 100,
            },
        },
    }
    result, sent = await exchange("get_refund_list", params, response)
    assert sent == params
    assert result == response


@pytest.mark.asyncio
async def test_refund_iso_alias_requires_explicit_timezone_and_converts_to_milliseconds():
    _, sent = await exchange(
        "get_refund_list",
        {
            "start_time": "2026-09-10T08:00:00+08:00",
            "end_time": "2026-09-10T00:30:00Z",
            "time_type": 2,
            "refund_status": "4,9001",
            "return_types": "1,6",
        },
        {"success": True, "code": 0, "data": {"afterSaleBasicInfos": [], "totalCount": 0}},
    )
    assert sent == {
        "startTime": 1788998400000,
        "endTime": 1789000200000,
        "timeType": 2,
        "pageNo": 1,
        "pageSize": 20,
        "statuses": [4, 9001],
        "returnTypes": [1, 6],
    }


@pytest.mark.asyncio
async def test_refund_native_numeric_milliseconds_are_never_guessed_from_magnitude():
    _, sent = await exchange(
        "get_refund_list", {"startTime": 1000, "endTime": 2000, "timeType": 1}, {"success": True, "code": 0, "data": {}}
    )
    assert sent["startTime"] == 1000 and sent["endTime"] == 2000


@pytest.mark.asyncio
async def test_refund_lookup_by_parent_order_does_not_invent_a_time_range():
    _, sent = await exchange("get_refund_list", {"orderId": "order-1"}, {"success": True, "code": 0, "data": {}})
    assert sent == {"orderId": "order-1", "pageNo": 1, "pageSize": 20}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,params,response",
    [
        (
            "get_order_detail",
            {"orderId": "order-1"},
            {"success": True, "error_code": 0, "data": {"orderId": "order-1", "shopId": "a" * 24}},
        ),
        (
            "get_refund_detail",
            {"returnsId": "return-1"},
            {
                "success": True,
                "code": 0,
                "data": {
                    "afterSaleInfo": {
                        "returnsId": "return-1",
                        "orderId": "order-1",
                        "refundStatus": 2,
                        "refundAmountYuan": "12.34",
                        "refundTime": 1788969600,
                    }
                },
            },
        ),
    ],
)
async def test_native_detail_ids_preserve_official_containers(operation, params, response):
    result, sent = await exchange(operation, params, response)
    assert sent == params
    assert result == response


ORDER = {"startTime": 1788969600000, "endTime": 1788971400000, "timeType": 2}
REFUND = {"startTime": 1788969600000, "endTime": 1788971400000, "timeType": 2}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,params",
    [
        ("get_order_list", {**ORDER, "start_time": ORDER["startTime"]}),
        ("get_order_list", {**ORDER, "pageNo": 2, "page": 2}),
        ("get_order_list", {**ORDER, "timeType": 3}),
        ("get_order_list", {**ORDER, "startTime": True}),
        ("get_order_list", {**ORDER, "startTime": 1788969600000.5}),
        ("get_order_list", {**ORDER, "startTime": 2**63}),
        ("get_order_list", {**ORDER, "pageNo": 101}),
        ("get_order_list", {**ORDER, "pageSize": 0}),
        ("get_order_list", {**ORDER, "endTime": ORDER["startTime"]}),
        ("get_order_list", {**ORDER, "orderStatus": 11}),
        ("get_order_list", {**ORDER, "orderType": 6}),
        ("get_order_list", {"start_time": "2026-09-10T00:00:00Z", "end_time": "2026-09-10T00:30:00Z"}),
        ("get_order_list", {**ORDER, "unknownFilter": 1}),
        ("get_refund_list", {**REFUND, "endTime": REFUND["endTime"] + 1}),
        ("get_refund_list", {**REFUND, "timeType": 1, "endTime": REFUND["startTime"] + 86_400_001}),
        ("get_refund_list", {**REFUND, "pageNo": 501, "pageSize": 100}),
        ("get_refund_list", {**REFUND, "timeType": 0}),
        ("get_refund_list", {**REFUND, "statuses": [999]}),
        ("get_refund_list", {**REFUND, "statuses": "4"}),
        ("get_refund_list", {**REFUND, "returnTypes": [3]}),
        ("get_refund_list", {"orderId": "order-1", "timeType": 2}),
        ("get_refund_list", {"orderId": "order-1", "startTime": 1000}),
        ("get_refund_list", {"start_time": "2026-09-10 00:00:00", "end_time": "2026-09-10 00:30:00"}),
        ("get_refund_list", {"startTime": "2026-09-10T00:00:00Z", "endTime": "2026-09-10T00:30:00Z"}),
        ("get_order_detail", {"orderId": "order-1", "order_id": "order-1"}),
        ("get_order_detail", {"orderId": " "}),
        ("get_order_detail", {"orderId": "order-1", "headers": {"Authorization": "override"}}),
        ("get_refund_detail", {"returnsId": "return-1", "requestHeader": {"requestFrom": 1}}),
        ("get_refund_detail", {"returnsId": "return-1", "needNegotiateRecord": True}),
    ],
)
async def test_invalid_or_ambiguous_parameters_never_send(operation, params):
    def forbidden(request):
        pytest.fail("invalid contract reached HTTP")

    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as http:
        async with create_platform_client("xiaohongshu", CREDS, http_client=http) as client:
            with pytest.raises(ValueError):
                await client.call(operation, params)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        {},
        [],
        {"data": {}},
        {"success": True, "data": {}},
        {"success": "true", "code": 0, "data": {}},
        {"success": 1, "code": 0, "data": {}},
        {"success": False, "code": 0, "data": {}},
        {"success": True, "code": 0, "data": []},
        {"success": True, "code": False, "data": {}},
        {"success": True, "code": 0, "error_code": 401, "data": {}},
        {"success": True, "code": 401, "error_code": 0, "data": {}},
        {"success": True, "code": "xhs-shop-token", "data": {}},
        {"error_response": {"code": 401, "msg": "xhs-shop-token phone=13800000000"}},
        {
            "success": True,
            "error_code": 0,
            "data": {"success": False, "code": 401, "data": {}, "msg": "xhs-shop-token phone=13800000000"},
        },
        {"success": True, "error_code": 0, "data": {"code": 0, "data": {}}},
        {"success": True, "error_code": 0, "data": {"success": True, "code": 0, "data": []}},
    ],
)
async def test_unknown_failed_and_nested_failed_envelopes_raise_safe_errors(response):
    with pytest.raises(CommerceAPIError) as caught:
        await exchange("get_refund_detail", {"refund_id": "return-1"}, response)
    assert isinstance(caught.value.code, int)
    assert "xhs-shop-token" not in str(caught.value)
    assert "13800000000" not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", ["get_order_list", "get_refund_list"])
async def test_mcp_tools_expose_update_time_mode(monkeypatch, tool_name):
    from servers.xiaohongshu import server

    seen = []

    async def call(method, path, params):
        seen.append(params)
        return {"success": True, "error_code": 0, "data": {}}

    monkeypatch.setattr(server.xhs, "_call", call)
    await getattr(server, tool_name)(start_time="1000", end_time="2000", time_type=2)
    assert int(seen[0]["time_type"]) == 2
