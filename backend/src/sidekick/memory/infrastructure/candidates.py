"""SQL behind the derived-memory candidate and tombstone pages. Read-only, owner-scoped.

The rules these statements apply (what is a candidate, what is a tombstone, how trash, archive,
exclusion and switched-off domains count) are documented in `sidekick.memory.application.queries`,
which also defines the page types returned here.
"""

from collections.abc import Iterable
from datetime import date, datetime, tzinfo
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, Row, and_, or_, select
from sqlalchemy.orm import InstrumentedAttribute, Session, aliased

from sidekick.journal.domain.entry import KeyPointKind
from sidekick.memory.application.queries import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    MemoryCandidate,
    MemoryTombstone,
)
from sidekick.memory.domain import (
    ContactInput,
    JournalEntryInput,
    KeyPointInput,
    LinkedContactInput,
    MemoryKind,
    MemoryRecord,
    ProjectInput,
    TaskInput,
    is_memory_candidate,
)
from sidekick.projects.domain import ProjectStatus
from sidekick.shared.persistence.models import (
    ContactAliasRow,
    ContactRow,
    JournalEntryContactRow,
    JournalEntryProjectRow,
    JournalEntryRow,
    JournalSourceRow,
    MemorySettingsRow,
    MemorySourceRow,
    ProjectContactRow,
    ProjectRow,
    TaskContactRow,
    TaskRow,
)
from sidekick.shared.types import validate_limit

_FLAG_BY_KIND: dict[MemoryKind, InstrumentedAttribute[bool]] = {
    MemoryKind.JOURNAL_ENTRY: MemorySettingsRow.journal,
    MemoryKind.CONTACT: MemorySettingsRow.contacts,
    MemoryKind.PROJECT: MemorySettingsRow.projects,
    MemoryKind.TASK: MemorySettingsRow.tasks,
}


def candidate_page(
    session: Session,
    owner_id: UUID,
    kind: MemoryKind,
    *,
    owner_timezone: tzinfo,
    after: UUID | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
) -> list[MemoryCandidate]:
    """One keyset page of live records of `kind`, ordered by source id, after `after`.

    `owner_timezone` decides which calendar day a completed task belongs to.
    """

    checked = _checked_limit(limit)
    if kind is MemoryKind.JOURNAL_ENTRY:
        return _journal_candidates(session, owner_id, after=after, limit=checked)
    if kind is MemoryKind.CONTACT:
        return _contact_candidates(session, owner_id, after=after, limit=checked)
    if kind is MemoryKind.PROJECT:
        return _project_candidates(session, owner_id, after=after, limit=checked)
    return _task_candidates(
        session, owner_id, owner_timezone=owner_timezone, after=after, limit=checked
    )


def tombstone_page(
    session: Session,
    owner_id: UUID,
    kind: MemoryKind,
    *,
    after: UUID | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
) -> list[MemoryTombstone]:
    """One keyset page of `memory_sources` rows of `kind` that must be removed from the bank.

    A row is a tombstone when it is excluded, when its domain is switched off, or when its source
    is permanently gone or (for journal entries) replaced by a live source. A source in the trash
    is hidden, not a tombstone: its document stays in the bank so a restore costs nothing.
    Non-candidates that still have a live source are not returned here; `candidate_page` reports
    them with `is_candidate` False.
    """

    checked = _checked_limit(limit)
    rows = session.execute(
        select(MemorySourceRow.id, MemorySourceRow.source_id, MemorySourceRow.doc_key)
        .where(
            MemorySourceRow.owner_id == owner_id,
            MemorySourceRow.source_kind == kind.value,
            or_(
                MemorySourceRow.excluded.is_(True),
                ~_domain_enabled(owner_id, kind),
                ~_source_present(owner_id, kind),
            ),
            *_after(MemorySourceRow.id, after),
        )
        .order_by(MemorySourceRow.id)
        .limit(checked)
    ).all()
    return [
        MemoryTombstone(
            memory_source_id=memory_source_id,
            kind=kind,
            source_id=source_id,
            doc_key=doc_key,
        )
        for memory_source_id, source_id, doc_key in rows
    ]


def _checked_limit(limit: int) -> int:
    return validate_limit(
        limit, maximum=MAX_PAGE_SIZE, message=f"page limit must be between 1 and {MAX_PAGE_SIZE}"
    )


