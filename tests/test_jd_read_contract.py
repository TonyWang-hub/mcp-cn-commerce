"""Current JOS read protocol, independent of legacy CLI fixtures."""

import asyncio
import hashlib
import json
from urllib.parse import parse_qs

import httpx
import pytest

from servers.jd.client import JDMCP
from shared.cn_commerce_base import CommerceAPIError
from shared.platform_clients import create_platform_client, operation_catalog

METHODS = {
    "get_order_list": "jingdong.pop.order.search",
    "get_order_detail": "jingdong.pop.order.get",
    "get_shop_info": "jingdong.vender.shop.query",
}


def query(operation):
    if operation == "get_shop_info":
        return {}
    result = {"source_id": "JOS", "optional_fields": "orderId,venderId,actualPay,modified"}
    if operation == "get_order_detail":
        return {**result, "order_id": 123}
    return {
        **result,
        "start_date": "2026-09-01 00:00:00",
        "end_date": "2026-09-02 00:00:00",
        "order_state": "ALL",
        "page": "1",
        "page_size": "2",
        "dateType": 0,
        "sortType": 2,
    }


def payload(operation, rows=None, total=1):
    order = {"orderId": "123", "venderId": "456", "actualPay": "12.30", "modified": "2026-09-01 12:00:00"}
    if operation == "get_order_list":
        body = {
            "searchorderinfo_result": {
                "apiResult": {"success": True, "numberCode": 0},
                "orderTotal": total,
                "orderInfoList": [order] if rows is None else rows,
            }
        }
    elif operation == "get_order_detail":
        body = {"orderDetailInfo": {"apiResult": {"success": "true", "numberCode": "0"}, "orderInfo": order}}
    else:
        body = {"shop_jos_result": {"shop_id": "789", "vender_id": "456", "shop_name": "test shop"}}
    return {METHODS[operation].replace(".", "_") + "_responce": body}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", METHODS)
async def test_current_read_protocol_uses_form_signed_flat_business_json(operation):
    requests = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: (requests.append(r), httpx.Response(200, json=payload(operation)))[1])
    ) as http:
        client = create_platform_client(
            "jd", {"app_key": "app", "app_secret": "secret", "access_token": "token"}, http_client=http
        )
        assert await client.call(operation, query(operation)) == payload(operation)
        r = requests[0]
        assert str(r.url) == "https://api.jd.com/routerjson"
        assert r.method == "POST" and r.headers["content-type"].startswith("application/x-www-form-urlencoded")
        form = {key: values[0] for key, values in parse_qs(r.content.decode()).items()}
        assert set(form) == {"method", "app_key", "access_token", "timestamp", "v", "360buy_param_json", "sign"}
        assert form["method"] == METHODS[operation]
        assert json.loads(form["360buy_param_json"]) == query(operation)
        assert "paramOrderJSFQuery" not in form["360buy_param_json"]
        assert "venderId" not in json.loads(form["360buy_param_json"])
        raw = "secret" + "".join(key + value for key, value in sorted(form.items()) if key != "sign") + "secret"
        assert form["sign"] == hashlib.md5(raw.encode()).hexdigest().upper()
        assert len(form["timestamp"]) == 19
        assert operation_catalog("jd")[operation].contract_status == "documented"
        assert operation_catalog("jd")[operation].live_verified is False
        await client.close()
        assert not http.is_closed


