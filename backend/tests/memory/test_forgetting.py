"""The pure rules of forgetting one fact: normalisation, the salted key and the signed reference."""

from __future__ import annotations

import base64
import dataclasses
from uuid import UUID

import pytest

from sidekick.memory.forgetting import (
    FACT_REF_MAX_CHARS,
    FACT_REF_PREFIX,
    FORGET_KEY_VERSION,
    FORGET_SALT_BYTES,
    FORGET_TEXT_MAX_CHARS,
    FactRefParts,
    ForgottenUnitState,
    InvalidFactRefError,
    derive_fact_ref_key,
    forget_text_key,
    make_fact_ref,
    new_forget_salt,
    normalize_fact_text,
    parse_fact_ref,
)
from sidekick.shared.errors.core import SidekickError

SALT = "00112233445566778899aabbccddeeff"
OTHER_SALT = "ffeeddccbbaa99887766554433221100"
SOURCE_ID = UUID("018af000-0000-7000-8000-000000000a01")
TEXT_KEY = forget_text_key(SALT, "Anna gillar kaffe")
ID_KEY = b"x" * 32


def _parts(**overrides: object) -> FactRefParts:
    parts = FactRefParts(
        memory_source_id=SOURCE_ID,
        provider_fact_id="3f2b8c1e-6c1d-4b1a-9a53-0d1c2f4e5a6b",
        text_key=TEXT_KEY,
    )
    return dataclasses.replace(parts, **overrides)


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("Anna gillar kaffe", "anna gillar kaffe"),
        ("ANNA GILLAR KAFFE", "anna gillar kaffe"),
        ("  Anna \t gillar\n\nkaffe  ", "anna gillar kaffe"),
        ("Anna gillar kaffe.", "anna gillar kaffe"),
        ("Anna gillar kaffe!?.. ", "anna gillar kaffe"),
        ("Anna gillar kaffe ”", "anna gillar kaffe"),
        # A decomposed and a composed å are the same letter.
        ("Måna gillar kaffe", "måna gillar kaffe"),
        ("Måna gillar kaffe", "måna gillar kaffe"),
        # Compatibility forms: full-width letters, a ligature and a no-break space.
        ("\uff21nna gillar kaffe", "anna gillar kaffe"),
        ("Anna gillar \ufb01ka", "anna gillar fika"),
        ("Anna\u00a0gillar kaffe", "anna gillar kaffe"),
        # Invisible format characters (Cf) vanish: zero-width space and joiner, bidi mark, soft
        # hyphen and a byte-order mark.
        ("Anna\u200b gillar\u200d kaffe", "anna gillar kaffe"),
        ("An\u00adna gillar kaffe\u200e", "anna gillar kaffe"),
        ("\ufeffAnna gillar kaffe", "anna gillar kaffe"),
        ("Anna gillar ka\u200bffe", "anna gillar kaffe"),
        # Typographic apostrophes and quotes become straight ones.
        ("Anna\u2019s kaffe", "anna's kaffe"),
        ("Anna\u2018s kaffe", "anna's kaffe"),
        ("Anna\u02bcs kaffe", "anna's kaffe"),
        ("Anna s\u00e4ger \u201dkaffe\u201d idag", 'anna s\u00e4ger "kaffe" idag'),
        ("Anna s\u00e4ger \u201ekaffe\u201c idag", 'anna s\u00e4ger "kaffe" idag'),
        # Case folding maps the German sharp s to "ss".
        ("STRASSE", "strasse"),
        ("Straße", "strasse"),
        # Only the end loses punctuation; the inside of a statement stays as it is.
        ("Anna, gillar kaffe", "anna, gillar kaffe"),
    ],
)
def test_normalisation_makes_phrasings_of_one_statement_equal(raw: str, normalized: str) -> None:
    assert normalize_fact_text(raw) == normalized


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "\n\t", "...", " ! ? ", "\u201d\u201d", "\u200b\u200d", "\u200b . \ufeff"],
)
def test_a_statement_with_nothing_left_after_normalisation_is_refused(raw: str) -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        normalize_fact_text(raw)


