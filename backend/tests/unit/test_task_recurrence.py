"""Pure recurring-task and blocked-reminder behavior."""

from datetime import UTC, date, datetime, tzinfo
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from sidekick.shared.cadence import Cadence
from sidekick.shared.errors import ValidationError
from sidekick.shared.types import Actor
from sidekick.tasks.application import TaskService
from sidekick.tasks.domain import Priority, RecurrenceRule, Task, TaskStatus
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


def _last_weekdays(rule: RecurrenceRule, start: datetime, count: int, zone: tzinfo) -> list[date]:
    found: list[date] = []
    current = start
    for _ in range(count):
        next_due = rule.next_due_at(current, zone)
        assert next_due is not None
        found.append(next_due.astimezone(zone).date())
        current = next_due
    return found


def test_last_weekday_of_the_month_steps_back_from_a_weekend() -> None:
    rule = RecurrenceRule(frequency="monthly", last_weekday=True)

    # Only 31 Oct 2026 ends on a weekend (Saturday), so it lands on Friday the 30th.
    assert _last_weekdays(rule, datetime(2026, 7, 15, 9, tzinfo=UTC), 5, UTC) == [
        date(2026, 8, 31),
        date(2026, 9, 30),
        date(2026, 10, 30),
        date(2026, 11, 30),
        date(2026, 12, 31),
    ]


def test_last_weekday_of_february_in_a_leap_and_a_common_year() -> None:
    rule = RecurrenceRule(frequency="monthly", last_weekday=True)

    # 29 Feb 2028 is a Tuesday; 28 Feb 2027 is a Sunday, so Friday 26 February.
    assert rule.next_due_at(datetime(2028, 1, 10, 9, tzinfo=UTC)) == datetime(
        2028, 2, 29, 9, tzinfo=UTC
    )
    assert rule.next_due_at(datetime(2027, 1, 10, 9, tzinfo=UTC)) == datetime(
        2027, 2, 26, 9, tzinfo=UTC
    )


def test_last_weekday_keeps_local_wall_clock_across_a_clock_change() -> None:
    rule = RecurrenceRule(frequency="monthly", last_weekday=True)
    # 09:00 Stockholm (CEST) on Friday 25 September; the last weekday of October is Friday the
    # 30th, after the clocks went back on the 25th, so 09:00 local is 08:00 UTC.
    anchor = datetime(2026, 9, 25, 7, tzinfo=UTC)
    assert rule.next_due_at(anchor, STOCKHOLM) == datetime(2026, 10, 30, 8, tzinfo=UTC)


def test_last_weekday_every_second_month_and_until() -> None:
    rule = RecurrenceRule(
        frequency="monthly", interval=2, last_weekday=True, until=date(2026, 9, 1)
    )
    assert rule.next_due_at(datetime(2026, 6, 10, 9, tzinfo=UTC)) == datetime(
        2026, 8, 31, 9, tzinfo=UTC
    )
    assert rule.next_due_at(datetime(2026, 7, 10, 9, tzinfo=UTC)) is None


def test_last_weekday_is_monthly_only_and_excludes_a_day_of_month() -> None:
    with pytest.raises(ValidationError, match="only supported for monthly"):
        RecurrenceRule(frequency="weekly", last_weekday=True)
    with pytest.raises(ValidationError, match="cannot be combined"):
        RecurrenceRule(frequency="monthly", last_weekday=True, day_of_month=15)


def test_last_weekday_round_trips_through_the_stored_data() -> None:
    rule = RecurrenceRule(frequency="monthly", last_weekday=True)
    assert rule.to_data()["last_weekday"] is True
    assert RecurrenceRule.from_data(rule.to_data()) == rule
    # A rule stored before the field existed reads as not-last-weekday.
    assert RecurrenceRule.from_data({"frequency": "monthly"}) == RecurrenceRule(frequency="monthly")


def test_a_monthly_rule_without_a_day_keeps_the_day_the_task_was_due() -> None:
    rule = RecurrenceRule(frequency="monthly")
    # Due on the 15th but completed on the 3rd: the next one is due on the 15th of next month.
    assert rule.next_due_at(
        datetime(2026, 11, 3, 9, tzinfo=UTC), UTC, datetime(2026, 11, 15, 9, tzinfo=UTC)
    ) == datetime(2026, 12, 15, 9, tzinfo=UTC)
    # Without a due date the completion day stands.
    assert rule.next_due_at(datetime(2026, 11, 3, 9, tzinfo=UTC)) == datetime(
        2026, 12, 3, 9, tzinfo=UTC
    )


def test_a_monthly_task_completed_early_moves_on_from_its_due_month() -> None:
    rule = RecurrenceRule(frequency="monthly")
    # Due 5 Feb but finished on 30 Jan: the next one is 5 Mar, not 5 Feb again.
    assert rule.next_due_at(
        datetime(2026, 1, 30, 9, tzinfo=UTC), UTC, datetime(2026, 2, 5, 9, tzinfo=UTC)
    ) == datetime(2026, 3, 5, 9, tzinfo=UTC)


