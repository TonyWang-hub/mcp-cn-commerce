"""Regression cases derived from the official schemas read on 2026-09-10."""

import json
from unittest.mock import patch

import httpx
import pytest

from servers.doudian import server
from servers.doudian.client import DouDianClient
from shared.platform_clients import create_platform_client

CREDS = {"app_key": "app", "app_secret": "secret", "access_token": "token", "shop_id": "shop"}
ORDER = {
    "order_id": "order",
    "shop_id": 123,
    "order_status": 5,
    "pay_amount": 1000,
    "promotion_pay_amount": 100,
    "pay_time": 1788969900,
    "create_time": 1788969600,
    "actual_receive_amount_info": {"actual_receive_amount": 1050},
    "sku_order_list": [{"order_id": "sku-order", "product_id": "product", "item_num": 2, "price": 500}],
}
REFUND = {
    "aftersale_info": {
        "aftersale_id": "refund",
        "refund_status": 3,
        "aftersale_status": 12,
        "refund_amount": 1000,
        "apply_time": 1788969600,
        "update_time": 1788969900,
    },
    "order_info": {"shop_order_id": "order"},
}
DETAIL = {
    "process_info": {
        "after_sale_info": {
            "after_sale_id": 6965315853751632172,
            "refund_status": 3,
            "real_refund_amount": 900,
            "refund_total_amount": 1000,
            "refund_time": 1788969900,
        }
    },
    "order_info": {"shop_order_id": 123},
}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation, route, params, response",
    [
        ("get_order_list", "/order/searchList", {"page": 0, "size": 20}, {"shop_order_list": [ORDER], "total": 1}),
        ("get_order_detail", "/order/orderDetail", {"shop_order_id": "order"}, {"shop_order_detail": ORDER}),
        (
            "get_refund_list",
            "/afterSale/List",
            {"page": 0, "size": 20},
            {"items": [REFUND], "total": 1, "has_more": False},
        ),
        ("get_refund_detail", "/afterSale/Detail", {"after_sale_id": "6965315853751632172"}, DETAIL),
    ],
)
async def test_sdk_uses_official_route_and_preserves_official_data(operation, route, params, response):
    def handle(request):
        assert request.url.path == route
        assert request.url.params["method"] == route[1:].replace("/", ".")
        assert json.loads(request.content) == params
        return httpx.Response(200, json={"code": 10000, "data": response})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        async with create_platform_client("doudian", CREDS, http_client=http) as sdk:
            assert await sdk.call(operation, params) == response
            assert sdk.operations[operation].contract_status == "documented"
            assert not sdk.operations[operation].live_verified


@pytest.mark.asyncio
async def test_order_tool_builds_seconds_filters_and_preserves_payment_semantics():
    seen = []

    def handle(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"code": 10000, "data": {"shop_order_list": [ORDER], "total": 2}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        client = DouDianClient(**CREDS, http_client=http)
        with patch.object(server, "_get_client", return_value=client):
            result = await server.get_order_list("2026-09-10 00:00:00", "2026-09-10 01:00:00", "5", page_size=1)
    assert seen == [
        {
            "page": 0,
            "size": 1,
            "create_time_start": 1788969600,
            "create_time_end": 1788973200,
            "combine_status": [{"order_status": "5"}],
        }
    ]
    assert result["has_more"] is True
    order = result["orders"][0]
    assert order["pay_amount"] == 1000
    assert order["buyer_paid_amount"] == 900
    assert order["merchant_received_amount"] == 1050
    assert order["product_info"][0]["quantity"] == 2


@pytest.mark.asyncio
async def test_update_time_refund_tool_uses_sort_and_marks_detail_requirement():
    seen = []

    def handle(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"code": 10000, "data": {"items": [REFUND], "total": 1, "has_more": False}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        with patch.object(server, "_get_client", return_value=DouDianClient(**CREDS, http_client=http)):
            result = await server.get_refund_list("2026-09-10 00:00:00", "2026-09-10 01:00:00", time_type="update")
    assert seen[0]["update_start_time"] == 1788969600
    assert seen[0]["order_by"] == ["update_time asc"]
    refund = result["refunds"][0]
    assert refund["refund_id"] == "refund"
    assert refund["amount"] is None
    assert refund["detail_required"] is True
    assert "refund_time" not in refund


@pytest.mark.asyncio
async def test_unverified_shop_info_never_issues_a_business_request():
    result = await server.get_shop_info()
    assert result.get("supported") is False
    assert result.get("shop") is None
    async with create_platform_client("doudian", CREDS) as sdk:
        assert not sdk.operations["get_shop_info"].supported
        with pytest.raises(ValueError, match="Unsupported"):
            await sdk.call("get_shop_info", {})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {"page": -1, "size": 20},
        {"page": 0, "size": 101},
        {"page": 0, "size": 0},
        {"page": 0, "size": 20, "start_time": 1788969600},
        {"page": 0, "size": 20, "create_time_start": "2026-09-10"},
    ],
)
async def test_sdk_invalid_pagination_and_legacy_order_filters_fail_before_network(params):
    def forbidden(request):
        pytest.fail("invalid params reached network")

    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as http:
        async with create_platform_client("doudian", CREDS, http_client=http) as sdk:
            with pytest.raises(ValueError):
                await sdk.call("get_order_list", params)


