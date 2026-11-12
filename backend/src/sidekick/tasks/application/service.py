"""Transport-neutral Task commands and queries."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, tzinfo
from typing import Any, Protocol, TypeVar
from uuid import UUID

from sidekick.contacts.domain.contact import Contact
from sidekick.projects.domain import Project
from sidekick.shared.config import DEFAULT_OWNER_TIMEZONE, parse_owner_timezone
from sidekick.shared.errors import ConflictError, InvalidInputError, ValidationError
from sidekick.shared.replay import id_replay_record, items_replay_record
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
from sidekick.tasks.domain import (
    Priority,
    RecurrenceRule,
    Task,
    TaskActivityRecorder,
    TaskStatus,
    TaskStatusHistory,
    derive_domain_id,
)
from sidekick.work.domain import Domain, Process, Step
from sidekick.work.domain.planning import Cadence, WorkTag, parse_cadence
from sidekick.work.domain.tag_assignment import apply_record_tags

T = TypeVar("T")

DEFAULT_OWNER_ZONE = parse_owner_timezone(DEFAULT_OWNER_TIMEZONE)


@dataclass(frozen=True, slots=True)
class UpdateTaskCommand:
    """Explicit mutable Task fields; omitted and null remain distinct."""

    project_id: UUID | None | UnsetType = UNSET
    title: str | UnsetType = UNSET
    description: str | None | UnsetType = UNSET
    status: TaskStatus | UnsetType = UNSET
    priority: Priority | UnsetType = UNSET
    due_at: datetime | None | UnsetType = UNSET
    domain_id: UUID | None | UnsetType = UNSET
    process_id: UUID | None | UnsetType = UNSET
    attention_requested: bool | UnsetType = UNSET
    not_before: datetime | None | UnsetType = UNSET
    estimated_minutes: int | None | UnsetType = UNSET
    waiting_since: datetime | None | UnsetType = UNSET
    follow_up_at: datetime | None | UnsetType = UNSET
    waiting_on_contact_id: UUID | None | UnsetType = UNSET
    blocked_reminder_cadence: Cadence | None | UnsetType = UNSET
    blocked_reminder_snoozed_until: datetime | None | UnsetType = UNSET
    recurrence: RecurrenceRule | dict[str, Any] | None | UnsetType = UNSET
    last_completed_at: datetime | None | UnsetType = UNSET
    """Undo of a recurring completion: an earlier value (or null); never moves it forward."""
    tags: tuple[str, ...] | UnsetType = UNSET
    """The record's complete intended tag set; applied inside this same update."""

    def changes(self) -> dict[str, Any]:
        """Only Task fields. Tags are links and are applied separately."""

        return {
            key: value
            for key, value in {
                "project_id": self.project_id,
                "title": self.title,
                "description": self.description,
                "status": self.status,
                "priority": self.priority,
                "due_at": self.due_at,
                "domain_id": self.domain_id,
                "process_id": self.process_id,
                "attention_requested": self.attention_requested,
                "not_before": self.not_before,
                "estimated_minutes": self.estimated_minutes,
                "waiting_since": self.waiting_since,
                "follow_up_at": self.follow_up_at,
                "waiting_on_contact_id": self.waiting_on_contact_id,
                "blocked_reminder_cadence": self.blocked_reminder_cadence,
                "blocked_reminder_snoozed_until": self.blocked_reminder_snoozed_until,
                "recurrence": self.recurrence,
                "last_completed_at": self.last_completed_at,
            }.items()
            if value is not UNSET
        }

    def has_changes(self) -> bool:
        return bool(self.changes()) or self.tags is not UNSET


@dataclass(frozen=True, slots=True)
class TaskDetailRead:
    """One owned Task with what its detail view names, read in a single transaction."""

    task: Task
    tags: list[WorkTag]
    project_title: str | None
    """The Project's full title; the caller clips it the way a Work record does."""
    step_counts: dict[str, int]
    steps: list[Step]


@dataclass(frozen=True, slots=True)
class RescheduleTaskItem:
    """One Task's new due date, at the version the caller read; `due_at=None` clears it."""

    task_id: UUID
    expected_version: int
    due_at: datetime | None


@dataclass(frozen=True, slots=True)
class NewTaskItem:
    """One Task of a batch create, with its Steps as titles in the order they are created."""

    title: str
    due_at: datetime | None
    priority: Priority
    tags: tuple[str, ...]
    step_titles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BatchCreatedTask:
    """A Task of a batch as committed, with its Steps as plain step result data."""

    task: Task
    steps: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class TaskBatch:
    """The committed batch; `container_label` is the Project or Domain title, or None."""

    container_label: str | None
    tasks: tuple[BatchCreatedTask, ...]


@dataclass(frozen=True, slots=True)
class BoardPlacement:
    """Committed manual position of one Task inside a board status column."""

    task_id: UUID
    board_rank: int
    version: int


MAX_BOARD_COLUMN_REORDER = 100
MAX_RESCHEDULE_TASKS = 20
MAX_BATCH_CREATE_TASKS = 20
MAX_BATCH_STEPS_PER_TASK = 10


