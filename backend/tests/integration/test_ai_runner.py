"""The AI runner against PostgreSQL: a queued step is taken, called once and left for review.

What a run costs and when a spending cap stops it is in `test_ai_runner_spend.py`; the scenes both
use are in `tests/support/ai_runner_scenes.py`.
"""

import dataclasses
from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import SecretStr

from sidekick.api.app import Container
from sidekick.contacts.application.models import CreateContactCommand
from sidekick.lifecycle.domain import RecordKind
from sidekick.shared.types import Actor, TxSession, new_uuid7
from sidekick.work.application.ai_plans import PlanItem
from sidekick.work.application.ai_store import AiPlanView
from sidekick.work.domain.ai_model_port import (
    CallUsage,
    ModelRejected,
    ModelRequest,
    ModelResponse,
    ModelTransient,
    ModelUncertain,
    RejectionKind,
    StopReason,
)
from sidekick.work.domain.ai_outcome import OUTCOME_SCHEMA
from sidekick.work.domain.ai_plan import AiStepStatus
from sidekick.work.domain.ai_runs import (
    AiRunState,
    AiStepRun,
    ChecklistItem,
    CostSource,
    FailureCategory,
)
from sidekick.work.domain.ai_server_brief import SYSTEM_PROMPT, answer_token_limit
from sidekick.work.domain.ai_spec import AiContextSpec, Performer
from sidekick.work.persistence.store import SqlWorkStore
from tests.support.ai_runner import (
    MODEL,
    FakeModel,
    answer,
    make_runner,
    runner_container,
)
from tests.support.ai_runner_scenes import (
    SETTLED_COST,
    Scene,
    expire_lease,
    new_owner,
    play,
    queue,
    queued_scene,
    reserve_of,
)
from tests.support.ai_steps import (
    GOAL,
    SCOPES,
    admin_rows,
    ai_item,
    approve,
    approved_plan,
    key,
    new_task,
    owner_actor,
    plan,
    spec,
)
from tests.support.mcp_logging import (
    _all_logs,  # noqa: F401  # pyright: ignore[reportPrivateUsage, reportUnusedImport]
    _Collector,  # pyright: ignore[reportPrivateUsage]
)

pytestmark = pytest.mark.integration


def _plan_with_actions(container: Container, actor: Actor) -> tuple[AiPlanView, tuple[UUID, UUID]]:
    task = new_task(container, actor)
    step = container.steps.create_step(actor, task.id, title="Prepare", idempotency_key=key())
    first, second = (
        container.steps.create_action(actor, step.id, title=title, idempotency_key=key()).id
        for title in ("Look up hours", "Write summary")
    )
    view = plan(
        container,
        actor,
        [PlanItem(performer=Performer.AI, step_id=step.id, ai_spec=spec())],
        task=task,
    )
    return approve(container, actor, view), (first, second)


# A step that is run


def test_a_queued_step_is_run_once_and_waits_for_the_owner() -> None:
    container = runner_container()
    actor = owner_actor(container)
    view = approved_plan(container, actor)
    queued = queue(container, actor, view)
    assert queued.steps[0].history.latest is not None
    assert queued.steps[0].history.latest.state is AiRunState.QUEUED
    model = FakeModel([answer()])

    assert make_runner(container, model).run_next("worker-1") is True

    after = container.ai_plans.get_plan(actor, view.task.id)
    run = after.steps[0].history.latest
    assert run is not None
    assert run.state is AiRunState.TO_REVIEW
    assert run.result is not None and run.result.text == "The pharmacy opens at nine."
    assert run.usage.cost_microusd == SETTLED_COST
    assert run.usage.reserved_microusd == 0
    assert model.calls == 1


def test_nothing_queued_means_nothing_taken() -> None:
    container = runner_container()
    model = FakeModel([answer()])

    assert make_runner(container, model).run_next("w1") is False
    assert model.calls == 0


def test_a_result_reports_which_actions_it_finished() -> None:
    container = runner_container()
    actor = new_owner(container)
    view, (looked_up, summarised) = _plan_with_actions(container, actor)
    checklist: list[dict[str, object]] = [
        {"action_id": str(looked_up), "done": True},
        {"action_id": str(summarised), "done": False},
    ]

    scene = queued_scene(container, actor, view=view)
    model = FakeModel([answer(checklist=checklist)])
    make_runner(container, model).run_next("w1")

    run = scene.run()
    assert run.state is AiRunState.TO_REVIEW and run.result is not None
    assert run.result.checklist == (
        ChecklistItem(looked_up, True),
        ChecklistItem(summarised, False),
    )
    brief = model.requests[0].messages[0]["content"]
    assert str(looked_up) in brief and str(summarised) in brief


