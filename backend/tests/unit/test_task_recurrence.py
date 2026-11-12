"""Pure recurring-task and blocked-reminder behavior."""

from datetime import UTC, date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from sidekick.shared.errors import ValidationError
from sidekick.shared.types import Actor
from sidekick.tasks.application import TaskService
from sidekick.tasks.domain import Priority, RecurrenceRule, Task, TaskStatus
from sidekick.work.domain.planning import Cadence
from tests.support.fakes import InMemoryStore, make_cursor_codec

NOW = datetime(2026, 8, 21, 10, tzinfo=UTC)
STOCKHOLM = ZoneInfo("Europe/Stockholm")
# 23:30 UTC on Sunday 23 August is 01:30 on Monday 24 August in Stockholm (CEST, UTC+2).
NEAR_MIDNIGHT = datetime(2026, 8, 23, 23, 30, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return NOW


def owner() -> Actor:
    return Actor(UUID(int=1), frozenset({"tasks:read", "tasks:write"}))


def test_recurring_completion_reopens_same_task_and_keeps_history() -> None:
    store = InMemoryStore()
    service = TaskService(store, FixedClock(), make_cursor_codec())
    task = service.create(
        owner(),
        title="Review weekly plan",
        idempotency_key="recurring-task",
        due_at=NOW,
        recurrence={"frequency": "weekly", "weekdays": [4]},
    )

    completed = service.complete(owner(), task.id, version=task.version, idempotency_key="cycle-1")

    assert completed.id == task.id
    assert completed.status is TaskStatus.TODO
    assert completed.completed_at is None
    assert completed.last_completed_at == NOW
    assert completed.due_at == datetime(2026, 8, 28, 10, tzinfo=UTC)
    assert [event.to_status for event in service.history(owner(), task.id)] == [
        TaskStatus.TODO,
        TaskStatus.COMPLETED,
        TaskStatus.TODO,
    ]


def test_blocked_reminder_respects_cadence_and_snooze() -> None:
    task = Task(
        id=UUID(int=2),
        owner_id=UUID(int=1),
        project_id=None,
        title="Waiting for approval",
        description=None,
        status=TaskStatus.BLOCKED,
        priority=Priority.NORMAL,
        due_at=None,
        completed_at=None,
        created_at=NOW,
        updated_at=NOW,
        blocked_reminder_cadence=Cadence.WEEKLY,
        blocked_reminder_snoozed_until=datetime(2026, 8, 25, tzinfo=UTC),
    )
    assert not task.blocked_reminder_due(now=NOW)
    assert task.blocked_reminder_due(now=datetime(2026, 8, 26, tzinfo=UTC))


def test_monthly_schedule_clamps_short_months() -> None:
    rule = RecurrenceRule(frequency="monthly", day_of_month=31)
    next_due = rule.next_due_at(datetime(2026, 1, 31, 9, tzinfo=UTC))
    assert next_due == datetime(2026, 2, 28, 9, tzinfo=UTC)
    assert rule.until is None


def test_biweekly_schedule_walks_every_allowed_weekday_before_skipping_a_week() -> None:
    rule = RecurrenceRule(frequency="weekly", interval=2, weekdays=(0, 2))
    # Monday 24 August, then Wednesday the same week, then Monday and Wednesday two weeks on.
    expected = [
        datetime(2026, 8, 26, 9, tzinfo=UTC),
        datetime(2026, 9, 7, 9, tzinfo=UTC),
        datetime(2026, 9, 9, 9, tzinfo=UTC),
        datetime(2026, 9, 21, 9, tzinfo=UTC),
        datetime(2026, 9, 23, 9, tzinfo=UTC),
        datetime(2026, 10, 5, 9, tzinfo=UTC),
    ]
    current = datetime(2026, 8, 24, 9, tzinfo=UTC)
    actual = []
    for _ in expected:
        next_due = rule.next_due_at(current)
        assert next_due is not None
        actual.append(next_due)
        current = next_due
    assert actual == expected


def test_every_third_week_sequence_is_stable_across_a_clock_change() -> None:
    rule = RecurrenceRule(frequency="weekly", interval=3, weekdays=(1, 4))
    # 09:00 Stockholm on Tuesday 6 October (CEST); the clocks go back on 25 October.
    current = datetime(2026, 10, 6, 7, tzinfo=UTC)
    local = []
    for _ in range(6):
        next_due = rule.next_due_at(current, STOCKHOLM)
        assert next_due is not None
        local.append(next_due.astimezone(STOCKHOLM))
        current = next_due
    assert [(d.month, d.day, d.hour) for d in local] == [
        (10, 9, 9),
        (10, 27, 9),
        (10, 30, 9),
        (11, 17, 9),
        (11, 20, 9),
        (12, 8, 9),
    ]
    assert {d.weekday() for d in local} == {1, 4}


def test_biweekly_completed_after_the_last_allowed_weekday_jumps_two_weeks() -> None:
    rule = RecurrenceRule(frequency="weekly", interval=2, weekdays=(0, 2))
    # Friday 28 August: no allowed weekday left this week, so Monday 7 September.
    assert rule.next_due_at(datetime(2026, 8, 28, 9, tzinfo=UTC)) == datetime(
        2026, 9, 7, 9, tzinfo=UTC
    )


def test_leaving_blocked_clears_a_stale_snooze_date() -> None:
    task = Task(
        id=UUID(int=3),
        owner_id=UUID(int=1),
        project_id=None,
        title="Unblock approval",
        description=None,
        status=TaskStatus.BLOCKED,
        priority=Priority.NORMAL,
        due_at=None,
        completed_at=None,
        created_at=NOW,
        updated_at=NOW,
        blocked_reminder_snoozed_until=datetime(2026, 8, 25, tzinfo=UTC),
    )
    reopened = task.update(now=NOW, status=TaskStatus.TODO)
    assert reopened.blocked_reminder_snoozed_until is None


def test_completing_blocked_task_clears_a_stale_snooze_date() -> None:
    task = Task(
        id=UUID(int=4),
        owner_id=UUID(int=1),
        project_id=None,
        title="Resolve blocked item",
        description=None,
        status=TaskStatus.BLOCKED,
        priority=Priority.NORMAL,
        due_at=None,
        completed_at=None,
        created_at=NOW,
        updated_at=NOW,
        blocked_reminder_snoozed_until=datetime(2026, 8, 25, tzinfo=UTC),
    )
    completed = task.complete(now=NOW)
    assert completed.status is TaskStatus.COMPLETED
    assert completed.blocked_reminder_snoozed_until is None


class _Clock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def now(self) -> datetime:
        return self.at


def test_weekly_weekday_is_read_in_the_owner_zone_near_midnight() -> None:
    rule = RecurrenceRule(frequency="weekly", weekdays=(0,))

    # In UTC the anchor is still Sunday, so the old UTC reading gave Monday 24 August 23:30 UTC.
    assert rule.next_due_at(NEAR_MIDNIGHT) == datetime(2026, 8, 24, 23, 30, tzinfo=UTC)
    # In Stockholm the anchor is Monday 01:30, so the next Monday is 31 August at 01:30 local.
    assert rule.next_due_at(NEAR_MIDNIGHT, STOCKHOLM) == datetime(2026, 8, 30, 23, 30, tzinfo=UTC)


def test_daily_recurrence_keeps_local_wall_clock_across_a_clock_change() -> None:
    rule = RecurrenceRule(frequency="daily")
    # 09:00 Stockholm on Saturday 24 October is 07:00 UTC (CEST); Sunday 25 October is CET.
    anchor = datetime(2026, 10, 24, 7, 0, tzinfo=UTC)

    assert rule.next_due_at(anchor, STOCKHOLM) == datetime(2026, 10, 25, 8, 0, tzinfo=UTC)


def test_until_is_compared_as_an_owner_date() -> None:
    rule = RecurrenceRule(frequency="daily", until=date(2026, 8, 24))

    # Completed 00:30 Monday local; the next run is Tuesday 25 August local, past `until`.
    assert rule.next_due_at(NEAR_MIDNIGHT, STOCKHOLM) is None
    # Read in UTC the next run was Monday 24 August UTC, wrongly still inside `until`.
    assert rule.next_due_at(NEAR_MIDNIGHT) is not None


def test_task_service_completes_a_recurring_task_on_the_owner_weekday() -> None:
    store = InMemoryStore()
    service = TaskService(
        store, _Clock(NEAR_MIDNIGHT), make_cursor_codec(), owner_timezone=STOCKHOLM
    )
    task = service.create(
        owner(),
        title="Monday review",
        idempotency_key="monday-review",
        due_at=NEAR_MIDNIGHT,
        recurrence={"frequency": "weekly", "weekdays": [0]},
    )

    completed = service.complete(owner(), task.id, version=task.version, idempotency_key="cycle")

    assert completed.status is TaskStatus.TODO
    assert completed.due_at == datetime(2026, 8, 30, 23, 30, tzinfo=UTC)


def test_a_task_cannot_be_filed_under_both_a_project_and_a_process() -> None:
    # `hierarchy_tasks` picks `project_id or process_id` as the parent and relies on this.
    with pytest.raises(ValidationError, match="at most one"):
        Task(
            id=UUID(int=3),
            owner_id=UUID(int=1),
            project_id=UUID(int=4),
            process_id=UUID(int=5),
            title="Both",
            description=None,
            status=TaskStatus.TODO,
            priority=Priority.NORMAL,
            due_at=None,
            completed_at=None,
            created_at=NOW,
            updated_at=NOW,
        )