class TaskStore(TransactionalStore, IdempotentStore, AuditingStore, Protocol):
    """Concrete port needed for atomic Task and idempotency operations."""

    def list_board_column_tasks(
        self, session: TxSession, owner_id: UUID, status: TaskStatus, limit: int
    ) -> list[Task]: ...
    def list_tasks(
        self,
        session: TxSession,
        owner_id: UUID,
        limit: int,
        project_id: UUID | None = None,
        status: TaskStatus | None = None,
        after: tuple[KeyValue, ...] | None = None,
        include_archived: bool = False,
        process_id: UUID | None = None,
        unsorted: bool = False,
    ) -> list[Task]: ...
    def get_task(
        self,
        session: TxSession,
        owner_id: UUID,
        task_id: UUID,
        include_archived: bool = False,
        for_update: bool = False,
        include_hidden: bool = False,
    ) -> Task: ...
    def save_task(
        self, session: TxSession, task: Task, expected_version: int | None = None
    ) -> None: ...
    def save_step(self, session: TxSession, step: Step) -> None: ...
    def get_project(
        self,
        session: TxSession,
        owner_id: UUID,
        project_id: UUID,
        include_archived: bool = False,
    ) -> Project: ...
    def get_domain(self, session: TxSession, owner_id: UUID, domain_id: UUID) -> Domain: ...
    def get_process(self, session: TxSession, owner_id: UUID, process_id: UUID) -> Process: ...
    def get_contact(self, session: TxSession, owner_id: UUID, contact_id: UUID) -> Contact: ...
    def link_task_contact(
        self, session: TxSession, owner_id: UUID, task_id: UUID, contact_id: UUID
    ) -> datetime | None: ...
    def find_work_tag_by_slug(
        self, session: TxSession, owner_id: UUID, slug: str
    ) -> WorkTag | None: ...
    def save_work_tag(
        self, session: TxSession, tag: WorkTag, expected_version: int | None = None
    ) -> None: ...
    def replace_record_tags(
        self,
        session: TxSession,
        owner_id: UUID,
        kind: str,
        record_id: UUID,
        tag_ids: tuple[UUID, ...],
    ) -> None: ...
    def list_record_tags(
        self, session: TxSession, owner_id: UUID, kind: str, record_id: UUID
    ) -> list[WorkTag]: ...
    def append_task_status_history(
        self,
        session: TxSession,
        *,
        owner_id: UUID,
        task_id: UUID,
        from_status: TaskStatus | None,
        to_status: TaskStatus,
        changed_at: datetime,
        source: str,
    ) -> None: ...
    def list_task_status_history(
        self, session: TxSession, owner_id: UUID, task_id: UUID, limit: int
    ) -> list[TaskStatusHistory]: ...
    def project_titles(
        self, session: TxSession, owner_id: UUID, project_ids: tuple[UUID, ...]
    ) -> dict[UUID, str]: ...
    def process_domain_ids(
        self, session: TxSession, owner_id: UUID, process_ids: tuple[UUID, ...]
    ) -> dict[UUID, UUID]: ...
    def project_domain_ids(
        self, session: TxSession, owner_id: UUID, project_ids: tuple[UUID, ...]
    ) -> dict[UUID, UUID]: ...
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
    def list_live_steps_by_ids(
        self, session: TxSession, owner_id: UUID, step_ids: tuple[UUID, ...]
    ) -> dict[UUID, Step]: ...


