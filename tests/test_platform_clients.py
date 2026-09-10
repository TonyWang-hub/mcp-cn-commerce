"""Wire-level isolation and ownership checks for the explicit SDK."""

import asyncio
import importlib
import importlib.util

import httpx
import pytest


def sdk():
    assert importlib.util.find_spec("shared.platform_clients") is not None, "explicit platform SDK is missing"
    return importlib.import_module("shared.platform_clients")


@pytest.mark.asyncio
async def test_two_shops_keep_signed_credentials_separate_and_snapshot_inputs():
    factory = sdk().create_platform_client
    entered = asyncio.Event()
    seen = []

    async def handle(request):
        seen.append(dict(request.url.params))
        if len(seen) == 2:
            entered.set()
        await asyncio.wait_for(entered.wait(), 1)
        return httpx.Response(200, json={"shop_get_response": {"session": request.url.params["session"]}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        credentials_a = {"app_key": "app-a", "app_secret": "secret-a", "access_token": "token-a"}
        a = factory("taobao", credentials_a, http_client=http)
        b = factory(
            "taobao", {"app_key": "app-b", "app_secret": "secret-b", "access_token": "token-b"}, http_client=http
        )
        credentials_a["access_token"] = "changed-after-construction"
        results = await asyncio.gather(a.call("get_shop_info", {}), b.call("get_shop_info", {}))
        assert {r["shop_get_response"]["session"] for r in results} == {"token-a", "token-b"}
        assert {(r["app_key"], r["session"]) for r in seen} == {("app-a", "token-a"), ("app-b", "token-b")}
        assert all(r["method"] == "taobao.shop.get" and r["sign"] for r in seen)
        assert seen[0]["sign"] != seen[1]["sign"]
        await a.close()
        await b.close()
        assert not http.is_closed


@pytest.mark.asyncio
async def test_independent_resources_are_used_and_borrowed_transport_is_not_closed():
    factory = sdk().create_platform_client
    calls = []

    class Limiter:
        async def acquire(self, platform, endpoint):
            calls.append((platform, endpoint))

    def first(request):
        return httpx.Response(200, json={"source": "first"})

    def second(request):
        return httpx.Response(200, json={"source": "second"})

    credentials = {"access_token": "wx-token"}
    async with httpx.AsyncClient(transport=httpx.MockTransport(first)) as http_a:
        async with httpx.AsyncClient(transport=httpx.MockTransport(second)) as http_b:
            a = factory("weixin_store", credentials, http_client=http_a, rate_limiter=Limiter())
            b = factory("weixin_store", credentials, http_client=http_b)
            assert await a.call("get_shop_info", {}) == {"source": "first"}
            assert await b.call("get_shop_info", {}) == {"source": "second"}
            assert calls == [("WEIXIN_STORE", "/channels/ec/basics/info/get")]
            await a.close()
            assert not http_a.is_closed
            with pytest.raises(RuntimeError, match="closed"):
                await a.call("get_shop_info", {})
            await b.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation, params",
    [
        ("taobao.trade.close", {}),
        ("request", {"method": "taobao.trade.close"}),
        ("get_shop_info", {"method": "taobao.trade.close"}),
        ("get_shop_info", {"session": "other-shop"}),
        ("get_shop_info", {"access_token": "other-shop"}),
    ],
)
async def test_rejects_unknown_methods_and_protocol_overrides_without_http(operation, params):
    factory = sdk().create_platform_client

    def forbidden(request):
        pytest.fail("invalid SDK request reached the network")

    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as http:
        client = factory(
            "taobao", {"app_key": "app", "app_secret": "secret", "access_token": "token"}, http_client=http
        )
        with pytest.raises(ValueError):
            await client.call(operation, params)
        await client.close()


@pytest.mark.asyncio
async def test_closed_external_transport_cannot_fall_back_to_network():
    factory = sdk().create_platform_client
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})))
    client = factory("weixin_store", {"access_token": "token"}, http_client=http)
    await http.aclose()
    with pytest.raises(RuntimeError, match="closed"):
        await client.call("get_shop_info", {})
    await client.close()


