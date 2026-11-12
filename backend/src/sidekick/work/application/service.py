"""Owner-scoped Work use cases shared by the MCP adapter: Domains, Processes, the hierarchy, work
lists, agenda, Today and board reads, and the Domain and Process writes."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Any, Protocol, TypeVar, cast
from uuid import UUID

from sidekick.projects.domain import Project, ProjectStatus
from sidekick.shared.errors import InvalidInputError, ValidationError
from sidekick.shared.replay import id_replay_record
from sidekick.shared.types import (
    TIMED_KEY,
    UNSET,
    Actor,
    AuditingStore,
    Clock,
    CursorCodec,
    IdempotentStore,
    KeyValue,
    Page,
    TransactionalStore,
    TxSession,
    UnsetType,
    new_uuid7,
)
from sidekick.tasks.domain import Task, TaskStatus, derive_domain_id
from sidekick.work.domain import Action, Domain, DomainStatus, Process, ProcessStatus, Step
from sidekick.work.domain.planning import (
    Cadence,
    EstimateTotals,
    WorkTag,
    is_actionable_now,
    normalize_tag_filter,
    validate_estimated_minutes,
)
from sidekick.work.domain.tag_assignment import apply_record_tags
from sidekick.work.listing import (
    AgendaSpec,
    WorkKey,
    WorkListSpec,
    WorkRecord,
    project_due_at,
    project_earliest_start,
    sort_keys,
)

T = TypeVar("T")

HIERARCHY_KINDS = ("domain", "process", "project")
"""The order of `get_work_hierarchy` nodes; the cursor carries the index of the last kind served."""

HIERARCHY_CURSOR_KEY = "hierarchy:v1"


class ContextStore(TransactionalStore, IdempotentStore, AuditingStore, Protocol):
    def list_domains(
        self,
        session: TxSession,
        owner_id: UUID,
        limit: int,
        after: tuple[KeyValue, ...] | None = None,
        include_archived: bool = False,
    ) -> list[Domain]: ...
    def list_projects(
        self,
        session: TxSession,
        owner_id: UUID,
        limit: int,
        status: ProjectStatus | None = None,
        after: tuple[KeyValue, ...] | None = None,
        include_archived: bool = False,
    ) -> list[Project]: ...
    def list_tasks(
        self,
        session: TxSession,
        owner_id: UUID,
        limit: int,
        project_id: UUID | None = None,
        status: TaskStatus | None = None,
        after: tuple[KeyValue, ...] | None = None,
        include_archived: bool = False,
    ) -> list[Task]: ...
    def estimate_totals(
        self,
        session: TxSession,
        owner_id: UUID,
        *,
        now: datetime,
        project_id: UUID | None = None,
        agenda_start: datetime | None = None,
        agenda_end: datetime | None = None,
        task_ids: tuple[UUID, ...] = (),
        actionable_now: bool = False,
        focus_only: bool = False,
    ) -> dict[str, int]: ...
    def project_task_counts(
        self, session: TxSession, owner_id: UUID, *, project_id: UUID, now: datetime
    ) -> dict[str, int]: ...
    def task_step_counts(
        self, session: TxSession, owner_id: UUID, *, task_id: UUID
    ) -> dict[str, int]: ...
    def list_steps(
        self,
        session: TxSession,
        owner_id: UUID,
        task_id: UUID,
        limit: int,
        offset: int = 0,
        include_archived: bool = False,
    ) -> list[Step]: ...
    def list_actions(
        self,
        session: TxSession,
        owner_id: UUID,
        step_id: UUID,
        limit: int,
        offset: int = 0,
        include_archived: bool = False,
    ) -> list[Action]: ...
    def board_manual_statuses(
        self,
        session: TxSession,
        owner_id: UUID,
        status: str | None = None,
        project_id: UUID | None = None,
    ) -> tuple[str, ...]: ...
    def project_titles(
        self, session: TxSession, owner_id: UUID, project_ids: tuple[UUID, ...]
    ) -> dict[UUID, str]: ...
    def domain_accents(
        self, session: TxSession, owner_id: UUID, domain_ids: tuple[UUID, ...]
    ) -> dict[UUID, str | None]: ...
    def process_domain_ids(
        self, session: TxSession, owner_id: UUID, process_ids: tuple[UUID, ...]
    ) -> dict[UUID, UUID]: ...
    def project_domain_ids(
        self, session: TxSession, owner_id: UUID, project_ids: tuple[UUID, ...]
    ) -> dict[UUID, UUID]: ...
    def get_domain(self, session: TxSession, owner_id: UUID, domain_id: UUID) -> Domain: ...
    def save_domain(
        self, session: TxSession, domain: Domain, expected_version: int | None = None
    ) -> None: ...
    def record_tag_slugs(
        self,
        session: TxSession,
        owner_id: UUID,
        limit: int = 5000,
        record_ids: Mapping[str, Sequence[UUID]] | None = None,
    ) -> dict[tuple[str, UUID], tuple[str, ...]]: ...
    def work_list_keys(
        self,
        session: TxSession,
        owner_id: UUID,
        spec: WorkListSpec,
        *,
        after: tuple[KeyValue, ...] | None,
        limit: int,
    ) -> list[WorkKey]: ...
    def work_agenda_group_counts(
        self, session: TxSession, owner_id: UUID, spec: WorkListSpec
    ) -> dict[str, int]: ...
    def work_records_by_ids(
        self, session: TxSession, owner_id: UUID, ids_by_kind: Mapping[str, Sequence[UUID]]
    ) -> dict[str, dict[UUID, WorkRecord]]: ...
    def list_record_tags(
        self, session: TxSession, owner_id: UUID, kind: str, record_id: UUID
    ) -> list[WorkTag]: ...
    def replace_record_tags(
        self,
        session: TxSession,
        owner_id: UUID,
        kind: str,
        record_id: UUID,
        tag_ids: tuple[UUID, ...],
    ) -> None: ...
    def find_work_tag_by_slug(
        self, session: TxSession, owner_id: UUID, slug: str
    ) -> WorkTag | None: ...
    def save_work_tag(
        self, session: TxSession, tag: WorkTag, expected_version: int | None = None
    ) -> None: ...
    def list_processes(
        self,
        session: TxSession,
        owner_id: UUID,
        limit: int,
        domain_id: UUID | None = None,
        after: tuple[KeyValue, ...] | None = None,
        include_archived: bool = False,
    ) -> list[Process]: ...
    def get_process(self, session: TxSession, owner_id: UUID, process_id: UUID) -> Process: ...
    def save_process(
        self, session: TxSession, process: Process, expected_version: int | None = None
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class UpdateContextCommand:
    """Mutable Domain/Process fields. `tags` is the record's intended tag set."""

    name: str | UnsetType = UNSET
    description: str | None | UnsetType = UNSET
    status: DomainStatus | ProcessStatus | UnsetType = UNSET
    domain_id: UUID | UnsetType = UNSET
    review_cadence: Cadence | None | UnsetType = UNSET
    last_reviewed_at: datetime | None | UnsetType = UNSET
    cadence: Cadence | None | UnsetType = UNSET
    accent: str | None | UnsetType = UNSET
    tags: tuple[str, ...] | UnsetType = UNSET

    def changes(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "name": self.name,
                "description": self.description,
                "status": self.status,
                "domain_id": self.domain_id,
                "review_cadence": self.review_cadence,
                "last_reviewed_at": self.last_reviewed_at,
                "cadence": self.cadence,
                "accent": self.accent,
                "tags": self.tags,
            }.items()
            if value is not UNSET
        }

    def entity_changes(self, kind: str) -> dict[str, Any]:
        """Only the fields that exist for this kind; tags are applied separately."""

        allowed = {
            "domain": {
                "name",
                "description",
                "status",
                "review_cadence",
                "last_reviewed_at",
                "accent",
            },
            "process": {"name", "description", "status", "domain_id", "cadence"},
        }[kind]
        changes = self.changes()
        unsupported = set(changes) - allowed - {"tags"}
        if unsupported:
            raise ValidationError(f"unsupported {kind} planning field")
        return {key: value for key, value in changes.items() if key in allowed}


