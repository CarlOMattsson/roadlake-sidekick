"""get_work_hierarchy with include_tasks: Tasks and Steps under their Projects, owner-scoped.

The tree reuses the list_tasks and list_task_steps use cases, so these tests check the shape
of one call, the owner boundary, the missing-scope refusal and the caps.
"""

from typing import Any

import pytest
from fastmcp import Client, FastMCP

import sidekick.structured.work as work_module
from sidekick.api.app import Container, create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.mcp.text import CARD_NOTE
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings

WRITE_SCOPES = frozenset({"projects:read", "projects:write", "tasks:read", "tasks:write"})
READ_SCOPES = frozenset({"projects:read", "tasks:read"})


def _server_for(container: Container, actor: Actor) -> FastMCP:
    return create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)


def _setup() -> tuple[Container, Any, Any]:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    other = container.auth.provision_user("other-owner", "Other")
    return container, owner, other


def _structured(tool_result: Any) -> dict[str, Any]:
    assert tool_result.structured_content is not None
    structured: dict[str, Any] = tool_result.structured_content
    return structured


def _summary(tool_result: Any) -> str:
    """The card's one text block: the voice sentence, the id rows and the card note."""

    assert len(tool_result.content) == 1, "expected one text block; the card carries the rest"
    summary: str = tool_result.content[0].text
    return summary


async def _seed_tree(client: Client[Any], key: str) -> dict[str, Any]:
    """One Domain, one Project, one Task under the Project and two ordered Steps on the Task."""

    domain = _structured(
        await client.call_tool(
            "create_domain", {"name": "Home", "idempotency_key": f"{key}-domain"}
        )
    )["domain"]
    project = _structured(
        await client.call_tool(
            "create_project",
            {"domain_id": domain["id"], "title": "Garden", "idempotency_key": f"{key}-project"},
        )
    )["project"]
    task = _structured(
        await client.call_tool(
            "create_task",
            {
                "title": "Plant beans",
                "project_id": project["id"],
                "idempotency_key": f"{key}-task",
            },
        )
    )["task"]
    steps: list[dict[str, Any]] = []
    for index, title in enumerate(["Buy seeds", "Sow rows"]):
        step = _structured(
            await client.call_tool(
                "create_task_step",
                {
                    "task_id": task["id"],
                    "title": title,
                    "idempotency_key": f"{key}-step-{index}",
                },
            )
        )["step"]
        steps.append(step)
    return {"domain": domain, "project": project, "task": task, "steps": steps}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_include_tasks_shows_project_task_and_steps_in_one_call() -> None:
    container, owner, _ = _setup()
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        seeded = await _seed_tree(client, "tree-one")

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        tree = await client.call_tool("get_work_hierarchy", {"include_tasks": True})

    structured = _structured(tree)
    assert {node["id"] for node in structured["nodes"]} == {
        seeded["domain"]["id"],
        seeded["project"]["id"],
    }
    assert structured["truncated"] is False
    [task] = structured["tasks"]
    assert task["id"] == seeded["task"]["id"]
    assert task["parent_id"] == seeded["project"]["id"]
    assert task["title"] == "Plant beans"
    assert task["status"] == seeded["task"]["status"]
    assert task["version"] == seeded["task"]["version"]
    assert task["due_at"] is None
    assert [(step["id"], step["title"]) for step in task["steps"]] == [
        (seeded["steps"][0]["id"], "Buy seeds"),
        (seeded["steps"][1]["id"], "Sow rows"),
    ]
    assert set(task["steps"][0]) == {"id", "title", "status"}

    summary = _summary(tree)
    lines = summary.splitlines()
    # Line 1 is the voice sentence: counts and names, no ids.
    assert lines[0].startswith("Found 1 domain, 1 project, 1 task and 2 steps: ")
    assert seeded["task"]["id"] not in lines[0]
    # Nesting: the Project at depth 1 (two spaces), its Task at depth 2, its Steps at depth 3.
    assert f"\n  - {seeded['project']['id']} v1 | Garden | project |" in summary
    assert f"\n    - {seeded['task']['id']} v1 | Plant beans | task |" in summary
    assert f"\n      - {seeded['steps'][0]['id']} | Buy seeds | step |" in summary
    assert f"\n      - {seeded['steps'][1]['id']} | Sow rows | step |" in summary
    assert lines[-1] == CARD_NOTE


