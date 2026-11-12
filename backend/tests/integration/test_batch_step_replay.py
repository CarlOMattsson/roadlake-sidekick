"""A batch create replays the Steps it created, not the Task's current first ten.

The idempotency record keeps the created Step ids. A retry rebuilds the reply from exactly those
ids in creation order, with each Step as it is now. A recorded Step that was archived, trashed
or deleted since is left out; a record from before Step ids were kept falls back to the Task's
current live Steps.
"""

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session, sessionmaker

from sidekick.api.app import Container, create_app
from sidekick.shared.persistence.models import IdempotencyRow, StepRow
from sidekick.shared.types import Actor, utc_now
from sidekick.tasks.application.models import NewTaskItem, TaskBatch
from sidekick.tasks.domain import Priority
from tests.db import database_factory
from tests.support.settings import make_settings

SCOPES = frozenset({"tasks:read", "tasks:write", "projects:read", "projects:write"})
KEY = "batch-step-replay-1"


def _setup() -> tuple[Container, Actor, sessionmaker[Session]]:
    factory = database_factory()
    container: Container = create_app(make_settings(), factory).state.container
    owner = container.auth.provision_user("batch-replay", "Owner")
    return container, Actor(owner, SCOPES), factory


def _batch(container: Container, actor: Actor) -> TaskBatch:
    item = NewTaskItem("Plan", None, Priority.NORMAL, (), ("Ett", "Två", "Tre"))
    return container.task_bulk.create_batch(actor, [item], idempotency_key=KEY)


def _replay(container: Container, actor: Actor) -> TaskBatch:
    """The same batch call again, which the store answers from the record."""

    return _batch(container, actor)


def _ids(batch: TaskBatch) -> list[str]:
    return [step["id"] for step in batch.tasks[0].steps]


def _titles(batch: TaskBatch) -> list[str]:
    return [step["title"] for step in batch.tasks[0].steps]


@pytest.mark.integration
def test_the_record_keeps_step_ids_and_no_titles() -> None:
    container, actor, factory = _setup()
    batch = _batch(container, actor)

    with factory() as session:
        record = session.scalars(select(IdempotencyRow.result)).one()
    assert record == {
        "tasks": [
            {
                "task": {"id": str(batch.tasks[0].task.id)},
                "steps": [{"id": step_id} for step_id in _ids(batch)],
            }
        ]
    }


@pytest.mark.integration
def test_replay_after_adding_a_step_returns_only_the_created_steps() -> None:
    container, actor, _ = _setup()
    first = _batch(container, actor)
    task_id = first.tasks[0].task.id
    container.steps.create_step(actor, task_id, title="Fyra", idempotency_key="extra-step-1")

    replayed = _replay(container, actor)

    assert _ids(replayed) == _ids(first)
    assert _titles(replayed) == ["Ett", "Två", "Tre"]


@pytest.mark.integration
def test_replay_after_adding_steps_beyond_ten_still_returns_the_created_ones() -> None:
    container, actor, _ = _setup()
    first = _batch(container, actor)
    task_id = first.tasks[0].task.id
    for number in range(12):
        container.steps.create_step(
            actor, task_id, title=f"Extra {number}", idempotency_key=f"extra-many-{number}"
        )

    assert _ids(_replay(container, actor)) == _ids(first)


@pytest.mark.integration
def test_replay_after_reordering_keeps_creation_order_with_current_positions() -> None:
    container, actor, _ = _setup()
    first = _batch(container, actor)
    task_id = first.tasks[0].task.id
    steps = container.steps.list_steps(actor, task_id).items
    reordered = container.steps.reorder_steps(
        actor,
        task_id,
        items=[(step.id, step.version) for step in (steps[2], steps[0], steps[1])],
        idempotency_key="reorder-batch-1",
    )

    replayed = _replay(container, actor)

    assert _ids(replayed) == _ids(first)
    positions = {str(step.id): step.position for step in reordered.items}
    assert [step["position"] for step in replayed.tasks[0].steps] == [
        positions[step_id] for step_id in _ids(first)
    ]


@pytest.mark.integration
def test_replay_leaves_out_a_created_step_that_was_archived() -> None:
    container, actor, _ = _setup()
    first = _batch(container, actor)
    middle = container.steps.get_step(actor, UUID(_ids(first)[1]))
    container.steps.archive_step(
        actor, middle.id, version=middle.version, idempotency_key="archive-batch-1"
    )

    replayed = _replay(container, actor)

    assert _titles(replayed) == ["Ett", "Tre"]
    assert _ids(replayed) == [_ids(first)[0], _ids(first)[2]]


@pytest.mark.integration
def test_replay_leaves_out_a_created_step_that_was_trashed_or_deleted() -> None:
    container, actor, factory = _setup()
    first = _batch(container, actor)
    with factory.begin() as session:
        session.execute(
            update(StepRow).where(StepRow.id == UUID(_ids(first)[0])).values(trashed_at=utc_now())
        )
        session.execute(delete(StepRow).where(StepRow.id == UUID(_ids(first)[2])))

    replayed = _replay(container, actor)

    assert _ids(replayed) == [_ids(first)[1]]
    assert _titles(replayed) == ["Två"]


@pytest.mark.integration
def test_an_old_record_without_step_ids_falls_back_to_the_current_live_steps() -> None:
    container, actor, factory = _setup()
    first = _batch(container, actor)
    task_id = first.tasks[0].task.id
    old_format: dict[str, Any] = {"tasks": [{"task": {"id": str(task_id)}}]}
    with factory.begin() as session:
        session.execute(update(IdempotencyRow).values(result=old_format))
    container.steps.create_step(actor, task_id, title="Fyra", idempotency_key="extra-step-old")

    replayed = _replay(container, actor)

    assert _titles(replayed) == ["Ett", "Två", "Tre", "Fyra"]


@pytest.mark.integration
def test_a_batch_without_steps_replays_with_no_steps() -> None:
    container, actor, _ = _setup()
    item = NewTaskItem("Bara titel", None, Priority.NORMAL, (), ())
    container.task_bulk.create_batch(actor, [item], idempotency_key="no-steps-1")
    task_id = container.tasks.list(actor, limit=10).items[0].id
    container.steps.create_step(actor, task_id, title="Senare", idempotency_key="later-step-1")

    replayed = container.task_bulk.create_batch(actor, [item], idempotency_key="no-steps-1")

    assert replayed.tasks[0].steps == ()
