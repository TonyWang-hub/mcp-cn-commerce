"""Wire-level contract assertions for Taobao Open Platform (TOP).

These tests read the exact bytes the server would have put on the wire and
compare them against TOP's documented contract — gateway host, the *complete*
public-parameter set, the credential's parameter name, the timestamp format, and
the set of parameters that participate in the signature.

They sit below the boundary the unit tests mock (``taobao._request``), which is
exactly where every system-parameter defect in this repo hid: a test that stubs
``_request`` can never notice that the credential is sent as ``access_token``
instead of ``session``, or that ``sign_method`` is sent but not signed.

Sources for every expectation are recorded in ``docs/api-contracts/taobao.md``.
"""

from __future__ import annotations

import hashlib
import os
import re

import pytest

os.environ.setdefault("TAOBAO_APP_KEY", "test_key")
os.environ.setdefault("TAOBAO_APP_SECRET", "test_secret")
os.environ.setdefault("TAOBAO_ACCESS_TOKEN", "test_token")

from servers.taobao.server import (  # noqa: E402
    TOP_TIMESTAMP_FORMAT,
    get_increment_orders,
    get_order_list,
    get_product_detail,
    get_product_list,
    get_seller_info,
    get_shop_info,
    taobao,
)

APP_KEY = "wire_app_key"
APP_SECRET = "wire_app_secret"
ACCESS_TOKEN = "wire_session"

#: ``yyyy-MM-dd HH:mm:ss``. Deliberately a literal pattern rather than something
#: derived from the format string: the point is to pin the shape TOP documents,
#: not to agree with whatever the code happens to produce.
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")

#: TOP public parameters this client always sends. ``sign`` is included: it is
#: sent, it just does not sign itself.
PUBLIC_PARAMS = {
    "method",
    "app_key",
    "session",
    "timestamp",
    "format",
    "v",
    "sign_method",
    "sign",
}


@pytest.fixture(autouse=True)
def fixed_credentials():
    """Pin credentials so signature arithmetic in these tests is deterministic."""
    original = (taobao.app_key, taobao.app_secret, taobao.access_token)
    taobao.app_key, taobao.app_secret, taobao.access_token = APP_KEY, APP_SECRET, ACCESS_TOKEN
    yield
    taobao.app_key, taobao.app_secret, taobao.access_token = original
    # The pooled client now holds the capture double; drop it so it cannot leak
    # into any later test.
    taobao._client = None


def _reference_sign(secret: str, params: dict[str, str]) -> str:
    """TOP md5 signature, implemented independently of the production code.

    ``upper(md5(secret + Σ(key + value, keys ASCII-ascending) + secret))``, no
    separators, UTF-8, skipping any parameter whose key or value is empty.
    Written from the documented rule rather than by calling ``taobao._sign`` so
    that a wrong implementation cannot agree with itself.
    """
    payload = "".join(f"{k}{params[k]}" for k in sorted(params) if k and params[k] != "")
    return hashlib.md5((secret + payload + secret).encode("utf-8")).hexdigest().upper()


def _sent(request) -> dict[str, str]:
    """Every parameter actually transmitted, wherever the platform puts it."""
    body = request.body if isinstance(request.body, dict) else {}
    return {**request.query, **body}


# ── Gateway and transport ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_requests_go_to_the_main_router_gateway(wire):
    """The default host is the one the official access guide publishes."""
    await get_seller_info()

    assert len(wire) == 1
    request = wire[0]
    assert request.host == "gw.api.taobao.com"
    assert request.path == "/router/rest"
    assert request.method == "POST"


@pytest.mark.asyncio
async def test_legacy_gateway_stays_available_for_pinned_callers(wire, monkeypatch):
    """The other officially published host must remain usable.

    The relationship between the two hosts is undocumented, so this asserts only
    that overriding BASE_URL still works — not that they are aliases.
    """
    monkeypatch.setattr(taobao, "BASE_URL", taobao.LEGACY_BASE_URL)

    await get_seller_info()

    assert wire[0].host == "eco.taobao.com"
    assert wire[0].path == "/router/rest"


