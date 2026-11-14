"""Pure recurring-task schedules.

The schedule is deliberately small and explicit. It describes when the next
occurrence should be due; it never creates rows or performs I/O.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import Any, TypedDict

from sidekick.shared.errors import ValidationError

FREQUENCIES = frozenset({"daily", "weekly", "monthly", "yearly"})


class RecurrenceData(TypedDict):
    """A rule as `RecurrenceRule.to_data` serialises it: plain JSON values."""

    frequency: str
    interval: int
    weekdays: list[int]
    day_of_month: int | None
    until: str | None


@dataclass(frozen=True, slots=True)
class RecurrenceRule:
    frequency: str
    interval: int = 1
    weekdays: tuple[int, ...] = ()
    day_of_month: int | None = None
    until: date | None = None

    def __post_init__(self) -> None:
        if self.frequency not in FREQUENCIES:
            raise ValidationError("unsupported recurrence frequency")
        if not 1 <= self.interval <= 12:
            raise ValidationError("recurrence interval must be between 1 and 12")
        if len(set(self.weekdays)) != len(self.weekdays) or any(
            weekday < 0 or weekday > 6 for weekday in self.weekdays
        ):
            raise ValidationError("recurrence weekdays must be unique values from 0 to 6")
        if len(self.weekdays) > 7:
            raise ValidationError("recurrence may contain at most seven weekdays")
        if self.frequency != "weekly" and self.weekdays:
            raise ValidationError("weekdays are only supported for weekly recurrence")
        if self.day_of_month is not None and not 1 <= self.day_of_month <= 31:
            raise ValidationError("recurrence day of month must be between 1 and 31")
        if self.frequency != "monthly" and self.day_of_month is not None:
            raise ValidationError("day of month is only supported for monthly recurrence")

    @classmethod
    def from_data(cls, value: Mapping[str, Any] | None) -> "RecurrenceRule | None":
        if value is None:
            return None
        until = value.get("until")
        return cls(
            frequency=str(value["frequency"]),
            interval=int(value.get("interval", 1)),
            weekdays=tuple(int(item) for item in value.get("weekdays", ())),
            day_of_month=(int(value["day_of_month"]) if value.get("day_of_month") else None),
            until=(
                until if isinstance(until, date) else date.fromisoformat(until) if until else None
            ),
        )

    def to_data(self) -> RecurrenceData:
        return {
            "frequency": self.frequency,
            "interval": self.interval,
            "weekdays": list(self.weekdays),
            "day_of_month": self.day_of_month,
            "until": self.until.isoformat() if self.until else None,
        }

    def next_due_at(self, anchor: datetime, zone: tzinfo = UTC) -> datetime | None:
        """Return the next occurrence, preserving the anchor's wall-clock time in `zone`.

        Weekdays, the day of the month, `until` and the wall-clock time are all read in the
        owner's zone, so a Task completed at 00:30 Stockholm on a Monday recurs on the right
        weekday although that instant is still Sunday in UTC. The result is in UTC.
        """

        anchor = anchor.astimezone(zone)
        candidate = anchor
        if self.frequency == "daily":
            candidate = anchor + timedelta(days=self.interval)
        elif self.frequency == "weekly":
            if not self.weekdays:
                candidate = anchor + timedelta(days=7 * self.interval)
            elif self.interval > 1:
                # Stay in the anchor's week while an allowed weekday is still ahead of the
                # anchor; otherwise jump `interval` weeks and take the earliest allowed weekday.
                week_start = anchor.date() - timedelta(days=anchor.weekday())
                later = [day for day in self.weekdays if day > anchor.weekday()]
                if later:
                    candidate_date = week_start + timedelta(days=min(later))
                else:
                    candidate_date = (
                        week_start
                        + timedelta(weeks=self.interval)
                        + timedelta(days=min(self.weekdays))
                    )
                candidate = anchor.replace(
                    year=candidate_date.year,
                    month=candidate_date.month,
                    day=candidate_date.day,
                )
            else:
                for days_ahead in range(1, 7 * self.interval + 8):
                    possible = anchor + timedelta(days=days_ahead)
                    if possible.weekday() in self.weekdays:
                        candidate = possible
                        break
        elif self.frequency == "monthly":
            month_index = anchor.year * 12 + anchor.month - 1 + self.interval
            year, month_index = divmod(month_index, 12)
            month = month_index + 1
            day = self.day_of_month or anchor.day
            # Clamp days 29-31 to the last day of the target month.
            next_month = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
            last_day = (next_month - timedelta(days=1)).day
            candidate = anchor.replace(year=year, month=month, day=min(day, last_day))
        elif self.frequency == "yearly":
            year = anchor.year + self.interval
            try:
                candidate = anchor.replace(year=year)
            except ValueError:  # 29 February
                candidate = anchor.replace(year=year, day=28)
        if self.until is not None and candidate.date() > self.until:
            return None
        return candidate.astimezone(UTC)
