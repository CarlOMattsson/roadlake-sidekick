"""License keys (D-081): signed, checked offline, no database and no clock of their own."""

from __future__ import annotations

import base64
import json
from datetime import date
from html import unescape

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sidekick.license.key import (
    KEY_PREFIX,
    UNLICENSED,
    KeyRejected,
    LicensePayload,
    LicenseView,
    evaluate,
    parse_public_key,
    public_key_text,
    sign_key,
    verify_key,
)
from sidekick.license.public_key import PLACEHOLDER_PUBLIC_KEY
from sidekick.mcp.app_meta import with_app_context, with_license

OWNER = Ed25519PrivateKey.generate()
OTHER = Ed25519PrivateKey.generate()
PAYLOAD = LicensePayload("personal", "Kalle Anka", date(2026, 11, 9), date(2027, 11, 9), "abc123")
HTML = "<!doctype html><html><head></head><body></body></html>"


def sign(payload: LicensePayload = PAYLOAD, key: Ed25519PrivateKey = OWNER) -> str:
    return sign_key(key, payload)


def tamper(key_text: str, **changes: object) -> str:
    """The key with its payload edited but the old signature kept."""

    prefix, encoded, signature = key_text.split(".")
    padded = encoded + "=" * (-len(encoded) % 4)
    body = json.loads(base64.urlsafe_b64decode(padded))
    body.update(changes)
    edited = base64.urlsafe_b64encode(json.dumps(body).encode()).rstrip(b"=").decode()
    return f"{prefix}.{edited}.{signature}"


def test_a_signed_key_verifies_with_the_matching_public_key() -> None:
    text = sign()
    assert text.startswith(f"{KEY_PREFIX}.") and text.count(".") == 2
    assert text.isascii() and " " not in text
    assert verify_key(text, OWNER.public_key()) == PAYLOAD


def test_the_key_survives_being_pasted_wrapped_over_lines() -> None:
    text = sign()
    wrapped = f"  {text[:40]}\n{text[40:120]}\r\n{text[120:]}\n"
    assert verify_key(wrapped, OWNER.public_key()) == PAYLOAD


def test_a_longer_tier_is_just_a_later_expiry() -> None:
    five_years = LicensePayload("org", "Förening X", date(2026, 11, 9), date(2031, 11, 9), "k5")
    view = evaluate(sign(five_years), OWNER.public_key(), date(2030, 1, 1)).view
    assert view == LicenseView("licensed", "Förening X", "org", date(2031, 11, 9))


def test_a_tampered_payload_is_refused() -> None:
    for edited in (
        tamper(sign(), expires="2099-01-01"),
        tamper(sign(), licensee="Någon Annan"),
        tamper(sign(), kind="org"),
    ):
        with pytest.raises(KeyRejected) as refused:
            verify_key(edited, OWNER.public_key())
        assert refused.value.rejection == "bad_signature"


def test_the_wrong_public_key_refuses() -> None:
    with pytest.raises(KeyRejected) as refused:
        verify_key(sign(), OTHER.public_key())
    assert refused.value.rejection == "bad_signature"


def test_a_changed_signature_or_prefix_is_refused() -> None:
    text = sign()
    prefix, encoded, signature = text.split(".")
    flipped = ("B" if signature[0] != "B" else "C") + signature[1:]
    with pytest.raises(KeyRejected) as bad:
        verify_key(f"{prefix}.{encoded}.{flipped}", OWNER.public_key())
    assert bad.value.rejection == "bad_signature"
    # The format version is part of what is signed, so the prefix cannot be swapped.
    with pytest.raises(KeyRejected) as future:
        verify_key(f"ROADLAKE-2.{encoded}.{signature}", OWNER.public_key())
    assert future.value.rejection == "unsupported_version"


ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


def respelled(part: str) -> str:
    """The same bytes spelled non-canonically: the spare low bits of the last character set."""

    return part[:-1] + ALPHABET[ALPHABET.index(part[-1]) | 1]


def test_a_signature_spelled_non_canonically_is_refused_though_it_decodes_alike() -> None:
    prefix, encoded, signature = sign().split(".")
    assert len(signature) % 4 == 2  # 64 bytes leave four spare bits in the last character
    assert respelled(signature) != signature
    assert base64.urlsafe_b64decode(respelled(signature) + "==") == base64.urlsafe_b64decode(
        signature + "=="
    )
    with pytest.raises(KeyRejected) as refused:
        verify_key(f"{prefix}.{encoded}.{respelled(signature)}", OWNER.public_key())
    assert refused.value.rejection == "malformed"


