"""Work lists, the agenda, Today and the board: one filtered, sorted, keyset-paged read model."""

from dataclasses import replace
from datetime import UTC, datetime, time, timedelta, tzinfo
from uuid import UUID

from sidekick.projects.domain import Project
from sidekick.shared.types import (
    Actor,
    Clock,
    CursorCodec,
    KeyValue,
    Page,
    TxSession,
    paginate,
)
from sidekick.tasks.domain import Task, derive_domain_id
from sidekick.work.application.models import WorkQuery, WorkRow, WorkToday
from sidekick.work.application.serialization import (
    action_work_item,
    clipped_project_title,
    domain_work_item,
    process_work_item,
    project_work_item,
    step_work_item,
    task_work_item,
)
from sidekick.work.application.store import ContextStore
from sidekick.work.domain import Action, Domain, Process, Step
from sidekick.work.listing import AgendaSpec, WorkKey, WorkListSpec, sort_keys

TODAY_GROUPS = frozenset({"overdue", "today"})


def owner_day_bounds(instant: datetime, zone: tzinfo) -> tuple[datetime, datetime]:
    """The owner's calendar day around an aware instant, as UTC instants: `[start, end)`."""

    day = instant.astimezone(zone).date()
    start = datetime.combine(day, time.min, tzinfo=zone).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone).astimezone(UTC)
    return start, end


class WorkListService:
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

    def work_agenda_page(self, actor: Actor, query: WorkQuery) -> Page[WorkRow]:
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
        never the page. "Today" is the owner's calendar day (SIDEKICK_OWNER_TIMEZONE, D-063: owner
        timezone setting), not
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
        ) -> tuple[list[WorkRow], str | None, dict[str, int]]:
            keys = self.store.work_list_keys(
                session, actor.user_id, spec, after=after, limit=limit + 1
            )
            counts = self.store.work_agenda_group_counts(session, actor.user_id, spec)
            page, next_cursor = paginate(
                keys,
                limit,
                lambda last: self.cursor_codec.encode_keyset(
                    actor.user_id, last.position, "today:v1:" + query.key()
                ),
            )
            return self._work_items(session, actor.user_id, page, now), next_cursor, counts

        items, next_cursor, counts = self.store.transaction(read)
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
        tags, _ = query.normalized_tags()
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
            tag_match=query.tag_match,
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

    def work_list_page(self, actor: Actor, query: WorkQuery) -> Page[WorkRow]:
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
    ) -> Page[WorkRow]:
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
        ) -> tuple[list[WorkRow], str | None]:
            keys = self.store.work_list_keys(
                session, actor.user_id, spec, after=after, limit=query.limit + 1
            )
            page, next_cursor = paginate(
                keys,
                query.limit,
                lambda last: self.cursor_codec.encode_keyset(
                    actor.user_id, last.position, key_prefix + query.key()
                ),
            )
            return self._work_items(session, actor.user_id, page, now), next_cursor

        return Page(*self.store.transaction(read))

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
    ) -> list[WorkRow]:
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

        items: list[WorkRow] = []
        for key in keys:
            record = records.get(key.kind, {}).get(key.id)
            if record is None:
                continue  # Deleted since the key query read it.
            tags = tag_slugs.get((key.kind, key.id), ())
            item: WorkRow
            match record:
                case Domain():
                    item = domain_work_item(record, tags=tags, now=now)
                case Process():
                    item = process_work_item(record, tags=tags)
                case Project():
                    item = project_work_item(
                        record,
                        self.owner_timezone,
                        tags=tags,
                        now=now,
                        domain_accent=domain_accents.get(record.domain_id),
                    )
                case Task():
                    task_domain = task_domain_ids[record.id]
                    item = task_work_item(
                        record,
                        record.project_id or record.process_id or record.domain_id,
                        tags=tags,
                        now=now,
                        project_title=clipped_project_title(
                            titles.get(record.project_id) if record.project_id else None
                        ),
                        domain_accent=domain_accents.get(task_domain) if task_domain else None,
                    )
                case Step():
                    item = step_work_item(record, record.task_id)
                case Action():
                    item = action_work_item(record, record.step_id)
            if key.agenda_group is not None:
                item = replace(item, agenda_group=key.agenda_group)
            items.append(item)
        return items

    def work_board_page(
        self, actor: Actor, query: WorkQuery
    ) -> tuple[dict[str, list[WorkRow]], str | None]:
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
        columns: dict[str, list[WorkRow]] = {}
        for item in page.items:
            columns.setdefault(item.status, []).append(item)
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
