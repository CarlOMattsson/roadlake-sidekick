"""Transport-neutral queries and edits of existing manual Journal entries."""

from collections.abc import Callable, Sequence
from datetime import date, datetime
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
    JournalOrder,
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
from sidekick.work.domain.planning import normalize_tag_filter, normalize_tag_selection
from sidekick.work.domain.tag_assignment import apply_record_tags


def _wanted_tags(tags: Sequence[str] | None) -> tuple[str, ...] | None:
    """The normalized tag set a write asks for; None when it sends none (tags stay as they are)."""

    return None if tags is None else normalize_tag_selection(list(tags))


def _tags_payload(tags: tuple[str, ...] | None) -> dict[str, list[str]]:
    """The tag set for the idempotency fingerprint; empty when none was sent."""

    return {} if tags is None else {"tags": list(tags)}


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
        tags: Sequence[str] = (),
        tag_match: str = "any",
        order: JournalOrder = "asc",
        limit: int = 100,
        cursor: str | None = None,
    ) -> Page[JournalEntry]:
        actor.require("journal:read")
        validate_list_bounds(start_date, end_date, limit)
        wanted_tags, tag_match = normalize_tag_filter(list(tags), tag_match)
        query_key = journal_list_cursor_key(
            start_date, end_date, include_archived, wanted_tags, tag_match, order
        )
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
                tags=wanted_tags,
                tag_match=tag_match,
                order=order,
            )
        )
        return Page(
            *paginate(
                entries,
                limit,
                lambda last: entry_cursor(self.cursor_codec, actor, last, query_key, order),
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
        tags: Sequence[str] | None = None,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> JournalEntry:
        """Add and remove links to Projects and Contacts and set the tags of an entry.

        The content stays; the entry gets a new version. `tags` is the complete intended tag set.
        """

        actor.require("journal:write")
        change = checked_relation_change(actor, change)
        wanted_tags = _wanted_tags(tags)
        if change.is_empty() and wanted_tags is None:
            raise ValidationError("a relation or tag change is required")
        payload = {
            "entry_id": str(entry_id),
            "expected_version": expected_version,
            **change.payload(),
            **_tags_payload(wanted_tags),
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
            tags=wanted_tags,
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
        tags: Sequence[str] | None = None,
    ) -> JournalEntry:
        actor.require("journal:write")
        change = checked_relation_change(actor, relation_change or RelationChange())
        wanted_tags = _wanted_tags(tags)
        payload = {
            "entry_id": str(entry_id),
            "expected_version": expected_version,
            "title": title,
            "summary": summary,
            "key_points": [{"kind": point.kind.value, "text": point.text} for point in key_points],
            **change.payload(),
            **_tags_payload(wanted_tags),
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
            tags=wanted_tags,
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
        tags: Sequence[str] | None = None,
    ) -> JournalEntry:
        """Add to an entry without resending it.

        Key points go after the existing ones. `append_text` is the owner's own words: it is saved
        as a new source that replaces the entry's current source (the existing replacement model:
        same provenance, the old row stays as history), and the entry then points at it. A `None`
        title or summary keeps the current one. The entry gets a new version.
        """

        actor.require("journal:write")
        change = checked_relation_change(actor, relation_change or RelationChange())
        wanted_tags = _wanted_tags(tags)
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
            **_tags_payload(wanted_tags),
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
                    wanted_tags,
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
        tags: tuple[str, ...] | None,
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
        self._apply_tags(session, actor, updated.id, tags, now)
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

    def _apply_tags(
        self,
        session: TxSession,
        actor: Actor,
        entry_id: UUID,
        tags: tuple[str, ...] | None,
        now: datetime,
    ) -> None:
        """Replace the entry's tags with the complete intended set, when one was sent."""

        if tags is not None:
            apply_record_tags(
                self.store,
                session,
                owner_id=actor.user_id,
                kind="journal_entry",
                record_id=entry_id,
                values=tags,
                now=now,
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
        tags: tuple[str, ...] | None = None,
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
                    tags,
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
        tags: tuple[str, ...] | None = None,
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
            and tags is None
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
        self._apply_tags(session, actor, updated.id, tags, self.clock.now())
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
