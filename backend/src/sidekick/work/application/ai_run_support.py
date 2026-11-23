"""What the AI Step use cases share: spec and readiness checks, the brief and the audit trail."""

from collections.abc import Callable, Collection
from dataclasses import replace
from datetime import UTC, datetime, tzinfo
from typing import Literal
from uuid import UUID

from sidekick.activity.domain import ActivityCategory
from sidekick.shared.errors import ConflictError, NotFoundError, ValidationError
from sidekick.shared.errors.core import SidekickError
from sidekick.shared.owner_day import month_start
from sidekick.shared.replay import id_replay_record, record_id
from sidekick.shared.types import Actor, TxSession
from sidekick.tasks.domain import Task
from sidekick.work.application.ai_store import (
    LINK_NAMES_LIMIT,
    AiLimits,
    AiPlanStepView,
    AiPlanView,
    AiStepsStore,
    ServerRunInfo,
    ServerRunnerConfig,
)
from sidekick.work.domain import Step
from sidekick.work.domain.ai_plan import (
    STARTABLE,
    AiStepStatus,
    BriefSource,
    PlanState,
    render_brief,
    runs_on,
)
from sidekick.work.domain.ai_runs import AiRunState, AiStepRun, CostSource, RunnerKind
from sidekick.work.domain.ai_spec import AiStepSpecV1, Capability, Performer, Privacy
from sidekick.work.domain.run_ports import RunActivityRecorder

WORKER_SCOPES = frozenset({"ai:run", "tasks:read", "projects:read", "contacts:read"})
"""What a server run may read of the owner's data: names and titles, never any write."""


def require_spec(step: Step) -> AiStepSpecV1:
    if step.performer is not Performer.AI or step.ai_spec is None:
        raise ValidationError("this is not an AI step")
    return step.ai_spec


def server_blocker(spec: AiStepSpecV1) -> SidekickError | None:
    """Why the server cannot run a step with this spec, as the error to raise; None if it can."""

    if not runs_on(spec, RunnerKind.SERVER):
        return ValidationError("this step is meant for Claude Code")
    if spec.privacy is Privacy.LOCAL_ONLY:
        return ConflictError("this server has no local model", reason="ai_runner_off")
    if {Capability.WEB_SEARCH, Capability.WEB_FETCH} & set(spec.capabilities):
        return ConflictError("web tools are off on this server", reason="ai_runner_off")
    return None


def require_approved(view: AiPlanView) -> None:
    if view.state is PlanState.CHANGED_SINCE_APPROVAL:
        raise ConflictError("the plan changed since it was approved", reason="plan_changed")
    if view.state is not PlanState.APPROVED:
        raise ConflictError("the plan is not approved", reason="plan_not_approved")


def require_startable(view: AiPlanView, step_id: UUID) -> AiPlanStepView:
    require_approved(view)
    item = next((item for item in view.steps if item.step.id == step_id), None)
    if item is None:
        raise NotFoundError("step not found")
    require_spec(item.step)
    if item.status is AiStepStatus.EXHAUSTED:
        raise ConflictError("every attempt at the step is used", reason="ai_limit_reached")
    if item.status not in STARTABLE:
        raise ConflictError("the step is not ready", reason="step_not_ready")
    return item


def carried_over(earlier: AiStepRun | None) -> AiStepRun | None:
    """The attempt before this one when the owner's redo or answer is to be carried over."""

    if earlier is None:
        return None
    return earlier if earlier.state in (AiRunState.REDO, AiRunState.ANSWERED) else None


def render_run_brief(
    store: AiStepsStore,
    session: TxSession,
    *,
    run: AiStepRun,
    task: Task,
    step: Step,
    spec: AiStepSpecV1,
    scopes: Collection[str],
    runner: RunnerKind,
) -> str:
    """The brief for `run`, with the names and titles that `scopes` allow it to read."""

    owner_id = run.owner_id
    earlier = store.previous_ai_run(
        session, owner_id, step.id, run.attempt, since=task.last_completed_at
    )
    project_title = None
    if task.project_id is not None and "projects:read" in scopes:
        project_title = store.project_titles(session, owner_id, (task.project_id,)).get(
            task.project_id
        )
    contact_names = ()
    if spec.context.include_contacts and "contacts:read" in scopes:
        contact_names = tuple(
            store.task_contact_names(session, owner_id, task.id, LINK_NAMES_LIMIT)
        )
    reference_titles = ()
    if spec.context.include_references and "tasks:read" in scopes:
        reference_titles = tuple(
            store.task_reference_titles(session, owner_id, task.id, LINK_NAMES_LIMIT)
        )
    actions = store.list_actions_for_steps(session, owner_id, (step.id,))
    return render_brief(
        BriefSource(
            task_title=task.title,
            task_description=task.description,
            step=step,
            spec=spec,
            actions=actions.get(step.id, ()),
            run_id=run.id,
            run_version=run.version,
            project_title=project_title,
            contact_names=contact_names,
            reference_titles=reference_titles,
            previous=carried_over(earlier),
        ),
        runner,
    )


