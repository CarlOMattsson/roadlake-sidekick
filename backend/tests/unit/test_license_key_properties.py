"""Fuzzing the license key (D-081): whatever is pasted, only a closed rejection comes back, and
every key the licensor signs verifies to what was signed, and to nothing after one edit.

The keys are generated here; no real licensor key is read.
"""

from __future__ import annotations

import base64
import secrets
from datetime import date

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from hypothesis import given, settings
from hypothesis import strategies as st

from sidekick.license.key import (
    KEY_PREFIX,
    KINDS,
    MAX_KEY_ID_LENGTH,
    MAX_LICENSEE_LENGTH,
    KeyRejected,
    LicensePayload,
    evaluate,
    sign_key,
    verify_key,
)

OWNER = Ed25519PrivateKey.generate()
PUBLIC = OWNER.public_key()
TODAY = date(2026, 11, 15)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


_PRINTABLE = st.characters(blacklist_categories=("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"))


def _printable(max_size: int) -> st.SearchStrategy[str]:
    """Text the payload accepts: printable, not blank. Long names outside ASCII are drawn on
    purpose, since they are what makes a key long."""

    return st.one_of(
        st.text(_PRINTABLE, min_size=1, max_size=max_size),
        st.text(
            st.characters(min_codepoint=0x80, blacklist_categories=("Cc", "Cf", "Cs", "Co", "Cn")),
            min_size=max_size // 2,
            max_size=max_size,
        ),
    ).filter(lambda text: text.isprintable() and bool(text.strip()))


_days = st.dates(min_value=date(2000, 1, 1), max_value=date(2200, 12, 31))


@st.composite
def payloads(draw: st.DrawFn, key_id: st.SearchStrategy[str]) -> LicensePayload:
    issued = draw(_days)
    expires = draw(st.dates(min_value=issued, max_value=date(9999, 12, 31)))
    return LicensePayload(
        draw(st.sampled_from(KINDS)),
        draw(_printable(MAX_LICENSEE_LENGTH)),
        issued,
        expires,
        draw(key_id),
    )


# The key id the licensor's tool gives every key (`secrets.token_hex(6)`).
_issued_key_id = st.builds(lambda: secrets.token_hex(6))

# Pasted text: anything, or something shaped like a key around random parts.
_pasted = st.one_of(
    st.text(max_size=300),
    st.builds(
        lambda prefix, payload, signature: f"{prefix}.{payload}.{signature}",
        st.sampled_from([KEY_PREFIX, "ROADLAKE-2", "roadlake-1", ""]),
        st.one_of(st.binary(max_size=300).map(_b64), st.text(max_size=40)),
        st.one_of(st.binary(min_size=64, max_size=64).map(_b64), st.text(max_size=90)),
    ),
)


@given(_pasted)
@settings(max_examples=500)
def test_any_pasted_text_is_rejected_with_a_closed_reason(raw: str) -> None:
    with pytest.raises(KeyRejected) as rejected:
        verify_key(raw, PUBLIC)
    assert rejected.value.rejection in {
        "malformed",
        "unsupported_version",
        "bad_signature",
        "bad_payload",
    }
    evaluation = evaluate(raw, PUBLIC, TODAY)
    assert evaluation.view.state == "invalid"
    assert evaluation.view.as_json() == {"state": "invalid"}


@given(payloads(_issued_key_id), st.sampled_from(["", "\n", "  \n  ", "\r\n\t"]))
@settings(max_examples=300)
def test_every_issued_key_verifies_to_what_was_signed(payload: LicensePayload, wrap: str) -> None:
    key = sign_key(OWNER, payload)
    # A key pasted wrapped over lines, or with spaces around it, still reads.
    wrapped = wrap + wrap.join(key[i : i + 60] for i in range(0, len(key), 60)) + wrap

    verified = verify_key(wrapped, PUBLIC)

    assert verified == LicensePayload(
        payload.kind, payload.licensee.strip(), payload.issued, payload.expires, payload.key_id
    )
    state = evaluate(key, PUBLIC, TODAY).view.state
    assert state == ("expired" if payload.expires < TODAY else "licensed")


@given(payloads(_printable(MAX_KEY_ID_LENGTH)))
@settings(max_examples=200)
def test_a_key_is_either_signed_so_it_verifies_or_refused(payload: LicensePayload) -> None:
    try:
        key = sign_key(OWNER, payload)
    except ValueError:
        return
    assert verify_key(key, PUBLIC).key_id == payload.key_id


@given(payloads(_issued_key_id), st.data())
@settings(max_examples=300)
def test_one_changed_character_is_never_accepted(
    payload: LicensePayload, data: st.DataObject
) -> None:
    key = sign_key(OWNER, payload)
    index = data.draw(st.integers(min_value=0, max_value=len(key) - 1))
    replacement = data.draw(
        st.characters(blacklist_categories=("Zs", "Zl", "Zp", "Cc")).filter(
            lambda char: char != key[index] and not char.isspace()
        )
    )
    forged = key[:index] + replacement + key[index + 1 :]

    with pytest.raises(KeyRejected):
        verify_key(forged, PUBLIC)


@given(payloads(_issued_key_id))
@settings(max_examples=50)
def test_a_key_signed_by_anyone_else_is_a_bad_signature(payload: LicensePayload) -> None:
    key = sign_key(Ed25519PrivateKey.generate(), payload)

    with pytest.raises(KeyRejected) as rejected:
        verify_key(key, PUBLIC)
    assert rejected.value.rejection == "bad_signature"