@dataclass(frozen=True, slots=True)
class WorkQuery:
    """Closed, bounded projection inputs shared by Work read models."""

    q: str | None = None
    status: str | None = None
    priority: str | None = None
    due_from: datetime | None = None
    due_to: datetime | None = None
    attention: str = "all"
    archive: str = "active"
    kind: str = "all"
    sort: str = "updated_desc"
    group: str = "none"
    limit: int = 100
    cursor: str | None = None
    tags: tuple[str, ...] = ()
    """Bounded, deduplicated tag slugs. Empty means no tag filter."""
    tag_match: str = "any"
    actionable: str = "all"
    waiting: str = "all"
    estimate: str = "all"
    project_id: UUID | None = None
    """Only Tasks of this Project; Projects and other kinds never match. None means no filter."""
    max_minutes: int | None = None
    """Only records estimated at this many minutes or fewer; unestimated records never match."""
    include_undated: bool = False
    """Agenda only: also list open, actionable Tasks without a due date (grouped as upcoming)."""

    def validate(self) -> "WorkQuery":
        if not 1 <= self.limit <= 100:
            raise ValidationError("Work page size must be between 1 and 100")
        if self.attention not in {"all", "requested"}:
            raise ValidationError("invalid Work attention filter")
        if self.archive not in {"active", "archived", "all"}:
            raise ValidationError("invalid Work archive filter")
        if self.kind not in {"all", "domain", "process", "project", "task", "step", "action"}:
            raise ValidationError("invalid Work kind filter")
        if self.sort not in {
            "updated_desc",
            "due_asc",
            "title_asc",
            "priority_desc",
            "not_before_asc",
            "estimate_asc",
        }:
            raise ValidationError("invalid Work sort")
        if self.group not in {"none", "kind", "status", "context"}:
            raise ValidationError("invalid Work grouping")
        if self.q is not None and len(self.q) > 200:
            raise ValidationError("Work text query is too long")
        if self.actionable not in {"all", "now", "later"}:
            raise ValidationError("invalid Work actionable filter")
        if self.waiting not in {"all", "waiting", "not_waiting"}:
            raise ValidationError("invalid Work waiting filter")
        if self.estimate not in {"all", "estimated", "unestimated"}:
            raise ValidationError("invalid Work estimate filter")
        if self.max_minutes is not None:
            validate_estimated_minutes(self.max_minutes)
        normalize_tag_filter(list(self.tags), self.tag_match)
        return self

    def normalized_tags(self) -> tuple[tuple[str, ...], str]:
        return normalize_tag_filter(list(self.tags), self.tag_match)

    def key(self) -> str:
        tags, tag_match = self.normalized_tags()
        return json.dumps(
            {
                "q": self.q,
                "status": self.status,
                "priority": self.priority,
                "due_from": self.due_from.isoformat() if self.due_from else None,
                "due_to": self.due_to.isoformat() if self.due_to else None,
                "attention": self.attention,
                "archive": self.archive,
                "kind": self.kind,
                "sort": self.sort,
                "group": self.group,
                "limit": self.limit,
                "tags": list(tags),
                "tag_match": tag_match,
                "actionable": self.actionable,
                "waiting": self.waiting,
                "estimate": self.estimate,
                "project_id": str(self.project_id) if self.project_id else None,
                "max_minutes": self.max_minutes,
                "include_undated": self.include_undated,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


TODAY_GROUPS = frozenset({"overdue", "today"})


@dataclass(frozen=True, slots=True)
class WorkToday:
    """Arbetes Idag: one page of the overdue and today agenda groups, and the whole selection's
    counts. `day` is the owner's calendar day at `calculated_at`."""

    items: list[dict[str, Any]]
    next_cursor: str | None
    total: int
    overdue_total: int
    today_total: int
    day: date
    calculated_at: datetime


ESTIMATE_TOTAL_SCOPES = frozenset(
    {"agenda_day", "project_open_tasks", "actionable_now", "selection"}
)


def owner_day_bounds(instant: datetime, zone: tzinfo) -> tuple[datetime, datetime]:
    """The owner's calendar day around an aware instant, as UTC instants: `[start, end)`."""

    day = instant.astimezone(zone).date()
    start = datetime.combine(day, time.min, tzinfo=zone).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone).astimezone(UTC)
    return start, end


class ContextService:
    def __init__(
        self,
        store: ContextStore,
        clock: Clock,
        cursor_codec: CursorCodec,
        *,
        owner_timezone: tzinfo,
    ) -> None:
        self.store = store
        self.clock = clock
        self.cursor_codec = cursor_codec
        # The owner's zone (SIDEKICK_OWNER_TIMEZONE): what "today" and agenda days mean.
        self.owner_timezone = owner_timezone

    def _replayed_domain(self, session: TxSession, actor: Actor, record: dict[str, Any]) -> Domain:
        """The Domain a (possibly replayed) write refers to, re-read by id.

        The idempotency record keeps only the id, so a retry returns the Domain as it is now.
        """

        return self.store.get_domain(session, actor.user_id, UUID(record["id"]))

    def _replayed_process(
        self, session: TxSession, actor: Actor, record: dict[str, Any]
    ) -> Process:
        """The Process a (possibly replayed) write refers to, re-read by id."""

        return self.store.get_process(session, actor.user_id, UUID(record["id"]))

    def list_domains(
        self, actor: Actor, *, limit: int = 25, cursor: str | None = None
    ) -> Page[Domain]:
        actor.require("projects:read")
        if not 1 <= limit <= 100:
            raise InvalidInputError("limit must be between 1 and 100")
        key = "domains:v1"
        after = self.cursor_codec.decode_keyset(actor.user_id, cursor, key, kinds=TIMED_KEY)
        rows = self.store.transaction(
            lambda s: self.store.list_domains(s, actor.user_id, limit + 1, after)
        )
        return Page(
            rows[:limit],
            self.cursor_codec.encode_keyset(
                actor.user_id, (rows[limit - 1].updated_at, rows[limit - 1].id), key
            )
            if len(rows) > limit
            else None,
        )

    def list_processes(
        self,
        actor: Actor,
        *,
        domain_id: UUID | None = None,
        limit: int = 25,
        cursor: str | None = None,
    ) -> Page[Process]:
        actor.require("projects:read")
        if not 1 <= limit <= 100:
            raise InvalidInputError("limit must be between 1 and 100")
        key = f"processes:v1:domain={domain_id or '*'}"
        after = self.cursor_codec.decode_keyset(actor.user_id, cursor, key, kinds=TIMED_KEY)
        rows = self.store.transaction(
            lambda s: self.store.list_processes(s, actor.user_id, limit + 1, domain_id, after)
        )
        return Page(
            rows[:limit],
            self.cursor_codec.encode_keyset(
                actor.user_id, (rows[limit - 1].updated_at, rows[limit - 1].id), key
            )
            if len(rows) > limit
            else None,
        )

    def hierarchy(self, actor: Actor, *, limit: int = 100) -> list[dict[str, Any]]:
        nodes, _ = self.hierarchy_page(actor, limit=limit)
        return nodes

    def hierarchy_page(
        self, actor: Actor, *, limit: int = 100, cursor: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Return one page of nodes and the cursor of the next page, or None after the last.

        Nodes are ordered Domains, then Processes, then Projects, each newest change first.
        The cursor is the keyset position (kind rank, updated_at, id) of the last node served,
        so the next page continues strictly after it, also across a kind boundary, and no node
        is served twice while the data changes. Each kind is read with only the rows still
        needed plus one, so an overflow is detectable without a count query.
        """
        actor.require("projects:read")
        if not 1 <= limit <= 100:
            raise InvalidInputError("limit must be between 1 and 100")
        after = self.cursor_codec.decode_keyset(
            actor.user_id, cursor, HIERARCHY_CURSOR_KEY, kinds=(int, datetime, UUID)
        )
        if after is not None and not 0 <= cast("int", after[0]) < len(HIERARCHY_KINDS):
            raise InvalidInputError("invalid pagination cursor")

        def query(session: TxSession) -> list[tuple[int, datetime, UUID, dict[str, Any]]]:
            entries: list[tuple[int, datetime, UUID, dict[str, Any]]] = []
            for rank, kind in enumerate(HIERARCHY_KINDS):
                room = limit + 1 - len(entries)
                if room <= 0 or (after is not None and rank < cast("int", after[0])):
                    continue
                position = after[1:] if after is not None and rank == after[0] else None
                if kind == "domain":
                    rows = self.store.list_domains(session, actor.user_id, room, position)
                    entries.extend(
                        (
                            rank,
                            item.updated_at,
                            item.id,
                            {
                                "kind": kind,
                                "id": item.id,
                                "parent_id": None,
                                "title": item.name,
                                "status": item.status.value,
                                "version": item.version,
                                "accent": item.accent,
                            },
                        )
                        for item in rows
                    )
                elif kind == "process":
                    process_rows = self.store.list_processes(
                        session, actor.user_id, room, None, position
                    )
                    entries.extend(
                        (
                            rank,
                            item.updated_at,
                            item.id,
                            process_hierarchy_node(item),
                        )
                        for item in process_rows
                    )
                else:
                    project_rows = self.store.list_projects(
                        session, actor.user_id, room, None, position
                    )
                    entries.extend(
                        (
                            rank,
                            item.updated_at,
                            item.id,
                            {
                                "kind": kind,
                                "id": item.id,
                                "parent_id": item.domain_id,
                                "title": item.title,
                                "status": item.status.value,
                                "version": item.version,
                            },
                        )
                        for item in project_rows
                    )
            return entries

        entries = self.store.transaction(query)
        page = entries[:limit]
        next_cursor = (
            self.cursor_codec.encode_keyset(
                actor.user_id, (page[-1][0], page[-1][1], page[-1][2]), HIERARCHY_CURSOR_KEY
            )
            if len(entries) > limit
            else None
        )
        return [entry[3] for entry in page], next_cursor

    def estimate_totals(
        self,
        actor: Actor,
        *,
        scope: str,
        agenda_day: date | None = None,
        project_id: UUID | None = None,
        task_ids: tuple[UUID, ...] = (),
    ) -> EstimateTotals:
        """Aggregate one real Task set, never the current page of a projection.

        The four scopes deliberately have no generic filter expression. They are the
        product boundaries that can be explained to an owner and checked server-side.
        Agenda dates are days in the owner's zone (SIDEKICK_OWNER_TIMEZONE), so a day
        starts at local midnight and a DST day can be 23 or 25 hours long.
        """

        actor.require("tasks:read")
        if scope not in ESTIMATE_TOTAL_SCOPES:
            raise ValidationError("invalid estimate total scope")
        if scope == "agenda_day" and agenda_day is None:
            raise ValidationError("agenda day is required")
        if scope != "agenda_day" and agenda_day is not None:
            raise ValidationError("agenda day is only valid for the agenda scope")
        if scope == "project_open_tasks" and project_id is None:
            raise ValidationError("project is required")
        if scope != "project_open_tasks" and project_id is not None:
            raise ValidationError("project is only valid for the project scope")
        if scope == "selection" and not 1 <= len(task_ids) <= 100:
            raise ValidationError("selection must contain between 1 and 100 Tasks")
        if scope != "selection" and task_ids:
            raise ValidationError("Task selection is only valid for the selection scope")

        now = self.clock.now()
        agenda_start = None
        agenda_end = None
        if agenda_day is not None:
            agenda_start = datetime.combine(
                agenda_day, time.min, tzinfo=self.owner_timezone
            ).astimezone(UTC)
            agenda_end = datetime.combine(
                agenda_day + timedelta(days=1), time.min, tzinfo=self.owner_timezone
            ).astimezone(UTC)

        data = self.store.transaction(
            lambda session: self.store.estimate_totals(
                session,
                actor.user_id,
                now=now,
                project_id=project_id,
                agenda_start=agenda_start,
                agenda_end=agenda_end,
                task_ids=task_ids,
                actionable_now=scope == "actionable_now",
                focus_only=scope == "actionable_now",
            )
        )
        return EstimateTotals(scope=scope, calculated_at=now, **data)

    def project_task_counts(self, actor: Actor, project_id: UUID) -> dict[str, int]:
        """Done, total and overdue Tasks of one owned Project, counted in one read.

        Keys: tasks_done, tasks_total, tasks_overdue (see `ContextStore.project_task_counts`).
        """

        actor.require("tasks:read")
        now = self.clock.now()
        return self.store.transaction(
            lambda s: self.store.project_task_counts(
                s, actor.user_id, project_id=project_id, now=now
            )
        )

    def task_step_counts(self, actor: Actor, task_id: UUID) -> dict[str, int]:
        """Done and total Steps of one owned Task, counted in one read.

        Keys: steps_done, steps_total (see `ContextStore.task_step_counts`).
        """

        actor.require("tasks:read")
        return self.store.transaction(
            lambda s: self.store.task_step_counts(s, actor.user_id, task_id=task_id)
        )

    def work_agenda_page(self, actor: Actor, query: WorkQuery) -> Page[dict[str, Any]]:
        """Group by deadline, except records that are not yet actionable.

        A record with a future earliest start is grouped by that earliest start
        instead of being presented as due or overdue. A completed record is never
        overdue, due or upcoming, so the agenda leaves it out.

        With `include_undated`, an open, actionable Task without a due date is listed too,
        grouped as "upcoming" for the same reason (Tasks only; Domains, Processes and
        Projects carry no due date and would flood the list).

        A waiting record without a due date is left out, except when the query asks
        for `waiting="waiting"`. Then it is grouped as "upcoming": the agenda's
        group vocabulary is closed (see contracts/), and "upcoming" is the nearest
        existing group for a record that is neither overdue nor due today. Without
        the waiting filter, a record without a due date stays out as before.
        """

        now = self.clock.now()
        return self._work_page(
            actor,
            query,
            now=now,
            # Own cursor prefix: the agenda's offsets count its filtered list, not the Work list's.
            key_prefix="agenda:v1:",
            agenda=self._agenda_spec(query, now),
        )

    def work_today_page(self, actor: Actor, *, limit: int, cursor: str | None = None) -> WorkToday:
        """Arbetes Idag: exactly the agenda's overdue and today groups, open Tasks only.

        The selection is `work_agenda_page`'s own (`_agenda_spec`), restricted to the two
        groups, so a Task with a future earliest start (scheduled later), a completed Task and a
        Task due on a later day never count. The page is cut from the whole selected list,
        today's Tasks first and the overdue ones after them (the order the app's Idag reads),
        each group oldest due first as the agenda lists it. The totals count that whole list,
        never the page. "Today" is the owner's calendar day (SIDEKICK_OWNER_TIMEZONE, D-063), not
        the caller's and not UTC.
        """

        now = self.clock.now()
        query = WorkQuery(kind="task", sort="due_asc", limit=limit, cursor=cursor).validate()
        actor.require("tasks:read")
        spec = self._work_spec(
            query,
            now,
            self._agenda_spec(query, now, groups=tuple(sorted(TODAY_GROUPS)), today_first=True),
        )
        after = self._page_position(actor, query, spec, key_prefix="today:v1:")

        def read(
            session: TxSession,
        ) -> tuple[list[dict[str, Any]], tuple[KeyValue, ...] | None, dict[str, int]]:
            keys = self.store.work_list_keys(
                session, actor.user_id, spec, after=after, limit=limit + 1
            )
            counts = self.store.work_agenda_group_counts(session, actor.user_id, spec)
            items = self._work_items(session, actor.user_id, keys[:limit], now)
            return items, keys[limit - 1].position if len(keys) > limit else None, counts

        items, more_after, counts = self.store.transaction(read)
        next_cursor = None
        if more_after is not None:
            next_cursor = self.cursor_codec.encode_keyset(
                actor.user_id, more_after, "today:v1:" + query.key()
            )
        return WorkToday(
            items=items,
            next_cursor=next_cursor,
            total=sum(counts.get(group, 0) for group in TODAY_GROUPS),
            overdue_total=counts.get("overdue", 0),
            today_total=counts.get("today", 0),
            day=now.astimezone(self.owner_timezone).date(),
            calculated_at=now,
        )

    def _agenda_spec(
        self,
        query: WorkQuery,
        now: datetime,
        *,
        groups: tuple[str, ...] | None = None,
        today_first: bool = False,
    ) -> AgendaSpec:
        day_start, day_end = owner_day_bounds(now, self.owner_timezone)
        return AgendaSpec(
            now=now,
            day_start=day_start,
            day_end=day_end,
            include_undated=query.include_undated,
            waiting_only=query.waiting == "waiting",
            groups=groups,
            today_first=today_first,
        )

    def _work_spec(
        self,
        query: WorkQuery,
        now: datetime,
        agenda: AgendaSpec | None,
        *,
        board_order: bool = False,
    ) -> WorkListSpec:
        tags, tag_match = query.normalized_tags()
        return WorkListSpec(
            now=now,
            q=query.q,
            status=query.status,
            priority=query.priority,
            due_from=query.due_from,
            due_to=query.due_to,
            attention_requested=query.attention == "requested",
            archive=query.archive,
            kind=query.kind,
            project_id=query.project_id,
            tags=tags,
            tag_match=tag_match,
            actionable=query.actionable,
            waiting=query.waiting,
            estimate=query.estimate,
            max_minutes=query.max_minutes,
            sort=query.sort,
            group=query.group,
            agenda=agenda,
            owner_zone=getattr(self.owner_timezone, "key", "UTC"),
            board_order=board_order,
        )

    def work_list_page(self, actor: Actor, query: WorkQuery) -> Page[dict[str, Any]]:
        return self._work_page(
            actor, query, now=self.clock.now(), key_prefix="work:v2:", agenda=None
        )

    def _work_page(
        self,
        actor: Actor,
        query: WorkQuery,
        *,
        now: datetime,
        key_prefix: str,
        agenda: AgendaSpec | None,
        board_order: bool = False,
    ) -> Page[dict[str, Any]]:
        """Filter and sort the owner's whole list in the database, then read one page of it.

        The cursor holds the last record's sort position (keyset paging) and is bound to the
        whole filter set, so a page never repeats a record when others are added or removed
        meanwhile. The page's records are then loaded together, never one query per record.
        """

        query.validate()
        actor.require("tasks:read")
        spec = self._work_spec(query, now, agenda, board_order=board_order)
        after = self._page_position(actor, query, spec, key_prefix=key_prefix)

        def read(
            session: TxSession,
        ) -> tuple[list[dict[str, Any]], tuple[KeyValue, ...] | None]:
            keys = self.store.work_list_keys(
                session, actor.user_id, spec, after=after, limit=query.limit + 1
            )
            return (
                self._work_items(session, actor.user_id, keys[: query.limit], now),
                keys[query.limit - 1].position if len(keys) > query.limit else None,
            )

        items, more_after = self.store.transaction(read)
        next_cursor = None
        if more_after is not None:
            next_cursor = self.cursor_codec.encode_keyset(
                actor.user_id, more_after, key_prefix + query.key()
            )
        return Page(items, next_cursor)

    def _page_position(
        self, actor: Actor, query: WorkQuery, spec: WorkListSpec, *, key_prefix: str
    ) -> tuple[KeyValue, ...] | None:
        order = sort_keys(spec)
        return self.cursor_codec.decode_keyset(
            actor.user_id,
            query.cursor,
            key_prefix + query.key(),
            kinds=tuple(key.kind for key in order),
            nullable=tuple(key.nullable for key in order),
        )

    def _work_items(
        self, session: TxSession, owner_id: UUID, keys: list[WorkKey], now: datetime
    ) -> list[dict[str, Any]]:
        """The Work records for one page of keys: their tags, Project titles and Domain accents
        are read for this page only, a fixed number of queries however long the list is."""

        ids: dict[str, list[UUID]] = {}
        for key in keys:
            ids.setdefault(key.kind, []).append(key.id)
        records = self.store.work_records_by_ids(session, owner_id, ids)
        tag_slugs = self.store.record_tag_slugs(session, owner_id, record_ids=ids)
        tasks = {id_: t for id_, t in records.get("task", {}).items() if isinstance(t, Task)}
        projects = {
            id_: p for id_, p in records.get("project", {}).items() if isinstance(p, Project)
        }
        project_ids = tuple({t.project_id for t in tasks.values() if t.project_id is not None})
        process_ids = tuple({t.process_id for t in tasks.values() if t.process_id is not None})
        titles = self.store.project_titles(session, owner_id, project_ids)
        process_domains = self.store.process_domain_ids(session, owner_id, process_ids)
        project_domains = self.store.project_domain_ids(session, owner_id, project_ids)
        task_domain_ids = {
            task.id: derive_domain_id(task, process_domains, project_domains)
            for task in tasks.values()
        }
        # Only the Domains this page names: its Projects' and its Tasks' Domains.
        page_domain_ids = {project.domain_id for project in projects.values()}
        page_domain_ids.update(d for d in task_domain_ids.values() if d is not None)
        domain_accents = self.store.domain_accents(session, owner_id, tuple(page_domain_ids))

        items: list[dict[str, Any]] = []
        for key in keys:
            record = records.get(key.kind, {}).get(key.id)
            if record is None:
                continue  # Deleted since the key query read it.
            tags = tag_slugs.get((key.kind, key.id), ())
            item: dict[str, Any]
            match record:
                case Domain():
                    item = _domain_work_item(record, tags=tags, now=now)
                case Process():
                    item = _process_work_item(record, tags=tags)
                case Project():
                    item = _project_work_item(
                        record,
                        self.owner_timezone,
                        tags=tags,
                        now=now,
                        domain_accent=domain_accents.get(record.domain_id),
                    )
                case Task():
                    task_domain = task_domain_ids[record.id]
                    item = _task_work_item(
                        record,
                        record.project_id or record.process_id or record.domain_id,
                        tags=tags,
                        now=now,
                        project_title=_clipped_title(
                            titles.get(record.project_id) if record.project_id else None
                        ),
                        domain_accent=domain_accents.get(task_domain) if task_domain else None,
                    )
                case Step():
                    item = _step_work_item(record, record.task_id)
                case Action():
                    item = _action_work_item(record, record.step_id)
            if key.agenda_group is not None:
                item = {**item, "agenda_group": key.agenda_group}
            items.append(item)
        return items

    def work_board_page(
        self, actor: Actor, query: WorkQuery
    ) -> tuple[dict[str, list[dict[str, Any]]], str | None]:
        """Group the bounded Work page into status columns in manual board order.

        The database orders the whole list by manual `board_rank` first and the requested
        fallback order after it, and the cursor continues that order, so every page holds the
        next records of it and each column keeps the owner's order across pages. Ranks are
        ordering input only and are not part of any projection payload.
        """

        page = self._work_page(
            actor,
            query,
            now=self.clock.now(),
            key_prefix="work:board:v1:",
            agenda=None,
            board_order=True,
        )
        columns: dict[str, list[dict[str, Any]]] = {}
        for item in page.items:
            columns.setdefault(str(item["status"]), []).append(item)
        return columns, page.next_cursor

    def work_board_manual_statuses(self, actor: Actor, query: WorkQuery) -> tuple[str, ...]:
        """Status columns the owner has ordered by hand, under the board's status and Project scope.

        Only status names leave this method; rank values stay in the store.
        """

        actor.require("tasks:read")
        return self.store.transaction(
            lambda s: self.store.board_manual_statuses(
                s, actor.user_id, status=query.status, project_id=query.project_id
            )
        )

    def create_domain(
        self,
        actor: Actor,
        *,
        name: str,
        description: str | None,
        idempotency_key: str,
        correlation_id: str | None = None,
        accent: str | None = None,
    ) -> Domain:
        actor.require("projects:write")
        payload = {"name": name, "description": description, "accent": accent}
        return self.store.transaction(
            lambda s: self._replayed_domain(
                s,
                actor,
                self.store.idempotent(
                    s,
                    actor_id=actor.user_id,
                    operation="create_domain",
                    key=idempotency_key,
                    payload=payload,
                    execute=lambda: self._create_domain(s, actor, payload, correlation_id),
                    replay=id_replay_record,
                ),
            )
        )

    def _create_domain(
        self, session: TxSession, actor: Actor, payload: dict[str, Any], correlation_id: str | None
    ) -> dict[str, Any]:
        now = self.clock.now()
        entity = Domain(
            new_uuid7(),
            actor.user_id,
            payload["name"],
            payload["description"],
            DomainStatus.ACTIVE,
            now,
            now,
            accent=payload.get("accent"),
        )
        self.store.save_domain(session, entity)
        self.store.append_audit(
            session,
            actor_id=actor.user_id,
            event="domain.created",
            outcome="success",
            target_type="domain",
            target_id=entity.id,
            correlation_id=correlation_id,
        )
        return domain_to_data(entity)

    def get_domain(self, actor: Actor, domain_id: UUID) -> Domain:
        actor.require("projects:read")
        return self.store.transaction(lambda s: self.store.get_domain(s, actor.user_id, domain_id))

    def update_domain(
        self,
        actor: Actor,
        domain_id: UUID,
        *,
        version: int,
        idempotency_key: str,
        command: UpdateContextCommand,
        correlation_id: str | None = None,
    ) -> Domain:
        actor.require("projects:write")

        def operation(session: TxSession) -> dict[str, Any]:
            current = self.store.get_domain(session, actor.user_id, domain_id)
            changes = command.entity_changes("domain")
            changes.pop("status", None)
            updated = current.update(
                now=self.clock.now(),
                status=command.status if isinstance(command.status, DomainStatus) else UNSET,
                **changes,
            )
            self.store.save_domain(session, updated, expected_version=version)
            self.store.append_audit(
                session,
                actor_id=actor.user_id,
                event="domain.updated",
                outcome="success",
                target_type="domain",
                target_id=domain_id,
                correlation_id=correlation_id,
            )
            data = domain_to_data(updated)
            if command.tags is not UNSET:
                data["tags"] = list(
                    apply_record_tags(
                        self.store,
                        session,
                        owner_id=actor.user_id,
                        kind="domain",
                        record_id=domain_id,
                        values=command.tags,
                        now=self.clock.now(),
                    )
                )
            return data

        return self.store.transaction(
            lambda s: self._replayed_domain(
                s,
                actor,
                self.store.idempotent(
                    s,
                    actor_id=actor.user_id,
                    operation="update_domain",
                    key=idempotency_key,
                    payload={
                        "domain_id": str(domain_id),
                        "version": version,
                        "changes": command.changes(),
                    },
                    execute=lambda: operation(s),
                    replay=id_replay_record,
                ),
            )
        )

    def create_process(
        self,
        actor: Actor,
        *,
        domain_id: UUID,
        name: str,
        description: str | None,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> Process:
        actor.require("projects:write")
        payload = {"domain_id": str(domain_id), "name": name, "description": description}
        return self.store.transaction(
            lambda s: self._replayed_process(
                s,
                actor,
                self.store.idempotent(
                    s,
                    actor_id=actor.user_id,
                    operation="create_process",
                    key=idempotency_key,
                    payload=payload,
                    execute=lambda: self._create_process(
                        s, actor, domain_id, payload, correlation_id
                    ),
                    replay=id_replay_record,
                ),
            )
        )

    def get_process(self, actor: Actor, process_id: UUID) -> Process:
        actor.require("projects:read")
        return self.store.transaction(
            lambda s: self.store.get_process(s, actor.user_id, process_id)
        )

    def update_process(
        self,
        actor: Actor,
        process_id: UUID,
        *,
        version: int,
        idempotency_key: str,
        command: UpdateContextCommand,
        correlation_id: str | None = None,
    ) -> Process:
        actor.require("projects:write")

        def operation(session: TxSession) -> dict[str, Any]:
            current = self.store.get_process(session, actor.user_id, process_id)
            if command.domain_id is not UNSET:
                self.store.get_domain(session, actor.user_id, command.domain_id)
            changes = command.entity_changes("process")
            changes.pop("status", None)
            now = self.clock.now()
            next_expected_run_at = current.next_expected_run_at
            if command.cadence is not UNSET:
                next_expected_run_at = (
                    now + command.cadence.interval if command.cadence is not None else None
                )
            elif (
                command.status is ProcessStatus.ACTIVE
                and current.cadence is not None
                and next_expected_run_at is None
            ):
                next_expected_run_at = now + current.cadence.interval
            updated = current.update(
                now=now,
                status=command.status if isinstance(command.status, ProcessStatus) else UNSET,
                next_expected_run_at=next_expected_run_at,
                **changes,
            )
            self.store.save_process(session, updated, expected_version=version)
            self.store.append_audit(
                session,
                actor_id=actor.user_id,
                event="process.updated",
                outcome="success",
                target_type="process",
                target_id=process_id,
                correlation_id=correlation_id,
            )
            data = process_to_data(updated)
            if command.tags is not UNSET:
                data["tags"] = list(
                    apply_record_tags(
                        self.store,
                        session,
                        owner_id=actor.user_id,
                        kind="process",
                        record_id=process_id,
                        values=command.tags,
                        now=self.clock.now(),
                    )
                )
            return data

        return self.store.transaction(
            lambda s: self._replayed_process(
                s,
                actor,
                self.store.idempotent(
                    s,
                    actor_id=actor.user_id,
                    operation="update_process",
                    key=idempotency_key,
                    payload={
                        "process_id": str(process_id),
                        "version": version,
                        "changes": command.changes(),
                    },
                    execute=lambda: operation(s),
                    replay=id_replay_record,
                ),
            )
        )

    def _create_process(
        self,
        session: TxSession,
        actor: Actor,
        domain_id: UUID,
        payload: dict[str, Any],
        correlation_id: str | None,
    ) -> dict[str, Any]:
        now = self.clock.now()
        self.store.get_domain(session, actor.user_id, domain_id)
        entity = Process(
            new_uuid7(),
            actor.user_id,
            domain_id,
            payload["name"],
            payload["description"],
            ProcessStatus.ACTIVE,
            now,
            now,
        )
        self.store.save_process(session, entity)
        self.store.append_audit(
            session,
            actor_id=actor.user_id,
            event="process.created",
            outcome="success",
            target_type="process",
            target_id=entity.id,
            correlation_id=correlation_id,
        )
        return process_to_data(entity)


def domain_to_data(domain: Domain) -> dict[str, Any]:
    return {
        "id": str(domain.id),
        "owner_id": str(domain.owner_id),
        "name": domain.name,
        "description": domain.description,
        "status": domain.status.value,
        "created_at": domain.created_at.isoformat(),
        "updated_at": domain.updated_at.isoformat(),
        "version": domain.version,
        "review_cadence": domain.review_cadence.value if domain.review_cadence else None,
        "last_reviewed_at": (
            domain.last_reviewed_at.isoformat() if domain.last_reviewed_at else None
        ),
        "accent": domain.accent,
    }


def process_hierarchy_node(process: Process) -> dict[str, Any]:
    """The hierarchy node of one Process; `hierarchy_page` and a Process-only read share it."""

    return {
        "kind": "process",
        "id": process.id,
        "parent_id": process.domain_id,
        "title": process.name,
        "status": process.status.value,
        "version": process.version,
    }


def process_to_data(process: Process) -> dict[str, Any]:
    return {
        "id": str(process.id),
        "owner_id": str(process.owner_id),
        "domain_id": str(process.domain_id),
        "name": process.name,
        "description": process.description,
        "status": process.status.value,
        "created_at": process.created_at.isoformat(),
        "updated_at": process.updated_at.isoformat(),
        "version": process.version,
        "cadence": process.cadence.value if process.cadence else None,
        "next_expected_run_at": (
            process.next_expected_run_at.isoformat() if process.next_expected_run_at else None
        ),
    }


def _planning_defaults() -> dict[str, Any]:
    """Uniform keys, so one filter reads every kind the same way.

    `project_title` is only set on a Task that belongs to a Project; every other kind has none.
    """

    return {
        "project_title": None,
        "earliest_start": None,
        "actionable_now": True,
        "estimated_minutes": None,
        "waiting": False,
        "waiting_since": None,
        "follow_up_at": None,
        "waiting_on_contact_id": None,
        "follow_up_due": False,
        "blocked_reminder_due": False,
        "blocked_reminder_cadence": None,
        "blocked_reminder_snoozed_until": None,
        "recurrence": None,
        "last_completed_at": None,
        "review_due": False,
        "review_cadence": None,
        "cadence": None,
        "tags": (),
    }


MAX_PROJECT_TITLE_CHARS = 120


def clipped_project_title(title: str | None) -> str | None:
    """Public form of the Work record's Project-title clip (120 characters, last one `…`)."""

    return _clipped_title(title)


def _clipped_title(title: str | None) -> str | None:
    """A Project title as a Work record names it: at most 120 characters, the last one `…`."""

    if title is None or len(title) <= MAX_PROJECT_TITLE_CHARS:
        return title
    return title[: MAX_PROJECT_TITLE_CHARS - 1] + "…"


def _task_work_item(
    task: Task,
    parent_id: UUID | None,
    *,
    tags: tuple[str, ...] = (),
    now: datetime | None = None,
    project_title: str | None = None,
    domain_accent: str | None = None,
) -> dict[str, Any]:
    at = now or datetime.now(UTC)
    return {
        **_planning_defaults(),
        "kind": "task",
        "id": task.id,
        "parent_id": parent_id,
        "title": task.title,
        "status": task.status.value,
        "priority": task.priority.value,
        "due_at": task.due_at,
        "attention_requested": task.attention_requested,
        "version": task.version,
        "archived": task.archived_at is not None,
        "domain_id": task.domain_id,
        "process_id": task.process_id,
        "project_id": task.project_id,
        "project_title": project_title,
        "domain_accent": domain_accent,
        "task_id": task.id,
        "earliest_start": task.not_before,
        "actionable_now": is_actionable_now(task.not_before, at),
        "estimated_minutes": task.estimated_minutes,
        "waiting": task.waiting,
        "waiting_since": task.waiting_since,
        "follow_up_at": task.follow_up_at,
        "waiting_on_contact_id": task.waiting_on_contact_id,
        "follow_up_due": task.follow_up_due(now=at),
        "blocked_reminder_due": task.blocked_reminder_due(now=at),
        "blocked_reminder_cadence": (
            task.blocked_reminder_cadence.value if task.blocked_reminder_cadence else None
        ),
        "blocked_reminder_snoozed_until": task.blocked_reminder_snoozed_until,
        "recurrence": task.recurrence.to_data() if task.recurrence else None,
        "last_completed_at": task.last_completed_at,
        "tags": tags,
    }


def _domain_work_item(
    domain: Domain, *, tags: tuple[str, ...] = (), now: datetime | None = None
) -> dict[str, Any]:
    at = now or datetime.now(UTC)
    return {
        **_planning_defaults(),
        "kind": "domain",
        "id": domain.id,
        "parent_id": None,
        "title": domain.name,
        "status": domain.status.value,
        "priority": None,
        "due_at": None,
        "attention_requested": False,
        "version": domain.version,
        "archived": domain.status is DomainStatus.ARCHIVED,
        "domain_id": domain.id,
        "review_cadence": domain.review_cadence.value if domain.review_cadence else None,
        "review_due": domain.review_due(now=at),
        "tags": tags,
    }


def _process_work_item(process: Process, *, tags: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        **_planning_defaults(),
        "kind": "process",
        "id": process.id,
        "parent_id": process.domain_id,
        "title": process.name,
        "status": process.status.value,
        "priority": None,
        "due_at": None,
        "attention_requested": False,
        "version": process.version,
        "archived": process.status is ProcessStatus.ARCHIVED,
        "domain_id": process.domain_id,
        "process_id": process.id,
        "cadence": process.cadence.value if process.cadence else None,
        "tags": tags,
    }


def _project_work_item(
    project: Project,
    zone: tzinfo,
    *,
    tags: tuple[str, ...] = (),
    now: datetime | None = None,
    domain_accent: str | None = None,
) -> dict[str, Any]:
    at = now or datetime.now(UTC)
    due_at = project_due_at(project.target_date, zone) if project.target_date is not None else None
    earliest_start = (
        project_earliest_start(project.start_date, zone) if project.start_date is not None else None
    )
    return {
        **_planning_defaults(),
        "kind": "project",
        "id": project.id,
        "parent_id": project.domain_id,
        "title": project.title,
        "status": project.status.value,
        "priority": None,
        "due_at": due_at,
        "attention_requested": False,
        "version": project.version,
        "archived": project.archived_at is not None,
        "domain_id": project.domain_id,
        "domain_accent": domain_accent,
        "project_id": project.id,
        "earliest_start": earliest_start,
        "actionable_now": is_actionable_now(earliest_start, at),
        "tags": tags,
    }


def _step_work_item(step: Step, parent_id: UUID) -> dict[str, Any]:
    return {
        **_planning_defaults(),
        "kind": "step",
        "id": step.id,
        "parent_id": parent_id,
        "title": step.title,
        "status": step.status.value,
        "priority": None,
        "due_at": step.due_at,
        "attention_requested": step.attention_requested,
        "version": step.version,
        "archived": step.archived_at is not None,
        "task_id": step.task_id,
    }


def _action_work_item(action: Action, parent_id: UUID) -> dict[str, Any]:
    return {
        **_planning_defaults(),
        "kind": "action",
        "id": action.id,
        "parent_id": parent_id,
        "title": action.title,
        "status": action.status.value,
        "priority": None,
        "due_at": action.due_at,
        "attention_requested": action.attention_requested,
        "version": action.version,
        "archived": action.archived_at is not None,
    }
