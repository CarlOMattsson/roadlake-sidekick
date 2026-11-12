"""Inputs and outputs of the database-side Work list: one selection spec, one key per record.

The store turns a `WorkListSpec` into a single ordered query over every Work kind, so filtering,
sorting and paging happen in PostgreSQL and no read is capped by a row limit before a filter runs.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, tzinfo
from typing import NamedTuple
from uuid import UUID

from sidekick.projects.domain import Project
from sidekick.shared.types import KeyValue
from sidekick.tasks.domain import Task
from sidekick.work.domain import Action, Domain, Process, Step

WorkRecord = Domain | Process | Project | Task | Step | Action
"""Any one record the Work list can name."""


# A Project's target date is the last day it may land on, so it is due at the end of that day in
# the owner's zone (as a Task given a bare date is); its start date is the day's first moment.
PROJECT_TARGET_TIME = time(23, 59)


def project_due_at(target_date: date, zone: tzinfo) -> datetime:
    """The instant a Project's target date falls due: 23:59 that day in the owner's zone."""

    return datetime.combine(target_date, PROJECT_TARGET_TIME, tzinfo=zone)


def project_earliest_start(start_date: date, zone: tzinfo) -> datetime:
    """The instant a Project's start date begins: 00:00 that day in the owner's zone."""

    return datetime.combine(start_date, time.min, tzinfo=zone)


@dataclass(frozen=True, slots=True)
class AgendaSpec:
    """The agenda's own selection, evaluated by the database against one instant.

    `day_start` and `day_end` are the owner's calendar day as UTC instants, so the store never
    needs the owner's time zone. `groups` keeps only those agenda groups; `today_first` puts the
    `today` group ahead of the rest (Arbetes Idag).
    """

    now: datetime
    day_start: datetime
    day_end: datetime
    include_undated: bool = False
    waiting_only: bool = False
    groups: tuple[str, ...] | None = None
    today_first: bool = False


@dataclass(frozen=True, slots=True)
class WorkListSpec:
    """Closed filter, sort and grouping vocabulary of the Work list (see `WorkQuery`)."""

    now: datetime
    q: str | None = None
    status: str | None = None
    priority: str | None = None
    due_from: datetime | None = None
    due_to: datetime | None = None
    attention_requested: bool = False
    archive: str = "active"
    kind: str = "all"
    project_id: UUID | None = None
    tags: tuple[str, ...] = ()
    tag_match: str = "any"
    actionable: str = "all"
    waiting: str = "all"
    estimate: str = "all"
    max_minutes: int | None = None
    sort: str = "updated_desc"
    group: str = "none"
    agenda: AgendaSpec | None = None
    # IANA key of the owner's zone; it decides the instants of a Project's date-only fields.
    owner_zone: str = "UTC"
    # The status board's order: Tasks the owner placed by hand come first, by their rank, ahead
    # of the requested sort (which orders the rest, and ties between equal ranks).
    board_order: bool = False


class WorkKey(NamedTuple):
    """One selected record: its kind and id, its agenda group when the spec has an agenda, and
    its `position`: the value of every `sort_keys` component, which a cursor continues after."""

    kind: str
    id: UUID
    agenda_group: str | None
    position: tuple[KeyValue, ...] = ()


@dataclass(frozen=True, slots=True)
class SortKey:
    """One component of the list's total order.

    `name` selects the column or expression in the store; `kind` is the Python type of its value
    and `nullable` whether it can be absent; `nulls_first` is where absent values sort in the
    final order, after `descending` is applied.
    """

    name: str
    kind: type
    nullable: bool
    descending: bool
    nulls_first: bool


def sort_keys(spec: WorkListSpec) -> tuple[SortKey, ...]:
    """The total order of a Work list: the group key, the sort key, then kind and id as tiebreak.

    The order is unique per record, so a cursor holding the last record's values continues the
    list exactly (keyset paging); `updated_desc` orders by the last change (`updated_at`, which
    every write moves forward) and reverses the whole order, so ties fall to the newest id.
    """

    keys: list[tuple[str, type, bool, bool]] = []  # name, kind, nullable, NULLs first ascending
    if spec.group == "kind":
        keys.append(("kind", str, False, False))
    elif spec.group == "status":
        keys.append(("status", str, True, False))
    elif spec.group == "context":
        keys.append(("parent_id", UUID, True, True))
    if spec.sort == "due_asc":
        keys.append(("due_at", datetime, True, False))
    elif spec.sort == "not_before_asc":
        keys.append(("earliest_start", datetime, True, False))
    elif spec.sort == "estimate_asc":
        keys.append(("minutes", int, True, False))
    elif spec.sort == "title_asc":
        keys.append(("title", str, False, False))
    elif spec.sort == "priority_desc":
        keys.append(("priority", int, False, False))
    else:
        keys.append(("updated_at", datetime, False, False))
    keys.append(("id", UUID, False, False))
    keys.append(("kind", str, False, False))

    descending = spec.sort == "updated_desc"
    found: list[SortKey] = []
    if spec.agenda is not None and spec.agenda.today_first:
        found.append(SortKey("today_first", int, False, False, False))
    if spec.board_order:
        # Ascending whatever the sort; an unranked Task (NULL) sorts after every ranked one.
        found.append(SortKey("board_rank", int, True, False, False))
    for name, kind, nullable, nulls_first in keys:
        found.append(SortKey(name, kind, nullable, descending, nulls_first != descending))
    return tuple(found)
