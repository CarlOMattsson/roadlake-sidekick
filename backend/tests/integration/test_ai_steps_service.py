"""AI Step plans against PostgreSQL: writing a plan, approving it and the rules it holds.

The runs of a plan (start, report, review, isolation, deletion and the audit trail) are in
`test_ai_steps_service_runs.py`; both files share the helpers below.
"""

import pytest

from sidekick.shared.errors import ConflictError, PermissionDeniedError, ValidationError
from sidekick.shared.types import Actor
from sidekick.work.application.ai_plans import PlanItem
from sidekick.work.domain.ai_plan import AiStepStatus, PlanState
from sidekick.work.domain.ai_spec import (
    MAX_PLAN_STEPS,
    AiOutputSpec,
    Performer,
    ResultFormat,
)
from tests.support.ai_steps import (
    ai_item,
    approve,
    approved_plan,
    container_with,
    key,
    new_task,
    owner_actor,
    plan,
    spec,
    step_ids,
    titles,
)

pytestmark = pytest.mark.integration


# Writing the plan


def test_set_plan_marks_the_task_and_orders_new_steps_before_the_others() -> None:
    container = container_with()
    actor = owner_actor(container)
    task = new_task(container, actor)
    existing = container.steps.create_step(actor, task.id, title="Existing", idempotency_key=key())
    wanted = spec(output=AiOutputSpec(format=ResultFormat.MARKDOWN))

    view = plan(
        container,
        actor,
        [ai_item("Research", wanted), PlanItem(performer=Performer.OWNER, title="Collect")],
        task=task,
    )

    assert titles(view) == ["Research", "Collect", "Existing"]
    assert step_ids(view)[2] == existing.id
    assert [item.step.position for item in view.steps] == [0, 1, 2]
    assert view.task.ai_possible_since is not None
    assert view.state is PlanState.DRAFT
    research, collect, _ = (item.step for item in view.steps)
    assert research.performer is Performer.AI and research.ai_spec == wanted
    assert collect.performer is Performer.OWNER and collect.ai_spec is None
    assert view.steps[0].status is AiStepStatus.READY


def test_set_plan_can_reorder_and_change_an_existing_step() -> None:
    container = container_with()
    actor = owner_actor(container)
    task = new_task(container, actor)
    first = container.steps.create_step(actor, task.id, title="First", idempotency_key=key())
    second = container.steps.create_step(actor, task.id, title="Second", idempotency_key=key())

    view = plan(
        container,
        actor,
        [
            PlanItem(performer=Performer.AI, step_id=second.id, ai_spec=spec()),
            PlanItem(performer=Performer.OWNER, step_id=first.id),
        ],
        task=task,
    )

    assert step_ids(view) == [second.id, first.id]
    assert view.steps[0].step.performer is Performer.AI


def test_a_stale_task_version_is_a_conflict() -> None:
    container = container_with()
    actor = owner_actor(container)
    task = new_task(container, actor)
    plan(container, actor, [ai_item("One")], task=task)

    with pytest.raises(ConflictError) as raised:
        plan(container, actor, [ai_item("Two")], task=task)

    assert raised.value.reason == "stale_version"


@pytest.mark.parametrize(
    "items",
    [
        pytest.param([PlanItem(performer=Performer.OWNER, title="By hand")], id="no-ai-step"),
        pytest.param([ai_item(f"Step {n}") for n in range(MAX_PLAN_STEPS + 1)], id="too-many"),
        pytest.param([PlanItem(performer=Performer.AI, title="No spec")], id="ai-without-spec"),
        pytest.param([], id="empty"),
    ],
)
def test_a_plan_outside_the_rules_is_refused_and_writes_nothing(items: list[PlanItem]) -> None:
    container = container_with()
    actor = owner_actor(container)
    task = new_task(container, actor)

    with pytest.raises(ValidationError):
        plan(container, actor, items, task=task)

    view = container.ai_plans.get_plan(actor, task.id)
    assert view.task.ai_possible_since is None
    assert view.state is PlanState.NONE
    assert not view.steps


def test_an_owner_step_cannot_carry_a_spec() -> None:
    container = container_with()
    actor = owner_actor(container)
    item = PlanItem(performer=Performer.OWNER, title="By hand", ai_spec=spec())

    with pytest.raises(ValidationError):
        plan(container, actor, [ai_item("Real one"), item])


# Approving the plan


def test_approving_the_digest_the_owner_saw_approves_the_plan() -> None:
    container = container_with()
    actor = owner_actor(container)
    drafted = plan(container, actor, [ai_item("Look it up")])

    approved = approve(container, actor, drafted)

    assert approved.state is PlanState.APPROVED
    assert approved.digest == drafted.digest
    assert approved.task.ai_plan_digest == drafted.digest
    assert approved.task.ai_plan_approved_at is not None


