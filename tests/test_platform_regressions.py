"""Adapter contracts against real HTTPX requests, without live credentials.

These tests verify local transport/authentication behavior. They do not certify
that legacy business endpoint paths are still enabled for a merchant account.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import importlib
import json
from urllib.parse import parse_qs

import httpx
import pytest

from shared.cn_commerce_base import CommerceAPIError, ConfigValidationError


def module(platform):
    return importlib.import_module(f"servers.{platform}.server")


def make_client(platform):
    names = {
        "doudian": "DouDianClient",
        "jd": "JDMCP",
        "kuaishou": "KuaishouMCP",
        "oceanengine": "OceanEngine",
        "pinduoduo": "PinduoduoMCP",
        "taobao": "TaobaoMCP",
        "weixin_store": "WeixinStoreMCP",
        "xiaohongshu": "XiaohongshuMCP",
    }
    kwargs = dict(app_key="test-key", app_secret="test-secret", access_token="test-token")
    if platform == "kuaishou":
        kwargs["sign_secret"] = "different-signing-secret"
    if platform == "doudian":
        kwargs["shop_id"] = "test-shop"
    return getattr(module(platform), names[platform])(**kwargs)


async def read(client, platform, params=None):
    params = params or {"ids": [1, 2], "filter": {"active": True}}
    if platform == "doudian":
        return await client.request("order/list", params)
    if platform in {"jd", "taobao", "pinduoduo"}:
        return await client._call("test.order.get", params)
    if platform == "kuaishou":
        return await client._call("/test/order/get", params)
    if platform == "xiaohongshu":
        return await client._call("GET", "/api/order/detail", {"order_id": "1"})
    return await client._request("GET", "/test/order/get", params=params)


PLATFORMS = ["doudian", "jd", "kuaishou", "oceanengine", "pinduoduo", "taobao", "weixin_store", "xiaohongshu"]


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", PLATFORMS)
async def test_all_adapters_share_transport_metrics_and_trace(platform):
    client = make_client(platform)
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200 if len(requests) == 1 else 401, json={"code": 10000, "data": {}} if platform == "doudian" else {}
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    client._client = http
    try:
        await read(client, platform)
        try:
            await read(client, platform)
        except httpx.HTTPStatusError:
            pass
        assert len(requests) == 2
        assert client._client is http
        assert client.get_metrics_summary()["global"]["total_requests"] == 2
        assert client.get_metrics_summary()["global"]["total_errors"] == 1
        assert client.get_trace_summary()["span_count"] > 0
    finally:
        await client.close()
    assert http.is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "platform,global_name",
    [
        ("doudian", "_client"),
        ("jd", "jd"),
        ("kuaishou", "ks"),
        ("oceanengine", "_client"),
        ("pinduoduo", "pdd"),
        ("taobao", "taobao"),
        ("weixin_store", "_wx"),
        ("xiaohongshu", "xhs"),
    ],
)
async def test_lifespan_closes_pool_on_error(platform, global_name, monkeypatch):
    server_module = module(platform)
    client = make_client(platform)
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={})))
    client._client = http
    monkeypatch.setattr(server_module, global_name, client)
    with pytest.raises(RuntimeError):
        async with server_module._lifespan(None):
            raise RuntimeError("server stopped")
    assert http.is_closed


def test_kuaishou_factory_keeps_distinct_signing_secret(monkeypatch):
    for name, value in {
        "APP_KEY": "key",
        "APP_SECRET": "secret",
        "SIGN_SECRET": "signing",
        "ACCESS_TOKEN": "token",
    }.items():
        monkeypatch.setenv(f"KUAISHOU_{name}", value)
    client = module("kuaishou")._create_kuaishou_client()
    assert client.sign_secret == "signing"
    # Official SDK canonical vector: "a=1&signSecret=signing".
    assert client._sign({"a": 1}) == "fc86e42603d78b3822e19fa23c91173c"


@pytest.mark.asyncio
async def test_kuaishou_missing_signing_secret_fails_before_network():
    client = make_client("kuaishou")
    client.sign_secret = ""
    with pytest.raises(ConfigValidationError, match="KUAISHOU_SIGN_SECRET"):
        await client._call("/test")


@pytest.mark.asyncio
async def test_oceanengine_auth_and_array_query_on_the_wire(monkeypatch):
    server_module = module("oceanengine")
    monkeypatch.setenv("OCEANENGINE_ACCESS_TOKEN", "header-token")
    monkeypatch.setattr(server_module, "_client", None)
    client = server_module._get_client()
    assert client is server_module._get_client()
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"code": 0, "data": {"list": []}})

    client._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        result = await server_module.get_advertiser_info("1,2")
        assert isinstance(result, str)
        assert json.loads(result)["code"] == 0
        request = requests[0]
        assert request.url.host == "ad.oceanengine.com"
        assert request.headers["Access-Token"] == "header-token"
        assert request.url.params.get_list("advertiser_ids") == ["[1,2]"]
        assert "access_token" not in request.url.params
        assert "sign" not in request.url.params
        assert server_module._get_client().get_metrics_summary()["global"]["total_requests"] == 1
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("with_app", [False, True])
async def test_weixin_explicit_token_is_static_even_with_app_credentials(with_app):
    client = module("weixin_store").WeixinStoreMCP(
        app_key="app" if with_app else "",
        app_secret="secret" if with_app else "",
        access_token="static-token",
    )
    assert client.token_mode == "static"
    assert await client._ensure_token() == "static-token"
    assert client._client is None


def test_weixin_factory_accepts_token_only(monkeypatch):
    for name in ("WX_APP_ID", "WX_APP_SECRET", "WX_TOKEN_MODE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("WX_ACCESS_TOKEN", "provided-token")
    assert module("weixin_store")._create_weixin_store_client().token_mode == "static"


@pytest.mark.asyncio
async def test_weixin_concurrent_managed_refresh_fetches_one_token():
    client = module("weixin_store").WeixinStoreMCP(app_key="app", app_secret="secret")
    requests = []

    async def respond(request):
        requests.append(request)
        await asyncio.sleep(0)
        return httpx.Response(200, json={"access_token": "managed-token", "expires_in": 7200})

    client._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        tokens = await asyncio.gather(*(client._ensure_token() for _ in range(20)))
        assert tokens == ["managed-token"] * 20
        assert len(requests) == 1
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["pinduoduo"])
async def test_signed_collection_values_are_exactly_the_sent_values(platform):
    client = make_client(platform)
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={})

    client._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        await read(client, platform, {"ids": [1, 2], "filter": {"b": 2, "a": 1}})
        request = requests[0]
        values = parse_qs(request.content.decode()) if platform == "pinduoduo" else dict(request.url.params)
        params = {k: v[0] if isinstance(v, list) else v for k, v in values.items()}
        assert params["ids"] == "[1,2]"
        assert params["filter"] == '{"a":1,"b":2}'
        assert params["sign"] == client._sign(params)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_weixin_managed_invalid_token_refreshes_once():
    client = module("weixin_store").WeixinStoreMCP(app_key="app", app_secret="secret")
    tokens = []
    business_tokens = []

    def respond(request):
        if request.url.path == "/cgi-bin/token":
            token = f"managed-{len(tokens)}"
            tokens.append(token)
            return httpx.Response(200, json={"access_token": token, "expires_in": 7200})
        token = request.url.params["access_token"]
        business_tokens.append(token)
        return httpx.Response(200, json={"errcode": 42001, "errmsg": "expired"} if token == "managed-0" else {})

    client._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        assert await client._request("POST", "/test/order/get", data={"id": 1}) == {}
        assert business_tokens == ["managed-0", "managed-1"]
        assert len(tokens) == 2
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_doudian_official_signing_covers_exact_body_and_common_fields():
    client = make_client("doudian")
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"code": 10000, "data": {}})

    client._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        await client.request("product/list", {"z": 1.0, "a": {"z": False, "a": [1, "汉<>"]}})
        request = requests[0]
        body = request.content.decode()
        assert body == '{"a":{"a":[1,"汉<>"],"z":false},"z":1}'
        query = request.url.params
        assert query["method"] == "product.list"
        assert query["sign_method"] == "hmac-sha256"
        assert "param_json" not in query
        raw = (
            "test-secretapp_keytest-keymethodproduct.listparam_json"
            + body
            + "timestamp"
            + query["timestamp"]
            + "v2test-secret"
        )
        assert query["sign"] == hmac.new(b"test-secret", raw.encode(), hashlib.sha256).hexdigest()
    finally:
        await client.close()


def test_doudian_official_published_example_vector():
    # Published demonstration values from the official article 130 (not live credentials).
    client = module("doudian").DouDianClient(
        app_key="6844048284663924231",
        app_secret="749698a6-fcb3-4358-b241-ec1d93cf9c1f",
        access_token="unused",
    )
    assert (
        client._sign(
            {
                "app_key": client.app_key,
                "method": "product.list",
                "param_json": '{"page":"0","size":"20"}',
                "timestamp": "2020-07-05 22:33:59",
                "v": "2",
            }
        )
        == "a84fc5747114e63196565192a19f80d9d78819b8c8f5940eeb282bf78260901d"
    )


def test_xiaohongshu_order_and_refund_time_units_match_official_schemas():
    adapter = module("xiaohongshu").XiaohongshuMCP
    params = {"start_time": "2024-01-01 00:00:00", "end_time": "2024-01-01 23:59:59", "page": "2", "page_size": "20"}
    method, order = adapter._adapt_params("/api/order/list", params)
    assert method == "order.getOrderList"
    assert order == {"startTime": 1704038400, "endTime": 1704124799, "timeType": 1, "pageNo": 2, "pageSize": 20}
    method, refund = adapter._adapt_params("/api/refund/list", params)
    assert method == "afterSale.listAfterSaleInfos"
    assert refund["startTime"] == 1704038400000
    assert refund["endTime"] == 1704124799000


@pytest.mark.parametrize("path", ["/api/review/list", "/api/shop/info", "/api/promotion/list", "/api/coupon/list"])
def test_xiaohongshu_unverified_tools_fail_explicitly(path):
    with pytest.raises(CommerceAPIError, match="Unsupported Xiaohongshu tool") as caught:
        module("xiaohongshu").XiaohongshuMCP._adapt_params(path, {})
    assert caught.value.code == -2


def test_xiaohongshu_creation_time_window_does_not_silently_truncate():
    with pytest.raises(ValueError, match="24 hours"):
        module("xiaohongshu").XiaohongshuMCP._adapt_params(
            "/api/order/list",
            {
                "start_time": "2024-01-01",
                "end_time": "2024-02-01",
            },
        )


@pytest.mark.asyncio
async def test_xiaohongshu_official_oauth_wire_contract():
    client = make_client("xiaohongshu")
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"success": True, "error_code": 0, "data": {}})

    client._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        await client._call("GET", "/api/product/list", {"page": "2", "page_size": "20"})
        request = requests[0]
        payload = json.loads(request.content)
        assert str(request.url) == "https://ark.xiaohongshu.com/ark/open_api/v3/common_controller"
        assert request.method == "POST"
        assert request.headers["Content-Type"] == "application/json;charset=utf-8"
        assert payload["method"] == "product.searchItemList"
        assert payload["appId"] == "test-key"
        assert payload["accessToken"] == "test-token"
        assert payload["searchParam"] == {}
        assert payload["pageNo"] == 2 and payload["pageSize"] == 20
        assert "param_json" not in payload
        raw = f"product.searchItemList?appId=test-key&timestamp={payload['timestamp']}&version=2.0test-secret"
        assert payload["sign"] == hashlib.md5(raw.encode()).hexdigest()
        assert client._sign({**payload, "accessToken": "another", "pageNo": 99}) == payload["sign"]
    finally:
        await client.close()
