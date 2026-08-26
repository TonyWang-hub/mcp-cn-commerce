"""Wire-level contract assertions for 拼多多 (Pinduoduo).

Three things are pinned here, in ascending order of strength:

1. what we put on the wire (gateway, transport, parameter-name set, timestamp
   format) — compared against the official parameter table;
2. the cross-platform invariant that the signed set equals the sent set minus
   ``sign``;
3. our ``_sign`` reproducing the platform's **own published worked example**.

(3) is the hard one: it is arithmetic published by Pinduoduo, so a failure means
the gateway would reject us, no credentials required.

Human-readable contract declaration with official sources:
``docs/api-contracts/pinduoduo.md``.
"""

from __future__ import annotations

import os
import time
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

os.environ.setdefault("PINDUODUO_CLIENT_ID", "test_client_id")
os.environ.setdefault("PINDUODUO_CLIENT_SECRET", "test_client_secret")
os.environ.setdefault("PINDUODUO_ACCESS_TOKEN", "test_access_token")

from servers.pinduoduo import server as pdd_server
from servers.pinduoduo.server import PinduoduoMCP
from tests.contract.conftest import CapturedRequest
from tests.contract.vectors import VERIFIED, SignatureVector

# ── Official worked example ─────────────────────────────────────────────────

_VECTOR: SignatureVector = next(v for v in VERIFIED if v.platform == "pinduoduo")

#: The example's parameters, transcribed one by one from the official doc's
#: concatenated string. ``test_vector_params_reconstruct_official_payload``
#: proves the transcription is faithful, so nothing here is guesswork.
_VECTOR_PARAMS: dict[str, str] = {
    "access_token": "asd78172s8ds9a921j9qqwda12312w1w21211",
    "client_id": "1",
    "data_type": "XML",
    "order_status": "1",
    "page": "1",
    "page_size": "10",
    "timestamp": "1480411125",
    "type": "pdd.order.number.list.get",
}

# ── Contract constants (official parameter table) ───────────────────────────

GATEWAY = "https://gw-api.pinduoduo.com/api/router"

#: System parameters we must send on every call, per the official table.
SYSTEM_PARAMS = {"type", "client_id", "timestamp", "data_type", "access_token", "sign"}

#: ``sign_method`` does not appear in the official parameter table, so sending
#: it would add an unsignable-by-contract parameter. It must stay absent.
FORBIDDEN_PARAMS = {"sign_method", "format", "v", "version"}

#: Documented clock tolerance: 10 minutes (``pdd.time.get`` exists for aligning).
TIMESTAMP_TOLERANCE_S = 600

#: Every API type this server is allowed to address, post-correction.
EXPECTED_API_TYPES = {
    "pdd.order.list.get",
    "pdd.order.information.get",
    "pdd.goods.list.get",
    "pdd.goods.detail.get",
    "pdd.refund.list.increment.get",
    "pdd.refund.information.get",
    "pdd.logistics.ordertrace.get",
    "pdd.logistics.companies.get",
    "pdd.mall.info.get",
    "pdd.promotion.merchant.coupon.list.get",
}

#: Names that must never reappear: three were wrong, three were never real.
RETIRED_API_TYPES = {
    "pdd.logistics.trace.query",
    "pdd.refund.list.get",
    "pdd.promotion.list.get",
    "pdd.goods.search",
    "pdd.goods.comments.get",
    "pdd.ddk.goods.search",
}

