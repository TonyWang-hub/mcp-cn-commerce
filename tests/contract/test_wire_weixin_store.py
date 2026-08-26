"""Wire-level contract assertions for WeChat Store (微信小店).

These tests read the exact bytes the server would have put on the wire and
compare them against WeChat's documented contract — the endpoint path, the HTTP
verb (two endpoints are ``GET`` and reject a POST with errcode 43001), where the
credential goes, the request-body field names and their types, the documented
time-span caps, the status enums, and the two failure shapes (``errcode`` in the
body, and a bare HTTP 403 for an IP-allowlist miss that carries no errcode).

They sit below the boundary the unit tests mock (``_wx._request``), which is
exactly where this platform's defects hid: five of its eleven endpoints did not
exist and four of the six that did were sent invented request bodies, and a test
that stubs ``_request`` can never notice either.

Sources for every expectation are recorded in ``docs/api-contracts/weixin_store.md``.
"""

from __future__ import annotations

import json as jsonlib
import os
import time
from unittest.mock import MagicMock

import pytest

from tests.contract.conftest import CapturedRequest

os.environ.setdefault("WX_APP_ID", "test_app_id")
os.environ.setdefault("WX_APP_SECRET", "test_app_secret")
os.environ.setdefault("WX_ACCESS_TOKEN", "test_access_token_123456")

from servers.weixin_store.server import (  # noqa: E402
    AFTERSALE_TIME_SPAN_MAX_SECONDS,
    ORDER_TIME_SPAN_MAX_SECONDS,
    WeixinStoreMCP,
    _wx,
    get_logistics_tracking,
    get_order_detail,
    get_order_list,
    get_product_detail,
    get_product_list,
    get_refund_detail,
    get_refund_list,
    get_shop_info,
    get_supply_order_list,
    list_categories,
    list_coupons,
)
from shared.cn_commerce_base import CommerceAPIError  # noqa: E402

BASE_HOST = "api.weixin.qq.com"
WIRE_TOKEN = "wire_access_token"

T0 = 1704067200  # 2024-01-01T00:00:00Z
T_1H = T0 + 3600

#: Parameter names that must never appear on a WeChat Store request. The
#: no-signature claim is an inference (see the contract doc), but it is the
#: inference this client is built on, so it gets pinned: if a future change
#: starts sending ``sign``/``timestamp``, that is a contract decision that has
#: to be made deliberately, not inherited from the shared base class.
FORBIDDEN_PARAMS = {"sign", "sign_method", "timestamp", "app_key", "secret"}


@pytest.fixture(autouse=True)
def stable_token_cache():
    """Pin a live token so business calls make exactly one request each.

    Without this, ``_ensure_token`` would mint a token first and every
    single-request assertion would have to index past it.
    """
    saved = (
        _wx._stable_access_token,
        _wx._token_expires_at,
        _wx._token_ttl,
        list(_wx._force_refresh_log),
        _wx._coupon_page_cursor,
    )
    _wx._stable_access_token = WIRE_TOKEN
    _wx._token_expires_at = time.time() + 7200
    _wx._token_ttl = 7200.0
    _wx._force_refresh_log = []
    _wx._coupon_page_cursor = None
    yield
    (
        _wx._stable_access_token,
        _wx._token_expires_at,
        _wx._token_ttl,
        _wx._force_refresh_log,
        _wx._coupon_page_cursor,
    ) = saved


