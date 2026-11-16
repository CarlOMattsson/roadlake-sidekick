"""Completing a Task completes its open Steps and Actions; reopening it opens them again.

Every way to complete a Task goes through the same use case: the MCP tools, the companion
routes and the service itself. The Steps and Actions move in the Task's own transaction.
"""

import asyncio
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastmcp import Client

from sidekick.mcp.server import create_mcp_server
from sidekick.shared.errors import PermissionDeniedError
from sidekick.shared.types import Actor, new_uuid7
from sidekick.tasks.application.models import UpdateTaskCommand
from sidekick.tasks.domain import Task, TaskStatus
from sidekick.tasks.domain.recurrence import RecurrenceData
from sidekick.work.domain import Action, ActionStatus, Step
from sidekick.work.domain.ai_plan import PlanState
from sidekick.work.domain.ai_runs import AiRunResult, AiRunState, AiUsage
from sidekick.work.domain.ai_spec import ResultFormat
from tests.support.ai_steps import (
    admin_rows,
    ai_item,
    approve,
    approved_plan,
    container_with,
    plan,
)
from tests.support.ai_steps import owner_actor as ai_owner_actor
from tests.support.companion import (
    bearer,
    companion_app,
    create_task,
    owner,
    owner_actor,
    paired_token,
)

pytestmark = pytest.mark.integration


class World:
    """One app with an owner, the helpers to build a Task with Steps and to read it back."""

    def __init__(self) -> None:
        self.app: FastAPI = companion_app()
        self.container = self.app.state.container
        self.user_id = owner(self.app)
        self.actor = owner_actor(self.user_id)

    def key(self) -> str:
        return f"completion-{uuid4()}"

    def task(self, title: str = "Pack for the trip") -> Task:
        return create_task(self.app, self.user_id, title=title)

    def step(self, task: Task, title: str, *, done: bool = False) -> Step:
        step = self.container.steps.create_step(
            self.actor, task.id, title=title, idempotency_key=self.key()
        )
        return self.complete_step(step) if done else step

    def complete_step(self, step: Step) -> Step:
        return self.container.steps.complete_step(
            self.actor, step.id, version=step.version, idempotency_key=self.key()
        )

    def action(self, step: Step, title: str, *, done: bool = False) -> Action:
        action = self.container.steps.create_action(
            self.actor, step.id, title=title, idempotency_key=self.key()
        )
        if done:
            action = self.container.steps.complete_action(
                self.actor, action.id, version=action.version, idempotency_key=self.key()
            )
        return action

    def steps(self, task: Task) -> dict[str, Step]:
        page = self.container.steps.list_steps(self.actor, task.id)
        return {step.title: step for step in page.items}

    def actions(self, step: Step) -> dict[str, Action]:
        page = self.container.steps.list_actions(self.actor, step.id)
        return {action.title: action for action in page.items}

    def complete(self, task: Task, key: str | None = None) -> Task:
        current = self.container.tasks.get(self.actor, task.id)
        return self.container.tasks.complete(
            self.actor, task.id, version=current.version, idempotency_key=key or self.key()
        )

    def reopen(self, task: Task) -> Task:
        current = self.container.tasks.get(self.actor, task.id)
        return self.container.tasks.update(
            self.actor,
            task.id,
            version=current.version,
            idempotency_key=self.key(),
            command=UpdateTaskCommand(status=TaskStatus.TODO),
        )


