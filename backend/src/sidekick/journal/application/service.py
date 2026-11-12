"""Transport-neutral commands and queries for the manual Journal."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, tzinfo
from typing import Any, Protocol, TypeVar
from uuid import UUID

from sidekick.contacts.domain.contact import Contact
from sidekick.journal.domain.day_done import DayDone
from sidekick.journal.domain.entry import (
    ENTRY_PAGE_KEY,
    EntryHead,
    JournalEntry,
    KeyPoint,
    append_to_entry,
    archive_entry,
    entry_page_key,
    relink_entry,
    restore_entry,
    update_entry,
)
from sidekick.journal.domain.records import (
    DaySummaryStatus,
    EntryRelations,
    PendingJournalItem,
    RelationLabels,
)
from sidekick.journal.domain.source import JournalSource, SourceType, replacement_source
from sidekick.journal.domain.summary import DailySummary, SummaryContent, entry_fingerprint
from sidekick.projects.domain import Project, ProjectStatus
from sidekick.shared.config import DEFAULT_OWNER_TIMEZONE, parse_owner_timezone
from sidekick.shared.errors import ConflictError, NotFoundError, ValidationError
from sidekick.shared.types import (
    Actor,
    AuditingStore,
    Clock,
    CursorCodec,
    IdempotentStore,
    KeyValue,
    Page,
    TransactionalStore,
    TxSession,
    new_uuid7,
)
from sidekick.tasks.domain import Task, TaskStatus

T = TypeVar("T")
DEFAULT_OWNER_ZONE = parse_owner_timezone(DEFAULT_OWNER_TIMEZONE)
MAX_JOURNAL_RANGE_DAYS = 366
MAX_RELATIONS_PER_KIND = 25


@dataclass(frozen=True, slots=True)
class CreateSourceCommand:
    source_type: SourceType
    journal_date: date
    occurred_at: datetime | None
    source_recorded_at: datetime | None
    raw_text: str
    language: str | None
    replaces_source_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class CreateManualEntryCommand:
    source_id: UUID
    title: str
    summary: str | None
    key_points: tuple[KeyPoint, ...]
    project_ids: tuple[UUID, ...] = ()
    task_ids: tuple[UUID, ...] = ()
    contact_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class RelationChange:
    """Links to add to and remove from an existing entry (Projects and Contacts only)."""

    add_project_ids: tuple[UUID, ...] = ()
    remove_project_ids: tuple[UUID, ...] = ()
    add_contact_ids: tuple[UUID, ...] = ()
    remove_contact_ids: tuple[UUID, ...] = ()

    def is_empty(self) -> bool:
        return not (
            self.add_project_ids
            or self.remove_project_ids
            or self.add_contact_ids
            or self.remove_contact_ids
        )

    def payload(self) -> dict[str, list[str]]:
        """The non-empty id lists, for the idempotency fingerprint; empty for no change."""

        fields = {
            "add_project_ids": self.add_project_ids,
            "remove_project_ids": self.remove_project_ids,
            "add_contact_ids": self.add_contact_ids,
            "remove_contact_ids": self.remove_contact_ids,
        }
        return {name: [str(value) for value in ids] for name, ids in fields.items() if ids}


@dataclass(frozen=True, slots=True)
class JournalDay:
    journal_date: date
    entries: tuple[JournalEntry, ...]
    next_cursor: str | None
    summary_status: DaySummaryStatus
    entry_fingerprint: str
    summary: DailySummary | None = None
    done: DayDone = field(default_factory=DayDone)
    """What was completed or bought that day, in the owner's zone. Always present."""