@pytest.mark.asyncio
@pytest.mark.integration
async def test_default_call_has_no_tasks_key() -> None:
    container, owner, _ = _setup()
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        await _seed_tree(client, "tree-default")

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        tree = await client.call_tool("get_work_hierarchy", {})
    assert "tasks" not in _structured(tree)
    assert _structured(tree)["truncated"] is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_include_tasks_never_shows_another_owners_tasks_or_steps() -> None:
    container, owner, other = _setup()
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        mine = await _seed_tree(client, "scope-mine")
    async with Client(_server_for(container, Actor(other, WRITE_SCOPES))) as client:
        theirs = await _seed_tree(client, "scope-theirs")
        await client.call_tool(
            "create_task",
            {"title": "Other secret task", "idempotency_key": "scope-other-secret"},
        )

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        tree = await client.call_tool("get_work_hierarchy", {"include_tasks": True})

    task_ids = [task["id"] for task in _structured(tree)["tasks"]]
    assert task_ids == [mine["task"]["id"]]
    step_ids = [step["id"] for task in _structured(tree)["tasks"] for step in task["steps"]]
    assert step_ids == [step["id"] for step in mine["steps"]]
    rendered = str(_structured(tree))
    assert theirs["task"]["id"] not in rendered
    assert theirs["project"]["id"] not in rendered
    assert "Other secret task" not in rendered
    assert "owner_id" not in rendered


@pytest.mark.asyncio
@pytest.mark.integration
async def test_include_tasks_requires_tasks_read_as_well_as_projects_read() -> None:
    container, owner, _ = _setup()
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        await _seed_tree(client, "tree-scope")

    async with Client(_server_for(container, Actor(owner, frozenset({"projects:read"})))) as client:
        denied = await client.call_tool(
            "get_work_hierarchy", {"include_tasks": True}, raise_on_error=False
        )
        allowed = await client.call_tool("get_work_hierarchy", {})
    assert denied.is_error and _structured(denied)["code"] == "forbidden"
    assert _structured(allowed)["truncated"] is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_include_tasks_caps_steps_per_task_and_reports_truncation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(work_module, "_HIERARCHY_STEP_LIMIT", 2)
    container, owner, _ = _setup()
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        seeded = await _seed_tree(client, "tree-step-cap")
        await client.call_tool(
            "create_task_step",
            {
                "task_id": seeded["task"]["id"],
                "title": "Water daily",
                "idempotency_key": "tree-step-cap-extra",
            },
        )

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        capped = await client.call_tool("get_work_hierarchy", {"include_tasks": True})
    structured = _structured(capped)
    [task] = structured["tasks"]
    assert [step["title"] for step in task["steps"]] == ["Buy seeds", "Sow rows"]
    assert structured["truncated"] is True
    assert "Found 1 domain, 1 project, 1 task and 2 steps: " in _summary(capped)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_include_tasks_caps_task_count_and_reports_truncation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(work_module, "_HIERARCHY_TASK_LIMIT", 1)
    container, owner, _ = _setup()
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        seeded = await _seed_tree(client, "tree-task-cap")
        await client.call_tool(
            "create_task",
            {
                "title": "Second task",
                "project_id": seeded["project"]["id"],
                "idempotency_key": "tree-task-cap-extra",
            },
        )

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        capped = await client.call_tool("get_work_hierarchy", {"include_tasks": True})
        monkeypatch.setattr(work_module, "_HIERARCHY_TASK_LIMIT", 200)
        roomy = await client.call_tool("get_work_hierarchy", {"include_tasks": True})
    assert len(_structured(capped)["tasks"]) == 1
    assert _structured(capped)["truncated"] is True
    assert len(_structured(roomy)["tasks"]) == 2
    assert _structured(roomy)["truncated"] is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_include_tasks_leaves_out_tasks_whose_project_is_not_on_the_page() -> None:
    container, owner, _ = _setup()
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        await _seed_tree(client, "tree-page")

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        cut = await client.call_tool("get_work_hierarchy", {"limit": 1, "include_tasks": True})
    # Limit 1 keeps only the Domain, so the Project's Task is left out and the cut is reported.
    assert [node["kind"] for node in _structured(cut)["nodes"]] == ["domain"]
    assert _structured(cut)["tasks"] == []
    assert _structured(cut)["truncated"] is True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_include_tasks_leaves_out_archived_steps() -> None:
    container, owner, _ = _setup()
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        seeded = await _seed_tree(client, "tree-archive")
        archived_step = seeded["steps"][0]
        await client.call_tool(
            "archive_task_step",
            {
                "step_id": archived_step["id"],
                "version": archived_step["version"],
                "idempotency_key": "tree-archive-step",
            },
        )

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        tree = await client.call_tool("get_work_hierarchy", {"include_tasks": True})
    [task] = _structured(tree)["tasks"]
    assert [step["id"] for step in task["steps"]] == [seeded["steps"][1]["id"]]


