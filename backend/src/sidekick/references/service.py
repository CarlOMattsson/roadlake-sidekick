"""External reference use cases shared by HTTP and MCP.

Logs, spans, metrics and audit rows carry operation names and identifiers only: never a
title, link, account or provider-side identity.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from typing import Any, Protocol, cast
from uuid import UUID, uuid4

from sidekick.references.domain import MAX_REFERENCES_PER_TASK, SOURCES, ExternalReferenceDetails
from sidekick.references.persistence import ExternalReferenceRow, TaskExternalReferenceRow
from sidekick.references.schemas import (
    Kind,
    LinkResult,
    Provider,
    ReferencePage,
    ReferenceRecord,
    Source,
    UnlinkResult,
)
from sidekick.shared.errors import ConflictError, NotFoundError, ValidationError
from sidekick.shared.idempotent_operation import run_idempotent_operation
from sidekick.shared.observability import TelemetryPort
from sidekick.shared.replay import id_replay_record
from sidekick.shared.types import (
    TIMED_KEY,
    Actor,
    AuditingStore,
    Clock,
    CursorCodec,
    IdempotentStore,
    KeyValue,
    TransactionalStore,
    TxSession,
    paginate,
    validate_limit,
)

LOGGER = logging.getLogger("sidekick.references")


def reference_data(row: ExternalReferenceRow, linked_at: datetime) -> ReferenceRecord:
    return ReferenceRecord(
        id=row.id,
        kind=cast(Kind, row.kind),
        provider=cast(Provider, row.provider),
        account_ref=row.account_ref,
        external_id=row.external_id,
        instance_ref=row.instance_ref,
        title=row.title,
        url=row.url,
        occurs_at=row.occurs_at,
        snapshot_at=row.snapshot_at,
        source=cast(Source, row.source),
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
        linked_at=linked_at,
    )


class ReferenceStore(TransactionalStore, IdempotentStore, AuditingStore, Protocol):
    """What the reference use cases need from storage; every method is scoped to one owner."""

    def require_task(self, session: TxSession, owner: UUID, task_id: UUID) -> None: ...
    def lock_task(self, session: TxSession, owner: UUID, task_id: UUID) -> None: ...
    def lock_identity(
        self, session: TxSession, owner: UUID, details: ExternalReferenceDetails
    ) -> None: ...
    def find_by_identity(
        self, session: TxSession, owner: UUID, details: ExternalReferenceDetails
    ) -> ExternalReferenceRow | None: ...
    def upsert_reference(
        self,
        session: TxSession,
        owner: UUID,
        row: ExternalReferenceRow | None,
        details: ExternalReferenceDetails,
        *,
        source: str,
        now: datetime,
    ) -> ExternalReferenceRow: ...
    def add_relation(
        self, session: TxSession, owner: UUID, task_id: UUID, reference_id: UUID, now: datetime
    ) -> TaskExternalReferenceRow: ...
    def flush(self, session: TxSession) -> None: ...
    def get_reference(
        self, session: TxSession, owner: UUID, reference_id: UUID, *, lock: bool = False
    ) -> ExternalReferenceRow: ...
    def get_relation(
        self, session: TxSession, owner: UUID, task_id: UUID, reference_id: UUID
    ) -> TaskExternalReferenceRow | None: ...
    def count_for_task(self, session: TxSession, owner: UUID, task_id: UUID) -> int: ...
    def count_for_reference(self, session: TxSession, owner: UUID, reference_id: UUID) -> int: ...
    def delete_relation(
        self, session: TxSession, owner: UUID, task_id: UUID, reference_id: UUID
    ) -> None: ...
    def delete_reference(self, session: TxSession, owner: UUID, reference_id: UUID) -> None: ...
    def list_for_task(
        self,
        session: TxSession,
        owner: UUID,
        task_id: UUID,
        *,
        limit: int,
        after: tuple[KeyValue, ...] | None,
    ) -> list[tuple[ExternalReferenceRow, datetime]]: ...


class ExternalReferenceService:
    def __init__(
        self,
        store: ReferenceStore,
        clock: Clock,
        telemetry: TelemetryPort,
        cursor_codec: CursorCodec,
    ) -> None:
        self.store, self.clock, self.telemetry = store, clock, telemetry
        self.cursor_codec = cursor_codec

    def link(
        self,
        actor: Actor,
        task_id: UUID,
        details: ExternalReferenceDetails,
        *,
        source: str,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """Attach the pointer to the Task, creating or refreshing the shared reference row."""

        actor.require("tasks:write")
        if source not in SOURCES:
            raise ValidationError("invalid external reference source")
        payload = {
            "task_id": str(task_id),
            "source": source,
            "reference": asdict(details),
        }

        def execute(session: TxSession) -> dict[str, Any]:
            self.store.require_task(session, actor.user_id, task_id)
            self.store.lock_task(session, actor.user_id, task_id)
            self.store.lock_identity(session, actor.user_id, details)
            now = self.clock.now()
            row = self.store.upsert_reference(
                session,
                actor.user_id,
                self.store.find_by_identity(session, actor.user_id, details),
                details,
                source=source,
                now=now,
            )
            relation = self.store.get_relation(session, actor.user_id, task_id, row.id)
            created = relation is None
            if relation is None:
                if (
                    self.store.count_for_task(session, actor.user_id, task_id)
                    >= MAX_REFERENCES_PER_TASK
                ):
                    raise ConflictError("task has too many external references")
                relation = self.store.add_relation(session, actor.user_id, task_id, row.id, now)
            self.store.flush(session)
            self._audit(
                session, actor, "external_reference.linked", row.id, task_id, correlation_id
            )
            return LinkResult(
                task_id=task_id,
                reference=reference_data(row, relation.created_at),
                linked=True,
                relation_created=created,
            ).model_dump(mode="json")

        def rebuild(session: TxSession, record: dict[str, Any]) -> dict[str, Any]:
            # The record keeps ids and a flag; the pointer's text is read again, so a retry shows
            # the reference as it is now (and fails as not found once it was unlinked).
            reference_id = UUID(record["reference"]["id"])
            row = self.store.get_reference(session, actor.user_id, reference_id)
            relation = self.store.get_relation(session, actor.user_id, task_id, reference_id)
            if relation is None:
                raise NotFoundError("external reference not found")
            return LinkResult(
                task_id=task_id,
                reference=reference_data(row, relation.created_at),
                linked=True,
                relation_created=record["relation_created"],
            ).model_dump(mode="json")

        return self._write(
            actor,
            "link",
            idempotency_key,
            payload,
            execute,
            correlation_id,
            replay=lambda result: {
                "reference": id_replay_record(result["reference"]),
                "relation_created": result["relation_created"],
            },
            rebuild=rebuild,
        )

    def unlink(
        self,
        actor: Actor,
        task_id: UUID,
        reference_id: UUID,
        *,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """Remove the relation; the last relation also removes the pure-pointer row."""

        actor.require("tasks:write")
        payload = {"task_id": str(task_id), "reference_id": str(reference_id)}

        def execute(session: TxSession) -> dict[str, Any]:
            self.store.require_task(session, actor.user_id, task_id)
            self.store.get_reference(session, actor.user_id, reference_id, lock=True)
            removed_reference = False
            if self.store.get_relation(session, actor.user_id, task_id, reference_id) is not None:
                self.store.delete_relation(session, actor.user_id, task_id, reference_id)
                if self.store.count_for_reference(session, actor.user_id, reference_id) == 0:
                    self.store.delete_reference(session, actor.user_id, reference_id)
                    removed_reference = True
            self._audit(
                session, actor, "external_reference.unlinked", reference_id, task_id, correlation_id
            )
            return UnlinkResult(
                task_id=task_id,
                reference_id=reference_id,
                linked=False,
                reference_removed=removed_reference,
            ).model_dump(mode="json")

        return self._write(actor, "unlink", idempotency_key, payload, execute, correlation_id)

    def list_for_task(
        self, actor: Actor, task_id: UUID, *, limit: int = 25, cursor: str | None = None
    ) -> dict[str, Any]:
        actor.require("tasks:read")
        validate_limit(
            limit,
            maximum=MAX_REFERENCES_PER_TASK,
            message="invalid external reference page bounds",
            error=ValidationError,
        )
        query_key = f"task:{task_id}:external-references"
        after = self.cursor_codec.decode_keyset(actor.user_id, cursor, query_key, kinds=TIMED_KEY)

        def read(session: TxSession) -> dict[str, Any]:
            self.store.require_task(session, actor.user_id, task_id)
            rows = self.store.list_for_task(
                session, actor.user_id, task_id, limit=limit + 1, after=after
            )
            page, next_cursor = paginate(
                rows,
                limit,
                lambda last: self.cursor_codec.encode_keyset(
                    actor.user_id, (last[1], last[0].id), query_key
                ),
            )
            return ReferencePage(
                task_id=task_id,
                items=[reference_data(row, linked_at) for row, linked_at in page],
                next_cursor=next_cursor,
            ).model_dump(mode="json")

        return self.store.transaction(read)

    def _write(
        self,
        actor: Actor,
        operation: str,
        key: str,
        payload: dict[str, Any],
        execute: Callable[[TxSession], dict[str, Any]],
        correlation_id: str | None,
        *,
        replay: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        rebuild: Callable[[TxSession, dict[str, Any]], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return run_idempotent_operation(
            store=self.store,
            telemetry=self.telemetry,
            logger=LOGGER,
            feature="external_reference",
            actor_id=actor.user_id,
            operation=operation,
            key=key,
            payload=payload,
            execute=execute,
            correlation_id=correlation_id,
            replay=replay,
            rebuild=rebuild,
        )

    def _audit(
        self,
        session: TxSession,
        actor: Actor,
        event: str,
        target: UUID,
        related: UUID,
        correlation_id: str | None,
    ) -> None:
        self.store.append_audit(
            session,
            actor_id=actor.user_id,
            event=event,
            outcome="success",
            target_type="external_reference",
            target_id=target,
            related_id=related,
            correlation_id=correlation_id or uuid4().hex,
        )
