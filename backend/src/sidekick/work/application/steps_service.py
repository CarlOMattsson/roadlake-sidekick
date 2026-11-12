"""Step and Action use cases; Actions are intentionally Step-scoped."""

from dataclasses import replace
from datetime import datetime
from typing import Any, Protocol, TypeVar
from uuid import UUID

from sidekick.shared.errors import ConflictError, InvalidInputError
from sidekick.shared.replay import id_replay_record, items_replay_record
from sidekick.shared.types import (
    UNSET,
    Actor,
    AuditingStore,
    Clock,
    CursorCodec,
    IdempotentStore,
    Page,
    TransactionalStore,
    TxSession,
    UnsetType,
    new_uuid7,
)
from sidekick.tasks.domain import Task, TaskStatus
from sidekick.work.domain import Action, ActionStatus, Step

T = TypeVar("T")

# The most active Steps one reorder call covers. Creation does not cap Steps per Task, so a Task
# above this has to be trimmed (archive or trash) before it can be reordered as a whole.
MAX_REORDER_STEPS = 1000


class StepsStore(TransactionalStore, IdempotentStore, AuditingStore, Protocol):
    def get_task(self, session: TxSession, owner_id: UUID, task_id: UUID) -> Task: ...
    def list_steps(
        self,
        session: TxSession,
        owner_id: UUID,
        task_id: UUID,
        limit: int,
        offset: int = 0,
        *,
        after: tuple[int, UUID] | None = None,
    ) -> list[Step]: ...
    def save_step(
        self, session: TxSession, step: Step, expected_version: int | None = None
    ) -> None: ...
    def list_actions(
        self,
        session: TxSession,
        owner_id: UUID,
        step_id: UUID,
        limit: int,
        offset: int = 0,
        *,
        after: tuple[int, UUID] | None = None,
    ) -> list[Action]: ...
    def save_action(
        self, session: TxSession, action: Action, expected_version: int | None = None
    ) -> None: ...
    def get_action(self, session: TxSession, owner_id: UUID, action_id: UUID) -> Action: ...
    def get_step(self, session: TxSession, owner_id: UUID, step_id: UUID) -> Step: ...
    def lock_step_order(self, session: TxSession, owner_id: UUID, task_id: UUID) -> None: ...
    def next_step_position(self, session: TxSession, owner_id: UUID, task_id: UUID) -> int: ...
    def lock_action_order(self, session: TxSession, owner_id: UUID, step_id: UUID) -> None: ...
    def next_action_position(self, session: TxSession, owner_id: UUID, step_id: UUID) -> int: ...


