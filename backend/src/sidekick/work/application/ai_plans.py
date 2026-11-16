"""The plan of AI Steps: reading it, writing it as a proposal and the owner's approval of it."""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal
from uuid import UUID

from sidekick.activity.domain import ActivityCategory
from sidekick.shared.errors import ConflictError, NotFoundError, ValidationError
from sidekick.shared.replay import id_replay_record, id_result
from sidekick.shared.types import UNSET, Actor, Clock, TxSession, UnsetType, new_uuid7
from sidekick.tasks.domain import Task, TaskStatus
from sidekick.work.application.ai_store import (
    MAX_STEPS_PER_TASK,
    MICROUSD_PER_USD,
    AiLimits,
    AiPlanStepView,
    AiPlanView,
    AiStepsStore,
)
from sidekick.work.domain import Step
from sidekick.work.domain.ai_plan import (
    PlanStep,
    RunHistory,
    plan_digest,
    plan_state,
    step_status,
    validate_plan,
)
from sidekick.work.domain.ai_spec import MAX_PLAN_STEPS, AiStepSpecV1, Performer
from sidekick.work.domain.run_ports import RunActivityRecorder

PlanDecision = Literal["approve", "withdraw"]


@dataclass(frozen=True, slots=True)
class PlanItem:
    """One step of a proposed plan: an existing step by id, or a new one by title."""

    performer: Performer
    step_id: UUID | None = None
    title: str | None = None
    instruction: str | UnsetType | None = UNSET
    ai_spec: AiStepSpecV1 | None = None

    def payload(self) -> dict[str, object]:
        return {
            "step_id": str(self.step_id) if self.step_id else None,
            "title": self.title,
            "performer": self.performer.value,
            "instruction": self.instruction,
            "ai_spec": self.ai_spec.model_dump(mode="json") if self.ai_spec else None,
        }


def load_plan_view(
    store: AiStepsStore,
    session: TxSession,
    task: Task,
    *,
    limits: AiLimits,
    now: datetime,
) -> AiPlanView:
    """The Task's plan as it stands: digest, state and each step with where it is."""

    steps = store.list_steps(session, task.owner_id, task.id, MAX_STEPS_PER_TASK)
    actions = store.list_actions_for_steps(session, task.owner_id, tuple(step.id for step in steps))
    plan_steps = [
        PlanStep(step, tuple(action.title for action in actions.get(step.id, ()))) for step in steps
    ]
    ai_ids = tuple(step.id for step in steps if step.performer is Performer.AI)
    histories = store.run_histories(session, task.owner_id, ai_ids)
    views: list[AiPlanStepView] = []
    earlier_done = True
    for step in steps:
        history = histories.get(step.id, RunHistory())
        status = (
            step_status(
                step,
                earlier_done=earlier_done,
                history=history,
                max_attempts=limits.max_attempts_per_step,
                now=now,
            )
            if step.performer is Performer.AI
            else None
        )
        views.append(AiPlanStepView(step, actions.get(step.id, ()), status, history))
        earlier_done = earlier_done and step.status is TaskStatus.COMPLETED
    return AiPlanView(
        task=task,
        state=plan_state(task, plan_steps),
        digest=plan_digest(task, plan_steps),
        task_cap_microusd=limits.task_cap(task),
        steps=views,
    )