def record_run_event(
    store: AiStepsStore,
    activity: RunActivityRecorder | None,
    session: TxSession,
    run: AiStepRun,
    event: str,
    *,
    actor_type: str,
    now: datetime,
    correlation_id: str | None = None,
) -> None:
    """One audit event and one activity entry: ids, state, attempt and the task title."""

    store.append_audit(
        session,
        actor_id=run.owner_id,
        event=event,
        outcome="success",
        target_type="ai_step_run",
        target_id=run.id,
        related_id=run.step_id,
        correlation_id=correlation_id,
    )
    if activity is None:
        return
    try:
        title = store.get_task(session, run.owner_id, run.task_id).title
    except NotFoundError:
        title = None
    activity.append(
        session,
        owner_id=run.owner_id,
        aggregate_type="ai_step_run",
        aggregate_id=run.id,
        aggregate_version=run.version,
        event_type=event,
        actor_type=actor_type,
        actor_id=run.owner_id if actor_type == "user" else None,
        operation=event.removeprefix("ai."),
        category=ActivityCategory.AI_STEPS,
        summary=f"AI step run {run.state.value.replace('_', ' ')}"
        + (f": {title}" if title else ""),
        after_values={
            "state": run.state.value,
            "attempt": run.attempt,
            **({"title": title} if title else {}),
        },
        evidence={"task_id": run.task_id, "step_id": run.step_id},
        correlation_id=correlation_id,
        occurred_at=now,
    )


def replayed_run(
    store: AiStepsStore,
    actor: Actor,
    name: str,
    key: str,
    payload: dict[str, object],
    operation: Callable[[TxSession], dict[str, str]],
) -> AiStepRun:
    """Run `operation` once per key and answer with the run it wrote, re-read by id."""

    def replayed(session: TxSession) -> AiStepRun:
        record = store.idempotent(
            session,
            actor_id=actor.user_id,
            operation=name,
            key=key,
            payload=payload,
            execute=lambda: operation(session),
            replay=id_replay_record,
        )
        return store.get_ai_run(session, actor.user_id, record_id(record))

    return store.transaction(replayed)


def flag_attention(store: AiStepsStore, session: TxSession, run: AiStepRun, now: datetime) -> None:
    """Mark the run's step as waiting for the owner, unless it already is."""

    step = store.get_step(session, run.owner_id, run.step_id)
    if step.attention_requested:
        return
    flagged = step.update(now=now, attention_requested=True)
    store.save_step(session, flagged, expected_version=step.version)


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def breached_cap(
    store: AiStepsStore,
    session: TxSession,
    *,
    run: AiStepRun,
    task: Task,
    spec: AiStepSpecV1,
    limits: AiLimits,
    reserve_microusd: int,
    now: datetime,
    zone: tzinfo,
) -> Literal["step", "task", "month"] | None:
    """The cap that reserving `reserve_microusd` for a call of `run` would pass, if any.

    What counts as spent is what the runs cost plus what calls in flight reserved, so a cap holds
    when several calls are decided one after the other under the owner's spend lock. The Task's
    spending is counted from the start of its current cycle.
    """

    caps = limits.money_caps()
    counted = [source for source in CostSource if caps.counts(source)]
    return caps.breached_cap(
        source=CostSource.PRICE_TABLE,
        reserve_microusd=reserve_microusd,
        spent_on_task_microusd=store.sum_ai_cost_since(
            session, run.owner_id, task.last_completed_at or _EPOCH, counted, task_id=task.id
        ),
        spent_in_month_microusd=store.sum_ai_cost_since(
            session, run.owner_id, month_start(now, zone), counted
        ),
        task_cap_microusd=limits.task_cap(task),
        spent_on_run_microusd=run.usage.cost_microusd,
        run_budget_microusd=spec.budget_microusd(),
    )


def with_server_info(
    view: AiPlanView,
    store: AiStepsStore,
    session: TxSession,
    *,
    config: ServerRunnerConfig,
    limits: AiLimits,
    now: datetime,
    zone: tzinfo,
) -> AiPlanView:
    """`view` with what the owner needs to run a step on the server: which step may, and the
    spending of the Task's cycle and of the month against their caps."""

    caps = limits.money_caps()
    counted = [source for source in CostSource if caps.counts(source)]
    task = view.task
    steps = [
        replace(
            item,
            server_startable=config.available
            and item.status in STARTABLE
            and item.step.ai_spec is not None
            and server_blocker(item.step.ai_spec) is None,
        )
        for item in view.steps
    ]
    return replace(
        view,
        steps=steps,
        server=ServerRunInfo(
            available=config.available,
            task_spent_microusd=store.sum_ai_cost_since(
                session, task.owner_id, task.last_completed_at or _EPOCH, counted, task_id=task.id
            ),
            month_spent_microusd=store.sum_ai_cost_since(
                session, task.owner_id, month_start(now, zone), counted
            ),
            month_cap_microusd=limits.monthly_cap_microusd,
        ),
    )
