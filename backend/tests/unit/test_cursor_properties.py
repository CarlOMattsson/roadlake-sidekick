"""Fuzzing pagination cursors: a client hands any text back as `cursor`, so the codec must open a
sealed position exactly, and answer everything else (forged, foreign, edited or junk) with the one
closed rejection."""

from __future__ import annotations

import base64
from datetime import date, datetime
from uuid import UUID

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from sidekick.shared.errors import InvalidInputError
from sidekick.shared.types import MAX_CURSOR_LENGTH, NAMED_KEY, SORT_KEY_CHARS, CursorCodec
from sidekick.shared.types.core import KeyValue

CODEC = CursorCodec("unit-test-key-" + "x" * 32)

_actors = st.uuids()
_query_keys = st.text(max_size=80)
_text_keys = st.text(max_size=SORT_KEY_CHARS)
_moments = st.datetimes(timezones=st.timezones())

# One sort column: its Python type and the values a row can hold in it.
_COLUMNS: dict[type, st.SearchStrategy[KeyValue]] = {
    int: st.integers(),
    str: _text_keys,
    date: st.dates(),
    datetime: _moments,
    UUID: st.uuids(),
}


@st.composite
def positions(
    draw: st.DrawFn,
) -> tuple[tuple[type, ...], tuple[bool, ...], tuple[KeyValue, ...]]:
    kinds = tuple(draw(st.lists(st.sampled_from(list(_COLUMNS)), min_size=1, max_size=5)))
    nullable = tuple(draw(st.booleans()) for _ in kinds)
    values = tuple(
        draw(st.one_of(st.none(), _COLUMNS[kind]) if may_be_null else _COLUMNS[kind])
        for kind, may_be_null in zip(kinds, nullable, strict=True)
    )
    return kinds, nullable, values


def _rejected(call: object) -> None:
    assert callable(call)
    with pytest.raises(InvalidInputError, match="invalid pagination cursor"):
        call()


@given(_actors, _query_keys, positions())
@settings(max_examples=500, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_a_sealed_position_opens_to_the_same_values_and_types(
    actor: UUID,
    query_key: str,
    position: tuple[tuple[type, ...], tuple[bool, ...], tuple[KeyValue, ...]],
) -> None:
    kinds, nullable, values = position
    cursor = CODEC.encode_keyset(actor, values, query_key)

    opened = CODEC.decode_keyset(actor, cursor, query_key, kinds=kinds, nullable=nullable)

    # Aware datetimes compare by ISO form: across zones, Python never calls two datetimes
    # equal when one falls in a fold or gap (PEP 495), though the cursor keeps the instant.
    assert _comparable(opened or ()) == _comparable(values)
    assert [type(value) for value in opened or ()] == [type(value) for value in values]


def _comparable(values: tuple[KeyValue, ...]) -> list[object]:
    return [value.isoformat() if isinstance(value, datetime) else value for value in values]


@given(_actors, _text_keys, st.uuids())
@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_a_named_position_fits_every_transport(actor: UUID, name: str, row: UUID) -> None:
    assert len(CODEC.encode_keyset(actor, (name, row), "q" * 80)) <= MAX_CURSOR_LENGTH


@given(_actors, _query_keys, st.integers(min_value=0, max_value=2**63))
def test_an_offset_round_trips(actor: UUID, query_key: str, offset: int) -> None:
    assert CODEC.decode(actor, CODEC.encode(actor, offset, query_key), query_key) == offset


@given(_actors, st.uuids(), _query_keys, _query_keys, _text_keys)
@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_a_cursor_opens_only_for_its_own_actor_and_query(
    actor: UUID, other: UUID, query_key: str, other_query: str, name: str
) -> None:
    cursor = CODEC.encode_keyset(actor, (name, actor), query_key)
    if other != actor:
        _rejected(lambda: CODEC.decode_keyset(other, cursor, query_key, kinds=NAMED_KEY))
    if other_query != query_key:
        _rejected(lambda: CODEC.decode_keyset(actor, cursor, other_query, kinds=NAMED_KEY))
    _rejected(
        lambda: CursorCodec("another-key-" + "y" * 32).decode_keyset(
            actor, cursor, query_key, kinds=NAMED_KEY
        )
    )


@given(_actors, _text_keys, st.data())
@settings(max_examples=500, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_one_changed_character_is_rejected(actor: UUID, name: str, data: st.DataObject) -> None:
    cursor = CODEC.encode_keyset(actor, (name, actor), "q")
    index = data.draw(st.integers(min_value=0, max_value=len(cursor) - 1))
    replacement = data.draw(st.characters().filter(lambda char: char != cursor[index]))
    forged = cursor[:index] + replacement + cursor[index + 1 :]

    _rejected(lambda: CODEC.decode_keyset(actor, forged, "q", kinds=NAMED_KEY))


# What a client may send: any text, or base64url of any bytes (JSON or not, signed or not).
_client_cursors = st.one_of(
    st.text(max_size=MAX_CURSOR_LENGTH),
    st.binary(max_size=1500).map(lambda raw: base64.urlsafe_b64encode(raw).decode().rstrip("=")),
    st.builds(
        lambda body: base64.urlsafe_b64encode(body.encode() + bytes(32)).decode().rstrip("="),
        st.sampled_from(["{}", "[]", "null", '"x"', "1e999", "[" * 1400, '{"actor_id":1}']),
    ),
)


@given(_actors, _client_cursors)
@settings(max_examples=500, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_any_client_cursor_is_rejected_with_the_closed_error(actor: UUID, cursor: str) -> None:
    _rejected(lambda: CODEC.decode(actor, cursor))
    _rejected(lambda: CODEC.decode_position(actor, cursor))
    _rejected(lambda: CODEC.decode_keyset(actor, cursor, kinds=NAMED_KEY))
