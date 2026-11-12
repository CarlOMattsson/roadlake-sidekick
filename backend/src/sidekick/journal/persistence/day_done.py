"""The owner-scoped queries behind `DayDone`. See `journal/domain/day_done.py` for the rules."""

from datetime import date, datetime, tzinfo
from typing import Any
from uuid import UUID

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from sidekick.journal.domain.day_done import (
    DONE_LIST_LIMIT,
    DayDone,
    DoneCounts,
    DonePurchase,
    DoneStep,
    DoneTask,
    day_bounds,
)
from sidekick.shared.persistence.models import ProjectRow, StepRow, TaskRow
from sidekick.shared.persistence.stores.task_parents import task_parents_live
from sidekick.shared.types import Actor
from sidekick.shopping.persistence.rows import ShoppingItemRow, ShoppingListRow


def read_day_done(
    session: Session,
    actor: Actor,
    journal_date: date,
    zone: tzinfo,
    *,
    limit: int = DONE_LIST_LIMIT,
) -> DayDone:
    """The owner's done records for the day, within one already-open transaction."""

    owner_id = actor.user_id
    start, end = day_bounds(journal_date, zone)
    work = "tasks:read" in actor.scopes
    shopping = "shopping:read" in actor.scopes
    tasks, task_count = _tasks(session, owner_id, start, end, limit) if work else ((), 0)
    steps, step_count = _steps(session, owner_id, start, end, limit) if work else ((), 0)
    purchases, purchase_count = (
        _purchases(session, owner_id, start, end, limit) if shopping else ((), 0)
    )
    return DayDone(
        tasks=tasks,
        steps=steps,
        purchases=purchases,
        counts=DoneCounts(tasks=task_count, steps=step_count, purchases=purchase_count),
        truncated=task_count > limit or step_count > limit or purchase_count > limit,
    )


def _within(column: Any, start: datetime, end: datetime) -> Any:
    return and_(column >= start, column < end)


def _tasks(
    session: Session, owner_id: UUID, start: datetime, end: datetime, limit: int
) -> tuple[tuple[DoneTask, ...], int]:
    # A recurring task is reopened when it is completed, so its day comes from last_completed_at,
    # and only while it still recurs (a task whose repeat was removed no longer counts as done by
    # that old cycle). A task that finished its last cycle keeps completed_at as well, which wins
    # when both fall in the day.
    in_day = or_(
        _within(TaskRow.completed_at, start, end),
        and_(TaskRow.recurrence.is_not(None), _within(TaskRow.last_completed_at, start, end)),
    )
    done_at = case(
        (_within(TaskRow.completed_at, start, end), TaskRow.completed_at),
        else_=TaskRow.last_completed_at,
    )
    scope = (
        TaskRow.owner_id == owner_id,
        TaskRow.archived_at.is_(None),
        TaskRow.trashed_at.is_(None),
        task_parents_live(),
        in_day,
    )
    count = session.scalar(select(func.count()).select_from(TaskRow).where(*scope)) or 0
    rows = session.execute(
        select(
            TaskRow.id,
            TaskRow.title,
            done_at.label("done_at"),
            ProjectRow.title,
            TaskRow.recurrence.is_not(None),
        )
        .select_from(TaskRow)
        .outerjoin(
            ProjectRow,
            and_(ProjectRow.id == TaskRow.project_id, ProjectRow.owner_id == TaskRow.owner_id),
        )
        .where(*scope)
        .order_by(done_at.asc(), TaskRow.id.asc())
        .limit(limit)
    ).all()
    return (
        tuple(
            DoneTask(
                id=row[0],
                title=row[1],
                completed_at=row[2],
                project_title=row[3],
                recurring=bool(row[4]),
            )
            for row in rows
        ),
        count,
    )


def _steps(
    session: Session, owner_id: UUID, start: datetime, end: datetime, limit: int
) -> tuple[tuple[DoneStep, ...], int]:
    joined = and_(TaskRow.id == StepRow.task_id, TaskRow.owner_id == StepRow.owner_id)
    scope = (
        StepRow.owner_id == owner_id,
        StepRow.status == "completed",
        StepRow.archived_at.is_(None),
        StepRow.trashed_at.is_(None),
        _within(StepRow.completed_at, start, end),
        TaskRow.archived_at.is_(None),
        TaskRow.trashed_at.is_(None),
        task_parents_live(),
    )
    count = (
        session.scalar(
            select(func.count()).select_from(StepRow).join(TaskRow, joined).where(*scope)
        )
        or 0
    )
    rows = session.execute(
        select(StepRow.id, StepRow.title, StepRow.task_id, TaskRow.title, StepRow.completed_at)
        .join(TaskRow, joined)
        .where(*scope)
        .order_by(StepRow.completed_at.asc(), StepRow.id.asc())
        .limit(limit)
    ).all()
    return (
        tuple(
            DoneStep(
                id=row[0], title=row[1], task_id=row[2], task_title=row[3], completed_at=row[4]
            )
            for row in rows
        ),
        count,
    )


def _purchases(
    session: Session, owner_id: UUID, start: datetime, end: datetime, limit: int
) -> tuple[tuple[DonePurchase, ...], int]:
    joined = and_(
        ShoppingListRow.id == ShoppingItemRow.list_id,
        ShoppingListRow.owner_id == ShoppingItemRow.owner_id,
    )
    scope = (
        ShoppingItemRow.owner_id == owner_id,
        ShoppingItemRow.purchased.is_(True),
        ShoppingItemRow.trashed_at.is_(None),
        _within(ShoppingItemRow.purchased_at, start, end),
    )
    count = (
        session.scalar(
            select(func.count())
            .select_from(ShoppingItemRow)
            .join(ShoppingListRow, joined)
            .where(*scope)
        )
        or 0
    )
    rows = session.execute(
        select(
            ShoppingItemRow.id,
            ShoppingItemRow.name,
            ShoppingItemRow.list_id,
            ShoppingListRow.name,
            ShoppingItemRow.purchased_at,
        )
        .join(ShoppingListRow, joined)
        .where(*scope)
        .order_by(ShoppingItemRow.purchased_at.asc(), ShoppingItemRow.id.asc())
        .limit(limit)
    ).all()
    return (
        tuple(
            DonePurchase(
                id=row[0], title=row[1], list_id=row[2], list_title=row[3], purchased_at=row[4]
            )
            for row in rows
        ),
        count,
    )
