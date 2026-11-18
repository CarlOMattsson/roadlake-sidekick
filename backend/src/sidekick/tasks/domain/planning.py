"""Framework-free Task planning vocabulary: estimates, earliest start, and waiting.

Every rule here is a pure function of stored values and an explicit `now`. Nothing
in this module writes, schedules, or reacts to a passing timestamp: earliest start
and follow-up are read by derivation only.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, tzinfo
from uuid import UUID

from sidekick.shared.errors import ValidationError

MAX_ESTIMATED_MINUTES = 12_000
"""One working month. An estimate above this is a plan, not an estimate."""

END_OF_DAY_TIME = time(23, 59)
"""A bare date is stored as the last minute of its day in the owner's zone."""

ESTIMATE_PRESETS: tuple[int, ...] = (5, 15, 30, 60, 120, 240)
"""Approximate interface shortcuts. Storage is always whole minutes."""


@dataclass(frozen=True, slots=True)
class EstimateTotals:
    """A server-computed estimate summary for one explicitly bounded Task set."""

    scope: str
    task_count: int
    estimated_minutes_total: int
    overdue_minutes: int
    unestimated_count: int
    calculated_at: datetime

    def to_data(self) -> dict[str, object]:
        return {
            "scope": self.scope,
            "task_count": self.task_count,
            "estimated_minutes_total": self.estimated_minutes_total,
            "overdue_minutes": self.overdue_minutes,
            "unestimated_count": self.unestimated_count,
            "calculated_at": self.calculated_at,
        }


def validate_estimated_minutes(value: int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValidationError("estimate must be whole minutes")
    if value <= 0 or value > MAX_ESTIMATED_MINUTES:
        raise ValidationError(f"estimate must be between 1 and {MAX_ESTIMATED_MINUTES} minutes")
    return value


def is_actionable_now(earliest_start: datetime | None, now: datetime) -> bool:
    """True when nothing schedules the record for later."""

    return earliest_start is None or earliest_start <= now


def validate_waiting(
    *,
    waiting_since: datetime | None,
    follow_up_at: datetime | None,
    waiting_on_contact_id: UUID | None,
) -> None:
    """Follow-up time and waiting Contact exist only while the Task is waiting."""

    if waiting_since is None and (follow_up_at is not None or waiting_on_contact_id is not None):
        raise ValidationError("follow-up time and waiting contact require a waiting state")


def is_waiting(*, waiting_since: datetime | None, completed: bool) -> bool:
    return waiting_since is not None and not completed


def is_follow_up_due(
    *, waiting_since: datetime | None, follow_up_at: datetime | None, completed: bool, now: datetime
) -> bool:
    if not is_waiting(waiting_since=waiting_since, completed=completed):
        return False
    return follow_up_at is not None and follow_up_at <= now


def has_clock_time(due_at: datetime, zone: tzinfo) -> bool:
    """True unless `due_at` is the end of its day in `zone`, which is how a bare date is stored."""

    local = due_at.astimezone(zone)
    return (local.hour, local.minute) != (END_OF_DAY_TIME.hour, END_OF_DAY_TIME.minute)


def due_on_day(current: datetime | None, day: date, zone: tzinfo) -> datetime:
    """The due time on `day` in `zone`: `current`'s time of day if it has one, else end of day."""

    if current is None or not has_clock_time(current, zone):
        return datetime.combine(day, END_OF_DAY_TIME, tzinfo=zone)
    local = current.astimezone(zone)
    return datetime.combine(day, time(local.hour, local.minute), tzinfo=zone)
