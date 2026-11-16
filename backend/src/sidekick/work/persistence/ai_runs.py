"""AI Step runs: one row per attempt, read and written owner-filtered."""

from collections import defaultdict
from collections.abc import Collection
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, any_, bindparam, func, or_, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Session

from sidekick.references.persistence import ExternalReferenceRow, TaskExternalReferenceRow
from sidekick.shared.errors import ConflictError, NotFoundError
from sidekick.shared.persistence.models import (
    AiErasedRunCostRow,
    AiStepRunRow,
    ContactRow,
    StepRow,
    TaskContactRow,
    TaskRow,
)
from sidekick.tasks.domain import Task, TaskStatus
from sidekick.tasks.persistence import task_from_row
from sidekick.work.domain.ai_plan import RunHistory
from sidekick.work.domain.ai_runs import (
    ACTIVE_STATES,
    AiRunResult,
    AiRunState,
    AiStepRun,
    AiUsage,
    ChecklistItem,
    CostSource,
    FailureCategory,
    RunnerKind,
)
from sidekick.work.domain.ai_spec import ResultFormat

_UUID_ARRAY = ARRAY(PGUUID(as_uuid=True))


def run_from_row(row: AiStepRunRow) -> AiStepRun:
    result = None
    if row.result_text is not None and row.result_format is not None:
        result = AiRunResult(
            format=ResultFormat(row.result_format),
            text=row.result_text,
            summary=row.result_summary or "",
            checklist=tuple(
                ChecklistItem(UUID(item["action_id"]), bool(item["done"]))
                for item in row.checklist or ()
            ),
        )
    return AiStepRun(
        id=row.id,
        owner_id=row.owner_id,
        task_id=row.task_id,
        step_id=row.step_id,
        attempt=row.attempt,
        runner=RunnerKind(row.runner),
        state=AiRunState(row.state),
        plan_digest=row.plan_digest,
        created_at=row.created_at,
        updated_at=row.updated_at,
        version=row.version,
        provider=row.provider,
        worker_id=row.worker_id,
        lease_until=row.lease_until,
        queued_at=row.queued_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        reviewed_at=row.reviewed_at,
        result=result,
        question=row.question,
        answer=row.answer,
        feedback=row.feedback,
        usage=AiUsage(
            input_tokens=row.input_tokens,
            output_tokens=row.output_tokens,
            cache_read_tokens=row.cache_read_tokens,
            cache_write_tokens=row.cache_write_tokens,
            reserved_microusd=row.reserved_microusd,
            cost_microusd=row.cost_microusd,
            cost_source=CostSource(row.cost_source),
            model=row.model,
        ),
        error_category=FailureCategory(row.error_category) if row.error_category else None,
    )


def _apply(row: AiStepRunRow, run: AiStepRun) -> None:
    """Copies every changeable field of `run` onto `row`."""

    result = run.result
    row.state = run.state.value
    row.provider = run.provider
    row.model = run.usage.model
    row.worker_id = run.worker_id
    row.lease_until = run.lease_until
    row.queued_at = run.queued_at
    row.started_at = run.started_at
    row.finished_at = run.finished_at
    row.reviewed_at = run.reviewed_at
    row.result_format = result.format.value if result else None
    row.result_text = result.text if result else None
    row.result_summary = result.summary if result else None
    row.checklist = (
        [{"action_id": str(item.action_id), "done": item.done} for item in result.checklist]
        if result
        else None
    )
    row.question = run.question
    row.answer = run.answer
    row.feedback = run.feedback
    row.input_tokens = run.usage.input_tokens
    row.output_tokens = run.usage.output_tokens
    row.cache_read_tokens = run.usage.cache_read_tokens
    row.cache_write_tokens = run.usage.cache_write_tokens
    row.reserved_microusd = run.usage.reserved_microusd
    row.cost_microusd = run.usage.cost_microusd
    row.cost_source = run.usage.cost_source.value
    row.error_category = run.error_category.value if run.error_category else None
    row.updated_at = run.updated_at
    row.version = run.version


