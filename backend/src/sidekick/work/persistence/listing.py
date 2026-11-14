"""The owner's Work list: filtered, sorted and paged in one database query.

Every Work kind (Domain, Process, Project, Task, Step, Action) contributes one narrow `SELECT` of
the columns the filters and sort orders read. The branches are `UNION ALL`ed, the agenda group is
computed over the union when the spec asks for one, and `ORDER BY ... OFFSET ... LIMIT` cuts the
page. Only that page's records are then loaded in full (`work_records_by_ids`), so nothing is
capped before a filter runs and the statement count per page does not depend on the data size.
"""

import unicodedata
from collections.abc import Callable, Mapping, Sequence
from datetime import timedelta
from typing import Any, NamedTuple
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Integer,
    Select,
    String,
    and_,
    case,
    cast,
    collate,
    false,
    func,
    literal,
    literal_column,
    null,
    or_,
    select,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement

from sidekick.projects.persistence import project_from_row
from sidekick.shared.persistence.models import (
    ActionRow,
    DomainRow,
    ProcessRow,
    ProjectRow,
    StepRow,
    TaskRow,
)
from sidekick.shared.persistence.stores.keyset import text_key
from sidekick.shared.persistence.stores.task_parents import task_parents_live
from sidekick.shared.types import KeyValue
from sidekick.tasks.persistence import task_from_row
from sidekick.work.listing import (
    PROJECT_TARGET_TIME,
    AgendaSpec,
    SortKey,
    WorkKey,
    WorkListSpec,
    WorkRecord,
    sort_keys,
)
from sidekick.work.persistence.mappers import (
    action_from_row,
    domain_from_row,
    process_from_row,
    step_from_row,
)
from sidekick.work.persistence.tags import tag_condition

# A SELECT of any number of columns: `Select[Any]` would mean exactly one column.
_AnySelect = Select[*tuple[Any, ...]]
_TIMESTAMP = DateTime(timezone=True)
_PRIORITY_RANK = {"urgent": 0, "high": 1, "normal": 2, "low": 3}


class _Cols(NamedTuple):
    """The columns every branch of the union exposes, in this order."""

    kind: str
    id: Any
    parent_id: Any
    title: Any
    status: Any
    priority: Any
    due_at: Any
    attention: Any
    updated_at: Any
    archived: Any
    earliest_start: Any
    minutes: Any
    waiting: Any
    board_rank: Any

    def labelled(self) -> list[ColumnElement[Any]]:
        names = self._fields
        return [
            cast(literal_column(f"'{self.kind}'"), String).label("kind"),
            *(getattr(self, name).label(name) for name in names[1:]),
        ]


class _Branch(NamedTuple):
    cols: _Cols
    entity: Any
    join: Callable[[_AnySelect], _AnySelect]
    where: list[ColumnElement[bool]]


# Applied in this order after NFKC and lower case, in Python and in SQL alike.
_FOLD_REPLACEMENTS = (("\xdf", "ss"), ("\u03c2", "\u03c3"), ("i\u0307", "i"))


def fold_text(text: str) -> str:
    """The search and sort key of a string: NFKC, lower case, then `_FOLD_REPLACEMENTS`.

    Exactly the operations of `_casefold` in SQL, so the same text gets the same key on both
    sides, however unusual its characters. (It is not `str.casefold()`: that expands a few
    characters, such as `ǰ`, which SQL `lower()` cannot.)
    """

    folded = unicodedata.normalize("NFKC", text).lower()
    for source, target in _FOLD_REPLACEMENTS:
        folded = folded.replace(source, target)
    return folded


def _casefold(text: Any) -> ColumnElement[str]:
    """`fold_text` in SQL: `lower(normalize(x, NFKC))`, `ß` as `ss`, final sigma as plain sigma.

    Same result as the old `str.casefold()` for ordinary text, ligatures (U+FB00 is `ff`),
    `ß`/`ẞ`, Greek sigmas and Turkish capital `İ`. Remaining differences: NFKC also folds
    compatibility forms such as `²` and fullwidth letters, which `casefold()` alone kept, and the
    few characters whose full case folding expands to several characters (`ǰ`, `ΐ`, polytonic
    Greek such as `ᾈ`) fold only to their lower case here.
    `normalize()` needs a UTF-8 database, which Sidekick requires anyway.
    """

    folded = func.lower(func.normalize(text, literal_column("NFKC")))
    for source, target in _FOLD_REPLACEMENTS:
        folded = func.replace(folded, source, target)
    return folded


