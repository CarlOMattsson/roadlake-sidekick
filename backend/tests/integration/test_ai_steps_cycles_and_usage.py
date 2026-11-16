"""AI Step attempts per cycle of a repeating Task, and the month's AI cost and starts today."""

import os
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from sidekick.api.app import Container
from sidekick.shared.errors import ConflictError, PermissionDeniedError
from sidekick.shared.types import Actor
from sidekick.tasks.domain import Task
from sidekick.tasks.domain.recurrence import RecurrenceData
from sidekick.work.application.ai_store import AiUsageSummary
from sidekick.work.domain.ai_plan import AiStepStatus
from sidekick.work.domain.ai_runs import (
    AiRunResult,
    AiStepRun,
    AiUsage,
    CostSource,
    FailureCategory,
)
from sidekick.work.domain.ai_spec import ResultFormat
from tests.db import _cleanup_factory_for
from tests.support.ai_steps import (
    ai_item,
    approve,
    approved_plan,
    container_with,
    key,
    owner_actor,
    plan,
)

pytestmark = pytest.mark.integration

DAILY: RecurrenceData = {
    "frequency": "daily",
    "interval": 1,
    "weekdays": [],
    "day_of_month": None,
    "until": None,
}
MICRO = 1_000_000


def _repeating_plan(container: Container, actor: Actor) -> tuple[Task, UUID]:
    task = container.tasks.create(
        actor,
        title="Weekly price check",
        idempotency_key=key(),
        due_at=container.tasks.clock.now() + timedelta(days=1),
        recurrence=DAILY,
    )
    view = approve(container, actor, plan(container, actor, [ai_item("Look it up")], task=task))
    return task, view.steps[0].step.id


def _run(
    container: Container, actor: Actor, step_id: UUID, outcome: str, usage: AiUsage
) -> AiStepRun:
    started = container.ai_runs.start_step(actor, step_id, idempotency_key=key())
    kind: dict[str, object] = (
        {"result": AiRunResult(format=ResultFormat.TEXT, text="Found.", summary="Found")}
        if outcome == "result"
        else {"failure": FailureCategory.TOOL_ERROR}
    )
    return container.ai_runs.report(
        actor,
        started.run.id,
        run_version=started.run.version,
        outcome=outcome,  # type: ignore[arg-type]
        usage=usage,
        idempotency_key=key(),
        **kind,  # type: ignore[arg-type]
    )


def _status(container: Container, actor: Actor, task: Task) -> AiStepStatus | None:
    return container.ai_plans.get_plan(actor, task.id).steps[0].status


def _complete(container: Container, actor: Actor, task: Task) -> None:
    current = container.tasks.get(actor, task.id)
    container.tasks.complete(
        actor, task.id, version=current.version, idempotency_key=f"complete-{uuid4()}"
    )


def _admin(sql: str, **params: object) -> None:
    admin = _cleanup_factory_for(os.environ["SIDEKICK_TEST_ADMIN_DATABASE_URL"])
    with admin.begin() as session:
        session.execute(text(sql), params)


def test_a_repeating_task_gets_its_attempts_back_when_a_cycle_is_completed() -> None:
    container = container_with()
    actor = owner_actor(container)
    task, step_id = _repeating_plan(container, actor)
    for _ in range(3):
        _run(container, actor, step_id, "failed", AiUsage())

    assert _status(container, actor, task) is AiStepStatus.EXHAUSTED
    with pytest.raises(ConflictError) as raised:
        container.ai_runs.start_step(actor, step_id, idempotency_key=key())
    assert raised.value.reason == "ai_limit_reached"

    _complete(container, actor, task)

    assert _status(container, actor, task) is AiStepStatus.READY
    step = container.ai_plans.get_plan(actor, task.id).steps[0]
    assert (step.history.attempts, step.history.latest) == (0, None)
    # The next run is numbered after the earlier ones, so the step's attempt numbers stay unique.
    assert container.ai_runs.start_step(actor, step_id, idempotency_key=key()).run.attempt == 4


def test_the_attempts_of_the_new_cycle_are_counted_on_their_own() -> None:
    container = container_with()
    actor = owner_actor(container)
    task, step_id = _repeating_plan(container, actor)
    for _ in range(3):
        _run(container, actor, step_id, "failed", AiUsage())
    _complete(container, actor, task)

    for _ in range(3):
        _run(container, actor, step_id, "failed", AiUsage())

    assert _status(container, actor, task) is AiStepStatus.EXHAUSTED