class Checklist:
    """A Task with the mix of Steps and Actions the cascade has to tell apart."""

    def __init__(self, world: World) -> None:
        self.world = world
        self.task = world.task()
        self.open_step = world.step(self.task, "Open step")
        self.open_action = world.action(self.open_step, "Open action")
        self.done_action = world.action(self.open_step, "Done action", done=True)
        self.done_step = world.step(self.task, "Done step", done=True)
        self.late_action = world.action(self.done_step, "Action on a done step")
        self.archived_step = world.step(self.task, "Archived step")
        self.world.container.steps.archive_step(
            world.actor,
            self.archived_step.id,
            version=self.archived_step.version,
            idempotency_key=world.key(),
        )
        self.before_steps = world.steps(self.task)
        self.before_done_action = world.actions(self.open_step)["Done action"]
        self.before_late_action = world.actions(self.done_step)["Action on a done step"]

    def assert_closed(self) -> None:
        world = self.world
        steps = world.steps(self.task)
        assert steps["Open step"].status is TaskStatus.COMPLETED
        assert steps["Open step"].completed_at is not None
        actions = world.actions(self.open_step)
        assert actions["Open action"].status is ActionStatus.COMPLETED
        assert actions["Done action"] == self.before_done_action
        assert steps["Done step"] == self.before_steps["Done step"]
        assert world.actions(self.done_step)["Action on a done step"] == self.before_late_action
        archived = world.container.steps.get_step(world.actor, self.archived_step.id)
        assert archived.status is TaskStatus.TODO
        assert archived.version == self.archived_step.version + 1  # only its archiving

    def assert_reopened(self) -> None:
        world = self.world
        steps = world.steps(self.task)
        assert steps["Open step"].status is TaskStatus.TODO
        assert steps["Open step"].completed_at is None
        actions = world.actions(self.open_step)
        assert actions["Open action"].status is ActionStatus.OPEN
        assert actions["Done action"] == self.before_done_action
        assert steps["Done step"] == self.before_steps["Done step"]
        assert world.actions(self.done_step)["Action on a done step"] == self.before_late_action


DAILY: RecurrenceData = {
    "frequency": "daily",
    "interval": 1,
    "weekdays": [],
    "day_of_month": None,
    "until": None,
}


class RepeatingChecklist:
    """A repeating Task with a done and an open Step, a done Action and an archived Step."""

    def __init__(self, world: World) -> None:
        self.world = world
        self.task = world.container.tasks.create(
            world.actor,
            title="Water the plants",
            idempotency_key=world.key(),
            due_at=world.container.tasks.clock.now() + timedelta(days=1),
            recurrence=DAILY,
        )
        self.step = world.step(self.task, "Fill the can", done=True)
        world.action(self.step, "Find the can", done=True)
        world.step(self.task, "Pour")
        self.archived = world.step(self.task, "Archived step", done=False)
        world.container.steps.archive_step(
            world.actor,
            self.archived.id,
            version=self.archived.version,
            idempotency_key=world.key(),
        )

    def assert_reset(self) -> None:
        world = self.world
        steps = world.steps(self.task)
        assert {step.status for step in steps.values()} == {TaskStatus.TODO}
        assert all(step.completed_at is None for step in steps.values())
        assert {a.status for a in world.actions(steps["Fill the can"]).values()} == {
            ActionStatus.OPEN
        }
        archived = world.container.steps.get_step(world.actor, self.archived.id)
        assert archived.version == self.archived.version + 1  # only its archiving


def test_completing_a_task_completes_its_open_steps_and_actions() -> None:
    world = World()
    checklist = Checklist(world)

    done = world.complete(checklist.task)

    assert done.status is TaskStatus.COMPLETED
    checklist.assert_closed()
    # What the completion closed carries the Task's own completion time.
    assert world.steps(checklist.task)["Open step"].completed_at == done.completed_at


def test_the_same_key_repeats_nothing_and_a_second_completion_touches_no_step() -> None:
    world = World()
    checklist = Checklist(world)
    key = world.key()
    first = world.complete(checklist.task, key)
    steps_after = world.steps(checklist.task)
    actions_after = world.actions(checklist.open_step)

    replay = world.container.tasks.complete(
        world.actor, checklist.task.id, version=first.version - 1, idempotency_key=key
    )
    again = world.complete(checklist.task)

    assert replay.version == first.version == again.version
    assert world.steps(checklist.task) == steps_after
    assert world.actions(checklist.open_step) == actions_after


def test_reopening_a_task_opens_only_what_its_completion_closed() -> None:
    world = World()
    checklist = Checklist(world)
    world.complete(checklist.task)
    steps = world.steps(checklist.task)
    # Ticked off by hand while the Task is done, so it is not what the completion closed.
    manual = world.step(checklist.task, "Added later")
    manual = world.complete_step(manual)

    reopened = world.reopen(checklist.task)

    assert reopened.status is TaskStatus.TODO
    checklist.assert_reopened()
    assert world.steps(checklist.task)["Added later"].status is TaskStatus.COMPLETED
    assert world.steps(checklist.task)["Added later"] == world.container.steps.get_step(
        world.actor, manual.id
    )
    assert steps["Done step"].status is TaskStatus.COMPLETED