def test_a_payload_spelled_non_canonically_is_refused() -> None:
    for name in ("A", "AB", "ABC"):
        text = sign(LicensePayload("org", name, date(2026, 11, 9), date(2027, 11, 9), "k"))
        prefix, encoded, signature = text.split(".")
        if len(encoded) % 4:
            with pytest.raises(KeyRejected) as refused:
                verify_key(f"{prefix}.{respelled(encoded)}.{signature}", OWNER.public_key())
            assert refused.value.rejection == "malformed"
            return
    raise AssertionError("no payload with spare bits")


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "not a key",
        "ROADLAKE-1",
        "ROADLAKE-1.abc",
        "ROADLAKE-1.a.b.c",
        "OTHER-1.YWJj.YWJj",
        "ROADLAKE-1.!!!!.####",
        "ROADLAKE-1.YWJj.YWJj",
        "x" * 5000,
        "ROADLAKE-1." + "A" * 2000 + "." + "A" * 86,
    ],
)
def test_text_that_is_not_a_key_is_malformed(text: str) -> None:
    with pytest.raises(KeyRejected) as refused:
        verify_key(text, OWNER.public_key())
    assert refused.value.rejection in {"malformed", "unsupported_version"}


@pytest.mark.parametrize(
    "payload",
    [
        {"v": 1, "kind": "personal", "licensee": "A"},
        {
            "v": 1,
            "product": "sidekick",
            "kind": "gold",
            "licensee": "A",
            "issued": "2026-01-01",
            "expires": "2027-01-01",
            "key_id": "k",
        },
        {
            "v": 1,
            "product": "sidekick",
            "kind": "org",
            "licensee": "",
            "issued": "2026-01-01",
            "expires": "2027-01-01",
            "key_id": "k",
        },
        {
            "v": 1,
            "product": "sidekick",
            "kind": "org",
            "licensee": "A\nB",
            "issued": "2026-01-01",
            "expires": "2027-01-01",
            "key_id": "k",
        },
        {
            "v": 1,
            "product": "sidekick",
            "kind": "org",
            "licensee": "A",
            "issued": "20260101",
            "expires": "2027-01-01",
            "key_id": "k",
        },
        {
            "v": 1,
            "product": "sidekick",
            "kind": "org",
            "licensee": "A",
            "issued": "2027-01-01",
            "expires": "2026-01-01",
            "key_id": "k",
        },
        {
            "v": 1,
            "product": "sidekick",
            "kind": "org",
            "licensee": "A",
            "issued": "2026-01-01",
            "expires": "2027-02-30",
            "key_id": "k",
        },
        {
            "v": 1,
            "product": "sidekick",
            "kind": "org",
            "licensee": 5,
            "issued": "2026-01-01",
            "expires": "2027-01-01",
            "key_id": "k",
        },
    ],
)
def test_a_correctly_signed_but_wrong_payload_is_invalid(payload: dict[str, object]) -> None:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    signature = OWNER.sign(f"{KEY_PREFIX}.{encoded}".encode())
    text = f"{KEY_PREFIX}.{encoded}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"
    with pytest.raises(KeyRejected) as refused:
        verify_key(text, OWNER.public_key())
    assert refused.value.rejection == "bad_payload"


@pytest.mark.parametrize("product", [None, "other", "Sidekick", "", 7])
def test_a_key_must_be_signed_for_this_product(product: object) -> None:
    body: dict[str, object] = {
        "v": 1,
        "kind": "org",
        "licensee": "A",
        "issued": "2026-01-01",
        "expires": "2027-01-01",
        "key_id": "k",
    }
    if product is not None:
        body["product"] = product
    encoded = base64.urlsafe_b64encode(json.dumps(body).encode()).rstrip(b"=").decode()
    signature = base64.urlsafe_b64encode(OWNER.sign(f"{KEY_PREFIX}.{encoded}".encode()))
    with pytest.raises(KeyRejected) as refused:
        verify_key(f"{KEY_PREFIX}.{encoded}.{signature.rstrip(b'=').decode()}", OWNER.public_key())
    assert refused.value.rejection == "bad_payload"