async def _seed_process_with_task(client: Client[Any], key: str, domain_id: str) -> dict[str, Any]:
    """One Process under the Domain, with one Task filed under it."""

    process = _structured(
        await client.call_tool(
            "create_process",
            {"domain_id": domain_id, "name": "Weekly", "idempotency_key": f"{key}-process"},
        )
    )["process"]
    task = _structured(
        await client.call_tool(
            "create_task",
            {
                "title": "Water the plants",
                "process_id": process["id"],
                "idempotency_key": f"{key}-process-task",
            },
        )
    )["task"]
    return {"process": process, "task": task}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_process_id_lists_only_that_processs_tasks() -> None:
    container, owner, _ = _setup()
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        seeded = await _seed_tree(client, "tree-process")
        filed = await _seed_process_with_task(client, "tree-process", seeded["domain"]["id"])

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        everything = await client.call_tool("get_work_hierarchy", {"include_tasks": True})
        narrowed = await client.call_tool(
            "get_work_hierarchy",
            {"include_tasks": True, "process_id": filed["process"]["id"]},
        )
    assert {task["id"] for task in _structured(everything)["tasks"]} == {
        seeded["task"]["id"],
        filed["task"]["id"],
    }
    [task] = _structured(narrowed)["tasks"]
    assert task["id"] == filed["task"]["id"]
    assert task["parent_id"] == filed["process"]["id"]
    # Only that Process's node comes back, not the whole node page, and no next page.
    narrowed_structured = _structured(narrowed)
    [node] = narrowed_structured["nodes"]
    assert node["kind"] == "process"
    assert node["id"] == filed["process"]["id"]
    assert node["parent_id"] == seeded["domain"]["id"]
    assert narrowed_structured["next_cursor"] is None
    assert narrowed_structured["truncated"] is False
    assert len(_structured(everything)["nodes"]) > 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_process_id_is_refused_without_include_tasks() -> None:
    container, owner, _ = _setup()
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        seeded = await _seed_tree(client, "tree-process-flag")
        filed = await _seed_process_with_task(client, "tree-process-flag", seeded["domain"]["id"])

        refused = await client.call_tool(
            "get_work_hierarchy",
            {"process_id": filed["process"]["id"]},
            raise_on_error=False,
        )
    assert refused.is_error


@pytest.mark.asyncio
@pytest.mark.integration
async def test_process_id_of_another_owner_is_not_found_and_shows_nothing_of_theirs() -> None:
    container, owner, other = _setup()
    async with Client(_server_for(container, Actor(other, WRITE_SCOPES))) as client:
        theirs = await _seed_tree(client, "tree-process-theirs")
        their_process = await _seed_process_with_task(
            client, "tree-process-theirs", theirs["domain"]["id"]
        )

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        denied = await client.call_tool(
            "get_work_hierarchy",
            {"include_tasks": True, "process_id": their_process["process"]["id"]},
            raise_on_error=False,
        )
    assert denied.is_error and _structured(denied)["code"] == "not_found"
    assert "Water the plants" not in str(denied)
