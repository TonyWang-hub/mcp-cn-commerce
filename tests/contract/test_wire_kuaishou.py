"""Wire-level contract assertions for the Kuaishou (快手小店) open platform.

These tests read the exact bytes the server would have put on the wire and check
them against the gateway's documented contract across all four layers that were
previously wrong at once:

1. **path** — derived from the official dotted ``method`` name; there is no
   ``/open/api/...`` form on this gateway;
2. **parameter structure** — flat system params, business params packed into a
   *single* ``param`` JSON with camelCase keys;
3. **signature** — dedicated ``signSecret``, ``k=v`` joined with ``&``, a literal
   ``&signSecret=`` suffix, lowercase MD5 hex, computed *before* URL encoding;
4. **envelope / pagination** — ``result == 1`` for success, and five different
   pagination paradigms across the nine endpoints.

They sit below the boundary ``servers/kuaishou/tests/test_kuaishou.py`` mocks
(``ks._call``), which is exactly where these defects hid: a test that stubs
``_call`` can never notice that the credential went out as ``app_key``, that
``signMethod`` was sent but not signed, or that a failure envelope was handed to
the model as data.

Sources for every expectation are recorded in ``docs/api-contracts/kuaishou.md``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from urllib.parse import quote

import pytest

os.environ.setdefault("KUAISHOU_APP_KEY", "test_key")
os.environ.setdefault("KUAISHOU_APP_SECRET", "test_secret")
os.environ.setdefault("KUAISHOU_SIGN_SECRET", "test_sign_secret")
os.environ.setdefault("KUAISHOU_ACCESS_TOKEN", "test_token")

import servers.kuaishou.server as ks_server  # noqa: E402
from servers.kuaishou.server import (  # noqa: E402
    get_order_detail,
    get_order_list,
    get_product_detail,
    get_product_list,
    get_refund_detail,
    get_refund_list,
    get_review_list,
    get_shop_info,
    ks,
    list_coupons,
    mcp,
)
from shared.cn_commerce_base import CommerceAPIError  # noqa: E402

APP_KEY = "wire_appkey"
SIGN_SECRET = "wire_sign_secret"
APP_SECRET = "wire_oauth_secret"
ACCESS_TOKEN = "wire_access_token"

#: Epoch **milliseconds**, i.e. 13 digits. A literal shape rather than something
#: derived from the code, so a seconds-based regression cannot pass.
TIMESTAMP_RE = re.compile(r"^\d{13}$")

#: 32 lowercase hex characters — the official SDK uses ``md5Hex``.
MD5_LOWER_RE = re.compile(r"^[0-9a-f]{32}$")

#: The complete flat system-parameter set. Every name here is asserted verbatim
#: because the casing *is* the contract: ``appkey`` all-lowercase but
#: ``signMethod`` camelCase, with ``access_token`` snake_case between them.
SYSTEM_PARAMS = {
    "appkey",
    "method",
    "version",
    "access_token",
    "timestamp",
    "signMethod",
    "sign",
}

#: Names the previous implementation used, kept as explicit negatives.
FORBIDDEN_PARAMS = {"app_key", "sign_method", "signsecret", "signSecret", "uid"}

#: Every endpoint this server may reach: tool → (official method, official path).
ENDPOINTS = {
    "get_order_list": ("open.order.cursor.list", "/open/order/cursor/list"),
    "get_order_detail": ("open.order.detail", "/open/order/detail"),
    "get_product_list": ("open.item.list.get", "/open/item/list/get"),
    "get_product_detail": ("open.item.get", "/open/item/get"),
    "get_refund_list": (
        "open.seller.order.refund.pcursor.list",
        "/open/seller/order/refund/pcursor/list",
    ),
    "get_refund_detail": (
        "open.seller.order.refund.detail",
        "/open/seller/order/refund/detail",
    ),
    "get_review_list": ("open.comment.list.get", "/open/comment/list/get"),
    "list_coupons": ("open.promotion.coupon.page.list", "/open/promotion/coupon/page/list"),
    "get_shop_info": ("open.shop.info.get", "/open/shop/info/get"),
}

#: Tools removed because the platform does not offer the capability at all.
REMOVED_TOOLS = ("get_logistics_tracking", "list_logistics_companies", "list_promotions")


@pytest.fixture(autouse=True)
def fixed_credentials():
    """Pin credentials and signMethod so signature arithmetic is deterministic."""
    original = (ks.app_key, ks.app_secret, ks.sign_secret, ks.access_token, ks.sign_method)
    ks.app_key, ks.app_secret = APP_KEY, APP_SECRET
    ks.sign_secret, ks.access_token = SIGN_SECRET, ACCESS_TOKEN
    ks.sign_method = ks_server.SIGN_METHOD_MD5
    yield
    ks.app_key, ks.app_secret, ks.sign_secret, ks.access_token, ks.sign_method = original


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _fire(coro):
    """Run a tool for its outbound request only.

    The wire fixture answers every call with ``{}``, which is *not* a Kuaishou
    success envelope (``result == 1``), so the tool correctly raises. That the
    raise happens is itself asserted in the envelope tests below; here we only
    want the captured request.
    """
    with pytest.raises(CommerceAPIError):
        await coro


def _sent(request) -> dict[str, str]:
    """Every parameter actually transmitted, wherever the platform puts it."""
    body = request.body if isinstance(request.body, dict) else {}
    return {**request.query, **body}


def _reference_sign(secret: str, params: dict[str, str]) -> str:
    """Kuaishou MD5 signature, implemented from the documented rule.

    Sort every parameter except ``sign`` by name, join ``k=v`` pairs with ``&``,
    append the literal ``&signSecret=<signSecret>``, then MD5 → lowercase hex.
    Written out here rather than delegating to ``ks._sign`` so that a wrong
    implementation cannot agree with itself.
    """
    signable = {k: v for k, v in params.items() if k != "sign" and v not in (None, "")}
    payload = "&".join(f"{k}={signable[k]}" for k in sorted(signable))
    return hashlib.md5(f"{payload}&signSecret={secret}".encode()).hexdigest()


def _biz(request) -> dict:
    """The business params, unpacked from the single ``param`` JSON string."""
    raw = _sent(request)["param"]
    assert isinstance(raw, str), "`param` must be a JSON *string*, not a nested object"
    return json.loads(raw)


class _StubResponse:
    """Minimal stand-in for an httpx response, for envelope assertions."""

    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload) if isinstance(payload, (dict, list)) else str(payload)

    def json(self):
        return self._payload


# ── Layer 1: paths are the official ones ──────────────────────────────────────


@pytest.mark.asyncio
async def test_every_endpoint_uses_the_official_path_and_method(wire):
    """Each tool must hit the dotted method's slash-form path, over GET.

    The old ``/open/api/<noun>/<verb>`` template is fabricated: the ``api``
    segment does not exist on this gateway.
    """
    calls = {
        "get_order_list": get_order_list(start_time="1700000000000", end_time="1700086400000"),
        "get_order_detail": get_order_detail(order_id="2000001"),
        "get_product_list": get_product_list(),
        "get_product_detail": get_product_detail(item_id="30001"),
        "get_refund_list": get_refund_list(start_time="1700000000000", end_time="1700003600000"),
        "get_refund_detail": get_refund_detail(refund_id="40001"),
        "get_review_list": get_review_list(item_id="30001"),
        "list_coupons": list_coupons(),
        "get_shop_info": get_shop_info(),
    }

    for tool_name, coro in calls.items():
        await _fire(coro)

    assert len(wire) == len(ENDPOINTS)
    for request, tool_name in zip(wire, calls, strict=True):
        api_method, path = ENDPOINTS[tool_name]
        assert request.method == "GET", f"{tool_name}: all nine live endpoints are GET"
        assert request.host == "openapi.kwaixiaodian.com", f"{tool_name}: wrong gateway"
        assert request.path == path, f"{tool_name}: path is not the official one"
        assert _sent(request)["method"] == api_method, f"{tool_name}: wrong method name"
        assert "/api/" not in request.path, f"{tool_name}: fabricated `api` path segment is back"


def test_path_is_derived_from_the_method_name_mechanically():
    """The path rule is dots→slashes, so it cannot drift from the method name."""
    for api_method, path in ENDPOINTS.values():
        assert ks.path_for(api_method) == path

    with pytest.raises(ValueError):
        ks.path_for("")
    with pytest.raises(ValueError):
        ks.path_for("open..order")


def test_retired_order_methods_are_not_used():
    """The pcursor order methods were retired; the cursor ones replaced them."""
    used = {api_method for api_method, _ in ENDPOINTS.values()}
    assert "open.seller.order.pcursor.list" not in used
    assert "open.seller.order.detail" not in used
    # Same for the retired item methods.
    assert "open.item.list" not in used
    assert "open.item.detail" not in used


def test_capabilities_the_platform_does_not_offer_are_gone():
    """Logistics tracking / carrier list / promotion list must not be tools.

    Kuaishou only offers a *write* endpoint for carriers pushing tracking data
    to it (opposite direction), publishes carrier codes as a static document
    table rather than an API, and its marketing surface covers only coupons and
    audience packages.
    """
    for name in REMOVED_TOOLS:
        assert not hasattr(ks_server, name), f"{name} should have been removed"


@pytest.mark.asyncio
async def test_registered_tool_surface_matches_the_real_endpoints():
    """Nine platform tools plus the four shared operational ones."""
    names = {tool.name for tool in await mcp.list_tools()}
    assert set(ENDPOINTS) <= names
    assert names & set(REMOVED_TOOLS) == set()
    assert len(names) == len(ENDPOINTS) + 4


# ── Layer 2: parameter names, casing and placement ────────────────────────────


@pytest.mark.asyncio
async def test_system_parameter_names_and_casing(wire):
    """``appkey`` all-lowercase, ``signMethod`` camelCase, nothing extra flat."""
    await _fire(get_shop_info())
    sent = _sent(wire[0])

    assert set(sent) == SYSTEM_PARAMS, (
        "the flat parameter set must be exactly the system params — a business "
        "param leaking out flat means it is not inside `param`"
    )
    assert sent["appkey"] == APP_KEY
    assert sent["version"] == "1"
    assert sent["access_token"] == ACCESS_TOKEN
    assert sent["signMethod"] == "MD5"

    for forbidden in FORBIDDEN_PARAMS:
        assert forbidden not in sent, f"{forbidden} must never be sent"


@pytest.mark.asyncio
async def test_no_param_field_when_there_are_no_business_params(wire):
    """``param`` is only sent when non-empty, matching the signing rule."""
    await _fire(get_shop_info())
    assert "param" not in _sent(wire[0])


@pytest.mark.asyncio
async def test_business_params_are_one_json_string_with_camelcase_keys(wire):
    """Business params must be packed, not flattened, and camelCase throughout."""
    await _fire(
        get_order_list(
            start_time="1700000000000",
            end_time="1700086400000",
            order_view_status="3",
            page_size=50,
        )
    )
    sent = _sent(wire[0])

    assert set(sent) == SYSTEM_PARAMS | {"param"}
    biz = _biz(wire[0])
    assert biz == {
        "orderViewStatus": 3,
        "beginTime": 1700000000000,
        "endTime": 1700086400000,
        "pageSize": 50,
        "cursor": "",
    }
    for key in biz:
        assert re.fullmatch(r"[a-z]+([A-Z][a-z0-9]*)*", key), f"{key} is not camelCase"
        assert "_" not in key, f"{key} is snake_case; the gateway wants camelCase"


@pytest.mark.asyncio
async def test_timestamp_is_epoch_milliseconds(wire):
    """13-digit epoch millis, not seconds and not a formatted datetime."""
    await _fire(get_shop_info())
    assert TIMESTAMP_RE.match(_sent(wire[0])["timestamp"])


@pytest.mark.asyncio
async def test_human_times_are_converted_to_millis_in_gmt8(wire):
    """Naive datetime input is read as GMT+8, not as the process timezone."""
    await _fire(get_order_list(start_time="2024-01-01 00:00:00", end_time="2024-01-02 00:00:00"))
    biz = _biz(wire[0])
    # 2024-01-01T00:00:00+08:00 == 1704038400000
    assert biz["beginTime"] == 1704038400000
    assert biz["endTime"] == 1704038400000 + 86_400_000


# ── Layer 3: signature ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_signature_matches_the_documented_arithmetic(wire):
    """The sent ``sign`` must reproduce from the documented rule, lowercase."""
    await _fire(get_review_list(item_id="30001", offset=0, limit=20))
    sent = _sent(wire[0])

    assert MD5_LOWER_RE.match(sent["sign"]), "MD5 hex must be lowercase (official SDK uses md5Hex)"
    signable = {k: v for k, v in sent.items() if k != "sign"}
    assert sent["sign"] == _reference_sign(SIGN_SECRET, signable)


@pytest.mark.asyncio
async def test_signature_uses_sign_secret_not_app_secret(wire):
    """``signSecret`` is a separate credential; ``appSecret`` is OAuth-only."""
    await _fire(get_shop_info())
    sent = _sent(wire[0])
    signable = {k: v for k, v in sent.items() if k != "sign"}

    assert sent["sign"] == _reference_sign(SIGN_SECRET, signable)
    assert sent["sign"] != _reference_sign(APP_SECRET, signable)


@pytest.mark.asyncio
async def test_sign_secret_is_never_transmitted(wire):
    """The secret is a signature suffix, not a request parameter."""
    await _fire(get_shop_info())
    sent = _sent(wire[0])
    assert SIGN_SECRET not in sent.values()
    assert SIGN_SECRET not in wire[0].url


def test_sign_base_string_shape():
    """`k=v` joined with `&`, sorted, with the literal `&signSecret=` suffix."""
    params = ks.build_params("open.item.get", {"itemId": "30001"})
    raw = ks.sign_base_string(params)

    assert raw.endswith(f"&signSecret={SIGN_SECRET}")
    pairs = raw.split("&")
    assert pairs[-1].startswith("signSecret=")
    keys = [pair.split("=", 1)[0] for pair in pairs[:-1]]
    assert keys == sorted(keys), "parameters must be in ASCII name order"
    assert "sign" not in keys, "`sign` excludes itself"
    assert set(keys) == (SYSTEM_PARAMS - {"sign"}) | {"param"}


@pytest.mark.asyncio
async def test_signature_is_computed_before_url_encoding(wire):
    """Signing the percent-encoded values would produce a different signature.

    This is the ordering trap: the ``param`` JSON's quotes and colons must be
    encoded only on the way out, after the digest is taken over the raw bytes.
    """
    await _fire(get_product_detail(item_id="30001"))
    sent = _sent(wire[0])
    signable = {k: v for k, v in sent.items() if k != "sign"}

    assert '"' in sent["param"], "the captured `param` must still be raw JSON"
    encoded = {k: quote(str(v), safe="") for k, v in signable.items()}
    assert sent["sign"] == _reference_sign(SIGN_SECRET, signable)
    assert sent["sign"] != _reference_sign(SIGN_SECRET, encoded)


@pytest.mark.asyncio
async def test_hmac_sha256_variant_is_base64_not_hex(wire):
    """The documented alternative digest is Base64-encoded, not hex."""
    ks.sign_method = ks_server.SIGN_METHOD_HMAC_SHA256
    await _fire(get_shop_info())
    sent = _sent(wire[0])

    assert sent["signMethod"] == "HMAC_SHA256"
    assert not MD5_LOWER_RE.match(sent["sign"])
    assert sent["sign"].endswith("=") or "+" in sent["sign"] or "/" in sent["sign"] or len(sent["sign"]) == 44


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda: get_order_list(start_time="1700000000000", end_time="1700086400000"), id="order_list"),
        pytest.param(lambda: get_order_detail(order_id="2000001"), id="order_detail"),
        pytest.param(lambda: get_product_list(), id="product_list"),
        pytest.param(lambda: get_product_detail(item_id="30001"), id="product_detail"),
        pytest.param(lambda: get_refund_list(start_time="1700000000000", end_time="1700003600000"), id="refund_list"),
        pytest.param(lambda: get_refund_detail(refund_id="40001"), id="refund_detail"),
        pytest.param(lambda: get_review_list(item_id="30001"), id="review_list"),
        pytest.param(lambda: list_coupons(), id="coupons"),
        pytest.param(lambda: get_shop_info(), id="shop_info"),
    ],
)
async def test_signed_set_equals_sent_set(wire, assert_signature_set_matches_sent, call):
    """The cross-platform invariant, per endpoint: signed == sent − {sign}.

    Kuaishou is where this used to fail hardest — ``signMethod`` was sent but
    excluded from the digest, and ``method`` / ``version`` were never sent at all.
    """
    await _fire(call())

    request = wire[0]
    signable = {k: v for k, v in _sent(request).items() if k != "sign"}
    assert_signature_set_matches_sent(request, signed=set(signable))
    # And the arithmetic over exactly that set reproduces the sent signature.
    assert _sent(request)["sign"] == _reference_sign(SIGN_SECRET, signable)


# ── Layer 4: envelope ─────────────────────────────────────────────────────────


def test_success_requires_result_equals_one():
    """``result == 1`` is the success rule; the payload lives under ``data``."""
    payload = {"result": 1, "data": {"orderList": []}, "error_msg": ""}
    assert ks._check_envelope(_StubResponse(payload)) == payload


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"result": 2, "error_msg": "参数错误"}, id="business_error"),
        pytest.param({"result": 0, "error_msg": "invalid token"}, id="result_zero"),
        pytest.param({"error_response": {"code": 7, "msg": "x"}}, id="taobao_style_envelope"),
        pytest.param({}, id="empty"),
    ],
)
def test_non_one_result_is_an_error(payload):
    """Anything but ``result == 1`` must raise, not be returned as data.

    The base class looks for ``error_response``, which this gateway never emits,
    so every Kuaishou failure used to reach the model as a "successful" response
    whose data was in fact an error envelope.
    """
    with pytest.raises(CommerceAPIError):
        ks._check_envelope(_StubResponse(payload))


def test_error_message_is_taken_from_error_msg():
    """``error_msg`` must survive into the exception rather than becoming 'unknown'."""
    with pytest.raises(CommerceAPIError) as exc:
        ks._check_envelope(_StubResponse({"result": 62003, "error_msg": "订单不存在"}))
    assert exc.value.code == 62003
    assert exc.value.msg == "订单不存在"


def test_http_error_status_is_surfaced():
    with pytest.raises(CommerceAPIError) as exc:
        ks._check_envelope(_StubResponse({"result": 1}, status_code=503))
    assert exc.value.code == 503


# ── Layer 4: pagination paradigms differ per endpoint ─────────────────────────


@pytest.mark.asyncio
async def test_order_list_is_pure_cursor(wire):
    """No page number: cursor only, empty on the first call, pageSize ≤ 50."""
    await _fire(get_order_list(start_time="1700000000000", end_time="1700086400000", page_size=999))
    first = _biz(wire[0])
    assert first["cursor"] == "", "the first call sends an empty cursor"
    assert first["pageSize"] == 50, "pageSize is capped at 50"
    assert not {"pageNumber", "pageNo", "currentPage", "offset"} & set(first)

    wire.clear()
    await _fire(get_order_list(start_time="1700000000000", end_time="1700086400000", cursor="AAAA", page_size=10))
    assert _biz(wire[0])["cursor"] == "AAAA"

    wire.clear()
    await _fire(
        get_order_list(
            start_time="1700000000000",
            end_time="1700086400000",
            cursor=ks_server.CURSOR_EXHAUSTED,
        )
    )
    assert _biz(wire[0])["cursor"] == "", "'nomore' is an end sentinel, not a cursor"


@pytest.mark.asyncio
async def test_order_list_requires_order_view_status(wire):
    """``orderViewStatus`` is mandatory and enum-checked."""
    await _fire(get_order_list(start_time="1700000000000", end_time="1700086400000"))
    assert _biz(wire[0])["orderViewStatus"] == 1

    with pytest.raises(ValueError):
        await get_order_list(start_time="1700000000000", end_time="1700086400000", order_view_status="9")


@pytest.mark.asyncio
async def test_refund_list_is_hybrid_pcursor_plus_current_page(wire):
    """Both ``pcursor`` and ``currentPage`` are required, and both go out."""
    await _fire(get_refund_list(start_time="1700000000000", end_time="1700003600000", page_size=500))
    biz = _biz(wire[0])

    assert biz["pcursor"] == "", "pcursor is present but empty on the first call"
    assert biz["currentPage"] == 1
    assert biz["pageSize"] == 100, "pageSize is capped at 100"

    wire.clear()
    await _fire(
        get_refund_list(
            start_time="1700000000000",
            end_time="1700003600000",
            pcursor="BBBB",
            current_page=2,
        )
    )
    resumed = _biz(wire[0])
    assert (resumed["pcursor"], resumed["currentPage"]) == ("BBBB", 2)


@pytest.mark.asyncio
async def test_product_list_uses_real_page_numbers(wire):
    """``pageNumber`` + ``pageSize``, with pageSize clamped into 10–100."""
    await _fire(get_product_list(page=3, page_size=20))
    biz = _biz(wire[0])
    assert biz == {"pageNumber": 3, "pageSize": 20}

    wire.clear()
    await _fire(get_product_list(page=1, page_size=5))
    assert _biz(wire[0])["pageSize"] == 10, "pageSize floor is 10"


@pytest.mark.asyncio
async def test_review_list_uses_offset_limit_capped_at_20(wire):
    await _fire(get_review_list(item_id="30001", offset=40, limit=100))
    biz = _biz(wire[0])
    assert biz == {"itemId": "30001", "offset": 40, "limit": 20}


@pytest.mark.asyncio
async def test_coupon_list_uses_page_no_starting_at_one(wire):
    await _fire(list_coupons(page=1, page_size=20))
    assert _biz(wire[0]) == {"pageNo": 1, "pageSize": 20}

    wire.clear()
    await _fire(list_coupons(page=0))
    assert _biz(wire[0])["pageNo"] == 1, "pageNo starts at 1, not 0"


# ── Serialization discipline ──────────────────────────────────────────────────


def test_param_json_is_serialized_once_and_deterministically():
    """The signed bytes and the sent bytes must be the same string object's value."""
    biz = {"itemId": "30001", "extra": "a"}
    first = ks.pack_param(biz)
    second = ks.pack_param(dict(reversed(list(biz.items()))))
    assert first == second, "key order must not change the serialization"
    assert first == '{"extra":"a","itemId":"30001"}'
    assert ks.pack_param({}) == ""
    assert ks.pack_param(None) == ""
