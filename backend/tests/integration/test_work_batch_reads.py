"""Batched Step and Action reads: per-parent cap in SQL, one array parameter for any id count."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

from sidekick.shared.auth import AuthService
from sidekick.shared.persistence.models import ActionRow, StepRow, TaskRow
from sidekick.shared.types import new_uuid7
from sidekick.work.persistence.steps_actions import StepActionStore
from tests.db import database_factory

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


def _task(owner: UUID) -> TaskRow:
    return TaskRow(
        id=new_uuid7(),
        owner_id=owner,
        title="Uppgift",
        status="todo",
        priority="normal",
        created_at=NOW,
        updated_at=NOW,
        version=1,
    )


def _step(owner: UUID, task_id: UUID, position: int, **extra: object) -> StepRow:
    return StepRow(
        id=new_uuid7(),
        owner_id=owner,
        task_id=task_id,
        title=f"Steg {position}",
        status="todo",
        position=position,
        created_at=NOW,
        updated_at=NOW,
        version=1,
        **extra,
    )


def _action(owner: UUID, step_id: UUID, position: int, **extra: object) -> ActionRow:
    return ActionRow(
        id=new_uuid7(),
        owner_id=owner,
        step_id=step_id,
        title=f"Åtgärd {position}",
        status="open",
        position=position,
        created_at=NOW,
        updated_at=NOW,
        version=1,
        **extra,
    )


def _owner() -> tuple[UUID, sessionmaker[Session]]:
    factory = database_factory()
    owner = AuthService(factory, "pepper" * 8).provision_user("owner", "Owner")
    return owner, factory


@pytest.mark.integration
def test_steps_are_capped_per_task_in_sql_and_ordered_like_the_single_task_read() -> None:
    owner, factory = _owner()
    short, long = _task(owner), _task(owner)
    with factory.begin() as session:
        session.add_all([short, long])
        session.flush()
        # Inserted out of position order; equal positions fall back to id.
        session.add_all(_step(owner, long.id, position) for position in (4, 2, 0, 3, 1))
        session.add_all(_step(owner, short.id, position) for position in (1, 0))
        session.add(_step(owner, long.id, 9, trashed_at=NOW))
        session.add(_step(owner, long.id, 8, archived_at=NOW))
    with factory() as session:
        grouped = StepActionStore.list_steps_for_tasks(
            session, owner, (short.id, long.id), per_task_limit=3
        )
        for task in (short, long):
            single = StepActionStore.list_steps(session, owner, task.id, 3)
            assert [step.id for step in grouped[task.id]] == [step.id for step in single]
        assert [step.position for step in grouped[long.id]] == [0, 1, 2]
        assert [step.position for step in grouped[short.id]] == [0, 1]
        with_archived = StepActionStore.list_steps_for_tasks(
            session, owner, (long.id,), per_task_limit=10, include_archived=True
        )
        assert [step.position for step in with_archived[long.id]] == [0, 1, 2, 3, 4, 8]


@pytest.mark.integration
def test_actions_are_capped_per_step_in_sql_and_ordered_like_the_single_step_read() -> None:
    owner, factory = _owner()
    task = _task(owner)
    first, second = _step(owner, task.id, 0), _step(owner, task.id, 1)
    with factory.begin() as session:
        session.add(task)
        session.flush()
        session.add_all([first, second])
        session.flush()
        session.add_all(_action(owner, first.id, position) for position in (3, 1, 0, 2))
        session.add(_action(owner, second.id, 0))
        session.add(_action(owner, first.id, 7, trashed_at=NOW))
    with factory() as session:
        grouped = StepActionStore.list_actions_for_steps(
            session, owner, (first.id, second.id), per_step_limit=2
        )
        for step in (first, second):
            single = StepActionStore.list_actions(session, owner, step.id, 2)
            assert [action.id for action in grouped[step.id]] == [a.id for a in single]
        assert [action.position for action in grouped[first.id]] == [0, 1]
        assert len(grouped[second.id]) == 1


@pytest.mark.integration
def test_batched_reads_take_more_ids_than_the_driver_has_parameters() -> None:
    owner, factory = _owner()
    task = _task(owner)
    with factory.begin() as session:
        session.add(task)
        session.flush()
        session.add(_step(owner, task.id, 0))
    ids = (*(uuid4() for _ in range(70_000)), task.id)
    with factory() as session:
        assert len(StepActionStore.list_steps_for_tasks(session, owner, ids)[task.id]) == 1
        assert StepActionStore.list_actions_for_steps(session, owner, ids) == {}