# ── Endpoints ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_retired_endpoints_are_not_on_the_wire(wire):
    """``taobao.item.get`` (2018-01-22) and ``taobao.shop.get`` (2019-04-08) are gone.

    Asserted at the wire level rather than by reading the source, because these
    method names also live in fixtures and docs that drift independently.
    """
    await get_product_detail(num_iid="10000001")
    await get_shop_info()

    methods = [_sent(request)["method"] for request in wire]
    assert methods == ["taobao.item.seller.get", "taobao.shop.seller.get"]


# ── Parameter set ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_parameter_set_is_exactly_the_documented_one(wire):
    """Set equality, so both a missing and an unexpected parameter fail.

    An extra parameter is not harmless on TOP: it changes the signature base
    string, and undeclared business parameters are how "works in the doc,
    rejects on the gateway" bugs start.
    """
    await get_product_detail(num_iid="10000001")

    assert set(_sent(wire[0])) == PUBLIC_PARAMS | {"num_iid"}


@pytest.mark.asyncio
async def test_credential_is_named_session_not_access_token(wire):
    """TOP's public-parameter table has no ``access_token``; it is ``session``."""
    await get_seller_info()

    sent = _sent(wire[0])
    assert sent["session"] == ACCESS_TOKEN
    assert "access_token" not in sent


@pytest.mark.asyncio
async def test_response_format_and_version_are_sent(wire):
    """``format`` defaults to xml server-side, and ``v`` is required."""
    await get_seller_info()

    sent = _sent(wire[0])
    assert sent["format"] == "json"
    assert sent["v"] == "2.0"


@pytest.mark.asyncio
async def test_trade_queries_opt_into_has_next_paging(wire):
    """Both trade queries carry the platform's recommended paging flag."""
    await get_order_list(start_time="2024-01-01 00:00:00", end_time="2024-01-31 23:59:59")
    await get_increment_orders(start_time="2024-01-01 00:00:00", end_time="2024-01-31 23:59:59")

    assert [_sent(r)["use_has_next"] for r in wire] == ["true", "true"]


@pytest.mark.asyncio
async def test_use_has_next_is_not_sprayed_across_every_list_call(wire):
    """Only endpoints whose official parameter table declares it receive it."""
    await get_product_list()

    assert "use_has_next" not in _sent(wire[0])


# ── Timestamp ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_timestamp_uses_the_documented_wall_clock_format(wire):
    """``yyyy-MM-dd HH:mm:ss`` — not epoch milliseconds, not ISO 8601."""
    await get_seller_info()

    timestamp = _sent(wire[0])["timestamp"]
    assert TIMESTAMP_RE.match(timestamp), f"not TOP's timestamp shape: {timestamp!r}"


@pytest.mark.asyncio
async def test_timestamp_is_beijing_time_regardless_of_process_timezone(wire):
    """GMT+8 must be explicit: containers routinely run with TZ=UTC.

    Reading it off the process clock would put every request eight hours outside
    the gateway's 10-minute tolerance window.
    """
    import time as time_module
    from datetime import datetime, timedelta, timezone

    # Restored by hand rather than via monkeypatch: the process timezone lives in
    # a C-level cache that only tzset() refreshes, so leaving it set would leak
    # UTC into every later test in the session.
    tzset = getattr(time_module, "tzset", None)
    previous_tz = os.environ.get("TZ")
    os.environ["TZ"] = "UTC"
    if tzset:
        tzset()
    try:
        await get_seller_info()
    finally:
        if previous_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous_tz
        if tzset:
            tzset()

    sent_at = datetime.strptime(_sent(wire[0])["timestamp"], TOP_TIMESTAMP_FORMAT)
    beijing_now = datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None)
    assert abs(beijing_now - sent_at) < timedelta(minutes=1)