class JournalStore(TransactionalStore, IdempotentStore, AuditingStore, Protocol):
    """Journal-focused persistence operations used by the manual application service."""

    def save_journal_source(self, session: TxSession, source: JournalSource) -> None: ...

    def get_journal_source(
        self, session: TxSession, owner_id: UUID, source_id: UUID
    ) -> JournalSource: ...

    def save_journal_entry(self, session: TxSession, entry: JournalEntry) -> None: ...

    def get_journal_entry(
        self, session: TxSession, owner_id: UUID, entry_id: UUID
    ) -> JournalEntry: ...

    def list_journal_entries(
        self,
        session: TxSession,
        owner_id: UUID,
        *,
        start_date: date,
        end_date: date,
        include_archived: bool = False,
        limit: int = 100,
        after: tuple[KeyValue, ...] | None = None,
    ) -> list[JournalEntry]: ...

    def list_pending_journal_items(
        self,
        session: TxSession,
        owner_id: UUID,
        *,
        start_date: date,
        end_date: date,
        limit: int = 100,
    ) -> list[PendingJournalItem]: ...

    def journal_source_has_live_replacement(
        self, session: TxSession, owner_id: UUID, source_id: UUID
    ) -> bool: ...

    def supersede_pending_journal_drafts(
        self,
        session: TxSession,
        *,
        owner_id: UUID,
        source_id: UUID,
        now: datetime,
        correlation_id: str | None,
    ) -> int: ...

    def add_journal_entry_relations(
        self,
        session: TxSession,
        *,
        owner_id: UUID,
        entry_id: UUID,
        project_ids: tuple[UUID, ...],
        task_ids: tuple[UUID, ...],
        contact_ids: tuple[UUID, ...],
    ) -> None: ...

    def remove_journal_entry_relations(
        self,
        session: TxSession,
        *,
        owner_id: UUID,
        entry_id: UUID,
        project_ids: tuple[UUID, ...],
        contact_ids: tuple[UUID, ...],
    ) -> None: ...

    def get_journal_entry_relations(
        self, session: TxSession, owner_id: UUID, entry_id: UUID
    ) -> "EntryRelations": ...

    def update_journal_entry(
        self,
        session: TxSession,
        *,
        owner_id: UUID,
        entry: JournalEntry,
        expected_version: int,
    ) -> JournalEntry: ...

    def get_daily_summary(
        self, session: TxSession, owner_id: UUID, summary_or_date: UUID | date
    ) -> DailySummary | None: ...

    def get_daily_summary_status(
        self,
        session: TxSession,
        owner_id: UUID,
        journal_date: date,
        *,
        summary: DailySummary | None = ...,
        active: list[EntryHead] | None = None,
    ) -> DaySummaryStatus: ...

    def read_day_done(
        self, session: TxSession, actor: Actor, journal_date: date, zone: tzinfo
    ) -> DayDone: ...

    def get_journal_entries_relations(
        self, session: TxSession, owner_id: UUID, entry_ids: tuple[UUID, ...]
    ) -> dict[UUID, "EntryRelations"]: ...

    def upsert_manual_daily_summary(
        self,
        session: TxSession,
        *,
        owner_id: UUID,
        journal_date: date,
        content: SummaryContent,
        expected_entry_fingerprint: str,
        expected_summary_version: int | None,
        now: datetime,
        correlation_id: str | None = None,
    ) -> DailySummary: ...

    def list_active_journal_entry_heads(
        self, session: TxSession, owner_id: UUID, journal_date: date
    ) -> list[EntryHead]: ...
    def mark_daily_journal_summary_stale(
        self, session: TxSession, owner_id: UUID, journal_date: date
    ) -> None: ...

    def get_project(self, session: TxSession, owner_id: UUID, project_id: UUID) -> Project: ...

    def get_task(self, session: TxSession, owner_id: UUID, task_id: UUID) -> Task: ...

    def get_contact(
        self,
        session: TxSession,
        owner_id: UUID,
        contact_id: UUID,
        include_archived: bool = False,
    ) -> Contact: ...


