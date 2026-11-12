"""The day rule and the Step completion time, with no database."""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from sidekick.journal.domain.day_done import DayDone, day_bounds
from sidekick.tasks.domain import TaskStatus
from sidekick.work.domain.steps import Step

STOCKHOLM = ZoneInfo("Europe/Stockholm")
EARLY = datetime(2026, 11, 8, 8, 0, tzinfo=UTC)
LATER = EARLY + timedelta(hours=3)


def _length(day: date) -> timedelta:
    start, end = day_bounds(day, STOCKHOLM)
    return end.astimezone(UTC) - start.astimezone(UTC)


def test_an_ordinary_day_runs_midnight_to_midnight_in_the_owner_zone() -> None:
    start, end = day_bounds(date(2026, 7, 21), STOCKHOLM)

    # Summer time: midnight in Stockholm is 22:00 UTC the evening before.
    assert start.astimezone(UTC) == datetime(2026, 7, 20, 22, 0, tzinfo=UTC)
    assert end.astimezone(UTC) == datetime(2026, 7, 21, 22, 0, tzinfo=UTC)
    assert _length(date(2026, 7, 21)) == timedelta(hours=24)
    start, _ = day_bounds(date(2026, 1, 15), STOCKHOLM)
    assert start.astimezone(UTC) == datetime(2026, 1, 14, 23, 0, tzinfo=UTC)


def test_the_days_of_the_clock_changes_are_23_and_25_hours_long() -> None:
    assert _length(date(2026, 3, 29)) == timedelta(hours=23)
    assert _length(date(2026, 10, 25)) == timedelta(hours=25)


def test_an_empty_day_has_zero_counts_and_is_not_truncated() -> None:
    done = DayDone()

    assert (done.tasks, done.steps, done.purchases) == ((), (), ())
    assert (done.counts.tasks, done.counts.steps, done.counts.purchases) == (0, 0, 0)
    assert done.truncated is False


def _step(**changes: object) -> Step:
    values: dict[str, object] = {
        "id": uuid4(),
        "owner_id": uuid4(),
        "task_id": uuid4(),
        "title": "Ring",
        "status": TaskStatus.TODO,
        "position": 0,
        "due_at": None,
        "attention_requested": False,
        "created_at": EARLY,
        "updated_at": EARLY,
    }
    values.update(changes)
    return Step(**values)  # type: ignore[arg-type]


def test_completing_a_step_records_when_and_keeps_the_first_time() -> None:
    done = _step().complete(now=EARLY)

    assert done.completed_at == EARLY
    again = done.complete(now=LATER)
    assert again is done
    assert again.completed_at == EARLY


def test_setting_status_completed_records_the_time_and_reopening_clears_it() -> None:
    done = _step().update(now=EARLY, status=TaskStatus.COMPLETED)
    assert done.completed_at == EARLY

    # An edit that leaves the status alone keeps the time.
    renamed = done.update(now=LATER, title="Ring igen")
    assert renamed.completed_at == EARLY

    # Same status again keeps the original time.
    assert done.update(now=LATER, status=TaskStatus.COMPLETED).completed_at == EARLY

    reopened = done.update(now=LATER, status=TaskStatus.IN_PROGRESS)
    assert reopened.completed_at is None
    assert reopened.status is TaskStatus.IN_PROGRESS

    # Ticked off a second time, the new time wins.
    assert reopened.complete(now=LATER + timedelta(hours=1)).completed_at == LATER + timedelta(
        hours=1
    )


def test_a_new_step_has_no_completion_time() -> None:
    assert _step().completed_at is None
