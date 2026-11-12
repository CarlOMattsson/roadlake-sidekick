"""What got done on one calendar day: the read behind the diary's "Gjort" section.

One owner-scoped read over three domains. A task counts when it was completed within the day
(a recurring task by its last completed cycle), a step when it was ticked off within the day, and a
shopping item when it was bought within the day and is still bought. Records in the trash and
archived tasks or steps are left out. The day runs from midnight to midnight in the owner's zone,
so a day on a daylight-saving change is 23 or 25 hours long. Each list is ordered by time, shows
at most `DONE_LIST_LIMIT` records, and `counts` always hold the real totals.

Reading another domain's records needs that domain's read scope. Without it the lists stay empty,
the same way other cross-domain parts of a read are left out; nothing is disclosed. The database
read is in `journal/persistence/day_done.py`; this module holds the shapes and the day rule
only.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, tzinfo
from uuid import UUID

DONE_LIST_LIMIT = 50


@dataclass(frozen=True, slots=True)
class DoneTask:
    id: UUID
    title: str
    completed_at: datetime
    project_title: str | None
    recurring: bool


@dataclass(frozen=True, slots=True)
class DoneStep:
    id: UUID
    title: str
    task_id: UUID
    task_title: str
    completed_at: datetime


@dataclass(frozen=True, slots=True)
class DonePurchase:
    id: UUID
    title: str
    list_id: UUID
    list_title: str
    purchased_at: datetime


@dataclass(frozen=True, slots=True)
class DoneCounts:
    tasks: int = 0
    steps: int = 0
    purchases: int = 0


@dataclass(frozen=True, slots=True)
class DayDone:
    tasks: tuple[DoneTask, ...] = ()
    steps: tuple[DoneStep, ...] = ()
    purchases: tuple[DonePurchase, ...] = ()
    counts: DoneCounts = field(default_factory=DoneCounts)
    truncated: bool = False


def day_bounds(journal_date: date, zone: tzinfo) -> tuple[datetime, datetime]:
    """Half-open `[start, end)` of the calendar day in `zone`, as zone-aware datetimes."""

    start = datetime.combine(journal_date, time.min, tzinfo=zone)
    end = datetime.combine(journal_date + timedelta(days=1), time.min, tzinfo=zone)
    return start, end


def owner_today(instant: datetime, zone: tzinfo) -> date:
    """The owner's calendar date at an aware instant; never the UTC date or the server's own."""

    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("instant must be timezone-aware")
    return instant.astimezone(zone).date()
