"""The activity ledger and bounded activity-history use cases."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, cast
from uuid import UUID

from sidekick.activity.domain import ActivityCategory, category_for_operation
from sidekick.shared.errors import ValidationError
from sidekick.shared.types import (
    TIMED_KEY,
    Actor,
    CursorCodec,
    IdempotentStore,
    KeyValue,
    Page,
    TransactionalStore,
    TxSession,
    new_uuid7,
    paginate,
    validate_limit,
)
from sidekick.tasks.domain import Task

# A bounded JSON object: keys are text, values are plain JSON values.
JsonObject = dict[str, object]

# Activity entries are read-scoped by the domain that owns their aggregate. An aggregate type
# missing from this map is treated as cross-domain and needs every scope in
# _ACTIVITY_UNMAPPED_SCOPES. `automation_run` is no longer written: it keeps the history of the
# retired automation engine readable.
ACTIVITY_AGGREGATE_SCOPES: dict[str, str] = {
    "task": "tasks:read",
    "automation_run": "tasks:read",
    "process_run": "projects:read",
}
_ACTIVITY_UNMAPPED_SCOPES = frozenset({"tasks:read", "projects:read"})


def _visible_activity_aggregate_types(actor: Actor) -> tuple[str, ...] | None:
    """Mapped aggregate types the actor may read, or None when every type is visible."""
    if actor.scopes >= _ACTIVITY_UNMAPPED_SCOPES:
        return None
    return tuple(
        sorted(
            aggregate_type
            for aggregate_type, scope in ACTIVITY_AGGREGATE_SCOPES.items()
            if scope in actor.scopes
        )
    )


@dataclass(frozen=True, slots=True)
class ActivityEntry:
    id: UUID
    domain_event_id: UUID
    category: str
    source: str
    operation: str
    state: str
    aggregate_type: str
    aggregate_id: UUID
    summary: str
    before_values: JsonObject
    after_values: JsonObject
    evidence: JsonObject
    # Set only on entries the retired automation engine wrote; new entries never carry one.
    policy_mode: str | None
    correlation_id: str | None
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class NewActivity:
    """One ledger event and the activity-history entry projected from it, ready to be stored."""

    event_id: UUID
    entry_id: UUID
    owner_id: UUID
    aggregate_type: str
    aggregate_id: UUID
    aggregate_version: int
    event_type: str
    actor_type: str
    actor_id: UUID | None
    command_id: UUID
    correlation_id: str | None
    payload: JsonObject
    category: str
    operation: str
    summary: str
    before_values: JsonObject
    after_values: JsonObject
    evidence: JsonObject
    occurred_at: datetime


class ActivityWriter(Protocol):
    def append_activity(self, session: TxSession, activity: NewActivity) -> None:
        """Store the ledger event, then its projection, in the open transaction."""
        ...


class ActivityStore(ActivityWriter, TransactionalStore, IdempotentStore, Protocol):
    def activity_entries(
        self,
        session: TxSession,
        owner: UUID,
        *,
        aggregate_types: Sequence[str] | None,
        category: str | None,
        state: str | None,
        after: tuple[KeyValue, ...] | None,
        limit: int,
    ) -> list[ActivityEntry]: ...


def json_safe(value: object, *, max_text: int = 2000) -> object:
    """Turn domain values into bounded JSON without retaining provider internals."""

    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, str):
        return value[:max_text]
    if isinstance(value, Mapping):
        return json_object(cast(Mapping[object, object], value), max_text=max_text)
    if isinstance(value, (list, tuple)):
        return [json_safe(item, max_text=max_text) for item in cast(Sequence[object], value)[:50]]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return str(value)[:max_text]


def json_object[K](value: Mapping[K, object], *, max_text: int = 2000) -> JsonObject:
    """`json_safe` of a mapping, which is always an object."""

    return {str(key): json_safe(item, max_text=max_text) for key, item in value.items()}


class ActivityLedger:
    """Append one authoritative event and its bounded read projection in one transaction."""

    def __init__(self, writer: ActivityWriter) -> None:
        self.writer = writer

    def append(
        self,
        session: TxSession,
        *,
        owner_id: UUID,
        aggregate_type: str,
        aggregate_id: UUID,
        aggregate_version: int,
        event_type: str,
        actor_type: str,
        actor_id: UUID | None,
        operation: str,
        category: ActivityCategory | str,
        summary: str,
        before_values: JsonObject | None = None,
        after_values: JsonObject | None = None,
        evidence: JsonObject | None = None,
        correlation_id: str | None = None,
        occurred_at: datetime,
    ) -> UUID:
        event_id = new_uuid7()
        payload = json_object(
            {
                "operation": operation,
                "before": before_values or {},
                "after": after_values or {},
                "evidence": evidence or {},
            }
        )
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > 30_000:
            raise ValidationError("activity event payload is too large")
        self.writer.append_activity(
            session,
            NewActivity(
                event_id=event_id,
                entry_id=new_uuid7(),
                owner_id=owner_id,
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                aggregate_version=aggregate_version,
                event_type=event_type,
                actor_type=actor_type,
                actor_id=actor_id,
                command_id=new_uuid7(),
                correlation_id=correlation_id,
                payload=payload,
                category=category.value if isinstance(category, StrEnum) else str(category),
                operation=operation,
                summary=summary[:300],
                before_values=json_object(before_values or {}, max_text=1000),
                after_values=json_object(after_values or {}, max_text=1000),
                evidence=json_object(evidence or {}, max_text=1000),
                occurred_at=occurred_at,
            ),
        )
        return event_id

    def record_task(
        self,
        session: TxSession,
        *,
        task: Task,
        operation: str,
        actor_id: UUID,
        actor_type: str,
        occurred_at: datetime,
        before: Task | None = None,
        correlation_id: str | None = None,
        changed_fields: frozenset[str] | None = None,
    ) -> UUID:
        """Record a Task command after its projection has passed optimistic locking."""

        def values(item: Task | None) -> JsonObject:
            if item is None:
                return {}
            return {
                "title": item.title,
                "description": item.description,
                "status": item.status,
                "priority": item.priority,
                "due_at": item.due_at,
                "project_id": item.project_id,
                "domain_id": item.domain_id,
                "process_id": item.process_id,
                "version": item.version,
                "archived_at": item.archived_at,
            }

        category = category_for_operation(operation, changed_fields)
        return self.append(
            session,
            owner_id=task.owner_id,
            aggregate_type="task",
            aggregate_id=task.id,
            aggregate_version=task.version,
            event_type=f"task.{operation.removeprefix('task_')}",
            actor_type=actor_type,
            actor_id=actor_id,
            operation=operation,
            category=category,
            summary=f"{operation.replace('_', ' ').capitalize()}: {task.title}",
            before_values=values(before),
            after_values=values(task),
            correlation_id=correlation_id,
            occurred_at=occurred_at,
        )


class ActivityService:
    def __init__(self, store: ActivityStore, cursor_codec: CursorCodec) -> None:
        self.store = store
        self.cursor_codec = cursor_codec

    def list_activity(
        self,
        actor: Actor,
        *,
        limit: int = 50,
        cursor: str | None = None,
        category: str | None = None,
        state: str | None = None,
    ) -> Page[ActivityEntry]:
        actor.require("tasks:read")
        validate_limit(limit, maximum=100, error=ValidationError)
        visible_types = _visible_activity_aggregate_types(actor)
        visible_key = "*" if visible_types is None else ",".join(visible_types) or "-"
        query_key = (
            f"activity:v1:category={category or '*'}:state={state or '*'}:types={visible_key}"
        )
        after = self.cursor_codec.decode_keyset(actor.user_id, cursor, query_key, kinds=TIMED_KEY)

        def operation(session: TxSession) -> list[ActivityEntry]:
            return self.store.activity_entries(
                session,
                actor.user_id,
                aggregate_types=visible_types,
                category=category,
                state=state,
                after=after,
                limit=limit + 1,
            )

        items = self.store.transaction(operation)
        return Page(
            *paginate(
                items,
                limit,
                lambda last: self.cursor_codec.encode_keyset(
                    actor.user_id, (last.occurred_at, last.id), query_key
                ),
            )
        )
