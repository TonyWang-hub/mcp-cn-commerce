"""Five current Kuaishou official read contracts, intercepted at the wire."""

import asyncio
import base64
import hashlib
import hmac
import json

import httpx
import pytest

from servers.kuaishou.client import KuaishouMCP
from shared.cn_commerce_base import CommerceAPIError
from shared.platform_clients import create_platform_client, operation_catalog

METHODS = {
    "get_order_list": "open.order.cursor.list",
    "get_order_detail": "open.order.detail",
    "get_refund_list": "open.seller.order.refund.pcursor.list",
    "get_refund_detail": "open.seller.order.refund.detail",
    "get_shop_info": "open.shop.info.get",
}
BEGIN = 1788192000000
END = BEGIN + 3600000


def params(operation):
    if operation == "get_order_list":
        return {"orderViewStatus": 1, "pageSize": 20, "beginTime": BEGIN, "endTime": END, "cursor": "", "queryType": 2}
    if operation == "get_refund_list":
        return {
            "type": 9,
            "pageSize": 20,
            "beginTime": BEGIN,
            "endTime": END,
            "pcursor": "",
            "currentPage": 1,
            "queryType": 2,
            "option": {"needExchange": True},
        }
    if operation == "get_order_detail":
        return {"oid": 123}
    if operation == "get_refund_detail":
        return {"refundId": 456}
    return {}


def payload(operation):
    if operation == "get_order_list":
        data = {
            "cursor": "nomore",
            "orderList": [{"orderBaseInfo": {"oid": 123, "sellerOpenId": "seller-open-1", "totalFee": 1234}}],
        }
    elif operation == "get_refund_list":
        data = {
            "pcursor": "nomore",
            "refundOrderInfoList": [{"refundId": 456, "oid": 123, "sellerId": 789}],
            "totalSize": 1,
        }
    elif operation == "get_order_detail":
        data = {"orderBaseInfo": {"oid": 123, "sellerOpenId": "seller-open-1", "totalFee": 1234}}
    elif operation == "get_refund_detail":
        data = {"refundId": 456, "oid": 123, "sellerId": 789, "status": 60, "handlingWay": 10, "refundFee": 890}
    else:
        data = {"shopName": "示例店", "shopType": 1}
    return {"result": 1, "data": data}


def credentials(suffix="1"):
    return {
        "app_key": "app-" + suffix,
        "app_secret": "oauth-secret-" + suffix,
        "sign_secret": "sign-secret-" + suffix,
        "access_token": "token-" + suffix,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", METHODS)
async def test_current_kuaishou_method_signing_and_business_envelope(operation):
    requests = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: (requests.append(r), httpx.Response(200, json=payload(operation)))[1])
    ) as http:
        client = create_platform_client("kuaishou", credentials(), http_client=http)
        assert await client.call(operation, params(operation)) == payload(operation)
        r = requests[0]
        assert r.method == "GET" and not r.content
        assert r.url.host == "openapi.kwaixiaodian.com"
        assert r.url.path == "/" + METHODS[operation].replace(".", "/")
        query = dict(r.url.params)
        assert set(query) == {"appkey", "method", "version", "timestamp", "access_token", "signMethod", "param", "sign"}
        assert query["appkey"] == "app-1" and query["access_token"] == "token-1"
        assert query["version"] == "1" and query["signMethod"] == "MD5"
        assert len(query["timestamp"]) == 13
        assert json.loads(query["param"]) == params(operation)
        raw = "&".join(k + "=" + v for k, v in sorted(query.items()) if k != "sign") + "&signSecret=sign-secret-1"
        assert query["sign"] == hashlib.md5(raw.encode()).hexdigest()
        assert "oauth-secret" not in str(r.url)
        assert operation_catalog("kuaishou")[operation].contract_status == "documented"
        await client.close()
        assert not http.is_closed


def test_official_hmac_signature_is_base64_and_includes_signsecret_suffix():
    client = KuaishouMCP(**credentials())
    query = {"appkey": "app-1", "method": "open.shop.info.get", "param": "{}", "signMethod": "HMAC_SHA256"}
    raw = "appkey=app-1&method=open.shop.info.get&param={}&signMethod=HMAC_SHA256&signSecret=sign-secret-1"
    expected = base64.b64encode(hmac.new(b"sign-secret-1", raw.encode(), hashlib.sha256).digest()).decode()
    assert client._sign(query) == expected