@pytest.mark.asyncio
async def test_two_jd_authorizations_and_pages_keep_credentials_and_window():
    requests = []

    async def respond(request):
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        business = json.loads(form["360buy_param_json"])
        requests.append((form, business))
        await asyncio.sleep(0)
        page = int(business["page"])
        return httpx.Response(200, json=payload("get_order_list", rows=[{"orderId": str(page)}], total=2))

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        clients = [
            create_platform_client(
                "jd",
                {"app_key": f"app-{i}", "app_secret": f"secret-{i}", "access_token": f"token-{i}"},
                http_client=http,
            )
            for i in [1, 2]
        ]

        async def collect(client):
            rows = []
            for page in [1, 2]:
                result = await client.call(
                    "get_order_list", {**query("get_order_list"), "page": str(page), "page_size": "1"}
                )
                data = result["jingdong_pop_order_search_responce"]["searchorderinfo_result"]
                assert data["orderTotal"] == 2
                rows.extend(data["orderInfoList"])
            return rows

        assert await asyncio.gather(*(collect(c) for c in clients)) == [[{"orderId": "1"}, {"orderId": "2"}]] * 2
        for form, business in requests:
            suffix = form["app_key"][-1]
            assert form["access_token"] == f"token-{suffix}"
            raw = (
                f"secret-{suffix}" + "".join(k + v for k, v in sorted(form.items()) if k != "sign") + f"secret-{suffix}"
            )
            assert form["sign"] == hashlib.md5(raw.encode()).hexdigest().upper()
            assert business["start_date"] == "2026-09-01 00:00:00"
            assert business["end_date"] == "2026-09-02 00:00:00"
        for client in clients:
            await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"source_id": ""},
        {"source_id": None},
        {"optional_fields": ""},
        {"page": "0"},
        {"page": 1},
        {"page_size": "101"},
        {"end_date": "2026-10-02 00:00:00"},
        {"end_date": "2026-08-31 00:00:00"},
        {"start_date": "2026-09-01T00:00:00Z"},
        {"venderId": 999},
        {"paramOrderJSFQuery": {}},
        {"unknown_field": "x"},
        {"order_state": "BOGUS"},
        {"dateType": True},
    ],
)
async def test_invalid_or_injected_order_fields_fail_before_http(change):
    requests = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: (requests.append(r), httpx.Response(200, json={}))[1])
    ) as http:
        client = JDMCP(app_key="app", app_secret="secret", access_token="token", http_client=http)
        with pytest.raises(ValueError, match="JD POP"):
            await client._call(METHODS["get_order_list"], {**query("get_order_list"), **change})
        assert not requests
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        {"error_response": {"code": 7, "msg": "invalid token"}},
        {"code": "10500001", "errorMessage": "wrong merchant"},
        {"jingdong_pop_order_search_responce": {"code": "103", "zh_desc": "invalid app"}},
        {
            "jingdong_pop_order_search_responce": {
                "searchorderinfo_result": {
                    "apiResult": {"success": False, "numberCode": "10100021", "chineseErrCode": "invalid state"}
                }
            }
        },
    ],
)
async def test_http_success_does_not_hide_official_error_envelopes(bad):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=bad))) as http:
        client = JDMCP(app_key="app", app_secret="secret", access_token="token", http_client=http)
        with pytest.raises(CommerceAPIError):
            await client._call(METHODS["get_order_list"], query("get_order_list"))
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"jingdong_pop_order_search_responce": {}},
        {
            "jingdong_pop_order_search_responce": {
                "searchorderinfo_result": {"apiResult": {"success": "false"}, "orderTotal": 0, "orderInfoList": []}
            }
        },
        {
            "jingdong_pop_order_search_responce": {
                "searchorderinfo_result": {"apiResult": {"success": "yes"}, "orderTotal": 0, "orderInfoList": []}
            }
        },
        {
            "jingdong_pop_order_search_responce": {
                "searchorderinfo_result": {"apiResult": {"success": True}, "orderInfoList": []}
            }
        },
    ],
)
async def test_malformed_or_negative_success_cannot_be_empty_success(bad):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=bad))) as http:
        client = JDMCP(app_key="app", app_secret="secret", access_token="token", http_client=http)
        with pytest.raises((ValueError, CommerceAPIError)):
            await client._call(METHODS["get_order_list"], query("get_order_list"))
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", METHODS)
async def test_cli_read_tools_reach_the_current_signed_contract(monkeypatch, operation):
    from servers.jd import server

    requests = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: (requests.append(r), httpx.Response(200, json=payload(operation)))[1])
    ) as http:
        client = JDMCP(app_key="app", app_secret="secret", access_token="token", http_client=http)
        monkeypatch.setattr(server, "jd", client)
        params = {"source_id": "JOS", "optional_fields": "orderId,venderId,actualPay,modified"}
        if operation == "get_order_list":
            params.update(start_time="2026-09-01 00:00:00", end_time="2026-09-02 00:00:00", page_size=2)
        elif operation == "get_order_detail":
            params.update(order_id="123")
        else:
            params = {}
        assert json.loads(await getattr(server, operation)(**params)) == payload(operation)
        assert len(requests) == 1
        assert parse_qs(requests[0].content.decode())["method"] == [METHODS[operation]]
        await client.close()
