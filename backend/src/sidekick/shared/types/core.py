"""Identity, time, and identifier primitives."""

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Protocol, cast
from uuid import UUID

from sidekick.shared.errors.core import InvalidInputError, PermissionDeniedError


class UnsetType(Enum):
    """Sentinel distinguishing omitted fields from explicit null values."""

    TOKEN = "unset"  # noqa: S105  # the UNSET sentinel, not a credential


UNSET = UnsetType.TOKEN


@dataclass(frozen=True, slots=True)
class Actor:
    """Verified internal identity and transport scopes."""

    user_id: UUID
    scopes: frozenset[str]

    def require(self, scope: str) -> None:
        if scope not in self.scopes:
            raise PermissionDeniedError(f"missing required scope: {scope}")


@dataclass(frozen=True, slots=True)
class Page[T]:
    items: list[T]
    next_cursor: str | None


type KeyValue = None | int | str | datetime | UUID
"""One component of a keyset position: the value of a sort column in the last row served."""


MIN_IDEMPOTENCY_KEY_LENGTH = 8
MAX_IDEMPOTENCY_KEY_LENGTH = 128
"""Bounds of an idempotency key, in characters, on every transport (MCP schema, HTTP header) and
in the write path that runs the operation."""

MAX_CURSOR_LENGTH = 2048
"""Longest pagination cursor any transport accepts, in characters (MCP schema, HTTP query).

A cursor is base64url of `{"actor_id", "keyset", "query_key"}` as JSON plus a 32-byte signature.
The bound holds for every character a name or title can contain, because a text component of the
keyset is stored as base64url of its UTF-8 bytes (no JSON escaping, whatever the code points):

- text component: at most `SORT_KEY_CHARS` (200) characters, at most 4 bytes each in UTF-8 = 800
  bytes = 1067 base64 characters, plus 2 quotes;
- the other components of the longest position (Work, `title_asc` in a context-grouped agenda):
  a UUID twice (38 each), a 4-character-or-less integer, a short kind (<= 20) and commas: < 150;
- fixed part of the JSON: actor id 36 and filter digest 64 with their field names: 142;
- so the JSON is < 1361 bytes, with the signature < 1393 bytes, and base64 makes that < 1858.

2048 leaves a margin; `test_keyset_cursor.py` measures the worst case (control characters,
quotes, backslashes, 4-byte characters) for contacts and Work against it.
"""

SORT_KEY_CHARS = 200
"""Text sort keys (contact name, Work title) order by their first 200 characters, then the id.

Names and titles are at most 200 characters, so this only cuts keys that grew when folded
(NFKC, case folding). The order stays total, and a cursor carries a bounded text.
"""

TIMED_KEY = (datetime, UUID)
"""Sort key of a list ordered by a timestamp: (timestamp, id)."""

NAMED_KEY = (str, UUID)
"""Sort key of a list ordered by a text key: (name key, id), both ascending."""


def pack_key(values: tuple[KeyValue, ...]) -> list[Any]:
    """A sort position as plain JSON values; `unpack_key` restores the types from `kinds`."""

    return [
        value.isoformat()
        if isinstance(value, datetime)
        else str(value)
        if isinstance(value, UUID)
        else _pack_text(value)
        if isinstance(value, str)
        else value
        for value in values
    ]


def _pack_text(text: str) -> str:
    """Text as base64url of its UTF-8 bytes: 4/3 of the byte length for any character."""

    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def _unpack_text(token: str) -> str:
    decoded = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    if _pack_text(decoded.decode()) != token:  # one spelling per text; UTF-8 must be valid
        raise ValueError
    return decoded.decode()


def unpack_key(
    raw: object, kinds: tuple[type, ...], nullable: tuple[bool, ...] | None = None
) -> tuple[KeyValue, ...]:
    """The sort position `pack_key` produced; any other shape or type is an invalid cursor.

    `kinds` gives the Python type of each component and `nullable` which ones may be null
    (none by default), so a forged position can never reach the database as a wrong type.
    """

    try:
        if not isinstance(raw, list) or len(cast("list[Any]", raw)) != len(kinds):
            raise ValueError
        values: list[KeyValue] = []
        for index, item in enumerate(cast("list[Any]", raw)):
            kind = kinds[index]
            if item is None:
                if nullable is None or not nullable[index]:
                    raise ValueError
                values.append(None)
            elif kind is datetime and isinstance(item, str):
                moment = datetime.fromisoformat(item)
                if moment.tzinfo is None:
                    raise ValueError
                values.append(moment)
            elif kind is UUID and isinstance(item, str):
                values.append(UUID(item))
            elif kind is str and isinstance(item, str):
                values.append(_unpack_text(item))
            elif type(item) is kind and kind is int:
                values.append(item)
            else:
                raise ValueError
        return tuple(values)
    except (TypeError, ValueError) as error:
        raise InvalidInputError("invalid pagination cursor") from error