OTHER_MAPPINGS = [
    ("jd", "get_order_list", "jd.pop.order.search"),
    ("jd", "get_order_detail", "jd.pop.order.get"),
    ("jd", "get_refund_list", "jd.pop.afs.search"),
    ("jd", "get_refund_detail", "jd.pop.afs.get"),
    ("jd", "get_shop_info", "jd.pop.shop.get"),
    ("kuaishou", "get_order_list", "/open/api/order/list"),
    ("kuaishou", "get_order_detail", "/open/api/order/detail"),
    ("kuaishou", "get_refund_list", "/open/api/refund/list"),
    ("kuaishou", "get_refund_detail", "/open/api/refund/detail"),
    ("kuaishou", "get_shop_info", "/open/api/shop/info"),
    ("xiaohongshu", "get_order_list", "order.getOrderList"),
    ("xiaohongshu", "get_order_detail", "order.getOrderDetail"),
    ("xiaohongshu", "get_refund_list", "afterSale.listAfterSaleInfos"),
    ("xiaohongshu", "get_refund_detail", "afterSale.getAfterSaleInfo"),
    ("weixin_store", "get_order_list", "/channels/ec/order/list/get"),
    ("weixin_store", "get_order_detail", "/channels/ec/order/get"),
    ("weixin_store", "get_refund_list", "/channels/ec/aftersale/getaftersalelist"),
    ("weixin_store", "get_refund_detail", "/channels/ec/aftersale/getaftersaleorder"),
    ("weixin_store", "get_shop_info", "/channels/ec/basics/info/get"),
    ("oceanengine", "get_advertiser_info", "/open_api/2/advertiser/info/"),
    ("oceanengine", "get_account_balance", "/open_api/2/advertiser/fund/get/"),
    ("oceanengine", "get_campaign_report", "/open_api/2/report/advertiser/get/"),
    ("oceanengine", "get_ad_detail_report", "/open_api/2/report/ad/get/"),
    ("oceanengine", "get_qianchuan_report", "/open_api/2/qianchuan/report/ad/get/"),
]


def platform_credentials(platform):
    if platform in {"weixin_store", "oceanengine"}:
        return {"access_token": "shop-token"}
    values = {"app_key": "app", "app_secret": "secret", "access_token": "shop-token"}
    if platform == "kuaishou":
        values["sign_secret"] = "sign-secret"
    if platform == "doudian":
        values["shop_id"] = "shop"
    return values


