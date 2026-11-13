"""Owner-scoped Work use cases shared by the MCP adapter: Domains, Processes, the hierarchy,
estimate totals and counts, and the Domain and Process writes."""

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import cast
from uuid import UUID

from sidekick.shared.errors import InvalidInputError, ValidationError
from sidekick.shared.replay import id_replay_record, id_result, record_id
from sidekick.shared.types import (
    TIMED_KEY,
    UNSET,
    Actor,
    Clock,
    CursorCodec,
    Page,
    TxSession,
    new_uuid7,
    paginate,
    validate_limit,
)
from sidekick.tasks.domain.planning import EstimateTotals
from sidekick.work.application.models import HierarchyNode, UpdateContextCommand
from sidekick.work.application.serialization import (
    domain_hierarchy_node,
    process_hierarchy_node,
    project_hierarchy_node,
)
from sidekick.work.application.store import ContextStore
from sidekick.work.domain import Domain, DomainStatus, Process, ProcessStatus
from sidekick.work.domain.tag_assignment import apply_record_tags

HIERARCHY_KINDS = ("domain", "process", "project")
"""The order of `get_work_hierarchy` nodes; the cursor carries the index of the last kind served."""

HIERARCHY_CURSOR_KEY = "hierarchy:v1"

ESTIMATE_TOTAL_SCOPES = frozenset(
    {"agenda_day", "project_open_tasks", "actionable_now", "selection"}
)


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

    def _replayed_domain(
        self, session: TxSession, actor: Actor, record: Mapping[str, object]
    ) -> Domain:
        """The Domain a (possibly replayed) write refers to, re-read by id.

        The idempotency record keeps only the id, so a retry returns the Domain as it is now.
        """

        return self.store.get_domain(session, actor.user_id, record_id(record))

    def _replayed_process(
        self, session: TxSession, actor: Actor, record: Mapping[str, object]
    ) -> Process:
        """The Process a (possibly replayed) write refers to, re-read by id."""

        return self.store.get_process(session, actor.user_id, record_id(record))

    def list_domains(
        self, actor: Actor, *, limit: int = 25, cursor: str | None = None
    ) -> Page[Domain]:
        actor.require("projects:read")
        validate_limit(limit, maximum=100)
        key = "domains:v1"
        after = self.cursor_codec.decode_keyset(actor.user_id, cursor, key, kinds=TIMED_KEY)
        rows = self.store.transaction(
            lambda s: self.store.list_domains(s, actor.user_id, limit + 1, after)
        )
        return Page(
            *paginate(
                rows,
                limit,
                lambda last: self.cursor_codec.encode_keyset(
                    actor.user_id, (last.updated_at, last.id), key
                ),
            )
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
        validate_limit(limit, maximum=100)
        key = f"processes:v1:domain={domain_id or '*'}"
        after = self.cursor_codec.decode_keyset(actor.user_id, cursor, key, kinds=TIMED_KEY)
        rows = self.store.transaction(
            lambda s: self.store.list_processes(s, actor.user_id, limit + 1, domain_id, after)
        )
        return Page(
            *paginate(
                rows,
                limit,
                lambda last: self.cursor_codec.encode_keyset(
                    actor.user_id, (last.updated_at, last.id), key
                ),
            )
        )

    def hierarchy_page(
        self, actor: Actor, *, limit: int = 100, cursor: str | None = None
    ) -> tuple[list[HierarchyNode], str | None]:
        """Return one page of nodes and the cursor of the next page, or None after the last.

        Nodes are ordered Domains, then Processes, then Projects, each newest change first.
        The cursor is the keyset position (kind rank, updated_at, id) of the last node served,
        so the next page continues strictly after it, also across a kind boundary, and no node
        is served twice while the data changes. Each kind is read with only the rows still
        needed plus one, so an overflow is detectable without a count query.
        """
        actor.require("projects:read")
        validate_limit(limit, maximum=100)
        after = self.cursor_codec.decode_keyset(
            actor.user_id, cursor, HIERARCHY_CURSOR_KEY, kinds=(int, datetime, UUID)
        )
        if after is not None and not 0 <= cast("int", after[0]) < len(HIERARCHY_KINDS):
            raise InvalidInputError("invalid pagination cursor")

        def query(session: TxSession) -> list[tuple[int, datetime, UUID, HierarchyNode]]:
            entries: list[tuple[int, datetime, UUID, HierarchyNode]] = []
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
                            domain_hierarchy_node(item),
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
                            project_hierarchy_node(item),
                        )
                        for item in project_rows
                    )
            return entries

        entries = self.store.transaction(query)
        page, next_cursor = paginate(
            entries,
            limit,
            lambda last: self.cursor_codec.encode_keyset(
                actor.user_id, (last[0], last[1], last[2]), HIERARCHY_CURSOR_KEY
            ),
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
                    execute=lambda: id_result(
                        self._create_domain(
                            s,
                            actor,
                            name=name,
                            description=description,
                            accent=accent,
                            correlation_id=correlation_id,
                        ).id
                    ),
                    replay=id_replay_record,
                ),
            )
        )

    def _create_domain(
        self,
        session: TxSession,
        actor: Actor,
        *,
        name: str,
        description: str | None,
        accent: str | None,
        correlation_id: str | None,
    ) -> Domain:
        now = self.clock.now()
        entity = Domain(
            new_uuid7(),
            actor.user_id,
            name,
            description,
            DomainStatus.ACTIVE,
            now,
            now,
            accent=accent,
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
        return entity

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

        def operation(session: TxSession) -> Domain:
            current = self.store.get_domain(session, actor.user_id, domain_id)
            changes = command.entity_changes("domain")
            changes.pop("status", None)
            now = self.clock.now()
            if changes or command.status is not UNSET or command.tags is UNSET:
                updated = current.update(
                    now=now,
                    status=command.status if isinstance(command.status, DomainStatus) else UNSET,
                    **changes,
                )
            else:
                # A tags-only update still advances the version under the caller's expected one.
                updated = replace(current, version=current.version + 1, updated_at=now)
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
            if command.tags is not UNSET:
                apply_record_tags(
                    self.store,
                    session,
                    owner_id=actor.user_id,
                    kind="domain",
                    record_id=domain_id,
                    values=command.tags,
                    now=self.clock.now(),
                )
            return updated

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
                    execute=lambda: id_result(operation(s).id),
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
                    execute=lambda: id_result(
                        self._create_process(
                            s,
                            actor,
                            domain_id,
                            name=name,
                            description=description,
                            correlation_id=correlation_id,
                        ).id
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

        def operation(session: TxSession) -> Process:
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
            if changes or command.status is not UNSET or command.tags is UNSET:
                updated = current.update(
                    now=now,
                    status=command.status if isinstance(command.status, ProcessStatus) else UNSET,
                    next_expected_run_at=next_expected_run_at,
                    **changes,
                )
            else:
                # A tags-only update still advances the version under the caller's expected one.
                updated = replace(current, version=current.version + 1, updated_at=now)
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
            if command.tags is not UNSET:
                apply_record_tags(
                    self.store,
                    session,
                    owner_id=actor.user_id,
                    kind="process",
                    record_id=process_id,
                    values=command.tags,
                    now=self.clock.now(),
                )
            return updated

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
                    execute=lambda: id_result(operation(s).id),
                    replay=id_replay_record,
                ),
            )
        )

    def _create_process(
        self,
        session: TxSession,
        actor: Actor,
        domain_id: UUID,
        *,
        name: str,
        description: str | None,
        correlation_id: str | None,
    ) -> Process:
        now = self.clock.now()
        self.store.get_domain(session, actor.user_id, domain_id)
        entity = Process(
            new_uuid7(),
            actor.user_id,
            domain_id,
            name,
            description,
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
        return entity