def test_a_step_opened_and_ticked_again_by_hand_stays_done_when_the_task_reopens() -> None:
    world = World()
    task = world.task()
    step = world.step(task, "Only step")
    world.complete(task)
    closed = world.container.steps.get_step(world.actor, step.id)
    reopened_step = world.container.steps.update_step(
        world.actor,
        step.id,
        version=closed.version,
        idempotency_key=world.key(),
        status=TaskStatus.TODO,
    )
    world.container.steps.complete_step(
        world.actor, step.id, version=reopened_step.version, idempotency_key=world.key()
    )

    world.reopen(task)

    assert world.steps(task)["Only step"].status is TaskStatus.COMPLETED


def test_a_repeating_task_starts_its_steps_and_actions_over_for_the_next_run() -> None:
    world = World()
    checklist = RepeatingChecklist(world)
    key = world.key()

    next_run = world.complete(checklist.task, key)

    assert next_run.status is TaskStatus.TODO
    checklist.assert_reset()
    after = (world.steps(checklist.task), world.actions(checklist.step))
    # The same key again repeats nothing.
    world.container.tasks.complete(
        world.actor, checklist.task.id, version=checklist.task.version, idempotency_key=key
    )
    assert (world.steps(checklist.task), world.actions(checklist.step)) == after


def test_the_mcp_and_companion_completion_of_a_repeating_task_start_it_over() -> None:
    world = World()
    checklist = RepeatingChecklist(world)
    task = checklist.task
    asyncio.run(_complete_through_mcp(world, task.id, task.version))
    checklist.assert_reset()
    again = RepeatingChecklist(world)
    with TestClient(world.app) as client:
        token = paired_token(client, world.app, world.user_id)
        response = client.post(
            f"/companion/v1/tasks/{again.task.id}/complete",
            headers={**bearer(token), "Idempotency-Key": "companion-repeat-1"},
            json={"version": again.task.version},
        )
    assert response.status_code == 200, response.text
    assert response.json()["task"]["status"] == "todo"
    again.assert_reset()


async def _complete_through_mcp(world: World, task_id: UUID, version: int) -> None:
    async with mcp_client(world) as client:
        await client.call_tool(
            "complete_task",
            {"task_id": str(task_id), "version": version, "idempotency_key": "mcp-repeat-0001"},
        )


def test_the_activity_of_a_repeating_completion_counts_what_was_reset() -> None:
    world = World()
    checklist = RepeatingChecklist(world)
    world.complete(checklist.task)

    entries = admin_rows(
        "SELECT evidence::text FROM sidekick.activity_entries "
        "WHERE operation = 'complete_task' AND aggregate_id = :id",
        id=checklist.task.id,
    )

    assert len(entries) == 1
    assert '"steps_reset": 1' in str(entries[0][0])
    assert '"actions_reset": 1' in str(entries[0][0])


def test_a_repeating_ai_plan_stays_approved_and_its_running_run_is_cancelled() -> None:
    container = container_with()
    actor = ai_owner_actor(container)
    task = container.tasks.create(
        actor,
        title="Weekly price check",
        idempotency_key=f"repeat-{uuid4()}",
        due_at=container.tasks.clock.now() + timedelta(days=1),
        recurrence=DAILY,
    )
    drafted = plan(container, actor, [ai_item("Look it up"), ai_item("Write it down")], task=task)
    view = approve(container, actor, drafted)
    first, second = (item.step.id for item in view.steps)
    started = container.ai_runs.start_step(actor, first, idempotency_key=f"ai-{uuid4()}")
    reported = container.ai_runs.report(
        actor,
        started.run.id,
        run_version=started.run.version,
        outcome="result",
        result=AiRunResult(format=ResultFormat.TEXT, text="Found.", summary="Found"),
        usage=AiUsage(),
        idempotency_key=str(new_uuid7()),
    )
    container.ai_runs.review(
        actor,
        reported.id,
        run_version=reported.version,
        decision="accept",
        idempotency_key=str(new_uuid7()),
    )
    running = container.ai_runs.start_step(actor, second, idempotency_key=f"ai-{uuid4()}")
    current = container.tasks.get(actor, task.id)

    container.tasks.complete(
        actor, task.id, version=current.version, idempotency_key=f"complete-{uuid4()}"
    )

    after = container.ai_plans.get_plan(actor, task.id)
    assert after.state is PlanState.APPROVED
    assert [item.step.status for item in after.steps] == [TaskStatus.TODO, TaskStatus.TODO]
    assert not any(item.step.attention_requested for item in after.steps)
    assert container.ai_runs.get_run(actor, running.run.id).state is AiRunState.CANCELLED


