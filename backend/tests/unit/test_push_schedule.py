"""When visible push reminders are due (ADR-005; D-078): pure rules, a fixed clock."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from sidekick.companion.push_schedule import DUE_WINDOW, SUMMARY_WINDOW, ReminderPolicy
from sidekick.shared.config import Settings

STOCKHOLM = ZoneInfo("Europe/Stockholm")
POLICY = ReminderPolicy(
    zone=STOCKHOLM,
    summary_time=time(8, 0),
    due_lead=timedelta(minutes=15),
    quiet_start=time(21, 0),
    quiet_end=time(7, 0),
)


EARLIER = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)  # A Task created long before every case.


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(UTC)


def local(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=STOCKHOLM)


def test_the_summary_opens_at_eight_in_the_owners_zone_not_in_utc() -> None:
    # November: Stockholm is UTC+1, so 08:00 there is 07:00 UTC.
    assert POLICY.summary_day(utc("2026-11-09T06:59:59+00:00")) is None
    assert POLICY.summary_day(utc("2026-11-09T07:00:00+00:00")) == date(2026, 11, 9)
    # July: UTC+2, so the same wall-clock time is an hour earlier in UTC.
    assert POLICY.summary_day(utc("2026-07-09T05:59:59+00:00")) is None
    assert POLICY.summary_day(utc("2026-07-09T06:00:00+00:00")) == date(2026, 7, 9)


def test_the_summary_day_is_the_owners_day_when_it_differs_from_the_utc_day() -> None:
    # The owner's 00:30 on the 9th is still the 8th in UTC: no summary then, one at 08:00.
    early = utc("2026-11-08T23:30:00+00:00")
    assert early.date() == date(2026, 11, 8)
    assert POLICY.summary_day(early) is None
    assert POLICY.summary_day(local("2026-11-09T08:00:00")) == date(2026, 11, 9)


def test_the_summary_stays_open_for_its_window_only() -> None:
    opens = local("2026-11-09T08:00:00")
    assert POLICY.summary_day(opens + SUMMARY_WINDOW - timedelta(seconds=1)) is not None
    assert POLICY.summary_day(opens + SUMMARY_WINDOW) is None


@pytest.mark.parametrize(
    ("moment", "quiet"),
    [
        ("2026-11-09T20:59:59", False),
        ("2026-11-09T21:00:00", True),
        ("2026-11-09T23:59:00", True),
        ("2026-11-10T00:00:00", True),
        ("2026-11-10T06:59:59", True),
        ("2026-11-10T07:00:00", False),
        ("2026-11-10T12:00:00", False),
    ],
)
def test_the_quiet_hours_run_from_21_to_07_in_the_owners_zone(moment: str, quiet: bool) -> None:
    assert POLICY.in_quiet_hours(local(moment)) is quiet


def test_a_summary_is_never_queued_in_quiet_hours() -> None:
    late = ReminderPolicy(STOCKHOLM, time(8, 0), timedelta(minutes=15), time(7, 30), time(8, 30))
    assert late.summary_day(local("2026-11-09T08:00:00")) is None
    assert late.summary_day(local("2026-11-09T08:30:00")) == date(2026, 11, 9)


def test_a_due_reminder_comes_fifteen_minutes_before_the_clock_time() -> None:
    due = local("2026-11-09T14:00:00")
    assert POLICY.due_reminder_time(due) == local("2026-11-09T13:45:00")
    assert not POLICY.due_reminder_is_due(due, local("2026-11-09T13:44:59"), EARLIER)
    assert POLICY.due_reminder_is_due(due, local("2026-11-09T13:45:00"), EARLIER)
    assert POLICY.due_reminder_is_due(due, due - timedelta(seconds=1), EARLIER)


def test_a_bare_date_stored_as_2359_has_no_clock_time_to_announce() -> None:
    assert POLICY.due_reminder_time(local("2026-11-09T23:59:00")) is None
    assert not POLICY.has_clock_time(local("2026-11-09T23:59:00"))
    assert POLICY.has_clock_time(local("2026-11-09T23:58:00"))
    # The same instant in UTC (22:59) is still the bare date: the owner's zone decides.
    assert POLICY.due_reminder_time(utc("2026-11-09T22:59:00+00:00")) is None
    assert not POLICY.due_reminder_is_due(
        local("2026-11-09T23:59:00"), local("2026-11-09T23:50:00"), EARLIER
    )


@pytest.mark.parametrize(
    ("due", "expected"),
    [
        # 06:55 is quiet: moved to 07:00 the same morning.
        ("2026-11-10T07:10:00", "2026-11-10T07:00:00"),
        ("2026-11-10T02:00:00", "2026-11-10T07:00:00"),
        # 21:15 and 22:45 are quiet: moved to 07:00 the next morning.
        ("2026-11-09T21:30:00", "2026-11-10T07:00:00"),
        ("2026-11-09T23:00:00", "2026-11-10T07:00:00"),
        # 20:55 and 07:15 are not quiet: shown at their own time.
        ("2026-11-09T21:10:00", "2026-11-09T20:55:00"),
        ("2026-11-10T07:30:00", "2026-11-10T07:15:00"),
    ],
)
def test_a_due_reminder_in_quiet_hours_is_moved_to_seven(due: str, expected: str) -> None:
    assert POLICY.due_reminder_time(local(due)) == local(expected)


def test_a_moved_reminder_is_eligible_from_seven_even_when_the_task_is_already_due() -> None:
    due = local("2026-11-09T22:00:00")
    assert not POLICY.due_reminder_is_due(due, local("2026-11-10T06:59:59"), EARLIER)
    assert POLICY.due_reminder_is_due(due, local("2026-11-10T07:00:00"), EARLIER)
    assert not POLICY.due_reminder_is_due(due, local("2026-11-10T07:00:00") + DUE_WINDOW, EARLIER)


def test_a_due_at_moved_far_into_the_past_is_not_announced_late() -> None:
    assert not POLICY.due_reminder_is_due(
        local("2026-11-09T10:00:00"), local("2026-11-09T18:00:00"), EARLIER
    )


def test_a_task_created_after_its_reminder_moment_gets_no_reminder_for_a_time_already_past() -> (
    None
):
    # Created 10:30, due 09:00: the moment (08:45) is behind it and so is the due time.
    due = local("2026-11-09T09:00:00")
    created = local("2026-11-09T10:30:00")
    assert not POLICY.due_reminder_is_due(due, local("2026-11-09T10:31:00"), created)
    # The same Task, still before its due time, would have been announced: the ordinary case.
    assert POLICY.due_reminder_is_due(due, local("2026-11-09T08:50:00"), EARLIER)


def test_a_reminder_moved_to_seven_needs_a_task_that_existed_by_then() -> None:
    due = local("2026-11-10T02:00:00")  # The moment 01:45 is quiet: moved to 07:00.
    seven = local("2026-11-10T07:00:00")
    assert POLICY.due_reminder_is_due(due, seven, seven)  # created exactly at the moment
    assert POLICY.due_reminder_is_due(due, seven, local("2026-11-09T20:00:00"))
    # Created at 07:05 with a night due_at: overdue already, left to the morning summary.
    assert not POLICY.due_reminder_is_due(
        due, local("2026-11-10T07:10:00"), local("2026-11-10T07:05:00")
    )


def test_the_reminder_time_follows_the_clock_across_the_dst_change() -> None:
    # 2026-10-25 the clocks go back at 03:00 CEST: 14:00 that day is CET (UTC+1).
    due = local("2026-10-25T14:00:00")
    assert POLICY.due_reminder_time(due) == utc("2026-10-25T12:45:00+00:00")


def settings(**fields: object) -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+psycopg://x:y@127.0.0.1:1/z",
        cursor_signing_secret="session-secret-for-tests-only-123456",
        token_pepper="token-pepper-for-tests-only-12345678",
        **fields,  # type: ignore[arg-type]
    )


def test_the_defaults_are_the_contract_times() -> None:
    config = settings()
    assert (config.push_summary_time, config.push_due_lead_minutes) == (time(8, 0), 15)
    assert (config.push_quiet_start, config.push_quiet_end) == (time(21, 0), time(7, 0))


def test_a_summary_time_inside_the_quiet_hours_is_refused() -> None:
    with pytest.raises(ValueError, match="quiet"):
        settings(push_summary_time=time(22, 0))
    assert settings(push_summary_time=time(9, 30)).push_summary_time == time(9, 30)
