"""Wire-level contract assertions for 小红书 (Xiaohongshu) 电商开放平台.

These tests read the exact bytes the server would have put on the wire and check
them against the platform's documented contract: the single gateway URL, POST
only, every parameter in the JSON body, the camelCase parameter names, the
10-digit second ``timestamp``, and a signature that covers *only* the four
system parameters and is lowercase 32-hex.

They sit below the boundary the unit tests mock (``xhs._call``), which is exactly
where this platform's defects hid: a test that stubs ``_call`` can never notice
that the request went to a fabricated REST path over GET with the parameters in
a query string.

每条期望的官方出处记录在 ``docs/api-contracts/xiaohongshu.md``。
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
from typing import Any

import pytest

from tests.contract.conftest import CapturedRequest

os.environ.setdefault("XHS_CLIENT_ID", "test_client_id")
os.environ.setdefault("XHS_CLIENT_SECRET", "test_client_secret")
os.environ.setdefault("XHS_ACCESS_TOKEN", "test_token")

from servers.xiaohongshu.server import (  # noqa: E402
    API_VERSION,
    CONTENT_TYPE,
    GATEWAY_URL,
    SIGNED_PARAMS,
    XiaohongshuMCP,
    get_inventory,
    get_monthly_statement_url,
    get_order_detail,
    get_order_list,
    get_product_list,
    get_refund_list,
    get_settlement_transactions,
)
from shared.cn_commerce_base import CommerceAPIError  # noqa: E402

APP_ID = "wire_app_id"
APP_SECRET = "wire_app_secret"
ACCESS_TOKEN = "wire_access_token"

#: UNIX 秒 = 10 位数字的字符串。写成字面 pattern 而不是从代码推导：要钉的是官方
#: 文档的形状（"UNIX时间戳，单位秒"，example ``"1612518379"``），不是代码碰巧产出的东西。
TIMESTAMP_RE = re.compile(r"^\d{10}$")

#: 小红书系统参数全集（含 ``sign`` 本身：它被发送，只是不签自己）。
SYSTEM_PARAM_NAMES = {"appId", "method", "version", "timestamp", "sign", "accessToken"}

#: 旧实现发过的参数名，一个都不许再出现。
FABRICATED_PARAM_NAMES = {"client_id", "sign_method", "access_token", "app_key"}


def _live_client() -> XiaohongshuMCP:
    """当前模块绑定的客户端实例（``tests/test_api_compatibility.py`` 会 reload 本模块，
    reload 会重新绑定模块全局 ``xhs``；工具函数调用时读的是那个"当前"实例）。"""
    import servers.xiaohongshu.server as mod

    return mod.xhs


@pytest.fixture(autouse=True)
def fixed_credentials():
    """Pin credentials so the signature arithmetic in these tests is deterministic."""
    xhs = _live_client()
    original = (xhs.app_key, xhs.app_secret, xhs.access_token)
    xhs.app_key, xhs.app_secret, xhs.access_token = APP_ID, APP_SECRET, ACCESS_TOKEN
    yield
    xhs.app_key, xhs.app_secret, xhs.access_token = original


def _reference_sign(app_id: str, secret: str, api_method: str, timestamp: str) -> str:
    """官方签名算法的独立实现（不调用生产代码，避免"自己和自己一致"）。

    ``md5(method + "?" + "appId=..&timestamp=..&version=2.0" + appSecret)`` 取小写
    hex。三段 ``k=v`` 按官方示例代码的 ``sort()`` 自然序排列。
    """
    parts = sorted([f"appId={app_id}", f"timestamp={timestamp}", f"version={API_VERSION}"])
    return hashlib.md5(f"{api_method}?{'&'.join(parts)}{secret}".encode()).hexdigest()


async def _send(wire: list[CapturedRequest], coro: Any) -> CapturedRequest:
    """跑一个工具，返回它试图发出的那一个请求。

    capture double 让 ``response.json()`` 返回 ``{}``，而 ``{}`` 不是合法的成功信封，
    所以工具必然抛 ``CommerceAPIError`` —— 这本身就是判错逻辑在真实调用路径上生效的
    证据（见 ``test_unrecognized_envelope_fails_closed``）。
    """
    with contextlib.suppress(CommerceAPIError):
        await coro
    assert len(wire) == 1, f"预期恰好一个出网请求，实际 {len(wire)}"
    return wire[0]


async def _order_list_request(wire: list[CapturedRequest]) -> CapturedRequest:
    return await _send(wire, get_order_list(start_time=1612518379, end_time=1612518380))


# ═══════════════════════════════════════════════════════════════════════════════
# 网关与传输
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_single_gateway_url(wire):
    """所有业务接口都打到同一个 common_controller，没有 per-endpoint path。"""
    request = await _order_list_request(wire)
    assert request.url == GATEWAY_URL
    assert request.host == "ark.xiaohongshu.com"
    assert request.path == "/ark/open_api/v3/common_controller"


@pytest.mark.asyncio
async def test_gateway_host_is_ark_not_open(wire):
    """``open.xiaohongshu.com`` 是文档站/控制台，不是调用网关。"""
    request = await _order_list_request(wire)
    assert "open.xiaohongshu.com" not in request.url


@pytest.mark.asyncio
async def test_no_per_method_rest_path(wire):
    """官方文档里的 ``"path":"/ark/order.getOrderList"`` 是文档系统内部注册路径。

    它既不是 URL 的一部分，那些 ``/api/order/list`` 式的 REST path 更是虚构的。
    """
    request = await _order_list_request(wire)
    assert "order.getOrderList" not in request.path
    assert "/api/order" not in request.url


@pytest.mark.asyncio
async def test_method_is_post_only(wire):
    request = await _order_list_request(wire)
    assert request.method == "POST"


@pytest.mark.asyncio
async def test_content_type_header(wire):
    request = await _order_list_request(wire)
    assert request.headers.get("Content-Type") == CONTENT_TYPE
    assert request.headers["Content-Type"] == "application/json;charset=utf-8"


@pytest.mark.asyncio
async def test_every_parameter_travels_in_the_json_body(wire):
    """系统参数与业务参数全部扁平放在 body；query string 必须为空。"""
    request = await _order_list_request(wire)
    assert request.query == {}, f"不该有 query 参数，实际 {sorted(request.query)}"
    body = request.json_body()
    assert isinstance(body, dict)
    # 系统参数与业务参数同层扁平，没有 biz/params 之类的嵌套包装
    assert {"appId", "method", "sign", "timestamp", "version"} <= set(body)
    assert {"startTime", "endTime", "timeType", "pageNo", "pageSize"} <= set(body)


# ═══════════════════════════════════════════════════════════════════════════════
# 系统参数
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_system_parameter_names_and_case(wire):
    """参数名是小驼峰的 appId / accessToken，不是 client_id / access_token。"""
    request = await _order_list_request(wire)
    body = request.json_body()

    assert body["appId"] == APP_ID
    assert body["accessToken"] == ACCESS_TOKEN
    assert body["method"] == "order.getOrderList"
    assert body["version"] == API_VERSION == "2.0"

    for fabricated in FABRICATED_PARAM_NAMES:
        assert fabricated not in body, f"{fabricated} 是旧实现虚构的参数名"


@pytest.mark.asyncio
async def test_all_system_parameters_are_strings(wire):
    """官方参数表把 6 个系统参数全部标为 string。"""
    body = (await _order_list_request(wire)).json_body()
    for name in SYSTEM_PARAM_NAMES:
        assert isinstance(body[name], str), f"{name} 应为 string，实际 {type(body[name]).__name__}"


@pytest.mark.asyncio
async def test_timestamp_is_ten_digit_unix_seconds(wire):
    """官方：``UNIX时间戳，单位秒``。旧实现发的是 13 位毫秒。"""
    import time

    body = (await _order_list_request(wire)).json_body()
    timestamp = body["timestamp"]
    assert TIMESTAMP_RE.match(timestamp), f"timestamp 应为 10 位秒，实际 {timestamp!r}"
    assert abs(int(timestamp) - int(time.time())) < 60


@pytest.mark.asyncio
async def test_business_time_params_stay_seconds_while_timestamp_is_seconds(wire):
    """``order.getOrderList`` 的业务时间入参也是秒，但出参是毫秒（不在此断言）。"""
    body = (await _order_list_request(wire)).json_body()
    assert body["startTime"] == 1612518379
    assert len(str(body["startTime"])) == 10


@pytest.mark.asyncio
async def test_access_token_is_present_for_business_calls(wire):
    body = (await _order_list_request(wire)).json_body()
    assert "accessToken" in body


@pytest.mark.asyncio
async def test_access_token_omitted_when_unconfigured(wire):
    """``accessToken`` 官方标注"非必须"，未配置时不应发空串。"""
    _live_client().access_token = ""
    body = (await _order_list_request(wire)).json_body()
    assert "accessToken" not in body


# ═══════════════════════════════════════════════════════════════════════════════
# 签名
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_signature_reproduces_official_algorithm(wire):
    body = (await _order_list_request(wire)).json_body()
    assert body["sign"] == _reference_sign(APP_ID, APP_SECRET, body["method"], body["timestamp"])


@pytest.mark.asyncio
async def test_signature_is_lowercase_32_hex(wire):
    body = (await _order_list_request(wire)).json_body()
    sign = body["sign"]
    assert re.fullmatch(r"[0-9a-f]{32}", sign), f"应为 32 位小写 hex，实际 {sign!r}"


@pytest.mark.asyncio
async def test_signature_ignores_business_parameters(wire):
    """同一 method/timestamp 下，改业务参数不改签名（业务参数不入签）。"""
    request_a = await _order_list_request(wire)
    body_a = request_a.json_body()

    wire.clear()
    request_b = await _send(
        wire,
        get_order_list(start_time=1612518379, end_time=1612518380, page_no=7, page_size=99),
    )
    body_b = request_b.json_body()

    assert body_b["pageNo"] == 7 and body_a["pageNo"] == 1
    if body_a["timestamp"] == body_b["timestamp"]:
        assert body_a["sign"] == body_b["sign"]
    # 与时间戳无关的强断言：两次都各自等于"仅 4 个系统参数"的参考签名
    for body in (body_a, body_b):
        assert body["sign"] == _reference_sign(APP_ID, APP_SECRET, body["method"], body["timestamp"])


@pytest.mark.asyncio
async def test_signature_ignores_access_token(wire):
    """``accessToken`` 不参与 sign（官方《签名算法》与《系统参数说明》两处明文）。"""
    request_a = await _order_list_request(wire)
    body_a = request_a.json_body()

    wire.clear()
    _live_client().access_token = "a-totally-different-token"
    body_b = (await _order_list_request(wire)).json_body()

    assert body_a["accessToken"] != body_b["accessToken"]
    for body in (body_a, body_b):
        assert body["sign"] == _reference_sign(APP_ID, APP_SECRET, body["method"], body["timestamp"])


@pytest.mark.asyncio
async def test_signature_covers_exactly_the_four_system_parameters(wire):
    """把每个入签字段依次改掉，签名都必须变；改其他字段签名不变。"""
    body = (await _order_list_request(wire)).json_body()
    baseline = _reference_sign(APP_ID, APP_SECRET, body["method"], body["timestamp"])

    assert SIGNED_PARAMS == {"method", "appId", "timestamp", "version"}
    assert _reference_sign("other_app", APP_SECRET, body["method"], body["timestamp"]) != baseline
    assert _reference_sign(APP_ID, APP_SECRET, "order.getOrderDetail", body["timestamp"]) != baseline
    assert _reference_sign(APP_ID, APP_SECRET, body["method"], "1600000000") != baseline
    assert _reference_sign(APP_ID, "other_secret", body["method"], body["timestamp"]) != baseline


@pytest.mark.asyncio
async def test_sign_source_has_no_space_after_ampersand(wire):
    """官方正文写成 ``appId=xxx& timestamp=...``，同页注明"实际中不存在"该空格。"""
    body = (await _order_list_request(wire)).json_body()
    source = _live_client()._sign_source(body["method"], body["timestamp"])
    assert " " not in source
    assert source.startswith(f"{body['method']}?appId=")


# ── 跨平台通用断言：签名集合 == 发送集合 − {sign} ────────────────────────────────
#
# 小红书是这条不变式的**明文例外**：``accessToken`` 与全部业务参数被发送但不入签
# （官方《签名算法》"目前参与加密的均为系统参数和 appSecret。系统参数有：appId,
# timestamp,version,method"；《系统参数说明》"该字段不参与sign签名运算"）。
# 因此下面不是跳过断言，而是把例外集合显式列出来、从发送集合里扣掉之后仍然启用通用
# 断言，并额外钉住"例外项确实被发送了" —— 否则"例外"就会变成掩盖漏发参数的借口。


@pytest.mark.asyncio
async def test_signature_set_matches_sent_modulo_documented_exceptions(wire, assert_signature_set_matches_sent):
    request = await _order_list_request(wire)
    body = request.json_body()

    business_params = {"startTime", "endTime", "timeType", "orderType", "orderStatus", "pageNo", "pageSize"}
    documented_exceptions = {"accessToken"} | business_params

    # 例外项必须真的在发送集合里（否则这个测试会因为"漏发"而假绿）
    assert documented_exceptions <= set(body), sorted(documented_exceptions - set(body))

    narrowed = CapturedRequest(
        method=request.method,
        url=request.url,
        query=dict(request.query),
        body={k: v for k, v in body.items() if k not in documented_exceptions},
        headers=dict(request.headers),
    )
    assert_signature_set_matches_sent(narrowed, signed=set(SIGNED_PARAMS))


@pytest.mark.asyncio
async def test_naive_signature_set_invariant_would_fail_here(wire, assert_signature_set_matches_sent):
    """把例外集合去掉，通用断言必须失败 —— 证明这个例外是真的、不是懒。

    这条测试同时是护栏：若有人"顺手"把业务参数加进签名以让通用断言过关，官方验签
    就会挂，而这条测试会先变红。
    """
    request = await _order_list_request(wire)
    with pytest.raises(AssertionError, match="sent but not signed"):
        assert_signature_set_matches_sent(request, signed=set(SIGNED_PARAMS))


# ═══════════════════════════════════════════════════════════════════════════════
# method 名（每个工具打的是官方 method，不是虚构 path）
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("call_factory", "expected_method"),
    [
        (lambda: get_order_list(start_time=1612518379, end_time=1612518380), "order.getOrderList"),
        (lambda: get_order_detail(order_id="P1"), "order.getOrderDetail"),
        (lambda: get_product_list(), "product.searchItemList"),
        (lambda: get_refund_list(order_id="P1"), "afterSale.listAfterSaleInfos"),
        (lambda: get_inventory(sku_id="s1"), "inventory.getSkuStockV2"),
        (
            lambda: get_settlement_transactions(start_time=1612518379000, end_time=1612518380000),
            "finance.pageQueryTransaction",
        ),
        (lambda: get_monthly_statement_url(month="2024-01"), "bill.downloadStatement"),
    ],
)
async def test_tool_sends_official_method_to_the_same_gateway(wire, call_factory, expected_method):
    request = await _send(wire, call_factory())
    body = request.json_body()
    assert body["method"] == expected_method
    # 网关版本族不同（103/1661 vs 165/2804），但 URL、系统参数与签名规则一致
    assert request.url == GATEWAY_URL
    assert request.method == "POST"
    assert body["sign"] == _reference_sign(APP_ID, APP_SECRET, expected_method, body["timestamp"])


@pytest.mark.asyncio
async def test_retired_method_names_are_never_sent(wire):
    """官方示例里的 ``package.getPackageList`` / ``product.createItem`` 都已下线。"""
    body = (await _order_list_request(wire)).json_body()
    assert not body["method"].startswith("package.")
    assert body["method"] != "product.createItem"


# ═══════════════════════════════════════════════════════════════════════════════
# 判错（在真实调用路径上，而不是只在解包函数上）
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_unrecognized_envelope_fails_closed(wire):
    """capture double 返回 ``{}``：既非 ``error_code==0`` 也无 ``success`` ⇒ 必须抛错。

    旧实现只查淘宝/拼多多的 ``error_response``，于是把任何信封原样当业务数据返回，
    失败完全检测不到。
    """
    with pytest.raises(CommerceAPIError):
        await get_order_list(start_time=1612518379, end_time=1612518380)
    assert len(wire) == 1  # 确认失败发生在收到响应之后，而不是构造请求时


def test_success_requires_error_code_zero_and_success_true():
    unwrap = XiaohongshuMCP._unwrap_envelope
    ok = {"error_code": 0, "error_msg": "", "success": True, "data": {"total": 1}}
    assert unwrap(ok, api_method="order.getOrderList", gateway="103/1661") == {"total": 1}

    for bad in (
        {"error_code": -2000400, "error_msg": "请求参数错误", "success": False},
        {"error_code": 0, "success": False, "data": {}},
        {"error_response": {"code": 10001, "msg": "order not found"}},
        {"data": {"total": 1}},
    ):
        with pytest.raises(CommerceAPIError):
            unwrap(bad, api_method="order.getOrderList", gateway="103/1661")
