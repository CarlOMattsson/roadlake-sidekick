"""Shared identifier and authorization primitives."""

from uuid import UUID

import pytest

from sidekick.shared.errors import InvalidInputError, PermissionDeniedError
from sidekick.shared.types import Actor, CursorCodec, new_uuid7


def test_uuid7_has_expected_variant_and_version() -> None:
    identifier = new_uuid7()
    assert identifier.version == 7
    assert identifier.variant == "specified in RFC 4122"


def test_actor_requires_explicit_scope() -> None:
    actor = Actor(UUID(int=1), frozenset({"projects:read"}))
    actor.require("projects:read")
    with pytest.raises(PermissionDeniedError, match="tasks:read"):
        actor.require("tasks:read")


def test_cursor_is_signed_and_actor_bound() -> None:
    codec = CursorCodec("cursor-secret-for-tests")
    cursor = codec.encode(UUID(int=1), 25)
    assert codec.decode(UUID(int=1), cursor) == 25
    with pytest.raises(InvalidInputError, match="invalid pagination"):
        codec.decode(UUID(int=2), cursor)
    with pytest.raises(InvalidInputError, match="invalid pagination"):
        codec.decode(UUID(int=1), cursor[:-2] + "xx")


def test_cursor_is_bound_to_the_original_query() -> None:
    codec = CursorCodec("cursor-secret-for-tests")
    cursor = codec.encode(UUID(int=1), 25, "tasks:v1:project=one:status=todo")
    assert codec.decode(UUID(int=1), cursor, "tasks:v1:project=one:status=todo") == 25
    with pytest.raises(InvalidInputError, match="invalid pagination"):
        codec.decode(UUID(int=1), cursor, "tasks:v1:project=two:status=todo")
