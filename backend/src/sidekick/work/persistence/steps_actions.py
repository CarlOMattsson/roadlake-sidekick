"""Steps and Actions, including the batched reads used by work lists."""

from uuid import UUID

from sqlalchemy import any_, bindparam, func, select, tuple_
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Session

from sidekick.shared.errors import (
    ConflictError,
    NotFoundError,
)
from sidekick.shared.persistence.models import (
    ActionRow,
    StepRow,
    TaskRow,
)
from sidekick.tasks.domain import TaskStatus
from sidekick.work.domain import (
    Action,
    ActionStatus,
    Step,
)
from sidekick.work.persistence.mappers import (
    action_from_row,
    action_to_row,
    step_from_row,
    step_to_row,
)

_UUID_ARRAY = ARRAY(PGUUID(as_uuid=True))
"""Bind type for `= ANY(:ids)`: one array parameter however many ids."""


class StepActionStore:
    """Steps and Actions, including the batched reads used by work lists.

    Mixin composed into ``SqlAlchemyStore``; methods are static and owner-filtered.
    """

    @staticmethod
    def list_steps(
        session: Session,
        owner_id: UUID,
        task_id: UUID,
        limit: int,
        offset: int = 0,
        include_archived: bool = False,
        *,
        after: tuple[int, UUID] | None = None,
    ) -> list[Step]:
        statement = select(StepRow).where(
            StepRow.owner_id == owner_id,
            StepRow.task_id == task_id,
            StepRow.trashed_at.is_(None),
        )
        if not include_archived:
            statement = statement.where(StepRow.archived_at.is_(None))
        if after is not None:
            statement = statement.where(tuple_(StepRow.position, StepRow.id) > after)
        rows = session.scalars(
            statement.order_by(StepRow.position.asc(), StepRow.id.asc()).offset(offset).limit(limit)
        )
        return [step_from_row(row) for row in rows]

    @staticmethod
    def list_live_steps_by_ids(
        session: Session, owner_id: UUID, step_ids: tuple[UUID, ...]
    ) -> dict[UUID, Step]:
        """The owner's Steps among `step_ids` that are neither archived nor in the trash."""

        if not step_ids:
            return {}
        rows = session.scalars(
            select(StepRow).where(
                StepRow.owner_id == owner_id,
                StepRow.id == any_(bindparam("step_ids", list(step_ids), type_=_UUID_ARRAY)),
                StepRow.trashed_at.is_(None),
                StepRow.archived_at.is_(None),
            )
        )
        return {row.id: step_from_row(row) for row in rows}

    @staticmethod
    def list_steps_for_tasks(
        session: Session,
        owner_id: UUID,
        task_ids: tuple[UUID, ...],
        per_task_limit: int = 1000,
        include_archived: bool = False,
    ) -> dict[UUID, list[Step]]:
        """Steps of several Tasks in one query, in the same order as `list_steps` per Task."""

        grouped: dict[UUID, list[Step]] = {}
        if not task_ids:
            return grouped
        # One typed array parameter, not one bind per id: thousands of Tasks never hit the
        # driver's parameter limit. The per-Task cap is applied in SQL by `row_number()`.
        filters = [
            StepRow.owner_id == owner_id,
            StepRow.task_id == any_(bindparam("task_ids", list(task_ids), type_=_UUID_ARRAY)),
            StepRow.trashed_at.is_(None),
        ]
        if not include_archived:
            filters.append(StepRow.archived_at.is_(None))
        ranked = (
            select(
                StepRow.id.label("step_id"),
                func.row_number()
                .over(
                    partition_by=StepRow.task_id,
                    order_by=(StepRow.position.asc(), StepRow.id.asc()),
                )
                .label("rn"),
            )
            .where(*filters)
            .subquery()
        )
        statement = (
            select(StepRow)
            .join(ranked, ranked.c.step_id == StepRow.id)
            .where(ranked.c.rn <= per_task_limit)
            .order_by(StepRow.position.asc(), StepRow.id.asc())
        )
        for row in session.scalars(statement):
            grouped.setdefault(row.task_id, []).append(step_from_row(row))
        return grouped

    @staticmethod
    def list_actions_for_steps(
        session: Session,
        owner_id: UUID,
        step_ids: tuple[UUID, ...],
        per_step_limit: int = 1000,
        include_archived: bool = False,
    ) -> dict[UUID, list[Action]]:
        """Actions of several Steps in one query, in the same order as `list_actions` per Step."""

        grouped: dict[UUID, list[Action]] = {}
        if not step_ids:
            return grouped
        filters = [
            ActionRow.owner_id == owner_id,
            ActionRow.step_id == any_(bindparam("step_ids", list(step_ids), type_=_UUID_ARRAY)),
            ActionRow.trashed_at.is_(None),
        ]
        if not include_archived:
            filters.append(ActionRow.archived_at.is_(None))
        ranked = (
            select(
                ActionRow.id.label("action_id"),
                func.row_number()
                .over(
                    partition_by=ActionRow.step_id,
                    order_by=(ActionRow.position.asc(), ActionRow.id.asc()),
                )
                .label("rn"),
            )
            .where(*filters)
            .subquery()
        )
        statement = (
            select(ActionRow)
            .join(ranked, ranked.c.action_id == ActionRow.id)
            .where(ranked.c.rn <= per_step_limit)
            .order_by(ActionRow.position.asc(), ActionRow.id.asc())
        )
        for row in session.scalars(statement):
            grouped.setdefault(row.step_id, []).append(action_from_row(row))
        return grouped

    @staticmethod
    def lock_step_order(session: Session, owner_id: UUID, task_id: UUID) -> None:
        """Serialize position changes among one Task's Steps by locking the Task row.

        Held until the transaction ends. Creating, restoring and reordering Steps all take it
        first, so two writers can never allocate or renumber positions against the same state.
        """

        locked = session.scalar(
            select(TaskRow.id)
            .where(TaskRow.id == task_id, TaskRow.owner_id == owner_id)
            .with_for_update()
        )
        if locked is None:
            raise NotFoundError("task not found")

    @staticmethod
    def next_step_position(session: Session, owner_id: UUID, task_id: UUID) -> int:
        """One past the highest position of any Step of the Task, archived and trashed included.

        Counting hidden Steps keeps a later restore from landing on a live Step's position. Call
        `lock_step_order` first in the same transaction.
        """

        highest = session.scalar(
            select(func.max(StepRow.position)).where(
                StepRow.owner_id == owner_id, StepRow.task_id == task_id
            )
        )
        return 0 if highest is None else int(highest) + 1

    @staticmethod
    def get_step(session: Session, owner_id: UUID, step_id: UUID) -> Step:
        row = session.scalar(
            select(StepRow).where(
                StepRow.id == step_id,
                StepRow.owner_id == owner_id,
                StepRow.trashed_at.is_(None),
            )
        )
        if row is None:
            raise NotFoundError("step not found")
        return step_from_row(row)

    @staticmethod
    def save_step(session: Session, step: Step, expected_version: int | None = None) -> None:
        row = session.scalar(select(StepRow).where(StepRow.id == step.id).with_for_update())
        if row is None:
            session.add(step_to_row(step))
            return
        if row.owner_id != step.owner_id:
            raise NotFoundError("step not found")
        if expected_version is not None and row.version != expected_version:
            raise ConflictError("stale step version", reason="stale_version")
        for field in (
            "title",
            "status",
            "position",
            "due_at",
            "attention_requested",
            "instruction",
            "updated_at",
            "version",
            "archived_at",
            "completed_at",
        ):
            value = getattr(step, field)
            setattr(row, field, value.value if isinstance(value, TaskStatus) else value)

    @staticmethod
    def list_actions(
        session: Session,
        owner_id: UUID,
        step_id: UUID,
        limit: int,
        offset: int = 0,
        include_archived: bool = False,
        *,
        after: tuple[int, UUID] | None = None,
    ) -> list[Action]:
        statement = select(ActionRow).where(
            ActionRow.owner_id == owner_id,
            ActionRow.step_id == step_id,
            ActionRow.trashed_at.is_(None),
        )
        if not include_archived:
            statement = statement.where(ActionRow.archived_at.is_(None))
        if after is not None:
            statement = statement.where(tuple_(ActionRow.position, ActionRow.id) > after)
        rows = session.scalars(
            statement.order_by(ActionRow.position.asc(), ActionRow.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return [action_from_row(row) for row in rows]

    @staticmethod
    def lock_action_order(session: Session, owner_id: UUID, step_id: UUID) -> None:
        """Serialize position changes among one Step's Actions by locking the Step row."""

        locked = session.scalar(
            select(StepRow.id)
            .where(StepRow.id == step_id, StepRow.owner_id == owner_id)
            .with_for_update()
        )
        if locked is None:
            raise NotFoundError("step not found")

    @staticmethod
    def next_action_position(session: Session, owner_id: UUID, step_id: UUID) -> int:
        """One past the highest position of any Action of the Step, archived and trashed included.

        Call `lock_action_order` first in the same transaction.
        """

        highest = session.scalar(
            select(func.max(ActionRow.position)).where(
                ActionRow.owner_id == owner_id, ActionRow.step_id == step_id
            )
        )
        return 0 if highest is None else int(highest) + 1

    @staticmethod
    def get_action(session: Session, owner_id: UUID, action_id: UUID) -> Action:
        row = session.scalar(
            select(ActionRow).where(
                ActionRow.owner_id == owner_id,
                ActionRow.id == action_id,
                ActionRow.trashed_at.is_(None),
            )
        )
        if row is None:
            raise NotFoundError("action not found")
        return action_from_row(row)

    @staticmethod
    def save_action(session: Session, action: Action, expected_version: int | None = None) -> None:
        row = session.scalar(select(ActionRow).where(ActionRow.id == action.id).with_for_update())
        if row is None:
            session.add(action_to_row(action))
            return
        if row.owner_id != action.owner_id:
            raise NotFoundError("action not found")
        if expected_version is not None and row.version != expected_version:
            raise ConflictError("stale action version")
        for field in (
            "title",
            "status",
            "position",
            "due_at",
            "attention_requested",
            "note",
            "updated_at",
            "version",
            "archived_at",
        ):
            value = getattr(action, field)
            setattr(row, field, value.value if isinstance(value, ActionStatus) else value)