class JournalService:
    """AI-independent Journal source and manual-entry use cases."""

    def __init__(
        self,
        store: JournalStore,
        clock: Clock,
        cursor_codec: CursorCodec,
        owner_timezone: tzinfo = DEFAULT_OWNER_ZONE,
    ) -> None:
        self.store = store
        self.clock = clock
        self.cursor_codec = cursor_codec
        self.owner_timezone = owner_timezone

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
            project_ids=_bounded_unique_ids(project_ids, "project_ids"),
            task_ids=_bounded_unique_ids(task_ids, "task_ids"),
            contact_ids=_bounded_unique_ids(contact_ids, "contact_ids"),
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
        self._require_active_relations(session, actor, command)
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
        bounded_projects = _bounded_unique_ids(project_ids, "project_ids")
        bounded_tasks = _bounded_unique_ids(task_ids, "task_ids")
        bounded_contacts = _bounded_unique_ids(contact_ids, "contact_ids")
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

    def _require_active_relations(
        self, session: TxSession, actor: Actor, command: CreateManualEntryCommand
    ) -> None:
        self._require_active_links(
            session, actor, command.project_ids, command.task_ids, command.contact_ids
        )

    def _require_active_links(
        self,
        session: TxSession,
        actor: Actor,
        project_ids: tuple[UUID, ...],
        task_ids: tuple[UUID, ...],
        contact_ids: tuple[UUID, ...],
    ) -> None:
        for project_id in sorted(project_ids, key=lambda value: value.int):
            project = self.store.get_project(session, actor.user_id, project_id)
            if project.status is ProjectStatus.COMPLETED:
                raise NotFoundError("project not found")
        for task_id in sorted(task_ids, key=lambda value: value.int):
            task = self.store.get_task(session, actor.user_id, task_id)
            if task.status is TaskStatus.COMPLETED:
                raise NotFoundError("task not found")
        for contact_id in sorted(contact_ids, key=lambda value: value.int):
            contact = self.store.get_contact(session, actor.user_id, contact_id)
            if contact.archived:
                raise NotFoundError("contact not found")

    def _apply_relation_change(
        self, session: TxSession, actor: Actor, entry_id: UUID, change: RelationChange
    ) -> None:
        """Add and remove links inside the entry's transaction, with the creation checks.

        Added Projects and Contacts must be the owner's and active, as when the entry is created.
        A link that is already there is not added again and a link that is not there is not
        removed, so the call can be repeated and an undo is simply the opposite change.
        """

        current = self.store.get_journal_entry_relations(session, actor.user_id, entry_id)
        add_projects = tuple(i for i in change.add_project_ids if i not in current.project_ids)
        add_contacts = tuple(i for i in change.add_contact_ids if i not in current.contact_ids)
        drop_projects = tuple(i for i in change.remove_project_ids if i in current.project_ids)
        drop_contacts = tuple(i for i in change.remove_contact_ids if i in current.contact_ids)
        self._require_active_links(session, actor, add_projects, (), add_contacts)
        kept_projects = len(current.project_ids) - len(drop_projects) + len(add_projects)
        kept_contacts = len(current.contact_ids) - len(drop_contacts) + len(add_contacts)
        if max(kept_projects, kept_contacts) > MAX_RELATIONS_PER_KIND:
            raise ValidationError("an entry can hold at most 25 Projects and 25 Contacts")
        if drop_projects or drop_contacts:
            self.store.remove_journal_entry_relations(
                session,
                owner_id=actor.user_id,
                entry_id=entry_id,
                project_ids=drop_projects,
                contact_ids=drop_contacts,
            )
        if add_projects or add_contacts:
            self.store.add_journal_entry_relations(
                session,
                owner_id=actor.user_id,
                entry_id=entry_id,
                project_ids=add_projects,
                task_ids=(),
                contact_ids=add_contacts,
            )

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
        _validate_list_bounds(start_date, end_date, limit)
        query_key = journal_list_cursor_key(start_date, end_date, include_archived)
        after = _decode_cursor(self.cursor_codec, actor.user_id, cursor, query_key)
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
            items=entries[:limit],
            next_cursor=self._entry_cursor(actor, entries[limit - 1], query_key)
            if len(entries) > limit
            else None,
        )

    def _entry_cursor(self, actor: Actor, last: JournalEntry, query_key: str) -> str:
        """Keyset cursor after the last entry served: it does not shift when entries come and go."""

        return self.cursor_codec.encode_keyset(actor.user_id, entry_page_key(last), query_key)

    def list_pending_items(
        self,
        actor: Actor,
        *,
        start_date: date,
        end_date: date,
        limit: int = 100,
    ) -> tuple[PendingJournalItem, ...]:
        actor.require("journal:read")
        _validate_list_bounds(start_date, end_date, limit)
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

    def get_entry_relations(self, actor: Actor, entry_id: UUID) -> EntryRelations:
        actor.require("journal:read")
        relation_reader = getattr(self.store, "get_journal_entry_relations", None)
        if relation_reader is None:
            return EntryRelations()
        return self.store.transaction(
            lambda session: relation_reader(session, actor.user_id, entry_id)
        )

    def get_entries_relations(
        self, actor: Actor, entry_ids: tuple[UUID, ...], *, with_labels: bool
    ) -> dict[UUID, tuple[EntryRelations, RelationLabels | None]]:
        """Links, and with `with_labels` their names, of several entries in one transaction.

        The same links and names `get_entry_relations` and `get_relation_labels` give per entry:
        a kind's names need its read scope.
        """

        actor.require("journal:read")
        relation_reader = getattr(self.store, "get_journal_entries_relations", None)
        if relation_reader is None or not entry_ids:
            return {entry_id: (EntryRelations(), None) for entry_id in entry_ids}
        label_reader = getattr(self.store, "get_journal_relation_labels", None)
        can_name_projects = with_labels and "projects:read" in actor.scopes
        can_name_contacts = with_labels and "contacts:read" in actor.scopes

        def read(session: TxSession) -> dict[UUID, tuple[EntryRelations, RelationLabels | None]]:
            relations = relation_reader(session, actor.user_id, entry_ids)
            project_ids = tuple(
                {i for r in relations.values() for i in r.project_ids} if can_name_projects else ()
            )
            contact_ids = tuple(
                {i for r in relations.values() for i in r.contact_ids} if can_name_contacts else ()
            )
            names = (
                label_reader(session, actor.user_id, project_ids, contact_ids)
                if label_reader is not None and (project_ids or contact_ids)
                else RelationLabels(projects={}, contacts={})
            )
            return {
                entry_id: (
                    relations[entry_id],
                    RelationLabels(
                        projects={
                            i: names.projects[i]
                            for i in relations[entry_id].project_ids
                            if i in names.projects
                        },
                        contacts={
                            i: names.contacts[i]
                            for i in relations[entry_id].contact_ids
                            if i in names.contacts
                        },
                    )
                    if with_labels
                    else None,
                )
                for entry_id in entry_ids
            }

        return self.store.transaction(read)

    def get_relation_labels(self, actor: Actor, relations: EntryRelations) -> RelationLabels:
        """Names of the linked Projects and Contacts; none for a kind the actor may not read."""

        reader = getattr(self.store, "get_journal_relation_labels", None)
        project_ids = relations.project_ids if "projects:read" in actor.scopes else ()
        contact_ids = relations.contact_ids if "contacts:read" in actor.scopes else ()
        if reader is None or not (project_ids or contact_ids):
            return RelationLabels(projects={}, contacts={})
        return self.store.transaction(
            lambda session: reader(session, actor.user_id, project_ids, contact_ids)
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
        change = self._checked_relation_change(actor, change)
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

    def _changes_links(
        self, session: TxSession, actor: Actor, entry_id: UUID, change: RelationChange
    ) -> bool:
        """Whether the change adds a missing link or removes a present one."""

        current = self.store.get_journal_entry_relations(session, actor.user_id, entry_id)
        return (
            any(i not in current.project_ids for i in change.add_project_ids)
            or any(i in current.project_ids for i in change.remove_project_ids)
            or any(i not in current.contact_ids for i in change.add_contact_ids)
            or any(i in current.contact_ids for i in change.remove_contact_ids)
        )

    @staticmethod
    def _checked_relation_change(actor: Actor, change: RelationChange) -> RelationChange:
        """Bounds the id lists and requires the read scope of every kind the change names."""

        change = RelationChange(
            add_project_ids=_bounded_unique_ids(change.add_project_ids, "add_project_ids"),
            remove_project_ids=_bounded_unique_ids(change.remove_project_ids, "remove_project_ids"),
            add_contact_ids=_bounded_unique_ids(change.add_contact_ids, "add_contact_ids"),
            remove_contact_ids=_bounded_unique_ids(change.remove_contact_ids, "remove_contact_ids"),
        )
        if change.add_project_ids or change.remove_project_ids:
            actor.require("projects:read")
        if change.add_contact_ids or change.remove_contact_ids:
            actor.require("contacts:read")
        if set(change.add_project_ids) & set(change.remove_project_ids) or set(
            change.add_contact_ids
        ) & set(change.remove_contact_ids):
            raise ValidationError("a link cannot be both added and removed")
        return change

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
        change = self._checked_relation_change(actor, relation_change or RelationChange())
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
        change = self._checked_relation_change(actor, relation_change or RelationChange())
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
            self._apply_relation_change(session, actor, updated.id, relation_change)
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
            and not self._changes_links(session, actor, entry_id, relation_change)
        ):
            # Only links that are already there are added and only missing ones removed: nothing
            # changed, so the entry keeps its version and the day summary is not marked stale.
            return {"entry_id": str(entry_id)}
        self.store.update_journal_entry(
            session, owner_id=actor.user_id, entry=updated, expected_version=expected_version
        )
        if relation_change is not None and not relation_change.is_empty():
            self._apply_relation_change(session, actor, updated.id, relation_change)
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

    def put_manual_summary(
        self,
        actor: Actor,
        *,
        journal_date: date,
        expected_entry_fingerprint: str,
        expected_summary_version: int | None,
        content: SummaryContent,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> DailySummary:
        actor.require("journal:write")
        payload = {
            "journal_date": journal_date.isoformat(),
            "expected_entry_fingerprint": expected_entry_fingerprint,
            "expected_summary_version": expected_summary_version,
            "content": content.model_dump(mode="json"),
        }

        def operation(session: TxSession) -> DailySummary:
            result = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="put_manual_daily_summary",
                key=idempotency_key,
                payload=payload,
                execute=lambda: {
                    "summary_id": str(
                        self.store.upsert_manual_daily_summary(
                            session,
                            owner_id=actor.user_id,
                            journal_date=journal_date,
                            content=content,
                            expected_entry_fingerprint=expected_entry_fingerprint,
                            expected_summary_version=expected_summary_version,
                            now=self.clock.now(),
                            correlation_id=correlation_id,
                        ).id
                    )
                },
            )
            summary = self.store.get_daily_summary(
                session,
                actor.user_id,
                UUID(result["summary_id"]) if "summary_id" in result else journal_date,
            )
            if summary is None:
                raise NotFoundError("daily summary not found")
            return summary

        return self.store.transaction(operation)

    def get_summary(
        self, actor: Actor, journal_date: date
    ) -> tuple[DaySummaryStatus, DailySummary | None]:
        actor.require("journal:read")
        status_reader = getattr(self.store, "get_daily_summary_status", None)
        summary_reader = getattr(self.store, "get_daily_summary", None)
        if status_reader is None or summary_reader is None:
            return DaySummaryStatus(), None
        return self.store.transaction(
            lambda session: (
                status_reader(session, actor.user_id, journal_date),
                summary_reader(session, actor.user_id, journal_date),
            )
        )

    def get_day(
        self,
        actor: Actor,
        *,
        journal_date: date,
        include_archived: bool = False,
        limit: int = 100,
        cursor: str | None = None,
        include_done: bool = True,
    ) -> JournalDay:
        """One diary day. `include_done` false skips the done read for callers that ignore it."""

        actor.require("journal:read")
        if not 1 <= limit <= 100:
            raise ValidationError("limit must be between 1 and 100")
        query_key = journal_day_cursor_key(journal_date, include_archived)
        after = _decode_cursor(self.cursor_codec, actor.user_id, cursor, query_key)

        def read(
            session: TxSession,
        ) -> tuple[
            list[JournalEntry],
            DaySummaryStatus,
            DailySummary | None,
            list[EntryHead],
            DayDone,
        ]:
            entries = self.store.list_journal_entries(
                session,
                actor.user_id,
                start_date=journal_date,
                end_date=journal_date,
                include_archived=include_archived,
                limit=limit + 1,
                after=after,
            )
            # A day without entries is still a day: what was done on it is shown all the same,
            # and the answer is the same whether the date is empty or belongs to nobody.
            # Over all active entries of the day, not the page: put_manual_summary validates this
            # value against the same full set, so a paged fingerprint would be wrong for days over
            # one page.
            active = self.store.list_active_journal_entry_heads(
                session, actor.user_id, journal_date
            )
            status_reader = getattr(self.store, "get_daily_summary_status", None)
            summary_reader = getattr(self.store, "get_daily_summary", None)
            summary = (
                summary_reader(session, actor.user_id, journal_date)
                if summary_reader is not None
                else None
            )
            summary_status = (
                status_reader(session, actor.user_id, journal_date, summary=summary, active=active)
                if status_reader is not None
                else DaySummaryStatus()
            )
            done = (
                self.store.read_day_done(session, actor, journal_date, self.owner_timezone)
                if include_done
                else DayDone()
            )
            return entries, summary_status, summary, active, done

        entries, summary_status, summary, active, done = self.store.transaction(read)
        return JournalDay(
            journal_date=journal_date,
            entries=tuple(entries[:limit]),
            next_cursor=self._entry_cursor(actor, entries[limit - 1], query_key)
            if len(entries) > limit
            else None,
            summary_status=summary_status,
            entry_fingerprint=entry_fingerprint(active),
            summary=summary,
            done=done,
        )


