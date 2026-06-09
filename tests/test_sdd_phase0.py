"""SDD Phase 0 regression tests: signature canonicalization + input validation.

Covers Item 2 of docs/specs/sdd-items-1-5.md:
- ``canonicalize_sign_value`` produces deterministic strings for dict/list/bool/None.
- ``_sign`` is stable regardless of dict ordering / object identity.
- ``_request`` rejects injection-style payloads before any network call.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shared.cn_commerce_base import (
    CommerceMCPBase,
    SignMethod,
    canonicalize_sign_value,
)


class _DummyClient(CommerceMCPBase):
    BASE_URL = "https://example.test/api/"
    sign_method = SignMethod.MD5


class TestCanonicalizeSignValue:
    def test_none_is_empty_string(self):
        assert canonicalize_sign_value(None) == ""

    def test_bool_is_lowercase_word(self):
        assert canonicalize_sign_value(True) == "true"
        assert canonicalize_sign_value(False) == "false"

    def test_dict_is_sorted_compact_json(self):
        # Same logical dict, different insertion order -> identical output.
        a = canonicalize_sign_value({"b": 1, "a": 2})
        b = canonicalize_sign_value({"a": 2, "b": 1})
        assert a == b == '{"a":2,"b":1}'

    def test_list_is_compact_json(self):
        assert canonicalize_sign_value([1, 2, 3]) == "[1,2,3]"

    def test_scalar_passthrough(self):
        assert canonicalize_sign_value(42) == "42"
        assert canonicalize_sign_value("x") == "x"


class TestSignStability:
    def test_sign_is_order_independent_for_nested_values(self):
        client = _DummyClient(app_key="k", app_secret="s", access_token="t")
        sig1 = client._sign({"filter": {"b": 1, "a": 2}, "ids": [3, 1, 2]})
        sig2 = client._sign({"ids": [3, 1, 2], "filter": {"a": 2, "b": 1}})
        assert sig1 == sig2

    def test_sign_differs_when_value_changes(self):
        client = _DummyClient(app_key="k", app_secret="s")
        assert client._sign({"a": [1, 2]}) != client._sign({"a": [1, 3]})


class TestRequestInputValidation:
    @pytest.mark.asyncio
    async def test_sql_injection_rejected(self):
        client = _DummyClient(app_key="k", app_secret="s", access_token="t")
        with pytest.raises(ValueError):
            await client._request("GET", "orders", params={"q": "1' OR '1'='1"})

    @pytest.mark.asyncio
    async def test_path_traversal_rejected(self):
        client = _DummyClient(app_key="k", app_secret="s")
        with pytest.raises(ValueError):
            await client._request("GET", "orders", params={"file": "../../etc/passwd"})

    @pytest.mark.asyncio
    async def test_validation_can_be_disabled(self):
        # With validation off, the suspicious value must pass the validation gate
        # (it will then fail later at the network layer, which is fine — we only
        # assert that no ValueError is raised by the validator).
        client = _DummyClient(app_key="k", app_secret="s", validate_input=False)
        try:
            await client._request("GET", "orders", params={"q": "1' OR '1'='1"})
        except ValueError as exc:  # pragma: no cover - must not be a validation error
            pytest.fail(f"validation should be disabled, got ValueError: {exc}")
        except Exception:
            pass  # network/HTTP errors are expected and acceptable here
