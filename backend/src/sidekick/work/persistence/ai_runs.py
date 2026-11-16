"""AI Step runs: one row per attempt, read and written owner-filtered."""

from collections import defaultdict
from datetime import datetime
from uuid import UUID

from sqlalchemy import any_, bindparam, func, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Session

from sidekick.references.persistence import ExternalReferenceRow, TaskExternalReferenceRow
from sidekick.shared.errors import ConflictError, NotFoundError
from sidekick.shared.persistence.models import (
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
        session: Session, owner_id: UUID, step_id: UUID, attempt: int
    ) -> AiStepRun | None:
        """The attempt just before `attempt` on the step, if there is one."""

        row = session.scalar(
            select(AiStepRunRow)
            .where(
                AiStepRunRow.owner_id == owner_id,
                AiStepRunRow.step_id == step_id,
                AiStepRunRow.attempt < attempt,
            )
            .order_by(AiStepRunRow.attempt.desc())
            .limit(1)
        )
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
        session: Session, owner_id: UUID, step_ids: tuple[UUID, ...]
    ) -> dict[UUID, RunHistory]:
        """How many attempts each step has had and how the latest one stands."""

        if not step_ids:
            return {}
        rows = session.scalars(
            select(AiStepRunRow)
            .where(
                AiStepRunRow.owner_id == owner_id,
                AiStepRunRow.step_id == any_(bindparam("step_ids", list(step_ids), _UUID_ARRAY)),
            )
            .order_by(AiStepRunRow.step_id, AiStepRunRow.attempt)
        )
        grouped: dict[UUID, list[AiStepRun]] = defaultdict(list)
        for row in rows:
            grouped[row.step_id].append(run_from_row(row))
        return {
            step_id: RunHistory(attempts=len(runs), latest=runs[-1])
            for step_id, runs in grouped.items()
        }

    @staticmethod
    def count_ai_runs_since(
        session: Session, owner_id: UUID, runner: RunnerKind, since: datetime
    ) -> int:
        """How many runs of this runner were created from `since` on."""

        return (
            session.scalar(
                select(func.count())
                .select_from(AiStepRunRow)
                .where(
                    AiStepRunRow.owner_id == owner_id,
                    AiStepRunRow.runner == runner.value,
                    AiStepRunRow.created_at >= since,
                )
            )
            or 0
        )

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
