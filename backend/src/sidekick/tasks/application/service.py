"""Transport-neutral Task commands and queries."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, tzinfo
from typing import Any
from uuid import UUID

from sidekick.shared.config import DEFAULT_OWNER_TIMEZONE, parse_owner_timezone
from sidekick.shared.errors import ConflictError, InvalidInputError
from sidekick.shared.replay import id_replay_record
from sidekick.shared.types import (
    TIMED_KEY,
    UNSET,
    Actor,
    Clock,
    CursorCodec,
    Page,
    TxSession,
    UnsetType,
    new_uuid7,
)
from sidekick.tasks.application.models import TaskDetailRead, UpdateTaskCommand
from sidekick.tasks.application.serialization import task_to_data
from sidekick.tasks.application.store import TaskStore
from sidekick.tasks.domain import (
    Priority,
    RecurrenceRule,
    Task,
    TaskActivityRecorder,
    TaskStatus,
    TaskStatusHistory,
    derive_domain_id,
)
from sidekick.work.domain.planning import Cadence, parse_cadence
from sidekick.work.domain.tag_assignment import apply_record_tags

DEFAULT_OWNER_ZONE = parse_owner_timezone(DEFAULT_OWNER_TIMEZONE)


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

    def replayed_tasks(
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
                execute=lambda: self.update_in_session(
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

    def update_in_session(
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
        """Update a Task inside the caller's open transaction and return its serialized result.

        The body of `update`, also run per item by the bulk reschedule.
        """

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
            project_id = _require_uuid(project_id)
            self.store.get_project(session, actor.user_id, project_id)
        if "domain_id" in changes and changes["domain_id"] is not None:
            domain_id = changes["domain_id"]
            domain_id = _require_uuid(domain_id)
            self.store.get_domain(session, actor.user_id, domain_id)
        if "process_id" in changes and changes["process_id"] is not None:
            process_id = changes["process_id"]
            process_id = _require_uuid(process_id)
            self.store.get_process(session, actor.user_id, process_id)
        if "waiting_on_contact_id" in changes and changes["waiting_on_contact_id"] is not None:
            contact_id = changes["waiting_on_contact_id"]
            contact_id = _require_uuid(contact_id)
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
            tags = command.tags
            if isinstance(tags, UnsetType):
                raise RuntimeError("tags_changed without tags")
            apply_record_tags(
                self.store,
                session,
                owner_id=actor.user_id,
                kind="task",
                record_id=task_id,
                values=tags,
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


def _require_uuid(value: object) -> UUID:
    if not isinstance(value, UUID):
        raise TypeError(f"expected a UUID, got {type(value).__name__}")
    return value


def _recurrence_rule(value: RecurrenceRule | dict[str, Any] | None) -> RecurrenceRule | None:
    """A command's recurrence as a domain rule: a rule stays, a dict is validated, null clears."""

    return value if isinstance(value, RecurrenceRule) else RecurrenceRule.from_data(value)