def _after(column: InstrumentedAttribute[UUID], after: UUID | None) -> list[ColumnElement[bool]]:
    return [] if after is None else [column > after]


def _domain_enabled(owner_id: UUID, kind: MemoryKind) -> ColumnElement[bool]:
    """True when the owner's memory settings switch this kind on. No settings row means off."""

    flag = _FLAG_BY_KIND[kind]
    return (
        select(MemorySettingsRow.owner_id)
        .where(MemorySettingsRow.owner_id == owner_id, flag.is_(True))
        .exists()
    )


def _excluded(
    owner_id: UUID, kind: MemoryKind, source_id: InstrumentedAttribute[UUID]
) -> ColumnElement[bool]:
    """True when the owner excluded this source from memory. Correlated to the outer source row."""

    return (
        select(MemorySourceRow.id)
        .where(
            MemorySourceRow.owner_id == owner_id,
            MemorySourceRow.source_kind == kind.value,
            MemorySourceRow.source_id == source_id,
            MemorySourceRow.excluded.is_(True),
        )
        .exists()
    )


def _source_present(owner_id: UUID, kind: MemoryKind) -> ColumnElement[bool]:
    """True when the memory row's source still exists, trashed or not, and is not superseded.

    A trashed record is hidden but kept, so it is present. A journal entry whose source is replaced
    by a live source is superseded and counts as gone. Correlated to MemorySourceRow.
    """

    if kind is MemoryKind.JOURNAL_ENTRY:
        return _journal_present(owner_id)
    if kind is MemoryKind.CONTACT:
        return (
            select(ContactRow.id)
            .where(
                ContactRow.id == MemorySourceRow.source_id,
                ContactRow.owner_id == owner_id,
            )
            .exists()
        )
    if kind is MemoryKind.PROJECT:
        return (
            select(ProjectRow.id)
            .where(
                ProjectRow.id == MemorySourceRow.source_id,
                ProjectRow.owner_id == owner_id,
            )
            .exists()
        )
    return (
        select(TaskRow.id)
        .where(
            TaskRow.id == MemorySourceRow.source_id,
            TaskRow.owner_id == owner_id,
        )
        .exists()
    )


def _journal_source_replaced(owner_id: UUID) -> ColumnElement[bool]:
    """True when a live (untrashed) source replaces the plain `JournalSourceRow` in scope.

    Written against the plain `JournalSourceRow` so that the replacement subquery correlates to
    whichever select carries the source in its FROM clause.
    """

    replacement = aliased(JournalSourceRow)
    return (
        select(replacement.id)
        .where(
            replacement.owner_id == owner_id,
            replacement.replaces_source_id == JournalSourceRow.id,
            replacement.trashed_at.is_(None),
        )
        .exists()
    )


def _journal_source_is_live(owner_id: UUID) -> ColumnElement[bool]:
    """A journal source is live when it is not trashed and no live source replaces it."""

    return and_(JournalSourceRow.trashed_at.is_(None), ~_journal_source_replaced(owner_id))


def _journal_present(owner_id: UUID) -> ColumnElement[bool]:
    """The entry and its source exist (in the trash or not) and no live source replaces it."""

    return (
        select(JournalEntryRow.id)
        .select_from(JournalEntryRow)
        .join(
            JournalSourceRow,
            and_(
                JournalSourceRow.id == JournalEntryRow.source_id,
                JournalSourceRow.owner_id == JournalEntryRow.owner_id,
            ),
        )
        .where(
            JournalEntryRow.id == MemorySourceRow.source_id,
            JournalEntryRow.owner_id == owner_id,
            ~_journal_source_replaced(owner_id),
        )
        .exists()
    )


def _candidate(
    kind: MemoryKind,
    source_id: UUID,
    source_updated_at: datetime,
    archived_at: datetime | None,
    record: MemoryRecord,
) -> MemoryCandidate:
    return MemoryCandidate(
        kind=kind,
        source_id=source_id,
        source_updated_at=source_updated_at,
        archived=archived_at is not None,
        is_candidate=is_memory_candidate(record),
        record=record,
    )