class StepsService:
    def __init__(self, store: StepsStore, clock: Clock, cursor_codec: CursorCodec) -> None:
        self.store = store
        self.clock = clock
        self.cursor_codec = cursor_codec

    def _audit(
        self,
        session: TxSession,
        actor: Actor,
        event: str,
        target_type: str,
        target_id: UUID,
        correlation_id: str | None,
    ) -> None:
        """One content-free audit event: names, ids and the correlation id, never titles or notes.

        Callers sit inside the idempotent `execute`, so a replay records no second event.
        """

        self.store.append_audit(
            session,
            actor_id=actor.user_id,
            event=event,
            outcome="success",
            target_type=target_type,
            target_id=target_id,
            correlation_id=correlation_id,
        )

    def _replayed_step(self, session: TxSession, actor: Actor, record: dict[str, Any]) -> Step:
        """The Step a (possibly replayed) write refers to, re-read by id.

        The idempotency record keeps only the id, so a retry returns the Step as it is now.
        """

        return self.store.get_step(session, actor.user_id, UUID(str(record["id"])))

    def _replayed_action(self, session: TxSession, actor: Actor, record: dict[str, Any]) -> Action:
        """The Action a (possibly replayed) write refers to, re-read by id."""

        return self.store.get_action(session, actor.user_id, UUID(str(record["id"])))

    def list_steps(
        self, actor: Actor, task_id: UUID, *, limit: int = 100, cursor: str | None = None
    ) -> Page[Step]:
        """Continue active Steps in position/id order; a reorder invalidates what was read."""

        actor.require("tasks:read")
        if not 1 <= limit <= 100:
            raise InvalidInputError("limit must be between 1 and 100")
        query_key = f"steps:v1:task={task_id}"
        after = self._decode_position(actor, cursor, query_key)
        rows = self.store.transaction(
            lambda s: self.store.list_steps(s, actor.user_id, task_id, limit + 1, after=after)
        )
        return self._page(actor, rows, limit, query_key)

    def get_step(self, actor: Actor, step_id: UUID) -> Step:
        actor.require("tasks:read")
        return self.store.transaction(lambda s: self.store.get_step(s, actor.user_id, step_id))

    def create_step(
        self,
        actor: Actor,
        task_id: UUID,
        *,
        title: str,
        due_at: datetime | None = None,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> Step:
        actor.require("tasks:write")

        def operation(session: TxSession) -> dict[str, Any]:
            return self._create_step(
                session, actor, task_id, title=title, due_at=due_at, correlation_id=correlation_id
            )

        return self.store.transaction(
            lambda s: self._replayed_step(
                s,
                actor,
                self.store.idempotent(
                    s,
                    actor_id=actor.user_id,
                    operation="create_step",
                    key=idempotency_key,
                    payload={"task_id": str(task_id), "title": title, "due_at": due_at},
                    execute=lambda: operation(s),
                    replay=id_replay_record,
                ),
            )
        )

    def _create_step(
        self,
        session: TxSession,
        actor: Actor,
        task_id: UUID,
        *,
        title: str,
        due_at: datetime | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        task = self.store.get_task(session, actor.user_id, task_id)
        self.store.lock_step_order(session, actor.user_id, task.id)
        position = self.store.next_step_position(session, actor.user_id, task.id)
        now = self.clock.now()
        step = Step(
            new_uuid7(),
            actor.user_id,
            task.id,
            title,
            TaskStatus.TODO,
            position,
            due_at,
            False,
            now,
            now,
        )
        self.store.save_step(session, step)
        self._audit(session, actor, "step.created", "step", step.id, correlation_id)
        return _step_result(step)

    def list_actions(
        self, actor: Actor, step_id: UUID, *, limit: int = 100, cursor: str | None = None
    ) -> Page[Action]:
        """Continue active Actions in position/id order; a reorder invalidates what was read."""

        actor.require("tasks:read")
        if not 1 <= limit <= 100:
            raise InvalidInputError("limit must be between 1 and 100")
        query_key = f"actions:v1:step={step_id}"
        after = self._decode_position(actor, cursor, query_key)
        rows = self.store.transaction(
            lambda s: self.store.list_actions(s, actor.user_id, step_id, limit + 1, after=after)
        )
        return self._page(actor, rows, limit, query_key)

    def _decode_position(
        self, actor: Actor, cursor: str | None, query_key: str
    ) -> tuple[int, UUID] | None:
        try:
            token = self.cursor_codec.decode_position(actor.user_id, cursor, query_key)
            if token is None:
                return None
            position, record_id = token.split(":")
            if int(position) < 0:
                raise ValueError
            return int(position), UUID(record_id)
        except ValueError as error:
            raise InvalidInputError("invalid pagination cursor") from error

    def _page[Item: (Step, Action)](
        self, actor: Actor, rows: list[Item], limit: int, query_key: str
    ) -> Page[Item]:
        items = rows[:limit]
        next_cursor = (
            self.cursor_codec.encode_position(
                actor.user_id, f"{items[-1].position}:{items[-1].id}", query_key
            )
            if len(rows) > limit
            else None
        )
        return Page(items, next_cursor)

    def get_action(self, actor: Actor, action_id: UUID) -> Action:
        actor.require("tasks:read")
        return self.store.transaction(lambda s: self.store.get_action(s, actor.user_id, action_id))

    def create_action(
        self,
        actor: Actor,
        step_id: UUID,
        *,
        title: str,
        due_at: datetime | None = None,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> Action:
        actor.require("tasks:write")

        def operation(session: TxSession) -> dict[str, Any]:
            return self._create_action(
                session, actor, step_id, title=title, due_at=due_at, correlation_id=correlation_id
            )

        return self.store.transaction(
            lambda s: self._replayed_action(
                s,
                actor,
                self.store.idempotent(
                    s,
                    actor_id=actor.user_id,
                    operation="create_action",
                    key=idempotency_key,
                    payload={"step_id": str(step_id), "title": title, "due_at": due_at},
                    execute=lambda: operation(s),
                    replay=id_replay_record,
                ),
            )
        )

    def _create_action(
        self,
        session: TxSession,
        actor: Actor,
        step_id: UUID,
        *,
        title: str,
        due_at: datetime | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        self.store.get_step(session, actor.user_id, step_id)
        self.store.lock_action_order(session, actor.user_id, step_id)
        position = self.store.next_action_position(session, actor.user_id, step_id)
        now = self.clock.now()
        action = Action(
            new_uuid7(),
            actor.user_id,
            step_id,
            title,
            ActionStatus.OPEN,
            position,
            due_at,
            False,
            now,
            now,
        )
        self.store.save_action(session, action)
        self._audit(session, actor, "action.created", "action", action.id, correlation_id)
        return _action_result(action)

    def complete_action(
        self,
        actor: Actor,
        action_id: UUID,
        *,
        version: int,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> Action:
        actor.require("tasks:write")

        def operation(session: TxSession) -> dict[str, Any]:
            action = self.store.get_action(session, actor.user_id, action_id)
            updated = action.complete(now=self.clock.now())
            self.store.save_action(session, updated, expected_version=version)
            self._audit(session, actor, "action.completed", "action", action_id, correlation_id)
            return _action_result(updated)

        return self.store.transaction(
            lambda s: self._replayed_action(
                s,
                actor,
                self.store.idempotent(
                    s,
                    actor_id=actor.user_id,
                    operation="complete_action",
                    key=idempotency_key,
                    payload={"action_id": str(action_id), "version": version},
                    execute=lambda: operation(s),
                    replay=id_replay_record,
                ),
            )
        )

    def update_step(
        self,
        actor: Actor,
        step_id: UUID,
        *,
        version: int,
        idempotency_key: str,
        title: str | UnsetType = UNSET,
        status: TaskStatus | UnsetType = UNSET,
        due_at: datetime | None | UnsetType = UNSET,
        attention_requested: bool | UnsetType = UNSET,
        instruction: str | None | UnsetType = UNSET,
        only_if_status: TaskStatus | None = None,
        correlation_id: str | None = None,
    ) -> Step:
        """Update one Step under optimistic concurrency and an idempotency key.

        `only_if_status` guards the Step's current status inside the write's own transaction (the
        companion's reopen is only for a completed Step); it runs only when the key is not a
        replay, so a replay still answers with the stored result.
        """

        actor.require("tasks:write")

        def operation(session: TxSession) -> dict[str, Any]:
            current = self.store.get_step(session, actor.user_id, step_id)
            if only_if_status is not None and current.status is not only_if_status:
                raise ConflictError("step is not in the required status", reason="not_completed")
            updated = current.update(
                now=self.clock.now(),
                title=title,
                status=status,
                due_at=due_at,
                attention_requested=attention_requested,
                instruction=instruction,
            )
            self.store.save_step(session, updated, expected_version=version)
            self._audit(session, actor, "step.updated", "step", step_id, correlation_id)
            return _step_result(updated)

        return self.store.transaction(
            lambda s: self._replayed_step(
                s,
                actor,
                self.store.idempotent(
                    s,
                    actor_id=actor.user_id,
                    operation="update_step",
                    key=idempotency_key,
                    payload={
                        "step_id": str(step_id),
                        "version": version,
                        "title": title,
                        "status": status,
                        "due_at": due_at,
                        "attention_requested": attention_requested,
                        "instruction": instruction,
                    },
                    execute=lambda: operation(s),
                    replay=id_replay_record,
                ),
            )
        )

    def complete_step(
        self,
        actor: Actor,
        step_id: UUID,
        *,
        version: int,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> Step:
        actor.require("tasks:write")

        def operation(session: TxSession) -> dict[str, Any]:
            current = self.store.get_step(session, actor.user_id, step_id)
            updated = current.complete(now=self.clock.now())
            self.store.save_step(session, updated, expected_version=version)
            self._audit(session, actor, "step.completed", "step", step_id, correlation_id)
            return _step_result(updated)

        return self.store.transaction(
            lambda s: self._replayed_step(
                s,
                actor,
                self.store.idempotent(
                    s,
                    actor_id=actor.user_id,
                    operation="complete_step",
                    key=idempotency_key,
                    payload={"step_id": str(step_id), "version": version},
                    execute=lambda: operation(s),
                    replay=id_replay_record,
                ),
            )
        )

    def update_action(
        self,
        actor: Actor,
        action_id: UUID,
        *,
        version: int,
        idempotency_key: str,
        title: str | UnsetType = UNSET,
        due_at: datetime | None | UnsetType = UNSET,
        attention_requested: bool | UnsetType = UNSET,
        note: str | None | UnsetType = UNSET,
        correlation_id: str | None = None,
    ) -> Action:
        actor.require("tasks:write")

        def operation(session: TxSession) -> dict[str, Any]:
            current = self.store.get_action(session, actor.user_id, action_id)
            updated = current.update(
                now=self.clock.now(),
                title=title,
                due_at=due_at,
                attention_requested=attention_requested,
                note=note,
            )
            self.store.save_action(session, updated, expected_version=version)
            self._audit(session, actor, "action.updated", "action", action_id, correlation_id)
            return _action_result(updated)

        return self.store.transaction(
            lambda s: self._replayed_action(
                s,
                actor,
                self.store.idempotent(
                    s,
                    actor_id=actor.user_id,
                    operation="update_action",
                    key=idempotency_key,
                    payload={
                        "action_id": str(action_id),
                        "version": version,
                        "title": title,
                        "due_at": due_at,
                        "attention_requested": attention_requested,
                        "note": note,
                    },
                    execute=lambda: operation(s),
                    replay=id_replay_record,
                ),
            )
        )

    def archive_step(
        self,
        actor: Actor,
        step_id: UUID,
        *,
        version: int,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> Step:
        return self._set_step_archive(
            actor,
            step_id,
            version=version,
            archived=True,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    def restore_step(
        self,
        actor: Actor,
        step_id: UUID,
        *,
        version: int,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> Step:
        return self._set_step_archive(
            actor,
            step_id,
            version=version,
            archived=False,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    def _set_step_archive(
        self,
        actor: Actor,
        step_id: UUID,
        *,
        version: int,
        archived: bool,
        idempotency_key: str,
        correlation_id: str | None,
    ) -> Step:
        actor.require("tasks:write")

        def operation(session: TxSession) -> dict[str, Any]:
            return self._archive_step_data(
                session,
                actor,
                step_id,
                version,
                archived=archived,
                correlation_id=correlation_id,
            )

        return self.store.transaction(
            lambda s: self._replayed_step(
                s,
                actor,
                self.store.idempotent(
                    s,
                    actor_id=actor.user_id,
                    operation="archive_step" if archived else "restore_step",
                    key=idempotency_key,
                    payload={"step_id": str(step_id), "version": version},
                    execute=lambda: operation(s),
                    replay=id_replay_record,
                ),
            )
        )

    def _archive_step(
        self,
        session: TxSession,
        actor: Actor,
        step_id: UUID,
        version: int,
        correlation_id: str | None = None,
    ) -> Step:
        """Session-taking primitive for cross-service composition (revert, batch apply).

        Callers are responsible for their own `Actor.require` and idempotency: the
        equivalent of `TaskService._archive` and `ContactService._archive`, kept
        private because this class's public surface is the reviewed HTTP/MCP contract.
        """

        return _step_from_data(
            self._archive_step_data(
                session,
                actor,
                step_id,
                version,
                archived=True,
                correlation_id=correlation_id,
            )
        )

    def _archive_step_data(
        self,
        session: TxSession,
        actor: Actor,
        step_id: UUID,
        version: int,
        *,
        archived: bool,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        current = self.store.get_step(session, actor.user_id, step_id)
        updated = (current.archive if archived else current.restore)(now=self.clock.now())
        if not archived and updated is not current:
            # Renumbering while it was hidden may have given its position to a live Step.
            self.store.lock_step_order(session, actor.user_id, current.task_id)
            taken = {
                step.position
                for step in self.store.list_steps(session, actor.user_id, current.task_id, 1000)
            }
            if updated.position in taken:
                updated = replace(
                    updated,
                    position=self.store.next_step_position(session, actor.user_id, current.task_id),
                )
        self.store.save_step(session, updated, expected_version=version)
        if updated is not current:
            self.store.append_audit(
                session,
                actor_id=actor.user_id,
                event="step.archived" if archived else "step.restored",
                outcome="success",
                target_type="step",
                target_id=step_id,
                correlation_id=correlation_id,
            )
        return _step_result(updated)

    def archive_action(
        self,
        actor: Actor,
        action_id: UUID,
        *,
        version: int,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> Action:
        return self._set_action_archive(
            actor,
            action_id,
            version=version,
            archived=True,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    def restore_action(
        self,
        actor: Actor,
        action_id: UUID,
        *,
        version: int,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> Action:
        return self._set_action_archive(
            actor,
            action_id,
            version=version,
            archived=False,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    def _set_action_archive(
        self,
        actor: Actor,
        action_id: UUID,
        *,
        version: int,
        archived: bool,
        idempotency_key: str,
        correlation_id: str | None,
    ) -> Action:
        actor.require("tasks:write")

        def operation(session: TxSession) -> dict[str, Any]:
            return self._archive_action_data(
                session,
                actor,
                action_id,
                version,
                archived=archived,
                correlation_id=correlation_id,
            )

        return self.store.transaction(
            lambda s: self._replayed_action(
                s,
                actor,
                self.store.idempotent(
                    s,
                    actor_id=actor.user_id,
                    operation="archive_action" if archived else "restore_action",
                    key=idempotency_key,
                    payload={"action_id": str(action_id), "version": version},
                    execute=lambda: operation(s),
                    replay=id_replay_record,
                ),
            )
        )

    def _archive_action_data(
        self,
        session: TxSession,
        actor: Actor,
        action_id: UUID,
        version: int,
        *,
        archived: bool,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        current = self.store.get_action(session, actor.user_id, action_id)
        updated = (current.archive if archived else current.restore)(now=self.clock.now())
        if not archived and updated is not current:
            # Renumbering while it was hidden may have given its position to a live Action.
            self.store.lock_action_order(session, actor.user_id, current.step_id)
            taken = {
                action.position
                for action in self.store.list_actions(session, actor.user_id, current.step_id, 1000)
            }
            if updated.position in taken:
                updated = replace(
                    updated,
                    position=self.store.next_action_position(
                        session, actor.user_id, current.step_id
                    ),
                )
        self.store.save_action(session, updated, expected_version=version)
        if updated is not current:
            self.store.append_audit(
                session,
                actor_id=actor.user_id,
                event="action.archived" if archived else "action.restored",
                outcome="success",
                target_type="action",
                target_id=action_id,
                correlation_id=correlation_id,
            )
        return _action_result(updated)

    def reorder_steps(
        self,
        actor: Actor,
        task_id: UUID,
        *,
        items: list[tuple[UUID, int]],
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> Page[Step]:
        actor.require("tasks:write")

        def operation(session: TxSession) -> dict[str, Any]:
            self.store.lock_step_order(session, actor.user_id, task_id)
            current = self.store.list_steps(session, actor.user_id, task_id, MAX_REORDER_STEPS + 1)
            if len(current) > MAX_REORDER_STEPS:
                raise InvalidInputError("task has too many active steps to reorder in one call")
            if {item.id for item in current} != {item_id for item_id, _ in items}:
                raise InvalidInputError("reorder must include every active step exactly once")
            by_id = {item.id: item for item in current}
            updated: list[dict[str, Any]] = []
            for position, (item_id, version) in enumerate(items):
                item = by_id[item_id]
                if item.version != version:
                    raise ConflictError("stale step ordering")
                changed = item.move(position=position, now=self.clock.now())
                self.store.save_step(session, changed, expected_version=version)
                updated.append(_step_result(changed))
            self._audit(session, actor, "steps.reordered", "task", task_id, correlation_id)
            return {"items": updated}

        def replayed(session: TxSession) -> Page[Step]:
            result = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="reorder_steps",
                key=idempotency_key,
                payload={"task_id": str(task_id), "items": [[str(i), v] for i, v in items]},
                execute=lambda: operation(session),
                replay=items_replay_record,
            )
            return Page(
                [self._replayed_step(session, actor, item) for item in result["items"]], None
            )

        return self.store.transaction(replayed)

    def reorder_actions(
        self,
        actor: Actor,
        step_id: UUID,
        *,
        items: list[tuple[UUID, int]],
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> Page[Action]:
        actor.require("tasks:write")

        def operation(session: TxSession) -> dict[str, Any]:
            self.store.lock_action_order(session, actor.user_id, step_id)
            current = self.store.list_actions(session, actor.user_id, step_id, 100)
            if {item.id for item in current} != {item_id for item_id, _ in items}:
                raise InvalidInputError("reorder must include every active action exactly once")
            by_id = {item.id: item for item in current}
            updated: list[dict[str, Any]] = []
            for position, (item_id, version) in enumerate(items):
                item = by_id[item_id]
                if item.version != version:
                    raise ConflictError("stale action ordering")
                changed = item.move(position=position, now=self.clock.now())
                self.store.save_action(session, changed, expected_version=version)
                updated.append(_action_result(changed))
            self._audit(session, actor, "actions.reordered", "step", step_id, correlation_id)
            return {"items": updated}

        def replayed(session: TxSession) -> Page[Action]:
            result = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="reorder_actions",
                key=idempotency_key,
                payload={"step_id": str(step_id), "items": [[str(i), v] for i, v in items]},
                execute=lambda: operation(session),
                replay=items_replay_record,
            )
            return Page(
                [self._replayed_action(session, actor, item) for item in result["items"]], None
            )

        return self.store.transaction(replayed)


def _step_result(item: Step) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "owner_id": str(item.owner_id),
        "task_id": str(item.task_id),
        "title": item.title,
        "status": item.status.value,
        "position": item.position,
        "due_at": item.due_at.isoformat() if item.due_at else None,
        "attention_requested": item.attention_requested,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
        "version": item.version,
        "archived_at": item.archived_at.isoformat() if item.archived_at else None,
        "instruction": item.instruction,
        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
    }


def _action_result(item: Action) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "owner_id": str(item.owner_id),
        "step_id": str(item.step_id),
        "title": item.title,
        "status": item.status.value,
        "position": item.position,
        "due_at": item.due_at.isoformat() if item.due_at else None,
        "attention_requested": item.attention_requested,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
        "version": item.version,
        "archived_at": item.archived_at.isoformat() if item.archived_at else None,
        "note": item.note,
    }


def _step_from_data(data: dict[str, Any]) -> Step:
    return Step(
        id=UUID(str(data["id"])),
        owner_id=UUID(str(data["owner_id"])),
        task_id=UUID(str(data["task_id"])),
        title=str(data["title"]),
        status=TaskStatus(str(data["status"])),
        position=int(data["position"]),
        due_at=_datetime(data.get("due_at")),
        attention_requested=bool(data["attention_requested"]),
        created_at=_datetime_required(data["created_at"]),
        updated_at=_datetime_required(data["updated_at"]),
        version=int(data["version"]),
        archived_at=_datetime(data.get("archived_at")),
        instruction=data.get("instruction"),
        completed_at=_datetime(data.get("completed_at")),
    )


def _datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _datetime_required(value: object) -> datetime:
    parsed = _datetime(str(value))
    if parsed is None:
        raise ValueError("required datetime is missing")
    return parsed
