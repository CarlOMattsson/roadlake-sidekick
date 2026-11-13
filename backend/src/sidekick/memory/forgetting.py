"""Pure rules for forgetting one remembered fact: its key, its reference and its states.

No database, clock or network code lives here. A forgotten statement is stored only as a salted
digest, so Sidekick can hide it again whenever the memory provider derives it anew, yet can never
list what the owner asked it to forget.

`FORGET_KEY_VERSION` is part of every key. Changing the normalisation or the key formula means a
new version and a period in which both keys are checked, because a stored key that stops matching
makes a forgotten statement visible again without anyone noticing.

The normalisation rests on the Unicode database that ships with Python (`unicodedata`): its
compatibility mappings, character categories and case folding. A Python upgrade that moves to a
newer Unicode version can change how a rare character normalises, and so change a key. Raise
`FORGET_KEY_VERSION` (and check both versions for a period) whenever the Unicode version of the
runtime changes in a way that alters `normalize_fact_text` for any character.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

from sidekick.shared.errors import RefusedError

FORGET_KEY_VERSION = "forget-v1"
FORGET_SALT_BYTES = 16
#: The longest statement, in characters after normalisation. A fact is one sentence; this keeps a
#: key cheap to compute and refuses a document pasted in by mistake.
FORGET_TEXT_MAX_CHARS = 4000
# Compatibility mapping can lengthen a text (a ligature or a symbol becomes several characters),
# so a text far over the limit before normalisation is refused without being processed.
_RAW_TEXT_MAX_CHARS = FORGET_TEXT_MAX_CHARS * 4
_TYPOGRAPHIC_QUOTES = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u02bc": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u201f": '"',
    }
)
FACT_REF_PREFIX = "f1."
FACT_REF_MAX_CHARS = 200
_FACT_REF_LABEL = b"memory-fact-ref"
_FACT_REF_TAG_BYTES = 16
_KEY_BYTES = 32
_UUID_BYTES = 16
_MIN_BODY_BYTES = _UUID_BYTES + _KEY_BYTES + 1


class ForgottenUnitState(StrEnum):
    """Where hiding one provider fact stands. `parked`: only Sidekick hides it."""

    PENDING = "pending"
    INVALIDATED = "invalidated"
    REVERTING = "reverting"
    PARKED = "parked"


class InvalidFactRefError(RefusedError):
    """A fact reference that is malformed or not signed by this installation. Carries no detail."""

    def __init__(self) -> None:
        super().__init__("invalid fact reference")


def normalize_fact_text(text: str) -> str:
    """The form two phrasings of one statement share.

    Compatibility-composed Unicode (NFKC, so full-width letters and ligatures match their plain
    forms), without invisible format characters (zero-width spaces and joiners, bidi marks, soft
    hyphens), case-folded, typographic quotes and apostrophes made straight, one space between
    words, and no trailing punctuation or spaces.

    Raises `ValueError` when nothing is left, because an empty statement is never forgotten, or
    when more than `FORGET_TEXT_MAX_CHARS` characters are left.
    """

    if len(text) > _RAW_TEXT_MAX_CHARS:
        raise ValueError("a statement to forget is too long")
    composed = unicodedata.normalize("NFKC", text)
    visible = "".join(char for char in composed if unicodedata.category(char) != "Cf")
    folded = unicodedata.normalize("NFKC", visible.casefold())
    collapsed = " ".join(folded.translate(_TYPOGRAPHIC_QUOTES).split())
    end = len(collapsed)
    while end > 0 and unicodedata.category(collapsed[end - 1]).startswith(("P", "Z")):
        end -= 1
    normalized = collapsed[:end]
    if not normalized:
        raise ValueError("a statement to forget cannot be empty")
    if len(normalized) > FORGET_TEXT_MAX_CHARS:
        raise ValueError("a statement to forget is too long")
    return normalized


def new_forget_salt() -> str:
    """A fresh per-owner salt as lower-case hex (`FORGET_SALT_BYTES` random bytes)."""

    return secrets.token_hex(FORGET_SALT_BYTES)


def forget_text_key(salt: str, text: str) -> str:
    """The key under which an owner's statement is stored: a hex SHA-256, 64 characters.

    `salt` is the owner's salt from `new_forget_salt`. Another owner's salt gives another key for
    the same statement, so keys never match across owners.
    """

    try:
        salt_bytes = bytes.fromhex(salt)
    except ValueError as error:
        raise ValueError("the forget salt is not hexadecimal") from error
    if len(salt_bytes) != FORGET_SALT_BYTES:
        raise ValueError("the forget salt has the wrong length")
    material = FORGET_KEY_VERSION.encode("ascii") + salt_bytes + normalize_fact_text(text).encode()
    return hashlib.sha256(material).hexdigest()


@dataclass(frozen=True, slots=True)
class FactRefParts:
    """What a verified fact reference names. `text_key` is the key of the text recall returned."""

    memory_source_id: UUID
    provider_fact_id: str
    #: Left out of `repr`: the key is a digest of the statement and stays out of logs.
    text_key: str = field(repr=False)


def derive_fact_ref_key(id_derivation_key: bytes) -> bytes:
    """The MAC key for fact references, separated from the key that derives document ids."""

    return hmac.new(id_derivation_key, _FACT_REF_LABEL, hashlib.sha256).digest()


def _tag(key: bytes, body: bytes) -> bytes:
    return hmac.new(key, FACT_REF_PREFIX.encode() + body, hashlib.sha256).digest()[
        :_FACT_REF_TAG_BYTES
    ]


def make_fact_ref(key: bytes, parts: FactRefParts) -> str | None:
    """A signed, URL-safe reference to one recalled fact, or None when it cannot be built.

    None means the provider gave no usable id or the id is too long for a reference of at most
    `FACT_REF_MAX_CHARS` characters; the fact is then shown without a reference.
    """

    fact_id = parts.provider_fact_id.encode()
    if not fact_id or not parts.provider_fact_id.strip():
        return None
    try:
        text_key = bytes.fromhex(parts.text_key)
    except ValueError:
        return None
    if len(text_key) != _KEY_BYTES:
        return None
    body = parts.memory_source_id.bytes + text_key + fact_id
    reference = FACT_REF_PREFIX + base64.urlsafe_b64encode(body + _tag(key, body)).decode().rstrip(
        "="
    )
    return reference if len(reference) <= FACT_REF_MAX_CHARS else None


def parse_fact_ref(key: bytes, reference: str) -> FactRefParts:
    """The parts of a reference this installation signed. Anything else raises
    `InvalidFactRefError`, whatever the reason, so a caller learns nothing about why."""

    if not reference.startswith(FACT_REF_PREFIX) or len(reference) > FACT_REF_MAX_CHARS:
        raise InvalidFactRefError
    encoded = reference.removeprefix(FACT_REF_PREFIX)
    try:
        raw = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as error:
        raise InvalidFactRefError from error
    # One string form per reference: the standard alphabet, padding and stray bits are refused.
    if base64.urlsafe_b64encode(raw).decode().rstrip("=") != encoded:
        raise InvalidFactRefError
    if len(raw) < _MIN_BODY_BYTES + _FACT_REF_TAG_BYTES:
        raise InvalidFactRefError
    body, tag = raw[:-_FACT_REF_TAG_BYTES], raw[-_FACT_REF_TAG_BYTES:]
    if not hmac.compare_digest(tag, _tag(key, body)):
        raise InvalidFactRefError
    try:
        fact_id = body[_UUID_BYTES + _KEY_BYTES :].decode()
    except UnicodeDecodeError as error:
        raise InvalidFactRefError from error
    return FactRefParts(
        memory_source_id=UUID(bytes=body[:_UUID_BYTES]),
        provider_fact_id=fact_id,
        text_key=body[_UUID_BYTES : _UUID_BYTES + _KEY_BYTES].hex(),
    )