def _install_stub(monkeypatch, responses):
    """Record outbound requests and hand back scripted ``(status, payload)``.

    ``tests.contract.conftest.wire`` always answers 200/``{}``; the token and
    HTTP-403 assertions need control over status codes and bodies, so they use
    this instead. A ``str`` payload stands for a non-JSON body.
    """
    import httpx

    captured: list[CapturedRequest] = []
    queue = list(responses)

    def _record(http_method: str):
        async def _call(url, *, params=None, json=None, data=None, headers=None, **_):
            captured.append(
                CapturedRequest(
                    method=http_method,
                    url=str(url),
                    query=dict(params or {}),
                    body=json if json is not None else data,
                    headers=dict(headers or {}),
                )
            )
            status, payload = queue.pop(0) if queue else (200, {})
            response = MagicMock()
            response.status_code = status
            if isinstance(payload, str):
                response.json.side_effect = ValueError("not json")
                response.text = payload
            else:
                response.json.return_value = payload
                response.text = jsonlib.dumps(payload)
            return response

        return _call

    class _Recorder:
        def __init__(self, *_, **__):
            self.get = _record("GET")
            self.post = _record("POST")
            self.headers: dict[str, str] = {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def aclose(self):
            return None

    monkeypatch.setattr(httpx, "AsyncClient", _Recorder)
    return captured


# ── Every tool, with arguments that satisfy the documented contract ──────────

ALL_CALLS = [
    ("get_order_list", lambda: get_order_list(start_time=T0, end_time=T_1H)),
    ("get_order_detail", lambda: get_order_detail(order_id="3705115058471207123")),
    ("get_product_list", lambda: get_product_list()),
    ("get_product_detail", lambda: get_product_detail(product_id="10000000000001")),
    ("get_refund_list", lambda: get_refund_list(start_time=T0, end_time=T_1H)),
    ("get_refund_detail", lambda: get_refund_detail(after_sale_order_id="37051150584712")),
    ("get_logistics_tracking", lambda: get_logistics_tracking(order_id="37051150584712")),
    ("get_shop_info", lambda: get_shop_info()),
    ("list_coupons", lambda: list_coupons(status=2)),
    ("get_supply_order_list", lambda: get_supply_order_list()),
    ("list_categories", lambda: list_categories()),
]

#: path → HTTP verb, as documented. The two ``GET`` entries are the point: a
#: POST to either returns errcode 43001.
EXPECTED_ROUTES = {
    "get_order_list": ("POST", "/channels/ec/order/list/get"),
    "get_order_detail": ("POST", "/channels/ec/order/get"),
    "get_product_list": ("POST", "/channels/ec/product/list/get"),
    "get_product_detail": ("POST", "/channels/ec/product/get"),
    "get_refund_list": ("POST", "/channels/ec/aftersale/getaftersalelist"),
    "get_refund_detail": ("POST", "/channels/ec/aftersale/getaftersaleorder"),
    # No logistics-pull endpoint exists; delivery_info comes out of order/get.
    "get_logistics_tracking": ("POST", "/channels/ec/order/get"),
    "get_shop_info": ("GET", "/channels/ec/basics/info/get"),
    "list_coupons": ("POST", "/channels/ec/coupon/get_list"),
    # Shop side of the dropship pair — see the contract doc for the decision.
    "get_supply_order_list": ("POST", "/channels/ec/order/dropship/list"),
    # Note the /shop/ec/ prefix: this one endpoint does not live under
    # /channels/ec/ like the rest of the surface.
    "list_categories": ("GET", "/shop/ec/category/all"),
}

#: Paths the audit found do not exist. Kept as an explicit blocklist so a
#: regression reintroducing any of them fails loudly rather than silently
#: returning errcode 48001/43001 at runtime.
NONEXISTENT_PATHS = {
    "/channels/ec/basicinfo/get",
    "/channels/ec/category/list/get",
    "/channels/ec/coupon/list/get",
    "/channels/ec/order/deliveryinfo/get",
    "/channels/ec/supplier/order/list/get",
}


# ═══════════════════════════════════════════════════════════════════════════════
# Routes: path + HTTP verb
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@pytest.mark.parametrize("name,call", ALL_CALLS, ids=[n for n, _ in ALL_CALLS])
async def test_each_tool_hits_the_documented_route(wire, name, call):
    await call()

    assert len(wire) == 1, f"{name} made {len(wire)} requests, expected 1"
    request = wire[0]
    expected_method, expected_path = EXPECTED_ROUTES[name]
    assert request.host == BASE_HOST
    assert request.path == expected_path
    assert request.method == expected_method


@pytest.mark.asyncio
@pytest.mark.parametrize("name,call", ALL_CALLS, ids=[n for n, _ in ALL_CALLS])
async def test_no_tool_calls_a_nonexistent_path(wire, name, call):
    await call()

    assert wire[0].path not in NONEXISTENT_PATHS


@pytest.mark.asyncio
async def test_the_two_get_endpoints_send_no_body(wire):
    """``GET`` with a body earns errcode 43001, so there must be no body."""
    await get_shop_info()
    await list_categories()

    assert [r.method for r in wire] == ["GET", "GET"]
    assert [r.body for r in wire] == [None, None]
    # ...and nothing but the credential on the query string.
    assert [set(r.query) for r in wire] == [{"access_token"}, {"access_token"}]


# ═══════════════════════════════════════════════════════════════════════════════
# Credential placement
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@pytest.mark.parametrize("name,call", ALL_CALLS, ids=[n for n, _ in ALL_CALLS])
async def test_access_token_travels_in_the_query_string(wire, name, call):
    await call()

    request = wire[0]
    assert request.query.get("access_token") == WIRE_TOKEN
    body = request.body if isinstance(request.body, dict) else {}
    assert "access_token" not in body, "the credential belongs on the query string only"


@pytest.mark.asyncio
@pytest.mark.parametrize("name,call", ALL_CALLS, ids=[n for n, _ in ALL_CALLS])
async def test_no_signature_parameters_are_sent(wire, name, call):
    """WeChat Store takes no signature — see the contract doc (inference)."""
    await call()

    request = wire[0]
    sent = set(request.query) | (set(request.body) if isinstance(request.body, dict) else set())
    assert not (sent & FORBIDDEN_PARAMS), f"{name} sent {sorted(sent & FORBIDDEN_PARAMS)}"


# ═══════════════════════════════════════════════════════════════════════════════
# Request bodies: field names and types
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_order_list_body_uses_a_nested_epoch_range(wire):
    await get_order_list(start_time=T0, end_time=T_1H, order_status="30", page_size=100)

    body = wire[0].json_body()
    assert set(body) == {"create_time_range", "page_size", "status"}
    assert body["create_time_range"] == {"start_time": T0, "end_time": T_1H}
    assert isinstance(body["create_time_range"]["start_time"], int)
    assert isinstance(body["create_time_range"]["end_time"], int)
    assert isinstance(body["page_size"], int)
    assert isinstance(body["status"], int)


@pytest.mark.asyncio
async def test_order_list_body_omits_the_invented_flat_fields(wire):
    """``start_create_time``/``end_create_time``/``page`` earn errcode 40097."""
    await get_order_list(start_time=T0, end_time=T_1H)

    body = wire[0].json_body()
    for invented in ("start_create_time", "end_create_time", "page"):
        assert invented not in body


@pytest.mark.asyncio
async def test_order_list_can_send_the_update_time_range(wire):
    await get_order_list(start_time=T0, end_time=T_1H, time_field="update_time")

    body = wire[0].json_body()
    assert "update_time_range" in body
    assert "create_time_range" not in body


@pytest.mark.asyncio
async def test_aftersale_list_body_is_flat_and_unpaged(wire):
    """A different contract from the order list: flat bounds, no page fields."""
    await get_refund_list(start_time=T0, end_time=T_1H)

    body = wire[0].json_body()
    assert set(body) == {"begin_create_time", "end_create_time"}
    assert body["begin_create_time"] == T0
    assert isinstance(body["begin_create_time"], int)
    assert isinstance(body["end_create_time"], int)


@pytest.mark.asyncio
async def test_product_list_body_carries_page_size_and_no_page(wire):
    await get_product_list(status="5", page_size=30)

    body = wire[0].json_body()
    assert set(body) == {"page_size", "status"}
    assert body["page_size"] == 30
    assert isinstance(body["status"], int)


@pytest.mark.asyncio
async def test_product_list_omits_status_when_unfiltered(wire):
    """There is no "all" member, so an unfiltered query omits the field."""
    await get_product_list()

    assert set(wire[0].json_body()) == {"page_size"}


@pytest.mark.asyncio
async def test_product_detail_body_carries_data_type(wire):
    await get_product_detail(product_id="10000000000001")

    body = wire[0].json_body()
    assert body == {"product_id": "10000000000001", "data_type": 1}


@pytest.mark.asyncio
async def test_coupon_body_carries_all_four_required_fields(wire):
    await list_coupons(status=2, page=1, page_size=200, page_ctx="")

    body = wire[0].json_body()
    assert set(body) == {"status", "page", "page_size", "page_ctx"}
    assert body["status"] == 2
    assert isinstance(body["page"], int)
    assert isinstance(body["page_size"], int)
    assert isinstance(body["page_ctx"], str)


@pytest.mark.asyncio
async def test_dropship_body_invents_nothing(wire):
    """The path is confirmed; its request fields are not. Spec §8: send nothing."""
    await get_supply_order_list()

    assert wire[0].json_body() == {}


# ═══════════════════════════════════════════════════════════════════════════════
# Time-span caps
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_order_list_refuses_a_span_over_seven_days(wire):
    with pytest.raises(ValueError, match="exceeds the documented maximum"):
        await get_order_list(start_time=T0, end_time=T0 + ORDER_TIME_SPAN_MAX_SECONDS + 1)

    assert wire == [], "a request that cannot succeed must not leave the process"


@pytest.mark.asyncio
async def test_order_list_allows_a_span_of_exactly_seven_days(wire):
    await get_order_list(start_time=T0, end_time=T0 + ORDER_TIME_SPAN_MAX_SECONDS)

    assert len(wire) == 1


@pytest.mark.asyncio
async def test_aftersale_list_refuses_a_span_over_24_hours(wire):
    """The after-sale cap is 24h — the order list's 7 days does not apply here."""
    with pytest.raises(ValueError, match="exceeds the documented maximum"):
        await get_refund_list(start_time=T0, end_time=T0 + AFTERSALE_TIME_SPAN_MAX_SECONDS + 1)

    assert wire == []


@pytest.mark.asyncio
async def test_aftersale_list_allows_a_span_of_exactly_24_hours(wire):
    await get_refund_list(start_time=T0, end_time=T0 + AFTERSALE_TIME_SPAN_MAX_SECONDS)

    assert len(wire) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "call",
    [
        lambda: get_order_list(start_time="2024-01-01 00:00:00", end_time="2024-01-02 00:00:00"),
        lambda: get_refund_list(start_time="2024-01-01 00:00:00", end_time="2024-01-01 01:00:00"),
    ],
    ids=["order_list", "aftersale_list"],
)
async def test_date_strings_never_reach_the_wire(wire, call):
    """Both list endpoints want epoch seconds; a string earns errcode 40097."""
    with pytest.raises(ValueError, match="epoch timestamp in seconds"):
        await call()

    assert wire == []


