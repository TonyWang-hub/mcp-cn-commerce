"""Assert our signing agrees with the platforms' own published arithmetic.

These are hard assertions: a failure means we would be rejected by the gateway.
"""

from __future__ import annotations

import hashlib

import pytest

from tests.contract.vectors import PENDING, VERIFIED, SignatureVector


def _md5_wrapped(secret: str, payload: str) -> str:
    """``upper(md5(secret + payload + secret))`` — the shared 淘宝/京东/拼多多 form."""
    return hashlib.md5((secret + payload + secret).encode()).hexdigest().upper()


@pytest.mark.parametrize("vector", VERIFIED, ids=lambda v: v.platform)
def test_official_vector_reproduces(vector: SignatureVector) -> None:
    """The official expected value must reproduce exactly."""
    assert vector.algorithm == "upper(md5(secret + payload + secret))", (
        f"{vector.platform}: unexpected algorithm {vector.algorithm!r}; "
        "add a branch here rather than loosening the assertion"
    )
    assert _md5_wrapped(vector.secret, vector.payload) == vector.expected, (
        f"{vector.platform} signature disagrees with the platform's own worked "
        f"example ({vector.source})"
    )


@pytest.mark.parametrize("vector", PENDING, ids=lambda v: v.platform)
def test_pending_vector_is_documented_not_guessed(vector: SignatureVector) -> None:
    """A vector we could not reproduce must stay explicitly unresolved.

    Guarding this keeps someone from quietly inventing an input string that
    happens to hash to the expected value.
    """
    assert not vector.verified
    assert not vector.payload, (
        f"{vector.platform}: a payload appeared for a pending vector. If it was "
        "recovered from the official source, move the vector into VERIFIED and "
        "let test_official_vector_reproduces assert it."
    )
    assert vector.notes, f"{vector.platform}: pending vectors must record why"
