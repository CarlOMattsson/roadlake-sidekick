"""The AI runner's spending limits against PostgreSQL: no call is made that could pass a cap.

Before a call the runner reserves the most the call can cost and refuses it when that would pass
the step's budget, the Task's cap or the month's cap. The tests here put costs of other runs just
under and just over each limit, and run workers side by side to show that the reservation, not
luck, keeps them under it.
"""

import itertools
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from sidekick.api.app import Container
from sidekick.contacts.application.models import CreateContactCommand
from sidekick.shared.errors import ConflictError
from sidekick.shared.types import Actor, new_uuid7
from sidekick.work.application.ai_store import MICROUSD_PER_USD
from sidekick.work.domain.ai_model_port import CallUsage, ModelRequest, ModelResponse
from sidekick.work.domain.ai_runs import (
    AiRunState,
    AiStepRun,
    AiUsage,
    CostSource,
    FailureCategory,
    RunnerKind,
)
from sidekick.work.domain.ai_spec import AiBudgetSpec, AiContextSpec
from sidekick.work.persistence.store import SqlWorkStore
from tests.support.ai_runner import FakeModel, answer, make_runner, runner_container
from tests.support.ai_runner_scenes import (
    SETTLED_COST,
    Scene,
    new_owner,
    probe_request,
    queued_scene,
    reserve_of,
    run_together,
    wait_until,
)
from tests.support.ai_steps import SCOPES, ai_item, approved_plan, key, new_task, plan, spec

pytestmark = pytest.mark.integration

_attempts = itertools.count(100)

TASK_CAP_MICROUSD = 2 * MICROUSD_PER_USD  # the default cap per Task


def _reserve() -> int:
    """What the runner sets aside for the default one-step plan."""

    container, request = probe_request()
    return reserve_of(container, request)


def _usd(microusd: int) -> float:
    return microusd / MICROUSD_PER_USD


def seed(
    container: Container,
    actor: Actor,
    scene: Scene,
    microusd: int,
    *,
    source: CostSource = CostSource.PRICE_TABLE,
    age: timedelta = timedelta(0),
    task_id: UUID | None = None,
    step_id: UUID | None = None,
) -> None:
    """An earlier attempt at the scene's step (or at another) that cost `microusd`."""

    now = datetime.now(UTC) - age
    run = AiStepRun(
        id=new_uuid7(),
        owner_id=actor.user_id,
        task_id=task_id or scene.task_id,
        step_id=step_id or scene.step_id,
        attempt=next(_attempts),
        runner=RunnerKind.SERVER,
        state=AiRunState.FAILED,
        plan_digest="0" * 64,
        created_at=now,
        updated_at=now,
        usage=AiUsage(cost_microusd=microusd, cost_source=source),
        error_category=FailureCategory.OTHER,
    )
    store = SqlWorkStore(container.session_factory, container.telemetry)
    store.transaction(lambda session: store.save_ai_run(session, run))


def _is_refused_by_a_cap(scene: Scene, model: FakeModel) -> bool:
    run = scene.run()
    assert run.usage.reserved_microusd == 0
    assert run.usage.cost_microusd == 0
    refused = run.state is AiRunState.FAILED and run.error_category is FailureCategory.BUDGET
    return refused and model.calls == 0 and not scene.attention()


def _took_the_call(scene: Scene, model: FakeModel) -> bool:
    run = scene.run()
    return (
        run.state is AiRunState.TO_REVIEW
        and model.calls == 1
        and (run.usage.cost_microusd == SETTLED_COST)
    )


# The Task's cap


@pytest.mark.parametrize(("over_by", "runs"), [(0, True), (1, False)], ids=["fits", "one-over"])
def test_a_call_that_would_pass_the_tasks_cap_is_not_made(over_by: int, runs: bool) -> None:
    reserve = _reserve()
    container = runner_container()
    scene = queued_scene(container)  # queued before the other costs exist, so it is let through
    seed(container, scene.actor, scene, TASK_CAP_MICROUSD - reserve + over_by)
    model = FakeModel([answer()])

    make_runner(container, model).run_next("w1")

    assert (_took_the_call(scene, model)) if runs else _is_refused_by_a_cap(scene, model)