def _bounded_unique_ids(values: tuple[UUID, ...], field_name: str) -> tuple[UUID, ...]:
    values = tuple(values)
    if len(values) > MAX_RELATIONS_PER_KIND:
        raise ValidationError(f"{field_name} must contain at most 25 identifiers")
    if len(values) != len(set(values)):
        raise ValidationError(f"{field_name} must contain unique identifiers")
    return values


def _decode_cursor(
    codec: CursorCodec, actor_id: UUID, cursor: str | None, query_key: str
) -> tuple[KeyValue, ...] | None:
    try:
        return codec.decode_keyset(actor_id, cursor, query_key, kinds=ENTRY_PAGE_KEY)
    except ValueError as error:
        raise ValidationError("invalid pagination cursor") from error


def _validate_list_bounds(start_date: date, end_date: date, limit: int) -> None:
    if end_date < start_date:
        raise ValidationError("end_date cannot precede start_date")
    if (end_date - start_date).days >= MAX_JOURNAL_RANGE_DAYS:
        raise ValidationError("journal range must span at most 366 inclusive days")
    if not 1 <= limit <= 100:
        raise ValidationError("limit must be between 1 and 100")


def journal_list_cursor_key(start_date: date, end_date: date, include_archived: bool) -> str:
    return (
        "journal:entries:v1:"
        f"from={start_date.isoformat()}:to={end_date.isoformat()}:"
        f"archived={str(include_archived).lower()}"
    )


def journal_day_cursor_key(journal_date: date, include_archived: bool) -> str:
    return (
        f"journal:day:v1:date={journal_date.isoformat()}:archived={str(include_archived).lower()}"
    )


def source_command_data(command: CreateSourceCommand) -> dict[str, Any]:
    return {
        "source_type": command.source_type.value,
        "journal_date": command.journal_date.isoformat(),
        "occurred_at": command.occurred_at.isoformat() if command.occurred_at else None,
        "source_recorded_at": command.source_recorded_at.isoformat()
        if command.source_recorded_at
        else None,
        "raw_text": command.raw_text,
        "language": command.language,
        "replaces_source_id": str(command.replaces_source_id)
        if command.replaces_source_id
        else None,
    }


def manual_entry_command_data(command: CreateManualEntryCommand) -> dict[str, Any]:
    return {
        "source_id": str(command.source_id),
        "title": command.title,
        "summary": command.summary,
        "key_points": [
            {"kind": point.kind.value, "text": point.text} for point in command.key_points
        ],
        "project_ids": [str(value) for value in command.project_ids],
        "task_ids": [str(value) for value in command.task_ids],
        "contact_ids": [str(value) for value in command.contact_ids],
    }
