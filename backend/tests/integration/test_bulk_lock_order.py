"""Multi-Task writes lock their rows in id order, whatever order the caller lists the Tasks in.

So two such writes over the same Tasks, listed in opposite orders, queue behind each other instead
of each holding one row the other waits for. Proved with a held lock: while the higher id is held
elsewhere, a write listing it first must already hold the lower id.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from sidekick.api.app import Container, create_container
from sidekick.shared.persistence.models import TaskRow
from sidekick.shared.types import Actor
from sidekick.tasks.application.models import RescheduleTaskItem, ReviewDecisionItem
from sidekick.tasks.domain import Task
from sidekick.tasks.domain.review import ReviewDecision
from tests.db import database_factory
from tests.support.settings import make_settings

SCOPES = frozenset({"tasks:read", "tasks:write", "projects:read"})


def _lock_held(factory: sessionmaker[Session], task_id: UUID) -> bool:
    with factory.begin() as probe:
        try:
            probe.execute(
                select(TaskRow.id).where(TaskRow.id == task_id).with_for_update(nowait=True)
            )
        except DBAPIError:
            return True
    return False


def _tasks(container: Container, actor: Actor) -> tuple[Task, Task]:
    made = [
        container.tasks.create(
            actor, title=f"Låsordning {n}", idempotency_key=f"lock-{uuid4().hex}"
        )
        for n in range(2)
    ]
    low, high = sorted(made, key=lambda task: task.id)
    return low, high


def _review(container: Container, actor: Actor, low: Task, high: Task) -> list[UUID]:
    reviewed = container.task_bulk.review(
        actor,
        [
            ReviewDecisionItem(high.id, high.version, ReviewDecision.KEEP),
            ReviewDecisionItem(low.id, low.version, ReviewDecision.KEEP),
        ],
        idempotency_key=f"lock-review-{uuid4().hex}",
    )
    return [entry.task.id for entry in reviewed]


def _reschedule(container: Container, actor: Actor, low: Task, high: Task) -> list[UUID]:
    moved = container.task_bulk.reschedule(
        actor,
        [
            RescheduleTaskItem(high.id, high.version, None),
            RescheduleTaskItem(low.id, low.version, None),
        ],
        idempotency_key=f"lock-move-{uuid4().hex}",
    )
    return [task.id for task in moved]


@pytest.mark.integration
@pytest.mark.parametrize("write", [_review, _reschedule], ids=["review_tasks", "reschedule_tasks"])
def test_a_bulk_write_takes_the_lower_id_first_and_answers_in_the_callers_order(
    write: Callable[[Container, Actor, Task, Task], list[UUID]],
) -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    actor = Actor(container.auth.provision_user("lock-order", "Lock Order"), SCOPES)
    low, high = _tasks(container, actor)
    answer: list[UUID] = []

    with factory.begin() as holder:
        holder.execute(select(TaskRow.id).where(TaskRow.id == high.id).with_for_update())
        worker = threading.Thread(target=lambda: answer.extend(write(container, actor, low, high)))
        worker.start()
        deadline = time.monotonic() + 10
        while not _lock_held(factory, low.id) and time.monotonic() < deadline:
            time.sleep(0.05)
        low_locked_first = _lock_held(factory, low.id)
    worker.join(timeout=30)

    assert low_locked_first, "the write waited on the higher id without holding the lower one"
    assert not worker.is_alive()
    assert answer == [high.id, low.id]