def _no_join(statement: _AnySelect) -> _AnySelect:
    return statement


def _typed_null(type_: Any) -> ColumnElement[Any]:
    return cast(null(), type_)


def _loaded(archived: ColumnElement[bool], include_archived: bool) -> list[ColumnElement[bool]]:
    return [] if include_archived else [~archived]


def _domain_branch(owner_id: UUID, include_archived: bool) -> _Branch:
    archived = DomainRow.status == "archived"
    cols = _Cols(
        "domain",
        DomainRow.id,
        _typed_null(PGUUID(as_uuid=True)),
        DomainRow.name,
        DomainRow.status,
        _typed_null(String(20)),
        _typed_null(_TIMESTAMP),
        false(),
        DomainRow.updated_at,
        archived,
        _typed_null(_TIMESTAMP),
        _typed_null(Integer),
        false(),
        _typed_null(Integer),
    )
    where = [
        DomainRow.owner_id == owner_id,
        DomainRow.trashed_at.is_(None),
        *_loaded(archived, include_archived),
    ]
    return _Branch(cols, DomainRow, _no_join, where)


def _process_branch(owner_id: UUID, include_archived: bool) -> _Branch:
    archived = ProcessRow.status == "archived"
    cols = _Cols(
        "process",
        ProcessRow.id,
        ProcessRow.domain_id,
        ProcessRow.name,
        ProcessRow.status,
        _typed_null(String(20)),
        _typed_null(_TIMESTAMP),
        false(),
        ProcessRow.updated_at,
        archived,
        _typed_null(_TIMESTAMP),
        _typed_null(Integer),
        false(),
        _typed_null(Integer),
    )
    where = [
        ProcessRow.owner_id == owner_id,
        ProcessRow.trashed_at.is_(None),
        *_loaded(archived, include_archived),
    ]
    return _Branch(cols, ProcessRow, _no_join, where)


def _owner_instant(day: Any, zone: str, offset: timedelta) -> ColumnElement[Any]:
    """A DATE plus `offset` as a wall-clock time in the owner's zone, as one instant.

    PostgreSQL's `timezone(zone, timestamp)` reads the timestamp in `zone`, whatever the session
    time zone; it mirrors `project_due_at` and `project_earliest_start` in `work.listing`.
    """

    return func.timezone(zone, cast(day, DateTime) + offset, type_=_TIMESTAMP)


def _project_branch(owner_id: UUID, include_archived: bool, zone: str) -> _Branch:
    archived = ProjectRow.archived_at.is_not(None)
    cols = _Cols(
        "project",
        ProjectRow.id,
        ProjectRow.domain_id,
        ProjectRow.title,
        ProjectRow.status,
        _typed_null(String(20)),
        _owner_instant(
            ProjectRow.target_date,
            zone,
            timedelta(hours=PROJECT_TARGET_TIME.hour, minutes=PROJECT_TARGET_TIME.minute),
        ),
        false(),
        ProjectRow.updated_at,
        archived,
        _owner_instant(ProjectRow.start_date, zone, timedelta()),
        _typed_null(Integer),
        false(),
        _typed_null(Integer),
    )
    where = [
        ProjectRow.owner_id == owner_id,
        ProjectRow.trashed_at.is_(None),
        *_loaded(archived, include_archived),
    ]
    return _Branch(cols, ProjectRow, _no_join, where)


def _task_branch(owner_id: UUID, include_archived: bool, project_id: UUID | None) -> _Branch:
    archived = TaskRow.archived_at.is_not(None)
    cols = _Cols(
        "task",
        TaskRow.id,
        func.coalesce(TaskRow.project_id, TaskRow.process_id, TaskRow.domain_id),
        TaskRow.title,
        TaskRow.status,
        TaskRow.priority,
        TaskRow.due_at,
        TaskRow.attention_requested,
        TaskRow.updated_at,
        archived,
        TaskRow.not_before,
        TaskRow.estimated_minutes,
        and_(TaskRow.waiting_since.is_not(None), TaskRow.status != "completed"),
        # The board ranks live, unarchived Tasks only (an archived Task's rank is not shown).
        case((archived, None), else_=TaskRow.board_rank),
    )
    where = [
        TaskRow.owner_id == owner_id,
        TaskRow.trashed_at.is_(None),
        task_parents_live(),
        *_loaded(archived, include_archived),
    ]
    if project_id is not None:
        where.append(TaskRow.project_id == project_id)
    return _Branch(cols, TaskRow, _no_join, where)


