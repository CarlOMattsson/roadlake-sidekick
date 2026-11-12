"""Projects, Tasks, board reads and Task status history."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from sidekick.projects.domain import Project, ProjectStatus
from sidekick.projects.persistence import project_from_row, project_to_row
from sidekick.shared.errors import (
    ConflictError,
    NotFoundError,
)
from sidekick.shared.persistence.models import (
    DomainRow,
    ProcessRow,
    ProjectRow,
    StepRow,
    TaskRow,
    TaskStatusHistoryRow,
)
from sidekick.shared.persistence.stores.keyset import rows_after
from sidekick.shared.persistence.stores.task_parents import task_parents_live
from sidekick.shared.types import KeyValue, new_uuid7
from sidekick.tasks.domain import Priority, RecurrenceRule, Task, TaskStatus, TaskStatusHistory
from sidekick.work.domain.planning import parse_cadence


def task_from_row(row: TaskRow) -> Task:
    return Task(
        id=row.id,
        owner_id=row.owner_id,
        project_id=row.project_id,
        domain_id=row.domain_id,
        process_id=row.process_id,
        title=row.title,
        description=row.description,
        status=TaskStatus(row.status),
        priority=Priority(row.priority),
        due_at=row.due_at,
        completed_at=row.completed_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        version=row.version,
        attention_requested=row.attention_requested,
        archived_at=row.archived_at,
        board_rank=row.board_rank,
        not_before=row.not_before,
        estimated_minutes=row.estimated_minutes,
        waiting_since=row.waiting_since,
        follow_up_at=row.follow_up_at,
        waiting_on_contact_id=row.waiting_on_contact_id,
        blocked_reminder_cadence=parse_cadence(row.blocked_reminder_cadence),
        blocked_reminder_snoozed_until=row.blocked_reminder_snoozed_until,
        blocked_last_reminded_at=row.blocked_last_reminded_at,
        recurrence=RecurrenceRule.from_data(row.recurrence),
        last_completed_at=row.last_completed_at,
    )


def task_to_row(task: Task) -> TaskRow:
    return TaskRow(
        id=task.id,
        owner_id=task.owner_id,
        project_id=task.project_id,
        domain_id=task.domain_id,
        process_id=task.process_id,
        title=task.title,
        description=task.description,
        status=task.status.value,
        priority=task.priority.value,
        due_at=task.due_at,
        completed_at=task.completed_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
        archived_at=task.archived_at,
        version=task.version,
        attention_requested=task.attention_requested,
        board_rank=task.board_rank,
        not_before=task.not_before,
        estimated_minutes=task.estimated_minutes,
        waiting_since=task.waiting_since,
        follow_up_at=task.follow_up_at,
        waiting_on_contact_id=task.waiting_on_contact_id,
        blocked_reminder_cadence=(
            task.blocked_reminder_cadence.value if task.blocked_reminder_cadence else None
        ),
        blocked_reminder_snoozed_until=task.blocked_reminder_snoozed_until,
        blocked_last_reminded_at=task.blocked_last_reminded_at,
        recurrence=task.recurrence.to_data() if task.recurrence else None,
        last_completed_at=task.last_completed_at,
    )


class ProjectTaskStore:
    """Projects, Tasks, board reads and Task status history.

    Mixin composed into ``SqlAlchemyStore``; methods are static and owner-filtered.
    """

    @staticmethod
    def get_project(
        session: Session, owner_id: UUID, project_id: UUID, include_archived: bool = False
    ) -> Project:
        statement = select(ProjectRow).where(
            ProjectRow.id == project_id,
            ProjectRow.owner_id == owner_id,
            ProjectRow.trashed_at.is_(None),
        )
        if not include_archived:
            statement = statement.where(ProjectRow.archived_at.is_(None))
        row = session.scalar(statement)
        if row is None:
            raise NotFoundError("project not found")
        return project_from_row(row)

    @staticmethod
    def list_projects(
        session: Session,
        owner_id: UUID,
        limit: int,
        status: ProjectStatus | None = None,
        after: tuple[KeyValue, ...] | None = None,
        include_archived: bool = False,
    ) -> list[Project]:
        """Newest change first; `after` is the (updated_at, id) of the last Project already read."""

        statement = select(ProjectRow).where(
            ProjectRow.owner_id == owner_id, ProjectRow.trashed_at.is_(None)
        )
        if not include_archived:
            statement = statement.where(ProjectRow.archived_at.is_(None))
        if status is not None:
            statement = statement.where(ProjectRow.status == status.value)
        if after is not None:
            statement = statement.where(
                rows_after((ProjectRow.updated_at, ProjectRow.id), after, descending=True)
            )
        rows = session.scalars(
            statement.order_by(ProjectRow.updated_at.desc(), ProjectRow.id.desc()).limit(limit)
        )
        return [project_from_row(row) for row in rows]

    @staticmethod
    def save_project(
        session: Session, project: Project, expected_version: int | None = None
    ) -> None:
        row = session.scalar(
            select(ProjectRow).where(ProjectRow.id == project.id).with_for_update()
        )
        if row is None:
            session.add(project_to_row(project))
            return
        if row.owner_id != project.owner_id:
            raise NotFoundError("project not found")
        if expected_version is not None and row.version != expected_version:
            raise ConflictError("stale project version")
        for field in (
            "title",
            "domain_id",
            "description",
            "status",
            "start_date",
            "target_date",
            "definition_of_done",
            "updated_at",
            "version",
        ):
            value = getattr(project, field)
            setattr(row, field, value.value if isinstance(value, ProjectStatus) else value)

    @staticmethod
    def get_task(
        session: Session,
        owner_id: UUID,
        task_id: UUID,
        include_archived: bool = False,
        for_update: bool = False,
        include_hidden: bool = False,
    ) -> Task:
        """One Task; `include_hidden` also finds one whose parent is in the trash (a replay)."""

        filters = [
            TaskRow.id == task_id,
            TaskRow.owner_id == owner_id,
            TaskRow.trashed_at.is_(None),
        ]
        if not include_hidden:
            filters.append(task_parents_live())
        if not include_archived:
            filters.append(TaskRow.archived_at.is_(None))
        statement = select(TaskRow).where(*filters)
        if for_update:
            # Lock the row so a guard on its current state holds until this transaction ends.
            statement = statement.with_for_update()
        row = session.scalar(statement)
        if row is None:
            raise NotFoundError("task not found")
        return task_from_row(row)

    @staticmethod
    def list_tasks(
        session: Session,
        owner_id: UUID,
        limit: int,
        project_id: UUID | None = None,
        status: TaskStatus | None = None,
        after: tuple[KeyValue, ...] | None = None,
        include_archived: bool = False,
        process_id: UUID | None = None,
        unsorted: bool = False,
    ) -> list[Task]:
        """Newest change first; `after` is the (updated_at, id) of the last Task already read."""

        statement = select(TaskRow).where(
            TaskRow.owner_id == owner_id, TaskRow.trashed_at.is_(None), task_parents_live()
        )
        if not include_archived:
            statement = statement.where(TaskRow.archived_at.is_(None))
        if project_id is not None:
            statement = statement.where(TaskRow.project_id == project_id)
        # A Task selects exactly one context, so filtering by Process needs no join.
        if process_id is not None:
            statement = statement.where(TaskRow.process_id == process_id)
        # Unsorted: no Domain, Project or Process context at all. A Process-linked Task is
        # sorted, because its Domain comes from the Process.
        if unsorted:
            statement = statement.where(
                TaskRow.domain_id.is_(None),
                TaskRow.project_id.is_(None),
                TaskRow.process_id.is_(None),
            )
        if status is not None:
            statement = statement.where(TaskRow.status == status.value)
        if after is not None:
            statement = statement.where(
                rows_after((TaskRow.updated_at, TaskRow.id), after, descending=True)
            )
        rows = session.scalars(
            statement.order_by(TaskRow.updated_at.desc(), TaskRow.id.desc()).limit(limit)
        )
        return [task_from_row(row) for row in rows]

    @staticmethod
    def estimate_totals(
        session: Session,
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
        """Aggregate a complete, owner-scoped Task set in one database read."""

        filters: list[Any] = [
            TaskRow.owner_id == owner_id,
            TaskRow.archived_at.is_(None),
            TaskRow.trashed_at.is_(None),
            task_parents_live(),
        ]
        if project_id is not None:
            filters.extend(
                (TaskRow.project_id == project_id, TaskRow.status != TaskStatus.COMPLETED.value)
            )
        if agenda_start is not None and agenda_end is not None:
            filters.extend((TaskRow.due_at >= agenda_start, TaskRow.due_at < agenda_end))
            filters.append(TaskRow.status != TaskStatus.COMPLETED.value)
        if task_ids:
            filters.append(TaskRow.id.in_(task_ids))
        if actionable_now:
            filters.append(or_(TaskRow.not_before.is_(None), TaskRow.not_before <= now))
            filters.append(TaskRow.status != TaskStatus.COMPLETED.value)
        if focus_only:
            filters.append(
                or_(
                    TaskRow.attention_requested.is_(True),
                    TaskRow.due_at < now,
                    TaskRow.status == TaskStatus.BLOCKED.value,
                    TaskRow.priority == "urgent",
                    TaskRow.waiting_since.is_not(None),
                    and_(TaskRow.waiting_since.is_not(None), TaskRow.follow_up_at <= now),
                )
            )

        overdue_estimates = case(
            (
                and_(
                    TaskRow.due_at < now,
                    TaskRow.status != TaskStatus.COMPLETED.value,
                    TaskRow.estimated_minutes.is_not(None),
                ),
                TaskRow.estimated_minutes,
            ),
            else_=0,
        )
        row = session.execute(
            select(
                func.count(TaskRow.id),
                func.coalesce(func.sum(TaskRow.estimated_minutes), 0),
                func.coalesce(func.sum(overdue_estimates), 0),
                func.count(TaskRow.id).filter(TaskRow.estimated_minutes.is_(None)),
            ).where(*filters)
        ).one()
        return {
            "task_count": int(row[0]),
            "estimated_minutes_total": int(row[1]),
            "overdue_minutes": int(row[2]),
            "unestimated_count": int(row[3]),
        }

    @staticmethod
    def project_task_counts(
        session: Session, owner_id: UUID, *, project_id: UUID, now: datetime
    ) -> dict[str, int]:
        """Done, total and overdue Tasks of one Project, in one aggregate read.

        Archived and trashed Tasks are left out, as in `estimate_totals`. A Task is overdue when it
        is not completed and its due instant has passed.
        """

        row = session.execute(
            select(
                func.count(TaskRow.id),
                func.count(TaskRow.id).filter(TaskRow.status == TaskStatus.COMPLETED.value),
                func.count(TaskRow.id).filter(
                    TaskRow.status != TaskStatus.COMPLETED.value,
                    TaskRow.due_at.is_not(None),
                    TaskRow.due_at < now,
                ),
            ).where(
                TaskRow.owner_id == owner_id,
                TaskRow.project_id == project_id,
                TaskRow.archived_at.is_(None),
                TaskRow.trashed_at.is_(None),
            )
        ).one()
        return {
            "tasks_total": int(row[0]),
            "tasks_done": int(row[1]),
            "tasks_overdue": int(row[2]),
        }

    @staticmethod
    def task_step_counts(session: Session, owner_id: UUID, *, task_id: UUID) -> dict[str, int]:
        """Done and total Steps of one Task, in one aggregate read; archived Steps are left out."""

        row = session.execute(
            select(
                func.count(StepRow.id),
                func.count(StepRow.id).filter(StepRow.status == TaskStatus.COMPLETED.value),
            ).where(
                StepRow.owner_id == owner_id,
                StepRow.task_id == task_id,
                StepRow.archived_at.is_(None),
                StepRow.trashed_at.is_(None),
            )
        ).one()
        return {"steps_total": int(row[0]), "steps_done": int(row[1])}

    @staticmethod
    def board_manual_statuses(
        session: Session,
        owner_id: UUID,
        status: str | None = None,
        project_id: UUID | None = None,
    ) -> tuple[str, ...]:
        """Status columns where the owner has placed at least one active Task by hand.

        Same visibility as the board: owner's live, unarchived Tasks, optionally narrowed to
        one status or Project. No pagination, so the answer covers the whole column. Returns
        status names only, in board column order.
        """

        statement = (
            select(TaskRow.status)
            .where(
                TaskRow.owner_id == owner_id,
                TaskRow.board_rank.is_not(None),
                TaskRow.archived_at.is_(None),
                TaskRow.trashed_at.is_(None),
                task_parents_live(),
            )
            .distinct()
        )
        if status is not None:
            statement = statement.where(TaskRow.status == status)
        if project_id is not None:
            statement = statement.where(TaskRow.project_id == project_id)
        found = set(session.scalars(statement).all())
        return tuple(column.value for column in TaskStatus if column.value in found)

    @staticmethod
    def project_titles(
        session: Session, owner_id: UUID, project_ids: tuple[UUID, ...]
    ) -> dict[UUID, str]:
        """Titles of the owner's live Projects named by one Work page, in one query.

        Archived Projects keep their title: a Task in an archived Project still names it.
        """

        if not project_ids:
            return {}
        rows = session.execute(
            select(ProjectRow.id, ProjectRow.title).where(
                ProjectRow.owner_id == owner_id,
                ProjectRow.id.in_(project_ids),
                ProjectRow.trashed_at.is_(None),
            )
        ).all()
        return {row[0]: row[1] for row in rows}

    @staticmethod
    def domain_accents(
        session: Session, owner_id: UUID, domain_ids: tuple[UUID, ...]
    ) -> dict[UUID, str | None]:
        """Accent of each named live Domain of the owner, archived ones included, in one query.

        Work reads pass the Domains their page needs, so the lookup is bounded by that page.
        """

        if not domain_ids:
            return {}
        rows = session.execute(
            select(DomainRow.id, DomainRow.accent).where(
                DomainRow.id.in_(domain_ids),
                DomainRow.owner_id == owner_id,
                DomainRow.trashed_at.is_(None),
            )
        ).all()
        return {row[0]: row[1] for row in rows}

    @staticmethod
    def process_domain_ids(
        session: Session, owner_id: UUID, process_ids: tuple[UUID, ...]
    ) -> dict[UUID, UUID]:
        """Domain of each of the owner's live Processes named by one Work page, in one query."""

        if not process_ids:
            return {}
        rows = session.execute(
            select(ProcessRow.id, ProcessRow.domain_id).where(
                ProcessRow.owner_id == owner_id,
                ProcessRow.id.in_(process_ids),
                ProcessRow.trashed_at.is_(None),
            )
        ).all()
        return {row[0]: row[1] for row in rows}

    @staticmethod
    def project_domain_ids(
        session: Session, owner_id: UUID, project_ids: tuple[UUID, ...]
    ) -> dict[UUID, UUID]:
        """Domain of each of the owner's live Projects named by one Work page, in one query.

        Archived Projects keep their Domain, as they keep their title.
        """

        if not project_ids:
            return {}
        rows = session.execute(
            select(ProjectRow.id, ProjectRow.domain_id).where(
                ProjectRow.owner_id == owner_id,
                ProjectRow.id.in_(project_ids),
                ProjectRow.trashed_at.is_(None),
            )
        ).all()
        return {row[0]: row[1] for row in rows}

    @staticmethod
    def list_board_column_tasks(
        session: Session, owner_id: UUID, status: TaskStatus, limit: int
    ) -> list[Task]:
        """Active Tasks of one status column in current board order."""

        rows = session.scalars(
            select(TaskRow)
            .where(
                TaskRow.owner_id == owner_id,
                TaskRow.status == status.value,
                TaskRow.archived_at.is_(None),
                TaskRow.trashed_at.is_(None),
                task_parents_live(),
            )
            .order_by(
                case((TaskRow.board_rank.is_(None), 1), else_=0),
                TaskRow.board_rank.asc(),
                TaskRow.updated_at.desc(),
                TaskRow.id.desc(),
            )
            .limit(limit)
        )
        return [task_from_row(row) for row in rows]

    @staticmethod
    def save_task(session: Session, task: Task, expected_version: int | None = None) -> None:
        row = session.scalar(select(TaskRow).where(TaskRow.id == task.id).with_for_update())
        if row is None:
            session.add(task_to_row(task))
            return
        if row.owner_id != task.owner_id:
            raise NotFoundError("task not found")
        if expected_version is not None and row.version != expected_version:
            raise ConflictError(
                "stale task version",
                reason="stale_version",
                subject=row.title,
                subject_kind="task",
            )
        for field in (
            "project_id",
            "domain_id",
            "process_id",
            "title",
            "description",
            "status",
            "priority",
            "due_at",
            "completed_at",
            "updated_at",
            "version",
            "attention_requested",
            "archived_at",
            "board_rank",
            "not_before",
            "estimated_minutes",
            "waiting_since",
            "follow_up_at",
            "waiting_on_contact_id",
            "blocked_reminder_cadence",
            "blocked_reminder_snoozed_until",
            "blocked_last_reminded_at",
            "recurrence",
            "last_completed_at",
        ):
            value = getattr(task, field)
            if isinstance(value, (TaskStatus, Priority)):
                value = value.value
            elif isinstance(value, RecurrenceRule):
                value = value.to_data()
            elif field == "blocked_reminder_cadence" and value is not None:
                value = value.value
            setattr(row, field, value)

    @staticmethod
    def append_task_status_history(
        session: Session,
        *,
        owner_id: UUID,
        task_id: UUID,
        from_status: TaskStatus | None,
        to_status: TaskStatus,
        changed_at: datetime,
        source: str,
    ) -> None:
        session.add(
            TaskStatusHistoryRow(
                id=new_uuid7(),
                owner_id=owner_id,
                task_id=task_id,
                from_status=from_status.value if from_status else None,
                to_status=to_status.value,
                changed_at=changed_at,
                source=source,
            )
        )

    @staticmethod
    def list_task_status_history(
        session: Session, owner_id: UUID, task_id: UUID, limit: int
    ) -> list[TaskStatusHistory]:
        rows = session.scalars(
            select(TaskStatusHistoryRow)
            .where(
                TaskStatusHistoryRow.owner_id == owner_id,
                TaskStatusHistoryRow.task_id == task_id,
            )
            .order_by(TaskStatusHistoryRow.changed_at.desc(), TaskStatusHistoryRow.id.desc())
            .limit(limit)
        )
        return [
            TaskStatusHistory(
                id=row.id,
                owner_id=row.owner_id,
                task_id=row.task_id,
                from_status=TaskStatus(row.from_status) if row.from_status else None,
                to_status=TaskStatus(row.to_status),
                changed_at=row.changed_at,
                source=row.source,
            )
            for row in rows
        ]