def test_the_signed_payload_names_the_product_and_the_prefix_is_roadlake() -> None:
    text = sign()
    assert KEY_PREFIX == "ROADLAKE-1" and text.startswith("ROADLAKE-1.")
    body = json.loads(base64.urlsafe_b64decode(text.split(".")[1] + "=="))
    assert body["product"] == "sidekick"
    with pytest.raises(KeyRejected) as refused:
        verify_key(tamper(text, product="other"), OWNER.public_key())
    assert refused.value.rejection == "bad_signature"


def test_the_old_prefix_is_not_a_key() -> None:
    old = "CHAR" + "LIE-1." + sign().split(".", 1)[1]
    with pytest.raises(KeyRejected) as refused:
        verify_key(old, OWNER.public_key())
    assert refused.value.rejection == "malformed"


def test_a_signed_payload_of_another_version_is_unsupported() -> None:
    body = {
        "v": 2,
        "product": "sidekick",
        "kind": "org",
        "licensee": "A",
        "issued": "2026-01-01",
        "expires": "2027-01-01",
        "key_id": "k",
    }
    encoded = base64.urlsafe_b64encode(json.dumps(body).encode()).rstrip(b"=").decode()
    signature = base64.urlsafe_b64encode(OWNER.sign(f"{KEY_PREFIX}.{encoded}".encode()))
    with pytest.raises(KeyRejected) as refused:
        verify_key(f"{KEY_PREFIX}.{encoded}.{signature.rstrip(b'=').decode()}", OWNER.public_key())
    assert refused.value.rejection == "unsupported_version"


def test_the_state_follows_the_expiry_date_inclusively() -> None:
    public = OWNER.public_key()
    text = sign()
    on_last_day = evaluate(text, public, date(2027, 11, 9)).view
    after = evaluate(text, public, date(2027, 11, 10)).view
    assert on_last_day == LicenseView("licensed", "Kalle Anka", "personal", date(2027, 11, 9))
    assert after == LicenseView("expired", "Kalle Anka", "personal", date(2027, 11, 9))
    assert after.state == "expired" and evaluate(text, public, date(2026, 11, 9)).reason is None


def test_no_key_is_unlicensed_and_a_bad_key_is_invalid_with_a_reason_for_the_log() -> None:
    public = OWNER.public_key()
    today = date(2026, 12, 1)
    assert evaluate(None, public, today).view == UNLICENSED
    wrong = evaluate(sign(key=OTHER), public, today)
    assert wrong.view == LicenseView("invalid") and wrong.reason == "bad_signature"
    assert wrong.view.as_json() == {"state": "invalid"}
    junk = evaluate("hello", public, today)
    assert junk.view.state == "invalid" and junk.reason == "malformed"


def test_without_a_usable_public_key_every_key_is_unlicensed() -> None:
    assert parse_public_key(PLACEHOLDER_PUBLIC_KEY) is None
    for value in ("", "   ", "AAAA", base64.b64encode(b"short").decode()):
        assert parse_public_key(value) is None
    result = evaluate(sign(), parse_public_key(PLACEHOLDER_PUBLIC_KEY), date(2026, 12, 1))
    assert result.view == UNLICENSED and result.reason == "no_public_key"


def test_the_public_key_text_round_trips() -> None:
    parsed = parse_public_key(public_key_text(OWNER.public_key()))
    assert parsed is not None
    assert verify_key(sign(), parsed) == PAYLOAD


def test_the_view_json_is_compact_and_carries_no_key_material() -> None:
    view = evaluate(sign(), OWNER.public_key(), date(2026, 12, 1)).view
    assert view.as_json() == {
        "state": "licensed",
        "licensee": "Kalle Anka",
        "kind": "personal",
        "expires": "2027-11-09",
    }


def test_the_license_meta_is_declared_and_escaped_for_an_attribute() -> None:
    view = LicenseView("licensed", 'Bolaget "AB" <x> & Co', "org", date(2027, 1, 1))
    declared = with_license(HTML, view)
    assert declared.startswith('<!doctype html><html><head><meta name="sidekick-license" content="')
    content = declared.split('content="', 1)[1].split('">', 1)[0]
    assert '"' not in content and "<" not in content and ">" not in content
    assert json.loads(unescape(content)) == view.as_json()
    assert with_license(HTML, None) == HTML


def test_the_app_context_declares_the_license_next_to_the_rooms() -> None:
    declared = with_app_context(HTML, "sv", {"work"}, None, UNLICENSED)
    assert '<meta name="sidekick-rooms" content="work">' in declared
    assert "sidekick-license" in declared
    assert "sidekick-license" not in with_app_context(HTML, "sv", {"work"}, None)