def _step_branch(owner_id: UUID, include_archived: bool) -> _Branch:
    archived = StepRow.archived_at.is_not(None)
    cols = _Cols(
        "step",
        StepRow.id,
        StepRow.task_id,
        StepRow.title,
        StepRow.status,
        _typed_null(String(20)),
        StepRow.due_at,
        StepRow.attention_requested,
        StepRow.updated_at,
        archived,
        _typed_null(_TIMESTAMP),
        _typed_null(Integer),
        false(),
        _typed_null(Integer),
    )
    where = [
        StepRow.owner_id == owner_id,
        StepRow.trashed_at.is_(None),
        TaskRow.trashed_at.is_(None),
        task_parents_live(),
        *_loaded(archived, include_archived),
        *_loaded(TaskRow.archived_at.is_not(None), include_archived),
    ]

    def join(statement: _AnySelect) -> _AnySelect:
        return statement.join(
            TaskRow, and_(TaskRow.id == StepRow.task_id, TaskRow.owner_id == StepRow.owner_id)
        )

    return _Branch(cols, StepRow, join, where)


def _action_branch(owner_id: UUID, include_archived: bool) -> _Branch:
    archived = ActionRow.archived_at.is_not(None)
    cols = _Cols(
        "action",
        ActionRow.id,
        ActionRow.step_id,
        ActionRow.title,
        ActionRow.status,
        _typed_null(String(20)),
        ActionRow.due_at,
        ActionRow.attention_requested,
        ActionRow.updated_at,
        archived,
        _typed_null(_TIMESTAMP),
        _typed_null(Integer),
        false(),
        _typed_null(Integer),
    )
    where = [
        ActionRow.owner_id == owner_id,
        ActionRow.trashed_at.is_(None),
        StepRow.trashed_at.is_(None),
        TaskRow.trashed_at.is_(None),
        task_parents_live(),
        *_loaded(archived, include_archived),
        *_loaded(StepRow.archived_at.is_not(None), include_archived),
        *_loaded(TaskRow.archived_at.is_not(None), include_archived),
    ]

    def join(statement: _AnySelect) -> _AnySelect:
        return statement.join(
            StepRow, and_(StepRow.id == ActionRow.step_id, StepRow.owner_id == ActionRow.owner_id)
        ).join(TaskRow, and_(TaskRow.id == StepRow.task_id, TaskRow.owner_id == StepRow.owner_id))

    return _Branch(cols, ActionRow, join, where)


def _predicates(owner_id: UUID, cols: _Cols, spec: WorkListSpec) -> list[ColumnElement[bool]]:
    """The list's filters over one branch's columns; a missing value never satisfies a filter."""

    found: list[ColumnElement[bool]] = []
    if spec.q:
        found.append(_casefold(cols.title).contains(fold_text(spec.q), autoescape=True))
    if spec.status:
        found.append(cols.status == spec.status)
    if spec.priority:
        found.append(cols.priority == spec.priority)
    if spec.due_from:
        found.append(cols.due_at >= spec.due_from)
    if spec.due_to:
        found.append(cols.due_at <= spec.due_to)
    if spec.attention_requested:
        found.append(cols.attention.is_(True))
    if spec.archive != "all":
        found.append(cols.archived.is_(spec.archive == "archived"))
    if spec.tags:
        found.append(tag_condition(cols.kind, cols.id, owner_id, spec.tags, spec.tag_match))
    not_yet = and_(cols.earliest_start.is_not(None), cols.earliest_start > spec.now)
    if spec.actionable == "now":
        found.append(~not_yet)
    elif spec.actionable == "later":
        found.append(not_yet)
    if spec.waiting != "all":
        found.append(cols.waiting.is_(spec.waiting == "waiting"))
    if spec.estimate == "estimated":
        found.append(cols.minutes.is_not(None))
    elif spec.estimate == "unestimated":
        found.append(cols.minutes.is_(None))
    if spec.max_minutes is not None:
        found.append(cols.minutes <= spec.max_minutes)
    return found


