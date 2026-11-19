"""Queueing an approved AI step for the server and cancelling the run, against PostgreSQL."""

import os
from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from sidekick.api.app import Container
from sidekick.lifecycle.domain import RecordKind
from sidekick.shared.errors import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from sidekick.shared.types import Actor
from sidekick.tasks.domain.recurrence import RecurrenceData
from sidekick.work.application.ai_store import AiPlanView
from sidekick.work.domain.ai_plan import AiStepStatus
from sidekick.work.domain.ai_runs import AiRunState, AiStepRun, AiUsage, RunnerKind
from sidekick.work.domain.ai_spec import Capability, Privacy, RunnerPreference
from tests.db import _cleanup_factory_for  # pyright: ignore[reportPrivateUsage]
from tests.support.ai_runner import FakeModel, answer, make_runner, runner_container
from tests.support.ai_steps import (
    SCOPES,
    admin_rows,
    ai_item,
    approve,
    approved_plan,
    container_with,
    key,
    new_task,
    owner_actor,
    plan,
    spec,
)

pytestmark = pytest.mark.integration

DAILY: RecurrenceData = {
    "frequency": "daily",
    "interval": 1,
    "weekdays": [],
    "day_of_month": None,
    "last_weekday": False,
    "until": None,
}


def queue(container: Container, actor: Actor, view: AiPlanView) -> AiPlanView:
    return container.ai_server_runs.queue_plan_step(
        actor, view.task.id, digest=view.digest, idempotency_key=key()
    )


def latest_run(view: AiPlanView) -> AiStepRun:
    run = view.steps[0].history.latest
    assert run is not None
    return run


def cancel(container: Container, actor: Actor, run: AiStepRun) -> AiStepRun:
    return container.ai_server_runs.cancel_run(
        actor, run.id, run_version=run.version, idempotency_key=key()
    )


def refused_with(container: Container, actor: Actor, view: AiPlanView) -> str | None:
    with pytest.raises(ConflictError) as raised:
        queue(container, actor, view)
    return raised.value.reason


def run_count() -> int:
    return int(admin_rows("SELECT count(*) FROM sidekick.ai_step_runs")[0][0])  # type: ignore[call-overload]


def book_cost(run_id: UUID, microusd: int, source: str) -> None:
    """Give a run a cost the way a finished run would have it, as the schema owner."""

    admin = _cleanup_factory_for(os.environ["SIDEKICK_TEST_ADMIN_DATABASE_URL"])
    with admin.begin() as session:
        session.execute(
            text(
                "UPDATE sidekick.ai_step_runs SET cost_microusd = :cost, cost_source = :source "
                "WHERE id = :id"
            ),
            {"cost": microusd, "source": source, "id": run_id},
        )


def cancelled_with_cost(
    container: Container, actor: Actor, view: AiPlanView, microusd: int, source: str
) -> AiPlanView:
    """Queue the step, cancel the run and book `microusd` on it; the step is ready again."""

    run = latest_run(queue(container, actor, view))
    cancel(container, actor, run)
    book_cost(run.id, microusd, source)
    return container.ai_plans.get_plan(actor, view.task.id)


def test_a_queued_step_is_a_queued_server_run() -> None:
    container = runner_container()
    actor = owner_actor(container)
    view = approved_plan(container, actor)
    before = container.ai_plans.get_plan(actor, view.task.id)
    assert before.steps[0].server_startable is True

    queued = queue(container, actor, view)

    run = latest_run(queued)
    assert run.state is AiRunState.QUEUED
    assert run.runner is RunnerKind.SERVER
    assert run.attempt == 1
    assert queued.steps[0].status is AiStepStatus.RUNNING
    assert queued.server is not None and queued.server.available is True
    assert run_count() == 1


def test_the_same_key_queues_one_run() -> None:
    container = runner_container()
    actor = owner_actor(container)
    view = approved_plan(container, actor)
    same_key = key()

    first = container.ai_server_runs.queue_plan_step(
        actor, view.task.id, digest=view.digest, idempotency_key=same_key
    )
    second = container.ai_server_runs.queue_plan_step(
        actor, view.task.id, digest=view.digest, idempotency_key=same_key
    )

    assert latest_run(first).id == latest_run(second).id
    assert run_count() == 1


