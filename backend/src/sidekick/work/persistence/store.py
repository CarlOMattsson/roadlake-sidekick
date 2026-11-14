"""The store of the Work use cases."""

from collections.abc import Mapping, Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from sidekick.projects.domain import Project, ProjectStatus
from sidekick.shared.observability import TelemetryPort
from sidekick.shared.persistence.stores.base import StoreBase
from sidekick.shared.types import KeyValue, TxSession
from sidekick.tasks.domain import Task, TaskStatus
from sidekick.tasks.persistence import ProjectTaskStore
from sidekick.work.persistence.listing import WorkListStore
from sidekick.work.persistence.steps_actions import StepActionStore
from sidekick.work.persistence.structure import WorkStructureStore
from sidekick.work.persistence.tags import RecordTagRelay, WorkTagStore


class SqlWorkStore(WorkStructureStore, StepActionStore, WorkListStore, RecordTagRelay, StoreBase):
    """The Work operations plus the Project, Task and tag reads the work lists and views need.

    Work shows Projects and Tasks beside Domains, Processes, Steps and Actions, so the reads of
    the Project and Task operations are delegated to them, and the tag operations to the tag store.
    """

    def __init__(
        self, session_factory: sessionmaker[Session], telemetry: TelemetryPort | None = None
    ) -> None:
        super().__init__(session_factory, telemetry)
        self._tags = WorkTagStore

    @staticmethod
    def record_tag_slugs(
        session: TxSession,
        owner_id: UUID,
        limit: int = 5000,
        record_ids: Mapping[str, Sequence[UUID]] | None = None,
    ) -> dict[tuple[str, UUID], tuple[str, ...]]:
        return WorkTagStore.record_tag_slugs(session, owner_id, limit, record_ids)

    @staticmethod
    def get_task(
        session: TxSession,
        owner_id: UUID,
        task_id: UUID,
        include_archived: bool = False,
    ) -> Task:
        return ProjectTaskStore.get_task(session, owner_id, task_id, include_archived)

    @staticmethod
    def list_projects(
        session: TxSession,
        owner_id: UUID,
        limit: int,
        status: ProjectStatus | None = None,
        after: tuple[KeyValue, ...] | None = None,
        include_archived: bool = False,
    ) -> list[Project]:
        return ProjectTaskStore.list_projects(
            session, owner_id, limit, status, after, include_archived
        )

    @staticmethod
    def list_tasks(
        session: TxSession,
        owner_id: UUID,
        limit: int,
        project_id: UUID | None = None,
        status: TaskStatus | None = None,
        after: tuple[KeyValue, ...] | None = None,
        include_archived: bool = False,
    ) -> list[Task]:
        return ProjectTaskStore.list_tasks(
            session, owner_id, limit, project_id, status, after, include_archived
        )

    @staticmethod
    def estimate_totals(
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
    ) -> dict[str, int]:
        return ProjectTaskStore.estimate_totals(
            session,
            owner_id,
            now=now,
            project_id=project_id,
            agenda_start=agenda_start,
            agenda_end=agenda_end,
            task_ids=task_ids,
            actionable_now=actionable_now,
            focus_only=focus_only,
        )

    @staticmethod
    def project_task_counts(
        session: TxSession, owner_id: UUID, *, project_id: UUID, now: datetime
    ) -> dict[str, int]:
        return ProjectTaskStore.project_task_counts(
            session, owner_id, project_id=project_id, now=now
        )

    @staticmethod
    def task_step_counts(session: TxSession, owner_id: UUID, *, task_id: UUID) -> dict[str, int]:
        return ProjectTaskStore.task_step_counts(session, owner_id, task_id=task_id)

    @staticmethod
    def board_manual_statuses(
        session: TxSession,
        owner_id: UUID,
        status: str | None = None,
        project_id: UUID | None = None,
    ) -> tuple[str, ...]:
        return ProjectTaskStore.board_manual_statuses(session, owner_id, status, project_id)

    @staticmethod
    def project_titles(
        session: TxSession, owner_id: UUID, project_ids: tuple[UUID, ...]
    ) -> dict[UUID, str]:
        return ProjectTaskStore.project_titles(session, owner_id, project_ids)

    @staticmethod
    def domain_accents(
        session: TxSession, owner_id: UUID, domain_ids: tuple[UUID, ...]
    ) -> dict[UUID, str | None]:
        return ProjectTaskStore.domain_accents(session, owner_id, domain_ids)

    @staticmethod
    def process_domain_ids(
        session: TxSession, owner_id: UUID, process_ids: tuple[UUID, ...]
    ) -> dict[UUID, UUID]:
        return ProjectTaskStore.process_domain_ids(session, owner_id, process_ids)

    @staticmethod
    def project_domain_ids(
        session: TxSession, owner_id: UUID, project_ids: tuple[UUID, ...]
    ) -> dict[UUID, UUID]:
        return ProjectTaskStore.project_domain_ids(session, owner_id, project_ids)
