"""Wire-level capture for contract assertions.

Platform servers are exercised normally; this fixture intercepts the outbound
HTTP call and hands the test the exact bytes we would have put on the wire.
Assertions then compare that against the platform's documented contract.

Why capture rather than mock at ``_call``: the existing unit tests already mock
there, which is precisely why every system-parameter defect in this repo went
unnoticed. The contract layer must sit *below* that boundary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest


@dataclass
class CapturedRequest:
    """What a platform server actually tried to send."""

    method: str = ""
    url: str = ""
    query: dict[str, Any] = field(default_factory=dict)
    body: Any = None
    headers: dict[str, str] = field(default_factory=dict)

    # ── Convenience accessors used by the per-platform assertions ──────────

    @property
    def path(self) -> str:
        """URL path with scheme/host stripped, for path-shape assertions."""
        without_scheme = self.url.split("://", 1)[-1]
        return "/" + without_scheme.partition("/")[2] if "/" in without_scheme else ""

    @property
    def host(self) -> str:
        return self.url.split("://", 1)[-1].partition("/")[0]

    def param(self, name: str) -> Any:
        """Look a parameter up wherever the platform puts it."""
        if name in self.query:
            return self.query[name]
        if isinstance(self.body, dict) and name in self.body:
            return self.body[name]
        return None

    def json_body(self) -> Any:
        if isinstance(self.body, (str, bytes)):
            return json.loads(self.body)
        return self.body


def _install(monkeypatch: pytest.MonkeyPatch, captured: list[CapturedRequest]) -> None:
    """Patch httpx.AsyncClient so every request is recorded, not sent.

    Both construction styles in this repo are covered: servers that reuse the
    base class client via ``_ensure_client`` and servers that build an
    ``httpx.AsyncClient`` inline per call.
    """
    import httpx

    def _record(http_method: str):
        async def _call(url: str, *, params=None, json=None, data=None, headers=None, **_):
            captured.append(
                CapturedRequest(
                    method=http_method,
                    url=str(url),
                    query=dict(params or {}),
                    body=json if json is not None else data,
                    headers=dict(headers or {}),
                )
            )
            response = MagicMock()
            response.status_code = 200
            response.json.return_value = {}
            response.text = "{}"
            return response

        return _call

    class _Recorder:
        def __init__(self, *_, **__):
            self.get = _record("GET")
            self.post = _record("POST")
            self.headers: dict[str, str] = {}

            # 基类 _ensure_client 建连时会先向 BASE_URL 发 HEAD 探针并读 is_closed。
            # 那个探针打的是 API 路由而不是健康端点（多个平台的契约声明都记了这点），
            # 但它确实会发生，录制器必须能承接，否则测试会死在建连而不是断言上。
            # 探针不记入 captured —— 它不是业务请求，记了会让每个平台断言都要绕开它。
            async def _probe(*_a, **_k):
                response = MagicMock()
                response.status_code = 200
                return response

            self.head = _probe
            self.is_closed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def aclose(self):
            return None

    monkeypatch.setattr(httpx, "AsyncClient", _Recorder)


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch):
    """Yield a list that fills with every outbound request the code attempts."""
    captured: list[CapturedRequest] = []
    _install(monkeypatch, captured)
    return captured


@pytest.fixture
def assert_signature_set_matches_sent():
    """Assert the cross-platform invariant: signed set == sent set − {sign}.

    This is the single defect class shared by every signing platform in this
    repo, so it gets one shared assertion rather than eight near-copies.
    """

    def _assert(request: CapturedRequest, *, signed: set[str], sign_field: str = "sign") -> None:
        sent = set(request.query) | (set(request.body) if isinstance(request.body, dict) else set())
        expected = sent - {sign_field}
        missing = expected - signed
        extra = signed - expected
        assert not missing, (
            f"sent but not signed: {sorted(missing)} — the platform will compute a " "different signature than we did"
        )
        assert not extra, f"signed but not sent: {sorted(extra)}"

    return _assert