def test_a_plan_that_is_not_the_one_the_owner_saw_is_not_run() -> None:
    container = runner_container()
    actor = owner_actor(container)
    view = approved_plan(container, actor)

    assert refused_with(container, actor, replace(view, digest="0" * 64)) == "plan_changed"
    assert run_count() == 0


def test_a_plan_that_is_not_approved_is_not_run() -> None:
    container = runner_container()
    actor = owner_actor(container)
    proposal = plan(container, actor, [ai_item("Look it up")])

    assert refused_with(container, actor, proposal) == "plan_not_approved"
    assert run_count() == 0


def test_a_plan_changed_after_approval_is_not_run() -> None:
    container = runner_container()
    actor = owner_actor(container)
    view = approved_plan(container, actor)
    step = container.ai_plans.get_plan(actor, view.task.id).steps[0].step
    container.steps.update_step(
        actor, step.id, version=step.version, title="Changed title", idempotency_key=key()
    )
    changed = container.ai_plans.get_plan(actor, view.task.id)

    assert refused_with(container, actor, changed) == "plan_changed"
    assert run_count() == 0


def test_a_server_with_the_runner_off_queues_nothing() -> None:
    container = container_with(ai_runner_enabled=False)
    actor = owner_actor(container)
    view = approved_plan(container, actor)

    assert refused_with(container, actor, view) == "ai_runner_off"
    assert container.ai_plans.get_plan(actor, view.task.id).steps[0].server_startable is False
    assert run_count() == 0


def test_a_model_without_a_known_price_is_not_run() -> None:
    container = runner_container(ai_model="some-unknown-model")
    actor = owner_actor(container)
    view = approved_plan(container, actor)

    assert refused_with(container, actor, view) == "ai_runner_off"
    server = container.ai_plans.get_plan(actor, view.task.id).server
    assert server is not None and server.available is False


def test_a_step_meant_for_claude_code_is_not_a_server_step() -> None:
    container = runner_container()
    actor = owner_actor(container)
    view = approved_plan(
        container, actor, [ai_item("Code", spec(runner=RunnerPreference.CLAUDE_CODE))]
    )

    with pytest.raises(ValidationError):
        queue(container, actor, view)
    assert run_count() == 0


@pytest.mark.parametrize(
    "step_spec",
    [
        spec(runner=RunnerPreference.SERVER, privacy=Privacy.LOCAL_ONLY),
        spec(capabilities=[Capability.WEB_SEARCH]),
    ],
    ids=["local_only", "web_search"],
)
def test_a_step_the_server_cannot_do_is_refused(step_spec: object) -> None:
    container = runner_container()
    actor = owner_actor(container)
    view = approved_plan(container, actor, [ai_item("Needs more", step_spec)])  # type: ignore[arg-type]

    assert refused_with(container, actor, view) == "ai_runner_off"
    assert container.ai_plans.get_plan(actor, view.task.id).steps[0].server_startable is False
    assert run_count() == 0


def test_queueing_needs_the_right_to_change_the_task() -> None:
    container = runner_container()
    actor = owner_actor(container)
    view = approved_plan(container, actor)

    for scopes in (frozenset({"tasks:read"}), frozenset({"tasks:read", "ai:run"})):
        with pytest.raises(PermissionDeniedError):
            queue(container, Actor(actor.user_id, scopes), view)
    assert run_count() == 0


def test_cancelling_needs_the_right_to_change_the_task() -> None:
    container = runner_container()
    actor = owner_actor(container)
    run = latest_run(queue(container, actor, approved_plan(container, actor)))

    with pytest.raises(PermissionDeniedError):
        cancel(container, Actor(actor.user_id, frozenset({"tasks:read", "ai:run"})), run)
    assert container.ai_plans.get_plan(actor, run.task_id).steps[0].status is AiStepStatus.RUNNING


def test_another_owner_cannot_queue_the_step() -> None:
    container = runner_container()
    actor = owner_actor(container)
    view = approved_plan(container, actor)
    other = Actor(container.auth.provision_user("ai-other-owner", "Other"), SCOPES)

    with pytest.raises(NotFoundError):
        queue(container, other, view)
    assert run_count() == 0