def _grouped_names(
    rows: Iterable[Row[UUID, UUID, str]],
) -> dict[UUID, tuple[str, ...]]:
    """Group (parent id, contact id, name) rows; one name per contact, sorted by name."""

    grouped: dict[UUID, dict[UUID, str]] = {}
    for parent_id, contact_id, name in rows:
        grouped.setdefault(parent_id, {})[contact_id] = name
    return {parent_id: tuple(sorted(names.values())) for parent_id, names in grouped.items()}


def _key_point(item: dict[str, Any]) -> KeyPointInput:
    return KeyPointInput(kind=KeyPointKind(str(item["kind"])), text=str(item["text"]))


def _completed_on(completed_at: datetime | None, zone: tzinfo) -> date | None:
    if completed_at is None:
        return None
    return completed_at.astimezone(zone).date()


# --- Journal entries -------------------------------------------------------------------------


def _journal_candidates(
    session: Session, owner_id: UUID, *, after: UUID | None, limit: int
) -> list[MemoryCandidate]:
    rows = session.execute(
        select(
            JournalEntryRow.id,
            JournalEntryRow.updated_at,
            JournalEntryRow.archived_at,
            JournalEntryRow.journal_date,
            JournalEntryRow.title,
            JournalEntryRow.summary,
            JournalEntryRow.key_points,
            JournalSourceRow.raw_text,
        )
        .select_from(JournalEntryRow)
        .join(
            JournalSourceRow,
            and_(
                JournalSourceRow.id == JournalEntryRow.source_id,
                JournalSourceRow.owner_id == JournalEntryRow.owner_id,
            ),
        )
        .where(
            JournalEntryRow.owner_id == owner_id,
            JournalEntryRow.trashed_at.is_(None),
            _journal_source_is_live(owner_id),
            _domain_enabled(owner_id, MemoryKind.JOURNAL_ENTRY),
            ~_excluded(owner_id, MemoryKind.JOURNAL_ENTRY, JournalEntryRow.id),
            *_after(JournalEntryRow.id, after),
        )
        .order_by(JournalEntryRow.id)
        .limit(limit)
    ).all()
    entry_ids = [row[0] for row in rows]
    contacts = _journal_contacts(session, owner_id, entry_ids)
    projects = _journal_projects(session, owner_id, entry_ids)
    candidates: list[MemoryCandidate] = []
    for (
        entry_id,
        updated_at,
        archived_at,
        journal_date,
        title,
        summary,
        key_points,
        raw_text,
    ) in rows:
        record = JournalEntryInput(
            journal_date=journal_date,
            title=title,
            summary=summary,
            key_points=tuple(_key_point(item) for item in key_points),
            raw_text=raw_text,
            contacts=contacts.get(entry_id, ()),
            project_titles=projects.get(entry_id, ()),
        )
        candidates.append(
            _candidate(MemoryKind.JOURNAL_ENTRY, entry_id, updated_at, archived_at, record)
        )
    return candidates


def _journal_contacts(
    session: Session, owner_id: UUID, entry_ids: list[UUID]
) -> dict[UUID, tuple[LinkedContactInput, ...]]:
    if not entry_ids:
        return {}
    rows = session.execute(
        select(
            JournalEntryContactRow.entry_id,
            ContactRow.id,
            ContactRow.display_name,
            ContactRow.relationship,
        )
        .select_from(JournalEntryContactRow)
        .join(
            ContactRow,
            and_(
                ContactRow.id == JournalEntryContactRow.contact_id,
                ContactRow.owner_id == JournalEntryContactRow.owner_id,
            ),
        )
        .where(
            JournalEntryContactRow.owner_id == owner_id,
            JournalEntryContactRow.entry_id.in_(entry_ids),
            ContactRow.trashed_at.is_(None),
        )
    ).all()
    grouped: dict[UUID, dict[UUID, LinkedContactInput]] = {}
    for entry_id, contact_id, name, relationship in rows:
        grouped.setdefault(entry_id, {})[contact_id] = LinkedContactInput(
            name=name, relationship=relationship
        )
    return {
        entry_id: tuple(sorted(linked.values(), key=lambda contact: contact.name))
        for entry_id, linked in grouped.items()
    }