def test_a_question_waits_for_the_owner_to_answer() -> None:
    played = play([answer("question", question="Which pharmacy do you mean?")])

    run = played.run
    assert run.state is AiRunState.NEEDS_INPUT
    assert run.question == "Which pharmacy do you mean?"
    assert run.result is None
    assert run.usage.cost_microusd == SETTLED_COST


@pytest.mark.parametrize(
    ("failure", "category"),
    [
        ("blocked", FailureCategory.BLOCKED),
        ("unclear_goal", FailureCategory.UNCLEAR_GOAL),
        ("budget", FailureCategory.BUDGET),
        ("other", FailureCategory.OTHER),
        ("none", FailureCategory.OTHER),
    ],
)
def test_a_failure_the_model_reports_is_kept_with_its_category(
    failure: str, category: FailureCategory
) -> None:
    played = play([answer("failed", failure=failure)])

    run = played.run
    assert run.state is AiRunState.FAILED
    assert run.error_category is category
    assert run.usage.cost_microusd == SETTLED_COST and run.usage.reserved_microusd == 0


_USAGE = CallUsage(input_tokens=1_000, output_tokens=200)
_BAD_ANSWERS = [
    pytest.param(ModelResponse(StopReason.END_TURN, "this is not json", _USAGE, MODEL), id="text"),
    pytest.param(ModelResponse(StopReason.END_TURN, None, _USAGE, MODEL), id="no-answer"),
    pytest.param(ModelResponse(StopReason.END_TURN, "[1, 2]", _USAGE, MODEL), id="not-an-object"),
    pytest.param(answer(stop_reason=StopReason.OTHER), id="other-stop-reason"),
    pytest.param(answer("dance"), id="unknown-outcome"),
    pytest.param(answer("failed", failure="exploded"), id="unknown-failure"),
    pytest.param(
        answer(checklist=[{"action_id": str(new_uuid7()), "done": True}]), id="unknown-action"
    ),
    pytest.param(answer(checklist=[{"action_id": "nope", "done": True}]), id="action-not-an-id"),
    pytest.param(answer(text="x" * 8_001), id="result-too-long"),
    pytest.param(answer(summary=""), id="empty-summary"),
    pytest.param(answer("question", question="q" * 1_001), id="question-too-long"),
]


@pytest.mark.parametrize("response", _BAD_ANSWERS)
def test_an_answer_that_breaks_the_schema_fails_the_run_but_is_billed(
    response: ModelResponse,
) -> None:
    played = play([response])

    run = played.run
    assert run.state is AiRunState.FAILED
    assert run.error_category is FailureCategory.INVALID_OUTPUT
    assert run.result is None and run.question is None
    assert run.usage.cost_microusd == SETTLED_COST and run.usage.reserved_microusd == 0
    assert played.model.calls == 1


@pytest.mark.parametrize(
    ("stop_reason", "category"),
    [
        (StopReason.REFUSAL, FailureCategory.REFUSED),
        (StopReason.MAX_TOKENS, FailureCategory.BUDGET),
    ],
)
def test_a_refusal_or_a_cut_off_answer_fails_the_run_but_is_billed(
    stop_reason: StopReason, category: FailureCategory
) -> None:
    played = play([answer(stop_reason=stop_reason)])

    run = played.run
    assert run.state is AiRunState.FAILED and run.error_category is category
    assert run.result is None
    assert run.usage.cost_microusd == SETTLED_COST and run.usage.reserved_microusd == 0


@pytest.mark.parametrize(
    ("response", "attention"),
    [
        (answer(), True),
        (answer("question", question="Which one?"), True),
        (answer("failed", failure="blocked"), False),
    ],
    ids=["result", "question", "failure"],
)
def test_the_step_asks_for_attention_when_the_owner_has_something_to_do(
    response: ModelResponse, attention: bool
) -> None:
    played = play([response])

    assert played.scene.attention() is attention


# What a failing model costs


def test_a_rate_limit_is_waited_out_and_only_the_call_that_answered_is_billed() -> None:
    sleeps: list[float] = []

    played = play([ModelTransient(retry_after=3), answer()], sleeps=sleeps)

    run = played.run
    assert run.state is AiRunState.TO_REVIEW
    assert sleeps == [3]
    assert played.model.calls == 2
    assert run.usage.cost_microusd == SETTLED_COST
    assert run.usage.reserved_microusd == 0


