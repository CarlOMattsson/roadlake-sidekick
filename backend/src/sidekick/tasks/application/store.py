"""The store port of the Task use cases."""

from __future__ import annotations

from datetime import datetime
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
from sidekick.tasks.domain import Task, TaskStatus, TaskStatusHistory
from sidekick.work.domain import Domain, Process, Step
from sidekick.work.domain.planning import WorkTag


class TaskStore(TransactionalStore, IdempotentStore, AuditingStore, Protocol):
    """Concrete port needed for atomic Task and idempotency operations."""

    def list_board_column_tasks(
        self, session: TxSession, owner_id: UUID, status: TaskStatus, limit: int
    ) -> list[Task]: ...
    def list_tasks(
        self,
        session: TxSession,
        owner_id: UUID,
        limit: int,
        project_id: UUID | None = None,
        status: TaskStatus | None = None,
        after: tuple[KeyValue, ...] | None = None,
        include_archived: bool = False,
        process_id: UUID | None = None,
        unsorted: bool = False,
    ) -> list[Task]: ...
    def get_task(
        self,
        session: TxSession,
        owner_id: UUID,
        task_id: UUID,
        include_archived: bool = False,
        for_update: bool = False,
        include_hidden: bool = False,
    ) -> Task: ...
    def save_task(
        self, session: TxSession, task: Task, expected_version: int | None = None
    ) -> None: ...
    def save_step(self, session: TxSession, step: Step) -> None: ...
    def get_project(
        self,
        session: TxSession,
        owner_id: UUID,
        project_id: UUID,
        include_archived: bool = False,
    ) -> Project: ...
    def get_domain(self, session: TxSession, owner_id: UUID, domain_id: UUID) -> Domain: ...
    def get_process(self, session: TxSession, owner_id: UUID, process_id: UUID) -> Process: ...
    def get_contact(self, session: TxSession, owner_id: UUID, contact_id: UUID) -> Contact: ...
    def link_task_contact(
        self, session: TxSession, owner_id: UUID, task_id: UUID, contact_id: UUID
    ) -> datetime | None: ...
    def find_work_tag_by_slug(
        self, session: TxSession, owner_id: UUID, slug: str
    ) -> WorkTag | None: ...
    def save_work_tag(
        self, session: TxSession, tag: WorkTag, expected_version: int | None = None
    ) -> None: ...
    def replace_record_tags(
        self,
        session: TxSession,
        owner_id: UUID,
        kind: str,
        record_id: UUID,
        tag_ids: tuple[UUID, ...],
    ) -> None: ...
    def list_record_tags(
        self, session: TxSession, owner_id: UUID, kind: str, record_id: UUID
    ) -> list[WorkTag]: ...
    def append_task_status_history(
        self,
        session: TxSession,
        *,
        owner_id: UUID,
        task_id: UUID,
        from_status: TaskStatus | None,
        to_status: TaskStatus,
        changed_at: datetime,
        source: str,
    ) -> None: ...
    def list_task_status_history(
        self, session: TxSession, owner_id: UUID, task_id: UUID, limit: int
    ) -> list[TaskStatusHistory]: ...
    def project_titles(
        self, session: TxSession, owner_id: UUID, project_ids: tuple[UUID, ...]
    ) -> dict[UUID, str]: ...
    def process_domain_ids(
        self, session: TxSession, owner_id: UUID, process_ids: tuple[UUID, ...]
    ) -> dict[UUID, UUID]: ...
    def project_domain_ids(
        self, session: TxSession, owner_id: UUID, project_ids: tuple[UUID, ...]
    ) -> dict[UUID, UUID]: ...
    def task_step_counts(
        self, session: TxSession, owner_id: UUID, *, task_id: UUID
    ) -> dict[str, int]: ...
    def list_steps(
        self,
        session: TxSession,
        owner_id: UUID,
        task_id: UUID,
        limit: int,
        offset: int = 0,
        include_archived: bool = False,
    ) -> list[Step]: ...
    def list_live_steps_by_ids(
        self, session: TxSession, owner_id: UUID, step_ids: tuple[UUID, ...]
    ) -> dict[UUID, Step]: ...