def test_update_task_with_a_completed_status_follows_the_same_rules() -> None:
    world = World()
    checklist = Checklist(world)

    world.container.tasks.update(
        world.actor,
        checklist.task.id,
        version=checklist.task.version,
        idempotency_key=world.key(),
        command=UpdateTaskCommand(status=TaskStatus.COMPLETED),
    )

    checklist.assert_closed()
    world.reopen(checklist.task)
    checklist.assert_reopened()


def test_the_activity_entry_counts_what_moved_and_the_audit_names_no_title() -> None:
    world = World()
    checklist = Checklist(world)
    correlation = f"cascade-{uuid4().hex[:12]}"
    current = world.container.tasks.get(world.actor, checklist.task.id)
    world.container.tasks.complete(
        world.actor,
        checklist.task.id,
        version=current.version,
        idempotency_key=world.key(),
        correlation_id=correlation,
    )

    entries = admin_rows(
        "SELECT evidence::text FROM sidekick.activity_entries "
        "WHERE operation = 'complete_task' AND aggregate_id = :id",
        id=checklist.task.id,
    )
    events = admin_rows(
        "SELECT event, to_jsonb(a)::text FROM sidekick.audit_events a WHERE correlation_id = :c",
        c=correlation,
    )

    assert len(entries) == 1
    assert '"steps_closed": 1' in str(entries[0][0])
    assert '"actions_closed": 1' in str(entries[0][0])
    assert sorted(str(row[0]) for row in events) == [
        "action.completed",
        "step.completed",
        "task.completed",
    ]
    assert "Open step" not in " ".join(str(row[1]) for row in events)


def test_another_owners_steps_are_never_touched() -> None:
    world = World()
    stranger_id = owner(world.app, "stranger")
    stranger = owner_actor(stranger_id)
    foreign_task = create_task(world.app, stranger_id, title="Foreign")
    foreign_step = world.container.steps.create_step(
        stranger, foreign_task.id, title="Foreign step", idempotency_key=world.key()
    )
    mine = world.task()
    world.step(mine, "My step")

    world.complete(mine)

    assert world.container.steps.get_step(stranger, foreign_step.id) == foreign_step
    with pytest.raises(PermissionDeniedError):
        read_only = Actor(world.user_id, frozenset({"tasks:read"}))
        world.container.tasks.complete(read_only, mine.id, version=1, idempotency_key=world.key())


def test_an_ai_step_with_a_running_run_is_completed_and_its_run_cancelled() -> None:
    container = container_with()
    actor = ai_owner_actor(container)
    view = approved_plan(container, actor, [ai_item("Look it up"), ai_item("Write it down")])
    started = container.ai_runs.start_step(actor, view.steps[0].step.id, idempotency_key="ai-1")
    task = container.tasks.get(actor, view.task.id)

    container.tasks.complete(
        actor, task.id, version=task.version, idempotency_key=f"complete-{uuid4()}"
    )

    steps = {s.title: s for s in container.steps.list_steps(actor, task.id).items}
    assert all(step.status is TaskStatus.COMPLETED for step in steps.values())
    assert container.ai_runs.get_run(actor, started.run.id).state is AiRunState.CANCELLED


def test_an_ai_result_waiting_for_review_stays_on_its_run() -> None:
    container = container_with()
    actor = ai_owner_actor(container)
    view = approved_plan(container, actor, [ai_item("Look it up")])
    started = container.ai_runs.start_step(actor, view.steps[0].step.id, idempotency_key="ai-2")
    reported = container.ai_runs.report(
        actor,
        started.run.id,
        run_version=started.run.version,
        outcome="result",
        result=AiRunResult(
            format=ResultFormat.TEXT, text="Open nine to six.", summary="Opening hours found"
        ),
        usage=AiUsage(),
        idempotency_key=str(new_uuid7()),
    )
    task = container.tasks.get(actor, view.task.id)
    flagged = container.steps.get_step(actor, view.steps[0].step.id)
    assert flagged.attention_requested

    container.tasks.complete(
        actor, task.id, version=task.version, idempotency_key=f"complete-{uuid4()}"
    )

    step = container.steps.get_step(actor, view.steps[0].step.id)
    assert step.status is TaskStatus.COMPLETED
    assert not step.attention_requested
    run = container.ai_runs.get_run(actor, reported.id)
    assert run.state is AiRunState.TO_REVIEW
    assert run.result is not None