# ═══════════════════════════════════════════════════════════════════════════════
# Status enums
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["10", "12", "13", "20", "21", "30", "100", "250"])
async def test_order_status_enum_members_pass(wire, status):
    await get_order_list(start_time=T0, end_time=T_1H, order_status=status)

    assert wire[0].json_body()["status"] == int(status)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["0", "50", "40", "101"])
async def test_order_status_non_members_never_reach_the_wire(wire, status):
    """``50`` and ``0`` are not WeChat order statuses; the old code used both."""
    with pytest.raises(ValueError, match="not a documented value"):
        await get_order_list(start_time=T0, end_time=T_1H, order_status=status)

    assert wire == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["0", "5", "6", "11"])
async def test_product_status_enum_members_pass(wire, status):
    await get_product_list(status=status)

    assert wire[0].json_body()["status"] == int(status)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["1", "2", "3", "4"])
async def test_product_status_non_members_never_reach_the_wire(wire, status):
    """The old docstring's 1/2/3/4 (上架/下架/审核中/审核失败) are all invented."""
    with pytest.raises(ValueError, match="not a documented value"):
        await get_product_list(status=status)

    assert wire == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [1, 2, 3, 4, 5, 200])
async def test_coupon_status_enum_members_pass(wire, status):
    await list_coupons(status=status)

    assert wire[0].json_body()["status"] == status