def test_a_provider_that_keeps_refusing_ends_the_run_at_no_cost() -> None:
    sleeps: list[float] = []

    played = play([ModelTransient(retry_after=2) for _ in range(3)], sleeps=sleeps)

    run = played.run
    assert run.state is AiRunState.FAILED and run.error_category is FailureCategory.PROVIDER
    assert played.model.calls == 3
    assert sleeps == [2, 2]
    assert run.usage.cost_microusd == 0 and run.usage.reserved_microusd == 0


def test_a_call_that_may_have_been_billed_costs_its_whole_reservation_and_is_not_retried() -> None:
    played = play([ModelUncertain(), answer()])

    run = played.run
    assert run.state is AiRunState.FAILED and run.error_category is FailureCategory.PROVIDER
    assert played.model.calls == 1
    reserve = reserve_of(played.scene.container, played.model.requests[0])
    assert run.usage.cost_microusd == reserve > 0
    assert run.usage.reserved_microusd == 0


def test_a_refused_key_ends_the_run_and_stops_the_worker_taking_more() -> None:
    played = play([ModelRejected(RejectionKind.AUTH), answer()])
    run = played.run
    assert run.state is AiRunState.FAILED and run.error_category is FailureCategory.PROVIDER
    assert run.usage.cost_microusd == 0
    assert played.runner.credentials_rejected is True

    again = played.scene.queue_again()

    assert played.runner.run_next("w1") is False
    assert again.run().state is AiRunState.QUEUED
    assert played.model.calls == 1


def test_a_refused_request_ends_only_that_run() -> None:
    played = play([ModelRejected(RejectionKind.REQUEST), answer()])
    run = played.run
    assert run.state is AiRunState.FAILED and run.error_category is FailureCategory.PROVIDER
    assert run.usage.cost_microusd == 0 and run.usage.reserved_microusd == 0
    assert played.runner.credentials_rejected is False

    again = played.scene.queue_again()

    assert played.runner.run_next("w1") is True
    assert again.run().state is AiRunState.TO_REVIEW


def test_a_worker_told_to_stop_cancels_the_run_instead_of_waiting() -> None:
    container = runner_container()
    scene = queued_scene(container)
    sleeps: list[float] = []
    model = FakeModel([ModelTransient(retry_after=5), answer()])
    runner = make_runner(container, model, sleeps=sleeps, stopping=lambda: True)

    runner.run_next("w1")

    run = scene.run()
    assert run.state is AiRunState.CANCELLED
    assert sleeps == [] and model.calls == 1
    assert run.usage.cost_microusd == 0 and run.usage.reserved_microusd == 0


# The plan or the owner changes while the run waits or is called


def _rename_step(scene: Scene, title: str = "Changed title") -> None:
    step = scene.container.steps.get_step(scene.actor, scene.step_id)
    scene.container.steps.update_step(
        scene.actor, step.id, version=step.version, title=title, idempotency_key=key()
    )


def test_a_plan_changed_before_the_run_is_taken_cancels_it_without_a_call() -> None:
    container = runner_container()
    scene = queued_scene(container)
    _rename_step(scene)
    model = FakeModel([answer()])

    make_runner(container, model).run_next("w1")

    run = scene.run()
    assert run.state is AiRunState.CANCELLED
    assert model.calls == 0
    assert run.usage.cost_microusd == 0 and run.usage.reserved_microusd == 0
    assert not scene.attention()


def test_a_plan_changed_during_the_call_keeps_the_cost_and_drops_the_answer() -> None:
    container = runner_container()
    scene = queued_scene(container)

    def change_the_plan(_: ModelRequest) -> ModelResponse:
        _rename_step(scene)
        return answer()

    model = FakeModel([change_the_plan])

    make_runner(container, model).run_next("w1")

    run = scene.run()
    assert run.state is AiRunState.CANCELLED
    assert run.result is None and run.question is None
    assert run.usage.cost_microusd == SETTLED_COST > 0
    assert run.usage.reserved_microusd == 0
    assert not scene.attention()