def test_a_task_that_did_not_complete_a_cycle_keeps_its_attempts() -> None:
    container = container_with()
    actor = owner_actor(container)
    view = approved_plan(container, actor, [ai_item("Look it up")])
    for _ in range(3):
        _run(container, actor, view.steps[0].step.id, "failed", AiUsage())

    after = container.ai_plans.get_plan(actor, view.task.id)

    assert after.steps[0].status is AiStepStatus.EXHAUSTED
    assert after.steps[0].history.attempts == 3


def test_a_result_waiting_in_the_old_cycle_does_not_decide_the_new_cycle() -> None:
    container = container_with()
    actor = owner_actor(container)
    task, step_id = _repeating_plan(container, actor)
    _run(container, actor, step_id, "result", AiUsage())
    assert _status(container, actor, task) is AiStepStatus.TO_REVIEW

    _complete(container, actor, task)

    assert _status(container, actor, task) is AiStepStatus.READY


def _usage_of(container: Container, actor: Actor) -> AiUsageSummary:
    return container.ai_runs.usage(actor)


def test_the_month_counts_billed_cost_and_keeps_client_estimates_apart() -> None:
    container = container_with(ai_monthly_cap_usd=20, ai_claude_code_starts_per_day=7)
    actor = owner_actor(container)
    view = approved_plan(container, actor, [ai_item("One"), ai_item("Two"), ai_item("Three")])
    first, second, third = (item.step.id for item in view.steps)
    for step_id, source, cost in (
        (first, CostSource.PROVIDER, 1_250_000),
        (second, CostSource.PRICE_TABLE, 250_000),
        (third, CostSource.CLIENT_ESTIMATE, 4 * MICRO),
    ):
        run = _run(
            container, actor, step_id, "result", AiUsage(cost_microusd=cost, cost_source=source)
        )
        container.ai_runs.review(
            actor, run.id, run_version=run.version, decision="accept", idempotency_key=key()
        )

    usage = _usage_of(container, actor)

    assert usage.spent_microusd == 1_500_000
    assert usage.client_estimate_microusd == 4 * MICRO
    assert usage.monthly_cap_microusd == 20 * MICRO
    assert (usage.starts_today, usage.starts_per_day_cap) == (3, 7)


def test_a_run_from_an_earlier_month_is_not_in_this_months_cost() -> None:
    container = container_with()
    actor = owner_actor(container)
    view = approved_plan(container, actor, [ai_item("One")])
    _run(
        container,
        actor,
        view.steps[0].step.id,
        "result",
        AiUsage(cost_microusd=MICRO, cost_source=CostSource.PROVIDER),
    )
    assert _usage_of(container, actor).spent_microusd == MICRO

    _admin("UPDATE sidekick.ai_step_runs SET created_at = created_at - interval '45 days'")

    usage = _usage_of(container, actor)
    assert (usage.spent_microusd, usage.starts_today) == (0, 0)


def test_the_cost_of_a_repeating_task_is_not_reset_by_a_new_cycle() -> None:
    container = container_with()
    actor = owner_actor(container)
    task, step_id = _repeating_plan(container, actor)
    _run(
        container,
        actor,
        step_id,
        "failed",
        AiUsage(cost_microusd=MICRO, cost_source=CostSource.PROVIDER),
    )
    _complete(container, actor, task)

    assert _usage_of(container, actor).spent_microusd == MICRO
    assert _usage_of(container, actor).starts_today == 1


def test_another_owners_runs_are_not_in_the_usage() -> None:
    container = container_with()
    mine = owner_actor(container, "ai-owner")
    other = owner_actor(container, "ai-other-owner")
    view = approved_plan(container, other, [ai_item("Theirs")])
    _run(
        container,
        other,
        view.steps[0].step.id,
        "failed",
        AiUsage(cost_microusd=MICRO, cost_source=CostSource.PROVIDER),
    )

    usage = _usage_of(container, mine)

    assert (usage.spent_microusd, usage.starts_today) == (0, 0)


def test_the_usage_needs_the_read_scope() -> None:
    container = container_with()
    actor = owner_actor(container)

    with pytest.raises(PermissionDeniedError):
        container.ai_runs.usage(Actor(actor.user_id, frozenset({"ai:run"})))
