"""Model-facing text of the Work record cards: get_task, get_project and get_work_hierarchy.

These tools open the Work app card, so each returns one text block (no JSON block): line 1 is the
voice sentence with titles and no ids, the id lines follow so the model can make a follow-up call,
and the last line tells the model the card shows the record. structuredContent is unchanged.

The inline-summary counts ride the same records: get_task carries its Project title and Step counts,
get_project its Task counts (done, total, overdue). Each count is one owner-scoped aggregate read,
and archived Steps are left out.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastmcp import Client, FastMCP

from sidekick.api.app import Container, create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.mcp.text import CARD_NOTE, MAX_ROWS, RECORD_CARD_NOTE
from sidekick.mcp.work_text import hierarchy_card_text, record_card_text
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings

SCOPES = frozenset({"projects:read", "projects:write", "tasks:read", "tasks:write"})
PAST = datetime(2020, 1, 1, tzinfo=UTC)


def _server_for(container: Container, actor: Actor) -> FastMCP:
    return create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)


def _structured(tool_result: Any) -> dict[str, Any]:
    assert tool_result.structured_content is not None
    structured: dict[str, Any] = tool_result.structured_content
    return structured


def _single_text(tool_result: Any) -> str:
    """The card's one text block: the voice sentence, the id lines and the card note."""

    assert len(tool_result.content) == 1, "expected one text block; the card carries the rest"
    text: str = tool_result.content[0].text
    return text


def _setup() -> tuple[Container, Any]:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    return container, owner


LONG_DESCRIPTION = "Lång " * 400