def test_the_owner_cancelling_during_the_call_keeps_the_cost_and_drops_the_answer() -> None:
    container = runner_container()
    scene = queued_scene(container)

    def owner_cancels(_: ModelRequest) -> ModelResponse:
        running = scene.run()
        assert running.state is AiRunState.RUNNING and running.usage.reserved_microusd > 0
        container.ai_server_runs.cancel_run(
            scene.actor, scene.run_id, run_version=running.version, idempotency_key=key()
        )
        return answer()

    model = FakeModel([owner_cancels])

    make_runner(container, model).run_next("w1")

    run = scene.run()
    assert run.state is AiRunState.CANCELLED
    assert run.result is None
    assert run.usage.cost_microusd == SETTLED_COST
    assert run.usage.reserved_microusd == 0
    assert model.calls == 1


def test_a_task_erased_during_the_call_ends_the_run_and_keeps_its_reservation_as_cost() -> None:
    container = runner_container()
    scene = queued_scene(container)
    reserved: list[int] = []

    def owner_erases(_: ModelRequest) -> ModelResponse:
        running = scene.run()
        assert running.state is AiRunState.RUNNING and running.usage.reserved_microusd > 0
        reserved.append(running.usage.reserved_microusd)
        task = container.tasks.get(scene.actor, scene.task_id)
        step = container.steps.get_step(scene.actor, scene.step_id)
        for kind, record_id, version in (
            (RecordKind.STEP, step.id, step.version),
            (RecordKind.TASK, task.id, task.version),
        ):
            trashed = container.lifecycle.trash(
                scene.actor, kind, record_id, version=version, idempotency_key=key()
            )
            container.lifecycle.permanently_remove(
                scene.actor, kind, record_id, version=trashed.version, idempotency_key=key()
            )
        return answer()

    model = FakeModel([owner_erases])

    assert make_runner(container, model).run_next("w1") is True

    assert model.calls == 1
    assert admin_rows("SELECT count(*) FROM sidekick.ai_step_runs") == [(0,)]
    assert admin_rows("SELECT cost_microusd FROM sidekick.ai_erased_run_costs") == [(reserved[0],)]


def test_a_task_in_the_trash_before_the_run_is_taken_cancels_it_without_a_call() -> None:
    container = runner_container()
    scene = queued_scene(container)
    task = container.tasks.get(scene.actor, scene.task_id)
    container.lifecycle.trash(
        scene.actor, RecordKind.TASK, task.id, version=task.version, idempotency_key=key()
    )
    model = FakeModel([answer()])

    make_runner(container, model).run_next("w1")

    assert scene.run().state is AiRunState.CANCELLED
    assert model.calls == 0
    assert scene.run().usage.cost_microusd == 0


def test_a_task_completed_before_the_run_is_taken_cancels_it_without_a_call() -> None:
    container = runner_container()
    scene = queued_scene(container)
    task = container.tasks.get(scene.actor, scene.task_id)
    container.tasks.complete(scene.actor, task.id, version=task.version, idempotency_key=key())
    model = FakeModel([answer()])

    make_runner(container, model).run_next("w1")

    assert scene.run().state is AiRunState.CANCELLED
    assert model.calls == 0
    assert scene.run().usage.cost_microusd == 0


# Runs whose worker went silent


def _strand(scene: Scene, reserve: int) -> AiStepRun:
    """Leave the run as a worker that died during a model call would: running, reserved."""

    store = SqlWorkStore(scene.container.session_factory, scene.container.telemetry)

    def move(session: TxSession) -> AiStepRun:
        run = store.get_ai_run(session, scene.actor.user_id, scene.run_id)
        now = datetime.now(UTC)
        claimed = run.claim(
            "dead-worker",
            provider="anthropic",
            model=MODEL,
            cost_source=CostSource.PRICE_TABLE,
            now=now,
        )
        reserved = claimed.reserve(reserve, now=now)
        store.save_ai_run(session, reserved, expected_version=run.version)
        return reserved

    return store.transaction(move)


def test_a_queued_run_nobody_took_lapses_without_costing_an_attempt() -> None:
    container = runner_container()
    scene = queued_scene(container)
    model = FakeModel([answer()])
    runner = make_runner(container, model)
    assert runner.recover_stalled() == 0
    expire_lease(scene.run_id)

    assert runner.recover_stalled() == 1

    run = scene.run()
    assert run.state is AiRunState.CANCELLED
    assert run.usage.cost_microusd == 0 and run.usage.reserved_microusd == 0
    assert scene.view().steps[0].status is AiStepStatus.READY
    assert scene.view().steps[0].history.attempts == 0
    assert model.calls == 0


