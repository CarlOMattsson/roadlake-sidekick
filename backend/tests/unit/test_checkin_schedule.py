"""When a check-in is due: off, snoozed, never answered, and the cadence."""

from datetime import date, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sidekick.checkins.domain.schedule import (
    CADENCE_DAYS,
    DEFAULT_CADENCE_DAYS,
    Schedule,
    is_due,
    is_valid_cadence,
    snooze_until,
)

TODAY = date(2026, 3, 16)


def test_the_cadences_are_a_week_a_fortnight_and_a_month() -> None:
    assert CADENCE_DAYS == (7, 14, 30)
    assert DEFAULT_CADENCE_DAYS == 7
    assert [is_valid_cadence(days) for days in (1, 7, 10, 14, 30, 31)] == [
        False,
        True,
        False,
        True,
        True,
        False,
    ]


@pytest.mark.parametrize("days", [0, 1, 8, 29, 365])
def test_a_schedule_refuses_a_cadence_outside_the_set(days: int) -> None:
    with pytest.raises(ValueError, match="cadence_days"):
        Schedule(enabled=True, cadence_days=days)


def test_it_is_never_due_while_switched_off() -> None:
    assert not is_due(Schedule(enabled=False), None, TODAY)
    assert not is_due(Schedule(enabled=False), TODAY - timedelta(days=400), TODAY)


def test_it_is_due_when_nothing_has_been_answered() -> None:
    assert is_due(Schedule(enabled=True), None, TODAY)


@pytest.mark.parametrize(
    ("cadence", "days_since", "due"),
    [(7, 6, False), (7, 7, True), (7, 8, True), (14, 13, False), (14, 14, True), (30, 29, False)],
)
def test_it_is_due_once_the_cadence_has_passed(cadence: int, days_since: int, due: bool) -> None:
    schedule = Schedule(enabled=True, cadence_days=cadence)
    assert is_due(schedule, TODAY - timedelta(days=days_since), TODAY) is due


def test_a_snooze_holds_it_back_until_the_day_itself() -> None:
    schedule = Schedule(enabled=True, snoozed_until=TODAY + timedelta(days=3))
    assert not is_due(schedule, None, TODAY)
    assert not is_due(schedule, None, TODAY + timedelta(days=2))
    assert is_due(schedule, None, TODAY + timedelta(days=3))


def test_a_snooze_does_not_make_a_recent_answer_due() -> None:
    schedule = Schedule(enabled=True, snoozed_until=TODAY - timedelta(days=1))
    assert not is_due(schedule, TODAY - timedelta(days=2), TODAY)


def test_a_missed_checkin_stays_due_with_no_overdue_state() -> None:
    schedule = Schedule(enabled=True)
    assert is_due(schedule, TODAY - timedelta(days=90), TODAY)
    assert is_due(schedule, TODAY - timedelta(days=9000), TODAY)


def test_an_answer_dated_in_the_future_is_not_due() -> None:
    assert not is_due(Schedule(enabled=True), TODAY + timedelta(days=1), TODAY)


def test_a_skip_is_due_again_one_cadence_later() -> None:
    assert snooze_until(TODAY, 7) == date(2026, 3, 23)
    assert snooze_until(TODAY, 30) == date(2026, 4, 15)
    with pytest.raises(ValueError, match="cadence_days"):
        snooze_until(TODAY, 5)


@given(
    st.sampled_from(CADENCE_DAYS), st.dates(min_value=date(2000, 1, 1), max_value=date(2100, 1, 1))
)
def test_after_a_skip_it_is_quiet_until_exactly_that_day(cadence: int, today: date) -> None:
    schedule = Schedule(
        enabled=True, cadence_days=cadence, snoozed_until=snooze_until(today, cadence)
    )
    assert not is_due(schedule, None, today)
    assert is_due(schedule, None, today + timedelta(days=cadence))