#: (tool, kwargs, expected API type, expected business parameter names).
TOOL_CALLS: list[tuple[Callable[..., Awaitable[str]], dict[str, Any], str, set[str]]] = [
    (
        pdd_server.get_order_list,
        {"start_time": "2024-01-01 00:00:00", "end_time": "2024-01-31 23:59:59"},
        "pdd.order.list.get",
        {"start_created_at", "end_created_at", "page", "page_size"},
    ),
    (
        pdd_server.get_order_detail,
        {"order_sn": "231215-1234567890123"},
        "pdd.order.information.get",
        {"order_sn"},
    ),
    (pdd_server.get_product_list, {}, "pdd.goods.list.get", {"page", "page_size"}),
    (
        pdd_server.get_product_detail,
        {"goods_id": "987654321"},
        "pdd.goods.detail.get",
        {"goods_id"},
    ),
    (
        pdd_server.get_refund_list,
        {"start_time": "2024-01-01 00:00:00", "end_time": "2024-01-31 23:59:59"},
        "pdd.refund.list.increment.get",
        {"start_created_at", "end_created_at", "page", "page_size"},
    ),
    (
        pdd_server.get_refund_detail,
        {"refund_id": "RF123456789"},
        "pdd.refund.information.get",
        {"refund_id"},
    ),
    (
        pdd_server.get_logistics_tracking,
        {"order_sn": "231215-1234567890123"},
        "pdd.logistics.ordertrace.get",
        {"order_sn"},
    ),
    (pdd_server.list_logistics_companies, {}, "pdd.logistics.companies.get", set()),
    (pdd_server.get_shop_info, {}, "pdd.mall.info.get", set()),
    (
        pdd_server.list_promotions,
        {},
        "pdd.promotion.merchant.coupon.list.get",
        {"page", "page_size"},
    ),
]

_IDS = [api_type for _, _, api_type, _ in TOOL_CALLS]


# ── Helpers ─────────────────────────────────────────────────────────────────


def _sent(request: CapturedRequest) -> dict[str, str]:
    """The form body Pinduoduo receives — everything travels in POST data."""
    assert isinstance(request.body, dict), "PDD sends all parameters as POST form data"
    return request.body


def _signed_param_names(client: PinduoduoMCP, sent: dict[str, str]) -> set[str]:
    """Derive which parameters actually influenced the signature.

    Derived by perturbation rather than by re-implementing the filter, so this
    stays honest if ``_sign``'s exclusion rules ever change.
    """
    payload = {k: v for k, v in sent.items() if k != "sign"}
    baseline = client._sign(payload)
    assert baseline == sent["sign"], (
        "recomputing the signature over the sent parameters does not reproduce the "
        "signature we sent — signing and sending disagree"
    )

    signed = set()
    for name in payload:
        probe = dict(payload)
        probe[name] = probe[name] + "X"
        if client._sign(probe) != baseline:
            signed.add(name)
    return signed


async def _capture(tool, kwargs, wire) -> CapturedRequest:
    await tool(**kwargs)
    assert len(wire) == 1, f"expected exactly one outbound request, got {len(wire)}"
    return wire[0]


# ── The official vector (hardest assertion) ─────────────────────────────────


def test_vector_params_reconstruct_official_payload() -> None:
    """Our transcription of the official example must rebuild its exact string.

    Without this, ``test_our_sign_reproduces_official_vector`` could pass on a
    parameter set that merely happens to hash correctly.
    """
    rebuilt = "".join(f"{k}{_VECTOR_PARAMS[k]}" for k in sorted(_VECTOR_PARAMS))
    assert rebuilt == _VECTOR.payload


def test_our_sign_reproduces_official_vector() -> None:
    """``PinduoduoMCP._sign`` must agree with Pinduoduo's own arithmetic."""
    client = PinduoduoMCP(
        app_key=_VECTOR_PARAMS["client_id"],
        app_secret=_VECTOR.secret,
        access_token=_VECTOR_PARAMS["access_token"],
    )
    assert (
        client._sign(_VECTOR_PARAMS) == _VECTOR.expected
    ), f"disagrees with the official worked example ({_VECTOR.source})"


def test_official_vector_timestamp_is_unix_seconds() -> None:
    """The example's own timestamp is the format authority: 10-digit seconds."""
    assert len(_VECTOR_PARAMS["timestamp"]) == 10
    assert _VECTOR_PARAMS["timestamp"] == "1480411125"


