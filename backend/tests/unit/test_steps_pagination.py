"""Step and Action listings continue with a signed keyset cursor, without a database."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from sidekick.shared.errors import InvalidInputError, PermissionDeniedError
from sidekick.shared.types import Actor, CursorCodec, new_uuid7
from sidekick.tasks.domain import TaskStatus
from sidekick.work.application.steps_service import StepsService
from sidekick.work.domain import Action, ActionStatus, Step

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
SCOPES = frozenset({"tasks:read"})
# Two rows share position 1, so the id tie-break has to keep the continuation exact.
POSITIONS = (0, 1, 1, 2, 3)


class FixedClock:
    def now(self) -> datetime:
        return NOW


class FakeStepsStore:
    """Only the reads a listing uses, ordered and filtered like the real store."""

    def __init__(self, steps: list[Step], actions: list[Action]) -> None:
        self.steps = steps
        self.actions = actions

    def transaction(self, operation: Callable[[Any], Any]) -> Any:
        return operation(None)

    def list_steps(
        self,
        session: Any,
        owner_id: UUID,
        task_id: UUID,
        limit: int,
        offset: int = 0,
        *,
        after: tuple[int, UUID] | None = None,
    ) -> list[Step]:
        rows = sorted(
            (s for s in self.steps if s.task_id == task_id and s.owner_id == owner_id),
            key=lambda s: (s.position, s.id),
        )
        return [s for s in rows if after is None or (s.position, s.id) > after][:limit]

    def list_actions(
        self,
        session: Any,
        owner_id: UUID,
        step_id: UUID,
        limit: int,
        offset: int = 0,
        *,
        after: tuple[int, UUID] | None = None,
    ) -> list[Action]:
        rows = sorted(
            (a for a in self.actions if a.step_id == step_id and a.owner_id == owner_id),
            key=lambda a: (a.position, a.id),
        )
        return [a for a in rows if after is None or (a.position, a.id) > after][:limit]


@dataclass(frozen=True)
class World:
    service: StepsService
    actor: Actor
    task_id: UUID
    step_id: UUID
    codec: CursorCodec


def _step(owner_id: UUID, task_id: UUID, position: int) -> Step:
    return Step(
        id=new_uuid7(),
        owner_id=owner_id,
        task_id=task_id,
        title=f"Step {position}",
        status=TaskStatus.TODO,
        position=position,
        due_at=None,
        attention_requested=False,
        created_at=NOW,
        updated_at=NOW,
    )


def _action(owner_id: UUID, step_id: UUID, position: int) -> Action:
    return Action(
        id=new_uuid7(),
        owner_id=owner_id,
        step_id=step_id,
        title=f"Action {position}",
        status=ActionStatus.OPEN,
        position=position,
        due_at=None,
        attention_requested=False,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.fixture
def world() -> World:
    actor = Actor(new_uuid7(), SCOPES)
    task_id, step_id = new_uuid7(), new_uuid7()
    store = FakeStepsStore(
        [_step(actor.user_id, task_id, p) for p in POSITIONS],
        [_action(actor.user_id, step_id, p) for p in POSITIONS],
    )
    codec = CursorCodec("unit-test-cursor-secret")
    service = StepsService(store, FixedClock(), codec)  # type: ignore[arg-type]
    return World(service, actor, task_id, step_id, codec)


def test_steps_are_read_in_pages_that_cover_every_step_once(world: World) -> None:
    first = world.service.list_steps(world.actor, world.task_id, limit=2)
    second = world.service.list_steps(world.actor, world.task_id, limit=2, cursor=first.next_cursor)
    third = world.service.list_steps(world.actor, world.task_id, limit=2, cursor=second.next_cursor)

    served = [s for page in (first, second, third) for s in page.items]
    assert [len(p.items) for p in (first, second, third)] == [2, 2, 1]
    assert first.next_cursor is not None
    assert second.next_cursor is not None
    assert third.next_cursor is None
    assert len({s.id for s in served}) == len(POSITIONS)
    assert [s.position for s in served] == sorted(POSITIONS)


def test_actions_are_read_in_pages_that_cover_every_action_once(world: World) -> None:
    first = world.service.list_actions(world.actor, world.step_id, limit=3)
    second = world.service.list_actions(
        world.actor, world.step_id, limit=3, cursor=first.next_cursor
    )

    assert [len(first.items), len(second.items)] == [3, 2]
    assert first.next_cursor is not None
    assert second.next_cursor is None
    assert len({a.id for a in first.items + second.items}) == len(POSITIONS)


def test_a_full_last_page_has_no_cursor(world: World) -> None:
    page = world.service.list_steps(world.actor, world.task_id, limit=len(POSITIONS))

    assert page.next_cursor is None


def test_a_cursor_is_bound_to_its_actor_and_parent(world: World) -> None:
    cursor = world.service.list_steps(world.actor, world.task_id, limit=2).next_cursor
    stranger = Actor(new_uuid7(), SCOPES)

    with pytest.raises(InvalidInputError, match="invalid pagination cursor"):
        world.service.list_steps(stranger, world.task_id, limit=2, cursor=cursor)
    with pytest.raises(InvalidInputError, match="invalid pagination cursor"):
        world.service.list_steps(world.actor, new_uuid7(), limit=2, cursor=cursor)
    with pytest.raises(InvalidInputError, match="invalid pagination cursor"):
        world.service.list_actions(world.actor, world.step_id, limit=2, cursor=cursor)
    with pytest.raises(InvalidInputError, match="invalid pagination cursor"):
        world.service.list_steps(world.actor, world.task_id, limit=2, cursor="not-a-cursor")


def test_a_signed_cursor_with_a_malformed_position_is_rejected(world: World) -> None:
    key = f"steps:v1:task={world.task_id}"
    malformed = ("7", f"x:{new_uuid7()}", f"-1:{new_uuid7()}", "1:nope")

    for position in malformed:
        forged = world.codec.encode_position(world.actor.user_id, position, key)
        with pytest.raises(InvalidInputError, match="invalid pagination cursor"):
            world.service.list_steps(world.actor, world.task_id, limit=2, cursor=forged)


def test_listings_require_the_read_scope_and_a_bounded_limit(world: World) -> None:
    blind = Actor(world.actor.user_id, frozenset())

    with pytest.raises(PermissionDeniedError):
        world.service.list_steps(blind, world.task_id)
    with pytest.raises(PermissionDeniedError):
        world.service.list_actions(blind, world.step_id)
    for limit in (0, 101):
        with pytest.raises(InvalidInputError):
            world.service.list_steps(world.actor, world.task_id, limit=limit)
        with pytest.raises(InvalidInputError):
            world.service.list_actions(world.actor, world.step_id, limit=limit)
