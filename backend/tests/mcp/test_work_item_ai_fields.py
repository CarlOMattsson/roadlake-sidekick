"""The Work list records carry a Task's AI state, and a board column counts what it lists."""

from typing import Any

import pytest
from fastmcp import Client, FastMCP

from sidekick.api.app import Container, create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.types import Actor
from sidekick.work.application.work_lists import board_column_totals
from tests.db import database_factory
from tests.support.app_origin import APP_ORIGIN
from tests.support.settings import make_settings

SCOPES = frozenset({"projects:read", "projects:write", "tasks:read", "tasks:write"})
SPEC = {"goal": "Draft the reply", "output": {"format": "text"}}
EMPTY_COLUMNS = {"todo": 0, "in_progress": 0, "blocked": 0, "completed": 0}


def _server_for(container: Container, actor: Actor) -> FastMCP:
    return create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)


async def _task(client: Client, title: str) -> dict[str, Any]:
    created = await client.call_tool(
        "create_task",
        {"title": title, "due_at": "2020-01-01T00:00:00Z", "idempotency_key": f"ai-fields-{title}"},
    )
    return created.structured_content["task"]


async def _project(client: Client, title: str) -> dict[str, Any]:
    domain = await client.call_tool(
        "create_domain", {"name": f"Domain {title}", "idempotency_key": f"ai-fields-d-{title}"}
    )
    created = await client.call_tool(
        "create_project",
        {
            "title": title,
            "domain_id": domain.structured_content["domain"]["id"],
            "idempotency_key": f"ai-fields-p-{title}",
        },
    )
    return created.structured_content["project"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_agenda_and_board_mark_ai_tasks_and_their_approved_plans() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("ai-fields-owner", "Owner")
    async with Client(_server_for(container, Actor(owner, SCOPES))) as client:
        plain = await _task(client, "plain")
        marked = await _task(client, "marked")
        planned = await _task(client, "planned")
        await client.call_tool(
            "update_task",
            {
                "task_id": marked["id"],
                "version": marked["version"],
                "idempotency_key": "ai-fields-mark",
                "changes": {"ai_possible": True},
            },
        )
        plan = await client.call_tool(
            "set_ai_plan",
            {
                "task_id": planned["id"],
                "task_version": planned["version"],
                "steps": [{"title": "Draft", "performer": "ai", "ai_spec": SPEC}],
                "idempotency_key": "ai-fields-plan",
            },
        )
        await client.call_tool(
            "approve_ai_plan",
            {
                "task_id": planned["id"],
                "digest": plan.structured_content["plan"]["digest"],
                "idempotency_key": "ai-fields-approve",
            },
            meta=APP_ORIGIN,
        )
        project = await _project(client, "Hus")
        agenda = await client.call_tool("get_work_agenda", {"limit": 100})
        board = await client.call_tool("get_work_board", {"limit": 50})

    expected = {
        plain["id"]: (False, False),
        marked["id"]: (True, False),
        planned["id"]: (True, True),
    }
    agenda_items = {item["id"]: item for item in agenda.structured_content["items"]}
    board_items = {
        item["id"]: item
        for column in board.structured_content["columns"].values()
        for item in column
    }
    for found in (agenda_items, board_items):
        assert {
            id_: (found[id_]["ai_possible"], found[id_]["ai_plan_approved"]) for id_ in expected
        } == expected
    # Other kinds carry the fields as false.
    project_item = board_items[project["id"]]
    assert (project_item["ai_possible"], project_item["ai_plan_approved"]) == (False, False)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_completed_project_is_not_counted_in_the_task_status_column() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("ai-fields-totals", "Owner")
    async with Client(_server_for(container, Actor(owner, SCOPES))) as client:
        done = await client.call_tool(
            "create_task", {"title": "done task", "idempotency_key": "totals-done-task"}
        )
        done_task = done.structured_content["task"]
        await client.call_tool(
            "update_task",
            {
                "task_id": done_task["id"],
                "version": done_task["version"],
                "idempotency_key": "totals-done-task-complete",
                "changes": {"status": "completed"},
            },
        )
        for title in ("finished", "running"):
            project = await _project(client, title)
            if title == "finished":
                finished = await client.call_tool(
                    "update_project",
                    {
                        "project_id": project["id"],
                        "version": project["version"],
                        "idempotency_key": "totals-project-complete",
                        "changes": {"status": "completed"},
                    },
                )
                assert not finished.is_error, finished.structured_content
        board = await client.call_tool("get_work_board", {"limit": 50})

    totals = board.structured_content["column_totals"]
    assert totals["completed"] == 1
    # The running Project and the two Domains are in no Task status column: counted where listed.
    assert totals["active"] == 3


def test_board_column_totals_leave_projects_out_of_task_status_columns_only() -> None:
    counts = {
        ("task", "completed"): 2,
        ("step", "completed"): 1,
        ("project", "completed"): 4,
        ("project", "active"): 3,
        ("domain", "active"): 1,
    }

    assert board_column_totals(counts) == {**EMPTY_COLUMNS, "completed": 3, "active": 4}
    assert board_column_totals({}) == EMPTY_COLUMNS