async def _seed(client: Client[Any], key: str) -> dict[str, Any]:
    """One Domain, one Project with a long description, and one Task under it.

    The Task has a two-line description, a tag, an estimate and two Steps, the first completed.
    """

    domain = _structured(
        await client.call_tool("create_domain", {"name": "Home", "idempotency_key": f"{key}-d"})
    )["domain"]
    project = _structured(
        await client.call_tool(
            "create_project",
            {
                "domain_id": domain["id"],
                "title": "Garden",
                "description": LONG_DESCRIPTION,
                "idempotency_key": f"{key}-p",
            },
        )
    )["project"]
    task = _structured(
        await client.call_tool(
            "create_task",
            {
                "title": "Plant beans",
                "project_id": project["id"],
                "description": "Köp frön.\nSå bönorna i raderna.",
                "tags": ["hushall"],
                "estimated_minutes": 30,
                "idempotency_key": f"{key}-t",
            },
        )
    )["task"]
    steps: list[dict[str, Any]] = []
    for index, title in enumerate(["Buy seeds", "Sow rows"]):
        step = _structured(
            await client.call_tool(
                "create_task_step",
                {"task_id": task["id"], "title": title, "idempotency_key": f"{key}-step-{index}"},
            )
        )["step"]
        steps.append(step)
    completed = await client.call_tool(
        "complete_task_step",
        {
            "step_id": steps[0]["id"],
            "version": steps[0]["version"],
            "idempotency_key": f"{key}-step-done",
        },
    )
    assert completed.structured_content is not None
    return {"domain": domain, "project": project, "task": task, "steps": steps}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_task_card_text_is_one_block_with_the_id_after_line_one() -> None:
    container, owner = _setup()
    async with Client(_server_for(container, Actor(owner, SCOPES))) as client:
        seeded = await _seed(client, "card-task")
        read = await client.call_tool("get_task", {"task_id": seeded["task"]["id"]})

    lines = _single_text(read).splitlines()
    assert lines[0].startswith("Task Plant beans: ")
    assert seeded["task"]["id"] not in lines[0]
    assert lines[1] == (
        f"{seeded['task']['id']} v{seeded['task']['version']}: Plant beans "
        f"in project {seeded['project']['id']}"
    )
    assert lines[-1] == RECORD_CARD_NOTE
    assert "Description: Köp frön. Så bönorna i raderna." in lines
    assert "Tags: hushall." in lines
    assert "Estimate: 30 min." in lines
    assert "Steps: 1 of 2 done." in lines
    assert "- Buy seeds | completed" in lines
    assert "- Sow rows | to do" in lines
    assert _structured(read)["task"]["id"] == seeded["task"]["id"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_project_card_text_is_one_block_with_the_id_after_line_one() -> None:
    container, owner = _setup()
    async with Client(_server_for(container, Actor(owner, SCOPES))) as client:
        seeded = await _seed(client, "card-project")
        read = await client.call_tool("get_project", {"project_id": seeded["project"]["id"]})

    lines = _single_text(read).splitlines()
    assert lines[0].startswith("Project Garden: ")
    assert seeded["project"]["id"] not in lines[0]
    assert lines[1] == (
        f"{seeded['project']['id']} v{seeded['project']['version']}: Garden "
        f"in domain {seeded['domain']['id']}"
    )
    assert lines[-1] == RECORD_CARD_NOTE
    collapsed = " ".join(LONG_DESCRIPTION.split())
    assert f"Description: {collapsed[:1499]}…" in lines
    assert "Estimate: 30 min over 1 open task, 0 unestimated." in lines
    assert _structured(read)["project"]["id"] == seeded["project"]["id"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_default_hierarchy_card_text_names_nodes_on_line_one_and_ids_below() -> None:
    container, owner = _setup()
    async with Client(_server_for(container, Actor(owner, SCOPES))) as client:
        seeded = await _seed(client, "card-tree")
        tree = await client.call_tool("get_work_hierarchy", {})

    text = _single_text(tree)
    lines = text.splitlines()
    assert lines[0] == "Found 1 domain and 1 project: Home and Garden."
    assert seeded["domain"]["id"] not in lines[0]
    domain_row = f"- {seeded['domain']['id']} v{seeded['domain']['version']} | Home | domain | "
    assert domain_row in text
    assert f"\n  - {seeded['project']['id']} v{seeded['project']['version']} | Garden | " in text
    assert lines[-1] == CARD_NOTE
    assert len(_structured(tree)["nodes"]) == 2


def test_record_card_text_puts_the_sentence_first_then_ids_details_and_the_note_last() -> None:
    text = record_card_text(
        "Task Köp färg: to do, no due date.",
        "t1 v1: Köp färg in project p1",
        ["Description: Ett rum.", "Tags: hem."],
    )

    assert text == (
        "Task Köp färg: to do, no due date.\n"
        "t1 v1: Köp färg in project p1\n"
        "Description: Ett rum.\n"
        "Tags: hem.\n"
        f"{RECORD_CARD_NOTE}"
    )


def test_hierarchy_card_text_indents_by_level_and_counts_rows_past_the_limit() -> None:
    nodes = [
        {"id": f"n{number}", "version": 1, "title": f"Node {number}", "kind": "project"}
        for number in range(MAX_ROWS + 2)
    ]
    indents = [0, 1, *([0] * MAX_ROWS)]

    lines = hierarchy_card_text(nodes, indents).splitlines()

    assert lines[0] == "- n0 v1 | Node 0 | project"
    assert lines[1] == "  - n1 v1 | Node 1 | project"
    assert len([line for line in lines if line.lstrip().startswith("- ")]) == MAX_ROWS
    assert lines[-2] == "… 2 more"
    assert lines[-1] == CARD_NOTE


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def _key() -> str:
    return f"card-{uuid4().hex}"


def _project(container: Container, actor: Actor, *, title: str = "Cards project") -> Any:
    domain = container.contexts.create_domain(
        actor, name="Cards domain", description=None, idempotency_key=_key()
    )
    return container.projects.create(
        actor, title=title, domain_id=domain.id, idempotency_key=_key()
    )


def _task(
    container: Container,
    actor: Actor,
    *,
    title: str = "Cards task",
    project_id: Any = None,
    due_at: datetime | None = None,
) -> Any:
    return container.tasks.create(
        actor, title=title, project_id=project_id, due_at=due_at, idempotency_key=_key()
    )


async def _read(container: Container, actor: Actor, name: str, arguments: dict[str, str]) -> Any:
    async with Client(_server_for(container, actor)) as client:
        return await client.call_tool(name, arguments, raise_on_error=False)


@pytest.mark.asyncio
async def test_discovery_declares_the_card_fields() -> None:
    server = create_mcp_server(create_container(make_settings()), enable_auth=False)
    tools = {tool.name: tool for tool in await server.list_tools()}

    task_schema = tools["get_task"].output_schema
    project_schema = tools["get_project"].output_schema
    assert task_schema is not None
    assert project_schema is not None
    task_fields: dict[str, Any] = task_schema["properties"]["task"]["properties"]
    assert {"project_title", "steps_done", "steps_total"} <= set(task_fields)
    assert task_fields["steps_done"]["type"] == "integer"
    project_fields: dict[str, Any] = project_schema["properties"]["project"]["properties"]
    assert {"tasks_done", "tasks_total", "tasks_overdue"} <= set(project_fields)
    assert project_fields["tasks_overdue"]["type"] == "integer"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_task_carries_project_title_and_step_counts() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user(_name("task-card"), "Owner")
    actor = Actor(owner, SCOPES)
    project = _project(container, actor)
    task = _task(container, actor, project_id=project.id)
    first = container.steps.create_step(actor, task.id, title="First", idempotency_key=_key())
    container.steps.create_step(actor, task.id, title="Second", idempotency_key=_key())
    container.steps.complete_step(actor, first.id, version=first.version, idempotency_key=_key())

    response = await _read(container, actor, "get_task", {"task_id": str(task.id)})

    assert not response.is_error, response.structured_content
    record = response.structured_content["task"]
    assert record["project_title"] == "Cards project"
    assert record["steps_done"] == 1
    assert record["steps_total"] == 2
    # The fields the card already read are unchanged.
    assert record["title"] == "Cards task"
    assert record["version"] == task.version
    assert record["project_id"] == str(project.id)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_archived_steps_are_left_out_of_the_step_counts() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user(_name("task-archive"), "Owner")
    actor = Actor(owner, SCOPES)
    task = _task(container, actor)
    container.steps.create_step(actor, task.id, title="Kept", idempotency_key=_key())
    archived = container.steps.create_step(actor, task.id, title="Archived", idempotency_key=_key())
    container.steps.archive_step(
        actor, archived.id, version=archived.version, idempotency_key=_key()
    )

    response = await _read(container, actor, "get_task", {"task_id": str(task.id)})

    assert not response.is_error, response.structured_content
    record = response.structured_content["task"]
    assert record["steps_total"] == 1
    assert record["steps_done"] == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_task_without_a_project_has_no_project_title_and_no_steps() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user(_name("task-bare"), "Owner")
    actor = Actor(owner, SCOPES)
    task = _task(container, actor)

    response = await _read(container, actor, "get_task", {"task_id": str(task.id)})

    assert not response.is_error, response.structured_content
    record = response.structured_content["task"]
    assert record["project_title"] is None
    assert record["steps_done"] == 0
    assert record["steps_total"] == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_task_clips_a_long_project_title_like_the_work_lists() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user(_name("task-clip"), "Owner")
    actor = Actor(owner, SCOPES)
    project = _project(container, actor, title="P" * 150)
    task = _task(container, actor, project_id=project.id)

    response = await _read(container, actor, "get_task", {"task_id": str(task.id)})

    assert not response.is_error, response.structured_content
    assert response.structured_content["task"]["project_title"] == "P" * 119 + "…"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_project_counts_done_total_and_overdue_tasks() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user(_name("project-counts"), "Owner")
    actor = Actor(owner, SCOPES)
    project = _project(container, actor)
    other_project = _project(container, actor, title="Other project")

    done = _task(container, actor, title="Done", project_id=project.id, due_at=PAST)
    container.tasks.complete(actor, done.id, version=done.version, idempotency_key=_key())
    _task(container, actor, title="Late", project_id=project.id, due_at=PAST)
    _task(
        container,
        actor,
        title="Later",
        project_id=project.id,
        due_at=datetime.now(UTC) + timedelta(days=3),
    )
    _task(container, actor, title="Undated", project_id=project.id)
    # A Task of another Project is not counted in this one.
    _task(container, actor, title="Elsewhere", project_id=other_project.id, due_at=PAST)

    response = await _read(container, actor, "get_project", {"project_id": str(project.id)})

    assert not response.is_error, response.structured_content
    record = response.structured_content["project"]
    assert record["tasks_total"] == 4
    assert record["tasks_done"] == 1
    # Overdue: not completed and due before now. The completed Task that was due in the past is not.
    assert record["tasks_overdue"] == 1
    # The fields the card already read are unchanged.
    assert record["title"] == "Cards project"
    assert record["version"] == project.version


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_project_without_tasks_counts_zero() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user(_name("project-empty"), "Owner")
    actor = Actor(owner, SCOPES)
    project = _project(container, actor)

    response = await _read(container, actor, "get_project", {"project_id": str(project.id)})

    assert not response.is_error, response.structured_content
    record = response.structured_content["project"]
    assert record["tasks_total"] == 0
    assert record["tasks_done"] == 0
    assert record["tasks_overdue"] == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_foreign_task_and_project_stay_unreadable_with_the_counts() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user(_name("card-owner"), "Owner")
    other = container.auth.provision_user(_name("card-other"), "Other")
    owner_actor = Actor(owner, SCOPES)
    project = _project(container, owner_actor)
    task = _task(container, owner_actor, project_id=project.id, due_at=PAST)

    other_actor = Actor(other, SCOPES)
    task_response = await _read(container, other_actor, "get_task", {"task_id": str(task.id)})
    project_response = await _read(
        container, other_actor, "get_project", {"project_id": str(project.id)}
    )

    assert task_response.is_error
    assert project_response.is_error
    assert "Cards project" not in str(project_response.structured_content)
    assert "Cards task" not in str(task_response.structured_content)
