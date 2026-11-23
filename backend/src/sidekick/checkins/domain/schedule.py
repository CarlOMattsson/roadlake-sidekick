"""When a check-in is due. A missed one simply stays due and quiet: no streak, no overdue state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Final

CADENCE_DAYS: Final = (7, 14, 30)
DEFAULT_CADENCE_DAYS: Final = 7


def is_valid_cadence(days: int) -> bool:
    return days in CADENCE_DAYS


@dataclass(frozen=True, slots=True)
class Schedule:
    """The owner's settings that decide whether a check-in is due."""

    enabled: bool
    cadence_days: int = DEFAULT_CADENCE_DAYS
    snoozed_until: date | None = None
    """The day it is next due after a skip; a date in the owner's own time zone."""

    def __post_init__(self) -> None:
        if not is_valid_cadence(self.cadence_days):
            raise ValueError("cadence_days must be 7, 14 or 30")


def is_due(schedule: Schedule, last_answered_on: date | None, today: date) -> bool:
    """Whether to offer a check-in on `today` (the owner's calendar day, given by the caller)."""

    if not schedule.enabled:
        return False
    if schedule.snoozed_until is not None and today < schedule.snoozed_until:
        return False
    if last_answered_on is None:
        return True
    return (today - last_answered_on).days >= schedule.cadence_days


def snooze_until(today: date, cadence_days: int) -> date:
    """The day a skipped check-in is due again."""

    if not is_valid_cadence(cadence_days):
        raise ValueError("cadence_days must be 7, 14 or 30")
    return today + timedelta(days=cadence_days)