def _agenda_group(source: Any, agenda: AgendaSpec) -> ColumnElement[str]:
    not_actionable = and_(
        source.c.earliest_start.is_not(None), source.c.earliest_start > agenda.now
    )
    return case(
        (not_actionable, "scheduled_later"),
        (source.c.due_at.is_(None), "upcoming"),
        (source.c.due_at < agenda.now, "overdue"),
        (and_(source.c.due_at >= agenda.day_start, source.c.due_at < agenda.day_end), "today"),
        else_="upcoming",
    )


def _agenda_filter(source: Any, agenda: AgendaSpec) -> ColumnElement[bool]:
    """Open records that are scheduled later, dated, or (as asked) undated, waiting or Tasks."""

    not_actionable = and_(
        source.c.earliest_start.is_not(None), source.c.earliest_start > agenda.now
    )
    undated = or_(
        source.c.waiting if agenda.waiting_only else false(),
        source.c.kind == "task" if agenda.include_undated else false(),
    )
    return and_(
        source.c.status != "completed",
        or_(not_actionable, source.c.due_at.is_not(None), undated),
    )


def _expression(source: Any, name: str) -> Any:
    """The SQL expression behind one `SortKey` of `work.listing.sort_keys`. Text compares by
    code point (`COLLATE "C"`)."""

    if name == "today_first":
        return case((source.c.agenda_group == "today", 0), else_=1)
    if name in ("kind", "status"):
        return collate(getattr(source.c, name), "C")
    if name == "title":
        return collate(text_key(_casefold(source.c.title)), "C")
    if name == "priority":
        return case(
            *((source.c.priority == label, rank) for label, rank in _PRIORITY_RANK.items()),
            else_=4,
        )
    return getattr(source.c, name)


def _ordering(source: Any, keys: Sequence[SortKey]) -> list[Any]:
    """`sort_keys` as SQL: the board rank, the group key, the sort key, then the id; the group,
    sort and id keys are reversed as a whole for `updated_desc`, which orders by `updated_at`."""

    ordering: list[Any] = []
    for key in keys:
        expression = _expression(source, key.name)
        ordered = expression.desc() if key.descending else expression.asc()
        ordering.append(ordered.nulls_first() if key.nulls_first else ordered.nulls_last())
    return ordering


def _after(source: Any, keys: Sequence[SortKey], position: tuple[KeyValue, ...]) -> Any:
    """The records that sort strictly after `position`, comparing key by key (NULL-aware)."""

    alternatives: list[ColumnElement[bool]] = []
    equal_so_far: list[ColumnElement[bool]] = []
    for key, value in zip(keys, position, strict=True):
        expression = _expression(source, key.name)
        if value is None:
            # Only a NULL that sorts first leaves anything after it: every non-NULL value.
            later = expression.is_not(None) if key.nulls_first else false()
            same = expression.is_(None)
        else:
            bound = literal(value, expression.type)
            later = expression < bound if key.descending else expression > bound
            if not key.nulls_first:
                later = or_(later, expression.is_(None))
            same = expression == bound
        alternatives.append(and_(*equal_so_far, later))
        equal_so_far.append(same)
    return or_(*alternatives)


def _wanted_kinds(spec: WorkListSpec) -> tuple[str, ...]:
    kinds = ("domain", "process", "project", "task", "step", "action")
    # A Project filter lists that Project's Tasks only; no other kind can match it.
    if spec.project_id is not None:
        kinds = ("task",)
    if spec.kind != "all":
        kinds = tuple(kind for kind in kinds if kind == spec.kind)
    return kinds


