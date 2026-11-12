"""Keyset cursors: sealed sort positions round-trip, stay small and reject every other shape."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from sidekick.shared.errors import InvalidInputError
from sidekick.shared.types import (
    MAX_CURSOR_LENGTH,
    NAMED_KEY,
    SORT_KEY_CHARS,
    TIMED_KEY,
    CursorCodec,
)
from sidekick.shared.types.core import unpack_key
from sidekick.work.application.service import WorkQuery
from sidekick.work.listing import AgendaSpec, WorkListSpec, sort_keys

ACTOR = UUID(int=7)
STAMP = datetime(2026, 11, 10, 12, 0, 0, 123456, tzinfo=UTC)
ROW = UUID(int=99)


def _codec() -> CursorCodec:
    return CursorCodec("unit-test-key-" + "x" * 32)


def test_a_position_round_trips_with_its_types() -> None:
    codec = _codec()
    cursor = codec.encode_keyset(ACTOR, (STAMP, ROW), "q")

    assert codec.decode_keyset(ACTOR, cursor, "q", kinds=TIMED_KEY) == (STAMP, ROW)
    assert codec.decode_keyset(ACTOR, None, "q", kinds=TIMED_KEY) is None


def test_nulls_round_trip_only_where_allowed() -> None:
    codec = _codec()
    cursor = codec.encode_keyset(ACTOR, (None, ROW), "q")

    kinds = (datetime, UUID)
    assert codec.decode_keyset(ACTOR, cursor, "q", kinds=kinds, nullable=(True, False)) == (
        None,
        ROW,
    )
    with pytest.raises(InvalidInputError):
        codec.decode_keyset(ACTOR, cursor, "q", kinds=kinds)


@pytest.mark.parametrize(
    "position",
    [
        (ROW, ROW),  # a UUID where a timestamp is expected
        (STAMP, STAMP),  # a timestamp where an id is expected
        (STAMP.replace(tzinfo=None), ROW),  # naive timestamp
        (STAMP,),  # too short
        (STAMP, ROW, 1),  # too long
        ("2026-11-10", ROW),  # not a timestamp
        (STAMP, "not-a-uuid"),
    ],
)
def test_a_signed_but_wrongly_shaped_position_is_rejected(position: tuple[Any, ...]) -> None:
    codec = _codec()
    cursor = codec.encode_keyset(ACTOR, position, "q")

    with pytest.raises(InvalidInputError, match="invalid pagination cursor"):
        codec.decode_keyset(ACTOR, cursor, "q", kinds=TIMED_KEY)


def test_a_boolean_is_not_an_integer_position() -> None:
    codec = _codec()
    cursor = codec.encode_keyset(ACTOR, (True,), "q")

    with pytest.raises(InvalidInputError):
        codec.decode_keyset(ACTOR, cursor, "q", kinds=(int,))


def test_other_actor_other_filter_other_key_and_offset_cursors_are_rejected() -> None:
    codec = _codec()
    cursor = codec.encode_keyset(ACTOR, (STAMP, ROW), "filter-a")

    with pytest.raises(InvalidInputError):
        codec.decode_keyset(UUID(int=8), cursor, "filter-a", kinds=TIMED_KEY)
    with pytest.raises(InvalidInputError):
        codec.decode_keyset(ACTOR, cursor, "filter-b", kinds=TIMED_KEY)
    with pytest.raises(InvalidInputError):
        CursorCodec("another-key-" + "y" * 32).decode_keyset(
            ACTOR, cursor, "filter-a", kinds=TIMED_KEY
        )
    with pytest.raises(InvalidInputError):
        codec.decode_keyset(ACTOR, codec.encode(ACTOR, 5, "filter-a"), "filter-a", kinds=TIMED_KEY)
    with pytest.raises(InvalidInputError):
        codec.decode_keyset(
            ACTOR, codec.encode_position(ACTOR, "5", "filter-a"), "filter-a", kinds=TIMED_KEY
        )


ASTRAL = "\U00020000"  # a CJK character outside the BMP: 4 bytes in UTF-8, stable under NFKC


# Worst cases for a JSON spelling: control characters (six characters escaped), quote and backslash
# (two), and four-byte characters. A text component is base64 of its UTF-8, so none is worse.
WORST_CHARACTERS = ["a", "\x01", "\x1f", '"', "\\", "\x7f", "\x85", "\u2028", ASTRAL]


@pytest.mark.parametrize("character", WORST_CHARACTERS)
def test_the_longest_work_cursor_fits_the_transport_limit(character: str) -> None:
    """The longest cursor: every text key at its cut-off length, whatever the characters."""

    spec = WorkListSpec(
        now=STAMP,
        sort="title_asc",
        group="context",
        agenda=AgendaSpec(STAMP, STAMP, STAMP, False, False, None, True),
    )
    order = sort_keys(spec)
    values: dict[type, Any] = {
        int: 1,
        str: "action",
        UUID: ROW,
        datetime: STAMP,
    }
    position = tuple(
        character * SORT_KEY_CHARS if key.name == "title" else values[key.kind] for key in order
    )
    query_key = "agenda:v1:" + WorkQuery(tags=("a",) * 5).key()

    cursor = _codec().encode_keyset(ACTOR, position, query_key)

    assert len(cursor) <= MAX_CURSOR_LENGTH
    assert (
        _codec().decode_keyset(
            ACTOR,
            cursor,
            query_key,
            kinds=tuple(key.kind for key in order),
            nullable=tuple(key.nullable for key in order),
        )
        == position
    )


@pytest.mark.parametrize("character", WORST_CHARACTERS)
def test_the_longest_contact_cursor_fits_the_transport_limit(character: str) -> None:
    text = character * SORT_KEY_CHARS
    query_key = "contacts:v2:q=" + "f" * 64 + ":archived=False"

    cursor = _codec().encode_keyset(ACTOR, (text, ROW), query_key)

    assert len(cursor) <= MAX_CURSOR_LENGTH
    assert _codec().decode_keyset(ACTOR, cursor, query_key, kinds=NAMED_KEY) == (text, ROW)


def test_the_measured_worst_case_is_a_four_byte_character_with_room_to_spare() -> None:
    lengths = {
        character: len(_codec().encode_keyset(ACTOR, (character * SORT_KEY_CHARS, ROW), "k"))
        for character in WORST_CHARACTERS
    }

    # Text is stored as base64 of its UTF-8, so the cursor grows with bytes, not with escapes.
    assert max(lengths, key=lambda character: lengths[character]) == ASTRAL
    assert max(lengths.values()) < MAX_CURSOR_LENGTH - 100


def test_text_that_is_not_canonical_base64_utf8_is_rejected() -> None:
    # Not base64, a lone UTF-8 continuation byte, padding, and a second spelling of "a".
    for forged in ("not base64!", "gA", "YQ=", "YR"):
        with pytest.raises(InvalidInputError):
            unpack_key([forged, str(ROW)], NAMED_KEY)


def test_the_work_order_is_total_and_ends_in_the_record_identity() -> None:
    for sort in ("updated_desc", "due_asc", "not_before_asc", "estimate_asc", "title_asc"):
        order = sort_keys(WorkListSpec(now=STAMP, sort=sort))
        assert [key.name for key in order[-2:]] == ["id", "kind"]
        assert all(key.descending for key in order) == (sort == "updated_desc")