def test_a_run_whose_worker_died_during_a_call_is_booked_at_its_reservation() -> None:
    container = runner_container()
    scene = queued_scene(container)
    stranded = _strand(scene, reserve=123_456)
    runner = make_runner(container, FakeModel())
    assert runner.recover_stalled() == 0  # its lease has not run out
    expire_lease(scene.run_id)

    assert runner.recover_stalled() == 1

    run = scene.run()
    assert run.state is AiRunState.CANCELLED and run.version > stranded.version
    assert run.usage.cost_microusd == 123_456
    assert run.usage.reserved_microusd == 0
    assert admin_rows(
        "SELECT actor_type FROM sidekick.domain_events "
        "WHERE aggregate_id = :id AND event_type = 'ai.run_abandoned'",
        id=scene.run_id,
    ) == [("worker",)]
    assert runner.recover_stalled() == 0  # booked once


def test_a_cancelled_run_that_kept_a_reservation_is_booked_when_its_lease_runs_out() -> None:
    container = runner_container()
    scene = queued_scene(container)
    stranded = _strand(scene, reserve=77_000)
    container.ai_server_runs.cancel_run(
        scene.actor, scene.run_id, run_version=stranded.version, idempotency_key=key()
    )
    assert scene.run().state is AiRunState.CANCELLED
    assert scene.run().usage.reserved_microusd == 77_000
    runner = make_runner(container, FakeModel())
    assert runner.recover_stalled() == 0
    expire_lease(scene.run_id)

    assert runner.recover_stalled() == 1

    run = scene.run()
    assert run.state is AiRunState.CANCELLED
    assert run.usage.cost_microusd == 77_000 and run.usage.reserved_microusd == 0
    assert runner.recover_stalled() == 0


def test_a_claude_code_run_is_not_the_servers_to_recover() -> None:
    container = runner_container()
    actor = new_owner(container)
    view = approved_plan(container, actor)
    started = container.ai_runs.start_step(actor, view.steps[0].step.id, idempotency_key=key())
    expire_lease(started.run.id)
    runner = make_runner(container, FakeModel())

    assert runner.recover_stalled() == 0

    assert container.ai_runs.get_run(actor, started.run.id).state is AiRunState.RUNNING


# What the model is sent


@pytest.mark.parametrize("include_contacts", [True, False])
def test_the_model_is_sent_names_and_titles_never_contact_details_or_tools(
    include_contacts: bool,
) -> None:
    container = runner_container()
    actor = new_owner(container)
    scopes = Actor(actor.user_id, SCOPES | {"contacts:read", "contacts:write"})
    command = CreateContactCommand(
        "Pia Apotekare",
        email="pia.hemlig@example.org",
        phone="+46 70 555 01 23",
        address="Hemliga gatan 7, 111 22 Stockholm",
        context_note="gate code 4711",
        organization="Hemliga Apoteket AB",
    )
    details = [command.email, command.phone, command.address, command.context_note]
    details.append(command.organization)
    contact = container.contacts.create(scopes, command, key())
    task = new_task(container, actor, "Pharmacy errand")
    container.contact_relations.link_task(scopes, contact.id, task.id, key())
    task = container.tasks.get(actor, task.id)
    items = [ai_item("Look it up", spec(context=AiContextSpec(include_contacts=include_contacts)))]
    view = approve(container, actor, plan(container, actor, items, task=task))
    scene = queued_scene(container, actor, view=view)
    model = FakeModel([answer()])

    make_runner(container, model).run_next("w1")

    assert scene.run().state is AiRunState.TO_REVIEW
    request = model.requests[0]
    brief = request.messages[0]["content"]
    assert "Pharmacy errand" in brief and GOAL in brief and "Look it up" in brief
    assert ("Pia Apotekare" in brief) is include_contacts
    everything = "\n".join(
        [request.system, *(part for m in request.messages for part in m.values())]
    )
    for secret in details:
        assert secret is not None and secret not in everything
    assert "555 01 23" not in everything
    assert "report_ai_step_result" not in everything
    assert request.system == SYSTEM_PROMPT
    assert request.output_schema is OUTCOME_SCHEMA
    assert request.max_tokens == answer_token_limit(
        view.steps[0].step.ai_spec,  # type: ignore[arg-type]
        container.settings.ai_max_output_tokens,
    )
    assert {field.name for field in dataclasses.fields(ModelRequest)} == {
        "system",
        "messages",
        "max_tokens",
        "output_schema",
    }  # nothing in a request can name a tool