@pytest.mark.asyncio
@pytest.mark.parametrize("platform, operation, expected", OTHER_MAPPINGS)
async def test_remaining_platform_operations_use_existing_wire_contract(platform, operation, expected):
    import json
    from urllib.parse import parse_qs

    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"data": {"ok": True}})

    params = {}
    if platform == "xiaohongshu":
        params = {
            "start_time": "2026-09-09 00:00:00",
            "end_time": "2026-09-10 00:00:00",
            "order_id": "order-1",
            "refund_id": "refund-1",
        }
    elif platform == "weixin_store" and operation == "get_order_list":
        params = {"create_time_range": {"start_time": 1788883200, "end_time": 1788969600}, "page_size": 20}
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        client = sdk().create_platform_client(platform, platform_credentials(platform), http_client=http)
        assert await client.call(operation, params) == {"data": {"ok": True}}
        assert len(requests) == 1
        request = requests[0]
        if platform == "pinduoduo":
            body = parse_qs(request.content.decode())
            assert body["type"] == [expected]
            assert body["access_token"] == ["shop-token"]
            assert body["sign"]
        elif platform == "jd":
            assert request.url.params["method"] == expected
            assert request.url.params["access_token"] == "shop-token"
        elif platform == "xiaohongshu":
            body = json.loads(request.content)
            assert body["method"] == expected
            assert body["accessToken"] == "shop-token"
        else:
            assert request.url.path == expected
            if platform == "oceanengine":
                assert request.headers["Access-Token"] == "shop-token"
            else:
                assert request.url.params["access_token"] == "shop-token"
        assert client.operations[operation].live_verified is False
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "platform, operation",
    [("xiaohongshu", "get_shop_info"), ("doudian", "get_shop_info"), ("oceanengine", "get_order_list")],
)
async def test_explicitly_unsupported_operations_have_metadata_and_never_send(platform, operation):
    def forbidden(request):
        pytest.fail("unsupported operation reached HTTP")

    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as http:
        client = sdk().create_platform_client(platform, platform_credentials(platform), http_client=http)
        assert client.operations[operation].supported is False
        assert client.operations[operation].reason
        with pytest.raises(ValueError, match="Unsupported"):
            await client.call(operation, {})
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "platform", ["doudian", "taobao", "jd", "kuaishou", "xiaohongshu", "weixin_store", "oceanengine"]
)
async def test_every_platform_keeps_two_authorizations_isolated_on_the_wire(platform):
    import json
    from urllib.parse import parse_qs

    entered = asyncio.Event()
    tokens = []

    async def handle(request):
        if platform == "taobao":
            token = request.url.params["session"]
        elif platform == "pinduoduo":
            token = parse_qs(request.content.decode())["access_token"][0]
        elif platform == "xiaohongshu":
            token = json.loads(request.content)["accessToken"]
        elif platform == "oceanengine":
            token = request.headers["Access-Token"]
        else:
            token = request.url.params["access_token"]
        tokens.append(token)
        if len(tokens) == 2:
            entered.set()
        await asyncio.wait_for(entered.wait(), 1)
        if platform == "taobao":
            return httpx.Response(
                200, json={"trade_fullinfo_get_response": {"trade": {"tid": 123, "token_used": token}}}
            )
        return httpx.Response(
            200,
            json={
                "data": (
                    {"shop_order_detail": {"order_id": "order", "token_used": token}}
                    if platform == "doudian"
                    else {"token_used": token}
                )
            },
        )

    first_credentials = platform_credentials(platform)
    second_credentials = {**first_credentials, "access_token": "second-shop-token"}
    operation = "get_advertiser_info" if platform == "oceanengine" else "get_order_detail"
    params = (
        {"order_id": "order"}
        if platform == "xiaohongshu"
        else ({"shop_order_id": "order"} if platform == "doudian" else {})
    )
    if platform == "taobao":
        params = {"fields": "tid", "tid": "123"}
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        async with sdk().create_platform_client(platform, first_credentials, http_client=http) as first:
            async with sdk().create_platform_client(platform, second_credentials, http_client=http) as second:
                first_credentials["access_token"] = "mutated"
                results = await asyncio.gather(first.call(operation, params), second.call(operation, params))
                assert set(tokens) == {"shop-token", "second-shop-token"}
                if platform == "doudian":
                    key_results = [r["shop_order_detail"] for r in results]
                elif platform == "taobao":
                    key_results = [r["trade_fullinfo_get_response"]["trade"] for r in results]
                else:
                    key_results = [r["data"] for r in results]
                assert [r["token_used"] for r in key_results] == ["shop-token", "second-shop-token"]


