"""The AI Step tools through a real FastMCP client and a real database.

The owner's Claude plans a task, the owner approves it in the app, the owner's Claude Code starts
the AI steps and reports back, and the owner reviews the result. Each role holds only the scopes
it needs: `ai:run` is opt-in, and approving or reviewing needs `tasks:write`.
"""

import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import pytest
from fastmcp.client.client import CallToolResult
from mcp.types import TextContent
from sqlalchemy import text

from sidekick.api.app import Container, create_container
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.mcp.harness import SwitchableServer
from tests.support.mcp_logging import (
    _all_logs,  # noqa: F401  (the `all_logs` fixture)
    _Collector,
)
from tests.support.settings import make_settings

RESULT_TEXT = "SENTINEL-RESULT-BODY draft reply for the landlord"
QUESTION_TEXT = "SENTINEL-QUESTION which tenant do you mean?"
SPEC = {"goal": "Draft a reply to the landlord", "output": {"format": "text"}}


@dataclass(frozen=True, slots=True)
class World:
    container: Container
    server: SwitchableServer
    code: Actor  # the owner's Claude Code: runs AI steps, may not plan, approve or review
    full: Actor  # a model that reads, writes and runs AI steps
    chat: Actor  # a chat model without ai:run
    ai_only: Actor  # ai:run without tasks:read
    setup: Actor  # what the tests themselves use to create and read tasks


def _world() -> World:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("ai-step-owner", "AI Step Owner")

    def actor(*scopes: str) -> Actor:
        return Actor(owner, frozenset(scopes))

    full = actor("tasks:read", "tasks:write", "ai:run")
    return World(
        container,
        SwitchableServer.build(container, full),
        code=actor("ai:run", "tasks:read"),
        full=full,
        chat=actor("tasks:read", "tasks:write"),
        ai_only=actor("ai:run"),
        setup=actor("tasks:read", "tasks:write", "projects:read"),
    )


async def _call(world: World, actor: Actor, name: str, **arguments: Any) -> CallToolResult:
    if "idempotency_key" not in arguments and name not in _READS:
        arguments["idempotency_key"] = f"ai-{uuid4().hex}"
    async with world.server.client(actor) as client:
        return await client.call_tool(name, arguments, raise_on_error=False)


_READS = {
    "get_ai_plan",
    "list_ai_steps",
    "get_ai_step_run",
    "get_ai_usage",
    "get_task",
    "list_recent_changes",
}


async def _ok(world: World, actor: Actor, name: str, **arguments: Any) -> dict[str, Any]:
    result = await _call(world, actor, name, **arguments)
    assert not result.is_error, result.structured_content
    assert result.structured_content is not None
    return result.structured_content


def _all_text(result: CallToolResult) -> str:
    texts = [block.text for block in result.content if isinstance(block, TextContent)]
    return "\n".join([*texts, json.dumps(result.structured_content)])


async def _task(world: World, title: str = "Reply to the landlord") -> dict[str, Any]:
    created = await _ok(world, world.setup, "create_task", title=title)
    return created["task"]


async def _planned(world: World) -> tuple[dict[str, Any], dict[str, Any]]:
    """A task with a draft plan of one AI step: the task and the plan."""
    task = await _task(world)
    steps = [{"title": "Draft the reply", "performer": "ai", "ai_spec": SPEC}]
    plan = await _ok(
        world, world.full, "set_ai_plan", task_id=task["id"], task_version=task["version"],
        steps=steps,
    )  # fmt: skip
    return task, plan["plan"]


async def _approved(world: World) -> dict[str, Any]:
    task, plan = await _planned(world)
    approved = await _ok(
        world, world.full, "approve_ai_plan", task_id=task["id"], digest=plan["digest"]
    )
    return approved["plan"]


async def _started(world: World) -> tuple[dict[str, Any], dict[str, Any]]:
    """An approved plan whose only AI step is running: the plan and the started step."""
    plan = await _approved(world)
    step_id = plan["steps"][0]["step"]["id"]
    started = await _ok(world, world.code, "start_ai_step", step_id=step_id)
    return plan, started