# What is kept and logged


SENTINEL_DESCRIPTION = "SENTINEL-DESCRIPTION-7f3a the landlord owes us money"
SENTINEL_TEXT = "SENTINEL-ANSWER-TEXT-91bc the pharmacy opens at nine"
SENTINEL_SUMMARY = "SENTINEL-ANSWER-SUMMARY-44de opens at nine"
SENTINEL_KEY = "sk-ant-SENTINEL-KEY-0d2e5c1f"


def test_a_run_leaves_no_task_text_prompt_answer_or_key_in_logs_or_the_audit_trail(
    all_logs: _Collector,
) -> None:
    container = runner_container(ai_anthropic_api_key=SecretStr(SENTINEL_KEY))
    actor = new_owner(container)
    task = container.tasks.create(
        actor, title="Pharmacy errand", description=SENTINEL_DESCRIPTION, idempotency_key=key()
    )
    view = approve(container, actor, plan(container, actor, [ai_item("Look it up")], task=task))
    scene = queued_scene(container, actor, view=view)
    model = FakeModel([answer(text=SENTINEL_TEXT, summary=SENTINEL_SUMMARY)])

    make_runner(container, model).run_next("w1")

    assert scene.run().state is AiRunState.TO_REVIEW
    assert SENTINEL_DESCRIPTION in model.requests[0].messages[0]["content"]
    rendered = all_logs.rendered()
    assert "ai_model_call" in rendered  # the capture saw the runner's own records
    for hidden in (
        SENTINEL_DESCRIPTION,
        SENTINEL_TEXT,
        SENTINEL_SUMMARY,
        SENTINEL_KEY,
        SYSTEM_PROMPT[:40],
        "# Assignment",
        "Material (data",
        GOAL,
        "Pharmacy errand",
    ):
        assert hidden not in rendered, hidden
    assert all(record.exc_info is None for record in all_logs.records)

    kept = {
        "audit": admin_rows(
            "SELECT to_jsonb(a)::text FROM sidekick.audit_events a "
            "WHERE target_type = 'ai_step_run'"
        ),
        "events": admin_rows(
            "SELECT to_jsonb(e)::text FROM sidekick.domain_events e "
            "WHERE aggregate_type = 'ai_step_run'"
        ),
        "activity": admin_rows(
            "SELECT to_jsonb(a)::text FROM sidekick.activity_entries a "
            "WHERE aggregate_type = 'ai_step_run'"
        ),
    }
    for name, rows in kept.items():
        assert rows, name
        text_of_rows = " ".join(str(row[0]) for row in rows)
        for hidden in (SENTINEL_DESCRIPTION, SENTINEL_TEXT, SENTINEL_SUMMARY, GOAL):
            assert hidden not in text_of_rows, (name, hidden)
    every_row = " ".join(
        str(row[0])
        for sql in (
            "SELECT to_jsonb(t)::text FROM sidekick.audit_events t",
            "SELECT to_jsonb(t)::text FROM sidekick.domain_events t",
            "SELECT to_jsonb(t)::text FROM sidekick.activity_entries t",
        )
        for row in admin_rows(sql)
    )
    assert SENTINEL_TEXT not in every_row and SENTINEL_SUMMARY not in every_row


def test_what_the_worker_does_is_recorded_as_the_worker() -> None:
    played = play([answer()])
    run_id = played.scene.run_id

    events = admin_rows(
        "SELECT event_type, actor_type FROM sidekick.domain_events "
        "WHERE aggregate_type = 'ai_step_run' AND aggregate_id = :id ORDER BY aggregate_version",
        id=run_id,
    )
    activity = admin_rows(
        "SELECT operation, source FROM sidekick.activity_entries "
        "WHERE aggregate_type = 'ai_step_run' AND aggregate_id = :id ORDER BY occurred_at, id",
        id=run_id,
    )

    assert events == [
        ("ai.run_queued", "user"),
        ("ai.run_started", "worker"),
        ("ai.run_reported", "worker"),
    ]
    assert activity == [
        ("run_queued", "user"),
        ("run_started", "worker"),
        ("run_reported", "worker"),
    ]
    audited = admin_rows(
        "SELECT event FROM sidekick.audit_events WHERE target_type = 'ai_step_run' "
        "AND target_id = :id ORDER BY occurred_at, id",
        id=run_id,
    )
    assert audited == [("ai.run_queued",), ("ai.run_started",), ("ai.run_reported",)]
