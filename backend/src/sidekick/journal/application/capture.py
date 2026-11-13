"""Journal sources and manual entries: capturing what the owner wrote."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sidekick.journal.application.models import (
    CreateManualEntryCommand,
    CreateSourceCommand,
    manual_entry_command_data,
    source_command_data,
)
from sidekick.journal.application.relations import bounded_unique_ids, require_active_links
from sidekick.journal.application.store import JournalStore
from sidekick.journal.domain.entry import JournalEntry, KeyPoint
from sidekick.journal.domain.source import JournalSource, SourceType, replacement_source
from sidekick.shared.errors import ConflictError, ValidationError
from sidekick.shared.types import Actor, Clock, TxSession, new_uuid7
from sidekick.work.domain.planning import normalize_tag_selection
from sidekick.work.domain.tag_assignment import apply_record_tags


class JournalCaptureService:
    """AI-independent Journal source and manual-entry creation."""

    def __init__(self, store: JournalStore, clock: Clock) -> None:
        self.store = store
        self.clock = clock

    def create_source(
        self,
        actor: Actor,
        *,
        source_type: SourceType,
        journal_date: date,
        occurred_at: datetime | None,
        source_recorded_at: datetime | None,
        raw_text: str,
        language: str | None,
        replaces_source_id: UUID | None,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> JournalSource:
        actor.require("journal:write")
        command = CreateSourceCommand(
            source_type=source_type,
            journal_date=journal_date,
            occurred_at=occurred_at,
            source_recorded_at=source_recorded_at,
            raw_text=raw_text,
            language=language,
            replaces_source_id=replaces_source_id,
        )
        payload = source_command_data(command)

        def operation(session: TxSession) -> JournalSource:
            result = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="create_journal_source",
                key=idempotency_key,
                payload=payload,
                execute=lambda: self._create_source(session, actor, command, correlation_id),
            )
            return self.store.get_journal_source(session, actor.user_id, UUID(result["source_id"]))

        return self.store.transaction(operation)

    def _create_source(
        self,
        session: TxSession,
        actor: Actor,
        command: CreateSourceCommand,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        try:
            if command.replaces_source_id is None:
                source = JournalSource(
                    id=new_uuid7(),
                    owner_id=actor.user_id,
                    source_type=command.source_type,
                    journal_date=command.journal_date,
                    occurred_at=command.occurred_at,
                    source_recorded_at=command.source_recorded_at,
                    raw_text=command.raw_text,
                    language=command.language,
                    replaces_source_id=None,
                    created_at=self.clock.now(),
                )
            else:
                replaced = self.store.get_journal_source(
                    session, actor.user_id, command.replaces_source_id
                )
                supplied_provenance = (
                    command.source_type,
                    command.journal_date,
                    command.occurred_at,
                    command.source_recorded_at,
                    command.language,
                )
                retained_provenance = (
                    replaced.source_type,
                    replaced.journal_date,
                    replaced.occurred_at,
                    replaced.source_recorded_at,
                    replaced.language,
                )
                if supplied_provenance != retained_provenance:
                    raise ValidationError("replacement source provenance must be unchanged")
                source = replacement_source(
                    replaced,
                    source_id=new_uuid7(),
                    raw_text=command.raw_text,
                    created_at=self.clock.now(),
                )
        except ValueError as error:
            raise ValidationError(str(error)) from error

        self.store.save_journal_source(session, source)
        self.store.append_audit(
            session,
            actor_id=actor.user_id,
            event="journal.source_created",
            outcome="success",
            target_type="journal_source",
            target_id=source.id,
            correlation_id=correlation_id,
        )
        return {"source_id": str(source.id)}

    def get_source(self, actor: Actor, source_id: UUID) -> JournalSource:
        actor.require("journal:read")
        return self.store.transaction(
            lambda session: self.store.get_journal_source(session, actor.user_id, source_id)
        )

    def create_manual_entry(
        self,
        actor: Actor,
        *,
        source_id: UUID,
        title: str,
        summary: str | None,
        key_points: tuple[KeyPoint, ...],
        project_ids: tuple[UUID, ...] = (),
        task_ids: tuple[UUID, ...] = (),
        contact_ids: tuple[UUID, ...] = (),
        tags: tuple[str, ...] = (),
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> JournalEntry:
        actor.require("journal:write")
        if project_ids:
            actor.require("projects:read")
        if task_ids:
            actor.require("tasks:read")
        if contact_ids:
            actor.require("contacts:read")
        command = CreateManualEntryCommand(
            source_id=source_id,
            title=title,
            summary=summary,
            key_points=tuple(key_points),
            project_ids=bounded_unique_ids(project_ids, "project_ids"),
            task_ids=bounded_unique_ids(task_ids, "task_ids"),
            contact_ids=bounded_unique_ids(contact_ids, "contact_ids"),
            tags=normalize_tag_selection(tags),
        )
        payload = manual_entry_command_data(command)

        def operation(session: TxSession) -> JournalEntry:
            result = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="create_manual_journal_entry",
                key=idempotency_key,
                payload=payload,
                execute=lambda: self._create_manual_entry(session, actor, command, correlation_id),
            )
            return self.store.get_journal_entry(session, actor.user_id, UUID(result["entry_id"]))

        return self.store.transaction(operation)

    def _create_manual_entry(
        self,
        session: TxSession,
        actor: Actor,
        command: CreateManualEntryCommand,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        source = self.store.get_journal_source(session, actor.user_id, command.source_id)
        if self.store.journal_source_has_live_replacement(session, actor.user_id, source.id):
            raise ConflictError("journal source was replaced")
        require_active_links(
            self.store,
            session,
            actor,
            command.project_ids,
            command.task_ids,
            command.contact_ids,
        )
        now = self.clock.now()
        try:
            entry = JournalEntry(
                id=new_uuid7(),
                owner_id=actor.user_id,
                source_id=source.id,
                journal_date=source.journal_date,
                occurred_at=source.occurred_at,
                source_recorded_at=source.source_recorded_at,
                title=command.title,
                summary=command.summary,
                key_points=command.key_points,
                version=1,
                created_at=now,
                updated_at=now,
                archived_at=None,
            )
        except ValueError as error:
            raise ValidationError(str(error)) from error
        self.store.save_journal_entry(session, entry)
        self.store.add_journal_entry_relations(
            session,
            owner_id=actor.user_id,
            entry_id=entry.id,
            project_ids=command.project_ids,
            task_ids=command.task_ids,
            contact_ids=command.contact_ids,
        )
        if command.tags:
            apply_record_tags(
                self.store,
                session,
                owner_id=actor.user_id,
                kind="journal_entry",
                record_id=entry.id,
                values=command.tags,
                now=now,
            )
        stale_marker = getattr(self.store, "mark_daily_journal_summary_stale", None)
        if stale_marker is not None:
            stale_marker(session, actor.user_id, entry.journal_date)
        self.store.append_audit(
            session,
            actor_id=actor.user_id,
            event="journal.manual_entry_created",
            outcome="success",
            target_type="journal_entry",
            target_id=entry.id,
            correlation_id=correlation_id,
        )
        return {"entry_id": str(entry.id)}

    def write_entry(
        self,
        actor: Actor,
        *,
        source_type: SourceType,
        journal_date: date,
        occurred_at: datetime | None,
        raw_text: str,
        language: str | None,
        title: str,
        summary: str | None,
        key_points: tuple[KeyPoint, ...],
        project_ids: tuple[UUID, ...] = (),
        task_ids: tuple[UUID, ...] = (),
        contact_ids: tuple[UUID, ...] = (),
        tags: tuple[str, ...] = (),
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> tuple[JournalSource, JournalEntry]:
        """Create one source and its entry in a single transaction.

        The source and entry steps reuse the same idempotent use-case bodies as `create_source`
        and `create_manual_entry`, under keys derived from the caller's key. A retry with the same
        key and payload returns the same pair; a failure in either step rolls both back.
        """

        actor.require("journal:write")
        if project_ids:
            actor.require("projects:read")
        if task_ids:
            actor.require("tasks:read")
        if contact_ids:
            actor.require("contacts:read")
        source_command = CreateSourceCommand(
            source_type=source_type,
            journal_date=journal_date,
            occurred_at=occurred_at,
            source_recorded_at=None,
            raw_text=raw_text,
            language=language,
        )
        bounded_projects = bounded_unique_ids(project_ids, "project_ids")
        bounded_tasks = bounded_unique_ids(task_ids, "task_ids")
        bounded_contacts = bounded_unique_ids(contact_ids, "contact_ids")
        wanted_tags = normalize_tag_selection(tags)
        source_payload = source_command_data(source_command)

        def operation(session: TxSession) -> tuple[JournalSource, JournalEntry]:
            source_result = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="create_journal_source",
                key=f"{idempotency_key}:source",
                payload=source_payload,
                execute=lambda: self._create_source(session, actor, source_command, correlation_id),
            )
            source_id = UUID(source_result["source_id"])
            entry_command = CreateManualEntryCommand(
                source_id=source_id,
                title=title,
                summary=summary,
                key_points=tuple(key_points),
                project_ids=bounded_projects,
                task_ids=bounded_tasks,
                contact_ids=bounded_contacts,
                tags=wanted_tags,
            )
            entry_result = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="create_manual_journal_entry",
                key=f"{idempotency_key}:entry",
                payload=manual_entry_command_data(entry_command),
                execute=lambda: self._create_manual_entry(
                    session, actor, entry_command, correlation_id
                ),
            )
            return (
                self.store.get_journal_source(session, actor.user_id, source_id),
                self.store.get_journal_entry(
                    session, actor.user_id, UUID(entry_result["entry_id"])
                ),
            )

        return self.store.transaction(operation)