def _report(run: dict[str, Any], outcome: str = "result", **extra: Any) -> dict[str, Any]:
    arguments: dict[str, Any] = {
        "run_id": run["id"],
        "run_version": run["version"],
        "outcome": outcome,
    }
    if outcome == "result":
        arguments["result"] = {"format": "text", "text": RESULT_TEXT, "summary": "A short draft"}
    if outcome == "question":
        arguments["question"] = QUESTION_TEXT
    return {**arguments, **extra}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_whole_flow_from_plan_to_an_accepted_step() -> None:
    world = _world()
    task, plan = await _planned(world)
    assert plan["state"] == "draft"
    assert plan["ai_possible"] is True
    drafted = await _ok(world, world.full, "get_ai_plan", task_id=task["id"])
    assert drafted["plan"]["state"] == "draft"
    assert drafted["plan"]["steps"][0]["ai_spec"]["goal"] == SPEC["goal"]

    approved = await _ok(
        world, world.full, "approve_ai_plan", task_id=task["id"], digest=plan["digest"]
    )
    assert approved["plan"]["state"] == "approved"
    step_id = approved["plan"]["steps"][0]["step"]["id"]

    ready = await _ok(world, world.code, "list_ai_steps", state="ready")
    assert [(item["step_id"], item["startable"]) for item in ready["items"]] == [(step_id, True)]

    result = await _call(world, world.code, "start_ai_step", step_id=step_id)
    assert not result.is_error
    started = result.structured_content
    assert started is not None
    assert started["run"]["state"] == "running"
    assert started["step_id"] == step_id
    assert started["budget_usd"] > 0
    assert started["max_turns"] > 0
    assert started["brief"] in _all_text(result)

    run = started["run"]
    reported = await _ok(world, world.code, "report_ai_step_result", **_report(run))
    assert reported["run"]["state"] == "to_review"
    assert reported["content"] is None

    read = await _ok(world, world.code, "get_ai_step_run", run_id=run["id"])
    assert read["content"] is None
    assert read["run"]["has_result"] is True
    with_content = await _ok(
        world, world.code, "get_ai_step_run", run_id=run["id"], include_content=True
    )
    assert with_content["content"]["result_text"] == RESULT_TEXT

    reviewed = await _ok(
        world, world.full, "review_ai_step_result",
        run_id=run["id"], run_version=reported["run"]["version"], decision="accept",
    )  # fmt: skip
    assert reviewed["run"]["state"] == "accepted"
    after = await _ok(world, world.full, "get_ai_plan", task_id=task["id"])
    assert after["plan"]["steps"][0]["ai_status"] == "done"
    assert after["plan"]["steps"][0]["step"]["status"] == "completed"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_claude_code_cannot_plan_approve_review_or_complete() -> None:
    world = _world()
    task, plan = await _planned(world)
    steps = [{"title": "Another", "performer": "ai", "ai_spec": SPEC}]
    refused = {
        "set_ai_plan": {"task_id": task["id"], "task_version": 99, "steps": steps},
        "approve_ai_plan": {"task_id": task["id"], "digest": plan["digest"]},
        "review_ai_step_result": {"run_id": str(uuid4()), "run_version": 1, "decision": "accept"},
        "complete_task_step": {"step_id": plan["steps"][0]["step"]["id"], "version": 1},
    }
    for name, arguments in refused.items():
        result = await _call(world, world.code, name, **arguments)
        assert result.is_error, name
        assert result.structured_content is not None
        assert result.structured_content["code"] == "forbidden", name
    after = await _ok(world, world.full, "get_ai_plan", task_id=task["id"])
    assert after["plan"]["state"] == "draft"
    assert after["plan"]["steps"][0]["step"]["status"] == "todo"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_claude_code_can_list_start_and_report() -> None:
    world = _world()
    _, started = await _started(world)
    listed = await _ok(world, world.code, "list_ai_steps")
    assert [item["status"] for item in listed["items"]] == ["running"]
    reported = await _ok(world, world.code, "report_ai_step_result", **_report(started["run"]))
    assert reported["run"]["state"] == "to_review"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_chat_model_plans_and_reads_but_cannot_run_steps() -> None:
    world = _world()
    plan, started = await _started(world)
    step_id = plan["steps"][0]["step"]["id"]
    assert (await _ok(world, world.chat, "get_ai_plan", task_id=plan["task_id"]))["plan"]
    task = await _task(world, "Chat planned")
    steps = [{"title": "Draft", "performer": "ai", "ai_spec": SPEC}]
    planned = await _ok(
        world, world.chat, "set_ai_plan", task_id=task["id"], task_version=task["version"],
        steps=steps,
    )  # fmt: skip
    assert planned["plan"]["state"] == "draft"

    for name, arguments in (
        ("start_ai_step", {"step_id": step_id}),
        ("report_ai_step_result", _report(started["run"])),
    ):
        result = await _call(world, world.chat, name, **arguments)
        assert result.is_error, name
        assert result.structured_content is not None
        assert result.structured_content["code"] == "forbidden", name


