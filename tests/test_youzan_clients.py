"""Official Youzan read contracts, resource ownership and shop isolation."""

import asyncio
import json

import httpx
import pytest

from shared.cn_commerce_base import CommerceAPIError
from shared.platform_clients import create_platform_client, operation_catalog

ORDER = {"order_info": {"tid": "E123", "node_kdt_id": 1}, "pay_info": {"payment": "10.00", "real_payment": "9.00"}}
CASES = [
    (
        "get_order_list",
        "/api/youzan.trades.sold.get/4.0.4",
        {"page_no": 1, "page_size": 20},
        {"full_order_info_list": [{"full_order_info": ORDER}], "total_results": 1},
    ),
    ("get_order_detail", "/api/youzan.trade.get/4.0.2", {"tid": "E123"}, {"full_order_info": ORDER}),
    (
        "get_refund_list",
        "/api/youzan.trade.refund.search/3.0.1",
        {"page_no": 1, "page_size": 20},
        {"refunds": [{"refund_id": "R1", "tid": "E123", "refund_fee": "10.00"}], "total": 1},
    ),
    (
        "get_refund_detail",
        "/api/youzan.trade.refund.get/3.0.1",
        {"refund_id": "R1"},
        {
            "refund_id": "R1",
            "tid": "E123",
            "refund_fee": "9.00",
            "refund_account_time": "2026-09-10 12:00:00",
            "refund_fund_list": [{"refund_fee": 900, "status": 2}],
        },
    ),
    ("get_shop_info", "/api/youzan.shop.get/3.0.0", {}, {"id": 1, "name": "test"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,path,params,data", CASES)
async def test_documented_business_wire_contract(operation, path, params, data):
    response = {"success": True, "code": 200, "data": data}

    def handle(request):
        assert request.method == "POST"
        assert request.url.host == "open.youzanyun.com"
        assert request.url.path == path
        assert dict(request.url.params) == {"access_token": "test-token"}
        assert json.loads(request.content) == params
        return httpx.Response(200, json=response)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        async with create_platform_client("youzan", {"access_token": "test-token"}, http_client=http) as client:
            assert await client.call(operation, params) == response
            assert operation_catalog("youzan")[operation].contract_status == "documented"
            assert not operation_catalog("youzan")[operation].live_verified


@pytest.mark.asyncio
async def test_two_authorizations_keep_token_snapshot_and_borrowed_resources():
    arrived = asyncio.Event()
    seen, limited = [], []

    class Limiter:
        async def acquire(self, platform, endpoint):
            limited.append((platform, endpoint))

    async def handle(request):
        token = request.url.params["access_token"]
        seen.append(token)
        if len(seen) == 2:
            arrived.set()
        await asyncio.wait_for(arrived.wait(), 1)
        return httpx.Response(200, json={"success": True, "code": "200", "data": {"id": 1 if token == "one" else 2}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        credentials = {"access_token": "one"}
        a = create_platform_client("youzan", credentials, http_client=http, rate_limiter=Limiter())
        b = create_platform_client("youzan", {"access_token": "two"}, http_client=http, rate_limiter=Limiter())
        credentials["access_token"] = "changed"
        results = await asyncio.gather(a.call("get_shop_info", {}), b.call("get_shop_info", {}))
        assert [result["data"]["id"] for result in results] == [1, 2]
        assert set(seen) == {"one", "two"}
        assert limited == [("YOUZAN", "youzan.shop.get/3.0.0")] * 2
        await a.close()
        await b.close()
        assert not http.is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,params",
    [
        ("youzan.trade.refund.apply", {}),
        ("get_shop_info", {"access_token": "other"}),
        ("get_shop_info", {"method": "youzan.trade.refund.apply"}),
        ("get_shop_info", {"unknown": 1}),
        ("get_order_list", {"page_no": 101, "page_size": 20}),
        ("get_order_list", {"page_no": 1, "page_size": 101}),
        ("get_order_list", {"start_created": "2026-09-10 00:00:00"}),
        ("get_order_list", {"start_created": 1788969600, "end_created": 1788973200}),
        ("get_order_list", {"start_created": "2026-01-01 00:00:00", "end_created": "2026-09-01 00:00:00"}),
        ("get_refund_list", {"page_no": 100, "page_size": 31}),
        ("get_refund_list", {"update_time_start": 1788969600000, "update_time_end": 1788973200000}),
        ("get_order_detail", {"order_id": "E123"}),
        ("get_refund_detail", {"refund_id": ""}),
    ],
)
async def test_invalid_requests_fail_before_network(operation, params):
    def forbidden(request):
        pytest.fail("invalid business request reached network")

    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as http:
        async with create_platform_client("youzan", {"access_token": "token"}, http_client=http) as client:
            with pytest.raises(ValueError):
                await client.call(operation, params)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        {"success": False, "code": 5000, "data": {}},
        {"success": True, "code": 200, "data": {}},
        {"code": 200, "data": {"id": 1}},
    ],
)
async def test_business_failure_or_unidentifiable_200_cannot_be_success(response):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response))
    ) as http:
        async with create_platform_client("youzan", {"access_token": "token"}, http_client=http) as client:
            with pytest.raises((ValueError, CommerceAPIError)):
                await client.call("get_shop_info", {})