@pytest.mark.asyncio
async def test_missing_order_list_is_not_successful_empty_page():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"code": 10000, "data": {"total": 0}}))
    ) as http:
        async with create_platform_client("doudian", CREDS, http_client=http) as sdk:
            with pytest.raises(ValueError, match="shop_order_list"):
                await sdk.call("get_order_list", {"page": 0, "size": 20})


def test_public_operation_catalog_requires_no_credentials(monkeypatch):
    from shared import platform_clients

    assert hasattr(platform_clients, "operation_catalog"), "public no-credential catalogue is missing"
    monkeypatch.setattr(platform_clients, "import_module", lambda name: pytest.fail("catalogue imported client"))
    catalog = platform_clients.operation_catalog("doudian")
    assert catalog["get_order_list"].endpoint == "order/searchList"
    with pytest.raises(TypeError):
        catalog["write"] = catalog["get_order_list"]
    with pytest.raises(ValueError):
        platform_clients.operation_catalog("unknown")


@pytest.mark.asyncio
async def test_two_pages_use_stable_update_window_and_zero_based_page_numbers():
    received = []
    start, end = 1788969600, 1788973200

    def handle(request):
        body = json.loads(request.content)
        received.append(body)
        page = body["page"]
        return httpx.Response(
            200,
            json={
                "code": 10000,
                "data": {"shop_order_list": [{**ORDER, "order_id": str(page)}], "total": 2, "page": page, "size": 1},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        async with create_platform_client("doudian", CREDS, http_client=http) as sdk:
            collected = []
            for page in range(2):
                data = await sdk.call(
                    "get_order_list",
                    {
                        "page": page,
                        "size": 1,
                        "update_time_start": start,
                        "update_time_end": end,
                        "order_by": "update_time",
                        "order_asc": True,
                    },
                )
                collected.extend(data["shop_order_list"])
            assert len(collected) == data["total"] == 2
    assert [r["page"] for r in received] == [0, 1]
    assert {(r["update_time_start"], r["update_time_end"], r["order_by"]) for r in received} == {
        (start, end, "update_time")
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,params",
    [
        ("get_refund_list", {"page": 501, "size": 100}),
        ("get_refund_list", {"page": 0, "size": 100, "update_start_time": 1788969600, "update_end_time": 1788973200}),
        ("get_order_detail", {"order_id": "wrong-alias"}),
        ("get_refund_detail", {"refund_id": "wrong-alias"}),
        ("get_order_list", {"page": 0, "size": 20, "create_time_start": 1788969600000}),
    ],
)
async def test_sdk_rejects_uncollectable_windows_and_wrong_detail_identifiers(operation, params):
    def forbidden(request):
        pytest.fail("invalid documented parameters reached network")

    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as http:
        async with create_platform_client("doudian", CREDS, http_client=http) as sdk:
            with pytest.raises(ValueError):
                await sdk.call(operation, params)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,params,response",
    [
        ("get_order_detail", {"shop_order_id": "order"}, {"shop_order_detail": {}}),
        ("get_refund_detail", {"after_sale_id": "refund"}, {"process_info": {"after_sale_info": {}}}),
        ("get_order_list", {"page": 0, "size": 1}, {"shop_order_list": [{}], "total": 1}),
        ("get_refund_list", {"page": 0, "size": 1}, {"items": [{}], "total": 1, "has_more": False}),
    ],
)
async def test_unidentifiable_records_are_not_valid_successes(operation, params, response):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"code": 10000, "data": response}))
    ) as http:
        async with create_platform_client("doudian", CREDS, http_client=http) as sdk:
            with pytest.raises(ValueError, match="identifier"):
                await sdk.call(operation, params)