def test_the_cap_given_when_the_plan_was_approved_goes_before_the_default() -> None:
    reserve = _reserve()
    own_cap = 500_000
    results: dict[int, bool] = {}
    for over_by in (0, 1):
        container = runner_container()
        actor = new_owner(container)
        items = [ai_item("Look it up", spec(budget=AiBudgetSpec(max_usd=0.4)))]
        drafted = plan(container, actor, items)
        view = container.ai_plans.approve_plan(
            actor,
            drafted.task.id,
            digest=drafted.digest,
            decision="approve",
            task_cap_usd=_usd(own_cap),
            idempotency_key=key(),
        )
        scene = queued_scene(container, actor, view=view)
        # Far under the default cap of 2 USD, but at or just over the cap the owner chose.
        seed(container, actor, scene, own_cap - reserve + over_by)
        model = FakeModel([answer()])

        make_runner(container, model).run_next("w1")

        results[over_by] = _took_the_call(scene, model)
        if over_by:
            assert _is_refused_by_a_cap(scene, model)

    assert results == {0: True, 1: False}


def test_a_higher_cap_chosen_at_approval_lets_a_run_pass_the_default_cap() -> None:
    reserve = _reserve()
    container = runner_container()
    actor = new_owner(container)
    drafted = plan(container, actor, [ai_item("Look it up")])
    view = container.ai_plans.approve_plan(
        actor,
        drafted.task.id,
        digest=drafted.digest,
        decision="approve",
        task_cap_usd=5.0,
        idempotency_key=key(),
    )
    scene = queued_scene(container, actor, view=view)
    seed(container, actor, scene, TASK_CAP_MICROUSD + reserve)  # over the default, under 5 USD
    model = FakeModel([answer()])

    make_runner(container, model).run_next("w1")

    assert _took_the_call(scene, model)


def test_what_an_estimate_from_claude_code_cost_never_counts() -> None:
    container = runner_container()
    scene = queued_scene(container)
    estimate = 50 * TASK_CAP_MICROUSD
    seed(container, scene.actor, scene, estimate, source=CostSource.CLIENT_ESTIMATE)
    model = FakeModel([answer()])

    make_runner(container, model).run_next("w1")

    assert _took_the_call(scene, model)
    usage = container.ai_runs.usage(scene.actor)
    assert usage.client_estimate_microusd == estimate
    assert usage.spent_microusd == SETTLED_COST


# The step's own budget


def test_a_step_whose_budget_cannot_hold_one_call_is_not_queued() -> None:
    reserve = _reserve()
    assert reserve > 10_000
    container = runner_container()
    actor = new_owner(container)
    view = approved_plan(
        container, actor, [ai_item("Look it up", spec(budget=AiBudgetSpec(max_usd=0.01)))]
    )

    with pytest.raises(ConflictError) as raised:
        queued_scene(container, actor, view=view)

    assert raised.value.reason == "ai_budget_reached"


def test_a_step_whose_brief_grew_past_its_budget_while_queued_is_refused_before_the_call() -> None:
    context = AiContextSpec(include_contacts=True)
    reserve = _reserve()
    container = runner_container()
    actor = new_owner(container)
    # Room for exactly the call of the brief as it is now: not for one byte more.
    budget = AiBudgetSpec(max_usd=_usd(reserve))
    items = [ai_item("Look it up", spec(context=context, budget=budget))]
    scene = queued_scene(container, actor, items)
    owner = Actor(actor.user_id, SCOPES | {"contacts:read", "contacts:write"})
    contact = container.contacts.create(owner, CreateContactCommand("C" * 150), key())
    container.contact_relations.link_task(owner, contact.id, scene.task_id, key())
    model = FakeModel([answer()])

    make_runner(container, model).run_next("w1")

    assert _is_refused_by_a_cap(scene, model)


# The month's cap