class CursorCodec:
    """Signed actor- and query-bound offset cursor for small private datasets.

    The query is bound by digest rather than by its literal text, so a cursor stays
    a small opaque token however rich the projection vocabulary becomes. A cursor
    issued for one query still cannot be replayed against another.
    """

    def __init__(self, secret: str) -> None:
        self._secret = secret.encode()

    @staticmethod
    def _digest(query_key: str) -> str:
        return hashlib.sha256(query_key.encode()).hexdigest()

    def _seal(self, actor_id: UUID, query_key: str, **fields: Any) -> str:
        payload = json.dumps(
            {"actor_id": str(actor_id), "query_key": self._digest(query_key), **fields},
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        signature = hmac.new(self._secret, payload, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(payload + signature).decode().rstrip("=")

    def _open(self, actor_id: UUID, cursor: str, query_key: str) -> dict[str, Any]:
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            decoded = base64.urlsafe_b64decode(padded.encode())
            canonical = base64.urlsafe_b64encode(decoded).decode().rstrip("=")
            if not hmac.compare_digest(canonical, cursor):
                raise ValueError
            payload, signature = decoded[:-32], decoded[-32:]
            expected = hmac.new(self._secret, payload, hashlib.sha256).digest()
            data = json.loads(payload)
            if (
                not hmac.compare_digest(signature, expected)
                or data["actor_id"] != str(actor_id)
                or data["query_key"] != self._digest(query_key)
            ):
                raise ValueError
            return data
        except (binascii.Error, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise InvalidInputError("invalid pagination cursor") from error

    def encode(self, actor_id: UUID, offset: int, query_key: str = "") -> str:
        return self._seal(actor_id, query_key, offset=offset)

    def decode(self, actor_id: UUID, cursor: str | None, query_key: str = "") -> int:
        if cursor is None:
            return 0
        data = self._open(actor_id, cursor, query_key)
        try:
            offset = int(data["offset"])
        except (KeyError, TypeError, ValueError) as error:
            raise InvalidInputError("invalid pagination cursor") from error
        if offset < 0:
            raise InvalidInputError("invalid pagination cursor")
        return offset

    def encode_position(self, actor_id: UUID, position: str, query_key: str = "") -> str:
        """Seal the sort key of the last row served, for keyset pagination over changing data."""

        return self._seal(actor_id, query_key, position=position)

    def decode_position(
        self, actor_id: UUID, cursor: str | None, query_key: str = ""
    ) -> str | None:
        """The sealed sort key, or None without a cursor; a bad or foreign one is rejected."""

        if cursor is None:
            return None
        position = self._open(actor_id, cursor, query_key).get("position")
        if not isinstance(position, str):
            raise InvalidInputError("invalid pagination cursor")
        return position

    def encode_keyset(
        self, actor_id: UUID, values: tuple[KeyValue, ...], query_key: str = ""
    ) -> str:
        """Seal the sort key of the last row served: the next page starts strictly after it.

        Unlike an offset, a keyset position does not move when rows are added or removed
        before it, so no row is served twice while a client pages
        (see docs/architecture/pagination.md).
        """

        return self._seal(actor_id, query_key, keyset=pack_key(values))

    def decode_keyset(
        self,
        actor_id: UUID,
        cursor: str | None,
        query_key: str = "",
        *,
        kinds: tuple[type, ...],
        nullable: tuple[bool, ...] | None = None,
    ) -> tuple[KeyValue, ...] | None:
        """The sealed sort position, or None without a cursor.

        A cursor of another actor, another filter set (`query_key`), another shape or one that
        was tampered with is rejected with `InvalidInputError`.
        """

        if cursor is None:
            return None
        return unpack_key(self._open(actor_id, cursor, query_key).get("keyset"), kinds, nullable)


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return utc_now()


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_uuid7() -> UUID:
    """Create a monotonic-time-sortable UUIDv7 without a framework dependency."""

    milliseconds = int(time.time() * 1000) & ((1 << 48) - 1)
    random_bits = secrets.randbits(74)
    value = milliseconds << 80
    value |= 0x7 << 76
    value |= ((random_bits >> 62) & 0xFFF) << 64
    value |= 0b10 << 62
    value |= random_bits & ((1 << 62) - 1)
    return UUID(int=value)
