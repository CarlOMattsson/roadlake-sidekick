"""Setting, changing and removing a Task's own recurrence through the update use case.

Recurrence is a property of the Task, not of a Process: `update_task` takes the same rule shape
the domain validates, and null removes it. No database: the in-memory store runs the real service.
"""

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError as PydanticValidationError

from sidekick.shared.errors import ConflictError, ValidationError
from sidekick.shared.types import Actor
from sidekick.structured.work_records import TaskChanges
from sidekick.tasks.application import TaskService, UpdateTaskCommand
from sidekick.tasks.domain import RecurrenceRule
from tests.support.fakes import InMemoryStore, make_cursor_codec

NOW = datetime(2026, 8, 21, 10, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return NOW


def _actor() -> Actor:
    return Actor(UUID(int=1), frozenset({"tasks:read", "tasks:write"}))


def _patch(changes: dict[str, Any]) -> UpdateTaskCommand:
    return UpdateTaskCommand(**TaskChanges.model_validate(changes).model_dump(exclude_unset=True))


def _service() -> TaskService:
    return TaskService(InMemoryStore(), FixedClock(), make_cursor_codec())


def test_update_sets_changes_and_removes_a_recurrence() -> None:
    service = _service()
    task = service.create(_actor(), title="Water the plants", idempotency_key="rec-create-0001")
    assert task.recurrence is None

    weekly = service.update(
        _actor(),
        task.id,
        version=task.version,
        idempotency_key="rec-set-0001",
        command=_patch({"recurrence": {"frequency": "weekly", "weekdays": [0, 3]}}),
    )
    assert weekly.recurrence == RecurrenceRule("weekly", weekdays=(0, 3))

    monthly = service.update(
        _actor(),
        task.id,
        version=weekly.version,
        idempotency_key="rec-change-0001",
        command=_patch({"recurrence": {"frequency": "monthly", "until": "2027-01-31"}}),
    )
    assert monthly.recurrence == RecurrenceRule("monthly", until=date(2027, 1, 31))

    cleared = service.update(
        _actor(),
        task.id,
        version=monthly.version,
        idempotency_key="rec-clear-0001",
        command=_patch({"recurrence": None}),
    )
    assert cleared.recurrence is None


def test_the_same_key_replays_a_recurrence_update_and_another_payload_conflicts() -> None:
    service = _service()
    task = service.create(_actor(), title="Pay rent", idempotency_key="rec-replay-create")
    command = _patch({"recurrence": {"frequency": "daily", "interval": 2}})

    first = service.update(
        _actor(), task.id, version=task.version, idempotency_key="rec-replay-0001", command=command
    )
    again = service.update(
        _actor(), task.id, version=task.version, idempotency_key="rec-replay-0001", command=command
    )
    assert again.version == first.version
    assert again.recurrence == RecurrenceRule("daily", interval=2)

    with pytest.raises(ConflictError):
        service.update(
            _actor(),
            task.id,
            version=task.version,
            idempotency_key="rec-replay-0001",
            command=_patch({"recurrence": {"frequency": "daily", "interval": 3}}),
        )


def test_update_needs_the_task_write_scope() -> None:
    service = _service()
    task = service.create(_actor(), title="Read only", idempotency_key="rec-scope-create")
    reader = Actor(UUID(int=1), frozenset({"tasks:read"}))
    with pytest.raises(Exception, match="tasks:write"):
        service.update(
            reader,
            task.id,
            version=task.version,
            idempotency_key="rec-scope-0001",
            command=_patch({"recurrence": {"frequency": "daily"}}),
        )
    assert service.get(_actor(), task.id).recurrence is None


@pytest.mark.parametrize(
    "rule",
    [
        {"frequency": "hourly"},
        {"frequency": "daily", "interval": 0},
        {"frequency": "daily", "interval": 13},
        {"frequency": "daily", "weekdays": [1]},
        {"frequency": "weekly", "weekdays": [7]},
        {"frequency": "weekly", "weekdays": [1, 1]},
        {"frequency": "weekly", "day_of_month": 3},
        {"frequency": "monthly", "day_of_month": 32},
        {"frequency": "monthly", "unknown": True},
    ],
)
def test_task_changes_refuses_what_the_domain_rule_refuses(rule: dict[str, Any]) -> None:
    with pytest.raises(PydanticValidationError):
        TaskChanges.model_validate({"recurrence": rule})
    if "unknown" not in rule and rule.get("frequency") != "hourly":
        with pytest.raises(ValidationError):
            RecurrenceRule.from_data(rule)


def test_task_changes_accepts_the_shapes_the_app_offers() -> None:
    for rule in (
        {"frequency": "daily"},
        {"frequency": "weekly"},
        {"frequency": "weekly", "weekdays": [0, 2, 4]},
        {"frequency": "monthly", "day_of_month": 31},
        {"frequency": "yearly", "interval": 2, "until": "2030-01-01"},
    ):
        changes = TaskChanges.model_validate({"recurrence": rule})
        assert changes.recurrence is not None
        assert "recurrence" in changes.model_dump(exclude_unset=True)
    # null is a change too (remove the rule); an empty change set is still refused.
    assert TaskChanges.model_validate({"recurrence": None}).model_fields_set == {"recurrence"}
    with pytest.raises(PydanticValidationError):
        TaskChanges.model_validate({})


def test_undoing_a_recurring_completion_restores_the_last_completion_and_the_due_date() -> None:
    service = _service()
    due = datetime(2026, 8, 21, 20, tzinfo=UTC)
    task = service.create(
        _actor(),
        title="Water the plants",
        idempotency_key="undo-create-0001",
        due_at=due,
        recurrence={"frequency": "daily"},
    )
    completed = service.complete(
        _actor(), task.id, version=task.version, idempotency_key="undo-complete-0001"
    )
    assert completed.last_completed_at == NOW
    assert completed.due_at != due

    undone = service.update(
        _actor(),
        task.id,
        version=completed.version,
        idempotency_key="undo-undo-0001",
        command=_patch({"due_at": due, "last_completed_at": None}),
    )

    assert undone.last_completed_at is None
    assert undone.due_at == due
    assert undone.status.value == "todo"


def test_last_completion_can_only_be_restored_backwards_on_a_recurring_task() -> None:
    service = _service()
    plain = service.create(_actor(), title="One-off", idempotency_key="lc-plain-0001")
    with pytest.raises(ValidationError):
        service.update(
            _actor(),
            plain.id,
            version=plain.version,
            idempotency_key="lc-plain-0002",
            command=_patch({"last_completed_at": NOW}),
        )

    recurring = service.create(
        _actor(),
        title="Daily",
        idempotency_key="lc-rec-0001",
        recurrence={"frequency": "daily"},
    )
    with pytest.raises(ValidationError):
        service.update(
            _actor(),
            recurring.id,
            version=recurring.version,
            idempotency_key="lc-rec-0002",
            command=_patch({"last_completed_at": NOW}),
        )