def test_a_monthly_task_completed_late_does_not_skip_a_month() -> None:
    rule = RecurrenceRule(frequency="monthly")
    # Due 28 Jan but finished on 2 Feb: the next one is 28 Feb, not 28 Mar.
    assert rule.next_due_at(
        datetime(2026, 2, 2, 9, tzinfo=UTC), UTC, datetime(2026, 1, 28, 9, tzinfo=UTC)
    ) == datetime(2026, 2, 28, 9, tzinfo=UTC)


def test_a_long_overdue_monthly_task_skips_the_occurrences_that_have_passed() -> None:
    rule = RecurrenceRule(frequency="monthly")
    due = datetime(2026, 1, 28, 9, tzinfo=UTC)
    # Due 28 Jan, finished 10 Apr: 28 Feb and 28 Mar are gone, so 28 Apr is next.
    assert rule.next_due_at(datetime(2026, 4, 10, 9, tzinfo=UTC), UTC, due) == datetime(
        2026, 4, 28, 9, tzinfo=UTC
    )
    # Finished on the 28th itself, that day has passed: the next one is 28 May.
    assert rule.next_due_at(datetime(2026, 4, 28, 9, tzinfo=UTC), UTC, due) == datetime(
        2026, 5, 28, 9, tzinfo=UTC
    )


def test_a_long_overdue_monthly_interval_and_until_apply_to_the_final_occurrence() -> None:
    due = datetime(2026, 1, 15, 9, tzinfo=UTC)
    done = datetime(2026, 5, 1, 9, tzinfo=UTC)
    rule = RecurrenceRule(frequency="monthly", interval=2)
    # 15 Mar has passed too, so the next one is 15 May.
    assert rule.next_due_at(done, UTC, due) == datetime(2026, 5, 15, 9, tzinfo=UTC)
    capped = RecurrenceRule(frequency="monthly", interval=2, until=date(2026, 5, 14))
    assert capped.next_due_at(done, UTC, due) is None


def test_last_weekday_completed_early_moves_to_the_next_months_last_weekday() -> None:
    rule = RecurrenceRule(frequency="monthly", last_weekday=True)
    # Friday 27 Feb 2026 is the last weekday of February; finished a month early on 30 Jan.
    due = datetime(2026, 2, 27, 9, tzinfo=UTC)
    assert rule.next_due_at(datetime(2026, 1, 30, 9, tzinfo=UTC), UTC, due) == datetime(
        2026, 3, 31, 9, tzinfo=UTC
    )
    # Finished two days early, within February, the next one is still March's.
    assert rule.next_due_at(datetime(2026, 2, 25, 9, tzinfo=UTC), UTC, due) == datetime(
        2026, 3, 31, 9, tzinfo=UTC
    )


def test_a_monthly_interval_counts_from_the_due_month() -> None:
    rule = RecurrenceRule(frequency="monthly", interval=2)
    assert rule.next_due_at(
        datetime(2026, 1, 30, 9, tzinfo=UTC), UTC, datetime(2026, 2, 5, 9, tzinfo=UTC)
    ) == datetime(2026, 4, 5, 9, tzinfo=UTC)


def test_a_monthly_due_month_is_read_in_the_owner_zone() -> None:
    rule = RecurrenceRule(frequency="monthly")
    # 23:30 UTC on 31 Jan is already 1 Feb in Stockholm, so the due month is February.
    due = datetime(2026, 1, 31, 23, 30, tzinfo=UTC)
    assert rule.next_due_at(datetime(2026, 1, 20, 9, tzinfo=UTC), STOCKHOLM, due) == datetime(
        2026, 3, 1, 9, tzinfo=UTC
    )


def test_a_monthly_rule_stops_at_until_measured_from_the_due_month() -> None:
    rule = RecurrenceRule(frequency="monthly", until=date(2026, 3, 4))
    due = datetime(2026, 2, 5, 9, tzinfo=UTC)
    assert rule.next_due_at(datetime(2026, 1, 30, 9, tzinfo=UTC), UTC, due) is None
    assert RecurrenceRule(frequency="monthly", until=date(2026, 3, 5)).next_due_at(
        datetime(2026, 1, 30, 9, tzinfo=UTC), UTC, due
    ) == datetime(2026, 3, 5, 9, tzinfo=UTC)


def test_task_service_completes_a_monthly_task_ahead_of_its_due_date() -> None:
    service = TaskService(InMemoryStore(), FixedClock(), make_cursor_codec())
    task = service.create(
        owner(),
        title="Pay the rent",
        idempotency_key="monthly-early",
        due_at=datetime(2026, 9, 5, 10, tzinfo=UTC),
        recurrence={"frequency": "monthly"},
    )

    completed = service.complete(owner(), task.id, version=task.version, idempotency_key="cycle-1")

    # Completed on 21 Aug, due 5 Sep: the next one is 5 Oct, not 5 Sep again.
    assert completed.due_at == datetime(2026, 10, 5, 10, tzinfo=UTC)


def test_a_weekly_two_weekday_rule_alternates_between_monday_and_thursday() -> None:
    rule = RecurrenceRule(frequency="weekly", weekdays=(0, 3))
    monday = datetime(2026, 8, 24, 9, tzinfo=UTC)
    assert rule.next_due_at(monday) == datetime(2026, 8, 27, 9, tzinfo=UTC)
    assert rule.next_due_at(datetime(2026, 8, 27, 9, tzinfo=UTC)) == datetime(
        2026, 8, 31, 9, tzinfo=UTC
    )


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