@pytest.mark.asyncio
async def test_coupon_status_zero_never_reaches_the_wire(wire):
    """``status`` is mandatory here and 0 is not a member — the old default."""
    with pytest.raises(ValueError, match="not a documented value"):
        await list_coupons(status=0)

    assert wire == []


@pytest.mark.asyncio
async def test_coupon_page_stride_is_capped_at_ten(wire):
    await list_coupons(status=2, page=1)
    with pytest.raises(ValueError, match="may not jump more than 10 pages"):
        await list_coupons(status=2, page=12)

    assert len(wire) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Token: POST /cgi-bin/stable_token
# ═══════════════════════════════════════════════════════════════════════════════


def _expire_token() -> None:
    _wx._stable_access_token = ""
    _wx._token_expires_at = 0.0
    _wx._token_ttl = -1.0


@pytest.mark.asyncio
async def test_token_is_minted_via_stable_token(monkeypatch):
    captured = _install_stub(
        monkeypatch,
        [(200, {"access_token": "minted", "expires_in": 7200}), (200, {"errcode": 0})],
    )
    _expire_token()

    await get_shop_info()

    token_call = captured[0]
    assert token_call.method == "POST"
    assert token_call.host == BASE_HOST
    assert token_call.path == "/cgi-bin/stable_token"
    assert token_call.json_body() == {
        "grant_type": "client_credential",
        "appid": _wx.app_key,
        "secret": _wx.app_secret,
        "force_refresh": False,
    }
    # The credential request itself carries no credential.
    assert token_call.query == {}
    # ...and the business call then uses what was minted.
    assert captured[1].query["access_token"] == "minted"