def _journal_projects(
    session: Session, owner_id: UUID, entry_ids: list[UUID]
) -> dict[UUID, tuple[str, ...]]:
    if not entry_ids:
        return {}
    rows = session.execute(
        select(JournalEntryProjectRow.entry_id, ProjectRow.id, ProjectRow.title)
        .select_from(JournalEntryProjectRow)
        .join(
            ProjectRow,
            and_(
                ProjectRow.id == JournalEntryProjectRow.project_id,
                ProjectRow.owner_id == JournalEntryProjectRow.owner_id,
            ),
        )
        .where(
            JournalEntryProjectRow.owner_id == owner_id,
            JournalEntryProjectRow.entry_id.in_(entry_ids),
            ProjectRow.trashed_at.is_(None),
        )
    ).all()
    return _grouped_names(rows)


# --- Contacts --------------------------------------------------------------------------------


def _contact_candidates(
    session: Session, owner_id: UUID, *, after: UUID | None, limit: int
) -> list[MemoryCandidate]:
    rows = session.execute(
        select(
            ContactRow.id,
            ContactRow.updated_at,
            ContactRow.archived_at,
            ContactRow.display_name,
            ContactRow.relationship,
            ContactRow.organization,
            ContactRow.role,
            ContactRow.context_note,
        )
        .where(
            ContactRow.owner_id == owner_id,
            ContactRow.trashed_at.is_(None),
            _domain_enabled(owner_id, MemoryKind.CONTACT),
            ~_excluded(owner_id, MemoryKind.CONTACT, ContactRow.id),
            *_after(ContactRow.id, after),
        )
        .order_by(ContactRow.id)
        .limit(limit)
    ).all()
    contact_ids = [row[0] for row in rows]
    aliases = _contact_aliases(session, owner_id, contact_ids)
    candidates: list[MemoryCandidate] = []
    for (
        contact_id,
        updated_at,
        archived_at,
        display_name,
        relationship,
        organization,
        role,
        context_note,
    ) in rows:
        record = ContactInput(
            display_name=display_name,
            aliases=aliases.get(contact_id, ()),
            relationship=relationship,
            organization=organization,
            role=role,
            context_note=context_note,
        )
        candidates.append(
            _candidate(MemoryKind.CONTACT, contact_id, updated_at, archived_at, record)
        )
    return candidates


def _contact_aliases(
    session: Session, owner_id: UUID, contact_ids: list[UUID]
) -> dict[UUID, tuple[str, ...]]:
    if not contact_ids:
        return {}
    rows = session.execute(
        select(ContactAliasRow.contact_id, ContactAliasRow.display_value)
        .where(
            ContactAliasRow.owner_id == owner_id,
            ContactAliasRow.contact_id.in_(contact_ids),
        )
        .order_by(ContactAliasRow.contact_id, ContactAliasRow.normalized_key)
    ).all()
    grouped: dict[UUID, list[str]] = {}
    for contact_id, display_value in rows:
        grouped.setdefault(contact_id, []).append(display_value)
    return {contact_id: tuple(values) for contact_id, values in grouped.items()}


# --- Projects --------------------------------------------------------------------------------


def _project_candidates(
    session: Session, owner_id: UUID, *, after: UUID | None, limit: int
) -> list[MemoryCandidate]:
    rows = session.execute(
        select(
            ProjectRow.id,
            ProjectRow.updated_at,
            ProjectRow.archived_at,
            ProjectRow.title,
            ProjectRow.description,
            ProjectRow.definition_of_done,
            ProjectRow.status,
            ProjectRow.start_date,
            ProjectRow.target_date,
        )
        .where(
            ProjectRow.owner_id == owner_id,
            ProjectRow.trashed_at.is_(None),
            _domain_enabled(owner_id, MemoryKind.PROJECT),
            ~_excluded(owner_id, MemoryKind.PROJECT, ProjectRow.id),
            *_after(ProjectRow.id, after),
        )
        .order_by(ProjectRow.id)
        .limit(limit)
    ).all()
    project_ids = [row[0] for row in rows]
    contacts = _project_contacts(session, owner_id, project_ids)
    candidates: list[MemoryCandidate] = []
    for (
        project_id,
        updated_at,
        archived_at,
        title,
        description,
        definition_of_done,
        status,
        start_date,
        target_date,
    ) in rows:
        record = ProjectInput(
            title=title,
            description=description,
            definition_of_done=definition_of_done,
            status=ProjectStatus(status),
            start_date=start_date,
            target_date=target_date,
            contact_names=contacts.get(project_id, ()),
        )
        candidates.append(
            _candidate(MemoryKind.PROJECT, project_id, updated_at, archived_at, record)
        )
    return candidates