def _selection(owner_id: UUID, spec: WorkListSpec, kinds: tuple[str, ...]) -> Any:
    """The union of the given kinds, with `agenda_group` added and the agenda filter applied."""

    include_archived = spec.archive != "active"
    branches = {
        "domain": lambda: _domain_branch(owner_id, include_archived),
        "process": lambda: _process_branch(owner_id, include_archived),
        "project": lambda: _project_branch(owner_id, include_archived, spec.owner_zone),
        "task": lambda: _task_branch(owner_id, include_archived, spec.project_id),
        "step": lambda: _step_branch(owner_id, include_archived),
        "action": lambda: _action_branch(owner_id, include_archived),
    }
    selects: list[_AnySelect] = []
    for kind in kinds:
        branch = branches[kind]()
        statement = branch.join(select(*branch.cols.labelled()).select_from(branch.entity))
        selects.append(statement.where(*branch.where, *_predicates(owner_id, branch.cols, spec)))
    union = selects[0] if len(selects) == 1 else selects[0].union_all(*selects[1:])
    merged = union.subquery("work")
    if spec.agenda is None:
        return select(*merged.c, cast(null(), String).label("agenda_group")).subquery("selected")
    return (
        select(*merged.c, _agenda_group(merged, spec.agenda).label("agenda_group"))
        .where(_agenda_filter(merged, spec.agenda))
        .subquery("selected")
    )


class WorkListStore:
    """Filtered, sorted and paged Work list reads.

    The operations are static and owner-filtered; `SqlWorkStore` adds the transaction boundary.
    """

    @staticmethod
    def work_list_keys(
        session: Session,
        owner_id: UUID,
        spec: WorkListSpec,
        *,
        after: tuple[KeyValue, ...] | None,
        limit: int,
    ) -> list[WorkKey]:
        """One page of the owner's selected records, in list order, as kind and id.

        `after` is the `position` of the last record already read (keyset paging): the page
        starts strictly after it, so records added or removed meanwhile never move the page.
        """

        kinds = _wanted_kinds(spec)
        if not kinds:
            return []
        selected = _selection(owner_id, spec, kinds)
        order = sort_keys(spec)
        statement = select(
            selected.c.kind,
            selected.c.id,
            selected.c.agenda_group,
            *(
                _expression(selected, key.name).label(f"sort_{index}")
                for index, key in enumerate(order)
            ),
        )
        if spec.agenda is not None and spec.agenda.groups is not None:
            statement = statement.where(selected.c.agenda_group.in_(spec.agenda.groups))
        if after is not None:
            statement = statement.where(_after(selected, order, after))
        rows = session.execute(statement.order_by(*_ordering(selected, order)).limit(limit))
        return [
            WorkKey(
                row.kind,
                row.id,
                row.agenda_group,
                tuple(row[3 + index] for index in range(len(order))),
            )
            for row in rows
        ]

    @staticmethod
    def work_agenda_group_counts(
        session: Session, owner_id: UUID, spec: WorkListSpec
    ) -> dict[str, int]:
        """How many selected records fall in each agenda group; the spec must carry an agenda."""

        if spec.agenda is None:
            raise ValueError("an agenda spec is required")
        kinds = _wanted_kinds(spec)
        if not kinds:
            return {}
        selected = _selection(owner_id, spec, kinds)
        statement = select(selected.c.agenda_group, func.count()).group_by(selected.c.agenda_group)
        if spec.agenda.groups is not None:
            statement = statement.where(selected.c.agenda_group.in_(spec.agenda.groups))
        return {str(group): int(count) for group, count in session.execute(statement)}

    @staticmethod
    def work_records_by_ids(
        session: Session, owner_id: UUID, ids_by_kind: Mapping[str, Sequence[UUID]]
    ) -> dict[str, dict[UUID, WorkRecord]]:
        """The named live records of the owner, one query per kind that has ids."""

        sources: dict[str, tuple[Any, Callable[[Any], WorkRecord]]] = {
            "domain": (DomainRow, domain_from_row),
            "process": (ProcessRow, process_from_row),
            "project": (ProjectRow, project_from_row),
            "task": (TaskRow, task_from_row),
            "step": (StepRow, step_from_row),
            "action": (ActionRow, action_from_row),
        }
        records: dict[str, dict[UUID, WorkRecord]] = {}
        for kind, ids in ids_by_kind.items():
            if not ids:
                continue
            row_type, build = sources[kind]
            rows = session.scalars(
                select(row_type).where(
                    row_type.owner_id == owner_id,
                    row_type.id.in_(list(ids)),
                    row_type.trashed_at.is_(None),
                )
            )
            records[kind] = {row.id: build(row) for row in rows}
        return records