@pytest.mark.asyncio
@pytest.mark.integration
async def test_ai_run_without_read_scope_cannot_start_a_step() -> None:
    world = _world()
    plan = await _approved(world)
    step_id = plan["steps"][0]["step"]["id"]
    result = await _call(world, world.ai_only, "start_ai_step", step_id=step_id)
    assert result.is_error
    assert result.structured_content is not None
    assert result.structured_content["code"] == "forbidden"
    ready = await _ok(world, world.full, "list_ai_steps", state="ready")
    assert [item["startable"] for item in ready["items"]] == [True]
    assert ready["items"][0]["latest_run"] is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_approving_a_plan_that_changed_since_the_owner_saw_it_is_refused() -> None:
    world = _world()
    task, plan = await _planned(world)
    step = plan["steps"][0]["step"]
    edited = await _call(
        world, world.full, "update_task_step",
        step_id=step["id"], version=step["version"], changes={"instruction": "Be blunt"},
    )  # fmt: skip
    assert not edited.is_error, edited.structured_content
    result = await _call(
        world, world.full, "approve_ai_plan", task_id=task["id"], digest=plan["digest"]
    )
    assert result.is_error
    assert result.structured_content is not None
    assert result.structured_content["code"] == "conflict"
    assert result.structured_content["reason"] == "plan_changed"
    still = await _ok(world, world.full, "get_ai_plan", task_id=task["id"])
    assert still["plan"]["state"] == "draft"
    assert still["plan"]["digest"] != plan["digest"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_draft_plan_can_be_rewritten_before_approval() -> None:
    world = _world()
    task, plan = await _planned(world)
    renamed = [{"step_id": plan["steps"][0]["step"]["id"], "performer": "ai", "title": "Renamed"}]
    changed = await _ok(
        world, world.full, "set_ai_plan", task_id=task["id"], task_version=plan["task_version"],
        steps=renamed,
    )  # fmt: skip
    assert changed["plan"]["digest"] != plan["digest"]
    assert changed["plan"]["state"] == "draft"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_step_of_a_plan_changed_after_approval_is_not_started() -> None:
    world = _world()
    plan = await _approved(world)
    step = plan["steps"][0]["step"]
    edited = await _call(
        world, world.full, "update_task_step",
        step_id=step["id"], version=step["version"], changes={"instruction": "Be blunt"},
    )  # fmt: skip
    assert not edited.is_error, edited.structured_content
    state = await _ok(world, world.full, "get_ai_plan", task_id=plan["task_id"])
    assert state["plan"]["state"] == "changed_since_approval"
    assert (await _ok(world, world.code, "list_ai_steps"))["items"] == []

    result = await _call(world, world.code, "start_ai_step", step_id=step["id"])
    assert result.is_error
    assert result.structured_content is not None
    assert result.structured_content["code"] == "conflict"
    assert result.structured_content["reason"] == "plan_changed"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_reported_cost_is_stored_as_the_clients_estimate() -> None:
    world = _world()
    _, started = await _started(world)
    usage = {"model": "claude-code", "input_tokens": 1200, "cost_usd_estimate": 0.25}
    reported = await _ok(
        world, world.code, "report_ai_step_result", **_report(started["run"], usage=usage)
    )
    run = reported["run"]
    assert run["cost_source"] == "client_estimate"
    assert run["cost_usd"] == pytest.approx(0.25)
    assert run["model"] == "claude-code"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_usage_shows_the_month_and_today_without_any_text() -> None:
    world = _world()
    _, started = await _started(world)
    usage = {"model": "claude-code", "cost_usd_estimate": 0.25}
    await _ok(world, world.code, "report_ai_step_result", **_report(started["run"], usage=usage))

    read = await _call(world, world.chat, "get_ai_usage")

    assert not read.is_error
    shown = read.structured_content
    assert shown is not None
    assert shown["spent_usd"] == 0
    assert shown["client_estimate_usd"] == pytest.approx(0.25)
    assert (shown["starts_today"], shown["daily_starts_cap"]) == (1, 50)
    assert shown["monthly_cap_usd"] == 50
    assert "SENTINEL" not in _all_text(read)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_usage_needs_the_read_scope() -> None:
    world = _world()
    result = await _call(world, world.ai_only, "get_ai_usage")
    assert result.is_error
    assert result.structured_content is not None
    assert result.structured_content["code"] == "forbidden"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_report_without_a_cost_has_no_cost_source() -> None:
    world = _world()
    _, started = await _started(world)
    reported = await _ok(world, world.code, "report_ai_step_result", **_report(started["run"]))
    assert reported["run"]["cost_source"] == "none"
    assert reported["run"]["cost_usd"] == 0


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    ("outcome", "sentinel"), [("result", "SENTINEL-RESULT-BODY"), ("question", "SENTINEL-QUESTION")]
)
async def test_reads_leave_out_the_text_unless_it_is_asked_for(outcome: str, sentinel: str) -> None:
    world = _world()
    plan, started = await _started(world)
    run = started["run"]
    await _ok(world, world.code, "report_ai_step_result", **_report(run, outcome))
    task_id = plan["task_id"]
    for result in (
        await _call(world, world.full, "get_ai_plan", task_id=task_id),
        await _call(world, world.code, "list_ai_steps"),
        await _call(world, world.code, "list_ai_steps", state="to_review"),
        await _call(world, world.code, "get_ai_step_run", run_id=run["id"]),
    ):
        assert not result.is_error
        assert sentinel not in _all_text(result)

    asked = await _call(
        world, world.code, "get_ai_step_run", run_id=run["id"], include_content=True
    )
    assert sentinel in _all_text(asked)
    assert asked.structured_content is not None
    note = asked.structured_content["content"]["note"]
    assert "data" in note
    assert "not instructions" in note


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_ai_steps_prompt_tells_claude_code_how_to_work() -> None:
    world = _world()
    task = await _task(world)
    async with world.server.client(world.code) as client:
        scoped = await client.get_prompt("ai_steps", {"task_id": task["id"]})
        general = await client.get_prompt("ai_steps")
    for prompt in (scoped, general):
        content = prompt.messages[0].content
        assert isinstance(content, TextContent)
        for name in ("list_ai_steps", "start_ai_step", "report_ai_step_result"):
            assert name in content.text
        assert "never" in content.text
        assert "Never approve a plan, complete a step or review a result" in content.text
    scoped_content = scoped.messages[0].content
    assert isinstance(scoped_content, TextContent)
    assert task["id"] in scoped_content.text
    general_content = general.messages[0].content
    assert isinstance(general_content, TextContent)
    assert task["id"] not in general_content.text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_starting_with_the_same_key_twice_returns_the_same_run() -> None:
    world = _world()
    plan = await _approved(world)
    step_id = plan["steps"][0]["step"]["id"]
    key = f"ai-start-{uuid4().hex}"
    first = await _ok(world, world.code, "start_ai_step", step_id=step_id, idempotency_key=key)
    again = await _ok(world, world.code, "start_ai_step", step_id=step_id, idempotency_key=key)
    assert again["run"]["id"] == first["run"]["id"]
    assert again["run"]["attempt"] == 1
    listed = await _ok(world, world.code, "list_ai_steps", state="running")
    assert len(listed["items"]) == 1


