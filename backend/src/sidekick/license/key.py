"""License keys (D-081: offline signed license keys): a signed, copy-pasteable string that is
checked without any network.

    ROADLAKE-1.<base64url(payload)>.<base64url(Ed25519 signature)>

The prefix is the licensor's namespace, not the product's, so one licensor can issue keys for more
than one product. The payload is compact JSON: `v` (1), `product` (`sidekick`), `kind` (`personal`
or `org`), `licensee` (a person's or an organisation's name), `issued` and `expires` (ISO dates; a
longer tier is just a later `expires`) and `key_id`. The signature covers the ASCII text
`ROADLAKE-1.<base64url(payload)>`, so the format version and the product are signed too.
Only the licensor holds the private key; the instance holds the public key.

Everything here is pure: no database, no clock, no framework. An expired key still verifies, and
the caller says what "today" is. A key that does not verify is `invalid`, with a closed reason for
the log. The reason, the key and the signature are never shown to the user.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Final, Literal, cast

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from sidekick.shared.errors.core import ValidationError

KEY_PREFIX: Final = "ROADLAKE-1"
FORMAT_VERSION: Final = 1
# The product this build accepts keys for; a key signed for another product is `bad_payload`.
PRODUCT: Final = "sidekick"
# A key is about 250 characters; the database column and the input checks share these ceilings.
MAX_KEY_LENGTH: Final = 1024
MAX_PASTED_LENGTH: Final = 4096
MAX_LICENSEE_LENGTH: Final = 120
MAX_KEY_ID_LENGTH: Final = 64
ED25519_KEY_BYTES: Final = 32
ED25519_SIGNATURE_BYTES: Final = 64

type LicenseKind = Literal["personal", "org"]
type LicenseState = Literal["unlicensed", "licensed", "expired", "invalid"]
type RejectReason = Literal[
    "malformed", "unsupported_version", "bad_signature", "bad_payload", "no_public_key"
]

KINDS: Final[tuple[LicenseKind, ...]] = ("personal", "org")
_BASE64URL = re.compile(r"[A-Za-z0-9_-]+")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_PAYLOAD_FIELDS: Final = frozenset(
    {"v", "product", "kind", "licensee", "issued", "expires", "key_id"}
)


class KeyRejected(ValidationError):
    """The text is not a valid license key for this public key. The message is the closed
    reason; it never carries any part of the key."""

    def __init__(self, reason: RejectReason) -> None:
        super().__init__(reason)
        self.rejection: RejectReason = reason


@dataclass(frozen=True, slots=True)
class LicensePayload:
    kind: LicenseKind
    licensee: str
    issued: date
    expires: date
    key_id: str


@dataclass(frozen=True, slots=True)
class LicenseView:
    """What the app may show: the state and, for a verified key, who and until when. Never the
    key, the signature, the key id or a reason."""

    state: LicenseState
    licensee: str | None = None
    kind: LicenseKind | None = None
    expires: date | None = None

    def as_json(self) -> dict[str, str]:
        """The shape every surface shares: `state` always; `licensee`, `kind` and `expires` only
        when the state carries them (`licensed`, `expired`)."""

        shown = {"state": self.state}
        if self.licensee is not None:
            shown["licensee"] = self.licensee
        if self.kind is not None:
            shown["kind"] = self.kind
        if self.expires is not None:
            shown["expires"] = self.expires.isoformat()
        return shown


UNLICENSED: Final = LicenseView("unlicensed")


@dataclass(frozen=True, slots=True)
class Evaluation:
    """A view plus the closed reason it is `invalid` (or `unlicensed` without a public key), for
    the log only."""

    view: LicenseView
    reason: RejectReason | None = None


def parse_public_key(value: str) -> Ed25519PublicKey | None:
    """The key a base64 raw Ed25519 public key names; `None` for the placeholder or any value that
    is not a valid key, so an instance with no real key treats every license key as unlicensed."""

    try:
        raw = base64.b64decode("".join(value.split()), validate=True)
        if len(raw) != ED25519_KEY_BYTES:
            return None
        return Ed25519PublicKey.from_public_bytes(raw)
    except (binascii.Error, ValueError):
        return None


def public_key_text(key: Ed25519PublicKey) -> str:
    return base64.b64encode(key.public_bytes_raw()).decode("ascii")


def _encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _decode(text: str) -> bytes:
    if _BASE64URL.fullmatch(text) is None:
        raise KeyRejected("malformed")
    try:
        decoded = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError):
        raise KeyRejected("malformed") from None
    # Only the canonical text of the bytes: the spare bits of the last character must be zero, so
    # one signed key has one spelling.
    if _encode(decoded) != text:
        raise KeyRejected("malformed")
    return decoded


def normalize(raw: str) -> str:
    """The pasted text without whitespace, so a key wrapped over lines still reads."""

    if len(raw) > MAX_PASTED_LENGTH:
        raise KeyRejected("malformed")
    text = "".join(raw.split())
    if not text or len(text) > MAX_KEY_LENGTH:
        raise KeyRejected("malformed")
    return text


def sign_key(private_key: Ed25519PrivateKey, payload: LicensePayload) -> str:
    """The key text for `payload`, signed by the owner's private key."""

    body = {
        "v": FORMAT_VERSION,
        "product": PRODUCT,
        "kind": payload.kind,
        "licensee": payload.licensee,
        "issued": payload.issued.isoformat(),
        "expires": payload.expires.isoformat(),
        "key_id": payload.key_id,
    }
    encoded = _encode(json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = private_key.sign(f"{KEY_PREFIX}.{encoded}".encode("ascii"))
    return f"{KEY_PREFIX}.{encoded}.{_encode(signature)}"


def verify_key(raw: str, public_key: Ed25519PublicKey) -> LicensePayload:
    """The payload of a key signed by the owner, or `KeyRejected` with a closed reason.

    The signature is checked before the payload is parsed, so nothing unsigned is ever read.
    Expiry is not checked here.
    """

    text = normalize(raw)
    parts = text.split(".")
    if len(parts) != 3:
        raise KeyRejected("malformed")
    prefix, encoded, encoded_signature = parts
    if prefix != KEY_PREFIX:
        raise KeyRejected("unsupported_version" if prefix.startswith("ROADLAKE-") else "malformed")
    payload_bytes = _decode(encoded)
    signature = _decode(encoded_signature)
    if len(signature) != ED25519_SIGNATURE_BYTES:
        raise KeyRejected("malformed")
    try:
        public_key.verify(signature, f"{prefix}.{encoded}".encode("ascii"))
    except InvalidSignature:
        raise KeyRejected("bad_signature") from None
    return _read_payload(payload_bytes)


def _read_payload(payload_bytes: bytes) -> LicensePayload:
    try:
        parsed: object = json.loads(payload_bytes.decode("utf-8"))
    except ValueError:
        raise KeyRejected("bad_payload") from None
    if not isinstance(parsed, dict):
        raise KeyRejected("bad_payload")
    data = cast("dict[str, object]", parsed)
    if not data.keys() >= _PAYLOAD_FIELDS:
        raise KeyRejected("bad_payload")
    version = data["v"]
    if type(version) is not int or version != FORMAT_VERSION:
        raise KeyRejected("unsupported_version")
    if data["product"] != PRODUCT:
        raise KeyRejected("bad_payload")
    licensee = _read_text(data["licensee"], MAX_LICENSEE_LENGTH)
    key_id = _read_text(data["key_id"], MAX_KEY_ID_LENGTH)
    issued, expires = _read_date(data["issued"]), _read_date(data["expires"])
    if expires < issued:
        raise KeyRejected("bad_payload")
    return LicensePayload(_read_kind(data["kind"]), licensee.strip(), issued, expires, key_id)


def _read_kind(value: object) -> LicenseKind:
    if value == "personal":
        return "personal"
    if value == "org":
        return "org"
    raise KeyRejected("bad_payload")


def _read_text(value: object, limit: int) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > limit
        or not value.isprintable()
    ):
        raise KeyRejected("bad_payload")
    return value


def _read_date(value: object) -> date:
    # `date.fromisoformat` also reads `20261109` and week dates; a key has exactly one form.
    if not isinstance(value, str) or _ISO_DATE.fullmatch(value) is None:
        raise KeyRejected("bad_payload")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise KeyRejected("bad_payload") from None


def evaluate(raw: str | None, public_key: Ed25519PublicKey | None, today: date) -> Evaluation:
    """The display state of the stored key on `today`.

    No stored key, or no usable public key at all, is `unlicensed`. A key that does not verify is
    `invalid`. A verified key is `licensed` through its `expires` date and `expired` after it.
    """

    if raw is None:
        return Evaluation(UNLICENSED)
    if public_key is None:
        return Evaluation(UNLICENSED, "no_public_key")
    try:
        payload = verify_key(raw, public_key)
    except KeyRejected as rejected:
        return Evaluation(LicenseView("invalid"), rejected.rejection)
    state: LicenseState = "expired" if today > payload.expires else "licensed"
    return Evaluation(LicenseView(state, payload.licensee, payload.kind, payload.expires))