def test_a_wrong_digest_is_refused() -> None:
    container = container_with()
    actor = owner_actor(container)
    drafted = plan(container, actor, [ai_item("Look it up")])

    with pytest.raises(ConflictError) as raised:
        container.ai_plans.approve_plan(
            actor, drafted.task.id, digest="0" * 64, decision="approve", idempotency_key=key()
        )

    assert raised.value.reason == "plan_changed"
    assert container.ai_plans.get_plan(actor, drafted.task.id).state is PlanState.DRAFT


def test_an_old_digest_is_refused_after_the_plan_changed() -> None:
    container = container_with()
    actor = owner_actor(container)
    drafted = plan(container, actor, [ai_item("Look it up")])
    step = drafted.steps[0].step
    container.steps.update_step(
        actor, step.id, version=step.version, title="Newer", idempotency_key=key()
    )

    with pytest.raises(ConflictError) as raised:
        approve(container, actor, drafted)

    assert raised.value.reason == "plan_changed"
    assert container.ai_plans.get_plan(actor, drafted.task.id).state is PlanState.DRAFT


def test_a_draft_plan_can_be_written_again() -> None:
    container = container_with()
    actor = owner_actor(container)
    drafted = plan(container, actor, [ai_item("Look it up")])

    again = container.ai_plans.set_plan(
        actor,
        drafted.task.id,
        task_version=drafted.task.version,
        items=[PlanItem(performer=Performer.AI, step_id=drafted.steps[0].step.id, title="Newer")],
        idempotency_key=key(),
    )

    assert again.steps[0].step.title == "Newer"


def test_withdrawing_clears_the_approval() -> None:
    container = container_with()
    actor = owner_actor(container)
    approved = approved_plan(container, actor)

    withdrawn = container.ai_plans.approve_plan(
        actor, approved.task.id, digest=approved.digest, decision="withdraw", idempotency_key=key()
    )

    assert withdrawn.state is PlanState.DRAFT
    assert withdrawn.task.ai_plan_digest is None
    assert withdrawn.task.ai_plan_approved_at is None


def test_writing_the_plan_again_takes_the_approval_back() -> None:
    container = container_with()
    actor = owner_actor(container)
    approved = approved_plan(container, actor)

    again = container.ai_plans.set_plan(
        actor,
        approved.task.id,
        task_version=approved.task.version,
        items=[PlanItem(performer=Performer.AI, step_id=approved.steps[0].step.id)],
        idempotency_key=key(),
    )

    assert again.state is PlanState.DRAFT
    assert again.task.ai_plan_digest is None


def test_a_step_edited_after_approval_changes_the_plan_and_stops_a_start() -> None:
    container = container_with()
    actor = owner_actor(container)
    approved = approved_plan(container, actor)
    step = approved.steps[0].step

    container.steps.update_step(
        actor, step.id, version=step.version, title="Something else", idempotency_key=key()
    )

    after = container.ai_plans.get_plan(actor, approved.task.id)
    assert after.state is PlanState.CHANGED_SINCE_APPROVAL
    with pytest.raises(ConflictError) as raised:
        container.ai_runs.start_step(actor, step.id, idempotency_key=key())
    assert raised.value.reason == "plan_changed"


def test_a_task_cap_below_a_step_budget_is_refused() -> None:
    container = container_with()
    actor = owner_actor(container)
    drafted = plan(container, actor, [ai_item("Costly", spec(budget={"max_usd": 1.5}))])

    with pytest.raises(ValidationError):
        container.ai_plans.approve_plan(
            actor,
            drafted.task.id,
            digest=drafted.digest,
            decision="approve",
            task_cap_usd=1.0,
            idempotency_key=key(),
        )


def test_approving_the_same_key_twice_changes_nothing_the_second_time() -> None:
    container = container_with()
    actor = owner_actor(container)
    drafted = plan(container, actor, [ai_item("Look it up")])
    request = {"digest": drafted.digest, "decision": "approve", "idempotency_key": key()}

    first = container.ai_plans.approve_plan(actor, drafted.task.id, **request)  # type: ignore[arg-type]
    second = container.ai_plans.approve_plan(actor, drafted.task.id, **request)  # type: ignore[arg-type]

    assert first.task.version == second.task.version
    assert second.state is PlanState.APPROVED


# Scopes


def test_the_plan_needs_the_task_scopes() -> None:
    container = container_with()
    actor = owner_actor(container)
    drafted = plan(container, actor, [ai_item("Look it up")])
    reader = Actor(actor.user_id, frozenset({"tasks:read", "ai:run"}))
    blind = Actor(actor.user_id, frozenset({"ai:run"}))

    with pytest.raises(PermissionDeniedError):
        plan(container, reader, [ai_item("Other")], task=drafted.task)
    with pytest.raises(PermissionDeniedError):
        approve(container, reader, drafted)
    with pytest.raises(PermissionDeniedError):
        container.ai_plans.get_plan(blind, drafted.task.id)
    assert container.ai_plans.get_plan(reader, drafted.task.id).state is PlanState.DRAFT