def test_a_step_that_is_already_queued_is_not_queued_again() -> None:
    container = runner_container()
    actor = owner_actor(container)
    view = approved_plan(container, actor)
    queue(container, actor, view)

    assert refused_with(container, actor, view) == "step_not_ready"
    assert run_count() == 1


def test_the_daily_limit_of_starts_is_kept_even_for_cancelled_runs() -> None:
    container = runner_container(ai_server_starts_per_day=1)
    actor = owner_actor(container)
    view = approved_plan(container, actor)
    cancel(container, actor, latest_run(queue(container, actor, view)))

    assert refused_with(container, actor, view) == "ai_limit_reached"
    assert run_count() == 1


def test_a_task_that_has_cost_nearly_its_cap_is_not_queued() -> None:
    container = runner_container()
    actor = owner_actor(container)
    view = approved_plan(container, actor)
    ready = cancelled_with_cost(container, actor, view, 1_900_000, "price_table")
    assert ready.steps[0].status is AiStepStatus.READY

    assert refused_with(container, actor, ready) == "ai_budget_reached"
    assert run_count() == 1


def test_a_month_that_has_cost_nearly_its_cap_is_not_queued() -> None:
    container = runner_container(ai_monthly_cap_usd=1.0)
    actor = owner_actor(container)
    view = approved_plan(container, actor)
    ready = cancelled_with_cost(container, actor, view, 900_000, "price_table")

    assert refused_with(container, actor, ready) == "ai_budget_reached"
    assert run_count() == 1


def test_the_month_counts_the_spending_on_other_tasks() -> None:
    container = runner_container(ai_monthly_cap_usd=1.0)
    actor = owner_actor(container)
    cancelled_with_cost(container, actor, approved_plan(container, actor), 900_000, "price_table")
    other_task = new_task(container, actor, "Another errand")
    other = approve(container, actor, plan(container, actor, [ai_item("Too")], task=other_task))

    assert refused_with(container, actor, other) == "ai_budget_reached"


def test_a_cost_the_client_estimated_does_not_count() -> None:
    container = runner_container()
    actor = owner_actor(container)
    view = approved_plan(container, actor)
    ready = cancelled_with_cost(container, actor, view, 1_990_000, "client_estimate")

    queued = queue(container, actor, ready)

    assert latest_run(queued).state is AiRunState.QUEUED
    assert latest_run(queued).attempt == 2


def test_a_client_cannot_report_on_a_run_the_server_runs() -> None:
    container = runner_container()
    actor = owner_actor(container)
    view = approved_plan(container, actor)
    run = latest_run(queue(container, actor, view))
    book_cost(run.id, 700_000, "price_table")
    admin = _cleanup_factory_for(os.environ["SIDEKICK_TEST_ADMIN_DATABASE_URL"])
    with admin.begin() as session:
        session.execute(
            text("UPDATE sidekick.ai_step_runs SET state = 'running' WHERE id = :id"),
            {"id": run.id},
        )

    with pytest.raises(ConflictError) as raised:
        container.ai_runs.report(
            actor,
            run.id,
            run_version=run.version,
            outcome="failure",
            usage=AiUsage(),
            idempotency_key=key(),
        )

    assert raised.value.reason == "run_not_open"
    row = admin_rows(
        "SELECT state, cost_microusd, cost_source FROM sidekick.ai_step_runs WHERE id = :id",
        id=run.id,
    )[0]
    assert tuple(row) == ("running", 700_000, "price_table")


def test_cancelling_a_queued_run_ends_it_and_leaves_the_step_ready() -> None:
    container = runner_container()
    actor = owner_actor(container)
    view = approved_plan(container, actor)
    run = latest_run(queue(container, actor, view))

    cancelled = cancel(container, actor, run)

    assert cancelled.state is AiRunState.CANCELLED
    ready = container.ai_plans.get_plan(actor, view.task.id)
    assert ready.steps[0].status is AiStepStatus.READY
    assert ready.steps[0].history.attempts == 0
    again = queue(container, actor, ready)
    assert latest_run(again).state is AiRunState.QUEUED
    assert latest_run(again).attempt == 2