def test_a_statement_over_the_length_limit_is_refused() -> None:
    longest = "a" * FORGET_TEXT_MAX_CHARS

    assert normalize_fact_text(longest) == longest
    with pytest.raises(ValueError, match="too long"):
        normalize_fact_text(longest + "a")
    # The limit counts normalised characters: invisible ones do not count.
    assert normalize_fact_text("a\u200b" * FORGET_TEXT_MAX_CHARS) == longest
    # Compatibility mapping lengthens text, so the limit applies after it ...
    with pytest.raises(ValueError, match="too long"):
        normalize_fact_text("\ufdfa" * 300)
    # ... and a text far over the limit is refused before it is processed.
    with pytest.raises(ValueError, match="too long"):
        normalize_fact_text("a" * (FORGET_TEXT_MAX_CHARS * 4 + 1))


def test_normalisation_is_idempotent() -> None:
    once = normalize_fact_text("  Måna  GILLAR kaffe.  ")

    assert normalize_fact_text(once) == once


def test_the_key_is_a_stable_sha256_hex_digest_for_one_owner() -> None:
    first = forget_text_key(SALT, "Anna gillar kaffe")

    assert first == forget_text_key(SALT, "Anna gillar kaffe")
    assert len(first) == 64
    assert set(first) <= set("0123456789abcdef")
    # Every phrasing that normalises alike has the one key.
    assert first == forget_text_key(SALT, "  ANNA gillar   kaffe. ")
    assert first != forget_text_key(SALT, "Anna gillar inte kaffe")


def test_the_key_differs_between_owners_and_with_the_key_version() -> None:
    assert forget_text_key(SALT, "Anna gillar kaffe") != forget_text_key(
        OTHER_SALT, "Anna gillar kaffe"
    )
    # SHA-256 of b"forget-v1" + the salt bytes + b"anna gillar kaffe"; it changes only with a new
    # version of the key formula.
    assert FORGET_KEY_VERSION == "forget-v1"
    assert forget_text_key(SALT, "Anna gillar kaffe") == (
        "a2abf88023fe57a3ad41d3dc7763aa2c989dfe0622a82cdcc4022d1aa6ca7ad2"
    )


@pytest.mark.parametrize("salt", ["", "zz", "00", SALT[:-2], SALT + "00", SALT.upper() + "0"])
def test_a_salt_that_is_not_sixteen_bytes_of_hex_is_refused(salt: str) -> None:
    with pytest.raises(ValueError, match="salt"):
        forget_text_key(salt, "Anna gillar kaffe")


def test_a_new_salt_is_sixteen_random_bytes_as_lower_case_hex() -> None:
    first, second = new_forget_salt(), new_forget_salt()

    assert len(first) == FORGET_SALT_BYTES * 2
    assert first == first.lower()
    assert bytes.fromhex(first)
    assert first != second


def test_no_key_reveals_the_text_it_stands_for() -> None:
    key = forget_text_key(SALT, "Anna gillar kaffe")

    assert "anna" not in key.lower()
    assert "kaffe" not in key


def test_the_unit_states_match_the_database_vocabulary() -> None:
    assert [state.value for state in ForgottenUnitState] == [
        "pending",
        "invalidated",
        "reverting",
        "parked",
    ]


def test_a_fact_reference_round_trips() -> None:
    key = derive_fact_ref_key(ID_KEY)
    parts = _parts()

    reference = make_fact_ref(key, parts)

    assert reference is not None
    assert reference.startswith(FACT_REF_PREFIX)
    assert len(reference) <= FACT_REF_MAX_CHARS
    assert parse_fact_ref(key, reference) == parts


def test_the_repr_of_a_reference_shows_no_text_key() -> None:
    assert TEXT_KEY not in repr(_parts())


def test_only_one_string_form_of_a_reference_is_accepted() -> None:
    key = derive_fact_ref_key(ID_KEY)
    reference = make_fact_ref(key, _parts())
    assert reference is not None
    encoded = reference.removeprefix(FACT_REF_PREFIX)
    assert len(encoded) % 4 == 2  # so the last character carries bits that no byte uses
    assert parse_fact_ref(key, reference) == _parts()

    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    stray_bit = encoded[:-1] + alphabet[alphabet.index(encoded[-1]) ^ 1]
    variants = [
        encoded + "==",
        " " + encoded,
        encoded + "\n",
        stray_bit,
        encoded.replace("-", "+").replace("_", "/"),
    ]
    for variant in variants:
        if variant == encoded:
            continue  # this reference has no character that the standard alphabet spells otherwise
        with pytest.raises(InvalidFactRefError):
            parse_fact_ref(key, FACT_REF_PREFIX + variant)