# --- The MCP tools and the companion routes ---------------------------------------------------


def mcp_client(world: World) -> Client[Any]:
    server = create_mcp_server(
        world.container, actor_provider=lambda: world.actor, enable_auth=False
    )
    return Client(server)


@pytest.mark.asyncio
async def test_the_mcp_tools_complete_and_reopen_the_steps_too() -> None:
    world = World()
    checklist = Checklist(world)
    task = checklist.task
    async with mcp_client(world) as client:
        done = await client.call_tool(
            "complete_task",
            {"task_id": str(task.id), "version": task.version, "idempotency_key": "mcp-done-0001"},
        )
        checklist.assert_closed()
        assert done.structured_content is not None
        reopened = await client.call_tool(
            "update_task",
            {
                "task_id": str(task.id),
                "version": done.structured_content["task"]["version"],
                "idempotency_key": "mcp-reopen-0001",
                "changes": {"status": "todo"},
            },
        )

    assert reopened.structured_content is not None
    assert reopened.structured_content["task"]["status"] == "todo"
    checklist.assert_reopened()


def test_the_companion_routes_complete_and_reopen_the_steps_too() -> None:
    world = World()
    checklist = Checklist(world)
    task = checklist.task
    with TestClient(world.app) as client:
        token = paired_token(client, world.app, world.user_id)
        done = client.post(
            f"/companion/v1/tasks/{task.id}/complete",
            headers={**bearer(token), "Idempotency-Key": "companion-done-1"},
            json={"version": task.version},
        )
        assert done.status_code == 200, done.text
        checklist.assert_closed()
        replay = client.post(
            f"/companion/v1/tasks/{task.id}/complete",
            headers={**bearer(token), "Idempotency-Key": "companion-done-1"},
            json={"version": task.version},
        )
        reopened = client.post(
            f"/companion/v1/tasks/{task.id}/reopen",
            headers={**bearer(token), "Idempotency-Key": "companion-reopen-1"},
            json={"version": done.json()["task"]["version"]},
        )

    assert replay.json() == done.json()
    assert reopened.status_code == 200, reopened.text
    checklist.assert_reopened()


def test_a_device_cannot_complete_another_owners_task_or_its_steps() -> None:
    world = World()
    stranger_id = owner(world.app, "stranger")
    foreign = create_task(world.app, stranger_id, title="Foreign")
    foreign_step = world.container.steps.create_step(
        owner_actor(stranger_id), foreign.id, title="Foreign step", idempotency_key=world.key()
    )
    with TestClient(world.app) as client:
        token = paired_token(client, world.app, world.user_id)
        response = client.post(
            f"/companion/v1/tasks/{foreign.id}/complete",
            headers={**bearer(token), "Idempotency-Key": "companion-foreign-1"},
            json={"version": foreign.version},
        )

    assert response.status_code == 404
    assert "Foreign" not in response.text
    stored = world.container.steps.get_step(owner_actor(stranger_id), foreign_step.id)
    assert stored.status is TaskStatus.TODO
    assert world.container.tasks.get(owner_actor(stranger_id), foreign.id).status is TaskStatus.TODO


def test_a_failed_cascade_leaves_the_task_open(monkeypatch: pytest.MonkeyPatch) -> None:
    world = World()
    task = world.task()
    step = world.step(task, "Only step")
    closer = world.container.tasks.step_closer
    assert closer is not None

    def failing(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(closer.store, "save_step", failing)
    with pytest.raises(RuntimeError):
        world.complete(task)
    monkeypatch.undo()

    assert world.container.tasks.get(world.actor, task.id).status is TaskStatus.TODO
    assert world.container.steps.get_step(world.actor, step.id).status is TaskStatus.TODO