def test_cancelling_with_an_old_version_is_refused() -> None:
    container = runner_container()
    actor = owner_actor(container)
    run = latest_run(queue(container, actor, approved_plan(container, actor)))

    with pytest.raises(ConflictError) as raised:
        container.ai_server_runs.cancel_run(
            actor, run.id, run_version=run.version + 1, idempotency_key=key()
        )

    assert raised.value.reason == "stale_version"
    assert container.ai_plans.get_plan(actor, run.task_id).steps[0].status is AiStepStatus.RUNNING


def test_a_run_that_has_ended_cannot_be_cancelled() -> None:
    container = runner_container()
    actor = owner_actor(container)
    run = latest_run(queue(container, actor, approved_plan(container, actor)))
    cancelled = cancel(container, actor, run)

    with pytest.raises(ConflictError) as raised:
        cancel(container, actor, cancelled)

    assert raised.value.reason == "run_not_open"


def test_cancelling_twice_with_the_same_key_cancels_once() -> None:
    container = runner_container()
    actor = owner_actor(container)
    run = latest_run(queue(container, actor, approved_plan(container, actor)))
    same_key = key()

    first = container.ai_server_runs.cancel_run(
        actor, run.id, run_version=run.version, idempotency_key=same_key
    )
    second = container.ai_server_runs.cancel_run(
        actor, run.id, run_version=run.version, idempotency_key=same_key
    )

    assert first.state is second.state is AiRunState.CANCELLED
    assert first.version == second.version == run.version + 1


def test_the_server_info_shows_what_the_task_and_the_month_have_cost() -> None:
    container = runner_container()
    actor = owner_actor(container)
    view = approved_plan(container, actor)
    ready = cancelled_with_cost(container, actor, view, 123_456, "price_table")
    ready = cancelled_with_cost(container, actor, ready, 777_000, "client_estimate")

    queued = queue(container, actor, ready)

    assert queued.server is not None
    assert queued.server.task_spent_microusd == 123_456
    assert queued.server.month_spent_microusd == 123_456
    assert queued.server.month_cap_microusd == 50_000_000
    shown = container.ai_plans.get_plan(actor, view.task.id).server
    assert shown == queued.server


def erase(container: Container, actor: Actor, kind: RecordKind, record_id: UUID) -> None:
    """Trash a record and remove it permanently."""

    version = {
        RecordKind.TASK: lambda: container.tasks.get(actor, record_id).version,
        RecordKind.STEP: lambda: container.steps.get_step(actor, record_id).version,
    }[kind]()
    trashed = container.lifecycle.trash(
        actor, kind, record_id, version=version, idempotency_key=key()
    )
    container.lifecycle.permanently_remove(
        actor, kind, record_id, version=trashed.version, idempotency_key=key()
    )


def erase_task(container: Container, actor: Actor, task_id: UUID) -> None:
    """Remove a Task permanently, after its Steps, as the trash allows."""

    for item in container.ai_plans.get_plan(actor, task_id).steps:
        erase(container, actor, RecordKind.STEP, item.step.id)
    erase(container, actor, RecordKind.TASK, task_id)


def kept_costs() -> list[tuple[object, ...]]:
    return admin_rows("SELECT runner, cost_source, cost_microusd FROM sidekick.ai_erased_run_costs")


def test_the_cost_of_an_erased_task_still_counts_in_the_month() -> None:
    container = runner_container()
    actor = owner_actor(container)
    view = approved_plan(container, actor)
    cancelled_with_cost(container, actor, view, 2_000_000, "price_table")

    erase_task(container, actor, view.task.id)

    assert run_count() == 0
    assert kept_costs() == [("server", "price_table", 2_000_000)]
    other_task = new_task(container, actor, "Another errand")
    other = approve(container, actor, plan(container, actor, [ai_item("Too")], task=other_task))
    server = container.ai_plans.get_plan(actor, other.task.id).server
    assert server is not None
    assert server.month_spent_microusd == 2_000_000
    assert server.task_spent_microusd == 0


def test_the_cost_of_an_erased_step_still_counts_for_its_task() -> None:
    container = runner_container()
    actor = owner_actor(container)
    view = approved_plan(container, actor)
    ready = cancelled_with_cost(container, actor, view, 700_000, "price_table")

    erase(container, actor, RecordKind.STEP, ready.steps[0].step.id)

    server = container.ai_plans.get_plan(actor, view.task.id).server
    assert server is not None
    assert server.task_spent_microusd == 700_000
    assert server.month_spent_microusd == 700_000


