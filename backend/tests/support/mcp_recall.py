"""Shared test helpers moved out of `tests/mcp/test_recall_memory.py`."""

from datetime import UTC, date, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from sidekick.api.app import Container, create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.memory.domain import MemoryKind
from sidekick.projects.domain import ProjectStatus
from sidekick.shared.persistence.models import (
    ContactRow,
    DomainRow,
    JournalEntryRow,
    JournalSourceRow,
    MemorySettingsRow,
    MemorySourceRow,
    ProjectRow,
    TaskRow,
)
from sidekick.shared.types import Actor, new_uuid7
from tests.support.settings import make_settings

NOW = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


JOURNAL_DATE = date(2026, 10, 20)


ALL_SCOPES = frozenset({"journal:read", "contacts:read", "projects:read", "tasks:read"})


def _container(factory: sessionmaker[Session]) -> Container:
    return create_container(make_settings(), factory)


def _owner(container: Container) -> UUID:
    return container.auth.provision_user("owner", "Owner")


def _settings(
    factory: sessionmaker[Session],
    owner_id: UUID,
    *,
    journal: bool = False,
    contacts: bool = False,
    projects: bool = False,
    tasks: bool = False,
) -> None:
    # The owner's row exists from provisioning (all four domains on), so replace it.
    with factory.begin() as session:
        session.merge(
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


def _journal(factory: sessionmaker[Session], owner_id: UUID, title: str) -> UUID:
    source_id = new_uuid7()
    entry_id = new_uuid7()
    raw_text = f"Råtext för {title}"
    with factory.begin() as session:
        session.add(
            JournalSourceRow(
                id=source_id,
                owner_id=owner_id,
                source_type="manual_text",
                journal_date=JOURNAL_DATE,
                raw_text=raw_text,
                content_fingerprint=sha256(raw_text.encode()).hexdigest(),
                replaces_source_id=None,
                created_at=NOW,
                trashed_at=None,
            )
        )
        session.flush()
        session.add(
            JournalEntryRow(
                id=entry_id,
                owner_id=owner_id,
                source_id=source_id,
                journal_date=JOURNAL_DATE,
                title=title,
                summary=None,
                key_points=[],
                version=1,
                created_at=NOW,
                updated_at=NOW,
                archived_at=None,
                trashed_at=None,
            )
        )
    return entry_id


def _contact(
    factory: sessionmaker[Session],
    owner_id: UUID,
    name: str,
    *,
    archived: bool = False,
    trashed: bool = False,
) -> UUID:
    contact_id = new_uuid7()
    with factory.begin() as session:
        session.add(
            ContactRow(
                id=contact_id,
                owner_id=owner_id,
                display_name=name,
                display_name_key=name.casefold(),
                context_note=None,
                relationship=None,
                organization=None,
                created_at=NOW,
                updated_at=NOW,
                archived=archived,
                archived_at=NOW if archived else None,
                version=1,
                trashed_at=NOW if trashed else None,
            )
        )
    return contact_id


def _task(
    factory: sessionmaker[Session], owner_id: UUID, title: str, *, completed_at: datetime | None
) -> UUID:
    task_id = new_uuid7()
    with factory.begin() as session:
        session.add(
            TaskRow(
                id=task_id,
                owner_id=owner_id,
                project_id=None,
                title=title,
                description=None,
                status="completed" if completed_at is not None else "todo",
                priority="normal",
                completed_at=completed_at,
                created_at=NOW,
                updated_at=NOW,
                version=1,
                attention_requested=False,
                waiting_on_contact_id=None,
                waiting_since=None,
                recurrence=None,
                trashed_at=None,
            )
        )
    return task_id


def _project(factory: sessionmaker[Session], owner_id: UUID, title: str) -> UUID:
    domain_id = new_uuid7()
    project_id = new_uuid7()
    with factory.begin() as session:
        session.add(
            DomainRow(
                id=domain_id,
                owner_id=owner_id,
                name="Område",
                description=None,
                status="active",
                created_at=NOW,
                updated_at=NOW,
                version=1,
                review_cadence=None,
                last_reviewed_at=None,
                trashed_at=None,
            )
        )
        session.flush()
        session.add(
            ProjectRow(
                id=project_id,
                owner_id=owner_id,
                domain_id=domain_id,
                title=title,
                description=None,
                status=ProjectStatus.ACTIVE.value,
                start_date=date(2026, 9, 1),
                target_date=None,
                created_at=NOW,
                updated_at=NOW,
                archived_at=None,
                version=1,
                definition_of_done=None,
                trashed_at=None,
            )
        )
    return project_id


def _memory_row(
    factory: sessionmaker[Session], owner_id: UUID, kind: MemoryKind, source_id: UUID
) -> str:
    """A `memory_sources` row and the opaque document id the provider knows it by."""

    row_id = new_uuid7()
    doc_key = f"d1_{row_id.hex}"
    with factory.begin() as session:
        session.add(
            MemorySourceRow(
                id=row_id,
                owner_id=owner_id,
                source_kind=kind.value,
                source_id=source_id,
                doc_key=doc_key,
                fingerprint=sha256(str(source_id).encode()).hexdigest(),
                pipeline_version=1,
                status="retained",
                attempts=1,
                next_attempt_at=None,
                operation_id="fake-op-000001",
                source_updated_at=NOW,
                retained_at=NOW,
                failure_category=None,
                excluded=False,
            )
        )
    return doc_key


def _server(container: Container, actor: Actor) -> Any:
    return create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)


def _structured(content: dict[str, Any] | None) -> dict[str, Any]:
    assert content is not None
    return content