@pytest.mark.asyncio
async def test_the_legacy_token_endpoint_is_never_called(monkeypatch):
    """``/cgi-bin/token`` mints an isolated credential; we use only one path."""
    captured = _install_stub(
        monkeypatch,
        [(200, {"access_token": "minted", "expires_in": 7200}), (200, {"errcode": 0})],
    )
    _expire_token()

    await get_shop_info()

    assert "/cgi-bin/token" not in {r.path for r in captured}


@pytest.mark.asyncio
async def test_token_ttl_comes_from_expires_in_not_a_constant(monkeypatch):
    """Non-forced mode can hand back the previous token with e.g. 345s left."""
    _install_stub(
        monkeypatch,
        [(200, {"access_token": "minted", "expires_in": 345}), (200, {"errcode": 0})],
    )
    _expire_token()

    before = time.time()
    await get_shop_info()

    assert _wx._token_ttl == 345.0
    assert before + 345 <= _wx._token_expires_at <= time.time() + 345
    assert _wx._token_expires_at < before + 7200, "7200 must not be assumed"


@pytest.mark.asyncio
async def test_short_ttl_is_still_usable(monkeypatch):
    """A 345s TTL must not be swallowed whole by the 300s refresh buffer."""
    _install_stub(
        monkeypatch,
        [
            (200, {"access_token": "minted", "expires_in": 345}),
            (200, {"errcode": 0}),
            (200, {"errcode": 0}),
        ],
    )
    _expire_token()

    await get_shop_info()
    await get_shop_info()

    assert _wx._stable_access_token == "minted"


@pytest.mark.asyncio
async def test_missing_expires_in_is_not_backfilled_with_a_guess(monkeypatch):
    _install_stub(
        monkeypatch,
        [(200, {"access_token": "minted"}), (200, {"errcode": 0})],
    )
    _expire_token()

    await get_shop_info()

    assert _wx._token_expires_at == 0.0, "an absent TTL must not become 7200"


@pytest.mark.asyncio
async def test_token_errcode_triggers_one_forced_refresh(monkeypatch):
    """40001/42001/40014 are the only errcodes worth force_refresh budget."""
    captured = _install_stub(
        monkeypatch,
        [
            (200, {"access_token": "tok1", "expires_in": 7200}),
            (200, {"errcode": 40001, "errmsg": "invalid credential"}),
            (200, {"access_token": "tok2", "expires_in": 7200}),
            (200, {"errcode": 0}),
        ],
    )
    _expire_token()

    await get_shop_info()

    assert [r.path for r in captured] == [
        "/cgi-bin/stable_token",
        "/channels/ec/basics/info/get",
        "/cgi-bin/stable_token",
        "/channels/ec/basics/info/get",
    ]
    assert captured[2].json_body()["force_refresh"] is True
    assert captured[3].query["access_token"] == "tok2"
    assert len(_wx._force_refresh_log) == 1