def test_factory_imports_no_mcp_server_and_reads_no_environment():
    import subprocess
    import sys

    script = """
import os
import sys
from shared.platform_clients import create_platform_client

def forbidden(*args, **kwargs):
    raise AssertionError("SDK read process environment")

os.environ.get = forbidden
for platform in ("doudian", "taobao", "jd", "pinduoduo", "kuaishou", "xiaohongshu", "weixin_store", "oceanengine"):
    creds = {"app_key": "app", "app_secret": "secret", "access_token": "token"}
    if platform == "doudian":
        creds["shop_id"] = "shop"
    if platform == "kuaishou":
        creds["sign_secret"] = "sign"
    client = create_platform_client(platform, creds)
    assert client.platform == platform
assert not any(name.startswith("servers.") and name.endswith(".server") for name in sys.modules)
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
async def test_owned_http_transport_is_closed_and_context_cannot_reopen(monkeypatch):
    from shared import cn_commerce_base

    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})))
    monkeypatch.setattr(cn_commerce_base.httpx, "AsyncClient", lambda **kwargs: http)
    client = sdk().create_platform_client("weixin_store", {"access_token": "token"})
    async with client:
        assert await client.call("get_shop_info", {}) == {}
        assert not http.is_closed
    assert http.is_closed
    await client.close()
    with pytest.raises(RuntimeError, match="closed"):
        async with client:
            pytest.fail("closed client reopened")


@pytest.mark.parametrize(
    "platform, credentials",
    [
        ("unknown", {}),
        ("taobao", {}),
        ("doudian", {"app_key": "app", "app_secret": "secret", "access_token": "token"}),
        ("taobao", {"app_key": "app", "app_secret": "secret", "access_token": ""}),
        ("taobao", {"app_key": "app", "app_secret": "secret", "access_token": "token", "url": "https://other.example"}),
        ("weixin_store", {"access_token": "token", "token_mode": "managed"}),
        ("weixin_store", {"access_token": "token", "app_secret": 123}),
    ],
)
def test_credentials_are_explicit_and_unknown_fields_rejected(platform, credentials, monkeypatch):
    monkeypatch.setenv("TAOBAO_ACCESS_TOKEN", "environment-token-cannot-fill-missing")
    with pytest.raises(ValueError):
        sdk().create_platform_client(platform, credentials)


@pytest.mark.asyncio
async def test_catalogue_is_immutable_and_reports_contract_gaps():
    from dataclasses import FrozenInstanceError

    client = sdk().create_platform_client("jd", platform_credentials("jd"))
    assert client.operations["get_order_list"].contract_status == "unverified"
    with pytest.raises(TypeError):
        client.operations["arbitrary_write"] = client.operations["get_order_list"]
    with pytest.raises(FrozenInstanceError):
        client.operations["get_order_list"].endpoint = "jd.write"
    await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "platform, operation, expected",
    [
        ("doudian", "get_order_list", "order.searchList"),
        ("doudian", "get_order_detail", "order.orderDetail"),
        ("doudian", "get_refund_list", "afterSale.List"),
        ("doudian", "get_refund_detail", "afterSale.Detail"),
        ("taobao", "get_order_list", "taobao.trades.sold.get"),
        ("taobao", "get_increment_orders", "taobao.trades.sold.increment.get"),
        ("taobao", "get_order_detail", "taobao.trade.fullinfo.get"),
        ("taobao", "get_refund_list", "taobao.refunds.receive.get"),
        ("taobao", "get_refund_detail", "taobao.refund.get"),
        ("taobao", "get_shop_info", "taobao.shop.get"),
    ],
)
async def test_doudian_and_top_read_mappings_use_existing_signed_methods(platform, operation, expected):
    calls = []
    params = {}
    response = {"ok": True}
    if platform == "doudian":
        if operation == "get_order_list":
            params, response = {"page": 0, "size": 20}, {"shop_order_list": [], "total": 0}
        elif operation == "get_order_detail":
            params, response = {"shop_order_id": "order"}, {"shop_order_detail": {"order_id": "order"}}
        elif operation == "get_refund_list":
            params, response = {"page": 0, "size": 20}, {"items": [], "total": 0, "has_more": False}
        else:
            params, response = {"after_sale_id": "refund"}, {
                "process_info": {"after_sale_info": {"after_sale_id": "refund"}}
            }
    else:
        refund = operation in {"get_refund_list", "get_refund_detail"}
        params = {"fields": "refund_id" if refund else "tid"}
        if operation == "get_order_detail":
            params["tid"] = "123"
            body = {"trade": {"tid": 123}}
        elif operation == "get_refund_detail":
            params["refund_id"] = "123"
            body = {"refund": {"refund_id": "123"}}
        else:
            body = {"total_results": 0, "refunds" if refund else "trades": {"refund" if refund else "trade": []}}
            if operation == "get_increment_orders":
                params.update(start_modified="2026-09-10 00:00:00", end_modified="2026-09-10 01:00:00")
        response = {expected.removeprefix("taobao.").replace(".", "_") + "_response": body}

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={"data": response} if platform == "doudian" else response)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        async with sdk().create_platform_client(platform, platform_credentials(platform), http_client=http) as client:
            result = await client.call(operation, params)
            assert result == response
            assert calls[0].url.params["method"] == expected
            assert calls[0].url.params["sign"]


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["type", "client_id", "sign", "accessToken", "app-key", "method"])
async def test_pdd_business_fields_cannot_override_form_credentials_or_read_route(field):
    def forbidden(request):
        pytest.fail("protocol override reached HTTP")

    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as http:
        async with sdk().create_platform_client(
            "pinduoduo", platform_credentials("pinduoduo"), http_client=http
        ) as client:
            with pytest.raises(ValueError):
                await client.call("get_order_list", {field: "override"})
