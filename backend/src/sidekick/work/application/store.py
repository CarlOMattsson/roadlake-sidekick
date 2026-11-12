"""The store port of the Work context use cases."""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sidekick.projects.domain import Project, ProjectStatus
from sidekick.shared.types import (
    AuditingStore,
    IdempotentStore,
    KeyValue,
    TransactionalStore,
    TxSession,
)
from sidekick.tasks.domain import Task, TaskStatus
from sidekick.work.domain import Action, Domain, Process, Step
from sidekick.work.domain.planning import WorkTag
from sidekick.work.listing import WorkKey, WorkListSpec, WorkRecord


class ContextStore(TransactionalStore, IdempotentStore, AuditingStore, Protocol):
    def list_domains(
        self,
        session: TxSession,
        owner_id: UUID,
        limit: int,
        after: tuple[KeyValue, ...] | None = None,
        include_archived: bool = False,
    ) -> list[Domain]: ...
    def list_projects(
        self,
        session: TxSession,
        owner_id: UUID,
        limit: int,
        status: ProjectStatus | None = None,
        after: tuple[KeyValue, ...] | None = None,
        include_archived: bool = False,
    ) -> list[Project]: ...
    def list_tasks(
        self,
        session: TxSession,
        owner_id: UUID,
        limit: int,
        project_id: UUID | None = None,
        status: TaskStatus | None = None,
        after: tuple[KeyValue, ...] | None = None,
        include_archived: bool = False,
    ) -> list[Task]: ...
    def estimate_totals(
        self,
        session: TxSession,
        owner_id: UUID,
        *,
        now: datetime,
        project_id: UUID | None = None,
        agenda_start: datetime | None = None,
        agenda_end: datetime | None = None,
        task_ids: tuple[UUID, ...] = (),
        actionable_now: bool = False,
        focus_only: bool = False,
    ) -> dict[str, int]: ...
    def project_task_counts(
        self, session: TxSession, owner_id: UUID, *, project_id: UUID, now: datetime
    ) -> dict[str, int]: ...
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
    def list_actions(
        self,
        session: TxSession,
        owner_id: UUID,
        step_id: UUID,
        limit: int,
        offset: int = 0,
        include_archived: bool = False,
    ) -> list[Action]: ...
    def board_manual_statuses(
        self,
        session: TxSession,
        owner_id: UUID,
        status: str | None = None,
        project_id: UUID | None = None,
    ) -> tuple[str, ...]: ...
    def project_titles(
        self, session: TxSession, owner_id: UUID, project_ids: tuple[UUID, ...]
    ) -> dict[UUID, str]: ...
    def domain_accents(
        self, session: TxSession, owner_id: UUID, domain_ids: tuple[UUID, ...]
    ) -> dict[UUID, str | None]: ...
    def process_domain_ids(
        self, session: TxSession, owner_id: UUID, process_ids: tuple[UUID, ...]
    ) -> dict[UUID, UUID]: ...
    def project_domain_ids(
        self, session: TxSession, owner_id: UUID, project_ids: tuple[UUID, ...]
    ) -> dict[UUID, UUID]: ...
    def get_domain(self, session: TxSession, owner_id: UUID, domain_id: UUID) -> Domain: ...
    def save_domain(
        self, session: TxSession, domain: Domain, expected_version: int | None = None
    ) -> None: ...
    def record_tag_slugs(
        self,
        session: TxSession,
        owner_id: UUID,
        limit: int = 5000,
        record_ids: Mapping[str, Sequence[UUID]] | None = None,
    ) -> dict[tuple[str, UUID], tuple[str, ...]]: ...
    def work_list_keys(
        self,
        session: TxSession,
        owner_id: UUID,
        spec: WorkListSpec,
        *,
        after: tuple[KeyValue, ...] | None,
        limit: int,
    ) -> list[WorkKey]: ...
    def work_agenda_group_counts(
        self, session: TxSession, owner_id: UUID, spec: WorkListSpec
    ) -> dict[str, int]: ...
    def work_records_by_ids(
        self, session: TxSession, owner_id: UUID, ids_by_kind: Mapping[str, Sequence[UUID]]
    ) -> dict[str, dict[UUID, WorkRecord]]: ...
    def list_record_tags(
        self, session: TxSession, owner_id: UUID, kind: str, record_id: UUID
    ) -> list[WorkTag]: ...
    def replace_record_tags(
        self,
        session: TxSession,
        owner_id: UUID,
        kind: str,
        record_id: UUID,
        tag_ids: tuple[UUID, ...],
    ) -> None: ...
    def find_work_tag_by_slug(
        self, session: TxSession, owner_id: UUID, slug: str
    ) -> WorkTag | None: ...
    def save_work_tag(
        self, session: TxSession, tag: WorkTag, expected_version: int | None = None
    ) -> None: ...
    def list_processes(
        self,
        session: TxSession,
        owner_id: UUID,
        limit: int,
        domain_id: UUID | None = None,
        after: tuple[KeyValue, ...] | None = None,
        include_archived: bool = False,
    ) -> list[Process]: ...
    def get_process(self, session: TxSession, owner_id: UUID, process_id: UUID) -> Process: ...
    def save_process(
        self, session: TxSession, process: Process, expected_version: int | None = None
    ) -> None: ...
