"""The runs of AI Steps against PostgreSQL: start, report, review and what surrounds them.

The plan itself is in `test_ai_steps_service.py`, whose helpers this file shares.
"""

import os
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from typing import Literal
from uuid import UUID

import pytest
from sqlalchemy import text

from sidekick.api.app import Container
from sidekick.lifecycle.application.empty_trash import empty_trash
from sidekick.lifecycle.domain import RecordKind
from sidekick.shared.errors import (
    ConflictError,
    IdempotencyKeyReusedError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from sidekick.shared.types import Actor, TxSession, new_uuid7
from sidekick.tasks.domain import TaskStatus
from sidekick.work.application import ai_runs_service
from sidekick.work.application.ai_plans import PlanItem
from sidekick.work.application.ai_store import AiPlanView, StartedAiStep
from sidekick.work.domain.ai_plan import AiStepStatus, PlanState
from sidekick.work.domain.ai_runs import (
    AiRunResult,
    AiRunState,
    AiStepRun,
    AiUsage,
    ChecklistItem,
    FailureCategory,
)
from sidekick.work.domain.ai_spec import (
    AiOutputSpec,
    AiStepSpecV1,
    Performer,
    ResultFormat,
    RunnerPreference,
)
from tests.db import _cleanup_factory_for
from tests.support.ai_steps import (
    GOAL,
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
    step_ids,
)

pytestmark = pytest.mark.integration

Decision = Literal["accept", "redo", "reject", "answer"]


def start(container: Container, actor: Actor, step_id: UUID, **kw: str) -> StartedAiStep:
    return container.ai_runs.start_step(actor, step_id, idempotency_key=key(), **kw)


def finding(**changes: object) -> AiRunResult:
    values: dict[str, object] = {
        "format": ResultFormat.TEXT,
        "text": "Open nine to six on weekdays.",
        "summary": "Opening hours found",
    }
    return AiRunResult(**{**values, **changes})  # type: ignore[arg-type]


def report(
    container: Container, actor: Actor, run: AiStepRun, outcome: str = "result", **kw: object
) -> AiStepRun:
    kw.setdefault("idempotency_key", key())
    kw.setdefault("usage", AiUsage())
    if outcome == "result":
        kw.setdefault("result", finding())
    return container.ai_runs.report(
        actor,
        run.id,
        run_version=run.version,
        outcome=outcome,
        **kw,  # type: ignore[arg-type]
    )


def review(
    container: Container,
    actor: Actor,
    run: AiStepRun,
    decision: Decision,
    comment: str | None = None,
    **kw: str,
) -> AiStepRun:
    return container.ai_runs.review(
        actor,
        run.id,
        run_version=run.version,
        decision=decision,
        comment=comment,
        idempotency_key=kw.pop("idempotency_key", key()),
        **kw,
    )


def started_plan(
    container: Container, actor: Actor, count: int = 1
) -> tuple[AiPlanView, StartedAiStep]:
    """An approved plan of `count` AI steps and the first one started."""

    view = approved_plan(container, actor, [ai_item(f"Step {n}") for n in range(count)])
    return view, start(container, actor, view.steps[0].step.id)


def status_of(container: Container, actor: Actor, view: AiPlanView, index: int = 0) -> object:
    return container.ai_plans.get_plan(actor, view.task.id).steps[index].status


# Start


def test_start_needs_an_approved_plan() -> None:
    container = container_with()
    actor = owner_actor(container)
    drafted = plan(container, actor, [ai_item("Look it up")])

    with pytest.raises(ConflictError) as raised:
        start(container, actor, drafted.steps[0].step.id)

    assert raised.value.reason == "plan_not_approved"


def test_start_is_refused_while_an_earlier_step_is_open() -> None:
    container = container_with()
    actor = owner_actor(container)
    view = approved_plan(container, actor, [ai_item("First"), ai_item("Second")])

    with pytest.raises(ConflictError) as raised:
        start(container, actor, view.steps[1].step.id)

    assert raised.value.reason == "step_not_ready"
    assert view.steps[1].status is AiStepStatus.WAITING


def test_start_gives_a_brief_and_a_running_run() -> None:
    container = container_with()
    actor = owner_actor(container)

    view, started = started_plan(container, actor)

    assert started.run.state is AiRunState.RUNNING
    assert started.run.attempt == 1
    assert started.run.plan_digest == view.digest
    assert str(started.run.id) in started.brief
    assert GOAL in started.brief
    assert started.budget_microusd == 1_000_000
    assert status_of(container, actor, view) is AiStepStatus.RUNNING


def test_a_second_start_while_the_run_is_active_is_refused() -> None:
    container = container_with()
    actor = owner_actor(container)
    view, started = started_plan(container, actor)

    with pytest.raises(ConflictError) as raised:
        start(container, actor, started.step.id)

    assert raised.value.reason == "step_not_ready"
    assert container.ai_plans.get_plan(actor, view.task.id).steps[0].history.attempts == 1


def test_the_same_key_starts_one_run() -> None:
    container = container_with()
    actor = owner_actor(container)
    view = approved_plan(container, actor)
    step_id = view.steps[0].step.id

    first = container.ai_runs.start_step(actor, step_id, idempotency_key="start-once")
    second = container.ai_runs.start_step(actor, step_id, idempotency_key="start-once")

    assert second.run.id == first.run.id
    assert admin_rows("SELECT count(*) FROM sidekick.ai_step_runs") == [(1,)]


def test_the_daily_limit_of_starts_is_enforced() -> None:
    container = container_with(ai_claude_code_starts_per_day=1)
    actor = owner_actor(container)
    view = approved_plan(container, actor, [ai_item("First"), ai_item("Second")])
    first = start(container, actor, view.steps[0].step.id)
    done = review(container, actor, report(container, actor, first.run), "accept")
    assert done.state is AiRunState.ACCEPTED

    with pytest.raises(ConflictError) as raised:
        start(container, actor, view.steps[1].step.id)

    assert raised.value.reason == "ai_limit_reached"


def test_a_step_for_the_server_runner_is_not_started_by_claude_code() -> None:
    container = container_with()
    actor = owner_actor(container)
    view = approved_plan(
        container, actor, [ai_item("Server only", spec(runner=RunnerPreference.SERVER))]
    )

    with pytest.raises(ValidationError):
        start(container, actor, view.steps[0].step.id)


def test_a_run_whose_lease_ran_out_is_replaced_by_the_next_attempt() -> None:
    container = container_with()
    actor = owner_actor(container)
    view, first = started_plan(container, actor)
    admin = _cleanup_factory_for(os.environ["SIDEKICK_TEST_ADMIN_DATABASE_URL"])
    with admin.begin() as session:
        session.execute(
            text("UPDATE sidekick.ai_step_runs SET lease_until = now() - interval '1 minute'")
        )

    assert status_of(container, actor, view) is AiStepStatus.READY
    second = start(container, actor, first.step.id)

    assert second.run.attempt == 2
    assert container.ai_runs.get_run(actor, first.run.id).state is AiRunState.CANCELLED


# Report


def test_a_result_waits_for_review_and_asks_for_attention() -> None:
    container = container_with()
    actor = owner_actor(container)
    view, started = started_plan(container, actor)

    run = report(container, actor, started.run)

    assert run.state is AiRunState.TO_REVIEW
    assert run.result is not None and run.result.summary == "Opening hours found"
    assert container.steps.get_step(actor, started.step.id).attention_requested
    assert status_of(container, actor, view) is AiStepStatus.TO_REVIEW


def test_a_result_in_another_format_than_the_step_asked_for_is_refused() -> None:
    container = container_with()
    actor = owner_actor(container)
    view = approved_plan(
        container,
        actor,
        [ai_item("Table", spec(output=AiOutputSpec(format=ResultFormat.TABLE)))],
    )
    started = start(container, actor, view.steps[0].step.id)

    with pytest.raises(ValidationError):
        report(container, actor, started.run)

    assert container.ai_runs.get_run(actor, started.run.id).state is AiRunState.RUNNING


def test_a_result_longer_than_the_step_allows_is_refused() -> None:
    container = container_with()
    actor = owner_actor(container)
    view = approved_plan(
        container, actor, [ai_item("Short", spec(output=AiOutputSpec(max_chars=10)))]
    )
    started = start(container, actor, view.steps[0].step.id)

    with pytest.raises(ValidationError):
        report(container, actor, started.run)


def test_a_checklist_naming_a_foreign_action_is_refused() -> None:
    container = container_with()
    actor = owner_actor(container)
    _, started = started_plan(container, actor)
    stray = finding(checklist=(ChecklistItem(new_uuid7(), True),))

    with pytest.raises(ValidationError):
        report(container, actor, started.run, result=stray)


def test_a_report_without_usage_counts_as_no_usage() -> None:
    container = container_with()
    actor = owner_actor(container)
    _, started = started_plan(container, actor)

    run = container.ai_runs.report(
        actor,
        started.run.id,
        run_version=started.run.version,
        outcome="result",
        result=finding(),
        idempotency_key=key(),
    )

    assert run.usage == AiUsage()


def test_a_question_makes_the_run_need_input() -> None:
    container = container_with()
    actor = owner_actor(container)
    view, started = started_plan(container, actor)

    run = report(container, actor, started.run, "question", question="Which pharmacy?")

    assert run.state is AiRunState.NEEDS_INPUT
    assert run.question == "Which pharmacy?"
    assert container.steps.get_step(actor, started.step.id).attention_requested
    assert status_of(container, actor, view) is AiStepStatus.NEEDS_INPUT


def test_a_failure_keeps_its_category() -> None:
    container = container_with()
    actor = owner_actor(container)
    view, started = started_plan(container, actor)

    run = report(container, actor, started.run, "failed", failure=FailureCategory.BLOCKED)

    assert run.state is AiRunState.FAILED
    assert run.error_category is FailureCategory.BLOCKED
    assert status_of(container, actor, view) is AiStepStatus.FAILED


def test_a_report_with_an_old_run_version_is_a_conflict() -> None:
    container = container_with()
    actor = owner_actor(container)
    _, started = started_plan(container, actor)
    report(container, actor, started.run)

    with pytest.raises(ConflictError) as raised:
        report(container, actor, started.run, "question", question="Too late?")

    assert raised.value.reason == "stale_version"


def test_the_same_report_again_is_a_replay_without_a_second_event() -> None:
    container = container_with()
    actor = owner_actor(container)
    _, started = started_plan(container, actor)

    first = report(container, actor, started.run, idempotency_key="report-once")
    second = report(container, actor, started.run, idempotency_key="report-once")

    assert second.id == first.id and second.version == first.version
    events = admin_rows(
        "SELECT count(*) FROM sidekick.audit_events WHERE event = 'ai.run_reported'"
    )
    assert events == [(1,)]


def test_the_same_key_with_another_report_is_a_conflict_and_not_a_replay() -> None:
    container = container_with()
    actor = owner_actor(container)
    _, started = started_plan(container, actor)
    report(container, actor, started.run, idempotency_key="report-key")

    with pytest.raises(IdempotencyKeyReusedError):
        report(
            container,
            actor,
            started.run,
            result=finding(text="Another answer entirely."),
            idempotency_key="report-key",
        )
    with pytest.raises(IdempotencyKeyReusedError):
        report(
            container,
            actor,
            started.run,
            usage=AiUsage(input_tokens=5),
            idempotency_key="report-key",
        )
    with pytest.raises(IdempotencyKeyReusedError):
        report(
            container, actor, started.run, "question", question="Why?", idempotency_key="report-key"
        )


# Review


def _plan_with_actions(container: Container, actor: Actor) -> tuple[AiPlanView, list[UUID]]:
    task = new_task(container, actor)
    step = container.steps.create_step(actor, task.id, title="Prepare", idempotency_key=key())
    actions = [
        container.steps.create_action(actor, step.id, title=title, idempotency_key=key()).id
        for title in ("Look up hours", "Write summary")
    ]
    view = plan(
        container,
        actor,
        [PlanItem(performer=Performer.AI, step_id=step.id, ai_spec=spec())],
        task=task,
    )
    return approve(container, actor, view), actions


def test_accept_completes_the_step_and_ticks_the_actions_the_result_reported_done() -> None:
    container = container_with()
    actor = owner_actor(container)
    view, (looked_up, summarised) = _plan_with_actions(container, actor)
    started = start(container, actor, view.steps[0].step.id)
    checklist = (ChecklistItem(looked_up, True), ChecklistItem(summarised, False))
    reported = report(container, actor, started.run, result=finding(checklist=checklist))

    accepted = review(container, actor, reported, "accept")

    assert accepted.state is AiRunState.ACCEPTED
    step = container.steps.get_step(actor, started.step.id)
    assert step.status is TaskStatus.COMPLETED and not step.attention_requested
    assert container.steps.get_action(actor, looked_up).status.value == "completed"
    assert container.steps.get_action(actor, summarised).status.value == "open"
    assert status_of(container, actor, view) is AiStepStatus.DONE


def test_redo_allows_a_new_attempt_that_carries_the_comment() -> None:
    container = container_with()
    actor = owner_actor(container)
    view, started = started_plan(container, actor)
    redo = review(container, actor, report(container, actor, started.run), "redo", "Shorter please")

    assert redo.state is AiRunState.REDO
    assert status_of(container, actor, view) is AiStepStatus.READY
    second = start(container, actor, started.step.id)
    assert second.run.attempt == 2


def test_the_next_attempt_after_a_redo_carries_the_comment() -> None:
    container = container_with()
    actor = owner_actor(container)
    _, started = started_plan(container, actor)
    review(container, actor, report(container, actor, started.run), "redo", "Shorter please")

    assert "Shorter please" in start(container, actor, started.step.id).brief


def test_redo_stops_at_the_most_attempts_a_step_may_have() -> None:
    container = container_with()
    actor = owner_actor(container)
    view = approved_plan(container, actor)
    step_id = view.steps[0].step.id
    for _ in range(3):
        started = start(container, actor, step_id)
        review(container, actor, report(container, actor, started.run), "redo")

    assert status_of(container, actor, view) is AiStepStatus.EXHAUSTED
    with pytest.raises(ConflictError) as raised:
        start(container, actor, step_id)
    assert raised.value.reason == "ai_limit_reached"


def test_reject_leaves_the_step_to_the_owner() -> None:
    container = container_with()
    actor = owner_actor(container)
    view, started = started_plan(container, actor)

    rejected = review(container, actor, report(container, actor, started.run), "reject")

    assert rejected.state is AiRunState.REJECTED
    assert status_of(container, actor, view) is AiStepStatus.STOPPED
    assert container.steps.get_step(actor, started.step.id).status is not TaskStatus.COMPLETED
    with pytest.raises(ConflictError):
        start(container, actor, started.step.id)


def test_an_answer_is_kept_and_allows_the_next_attempt() -> None:
    container = container_with()
    actor = owner_actor(container)
    _, started = started_plan(container, actor)
    asked = report(container, actor, started.run, "question", question="Which pharmacy?")

    answered = review(container, actor, asked, "answer", "The one on Main Street")

    assert answered.state is AiRunState.ANSWERED
    assert answered.answer == "The one on Main Street"
    second = start(container, actor, started.step.id)
    assert second.run.attempt == 2


def test_the_next_attempt_after_an_answer_carries_it() -> None:
    container = container_with()
    actor = owner_actor(container)
    _, started = started_plan(container, actor)
    asked = report(container, actor, started.run, "question", question="Which pharmacy?")
    review(container, actor, asked, "answer", "The one on Main Street")

    assert "The one on Main Street" in start(container, actor, started.step.id).brief


def test_an_answer_needs_text_and_a_review_needs_the_right_state() -> None:
    container = container_with()
    actor = owner_actor(container)
    _, started = started_plan(container, actor)
    asked = report(container, actor, started.run, "question", question="Which pharmacy?")

    with pytest.raises(ValidationError):
        review(container, actor, asked, "answer")
    with pytest.raises(ConflictError) as raised:
        review(container, actor, asked, "accept")
    assert raised.value.reason == "run_not_open"


def test_review_with_an_old_run_version_is_a_conflict() -> None:
    container = container_with()
    actor = owner_actor(container)
    _, started = started_plan(container, actor)
    report(container, actor, started.run)

    with pytest.raises(ConflictError) as raised:
        review(container, actor, started.run, "accept")  # the version before the report

    assert raised.value.reason == "stale_version"


# Scopes


def test_the_run_scope_and_the_write_scope_are_separate_powers() -> None:
    container = container_with()
    actor = owner_actor(container)
    view, started = started_plan(container, actor)
    reported = report(container, actor, started.run)
    runner = Actor(actor.user_id, frozenset({"tasks:read", "ai:run"}))
    owner_only = Actor(actor.user_id, frozenset({"tasks:read", "tasks:write"}))

    with pytest.raises(PermissionDeniedError):
        review(container, runner, reported, "accept")
    with pytest.raises(PermissionDeniedError):
        approve(container, runner, view)
    with pytest.raises(PermissionDeniedError):
        start(container, owner_only, started.step.id)
    with pytest.raises(PermissionDeniedError):
        report(container, owner_only, started.run)
    assert container.ai_runs.get_run(runner, started.run.id).state is AiRunState.TO_REVIEW


# Accepting needs the plan the run followed


def _to_review(container: Container, actor: Actor) -> tuple[AiPlanView, AiStepRun]:
    view, started = started_plan(container, actor)
    return view, report(container, actor, started.run)


def _rename_step(container: Container, actor: Actor, view: AiPlanView) -> None:
    step = container.ai_plans.get_plan(actor, view.task.id).steps[0].step
    container.steps.update_step(
        actor, step.id, version=step.version, title="Changed title", idempotency_key=key()
    )


def test_accept_is_refused_when_the_plan_changed_since_the_run_started() -> None:
    container = container_with()
    actor = owner_actor(container)
    view, reported = _to_review(container, actor)
    _rename_step(container, actor, view)

    with pytest.raises(ConflictError) as raised:
        review(container, actor, reported, "accept")

    assert raised.value.reason == "plan_changed"
    assert container.ai_runs.get_run(actor, reported.id).state is AiRunState.TO_REVIEW
    assert status_of(container, actor, view) is not AiStepStatus.DONE


def test_accept_is_refused_when_the_plan_was_approved_again_with_another_digest() -> None:
    container = container_with()
    actor = owner_actor(container)
    view, reported = _to_review(container, actor)
    _rename_step(container, actor, view)
    approve(container, actor, container.ai_plans.get_plan(actor, view.task.id))

    with pytest.raises(ConflictError) as raised:
        review(container, actor, reported, "accept")

    assert raised.value.reason == "plan_changed"


def test_accept_is_refused_while_the_approval_is_withdrawn_and_works_when_it_returns() -> None:
    container = container_with()
    actor = owner_actor(container)
    view, reported = _to_review(container, actor)
    container.ai_plans.approve_plan(
        actor, view.task.id, digest=view.digest, decision="withdraw", idempotency_key=key()
    )

    with pytest.raises(ConflictError) as raised:
        review(container, actor, reported, "accept")
    assert raised.value.reason == "plan_not_approved"

    approve(container, actor, container.ai_plans.get_plan(actor, view.task.id))
    assert review(container, actor, reported, "accept").state is AiRunState.ACCEPTED


@pytest.mark.parametrize("decision", ["redo", "reject"])
def test_redo_and_reject_still_work_after_the_plan_changed(decision: Decision) -> None:
    container = container_with()
    actor = owner_actor(container)
    view, reported = _to_review(container, actor)
    _rename_step(container, actor, view)

    decided = review(container, actor, reported, decision, "Not like this")

    assert decided.state in (AiRunState.REDO, AiRunState.REJECTED)


def test_an_answer_still_works_after_the_plan_changed() -> None:
    container = container_with()
    actor = owner_actor(container)
    view, started = started_plan(container, actor)
    asked = report(container, actor, started.run, "question", question="Which one?")
    _rename_step(container, actor, view)

    assert review(container, actor, asked, "answer", "The first").state is AiRunState.ANSWERED


# Owners are isolated


def test_another_owners_records_are_not_found_and_stay_untouched() -> None:
    container = container_with()
    actor = owner_actor(container)
    other = Actor(container.auth.provision_user("ai-other", "Other"), SCOPES)
    view, started = started_plan(container, actor)
    reported = report(container, actor, started.run)
    task_id, step_id = view.task.id, started.step.id
    other_task = new_task(container, other, "Theirs")
    attempts = {
        "get_plan": lambda: container.ai_plans.get_plan(other, task_id),
        "set_plan": lambda: plan(container, other, [ai_item("Mine now")], task=view.task),
        "approve_plan": lambda: approve(container, other, view),
        "start_step": lambda: start(container, other, step_id),
        "report": lambda: report(container, other, reported, "question", question="Why?"),
        "review": lambda: review(container, other, reported, "accept"),
        "get_run": lambda: container.ai_runs.get_run(other, reported.id),
    }

    for attempt in attempts.values():
        with pytest.raises(NotFoundError):
            attempt()

    after = container.ai_plans.get_plan(actor, task_id)
    assert after.digest == view.digest
    assert after.task.version == view.task.version
    assert step_ids(after) == step_ids(view)
    assert container.ai_runs.get_run(actor, reported.id) == reported
    assert container.tasks.get(other, other_task.id).version == other_task.version


# Deleting the task


def test_deleting_the_task_for_good_removes_its_runs_through_the_foreign_keys() -> None:
    container = container_with()
    actor = owner_actor(container)
    view, started = started_plan(container, actor)
    report(container, actor, started.run)
    step = container.steps.get_step(actor, started.step.id)
    task = container.tasks.get(actor, view.task.id)
    lifecycle = container.lifecycle
    lifecycle.trash(actor, RecordKind.STEP, step.id, version=step.version, idempotency_key=key())
    lifecycle.trash(actor, RecordKind.TASK, task.id, version=task.version, idempotency_key=key())
    assert admin_rows("SELECT count(*) FROM sidekick.ai_step_runs") == [(1,)]

    swept = empty_trash(lifecycle, remove=True)

    assert swept.removed[RecordKind.TASK] == 1 and not swept.kept
    assert admin_rows("SELECT count(*) FROM sidekick.ai_step_runs") == [(0,)]


# The lock comes before the reads

WAIT_SECONDS = 10


def _wait_for_a_blocked_session() -> None:
    """Wait until some session waits on a lock, so the test knows the start reached the lock."""

    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        waiting = admin_rows(
            "SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock' "
            "AND datname = current_database()"
        )
        if waiting != [(0,)]:
            return
        time.sleep(0.02)
    raise AssertionError("no start waited for the Task lock")


def test_a_withdrawal_that_commits_while_a_start_waits_for_the_lock_is_seen_by_the_start() -> None:
    container = container_with()
    actor = owner_actor(container)
    view = approved_plan(container, actor)
    store = container.ai_runs.store

    with ThreadPoolExecutor(max_workers=1) as pool:

        def withdraw_and_let_a_start_wait(session: TxSession) -> Future[StartedAiStep]:
            store.lock_step_order(session, actor.user_id, view.task.id)
            task = store.get_task(session, actor.user_id, view.task.id)
            withdrawn = replace(
                task, ai_plan_digest=None, ai_plan_approved_at=None, version=task.version + 1
            )
            store.save_task(session, withdrawn, expected_version=task.version)
            waiting = pool.submit(
                container.ai_runs.start_step,
                actor,
                view.steps[0].step.id,
                idempotency_key=key(),
            )
            _wait_for_a_blocked_session()
            return waiting

        waiting = store.transaction(withdraw_and_let_a_start_wait)
        with pytest.raises(ConflictError) as raised:
            waiting.result(timeout=WAIT_SECONDS)

    assert raised.value.reason == "plan_not_approved"
    assert admin_rows("SELECT count(*) FROM sidekick.ai_step_runs") == [(0,)]


def test_two_starts_at_once_with_the_same_key_make_one_run() -> None:
    container = container_with()
    actor = owner_actor(container)
    step_id = approved_plan(container, actor).steps[0].step.id

    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = [
            pool.submit(container.ai_runs.start_step, actor, step_id, idempotency_key="same-key")
            for _ in range(2)
        ]
        runs = [attempt.result(timeout=WAIT_SECONDS).run.id for attempt in attempts]

    assert runs[0] == runs[1]
    assert admin_rows("SELECT count(*) FROM sidekick.ai_step_runs") == [(1,)]


def test_two_starts_at_once_with_different_keys_make_one_run_and_refuse_the_other() -> None:
    container = container_with()
    actor = owner_actor(container)
    step_id = approved_plan(container, actor).steps[0].step.id

    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = [
            pool.submit(container.ai_runs.start_step, actor, step_id, idempotency_key=key())
            for _ in range(2)
        ]
        outcomes = [attempt.exception(timeout=WAIT_SECONDS) for attempt in attempts]

    refused = [outcome for outcome in outcomes if outcome is not None]
    assert len(refused) == 1 and isinstance(refused[0], ConflictError)
    assert admin_rows("SELECT count(*) FROM sidekick.ai_step_runs") == [(1,)]


# Listing reaches every Task


def test_the_list_pages_through_more_tasks_than_one_batch_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ai_runs_service, "TASK_BATCH", 2)
    container = container_with()
    actor = owner_actor(container)
    three_steps = approved_plan(container, actor, [ai_item(f"Wide {n}") for n in range(3)])
    singles = [approved_plan(container, actor, [ai_item(f"Single {n}")]) for n in range(4)]
    expected = {item.step.id for item in three_steps.steps} | {
        view.steps[0].step.id for view in singles
    }

    seen: list[UUID] = []
    cursor: str | None = None
    while True:
        page = container.ai_runs.list_steps(actor, limit=2, cursor=cursor)
        seen.extend(entry.step.id for entry in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break

    assert len(seen) == len(set(seen)) == len(expected)
    assert set(seen) == expected


# Audit trail


def test_every_write_leaves_one_content_free_audit_event_with_its_correlation_id() -> None:
    container = container_with()
    actor = owner_actor(container)
    secrets = [
        "Secret task title",
        "Secret step title",
        "Secret goal of the step",
        "Secret result text",
        "Secret result summary",
        "Secret question text",
        "Secret answer text",
    ]
    task = new_task(container, actor, secrets[0])
    items = [
        ai_item(secrets[1], AiStepSpecV1(goal=secrets[2])),
        ai_item("Second", AiStepSpecV1(goal=secrets[2])),
    ]
    written: list[tuple[str, str]] = []

    def note(correlation_id: str, event: str) -> str:
        written.append((correlation_id, event))
        return correlation_id

    drafted = plan(container, actor, items, task=task, correlation_id=note("c-plan", "ai.plan_set"))
    approved = approve(
        container, actor, drafted, correlation_id=note("c-approve", "ai.plan_approved")
    )
    first = approved.steps[0].step.id
    started = start(container, actor, first, correlation_id=note("c-start", "ai.run_started"))
    result = finding(text=secrets[3], summary=secrets[4])
    reported = report(
        container,
        actor,
        started.run,
        result=result,
        correlation_id=note("c-report", "ai.run_reported"),
    )
    review(container, actor, reported, "accept", correlation_id=note("c-accept", "ai.run_accepted"))
    second = start(
        container,
        actor,
        approved.steps[1].step.id,
        correlation_id=note("c-start-2", "ai.run_started"),
    )
    asked = report(
        container,
        actor,
        second.run,
        "question",
        question=secrets[5],
        correlation_id=note("c-ask", "ai.run_reported"),
    )
    review(
        container,
        actor,
        asked,
        "answer",
        secrets[6],
        correlation_id=note("c-answer", "ai.run_answered"),
    )
    container.ai_plans.approve_plan(
        actor,
        task.id,
        digest=approved.digest,
        decision="withdraw",
        idempotency_key=key(),
        correlation_id=note("c-withdraw", "ai.plan_withdrawn"),
    )

    for correlation_id, event in written:
        rows = admin_rows(
            "SELECT event, to_jsonb(a)::text FROM sidekick.audit_events a "
            "WHERE correlation_id = :c",
            c=correlation_id,
        )
        assert [row[0] for row in rows] == [event], correlation_id
        assert not [s for s in secrets if s in str(rows[0][1])], correlation_id
    every_row = " ".join(
        str(row[0]) for row in admin_rows("SELECT to_jsonb(a)::text FROM sidekick.audit_events a")
    )
    assert not [s for s in secrets if s in every_row]
    assert container.ai_plans.get_plan(actor, task.id).state is PlanState.DRAFT