@pytest.mark.asyncio
async def test_two_authorizations_continue_opaque_refund_cursors_without_mixing_signsecret():
    requests = []

    async def respond(request):
        query = dict(request.url.params)
        business = json.loads(query["param"])
        requests.append((query, business))
        await asyncio.sleep(0)
        data = payload("get_refund_list")["data"]
        data["pcursor"] = "next_漢字" if business["pcursor"] == "" else "nomore"
        return httpx.Response(200, json={"result": 1, "data": data})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        clients = [create_platform_client("kuaishou", credentials(str(i)), http_client=http) for i in [1, 2]]

        async def collect(client):
            first = await client.call("get_refund_list", params("get_refund_list"))
            second = await client.call(
                "get_refund_list", {**params("get_refund_list"), "pcursor": first["data"]["pcursor"], "currentPage": 2}
            )
            assert second["data"]["pcursor"] == "nomore"

        await asyncio.gather(*(collect(c) for c in clients))
        for query, business in requests:
            suffix = query["appkey"][-1]
            assert query["access_token"] == "token-" + suffix
            raw = (
                "&".join(k + "=" + v for k, v in sorted(query.items()) if k != "sign")
                + "&signSecret=sign-secret-"
                + suffix
            )
            assert query["sign"] == hashlib.md5(raw.encode()).hexdigest()
            assert business["beginTime"] == BEGIN and business["endTime"] == END
        for client in clients:
            await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,change",
    [
        ("get_order_list", {"cursor": None}),
        ("get_order_list", {"pageSize": 51}),
        ("get_order_list", {"endTime": BEGIN + 8 * 86400000}),
        ("get_order_list", {"queryType": 3}),
        ("get_order_list", {"orderViewStatus": 30}),
        ("get_refund_list", {"pcursor": None}),
        ("get_refund_list", {"endTime": BEGIN + 2 * 86400000}),
        ("get_refund_list", {"type": "open.write"}),
        ("get_refund_list", {"currentPage": 0}),
        ("get_refund_list", {"pageSize": 101}),
        ("get_refund_list", {"option": {"access_token": "other"}}),
        ("get_order_detail", {"oid": "KS123"}),
        ("get_refund_detail", {"refundId": True}),
        ("get_shop_info", {"sellerId": 999}),
    ],
)
async def test_invalid_native_business_contract_rejects_before_network(operation, change):
    requests = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: (requests.append(r), httpx.Response(200, json={"result": 1, "data": {}}))[1]
        )
    ) as http:
        client = KuaishouMCP(**credentials(), http_client=http)
        with pytest.raises(ValueError, match="Kuaishou"):
            await client._call(METHODS[operation], {**params(operation), **change})
        assert not requests
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        {"result": 1001, "error_msg": "no permission"},
        {"code": "1001", "msg": "gateway failure"},
        {"result": True, "data": {}},
        {"result": 1, "data": {}},
        {"result": 1, "data": {"orderList": [], "cursor": None}},
    ],
)
async def test_business_errors_and_missing_cursor_are_not_empty_success(bad):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=bad))) as http:
        client = KuaishouMCP(**credentials(), http_client=http)
        with pytest.raises((ValueError, CommerceAPIError)):
            await client._call(METHODS["get_order_list"], params("get_order_list"))
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", METHODS)
async def test_cli_uses_numeric_ids_millisecond_windows_and_real_cursor(monkeypatch, operation):
    from servers.kuaishou import server

    requests = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: (requests.append(r), httpx.Response(200, json=payload(operation)))[1])
    ) as http:
        client = KuaishouMCP(**credentials(), http_client=http)
        monkeypatch.setattr(server, "ks", client)
        if operation in {"get_order_list", "get_refund_list"}:
            args = {"start_time": "2026-09-01T00:00:00+08:00", "end_time": "2026-09-01T01:00:00+08:00"}
        elif operation == "get_order_detail":
            args = {"order_id": "123"}
        elif operation == "get_refund_detail":
            args = {"refund_id": "456"}
        else:
            args = {}
        assert json.loads(await getattr(server, operation)(**args)) == payload(operation)
        assert requests[0].url.params["method"] == METHODS[operation]
        assert json.loads(requests[0].url.params["param"]).get("currentPage", 1) == 1
        await client.close()