class TaskService:
    def __init__(
        self,
        store: TaskStore,
        clock: Clock,
        cursor_codec: CursorCodec,
        activity_ledger: TaskActivityRecorder | None = None,
        *,
        owner_timezone: tzinfo = DEFAULT_OWNER_ZONE,
    ) -> None:
        self.store = store
        self.clock = clock
        self.cursor_codec = cursor_codec
        self.activity_ledger = activity_ledger
        self.owner_timezone = owner_timezone

    def _replayed_task(self, session: TxSession, actor: Actor, record: dict[str, Any]) -> Task:
        """The Task a (possibly replayed) write refers to, re-read by id.

        The idempotency record keeps only the id, so a retry returns the Task as it is now,
        archived or not, and also while its parent is in the trash.
        """

        task = self.store.get_task(
            session,
            actor.user_id,
            UUID(str(record["id"])),
            include_archived=True,
            include_hidden=True,
        )
        return self._with_derived_domain(session, actor, task)

    def _replayed_tasks(
        self, session: TxSession, actor: Actor, records: Sequence[dict[str, Any]]
    ) -> list[Task]:
        """Several (possibly replayed) Tasks re-read by id, their Domains looked up together."""

        tasks = [
            self.store.get_task(
                session,
                actor.user_id,
                UUID(str(record["id"])),
                include_archived=True,
                include_hidden=True,
            )
            for record in records
        ]
        return self._with_derived_domains(session, actor, tasks)

    def list(
        self,
        actor: Actor,
        *,
        limit: int = 25,
        project_id: UUID | None = None,
        process_id: UUID | None = None,
        status: TaskStatus | None = None,
        cursor: str | None = None,
        unsorted: bool = False,
    ) -> Page[Task]:
        actor.require("tasks:read")
        if not 1 <= limit <= 100:
            raise InvalidInputError("limit must be between 1 and 100")
        # The cursor is bound to the whole filter set, so adding the Process context
        # invalidates a cursor issued for another one. The unsorted suffix is added only when
        # set, so cursors issued before it existed stay valid.
        query_key = (
            f"tasks:v1:project={project_id or '*'}:process={process_id or '*'}"
            f":status={status.value if status else '*'}" + (":unsorted" if unsorted else "")
        )
        after = self.cursor_codec.decode_keyset(actor.user_id, cursor, query_key, kinds=TIMED_KEY)
        tasks = self.store.transaction(
            lambda session: self._with_derived_domains(
                session,
                actor,
                self.store.list_tasks(
                    session,
                    actor.user_id,
                    limit + 1,
                    project_id,
                    status,
                    after,
                    process_id=process_id,
                    unsorted=unsorted,
                ),
            )
        )
        return Page(
            items=tasks[:limit],
            next_cursor=self.cursor_codec.encode_keyset(
                actor.user_id, (tasks[limit - 1].updated_at, tasks[limit - 1].id), query_key
            )
            if len(tasks) > limit
            else None,
        )

    def get(self, actor: Actor, task_id: UUID) -> Task:
        actor.require("tasks:read")
        return self.store.transaction(
            lambda session: self._with_derived_domain(
                session, actor, self.store.get_task(session, actor.user_id, task_id)
            )
        )

    def get_detail(self, actor: Actor, task_id: UUID, *, step_limit: int) -> TaskDetailRead:
        """The Task, its tags, Project title, Step counts and first Steps in one transaction.

        Needs the same scopes the separate reads did: `tasks:read` and `projects:read` (tags).
        """

        actor.require("tasks:read")
        actor.require("projects:read")

        def read(session: TxSession) -> TaskDetailRead:
            task = self._with_derived_domain(
                session, actor, self.store.get_task(session, actor.user_id, task_id)
            )
            tags = self.store.list_record_tags(session, actor.user_id, "task", task_id)
            title = None
            if task.project_id is not None:
                title = self.store.project_titles(session, actor.user_id, (task.project_id,)).get(
                    task.project_id
                )
            return TaskDetailRead(
                task=task,
                tags=tags,
                project_title=title,
                step_counts=self.store.task_step_counts(session, actor.user_id, task_id=task_id),
                steps=self.store.list_steps(session, actor.user_id, task_id, step_limit),
            )

        return self.store.transaction(read)

    def _with_derived_domain(self, session: TxSession, actor: Actor, task: Task) -> Task:
        return self._with_derived_domains(session, actor, [task])[0]

    def _with_derived_domains(
        self, session: TxSession, actor: Actor, tasks: Sequence[Task]
    ) -> list[Task]:
        """Expose ancestry without duplicating it in the exclusive Task context.

        The Domains of all the Tasks' Processes and Projects are read together, so the number of
        queries is the same however many Tasks there are (none when none names a parent).
        """
        process_ids = tuple({t.process_id for t in tasks if t.process_id is not None})
        project_ids = tuple({t.project_id for t in tasks if t.project_id is not None})
        process_domains = self.store.process_domain_ids(session, actor.user_id, process_ids)
        project_domains = self.store.project_domain_ids(session, actor.user_id, project_ids)
        return [
            replace(
                task, derived_domain_id=derive_domain_id(task, process_domains, project_domains)
            )
            for task in tasks
        ]

    def create(
        self,
        actor: Actor,
        *,
        title: str,
        idempotency_key: str,
        project_id: UUID | None = None,
        domain_id: UUID | None = None,
        process_id: UUID | None = None,
        description: str | None = None,
        priority: Priority = Priority.NORMAL,
        due_at: datetime | None = None,
        not_before: datetime | None = None,
        estimated_minutes: int | None = None,
        blocked_reminder_cadence: Cadence | None = None,
        blocked_reminder_snoozed_until: datetime | None = None,
        recurrence: dict[str, Any] | None = None,
        tags: tuple[str, ...] | None = None,
        contact_ids: tuple[UUID, ...] = (),
        correlation_id: str | None = None,
    ) -> Task:
        actor.require("tasks:write")
        if contact_ids:
            actor.require("contacts:write")
        payload: dict[str, Any] = {
            "title": title,
            "project_id": str(project_id) if project_id else None,
            "domain_id": str(domain_id) if domain_id else None,
            "process_id": str(process_id) if process_id else None,
            "description": description,
            "priority": priority.value,
            "due_at": due_at,
            "not_before": not_before,
            "estimated_minutes": estimated_minutes,
            "blocked_reminder_cadence": blocked_reminder_cadence.value
            if blocked_reminder_cadence
            else None,
            "blocked_reminder_snoozed_until": blocked_reminder_snoozed_until,
            "recurrence": recurrence,
            "tags": list(tags or ()),
        }
        if contact_ids:
            # Only present when used, so retries of existing create keys keep their payload hash.
            payload["contact_ids"] = [str(contact_id) for contact_id in contact_ids]

        def operation(session: TxSession) -> Task:
            result = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="create_task",
                key=idempotency_key,
                payload=payload,
                execute=lambda: self._create(session, actor, payload, correlation_id),
                replay=id_replay_record,
            )
            return self._replayed_task(session, actor, result)

        return self.store.transaction(operation)

    def create_in_session(
        self,
        session: TxSession,
        actor: Actor,
        payload: dict[str, Any],
        correlation_id: str | None,
        actor_type: str = "user",
    ) -> dict[str, Any]:
        """Create a task inside the caller's open transaction and return its serialized result.

        For callers that must write a Task together with other rows in one transaction
        (process-run materialisation). Same contract as `_create`, which it delegates to.
        """

        return self._create(session, actor, payload, correlation_id, actor_type)

    def _create(
        self,
        session: TxSession,
        actor: Actor,
        payload: dict[str, Any],
        correlation_id: str | None,
        actor_type: str = "user",
    ) -> dict[str, Any]:
        project_id = UUID(payload["project_id"]) if payload["project_id"] else None
        domain_id = UUID(payload["domain_id"]) if payload["domain_id"] else None
        process_id = UUID(payload["process_id"]) if payload["process_id"] else None
        if project_id:
            self.store.get_project(session, actor.user_id, project_id)
        if domain_id:
            self.store.get_domain(session, actor.user_id, domain_id)
        if process_id:
            self.store.get_process(session, actor.user_id, process_id)
        now = self.clock.now()
        task = Task(
            id=new_uuid7(),
            owner_id=actor.user_id,
            project_id=project_id,
            domain_id=domain_id,
            process_id=process_id,
            title=payload["title"],
            description=payload["description"],
            status=TaskStatus.TODO,
            priority=Priority(payload["priority"]),
            due_at=payload["due_at"],
            completed_at=None,
            created_at=now,
            updated_at=now,
            not_before=payload.get("not_before"),
            estimated_minutes=payload.get("estimated_minutes"),
            blocked_reminder_cadence=parse_cadence(payload.get("blocked_reminder_cadence")),
            blocked_reminder_snoozed_until=payload.get("blocked_reminder_snoozed_until"),
            recurrence=RecurrenceRule.from_data(payload.get("recurrence")),
        )
        self.store.save_task(session, task)
        self.store.append_task_status_history(
            session,
            owner_id=actor.user_id,
            task_id=task.id,
            from_status=None,
            to_status=task.status,
            changed_at=now,
            source="created",
        )
        for raw_contact_id in payload.get("contact_ids") or ():
            contact_id = UUID(raw_contact_id)
            # Owner-scoped check first. A missing Contact raises not-found, which rolls back the
            # Task row, its history and the idempotency record, all in this one transaction.
            self.store.get_contact(session, actor.user_id, contact_id)
            linked_at = self.store.link_task_contact(session, actor.user_id, task.id, contact_id)
            if linked_at is not None:
                self.store.append_audit(
                    session,
                    actor_id=actor.user_id,
                    event="contact.task_linked",
                    outcome="success",
                    target_type="task_contact",
                    target_id=contact_id,
                    related_id=task.id,
                    correlation_id=correlation_id,
                )
        if payload.get("tags"):
            apply_record_tags(
                self.store,
                session,
                owner_id=actor.user_id,
                kind="task",
                record_id=task.id,
                values=tuple(payload["tags"]),
                now=now,
            )
        self.store.append_audit(
            session,
            actor_id=actor.user_id,
            event="task.created",
            outcome="success",
            target_type="task",
            target_id=task.id,
            correlation_id=correlation_id,
        )
        if self.activity_ledger is not None:
            self.activity_ledger.record_task(
                session,
                task=task,
                operation="create_task",
                actor_id=actor.user_id,
                actor_type=actor_type,
                occurred_at=now,
                correlation_id=correlation_id,
            )
        return task_to_data(task)

    def update(
        self,
        actor: Actor,
        task_id: UUID,
        *,
        version: int,
        idempotency_key: str,
        command: UpdateTaskCommand,
        correlation_id: str | None = None,
        only_if_status: TaskStatus | None = None,
    ) -> Task:
        """Update one Task under optimistic concurrency and an idempotency key.

        `only_if_status` is a guard on the Task's current status, checked on the row locked in the
        same transaction as the write (a reopen is only for a completed Task). It runs only when
        the key is not a replay, so a replay still answers with the stored result.
        """

        actor.require("tasks:write")
        changes = command.changes()
        if "blocked_reminder_cadence" in changes:
            changes["blocked_reminder_cadence"] = parse_cadence(changes["blocked_reminder_cadence"])
        if "recurrence" in changes:
            changes["recurrence"] = _recurrence_rule(changes["recurrence"])
        if not command.has_changes():
            raise InvalidInputError("at least one change is required")
        payload: dict[str, Any] = {"task_id": str(task_id), "version": version, **changes}
        if isinstance(payload.get("recurrence"), RecurrenceRule):
            payload["recurrence"] = payload["recurrence"].to_data()
        if command.tags is not UNSET:
            payload["tags"] = list(command.tags)

        def operation(session: TxSession) -> Task:
            result = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="update_task",
                key=idempotency_key,
                payload=payload,
                execute=lambda: self._update(
                    session,
                    actor,
                    task_id,
                    version,
                    command,
                    correlation_id,
                    only_if_status=only_if_status,
                ),
                replay=id_replay_record,
            )
            return self._replayed_task(session, actor, result)

        return self.store.transaction(operation)

    def _update(
        self,
        session: TxSession,
        actor: Actor,
        task_id: UUID,
        version: int,
        command: UpdateTaskCommand,
        correlation_id: str | None,
        actor_type: str = "user",
        only_if_status: TaskStatus | None = None,
    ) -> dict[str, Any]:
        guarded = only_if_status is not None
        task = self.store.get_task(session, actor.user_id, task_id, for_update=guarded)
        if guarded and task.status is not only_if_status:
            raise ConflictError("task is not in the required status", reason="not_completed")
        changes = command.changes()
        if "blocked_reminder_cadence" in changes:
            changes["blocked_reminder_cadence"] = parse_cadence(changes["blocked_reminder_cadence"])
        if "recurrence" in changes:
            changes["recurrence"] = _recurrence_rule(changes["recurrence"])
        if "project_id" in changes and changes["project_id"] is not None:
            project_id = changes["project_id"]
            assert isinstance(project_id, UUID)
            self.store.get_project(session, actor.user_id, project_id)
        if "domain_id" in changes and changes["domain_id"] is not None:
            domain_id = changes["domain_id"]
            assert isinstance(domain_id, UUID)
            self.store.get_domain(session, actor.user_id, domain_id)
        if "process_id" in changes and changes["process_id"] is not None:
            process_id = changes["process_id"]
            assert isinstance(process_id, UUID)
            self.store.get_process(session, actor.user_id, process_id)
        if "waiting_on_contact_id" in changes and changes["waiting_on_contact_id"] is not None:
            contact_id = changes["waiting_on_contact_id"]
            assert isinstance(contact_id, UUID)
            # Owner check first, so a cross-owner Contact is a safe not-found.
            self.store.get_contact(session, actor.user_id, contact_id)
        now = self.clock.now()
        tags_changed = command.tags is not UNSET
        updated = task.update(now=now, **changes) if changes else task
        if (
            updated.status is TaskStatus.COMPLETED
            and updated.recurrence is not None
            and task.status is not TaskStatus.COMPLETED
        ):
            updated = updated.reopen_for_recurrence(now=now, zone=self.owner_timezone)
        # Tags are relations, but they are part of a Task's optimistic-concurrency
        # surface. A tags-only update therefore advances the Task generation before
        # replacing links, under the caller's original expected version. This also gives
        # a later undo an exact version to protect against the owner's newer tag edit.
        if tags_changed and updated is task:
            updated = replace(task, version=task.version + 1, updated_at=now)
        if changes or tags_changed:
            self.store.save_task(session, updated, expected_version=version)
        self._record_status_transition(session, actor, task, updated, now, source="updated")
        if tags_changed:
            assert command.tags is not UNSET
            apply_record_tags(
                self.store,
                session,
                owner_id=actor.user_id,
                kind="task",
                record_id=task_id,
                values=command.tags,
                now=now,
            )
        self.store.append_audit(
            session,
            actor_id=actor.user_id,
            event="task.updated",
            outcome="success",
            target_type="task",
            target_id=task.id,
            correlation_id=correlation_id,
        )
        if self.activity_ledger is not None:
            self.activity_ledger.record_task(
                session,
                task=updated,
                before=task,
                operation="update_task",
                actor_id=actor.user_id,
                actor_type=actor_type,
                occurred_at=now,
                correlation_id=correlation_id,
                changed_fields=frozenset(changes) | ({"tags"} if tags_changed else set[str]()),
            )
        return task_to_data(updated)

    def reschedule(
        self,
        actor: Actor,
        items: Sequence[RescheduleTaskItem],
        *,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> list[Task]:
        """Set the due date of several Tasks in one transaction, via the same `_update` as `update`.

        A stale version or any other failure raises before the transaction commits, so no Task in
        the batch changes. The idempotency key covers the whole batch.
        """
        actor.require("tasks:write")
        if not items:
            raise ValidationError("at least one task is required")
        if len(items) > MAX_RESCHEDULE_TASKS:
            raise ValidationError(
                f"at most {MAX_RESCHEDULE_TASKS} tasks can be rescheduled at once"
            )
        if len({item.task_id for item in items}) != len(items):
            raise ValidationError("each task may appear only once")
        payload: dict[str, Any] = {
            "items": [
                {
                    "task_id": str(item.task_id),
                    "expected_version": item.expected_version,
                    "due_at": item.due_at.isoformat() if item.due_at else None,
                }
                for item in items
            ]
        }

        def operation(session: TxSession) -> list[Task]:
            result = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="reschedule_tasks",
                key=idempotency_key,
                payload=payload,
                execute=lambda: {
                    "tasks": [
                        self._update(
                            session,
                            actor,
                            item.task_id,
                            item.expected_version,
                            UpdateTaskCommand(due_at=item.due_at),
                            correlation_id,
                        )
                        for item in items
                    ]
                },
                replay=lambda result: items_replay_record(result, "tasks"),
            )
            return self._replayed_tasks(session, actor, result["tasks"])

        return self.store.transaction(operation)

    def create_batch(
        self,
        actor: Actor,
        items: Sequence[NewTaskItem],
        *,
        idempotency_key: str,
        project_id: UUID | None = None,
        domain_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> TaskBatch:
        """Create 1 to 20 Tasks, each with its ordered Steps, in one transaction.

        Each Task goes through `_create`, the same path as `create`, and its Steps are saved in
        the same session. A failing item raises before the transaction commits, so no Task or
        Step of the batch is kept. The idempotency key covers the whole batch.
        """
        actor.require("tasks:write")
        if not items:
            raise ValidationError("at least one task is required")
        if len(items) > MAX_BATCH_CREATE_TASKS:
            raise ValidationError(f"at most {MAX_BATCH_CREATE_TASKS} tasks can be created at once")
        if any(len(item.step_titles) > MAX_BATCH_STEPS_PER_TASK for item in items):
            raise ValidationError(f"at most {MAX_BATCH_STEPS_PER_TASK} steps per task")
        payload: dict[str, Any] = {
            "project_id": str(project_id) if project_id else None,
            "domain_id": str(domain_id) if domain_id else None,
            "items": [
                {
                    "title": item.title,
                    "due_at": item.due_at,
                    "priority": item.priority.value,
                    "tags": list(item.tags),
                    "step_titles": list(item.step_titles),
                }
                for item in items
            ],
        }

        def operation(session: TxSession) -> TaskBatch:
            label: str | None = None
            if project_id:
                label = self.store.get_project(session, actor.user_id, project_id).title
            elif domain_id:
                label = self.store.get_domain(session, actor.user_id, domain_id).name
            result = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="create_tasks",
                key=idempotency_key,
                payload=payload,
                execute=lambda: {
                    "tasks": [
                        self._create_batch_item(
                            session, actor, item, project_id, domain_id, correlation_id
                        )
                        for item in items
                    ]
                },
                replay=task_batch_replay_record,
            )
            created = self._replayed_tasks(session, actor, [e["task"] for e in result["tasks"]])
            replayed_steps = [
                self._replayed_steps(session, actor, task.id, entry.get("steps"))
                for task, entry in zip(created, result["tasks"], strict=True)
            ]
            return TaskBatch(
                container_label=label,
                tasks=tuple(
                    BatchCreatedTask(task=task, steps=steps)
                    for task, steps in zip(created, replayed_steps, strict=True)
                ),
            )

        return self.store.transaction(operation)

    def _replayed_steps(
        self,
        session: TxSession,
        actor: Actor,
        task_id: UUID,
        recorded: Sequence[dict[str, Any]] | None,
    ) -> tuple[dict[str, Any], ...]:
        """The Steps a batch created for one Task, re-read by the ids its record kept.

        The reply lists exactly the recorded Steps in creation order, whatever has happened to
        the Task's Steps since, each as it is now (title, position, version), like a replayed
        Task. A recorded Step that is archived, in the trash or gone is left out: the reply
        schema has no flag for it, and listing it as live would mislead. `recorded` is None for
        a record written before Step ids were kept; those fall back to the Task's first
        `MAX_BATCH_STEPS_PER_TASK` live Steps, which is what such a retry returned until now.
        """

        if recorded is None:
            steps = self.store.list_steps(session, actor.user_id, task_id, MAX_BATCH_STEPS_PER_TASK)
        else:
            step_ids = tuple(UUID(str(entry["id"])) for entry in recorded)
            live = self.store.list_live_steps_by_ids(session, actor.user_id, step_ids)
            steps = [live[step_id] for step_id in step_ids if step_id in live]
        return tuple(
            {
                "id": str(step.id),
                "title": step.title,
                "position": step.position,
                "version": step.version,
            }
            for step in steps
        )

    def _create_batch_item(
        self,
        session: TxSession,
        actor: Actor,
        item: NewTaskItem,
        project_id: UUID | None,
        domain_id: UUID | None,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        task_data = self._create(
            session,
            actor,
            {
                "title": item.title,
                "project_id": str(project_id) if project_id else None,
                "domain_id": str(domain_id) if domain_id else None,
                "process_id": None,
                "description": None,
                "priority": item.priority.value,
                "due_at": item.due_at,
                "not_before": None,
                "estimated_minutes": None,
                "blocked_reminder_cadence": None,
                "blocked_reminder_snoozed_until": None,
                "recurrence": None,
                "tags": list(item.tags),
            },
            correlation_id,
        )
        # Flush so each Step row can reference its Task, as process-run materialisation does.
        session.flush()
        task_id = UUID(str(task_data["id"]))
        now = self.clock.now()
        steps: list[dict[str, Any]] = []
        for position, title in enumerate(item.step_titles):
            step = Step(
                new_uuid7(),
                actor.user_id,
                task_id,
                title,
                TaskStatus.TODO,
                position,
                None,
                False,
                now,
                now,
            )
            self.store.save_step(session, step)
            steps.append(
                {"id": str(step.id), "title": title, "position": position, "version": step.version}
            )
        return {"task": task_data, "steps": steps}

    def history(self, actor: Actor, task_id: UUID, *, limit: int = 100) -> list[TaskStatusHistory]:
        actor.require("tasks:read")
        if not 1 <= limit <= 100:
            raise InvalidInputError("history limit must be between 1 and 100")
        return self.store.transaction(
            lambda session: self.store.list_task_status_history(
                session, actor.user_id, task_id, limit
            )
        )

    def _record_status_transition(
        self,
        session: TxSession,
        actor: Actor,
        before: Task,
        after: Task,
        changed_at: datetime,
        *,
        source: str,
    ) -> None:
        if (
            after.recurrence is not None
            and before.status is not TaskStatus.COMPLETED
            and after.last_completed_at == changed_at
            and before.last_completed_at != after.last_completed_at
        ):
            # A recurring completion is represented as two visible lifecycle events,
            # even though the row is immediately reopened for its next occurrence.
            self.store.append_task_status_history(
                session,
                owner_id=actor.user_id,
                task_id=after.id,
                from_status=before.status,
                to_status=TaskStatus.COMPLETED,
                changed_at=changed_at,
                source="recurrence_completed",
            )
            self.store.append_task_status_history(
                session,
                owner_id=actor.user_id,
                task_id=after.id,
                from_status=TaskStatus.COMPLETED,
                to_status=TaskStatus.TODO,
                changed_at=changed_at,
                source="recurrence_next_occurrence",
            )
            return
        if before.status is after.status:
            return
        self.store.append_task_status_history(
            session,
            owner_id=actor.user_id,
            task_id=after.id,
            from_status=before.status,
            to_status=after.status,
            changed_at=changed_at,
            source=source,
        )

    def complete(
        self,
        actor: Actor,
        task_id: UUID,
        *,
        version: int,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> Task:
        actor.require("tasks:write")
        payload = {"task_id": str(task_id), "version": version}

        def operation(session: TxSession) -> Task:
            result = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="complete_task",
                key=idempotency_key,
                payload=payload,
                execute=lambda: self._complete(session, actor, task_id, version, correlation_id),
                replay=id_replay_record,
            )
            return self._replayed_task(session, actor, result)

        return self.store.transaction(operation)

    def reorder_board_column(
        self,
        actor: Actor,
        status: TaskStatus,
        *,
        items: Sequence[tuple[UUID, int]],
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> Sequence[BoardPlacement]:
        """Persist a complete manual order for one owner-scoped board column."""

        actor.require("tasks:write")
        if not items:
            raise ValidationError("board reorder must contain at least one task")
        if len(items) > MAX_BOARD_COLUMN_REORDER:
            raise ValidationError("board reorder exceeds the supported item count")
        if len({item_id for item_id, _ in items}) != len(items):
            raise ValidationError("board reorder must list every task exactly once")

        def operation(session: TxSession) -> dict[str, Any]:
            current = self.store.list_board_column_tasks(
                session, actor.user_id, status, MAX_BOARD_COLUMN_REORDER + 1
            )
            if len(current) > MAX_BOARD_COLUMN_REORDER:
                raise ValidationError("board column is too large to reorder")
            if {task.id for task in current} != {item_id for item_id, _ in items}:
                raise ValidationError("board reorder must include every active task exactly once")
            by_id = {task.id: task for task in current}
            placements: list[dict[str, Any]] = []
            for position, (item_id, version) in enumerate(items, start=1):
                task = by_id[item_id]
                if task.version != version:
                    raise ConflictError("stale task board order")
                ranked = task.rank_on_board(position=position, now=self.clock.now())
                if ranked is not task:
                    self.store.save_task(session, ranked, expected_version=version)
                placements.append(
                    {
                        "task_id": str(ranked.id),
                        "board_rank": position,
                        "version": ranked.version,
                    }
                )
            # Content-free: the event names the owner and the correlation id only. No task id,
            # title or column contents are copied into the audit row. It sits inside the
            # idempotent `execute`, so a replay returns the record without a second event.
            self.store.append_audit(
                session,
                actor_id=actor.user_id,
                event="task.board_reordered",
                outcome="success",
                target_type="task_board",
                correlation_id=correlation_id,
            )
            return {"items": placements}

        result = self.store.transaction(
            lambda session: self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="reorder_board_column",
                key=idempotency_key,
                payload={
                    "status": status.value,
                    "items": [[str(item_id), version] for item_id, version in items],
                },
                execute=lambda: operation(session),
            )
        )
        return [
            BoardPlacement(UUID(item["task_id"]), item["board_rank"], item["version"])
            for item in result["items"]
        ]

    def _complete(
        self,
        session: TxSession,
        actor: Actor,
        task_id: UUID,
        version: int,
        correlation_id: str | None,
        actor_type: str = "user",
    ) -> dict[str, Any]:
        task = self.store.get_task(session, actor.user_id, task_id)
        # Checked before the already-completed shortcut: a stale caller must learn that the
        # Task changed since it read it, not receive a silent success.
        if task.version != version:
            raise self._stale(task)
        now = self.clock.now()
        completed = task.complete(now=now, zone=self.owner_timezone)
        if completed is not task:
            self.store.save_task(session, completed, expected_version=version)
            self._record_status_transition(session, actor, task, completed, now, source="completed")
            self.store.append_audit(
                session,
                actor_id=actor.user_id,
                event="task.completed",
                outcome="success",
                target_type="task",
                target_id=task.id,
                correlation_id=correlation_id,
            )
            if self.activity_ledger is not None:
                self.activity_ledger.record_task(
                    session,
                    task=completed,
                    before=task,
                    operation="complete_task",
                    actor_id=actor.user_id,
                    actor_type=actor_type,
                    occurred_at=now,
                    correlation_id=correlation_id,
                    changed_fields=frozenset({"status"}),
                )
        return task_to_data(completed)

    @staticmethod
    def _stale(task: Task) -> ConflictError:
        return ConflictError(
            "stale task version",
            reason="stale_version",
            subject=task.title,
            subject_kind="task",
        )

    def _archive(
        self,
        session: TxSession,
        actor: Actor,
        task_id: UUID,
        version: int,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        task = self.store.get_task(session, actor.user_id, task_id, include_archived=True)
        if task.version != version:
            raise self._stale(task)
        archived = task.archive(now=self.clock.now())
        if archived is not task:
            self.store.save_task(session, archived, expected_version=version)
            self.store.append_audit(
                session,
                actor_id=actor.user_id,
                event="task.archived",
                outcome="success",
                target_type="task",
                target_id=task.id,
                correlation_id=correlation_id,
            )
        return task_to_data(archived)

    def _restore(
        self,
        session: TxSession,
        actor: Actor,
        task_id: UUID,
        version: int,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        task = self.store.get_task(session, actor.user_id, task_id, include_archived=True)
        if task.version != version:
            raise self._stale(task)
        restored = task.restore(now=self.clock.now())
        if restored is not task:
            self.store.save_task(session, restored, expected_version=version)
            self.store.append_audit(
                session,
                actor_id=actor.user_id,
                event="task.restored",
                outcome="success",
                target_type="task",
                target_id=task.id,
                correlation_id=correlation_id,
            )
        return task_to_data(restored)


def task_batch_replay_record(result: dict[str, Any]) -> dict[str, Any]:
    """Idempotency projection of a created batch: Task ids and Step ids; the rest is re-read.

    Records written before Step ids were kept have no `steps` key per entry; the replay reads
    those with a fallback (see `TaskService._replayed_steps`).
    """

    return {
        "tasks": [
            {
                "task": {"id": entry["task"]["id"]},
                "steps": [{"id": step["id"]} for step in entry["steps"]],
            }
            for entry in result["tasks"]
        ]
    }


def _recurrence_rule(value: RecurrenceRule | dict[str, Any] | None) -> RecurrenceRule | None:
    """A command's recurrence as a domain rule: a rule stays, a dict is validated, null clears."""

    return value if isinstance(value, RecurrenceRule) else RecurrenceRule.from_data(value)


def task_to_data(task: Task) -> dict[str, Any]:
    return {
        "id": str(task.id),
        "owner_id": str(task.owner_id),
        "project_id": str(task.project_id) if task.project_id else None,
        "domain_id": str(task.domain_id) if task.domain_id else None,
        "process_id": str(task.process_id) if task.process_id else None,
        "derived_domain_id": str(task.derived_domain_id) if task.derived_domain_id else None,
        "attention_requested": task.attention_requested,
        "title": task.title,
        "description": task.description,
        "status": task.status.value,
        "priority": task.priority.value,
        "due_at": task.due_at.isoformat() if task.due_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
        "version": task.version,
        "archived_at": task.archived_at.isoformat() if task.archived_at else None,
        "not_before": task.not_before.isoformat() if task.not_before else None,
        "estimated_minutes": task.estimated_minutes,
        "waiting_since": task.waiting_since.isoformat() if task.waiting_since else None,
        "follow_up_at": task.follow_up_at.isoformat() if task.follow_up_at else None,
        "waiting_on_contact_id": (
            str(task.waiting_on_contact_id) if task.waiting_on_contact_id else None
        ),
        "blocked_reminder_cadence": (
            task.blocked_reminder_cadence.value if task.blocked_reminder_cadence else None
        ),
        "blocked_reminder_snoozed_until": (
            task.blocked_reminder_snoozed_until.isoformat()
            if task.blocked_reminder_snoozed_until
            else None
        ),
        "blocked_last_reminded_at": (
            task.blocked_last_reminded_at.isoformat() if task.blocked_last_reminded_at else None
        ),
        "recurrence": task.recurrence.to_data() if task.recurrence else None,
        "last_completed_at": (
            task.last_completed_at.isoformat() if task.last_completed_at else None
        ),
    }


def task_public_data(task: Task) -> dict[str, Any]:
    """Serialize the public contract without internal ownership fields."""

    data = task_to_data(task)
    data.pop("owner_id")
    return data