@pytest.mark.parametrize(("over_by", "runs"), [(0, True), (1, False)], ids=["fits", "one-over"])
def test_a_call_that_would_pass_the_months_cap_is_not_made(over_by: int, runs: bool) -> None:
    reserve = _reserve()
    other_task_cost = 700_000  # more than the Task's own cap below: it must not count there
    month_cap = other_task_cost + reserve - over_by
    container = runner_container(ai_monthly_cap_usd=_usd(month_cap), ai_default_task_cap_usd=0.3)
    actor = new_owner(container)
    items = [ai_item("Look it up", spec(budget=AiBudgetSpec(max_usd=0.25)))]
    scene = queued_scene(container, actor, items)
    other = _another_task(container, actor)
    seed(container, actor, scene, other_task_cost, task_id=other.task_id, step_id=other.step_id)
    # A cost from before this month, on the other task, counts against neither cap.
    seed(
        container,
        actor,
        scene,
        10 * TASK_CAP_MICROUSD,
        age=timedelta(days=70),
        task_id=other.task_id,
        step_id=other.step_id,
    )
    model = FakeModel([answer()])

    make_runner(container, model).run_next("w1")

    assert (_took_the_call(scene, model)) if runs else _is_refused_by_a_cap(scene, model)


def _another_task(container: Container, actor: Actor) -> Scene:
    """A second Task of the owner with one step, for costs that belong to another Task."""

    task = new_task(container, actor, "Another errand")
    step = container.steps.create_step(actor, task.id, title="Other step", idempotency_key=key())
    return Scene(container, actor, task.id, step.id, new_uuid7())


# Workers side by side


class _TwoRuns:
    """The wait the first caller of the model does: until the other run has been refused."""

    def __init__(self, scenes: list[Scene]) -> None:
        self.scenes = scenes

    def refused(self) -> bool:
        return any(scene.run().state is AiRunState.FAILED for scene in self.scenes)

    def __call__(self, _: ModelRequest) -> ModelResponse:
        wait_until(self.refused, seconds=5)
        return answer(usage=CallUsage(input_tokens=100, output_tokens=10))


LAPS = 20


def test_two_workers_cannot_both_reserve_under_a_cap_only_one_call_fits() -> None:
    reserve = _reserve()
    headroom = 1_000  # more than the one call that is made costs in the end
    month_cap = reserve + headroom
    container = runner_container(ai_monthly_cap_usd=_usd(month_cap))

    for _ in range(LAPS):
        actor = new_owner(container)
        scenes = [queued_scene(container, actor), queued_scene(container, actor)]
        model = FakeModel([_TwoRuns(scenes)])

        results = run_together(container, model, ["w1", "w2"], read_delay=0.05)

        runs = [scene.run() for scene in scenes]
        assert model.calls == 1, [run.state for run in runs]
        assert sorted(run.state.value for run in runs) == ["failed", "to_review"]
        refused = next(run for run in runs if run.state is AiRunState.FAILED)
        assert refused.error_category is FailureCategory.BUDGET
        assert refused.usage.cost_microusd == 0 and refused.usage.reserved_microusd == 0
        assert (
            sum(run.usage.cost_microusd + run.usage.reserved_microusd for run in runs) <= month_cap
        )
        assert sorted(results) == [True, True]


def test_two_workers_cannot_take_the_same_queued_run() -> None:
    def slow(_: ModelRequest) -> ModelResponse:
        time.sleep(0.2)
        return answer()

    container = runner_container()

    for _ in range(LAPS):
        scene = queued_scene(container)
        model = FakeModel([slow])

        results = run_together(container, model, ["w1", "w2"])

        assert sorted(results) == [False, True]
        assert model.calls == 1
        run = scene.run()
        assert run.state is AiRunState.TO_REVIEW
        assert run.worker_id in ("w1", "w2")
        assert run.usage.cost_microusd == SETTLED_COST


# The reservation can be seen while the call is under way


def test_the_reservation_counts_as_spent_during_the_call_and_the_real_cost_after() -> None:
    container = runner_container()
    scene = queued_scene(container)
    seen: list[tuple[int, int, int]] = []

    def look_while_called(request: ModelRequest) -> ModelResponse:
        run = scene.run()
        spent = container.ai_runs.usage(scene.actor).spent_microusd
        seen.append((spent, run.usage.reserved_microusd, reserve_of(container, request)))
        return answer()

    model = FakeModel([look_while_called])

    make_runner(container, model).run_next("w1")

    ((spent, reserved, expected),) = seen
    assert spent == reserved == expected > SETTLED_COST
    run = scene.run()
    assert run.usage.reserved_microusd == 0 and run.usage.cost_microusd == SETTLED_COST
    assert container.ai_runs.usage(scene.actor).spent_microusd == SETTLED_COST