# ── Signature ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_signature_matches_an_independent_implementation(wire):
    """The transmitted ``sign`` must reproduce from the documented formula.

    This is what catches ``sign_method`` being sent but not signed: the
    reference implementation signs every transmitted parameter except ``sign``,
    so any parameter the production code leaves out yields a different digest.
    """
    await get_order_list(start_time="2024-01-01 00:00:00", end_time="2024-01-31 23:59:59")

    sent = _sent(wire[0])
    signed = {k: v for k, v in sent.items() if k != "sign"}
    assert sent["sign"] == _reference_sign(APP_SECRET, signed)


@pytest.mark.asyncio
async def test_sign_method_participates_in_the_signature(wire):
    """Called out separately because this defect is the reason the WP exists.

    Signing the same parameters *without* ``sign_method`` must not reproduce the
    transmitted signature — otherwise we are back to the base-class behaviour of
    computing the digest before adding the parameter.
    """
    await get_seller_info()

    sent = _sent(wire[0])
    assert sent["sign_method"] == "md5"
    without_sign_method = {k: v for k, v in sent.items() if k not in ("sign", "sign_method")}
    assert sent["sign"] != _reference_sign(APP_SECRET, without_sign_method)


@pytest.mark.asyncio
async def test_signed_set_equals_sent_set_minus_sign(wire, assert_signature_set_matches_sent):
    """The cross-platform invariant, via the shared assertion.

    The signed set is not taken on trust: ``_reference_sign`` reproducing the
    transmitted digest over exactly ``sent − {sign}`` is what establishes it.
    """
    await get_product_detail(num_iid="10000001")

    request = wire[0]
    sent = _sent(request)
    signed = {k: v for k, v in sent.items() if k != "sign"}
    assert sent["sign"] == _reference_sign(APP_SECRET, signed), "signed set is not sent − {sign}"

    assert_signature_set_matches_sent(request, signed=set(signed))


def test_key_ordering_is_ascii_code_point_not_alphabetic():
    """``foo`` < ``foo_bar`` < ``foobar``, because ``_`` (0x5F) < ``b`` (0x62).

    A locale-aware or case-folding sort silently produces a different base string
    and a signature the gateway rejects with ``25 Invalid Signature``.
    """
    params = {"foobar": "4", "foo_bar": "3", "foo": "1", "Foo": "0"}

    assert sorted(params) == ["Foo", "foo", "foo_bar", "foobar"]


def test_empty_valued_parameters_are_skipped_entirely():
    """A parameter with an empty value contributes neither key nor value.

    Enforced by the official SDK although the prose does not say so; skipping
    only the value would leave a stray key in the base string.
    """
    with_empty = {"a": "1", "b": "", "c": "3"}
    without_empty = {"a": "1", "c": "3"}

    assert _reference_sign(APP_SECRET, with_empty) == _reference_sign(APP_SECRET, without_empty)


@pytest.mark.asyncio
async def test_empty_valued_parameters_are_not_transmitted_either(wire, assert_signature_set_matches_sent):
    """Dropped from the wire, not just from the base string.

    Signing skips them, so transmitting one would break the invariant: the
    gateway would sign a parameter we did not.
    """
    await taobao._request("POST", "", params={"method": "taobao.user.seller.get", "blank": ""})

    sent = _sent(wire[0])
    assert "blank" not in sent
    assert_signature_set_matches_sent(wire[0], signed=set(k for k in sent if k != "sign"))


@pytest.mark.asyncio
async def test_production_signer_agrees_with_the_reference_on_empty_values(wire):
    """The server's own signer must also skip empty-valued parameters."""
    await get_seller_info()

    sent = _sent(wire[0])
    signed = {k: v for k, v in sent.items() if k != "sign"}
    assert taobao._sign({**signed, "padding": ""}) == _reference_sign(APP_SECRET, signed)
