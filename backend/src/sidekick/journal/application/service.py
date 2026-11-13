"""Transport-neutral queries and edits of existing manual Journal entries."""

from collections.abc import Callable
from datetime import date
from typing import Any
from uuid import UUID

from sidekick.journal.application.models import RelationChange
from sidekick.journal.application.paging import (
    decode_cursor,
    entry_cursor,
    journal_list_cursor_key,
    validate_list_bounds,
)
from sidekick.journal.application.relations import (
    apply_relation_change,
    changes_links,
    checked_relation_change,
)
from sidekick.journal.application.store import JournalStore
from sidekick.journal.domain.entry import (
    JournalEntry,
    KeyPoint,
    append_to_entry,
    archive_entry,
    relink_entry,
    restore_entry,
    update_entry,
)
from sidekick.journal.domain.records import PendingJournalItem
from sidekick.journal.domain.source import JournalSource, replacement_source
from sidekick.shared.errors import ConflictError, ValidationError
from sidekick.shared.types import Actor, Clock, CursorCodec, Page, TxSession, new_uuid7, paginate


class JournalService:
    """Journal entry reads and lifecycle: list, update, append, archive, restore and relink."""

    def __init__(self, store: JournalStore, clock: Clock, cursor_codec: CursorCodec) -> None:
        self.store = store
        self.clock = clock
        self.cursor_codec = cursor_codec

    def list_entries(
        self,
        actor: Actor,
        *,
        start_date: date,
        end_date: date,
        include_archived: bool = False,
        limit: int = 100,
        cursor: str | None = None,
    ) -> Page[JournalEntry]:
        actor.require("journal:read")
        validate_list_bounds(start_date, end_date, limit)
        query_key = journal_list_cursor_key(start_date, end_date, include_archived)
        after = decode_cursor(self.cursor_codec, actor.user_id, cursor, query_key)
        entries = self.store.transaction(
            lambda session: self.store.list_journal_entries(
                session,
                actor.user_id,
                start_date=start_date,
                end_date=end_date,
                include_archived=include_archived,
                limit=limit + 1,
                after=after,
            )
        )
        return Page(
            *paginate(
                entries,
                limit,
                lambda last: entry_cursor(self.cursor_codec, actor, last, query_key),
            )
        )

    def list_pending_items(
        self,
        actor: Actor,
        *,
        start_date: date,
        end_date: date,
        limit: int = 100,
    ) -> tuple[PendingJournalItem, ...]:
        actor.require("journal:read")
        validate_list_bounds(start_date, end_date, limit)
        return tuple(
            self.store.transaction(
                lambda session: self.store.list_pending_journal_items(
                    session,
                    actor.user_id,
                    start_date=start_date,
                    end_date=end_date,
                    limit=limit,
                )
            )
        )

    def get_entry(self, actor: Actor, entry_id: UUID) -> JournalEntry:
        actor.require("journal:read")
        return self.store.transaction(
            lambda session: self.store.get_journal_entry(session, actor.user_id, entry_id)
        )

    def change_entry_relations(
        self,
        actor: Actor,
        *,
        entry_id: UUID,
        expected_version: int,
        change: RelationChange,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> JournalEntry:
        """Add and remove links to Projects and Contacts on an entry; it gets a new version."""

        actor.require("journal:write")
        change = checked_relation_change(actor, change)
        if change.is_empty():
            raise ValidationError("a relation change is required")
        payload = {
            "entry_id": str(entry_id),
            "expected_version": expected_version,
            **change.payload(),
        }
        return self._mutate_entry(
            actor,
            entry_id=entry_id,
            expected_version=expected_version,
            operation="change_journal_entry_relations",
            idempotency_key=idempotency_key,
            payload=payload,
            transition=lambda entry: relink_entry(
                entry, expected_version=expected_version, changed_at=self.clock.now()
            ),
            correlation_id=correlation_id,
            relation_change=change,
            relations_only=True,
        )

    def update_entry(
        self,
        actor: Actor,
        *,
        entry_id: UUID,
        expected_version: int,
        title: str,
        summary: str | None,
        key_points: tuple[KeyPoint, ...],
        idempotency_key: str,
        correlation_id: str | None = None,
        relation_change: RelationChange | None = None,
    ) -> JournalEntry:
        actor.require("journal:write")
        change = checked_relation_change(actor, relation_change or RelationChange())
        payload = {
            "entry_id": str(entry_id),
            "expected_version": expected_version,
            "title": title,
            "summary": summary,
            "key_points": [{"kind": point.kind.value, "text": point.text} for point in key_points],
            **change.payload(),
        }
        return self._mutate_entry(
            actor,
            entry_id=entry_id,
            expected_version=expected_version,
            operation="update_journal_entry",
            idempotency_key=idempotency_key,
            payload=payload,
            transition=lambda entry: update_entry(
                entry,
                expected_version=expected_version,
                title=title,
                summary=summary,
                key_points=key_points,
                changed_at=self.clock.now(),
            ),
            correlation_id=correlation_id,
            relation_change=change,
        )

    def append_to_entry(
        self,
        actor: Actor,
        *,
        entry_id: UUID,
        expected_version: int,
        append_key_points: tuple[KeyPoint, ...],
        append_text: str | None,
        title: str | None = None,
        summary: str | None = None,
        idempotency_key: str,
        correlation_id: str | None = None,
        relation_change: RelationChange | None = None,
    ) -> JournalEntry:
        """Add to an entry without resending it.

        Key points go after the existing ones. `append_text` is the owner's own words: it is saved
        as a new source that replaces the entry's current source (the existing replacement model:
        same provenance, the old row stays as history), and the entry then points at it. A `None`
        title or summary keeps the current one. The entry gets a new version.
        """

        actor.require("journal:write")
        change = checked_relation_change(actor, relation_change or RelationChange())
        if not append_key_points and append_text is None:
            raise ValidationError("append_key_points or append_text is required")
        payload = {
            "entry_id": str(entry_id),
            "expected_version": expected_version,
            "title": title,
            "summary": summary,
            "append_key_points": [
                {"kind": point.kind.value, "text": point.text} for point in append_key_points
            ],
            "append_text": append_text,
            **change.payload(),
        }

        def operation(session: TxSession) -> JournalEntry:
            result = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="append_to_journal_entry",
                key=idempotency_key,
                payload=payload,
                execute=lambda: self._append_to_entry(
                    session,
                    actor,
                    entry_id,
                    expected_version,
                    title,
                    summary,
                    append_key_points,
                    append_text,
                    correlation_id,
                    change,
                ),
            )
            return self.store.get_journal_entry(session, actor.user_id, UUID(result["entry_id"]))

        return self.store.transaction(operation)

    def _append_to_entry(
        self,
        session: TxSession,
        actor: Actor,
        entry_id: UUID,
        expected_version: int,
        title: str | None,
        summary: str | None,
        append_key_points: tuple[KeyPoint, ...],
        append_text: str | None,
        correlation_id: str | None,
        relation_change: RelationChange,
    ) -> dict[str, Any]:
        current = self.store.get_journal_entry(session, actor.user_id, entry_id)
        if len(current.key_points) + len(append_key_points) > 50:
            raise ValidationError("an entry can hold at most 50 key points")
        now = self.clock.now()
        new_source: JournalSource | None = None
        old_source_id: UUID | None = None
        if append_text is not None:
            old_source = self.store.get_journal_source(session, actor.user_id, current.source_id)
            old_source_id = old_source.id
            try:
                new_source = replacement_source(
                    old_source,
                    source_id=new_uuid7(),
                    raw_text=f"{old_source.raw_text}\n\n{append_text}",
                    created_at=max(now, old_source.created_at),
                )
            except ValueError as error:
                raise ValidationError(str(error)) from error
        try:
            updated = append_to_entry(
                current,
                expected_version=expected_version,
                title=title,
                summary=summary,
                append_key_points=append_key_points,
                source_id=None if new_source is None else new_source.id,
                changed_at=now,
            )
        except ValueError as error:
            raise ConflictError(str(error)) from error
        if new_source is not None and old_source_id is not None:
            self.store.save_journal_source(session, new_source)
            self.store.append_audit(
                session,
                actor_id=actor.user_id,
                event="journal.source_created",
                outcome="success",
                target_type="journal_source",
                target_id=new_source.id,
                correlation_id=correlation_id,
            )
            # The old source no longer backs the entry. A pending AI draft on it could otherwise be
            # finalized into a second entry, so close it in the same transaction.
            self.store.supersede_pending_journal_drafts(
                session,
                owner_id=actor.user_id,
                source_id=old_source_id,
                now=now,
                correlation_id=correlation_id,
            )
        self.store.update_journal_entry(
            session, owner_id=actor.user_id, entry=updated, expected_version=expected_version
        )
        if not relation_change.is_empty():
            apply_relation_change(self.store, session, actor, updated.id, relation_change)
        self.store.mark_daily_journal_summary_stale(session, actor.user_id, updated.journal_date)
        self.store.append_audit(
            session,
            actor_id=actor.user_id,
            event="journal.entry_updated",
            outcome="success",
            target_type="journal_entry",
            target_id=updated.id,
            correlation_id=correlation_id,
        )
        return {"entry_id": str(updated.id)}

    def archive_entry(
        self,
        actor: Actor,
        *,
        entry_id: UUID,
        expected_version: int,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> JournalEntry:
        actor.require("journal:write")
        return self._mutate_entry(
            actor,
            entry_id=entry_id,
            expected_version=expected_version,
            operation="archive_journal_entry",
            idempotency_key=idempotency_key,
            payload={"entry_id": str(entry_id), "expected_version": expected_version},
            transition=lambda entry: archive_entry(
                entry, expected_version=expected_version, changed_at=self.clock.now()
            ),
            correlation_id=correlation_id,
        )

    def restore_entry(
        self,
        actor: Actor,
        *,
        entry_id: UUID,
        expected_version: int,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> JournalEntry:
        actor.require("journal:write")
        return self._mutate_entry(
            actor,
            entry_id=entry_id,
            expected_version=expected_version,
            operation="restore_journal_entry",
            idempotency_key=idempotency_key,
            payload={"entry_id": str(entry_id), "expected_version": expected_version},
            transition=lambda entry: restore_entry(
                entry, expected_version=expected_version, changed_at=self.clock.now()
            ),
            correlation_id=correlation_id,
        )

    def _mutate_entry(
        self,
        actor: Actor,
        *,
        entry_id: UUID,
        expected_version: int,
        operation: str,
        idempotency_key: str,
        payload: dict[str, Any],
        transition: Callable[[JournalEntry], JournalEntry],
        correlation_id: str | None,
        relation_change: RelationChange | None = None,
        relations_only: bool = False,
    ) -> JournalEntry:
        def operation_fn(session: TxSession) -> JournalEntry:
            result = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation=operation,
                key=idempotency_key,
                payload=payload,
                execute=lambda: self._transition_entry(
                    session,
                    actor,
                    entry_id,
                    expected_version,
                    transition,
                    correlation_id,
                    relation_change,
                    relations_only=relations_only,
                ),
            )
            return self.store.get_journal_entry(session, actor.user_id, UUID(result["entry_id"]))

        return self.store.transaction(operation_fn)

    def _transition_entry(
        self,
        session: TxSession,
        actor: Actor,
        entry_id: UUID,
        expected_version: int,
        transition: Callable[[JournalEntry], JournalEntry],
        correlation_id: str | None,
        relation_change: RelationChange | None = None,
        *,
        relations_only: bool = False,
    ) -> dict[str, Any]:
        current = self.store.get_journal_entry(session, actor.user_id, entry_id)
        try:
            updated = transition(current)
        except ValueError as error:
            raise ConflictError(str(error)) from error
        if (
            relations_only
            and relation_change is not None
            and not changes_links(self.store, session, actor, entry_id, relation_change)
        ):
            # Only links that are already there are added and only missing ones removed: nothing
            # changed, so the entry keeps its version and the day summary is not marked stale.
            return {"entry_id": str(entry_id)}
        self.store.update_journal_entry(
            session, owner_id=actor.user_id, entry=updated, expected_version=expected_version
        )
        if relation_change is not None and not relation_change.is_empty():
            apply_relation_change(self.store, session, actor, updated.id, relation_change)
        self.store.mark_daily_journal_summary_stale(session, actor.user_id, updated.journal_date)
        self.store.append_audit(
            session,
            actor_id=actor.user_id,
            event="journal.entry_updated",
            outcome="success",
            target_type="journal_entry",
            target_id=updated.id,
            correlation_id=correlation_id,
        )
        return {"entry_id": str(updated.id)}