def test_a_cost_the_client_estimated_stays_out_of_the_month_after_the_task_is_erased() -> None:
    container = runner_container()
    actor = owner_actor(container)
    view = approved_plan(container, actor)
    cancelled_with_cost(container, actor, view, 1_500_000, "client_estimate")

    erase_task(container, actor, view.task.id)

    other_task = new_task(container, actor, "Another errand")
    other = approve(container, actor, plan(container, actor, [ai_item("Too")], task=other_task))
    server = container.ai_plans.get_plan(actor, other.task.id).server
    assert server is not None and server.month_spent_microusd == 0


def test_the_daily_limit_of_starts_counts_runs_of_an_erased_task() -> None:
    container = runner_container(ai_server_starts_per_day=1)
    actor = owner_actor(container)
    view = approved_plan(container, actor)
    cancel(container, actor, latest_run(queue(container, actor, view)))

    erase_task(container, actor, view.task.id)

    other_task = new_task(container, actor, "Another errand")
    other = approve(container, actor, plan(container, actor, [ai_item("Too")], task=other_task))
    assert refused_with(container, actor, other) == "ai_limit_reached"


def test_a_reservation_still_held_when_the_task_is_erased_is_kept_as_cost() -> None:
    container = runner_container()
    actor = owner_actor(container)
    run = latest_run(queue(container, actor, approved_plan(container, actor)))
    admin = _cleanup_factory_for(os.environ["SIDEKICK_TEST_ADMIN_DATABASE_URL"])
    with admin.begin() as session:
        session.execute(
            text(
                "UPDATE sidekick.ai_step_runs SET state = 'running', cost_source = 'price_table', "
                "reserved_microusd = 300000, cost_microusd = 5000 WHERE id = :id"
            ),
            {"id": run.id},
        )

    erase_task(container, actor, run.task_id)

    assert kept_costs() == [("server", "price_table", 305_000)]


def test_erasing_the_account_leaves_no_cost_behind() -> None:
    container = runner_container()
    actor = owner_actor(container)
    view = approved_plan(container, actor)
    cancelled_with_cost(container, actor, view, 400_000, "price_table")
    erase_task(container, actor, view.task.id)
    queue(container, actor, approved_plan(container, actor))
    assert len(kept_costs()) == 1 and run_count() == 1

    admin = _cleanup_factory_for(os.environ["SIDEKICK_TEST_ADMIN_DATABASE_URL"])
    with admin.begin() as session:
        session.execute(text("DELETE FROM sidekick.users WHERE id = :id"), {"id": actor.user_id})

    assert run_count() == 0
    assert kept_costs() == []


def test_three_started_attempts_use_up_the_step_until_the_next_cycle() -> None:
    container = runner_container()
    actor = owner_actor(container)
    task = container.tasks.create(
        actor,
        title="Weekly price check",
        idempotency_key=key(),
        due_at=container.tasks.clock.now() + timedelta(days=1),
        recurrence=DAILY,
    )
    view = approve(container, actor, plan(container, actor, [ai_item("Look it up")], task=task))
    model = FakeModel([answer(outcome="failed", failure="blocked")])

    for attempt in (1, 2, 3):
        queued = queue(container, actor, view)
        assert latest_run(queued).attempt == attempt
        assert make_runner(container, model).run_next("worker-1") is True
        failed = container.ai_plans.get_plan(actor, task.id)
        assert latest_run(failed).state is AiRunState.FAILED
        assert failed.steps[0].history.attempts == attempt

    after = container.ai_plans.get_plan(actor, task.id)
    assert after.steps[0].status is AiStepStatus.EXHAUSTED
    assert refused_with(container, actor, after) == "ai_limit_reached"
    assert model.calls == 3

    current = container.tasks.get(actor, task.id)
    container.tasks.complete(
        actor, task.id, version=current.version, idempotency_key=f"complete-{uuid4()}"
    )

    renewed = container.ai_plans.get_plan(actor, task.id)
    assert renewed.steps[0].status is AiStepStatus.READY
    assert renewed.steps[0].history.attempts == 0
    assert latest_run(queue(container, actor, renewed)).attempt == 4