@pytest.mark.asyncio
async def test_non_token_errcode_does_not_burn_force_refresh(monkeypatch):
    captured = _install_stub(monkeypatch, [(200, {"errcode": 40097, "errmsg": "bad body"})])

    with pytest.raises(CommerceAPIError) as exc:
        await get_shop_info()

    assert exc.value.code == 40097
    assert len(captured) == 1
    assert _wx._force_refresh_log == []


@pytest.mark.asyncio
async def test_force_refresh_respects_the_thirty_second_interval(monkeypatch):
    """Inside the 30s window the error surfaces rather than a second refresh."""
    captured = _install_stub(monkeypatch, [(200, {"errcode": 40001, "errmsg": "expired"})])
    _wx._force_refresh_log = [time.time()]

    with pytest.raises(CommerceAPIError) as exc:
        await get_shop_info()

    assert exc.value.code == 40001
    assert len(captured) == 1, "no second stable_token call may be attempted"


@pytest.mark.asyncio
async def test_force_refresh_respects_the_daily_cap(monkeypatch):
    captured = _install_stub(monkeypatch, [(200, {"errcode": 40001, "errmsg": "expired"})])
    now = time.time()
    _wx._force_refresh_log = [now - 3600 - i for i in range(WeixinStoreMCP.FORCE_REFRESH_DAILY_LIMIT)]

    with pytest.raises(CommerceAPIError) as exc:
        await get_shop_info()

    assert exc.value.code == 40001
    assert len(captured) == 1


@pytest.mark.asyncio
async def test_expired_force_refresh_entries_fall_out_of_the_window(monkeypatch):
    """The cap is per day, so entries older than 24h stop counting."""
    captured = _install_stub(
        monkeypatch,
        [
            (200, {"errcode": 40001, "errmsg": "expired"}),
            (200, {"access_token": "tok2", "expires_in": 7200}),
            (200, {"errcode": 0}),
        ],
    )
    stale = time.time() - 86401
    _wx._force_refresh_log = [stale - i for i in range(WeixinStoreMCP.FORCE_REFRESH_DAILY_LIMIT)]

    await get_shop_info()

    assert len(captured) == 3
    assert captured[1].json_body()["force_refresh"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# HTTP 403 — IP allowlist miss, no errcode
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_http_403_on_a_business_call_is_reported_as_403(monkeypatch):
    """403 has no errcode and no guaranteed JSON body, so status comes first."""
    _install_stub(monkeypatch, [(403, "<html><body>403 Forbidden</body></html>")])

    with pytest.raises(CommerceAPIError) as exc:
        await get_order_list(start_time=T0, end_time=T_1H)

    assert exc.value.code == 403
    assert "IP allowlist" in exc.value.msg


@pytest.mark.asyncio
async def test_http_403_while_minting_a_token_is_reported_as_403(monkeypatch):
    captured = _install_stub(monkeypatch, [(403, "")])
    _expire_token()

    with pytest.raises(CommerceAPIError) as exc:
        await get_shop_info()

    assert exc.value.code == 403
    assert captured[0].path == "/cgi-bin/stable_token"


@pytest.mark.asyncio
async def test_http_403_is_not_mistaken_for_a_token_problem(monkeypatch):
    """A 403 must not trigger a forced refresh — the IP is wrong, not the token."""
    _install_stub(monkeypatch, [(403, "")])

    with pytest.raises(CommerceAPIError):
        await get_shop_info()

    assert _wx._force_refresh_log == []


@pytest.mark.asyncio
async def test_non_json_body_is_reported_rather_than_crashing(monkeypatch):
    _install_stub(monkeypatch, [(502, "<html>bad gateway</html>")])

    with pytest.raises(CommerceAPIError) as exc:
        await get_shop_info()

    assert "non-JSON response" in exc.value.msg
