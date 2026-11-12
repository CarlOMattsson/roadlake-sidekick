"""Shared test helpers moved out of `tests/memory/test_queries.py`."""

from datetime import UTC, date, datetime
from hashlib import sha256
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from sidekick.memory.domain import (
    MemoryKind,
)
from sidekick.shared.persistence.models import (
    ContactRow,
    DomainRow,
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
    UserRow,
)
from sidekick.shared.types import new_uuid7

NOW = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


JOURNAL_DATE = date(2026, 10, 20)


LONG_TEXT = "x" * 120


def _owner(factory: sessionmaker[Session]) -> UUID:
    owner_id = new_uuid7()
    with factory.begin() as session:
        session.add(
            UserRow(
                id=owner_id,
                username=f"memory-{owner_id.hex}",
                display_name="Minne",
                active=True,
                created_at=NOW,
            )
        )
    return owner_id


def _settings(
    factory: sessionmaker[Session],
    owner_id: UUID,
    *,
    journal: bool = False,
    contacts: bool = False,
    projects: bool = False,
    tasks: bool = False,
) -> None:
    with factory.begin() as session:
        session.add(
            MemorySettingsRow(
                owner_id=owner_id,
                journal=journal,
                contacts=contacts,
                projects=projects,
                tasks=tasks,
                paused=False,
                version=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )


def _enable_all(factory: sessionmaker[Session], owner_id: UUID) -> None:
    _settings(factory, owner_id, journal=True, contacts=True, projects=True, tasks=True)


def _domain(factory: sessionmaker[Session], owner_id: UUID) -> UUID:
    domain_id = new_uuid7()
    with factory.begin() as session:
        session.add(
            DomainRow(
                id=domain_id,
                owner_id=owner_id,
                name="Drift",
                description=None,
                status="active",
                created_at=NOW,
                updated_at=NOW,
                version=1,
            )
        )
    return domain_id


def _contact(
    factory: sessionmaker[Session],
    owner_id: UUID,
    name: str,
    *,
    context_note: str | None = None,
    relationship: str | None = None,
    organization: str | None = None,
    trashed: bool = False,
    archived: bool = False,
) -> UUID:
    contact_id = new_uuid7()
    with factory.begin() as session:
        session.add(
            ContactRow(
                id=contact_id,
                owner_id=owner_id,
                display_name=name,
                display_name_key=name.casefold(),
                context_note=context_note,
                relationship=relationship,
                organization=organization,
                created_at=NOW,
                updated_at=NOW,
                archived=archived,
                archived_at=NOW if archived else None,
                version=1,
                trashed_at=NOW if trashed else None,
            )
        )
    return contact_id


def _project(
    factory: sessionmaker[Session],
    owner_id: UUID,
    domain_id: UUID,
    title: str,
    *,
    description: str | None = None,
    status: str = "active",
    contacts: tuple[UUID, ...] = (),
    target_date: date | None = None,
    trashed: bool = False,
) -> UUID:
    project_id = new_uuid7()
    with factory.begin() as session:
        session.add(
            ProjectRow(
                id=project_id,
                owner_id=owner_id,
                domain_id=domain_id,
                title=title,
                description=description,
                status=status,
                start_date=None,
                target_date=target_date,
                created_at=NOW,
                updated_at=NOW,
                version=1,
                trashed_at=NOW if trashed else None,
            )
        )
        session.flush()  # No ORM relationship orders the link rows after the parent row.
        for contact_id in contacts:
            session.add(
                ProjectContactRow(
                    owner_id=owner_id,
                    project_id=project_id,
                    contact_id=contact_id,
                    created_at=NOW,
                )
            )
    return project_id


def _task(
    factory: sessionmaker[Session],
    owner_id: UUID,
    title: str,
    *,
    project_id: UUID | None = None,
    description: str | None = None,
    completed_at: datetime | None = None,
    waiting_on: UUID | None = None,
    contacts: tuple[UUID, ...] = (),
    recurring: bool = False,
    trashed: bool = False,
) -> UUID:
    task_id = new_uuid7()
    with factory.begin() as session:
        session.add(
            TaskRow(
                id=task_id,
                owner_id=owner_id,
                project_id=project_id,
                title=title,
                description=description,
                status="completed" if completed_at is not None else "todo",
                priority="normal",
                completed_at=completed_at,
                created_at=NOW,
                updated_at=NOW,
                version=1,
                attention_requested=False,
                waiting_on_contact_id=waiting_on,
                waiting_since=NOW if waiting_on is not None else None,
                recurrence={"frequency": "weekly"} if recurring else None,
                trashed_at=NOW if trashed else None,
            )
        )
        session.flush()
        for contact_id in contacts:
            session.add(
                TaskContactRow(
                    owner_id=owner_id,
                    task_id=task_id,
                    contact_id=contact_id,
                    created_at=NOW,
                )
            )
    return task_id


def _source(
    factory: sessionmaker[Session],
    owner_id: UUID,
    raw_text: str,
    *,
    replaces: UUID | None = None,
    trashed: bool = False,
) -> UUID:
    source_id = new_uuid7()
    with factory.begin() as session:
        session.add(
            JournalSourceRow(
                id=source_id,
                owner_id=owner_id,
                source_type="manual_text",
                journal_date=JOURNAL_DATE,
                raw_text=raw_text,
                content_fingerprint=sha256(raw_text.encode()).hexdigest(),
                replaces_source_id=replaces,
                created_at=NOW,
                trashed_at=NOW if trashed else None,
            )
        )
    return source_id


def _entry(
    factory: sessionmaker[Session],
    owner_id: UUID,
    source_id: UUID,
    title: str,
    *,
    summary: str | None = None,
    key_points: list[dict[str, str]] | None = None,
    contacts: tuple[UUID, ...] = (),
    projects: tuple[UUID, ...] = (),
    archived: bool = False,
    trashed: bool = False,
) -> UUID:
    entry_id = new_uuid7()
    with factory.begin() as session:
        session.add(
            JournalEntryRow(
                id=entry_id,
                owner_id=owner_id,
                source_id=source_id,
                journal_date=JOURNAL_DATE,
                title=title,
                summary=summary,
                key_points=key_points or [],
                version=1,
                created_at=NOW,
                updated_at=NOW,
                archived_at=NOW if archived else None,
                trashed_at=NOW if trashed else None,
            )
        )
        session.flush()
        for contact_id in contacts:
            session.add(
                JournalEntryContactRow(
                    owner_id=owner_id,
                    entry_id=entry_id,
                    contact_id=contact_id,
                    created_at=NOW,
                )
            )
        for project_id in projects:
            session.add(
                JournalEntryProjectRow(
                    owner_id=owner_id,
                    entry_id=entry_id,
                    project_id=project_id,
                    created_at=NOW,
                )
            )
    return entry_id


def _memory_source(
    factory: sessionmaker[Session],
    owner_id: UUID,
    kind: MemoryKind,
    source_id: UUID,
    *,
    excluded: bool = False,
) -> UUID:
    memory_id = new_uuid7()
    with factory.begin() as session:
        session.add(
            MemorySourceRow(
                id=memory_id,
                owner_id=owner_id,
                source_kind=kind.value,
                source_id=source_id,
                doc_key=f"doc-{memory_id}",
                fingerprint=sha256(str(source_id).encode()).hexdigest(),
                pipeline_version=1,
                status="pending",
                attempts=0,
                next_attempt_at=None,
                operation_id=None,
                source_updated_at=NOW,
                retained_at=None,
                failure_category=None,
                excluded=excluded,
            )
        )
    return memory_id
