"""The visibility rule for Tasks whose parent context is in the trash."""

from sqlalchemy import and_, exists, select
from sqlalchemy.sql import ColumnElement

from sidekick.shared.persistence.models import DomainRow, ProcessRow, ProjectRow, TaskRow


def task_parents_live() -> ColumnElement[bool]:
    """True for a Task none of whose parents (Project, Process, Domain) is in the trash.

    A Task whose parent is trashed is hidden from every normal read (lists, board, agenda,
    search, counts, the diary's done lists, push reminders) and comes back when the parent is
    restored; it is not trashed itself, so the trash view shows the parent. Correlates to `TaskRow`
    of the enclosing query only, so a query that also joins `ProjectRow` keeps the parent lookup
    its own. A Task with no parent of a kind, or an archived parent, stays visible.
    """

    return and_(
        ~exists(
            select(1)
            .where(ProjectRow.id == TaskRow.project_id, ProjectRow.trashed_at.is_not(None))
            .correlate(TaskRow)
        ),
        ~exists(
            select(1)
            .where(ProcessRow.id == TaskRow.process_id, ProcessRow.trashed_at.is_not(None))
            .correlate(TaskRow)
        ),
        ~exists(
            select(1)
            .where(DomainRow.id == TaskRow.domain_id, DomainRow.trashed_at.is_not(None))
            .correlate(TaskRow)
        ),
    )
