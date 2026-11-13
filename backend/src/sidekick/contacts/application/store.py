"""The store port Contact use cases depend on."""

from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from sidekick.contacts.domain.contact import Contact
from sidekick.projects.domain import Project
from sidekick.shared.types import (
    AuditingStore,
    IdempotentStore,
    KeyValue,
    TransactionalStore,
    TxSession,
)
from sidekick.tasks.domain import Task
from sidekick.work.domain.tag_assignment import RecordTagStore


class ContactStore(TransactionalStore, IdempotentStore, AuditingStore, RecordTagStore, Protocol):
    """Concrete port needed for atomic Contact and idempotency operations."""

    def contact_display_names(
        self, session: TxSession, owner_id: UUID, contact_ids: tuple[UUID, ...]
    ) -> dict[UUID, tuple[str, bool]]: ...
    def list_contacts(
        self,
        session: TxSession,
        owner_id: UUID,
        limit: int,
        q: str | None = None,
        include_archived: bool = False,
        after: tuple[KeyValue, ...] | None = None,
        tags: tuple[str, ...] = (),
        tag_match: str = "any",
    ) -> list[Contact]: ...
    def phonetic_contacts(
        self,
        session: TxSession,
        owner_id: UUID,
        query: str,
        *,
        include_archived: bool = False,
        limit: int = 25,
    ) -> list[Contact]: ...
    def get_contact(
        self,
        session: TxSession,
        owner_id: UUID,
        contact_id: UUID,
        include_archived: bool = False,
    ) -> Contact: ...
    def save_contact(
        self, session: TxSession, contact: Contact, expected_version: int | None = None
    ) -> None: ...
    def get_project(self, session: TxSession, owner_id: UUID, project_id: UUID) -> Project: ...
    def get_task(self, session: TxSession, owner_id: UUID, task_id: UUID) -> Task: ...
    def link_project_contact(
        self, session: TxSession, owner_id: UUID, project_id: UUID, contact_id: UUID
    ) -> datetime | None: ...
    def unlink_project_contact(
        self, session: TxSession, owner_id: UUID, project_id: UUID, contact_id: UUID
    ) -> None: ...
    def list_project_contacts(
        self,
        session: TxSession,
        owner_id: UUID,
        project_id: UUID,
        limit: int,
        after: tuple[KeyValue, ...] | None = None,
    ) -> list[Contact]: ...
    def link_task_contact(
        self, session: TxSession, owner_id: UUID, task_id: UUID, contact_id: UUID
    ) -> datetime | None: ...
    def unlink_task_contact(
        self, session: TxSession, owner_id: UUID, task_id: UUID, contact_id: UUID
    ) -> None: ...
    def list_task_contacts(
        self,
        session: TxSession,
        owner_id: UUID,
        task_id: UUID,
        limit: int,
        after: tuple[KeyValue, ...] | None = None,
    ) -> list[Contact]: ...
    def list_linked_projects(
        self,
        session: TxSession,
        owner_id: UUID,
        contact_id: UUID,
        limit: int,
        after: tuple[KeyValue, ...] | None = None,
        include_completed: bool = False,
    ) -> list[Project]: ...
    def list_linked_tasks(
        self,
        session: TxSession,
        owner_id: UUID,
        contact_id: UUID,
        limit: int,
        after: tuple[KeyValue, ...] | None = None,
        include_completed: bool = False,
    ) -> list[Task]: ...
    def list_linked_journal_entries(
        self,
        session: TxSession,
        owner_id: UUID,
        contact_id: UUID,
        limit: int,
    ) -> list[tuple[UUID, date, str]]: ...
