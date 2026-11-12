"""The owner's time zone decides what "today" and an agenda day mean."""

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from sidekick.shared.config import DEFAULT_OWNER_TIMEZONE, Settings
from sidekick.shared.types import Actor, SystemClock
from sidekick.work.application.service import ContextService
from sidekick.work.application.work_lists import owner_day_bounds
from tests.support.fakes import make_cursor_codec

STOCKHOLM = ZoneInfo("Europe/Stockholm")


def test_owner_timezone_defaults_to_stockholm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIDEKICK_OWNER_TIMEZONE", raising=False)

    settings = Settings(_env_file=None)

    assert DEFAULT_OWNER_TIMEZONE == "Europe/Stockholm"
    assert settings.owner_timezone == "Europe/Stockholm"
    assert settings.owner_zone == STOCKHOLM


def test_owner_timezone_is_read_from_the_prefixed_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIDEKICK_OWNER_TIMEZONE", "America/New_York")

    assert Settings(_env_file=None).owner_zone == ZoneInfo("America/New_York")


@pytest.mark.parametrize("value", ["Mars/Olympus", "", "../etc/passwd", "UTC+1"])
def test_invalid_owner_timezone_fails_at_startup(value: str) -> None:
    with pytest.raises(ValidationError, match="SIDEKICK_OWNER_TIMEZONE"):
        Settings(_env_file=None, owner_timezone=value)


def test_invalid_owner_timezone_error_does_not_repeat_the_value() -> None:
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, owner_timezone="Mars/Olympus")

    assert "Mars" not in str(error.value)


def test_late_utc_evening_is_already_the_next_day_in_stockholm() -> None:
    # 23:30 UTC on 28 October is 00:30 on 29 October in Stockholm (CET, UTC+1).
    late_utc = datetime(2026, 10, 28, 23, 30, tzinfo=UTC)
    morning_of_29th = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)

    start, end = owner_day_bounds(late_utc, STOCKHOLM)

    assert late_utc.date() == date(2026, 10, 28)
    assert start <= morning_of_29th < end
    assert not start <= morning_of_29th - timedelta(days=1) < end


def test_same_utc_day_can_be_two_owner_days() -> None:
    # 22:30 UTC is 23:30 in Stockholm, still 28 October; 23:30 UTC is already 29 October.
    before_midnight = datetime(2026, 10, 28, 22, 30, tzinfo=UTC)
    after_midnight = datetime(2026, 10, 28, 23, 30, tzinfo=UTC)

    start, end = owner_day_bounds(before_midnight, STOCKHOLM)

    assert before_midnight.date() == after_midnight.date()
    assert start <= before_midnight < end
    assert not start <= after_midnight < end


def test_owner_day_is_local_midnight_to_local_midnight_across_a_clock_change() -> None:
    # Stockholm leaves summer time on 25 October 2026: that local day lasts 25 hours.
    start, end = owner_day_bounds(datetime(2026, 10, 25, 12, 0, tzinfo=UTC), STOCKHOLM)

    assert start == datetime(2026, 10, 24, 22, 0, tzinfo=UTC)
    assert end == datetime(2026, 10, 25, 23, 0, tzinfo=UTC)


class _RecordingStore:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def transaction(self, operation: Callable[[Any], Any]) -> Any:
        return operation(None)

    def estimate_totals(self, session: Any, owner_id: Any, **kwargs: Any) -> dict[str, int]:
        self.calls.append(kwargs)
        return {
            "task_count": 0,
            "estimated_minutes_total": 0,
            "overdue_minutes": 0,
            "unestimated_count": 0,
        }


def test_agenda_day_starts_at_local_midnight_in_the_owner_zone() -> None:
    store = _RecordingStore()
    contexts = ContextService(
        cast(Any, store), SystemClock(), make_cursor_codec(), owner_timezone=STOCKHOLM
    )
    actor = Actor(uuid4(), frozenset({"tasks:read"}))

    contexts.estimate_totals(actor, scope="agenda_day", agenda_day=date(2026, 10, 29))

    # Local midnight on 29 October is 23:00 UTC on 28 October, and the day ends 24 hours later.
    assert store.calls[0]["agenda_start"] == datetime(2026, 10, 28, 23, 0, tzinfo=UTC)
    assert store.calls[0]["agenda_end"] == datetime(2026, 10, 29, 23, 0, tzinfo=UTC)