class AiRunStore:
    """AI Step runs and the Task reads that find the plans waiting on them.

    The operations are static and owner-filtered; `SqlWorkStore` adds the transaction boundary.
    """

    @staticmethod
    def step_task_id(session: Session, owner_id: UUID, step_id: UUID) -> UUID:
        """The Task a live Step belongs to, read as a column so no row is cached before a lock."""

        task_id = session.scalar(
            select(StepRow.task_id).where(
                StepRow.id == step_id,
                StepRow.owner_id == owner_id,
                StepRow.trashed_at.is_(None),
            )
        )
        if task_id is None:
            raise NotFoundError("step not found")
        return task_id

    @staticmethod
    def get_ai_run(session: Session, owner_id: UUID, run_id: UUID) -> AiStepRun:
        row = session.scalar(
            select(AiStepRunRow).where(AiStepRunRow.id == run_id, AiStepRunRow.owner_id == owner_id)
        )
        if row is None:
            raise NotFoundError("run not found")
        return run_from_row(row)

    @staticmethod
    def previous_ai_run(
        session: Session,
        owner_id: UUID,
        step_id: UUID,
        attempt: int,
        since: datetime | None = None,
    ) -> AiStepRun | None:
        """The attempt just before `attempt` on the step, if there is one, in the cycle that
        began at `since` (any cycle without it)."""

        statement = select(AiStepRunRow).where(
            AiStepRunRow.owner_id == owner_id,
            AiStepRunRow.step_id == step_id,
            AiStepRunRow.attempt < attempt,
        )
        if since is not None:
            statement = statement.where(AiStepRunRow.created_at > since)
        row = session.scalar(statement.order_by(AiStepRunRow.attempt.desc()).limit(1))
        return run_from_row(row) if row is not None else None

    @staticmethod
    def save_ai_run(session: Session, run: AiStepRun, expected_version: int | None = None) -> None:
        row = session.scalar(
            select(AiStepRunRow).where(AiStepRunRow.id == run.id).with_for_update()
        )
        if row is None:
            row = AiStepRunRow(
                id=run.id,
                owner_id=run.owner_id,
                task_id=run.task_id,
                step_id=run.step_id,
                attempt=run.attempt,
                runner=run.runner.value,
                plan_digest=run.plan_digest,
                created_at=run.created_at,
            )
            _apply(row, run)
            session.add(row)
            return
        if row.owner_id != run.owner_id:
            raise NotFoundError("run not found")
        if expected_version is not None and row.version != expected_version:
            raise ConflictError("stale run version", reason="stale_version")
        _apply(row, run)

    @staticmethod
    def run_histories(
        session: Session,
        owner_id: UUID,
        step_ids: tuple[UUID, ...],
        since: datetime | None = None,
    ) -> dict[UUID, RunHistory]:
        """How many attempts each step has had since `since` (all of them without it), and how
        the latest one stands; plus the highest attempt number each step has ever had. A run the
        server queued but never took is not an attempt."""

        if not step_ids:
            return {}
        step_filter = AiStepRunRow.step_id == any_(
            bindparam("step_ids", list(step_ids), _UUID_ARRAY)
        )
        last_attempts = {
            step_id: last
            for step_id, last in session.execute(
                select(AiStepRunRow.step_id, func.max(AiStepRunRow.attempt))
                .where(AiStepRunRow.owner_id == owner_id, step_filter)
                .group_by(AiStepRunRow.step_id)
            )
        }
        statement = select(AiStepRunRow).where(AiStepRunRow.owner_id == owner_id, step_filter)
        if since is not None:
            statement = statement.where(AiStepRunRow.created_at > since)
        grouped: dict[UUID, list[AiStepRun]] = defaultdict(list)
        for row in session.scalars(statement.order_by(AiStepRunRow.step_id, AiStepRunRow.attempt)):
            grouped[row.step_id].append(run_from_row(row))
        return {
            step_id: RunHistory(
                attempts=sum(1 for run in grouped[step_id] if run.started_at is not None),
                latest=grouped[step_id][-1] if grouped[step_id] else None,
                last_attempt=last_attempt,
            )
            for step_id, last_attempt in last_attempts.items()
        }

    @staticmethod
    def list_active_ai_runs(
        session: Session, owner_id: UUID, step_ids: tuple[UUID, ...]
    ) -> list[AiStepRun]:
        """The queued or running attempts among these steps, whatever their lease."""

        if not step_ids:
            return []
        rows = session.scalars(
            select(AiStepRunRow)
            .where(
                AiStepRunRow.owner_id == owner_id,
                AiStepRunRow.step_id == any_(bindparam("step_ids", list(step_ids), _UUID_ARRAY)),
                AiStepRunRow.state.in_([state.value for state in ACTIVE_STATES]),
            )
            .order_by(AiStepRunRow.step_id, AiStepRunRow.attempt)
        )
        return [run_from_row(row) for row in rows]

    @staticmethod
    def count_ai_runs_since(
        session: Session, owner_id: UUID, runner: RunnerKind, since: datetime
    ) -> int:
        """How many runs of this runner were created from `since` on, including the ones whose
        Step or Task has been erased since."""

        kept = session.scalar(
            select(func.count())
            .select_from(AiStepRunRow)
            .where(
                AiStepRunRow.owner_id == owner_id,
                AiStepRunRow.runner == runner.value,
                AiStepRunRow.created_at >= since,
            )
        )
        erased = session.scalar(
            select(func.count())
            .select_from(AiErasedRunCostRow)
            .where(
                AiErasedRunCostRow.owner_id == owner_id,
                AiErasedRunCostRow.runner == runner.value,
                AiErasedRunCostRow.created_at >= since,
            )
        )
        return (kept or 0) + (erased or 0)

    @staticmethod
    def sum_ai_cost_since(
        session: Session,
        owner_id: UUID,
        since: datetime,
        sources: Collection[CostSource],
        task_id: UUID | None = None,
    ) -> int:
        """Millionths of a dollar the runs created from `since` on cost, for these cost sources:
        what they cost and what a model call in flight has reserved. Runs whose Step or Task has
        been erased since still count. Only one Task's runs when `task_id` is given."""

        source_values = [source.value for source in sources]
        kept = select(
            func.coalesce(func.sum(AiStepRunRow.cost_microusd + AiStepRunRow.reserved_microusd), 0)
        ).where(
            AiStepRunRow.owner_id == owner_id,
            AiStepRunRow.created_at >= since,
            AiStepRunRow.cost_source.in_(source_values),
        )
        erased = select(func.coalesce(func.sum(AiErasedRunCostRow.cost_microusd), 0)).where(
            AiErasedRunCostRow.owner_id == owner_id,
            AiErasedRunCostRow.created_at >= since,
            AiErasedRunCostRow.cost_source.in_(source_values),
        )
        if task_id is not None:
            kept = kept.where(AiStepRunRow.task_id == task_id)
            erased = erased.where(AiErasedRunCostRow.task_id == task_id)
        return int(session.scalar(kept) or 0) + int(session.scalar(erased) or 0)

    @staticmethod
    def lock_owner_spend(session: Session, owner_id: UUID) -> None:
        """Serialize the owner's spending decisions until the transaction ends, so two model
        calls cannot both pass a cap that only one of them fits under."""

        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"ai-spend:{owner_id}"},
        )

    @staticmethod
    def next_queued_server_run(session: Session, now: datetime) -> AiStepRun | None:
        """The oldest queued server run that has not lapsed. Not locked: the caller locks the
        run's Task first and then reads the run again, so the lock order is the one every other
        writer of a run keeps (Task, then run)."""

        row = session.scalar(
            select(AiStepRunRow)
            .where(
                AiStepRunRow.runner == RunnerKind.SERVER.value,
                AiStepRunRow.state == AiRunState.QUEUED.value,
                AiStepRunRow.lease_until > now,
            )
            .order_by(AiStepRunRow.queued_at, AiStepRunRow.id)
            .limit(1)
        )
        return run_from_row(row) if row is not None else None

    @staticmethod
    def list_stalled_server_runs(session: Session, now: datetime, limit: int) -> list[AiStepRun]:
        """Server runs whose lease ran out while queued or running, or while a cancelled run's
        model call was still reserved. Not locked, for the reason `next_queued_server_run` gives."""

        rows = session.scalars(
            select(AiStepRunRow)
            .where(
                AiStepRunRow.runner == RunnerKind.SERVER.value,
                AiStepRunRow.lease_until <= now,
                or_(
                    AiStepRunRow.state.in_([state.value for state in ACTIVE_STATES]),
                    and_(
                        AiStepRunRow.state == AiRunState.CANCELLED.value,
                        AiStepRunRow.reserved_microusd > 0,
                    ),
                ),
            )
            .order_by(AiStepRunRow.lease_until)
            .limit(limit)
        )
        return [run_from_row(row) for row in rows]

    @staticmethod
    def list_tasks_with_approved_plans(
        session: Session, owner_id: UUID, limit: int, from_id: UUID | None = None
    ) -> list[Task]:
        """Open, live Tasks with an approved plan, in id order, from `from_id` on when given."""

        statement = select(TaskRow).where(
            TaskRow.owner_id == owner_id,
            TaskRow.ai_plan_digest.is_not(None),
            TaskRow.trashed_at.is_(None),
            TaskRow.archived_at.is_(None),
            TaskRow.status != TaskStatus.COMPLETED.value,
        )
        if from_id is not None:
            statement = statement.where(TaskRow.id >= from_id)
        rows = session.scalars(statement.order_by(TaskRow.id).limit(limit))
        return [task_from_row(row) for row in rows]

    @staticmethod
    def task_contact_names(
        session: Session, owner_id: UUID, task_id: UUID, limit: int
    ) -> list[str]:
        """Display names of the active Contacts linked to the Task; never their details."""

        return list(
            session.scalars(
                select(ContactRow.display_name)
                .join(
                    TaskContactRow,
                    (TaskContactRow.contact_id == ContactRow.id)
                    & (TaskContactRow.owner_id == ContactRow.owner_id),
                )
                .where(
                    TaskContactRow.owner_id == owner_id,
                    TaskContactRow.task_id == task_id,
                    ContactRow.archived.is_(False),
                    ContactRow.trashed_at.is_(None),
                )
                .order_by(ContactRow.display_name_key, ContactRow.id)
                .limit(limit)
            )
        )

    @staticmethod
    def task_reference_titles(
        session: Session, owner_id: UUID, task_id: UUID, limit: int
    ) -> list[str]:
        """Titles of the external references linked to the Task; never their addresses."""

        return list(
            session.scalars(
                select(ExternalReferenceRow.title)
                .join(
                    TaskExternalReferenceRow,
                    (TaskExternalReferenceRow.reference_id == ExternalReferenceRow.id)
                    & (TaskExternalReferenceRow.owner_id == ExternalReferenceRow.owner_id),
                )
                .where(
                    TaskExternalReferenceRow.owner_id == owner_id,
                    TaskExternalReferenceRow.task_id == task_id,
                )
                .order_by(TaskExternalReferenceRow.created_at, ExternalReferenceRow.id)
                .limit(limit)
            )
        )
