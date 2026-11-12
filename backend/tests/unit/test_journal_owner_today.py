"""The owner's "today" in the journal: the calendar date in Europe/Stockholm, with no database."""

from datetime import UTC, date, datetime, timedelta

import pytest

from sidekick.journal.domain.day_done import day_bounds, owner_today
from sidekick.shared.config import parse_owner_timezone

STOCKHOLM = parse_owner_timezone("Europe/Stockholm")


@pytest.mark.parametrize(
    ("instant", "expected"),
    [
        # Winter (UTC+1): 23:30 UTC on 4 November is already 00:30 on the 5th in Stockholm.
        (datetime(2026, 11, 4, 22, 59, 59, tzinfo=UTC), date(2026, 11, 4)),
        (datetime(2026, 11, 4, 23, 0, 0, tzinfo=UTC), date(2026, 11, 5)),
        (datetime(2026, 11, 4, 23, 30, tzinfo=UTC), date(2026, 11, 5)),
        # Summer (UTC+2): the owner's midnight is 22:00 UTC.
        (datetime(2026, 7, 20, 21, 59, 59, tzinfo=UTC), date(2026, 7, 20)),
        (datetime(2026, 7, 20, 22, 0, 0, tzinfo=UTC), date(2026, 7, 21)),
        # The instant counts, not its own offset: a New York clock still gives the Stockholm day.
        (datetime.fromisoformat("2026-11-04T18:30:00-05:00"), date(2026, 11, 5)),
    ],
)
def test_the_day_turns_at_the_owners_midnight_not_at_utc_midnight(
    instant: datetime, expected: date
) -> None:
    assert owner_today(instant, STOCKHOLM) == expected


def test_the_spring_forward_day_starts_and_ends_at_stockholm_midnight() -> None:
    # 2026-03-29: 02:00 becomes 03:00, so the day is 23 hours; midnight is 23:00 UTC before it.
    start, end = day_bounds(date(2026, 3, 29), STOCKHOLM)
    second = timedelta(seconds=1)

    assert owner_today(start.astimezone(UTC) - second, STOCKHOLM) == date(2026, 3, 28)
    assert owner_today(start.astimezone(UTC), STOCKHOLM) == date(2026, 3, 29)
    assert owner_today(end.astimezone(UTC) - second, STOCKHOLM) == date(2026, 3, 29)
    assert owner_today(end.astimezone(UTC), STOCKHOLM) == date(2026, 3, 30)
    # The jump itself (01:00 UTC) does not move the date.
    assert owner_today(datetime(2026, 3, 29, 0, 59, tzinfo=UTC), STOCKHOLM) == date(2026, 3, 29)
    assert owner_today(datetime(2026, 3, 29, 1, 0, tzinfo=UTC), STOCKHOLM) == date(2026, 3, 29)


def test_the_fall_back_day_is_25_hours_and_its_repeated_hour_stays_on_the_same_day() -> None:
    # 2026-10-25: 03:00 becomes 02:00. Both 02:30 (00:30 UTC and 01:30 UTC) are the 25th.
    assert owner_today(datetime(2026, 10, 24, 21, 59, tzinfo=UTC), STOCKHOLM) == date(2026, 10, 24)
    assert owner_today(datetime(2026, 10, 24, 22, 0, tzinfo=UTC), STOCKHOLM) == date(2026, 10, 25)
    assert owner_today(datetime(2026, 10, 25, 0, 30, tzinfo=UTC), STOCKHOLM) == date(2026, 10, 25)
    assert owner_today(datetime(2026, 10, 25, 1, 30, tzinfo=UTC), STOCKHOLM) == date(2026, 10, 25)
    assert owner_today(datetime(2026, 10, 25, 22, 59, tzinfo=UTC), STOCKHOLM) == date(2026, 10, 25)
    assert owner_today(datetime(2026, 10, 25, 23, 0, tzinfo=UTC), STOCKHOLM) == date(2026, 10, 26)


def test_a_naive_instant_is_refused_rather_than_read_in_the_servers_zone() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        owner_today(datetime(2026, 11, 4, 23, 30), STOCKHOLM)