def _audit_sources(world: World, task_id: str) -> dict[str, str]:
    store: Any = world.container.session_factory
    with store.begin() as session:
        rows = session.execute(
            text(
                "SELECT event, source FROM sidekick.audit_events "
                "WHERE target_id = :id AND event LIKE 'ai.plan_%'"
            ),
            {"id": task_id},
        ).all()
    return {event: source for event, source in rows}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_approval_is_the_owners_change_and_the_plan_is_claudes() -> None:
    world = _world()
    plan = await _approved(world)
    assert _audit_sources(world, plan["task_id"]) == {
        "ai.plan_set": "claude",
        "ai.plan_approved": "you",
    }


@pytest.mark.asyncio
@pytest.mark.integration
async def test_marking_a_task_possible_with_ai_and_removing_the_mark_withdraws_approval() -> None:
    world = _world()
    plan = await _approved(world)
    task_id = plan["task_id"]

    async def update(possible: Any) -> CallToolResult:
        current = (await _ok(world, world.setup, "get_task", task_id=task_id))["task"]
        return await _call(
            world, world.setup, "update_task",
            task_id=task_id, version=current["version"], changes={"ai_possible": possible},
        )  # fmt: skip

    refused = await update(None)
    assert refused.is_error
    assert (await _ok(world, world.setup, "get_task", task_id=task_id))["task"]["ai_possible"]

    removed = await update(False)
    assert not removed.is_error, removed.structured_content
    task = (await _ok(world, world.setup, "get_task", task_id=task_id))["task"]
    assert task["ai_possible"] is False
    after = await _ok(world, world.full, "get_ai_plan", task_id=task_id)
    assert after["plan"]["state"] == "none"
    assert after["plan"]["approved_at"] is None
    assert (await _ok(world, world.code, "list_ai_steps"))["items"] == []

    marked = await update(True)
    assert not marked.is_error, marked.structured_content
    task = (await _ok(world, world.setup, "get_task", task_id=task_id))["task"]
    assert task["ai_possible"] is True
    again = await _ok(world, world.full, "get_ai_plan", task_id=task_id)
    assert again["plan"]["state"] == "draft"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_starting_reporting_and_reviewing_never_write_text_to_a_log(
    all_logs: _Collector,
) -> None:
    goal = "SENTINEL-GOAL find the landlord's forwarding address"
    description = "SENTINEL-DESCRIPTION the flat on the second floor"
    comment = "SENTINEL-COMMENT make it shorter"
    world = _world()
    created = await _ok(
        world, world.setup, "create_task", title="SENTINEL-TITLE rent", description=description
    )
    task = created["task"]
    steps = [{"title": "SENTINEL-STEP", "performer": "ai", "ai_spec": {"goal": goal}}]
    plan = (
        await _ok(
            world,
            world.full,
            "set_ai_plan",
            task_id=task["id"],
            task_version=task["version"],
            steps=steps,
        )
    )["plan"]
    approved = await _ok(
        world, world.full, "approve_ai_plan", task_id=task["id"], digest=plan["digest"]
    )
    step_id = approved["plan"]["steps"][0]["step"]["id"]

    started = await _call(world, world.code, "start_ai_step", step_id=step_id)
    assert not started.is_error
    assert started.structured_content is not None
    run = started.structured_content["run"]
    assert goal in started.structured_content["brief"]
    # Calls the use case refuses, and one that fails validation before it gets there.
    await _call(world, world.code, "start_ai_step", step_id=step_id)
    refused_format = {"format": "table", "text": RESULT_TEXT, "summary": "x"}
    await _call(world, world.code, "report_ai_step_result", **_report(run, result=refused_format))
    await _call(world, world.code, "report_ai_step_result", **_report(run, outcome=RESULT_TEXT))
    reported = await _ok(world, world.code, "report_ai_step_result", **_report(run))
    await _ok(
        world, world.full, "review_ai_step_result",
        run_id=run["id"], run_version=reported["run"]["version"], decision="redo", comment=comment,
    )  # fmt: skip

    rendered = all_logs.rendered()
    for sentinel in (goal, description, comment, RESULT_TEXT, "SENTINEL-STEP", "SENTINEL-TITLE"):
        assert sentinel not in rendered, sentinel
    assert all(record.exc_info is None for record in all_logs.records)