def _project_contacts(
    session: Session, owner_id: UUID, project_ids: list[UUID]
) -> dict[UUID, tuple[str, ...]]:
    if not project_ids:
        return {}
    rows = session.execute(
        select(ProjectContactRow.project_id, ContactRow.id, ContactRow.display_name)
        .select_from(ProjectContactRow)
        .join(
            ContactRow,
            and_(
                ContactRow.id == ProjectContactRow.contact_id,
                ContactRow.owner_id == ProjectContactRow.owner_id,
            ),
        )
        .where(
            ProjectContactRow.owner_id == owner_id,
            ProjectContactRow.project_id.in_(project_ids),
            ContactRow.trashed_at.is_(None),
        )
    ).all()
    return _grouped_names(rows)


# --- Tasks -----------------------------------------------------------------------------------


def _task_candidates(
    session: Session, owner_id: UUID, *, owner_timezone: tzinfo, after: UUID | None, limit: int
) -> list[MemoryCandidate]:
    rows = session.execute(
        select(
            TaskRow.id,
            TaskRow.updated_at,
            TaskRow.archived_at,
            TaskRow.title,
            TaskRow.description,
            TaskRow.completed_at,
            TaskRow.recurrence.is_not(None),
            ProjectRow.title,
        )
        .select_from(TaskRow)
        .outerjoin(
            ProjectRow,
            and_(
                ProjectRow.id == TaskRow.project_id,
                ProjectRow.owner_id == TaskRow.owner_id,
                ProjectRow.trashed_at.is_(None),
            ),
        )
        .where(
            TaskRow.owner_id == owner_id,
            TaskRow.trashed_at.is_(None),
            _domain_enabled(owner_id, MemoryKind.TASK),
            ~_excluded(owner_id, MemoryKind.TASK, TaskRow.id),
            *_after(TaskRow.id, after),
        )
        .order_by(TaskRow.id)
        .limit(limit)
    ).all()
    task_ids = [row[0] for row in rows]
    contacts = _task_contacts(session, owner_id, task_ids)
    candidates: list[MemoryCandidate] = []
    for (
        task_id,
        updated_at,
        archived_at,
        title,
        description,
        completed_at,
        is_recurring,
        project_title,
    ) in rows:
        record = TaskInput(
            title=title,
            description=description,
            project_title=project_title,
            contact_names=contacts.get(task_id, ()),
            completed_on=_completed_on(completed_at, owner_timezone),
            is_recurring=bool(is_recurring),
        )
        candidates.append(_candidate(MemoryKind.TASK, task_id, updated_at, archived_at, record))
    return candidates


def _task_contacts(
    session: Session, owner_id: UUID, task_ids: list[UUID]
) -> dict[UUID, tuple[str, ...]]:
    """Linked contacts plus the waiting-on contact, each contact once, trashed contacts left out."""

    if not task_ids:
        return {}
    linked = session.execute(
        select(TaskContactRow.task_id, ContactRow.id, ContactRow.display_name)
        .select_from(TaskContactRow)
        .join(
            ContactRow,
            and_(
                ContactRow.id == TaskContactRow.contact_id,
                ContactRow.owner_id == TaskContactRow.owner_id,
            ),
        )
        .where(
            TaskContactRow.owner_id == owner_id,
            TaskContactRow.task_id.in_(task_ids),
            ContactRow.trashed_at.is_(None),
        )
    ).all()
    waiting = session.execute(
        select(TaskRow.id, ContactRow.id, ContactRow.display_name)
        .select_from(TaskRow)
        .join(
            ContactRow,
            and_(
                ContactRow.id == TaskRow.waiting_on_contact_id,
                ContactRow.owner_id == TaskRow.owner_id,
            ),
        )
        .where(
            TaskRow.owner_id == owner_id,
            TaskRow.id.in_(task_ids),
            ContactRow.trashed_at.is_(None),
        )
    ).all()
    return _grouped_names([*linked, *waiting])