# ── Transport and system parameters ─────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool", "kwargs", "api_type", "biz_params"), TOOL_CALLS, ids=_IDS)
async def test_request_shape(tool, kwargs, api_type, biz_params, wire) -> None:
    """POST form data to the single router gateway, nothing in the query string."""
    request = await _capture(tool, kwargs, wire)

    assert request.method == "POST"
    assert request.url == GATEWAY
    assert request.query == {}, "PDD carries no parameters in the query string"
    assert _sent(request)["type"] == api_type


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool", "kwargs", "api_type", "biz_params"), TOOL_CALLS, ids=_IDS)
async def test_parameter_name_set_is_exact(tool, kwargs, api_type, biz_params, wire) -> None:
    """Sending too much is as much a defect as sending too little."""
    sent = _sent(await _capture(tool, kwargs, wire))

    assert set(sent) == SYSTEM_PARAMS | biz_params
    assert not (
        set(sent) & FORBIDDEN_PARAMS
    ), f"{sorted(set(sent) & FORBIDDEN_PARAMS)} is not in the official parameter table"


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool", "kwargs", "api_type", "biz_params"), TOOL_CALLS, ids=_IDS)
async def test_timestamp_is_unix_seconds(tool, kwargs, api_type, biz_params, wire) -> None:
    """UNIX seconds, 10 digits — the previous milliseconds value was 45k years out."""
    before = int(time.time())
    sent = _sent(await _capture(tool, kwargs, wire))
    after = int(time.time())

    timestamp = sent["timestamp"]
    assert timestamp.isdigit(), f"timestamp must be a bare integer, got {timestamp!r}"
    assert len(timestamp) == 10, (
        f"expected 10-digit UNIX seconds, got {len(timestamp)} digits ({timestamp!r}) — "
        "13 digits means milliseconds crept back in"
    )

    value = int(timestamp)
    assert before <= value <= after, "timestamp must be the current clock reading"
    assert abs(value - after) <= TIMESTAMP_TOLERANCE_S, "outside the 10-minute tolerance"


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool", "kwargs", "api_type", "biz_params"), TOOL_CALLS, ids=_IDS)
async def test_signed_set_equals_sent_set(
    tool, kwargs, api_type, biz_params, wire, assert_signature_set_matches_sent
) -> None:
    """Signed set == sent set − {sign}: the defect class shared by every platform."""
    request = await _capture(tool, kwargs, wire)
    sent = _sent(request)

    # Precondition for the perturbation-based derivation below, and a real
    # hazard in its own right: the shared _sign drops empty-valued parameters,
    # while PDD requires every sent parameter to participate. As long as no
    # empty value is ever sent, the two rules agree.
    empty = sorted(k for k, v in sent.items() if v == "")
    assert not empty, f"empty-valued parameters would be sent but not signed: {empty}"

    assert_signature_set_matches_sent(request, signed=_signed_param_names(pdd_server.pdd, sent))


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool", "kwargs", "api_type", "biz_params"), TOOL_CALLS, ids=_IDS)
async def test_signature_is_uppercase_md5(tool, kwargs, api_type, biz_params, wire) -> None:
    """32 uppercase hex characters, per the official algorithm description."""
    sign = _sent(await _capture(tool, kwargs, wire))["sign"]

    assert len(sign) == 32
    assert sign == sign.upper()
    assert all(c in "0123456789ABCDEF" for c in sign)


# ── Endpoint inventory ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_type_inventory_matches_official_names(wire) -> None:
    """Every type we address exists officially; no retired name comes back."""
    for tool, kwargs, _, _ in TOOL_CALLS:
        await tool(**kwargs)

    sent_types = {request.body["type"] for request in wire}

    assert sent_types == EXPECTED_API_TYPES
    assert not (sent_types & RETIRED_API_TYPES)