class AiPlanService:
    def __init__(
        self,
        store: AiStepsStore,
        clock: Clock,
        limits: AiLimits,
        activity: RunActivityRecorder | None = None,
    ) -> None:
        self.store = store
        self.clock = clock
        self.limits = limits
        self.activity = activity

    def get_plan(self, actor: Actor, task_id: UUID) -> AiPlanView:
        actor.require("tasks:read")
        return self.store.transaction(lambda session: self._view(session, actor, task_id))

    def _view(self, session: TxSession, actor: Actor, task_id: UUID) -> AiPlanView:
        task = self.store.get_task(session, actor.user_id, task_id)
        return load_plan_view(self.store, session, task, limits=self.limits, now=self.clock.now())

    def set_plan(
        self,
        actor: Actor,
        task_id: UUID,
        *,
        task_version: int,
        items: Sequence[PlanItem],
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> AiPlanView:
        """Write the plan as a proposal: the listed steps in order, then the others as they were.

        Marks the Task as possible with AI and takes back an earlier approval, so the new plan is
        a draft until the owner approves it.
        """

        actor.require("tasks:write")
        if not 1 <= len(items) <= MAX_PLAN_STEPS:
            raise ValidationError(f"a plan lists 1-{MAX_PLAN_STEPS} steps")

        def operation(session: TxSession) -> dict[str, str]:
            self._write_plan(
                session, actor, task_id, task_version, items, correlation_id=correlation_id
            )
            return id_result(task_id)

        def replayed(session: TxSession) -> AiPlanView:
            self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="set_ai_plan",
                key=idempotency_key,
                payload={
                    "task_id": str(task_id),
                    "task_version": task_version,
                    "items": [item.payload() for item in items],
                },
                execute=lambda: operation(session),
                replay=id_replay_record,
            )
            return self._view(session, actor, task_id)

        return self.store.transaction(replayed)

    def _write_plan(
        self,
        session: TxSession,
        actor: Actor,
        task_id: UUID,
        task_version: int,
        items: Sequence[PlanItem],
        *,
        correlation_id: str | None,
    ) -> None:
        owner_id = actor.user_id
        task = self.store.get_task(session, owner_id, task_id)
        if task.version != task_version:
            raise ConflictError("stale task version", reason="stale_version")
        self.store.lock_step_order(session, owner_id, task_id)
        existing = self.store.list_steps(session, owner_id, task_id, MAX_STEPS_PER_TASK)
        now = self.clock.now()
        listed = self._apply_items(session, actor, task, existing, items, now)
        listed_ids = {step.id for step in listed}
        ordered = [*listed, *(step for step in existing if step.id not in listed_ids)]
        before = {step.id: step for step in existing}
        for position, step in enumerate(ordered):
            previous = before.get(step.id)
            placed = replace(step, position=position)
            if previous is not None and placed.version == previous.version and placed != previous:
                placed = replace(placed, updated_at=now, version=previous.version + 1)
            if placed != previous:
                self.store.save_step(
                    session, placed, expected_version=previous.version if previous else None
                )
        updated = self._proposed_task(task, now)
        validate_plan(
            self._plan_steps(session, owner_id, ordered),
            task_cap_microusd=self.limits.task_cap(updated),
        )
        self.store.save_task(session, updated, expected_version=task.version)
        self._record(
            session, actor, updated, "ai.plan_set", len(ordered), len(listed), correlation_id, now
        )

    def _apply_items(
        self,
        session: TxSession,
        actor: Actor,
        task: Task,
        existing: Sequence[Step],
        items: Sequence[PlanItem],
        now: datetime,
    ) -> list[Step]:
        by_id = {step.id: step for step in existing}
        position = len(existing)
        listed: list[Step] = []
        seen: set[UUID] = set()
        for item in items:
            if item.step_id is None:
                step = self._new_step(actor, task, item, position, now)
                position += 1
            else:
                if item.step_id in seen:
                    raise ValidationError("a step is listed twice in the plan")
                seen.add(item.step_id)
                current = by_id.get(item.step_id)
                if current is None:
                    raise NotFoundError("step not found")
                step = self._changed_step(current, item, now)
            listed.append(step)
        return listed

    @staticmethod
    def _spec_for(item: PlanItem, current: AiStepSpecV1 | None) -> AiStepSpecV1 | None:
        if item.performer is Performer.OWNER:
            if item.ai_spec is not None:
                raise ValidationError("an owner step has no AI spec")
            return None
        spec = item.ai_spec or current
        if spec is None:
            raise ValidationError("an AI step needs a spec")
        return spec

    def _new_step(
        self, actor: Actor, task: Task, item: PlanItem, position: int, now: datetime
    ) -> Step:
        if not item.title:
            raise ValidationError("a new step needs a title")
        return Step(
            new_uuid7(),
            actor.user_id,
            task.id,
            item.title,
            TaskStatus.TODO,
            position,
            None,
            False,
            now,
            now,
            instruction=None if isinstance(item.instruction, UnsetType) else item.instruction,
            performer=item.performer,
            ai_spec=self._spec_for(item, None),
        )

    def _changed_step(self, current: Step, item: PlanItem, now: datetime) -> Step:
        edits: dict[str, object] = {}
        if item.title:
            edits["title"] = item.title
        if not isinstance(item.instruction, UnsetType):
            edits["instruction"] = item.instruction
        candidate = replace(
            current,
            performer=item.performer,
            ai_spec=self._spec_for(item, current.ai_spec),
            **edits,
        )
        if candidate == current:
            return current
        if current.status is TaskStatus.COMPLETED:
            raise ValidationError("a completed step cannot be changed by a plan")
        return replace(candidate, updated_at=now, version=current.version + 1)

    @staticmethod
    def _proposed_task(task: Task, now: datetime) -> Task:
        """The Task after a plan is written: marked for AI, its approval withdrawn, version up.

        The version moves on every write, so each plan change is one entry of the Task's history.
        """

        changes: dict[str, object] = {
            "ai_plan_digest": None,
            "ai_plan_approved_at": None,
            "ai_task_cap_microusd": None,
        }
        if task.ai_possible_since is None:
            changes["ai_possible_since"] = now
        return replace(task, **changes, updated_at=now, version=task.version + 1)

    def _plan_steps(
        self, session: TxSession, owner_id: UUID, steps: Sequence[Step]
    ) -> list[PlanStep]:
        actions = self.store.list_actions_for_steps(
            session, owner_id, tuple(step.id for step in steps)
        )
        return [
            PlanStep(step, tuple(action.title for action in actions.get(step.id, ())))
            for step in steps
        ]

    def approve_plan(
        self,
        actor: Actor,
        task_id: UUID,
        *,
        digest: str,
        decision: PlanDecision,
        task_cap_usd: float | None = None,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> AiPlanView:
        """Approve the plan whose digest is `digest`, or withdraw an approval.

        The digest is what the owner saw; a plan that changed since is refused.
        """

        actor.require("tasks:write")
        cap = self._cap_microusd(task_cap_usd)

        def operation(session: TxSession) -> dict[str, str]:
            task = self.store.get_task(session, actor.user_id, task_id)
            view = load_plan_view(
                self.store, session, task, limits=self.limits, now=self.clock.now()
            )
            if decision == "withdraw":
                self._withdraw(session, actor, task, correlation_id)
            else:
                self._approve(session, actor, view, digest, cap, correlation_id)
            return id_result(task_id)

        def replayed(session: TxSession) -> AiPlanView:
            self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="approve_ai_plan",
                key=idempotency_key,
                payload={
                    "task_id": str(task_id),
                    "digest": digest,
                    "decision": decision,
                    "task_cap_microusd": cap,
                },
                execute=lambda: operation(session),
                replay=id_replay_record,
            )
            return self._view(session, actor, task_id)

        return self.store.transaction(replayed)

    def _cap_microusd(self, task_cap_usd: float | None) -> int | None:
        if task_cap_usd is None:
            return None
        cap = round(task_cap_usd * MICROUSD_PER_USD)
        if not 0 < cap <= self.limits.monthly_cap_microusd:
            raise ValidationError("the task cap must be above zero and within the monthly cap")
        return cap

    def _approve(
        self,
        session: TxSession,
        actor: Actor,
        view: AiPlanView,
        digest: str,
        cap: int | None,
        correlation_id: str | None,
    ) -> None:
        task = view.task
        if digest != view.digest:
            raise ConflictError("the plan changed", reason="plan_changed")
        if task.ai_possible_since is None:
            raise ValidationError("the task is not marked as possible with AI")
        if task.ai_plan_digest == digest and (cap is None or cap == task.ai_task_cap_microusd):
            return
        effective_cap = cap or self.limits.default_task_cap_microusd
        validate_plan([PlanStep(item.step) for item in view.steps], task_cap_microusd=effective_cap)
        now = self.clock.now()
        approved = replace(
            task,
            ai_plan_digest=digest,
            ai_plan_approved_at=now,
            ai_task_cap_microusd=cap,
            updated_at=now,
            version=task.version + 1,
        )
        self.store.save_task(session, approved, expected_version=task.version)
        self._record(
            session,
            actor,
            approved,
            "ai.plan_approved",
            len(view.steps),
            sum(item.step.performer is Performer.AI for item in view.steps),
            correlation_id,
            now,
        )

    def _withdraw(
        self, session: TxSession, actor: Actor, task: Task, correlation_id: str | None
    ) -> None:
        if task.ai_plan_digest is None:
            return
        now = self.clock.now()
        withdrawn = replace(
            task,
            ai_plan_digest=None,
            ai_plan_approved_at=None,
            ai_task_cap_microusd=None,
            updated_at=now,
            version=task.version + 1,
        )
        self.store.save_task(session, withdrawn, expected_version=task.version)
        self._record(session, actor, withdrawn, "ai.plan_withdrawn", 0, 0, correlation_id, now)

    def _record(
        self,
        session: TxSession,
        actor: Actor,
        task: Task,
        event: str,
        steps: int,
        ai_steps: int,
        correlation_id: str | None,
        now: datetime,
    ) -> None:
        """One audit event and one activity entry: ids and counts, never a title or a spec."""

        self.store.append_audit(
            session,
            actor_id=actor.user_id,
            event=event,
            outcome="success",
            target_type="task",
            target_id=task.id,
            correlation_id=correlation_id,
        )
        if self.activity is None:
            return
        self.activity.append(
            session,
            owner_id=actor.user_id,
            aggregate_type="task",
            aggregate_id=task.id,
            aggregate_version=task.version,
            event_type=event,
            actor_type="user",
            actor_id=actor.user_id,
            operation=event.removeprefix("ai."),
            category=ActivityCategory.AI_STEPS,
            summary=f"AI plan: {event.removeprefix('ai.plan_')}",
            after_values={"steps": steps, "ai_steps": ai_steps},
            correlation_id=correlation_id,
            occurred_at=now,
        )