def test_a_reference_holds_the_ids_and_the_key_but_no_text() -> None:
    key = derive_fact_ref_key(ID_KEY)
    reference = make_fact_ref(key, _parts())

    assert reference is not None
    assert "anna" not in reference.lower()
    assert "=" not in reference


def test_the_reference_key_is_separate_from_the_id_derivation_key() -> None:
    assert derive_fact_ref_key(ID_KEY) != ID_KEY
    assert derive_fact_ref_key(ID_KEY) != derive_fact_ref_key(b"y" * 32)


def test_a_reference_signed_with_another_key_is_refused() -> None:
    reference = make_fact_ref(derive_fact_ref_key(ID_KEY), _parts())
    assert reference is not None

    with pytest.raises(InvalidFactRefError):
        parse_fact_ref(derive_fact_ref_key(b"y" * 32), reference)


def _flip(reference: str, position: int) -> str:
    body = reference.removeprefix(FACT_REF_PREFIX)
    raw = bytearray(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    raw[position] ^= 0x01
    return FACT_REF_PREFIX + base64.urlsafe_b64encode(bytes(raw)).decode().rstrip("=")


@pytest.mark.parametrize("position", [0, 15, 16, 47, 48, -1])
def test_a_reference_with_any_changed_byte_is_refused(position: int) -> None:
    key = derive_fact_ref_key(ID_KEY)
    reference = make_fact_ref(key, _parts())
    assert reference is not None

    with pytest.raises(InvalidFactRefError):
        parse_fact_ref(key, _flip(reference, position))


def test_a_reference_cannot_be_moved_to_another_source_row() -> None:
    key = derive_fact_ref_key(ID_KEY)
    mine = make_fact_ref(key, _parts())
    other = make_fact_ref(key, _parts(memory_source_id=UUID(int=7)))
    assert mine is not None
    assert other is not None
    assert mine != other

    forged = other[: len(FACT_REF_PREFIX) + 22] + mine[len(FACT_REF_PREFIX) + 22 :]
    with pytest.raises(InvalidFactRefError):
        parse_fact_ref(key, forged)


@pytest.mark.parametrize(
    "reference",
    [
        "",
        "f1.",
        "f2.AAAA",
        "AAAA",
        "f1.not base64 at all!",
        "f1." + "A" * 10,
        "f1." + "A" * 80,
        "f1." + "A" * (FACT_REF_MAX_CHARS + 1),
    ],
)
def test_a_malformed_reference_is_refused_without_detail(reference: str) -> None:
    with pytest.raises(InvalidFactRefError) as raised:
        parse_fact_ref(derive_fact_ref_key(ID_KEY), reference)

    assert str(raised.value) == "invalid fact reference"
    assert reference not in str(raised.value) or reference == ""


def test_a_refused_reference_is_a_validation_error_with_a_fixed_text() -> None:
    assert issubclass(InvalidFactRefError, SidekickError)
    assert InvalidFactRefError().code == "validation_error"


def test_a_provider_id_too_long_for_a_reference_gives_no_reference() -> None:
    key = derive_fact_ref_key(ID_KEY)

    assert make_fact_ref(key, _parts(provider_fact_id="a" * 200)) is None
    longest = "a" * 83
    reference = make_fact_ref(key, _parts(provider_fact_id=longest))
    assert reference is not None
    assert len(reference) <= FACT_REF_MAX_CHARS
    assert parse_fact_ref(key, reference).provider_fact_id == longest
    assert make_fact_ref(key, _parts(provider_fact_id="a" * 84)) is None


@pytest.mark.parametrize("fact_id", ["", "   "])
def test_a_blank_provider_id_gives_no_reference(fact_id: str) -> None:
    assert make_fact_ref(derive_fact_ref_key(ID_KEY), _parts(provider_fact_id=fact_id)) is None


@pytest.mark.parametrize("text_key", ["", "zz", "ab" * 31, "ab" * 33])
def test_a_text_key_that_is_not_a_sha256_gives_no_reference(text_key: str) -> None:
    assert make_fact_ref(derive_fact_ref_key(ID_KEY), _parts(text_key=text_key)) is None
