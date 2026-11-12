"""create_tasks: 1 to 20 Tasks with ordered Steps in one atomic, retry-safe call.

A whiteboard with six notes becomes the Tasks of one Domain in one call. Twenty-one items are
refused by the MCP schema and by the service before any write. A failing item rolls back every
Task and Step of the batch, and a repeated idempotency key returns the same Tasks.
"""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import TextContent

from sidekick.api.app import Container, create_container
from sidekick.mcp.batch_tasks import register_batch_task_tools
from sidekick.mcp.instrument import instrument_mcp
from sidekick.mcp.tool_context import ToolContext
from sidekick.shared.errors import ValidationError
from sidekick.shared.types import Actor
from sidekick.tasks.application.service import MAX_BATCH_CREATE_TASKS, NewTaskItem
from sidekick.tasks.domain import Priority
from tests.db import database_factory
from tests.support.settings import make_settings

SCOPES = frozenset({"tasks:read", "tasks:write", "projects:read", "projects:write"})


def _setup() -> tuple[Container, Actor]:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("batch-owner", "Batch Owner")
    return container, Actor(owner, SCOPES)


def _server(container: Container, actor: Actor) -> FastMCP:
    mcp = FastMCP("create-tasks-test")
    register_batch_task_tools(
        mcp, ToolContext(container, lambda: actor, lambda name: instrument_mcp(container, name))
    )
    return mcp


def _item(title: str, **extra: Any) -> dict[str, Any]:
    return {"title": title, **extra}


async def _create(client: Client[Any], tasks: list[dict[str, Any]], key: str, **extra: Any) -> Any:
    return await client.call_tool(
        "create_tasks",
        {"tasks": tasks, "idempotency_key": key, **extra},
        raise_on_error=False,
    )


def _text_lines(result: Any) -> list[str]:
    block = result.content[0]
    assert isinstance(block, TextContent)
    return block.text.splitlines()


def _domain(container: Container, actor: Actor) -> Any:
    return container.contexts.create_domain(
        actor, name="Arbete", description=None, idempotency_key=f"domain-{uuid4().hex}"
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_whiteboard_notes_become_tasks_with_ordered_steps_in_one_call() -> None:
    container, actor = _setup()
    domain = _domain(container, actor)
    notes = [_item(f"Lapp {number}") for number in range(1, 6)]
    notes.append(
        _item(
            "Lapp 6",
            steps=["Skiss", "Utkast", "Klart"],
            tags=["Projekt"],
            due_at="2026-11-06",
        )
    )

    async with Client(_server(container, actor)) as client:
        created = await _create(client, notes, "whiteboard-1", domain_id=str(domain.id))

    assert not created.is_error, created.structured_content
    assert created.structured_content is not None
    assert created.structured_content["count"] == 6
    last = created.structured_content["tasks"][5]
    assert last["title"] == "Lapp 6"
    assert last["tags"] == ["projekt"]
    assert last["domain_id"] == str(domain.id)
    assert datetime.fromisoformat(last["due_at"]) == datetime(
        2026, 11, 6, 23, 59, tzinfo=container.settings.owner_zone
    )
    assert [step["title"] for step in last["steps"]] == ["Skiss", "Utkast", "Klart"]
    assert [step["position"] for step in last["steps"]] == [0, 1, 2]

    stored_steps = container.steps.list_steps(actor, UUID(last["id"])).items
    assert [step.title for step in stored_steps] == ["Skiss", "Utkast", "Klart"]

    lines = _text_lines(created)
    assert lines[0] == "Created 6 tasks in Arbete."
    assert len(lines) == 7
    assert f"{last['id']} v{last['version']}: Lapp 6" in lines[6]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_twenty_one_items_and_an_empty_list_are_refused_before_any_write() -> None:
    container, actor = _setup()
    too_many = [_item(f"Post {number}") for number in range(MAX_BATCH_CREATE_TASKS + 1)]

    async with Client(_server(container, actor)) as client:
        with pytest.raises(ToolError):
            await client.call_tool(
                "create_tasks",
                {"tasks": too_many, "idempotency_key": "batch-too-many-1"},
            )
        with pytest.raises(ToolError):
            await client.call_tool(
                "create_tasks",
                {"tasks": [], "idempotency_key": "batch-empty-1"},
            )

    service_items = [
        NewTaskItem(
            title=f"Post {number}",
            due_at=None,
            priority=Priority.NORMAL,
            tags=(),
            step_titles=(),
        )
        for number in range(MAX_BATCH_CREATE_TASKS + 1)
    ]
    with pytest.raises(ValidationError):
        container.tasks.create_batch(actor, service_items, idempotency_key="batch-service-21")

    assert container.tasks.list(actor, limit=100).items == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_repeating_the_key_returns_the_same_tasks_without_new_rows() -> None:
    container, actor = _setup()
    notes = [_item("Ett", steps=["A"]), _item("Två")]

    async with Client(_server(container, actor)) as client:
        first = await _create(client, notes, "whiteboard-repeat-1")
        second = await _create(client, notes, "whiteboard-repeat-1")

    assert not first.is_error, first.structured_content
    assert not second.is_error, second.structured_content
    assert second.structured_content == first.structured_content
    assert len(container.tasks.list(actor, limit=100).items) == 2


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_failing_item_rolls_back_every_task_and_step_of_the_batch() -> None:
    container, actor = _setup()
    notes = [
        _item("Ett", steps=["A", "B"]),
        _item("Två", steps=["C"]),
        # A tag with no visible character normalises to an empty slug, which the service refuses
        # after the first two items were written.
        _item("Trasig", steps=["D"], tags=["   "]),
    ]

    async with Client(_server(container, actor)) as client:
        failed = await _create(client, notes, "whiteboard-fail-1")

    assert failed.is_error
    assert failed.structured_content is not None
    assert failed.structured_content["code"] == "validation_error"
    assert container.tasks.list(actor, limit=100).items == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_image_data_in_a_title_or_step_is_refused_before_any_write() -> None:
    container, actor = _setup()
    image = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"

    async with Client(_server(container, actor)) as client:
        in_title = await client.call_tool(
            "create_tasks",
            {
                "tasks": [_item(image)],
                "idempotency_key": "batch-image-title-1",
            },
            raise_on_error=False,
        )
        in_step = await client.call_tool(
            "create_tasks",
            {
                "tasks": [_item("Ren", steps=[image])],
                "idempotency_key": "batch-image-step-1",
            },
            raise_on_error=False,
        )

    assert in_title.is_error
    assert in_step.is_error
    assert container.tasks.list(actor, limit=100).items == []
