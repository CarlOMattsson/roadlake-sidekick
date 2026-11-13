"""get_contact_context reports how many of each linked Project's Tasks are completed."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from fastmcp import Client, FastMCP
from fastmcp.client.client import CallToolResult
from sqlalchemy import update

from sidekick.api.app import Container, create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.persistence.models import TaskRow
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings

SCOPES = frozenset(
    {
        "contacts:read",
        "contacts:write",
        "projects:read",
        "projects:write",
        "tasks:read",
        "tasks:write",
    }
)


def _server(container: Container, owner: UUID, scopes: frozenset[str] = SCOPES) -> FastMCP:
    actor = Actor(owner, scopes)
    return create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)


async def _contact(client: Client, name: str) -> str:
    created = await client.call_tool(
        "create_contact", {"display_name": name, "idempotency_key": f"progress-contact-{name}"}
    )
    return created.structured_content["contact"]["id"]


async def _linked_project(client: Client, title: str, contact_id: str) -> str:
    domain = await client.call_tool(
        "create_domain", {"name": f"Domain {title}", "idempotency_key": f"progress-domain-{title}"}
    )
    created = await client.call_tool(
        "create_project",
        {
            "title": title,
            "domain_id": domain.structured_content["domain"]["id"],
            "idempotency_key": f"progress-project-{title}",
        },
    )
    project_id = created.structured_content["project"]["id"]
    await client.call_tool(
        "link_contact_to_project",
        {
            "contact_id": contact_id,
            "project_id": project_id,
            "idempotency_key": f"progress-link-{title}",
        },
    )
    return project_id


async def _task(
    client: Client, project_id: str, title: str, *, done: bool = False
) -> dict[str, Any]:
    created = await client.call_tool(
        "create_task",
        {"title": title, "project_id": project_id, "idempotency_key": f"progress-task-{title}"},
    )
    task = created.structured_content["task"]
    if done:
        completed = await client.call_tool(
            "complete_task",
            {
                "task_id": task["id"],
                "version": task["version"],
                "idempotency_key": f"progress-done-{title}",
            },
        )
        task = completed.structured_content["task"]
    return task


def _progress(context: CallToolResult, project_id: str) -> tuple[int, int]:
    (row,) = [p for p in context.structured_content["projects"]["items"] if p["id"] == project_id]
    return row["tasks_done"], row["tasks_total"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_context_counts_done_and_total_tasks_per_project_and_zero_for_none() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")

    async with Client(_server(container, owner)) as client:
        contact_id = await _contact(client, "Anna")
        busy = await _linked_project(client, "Busy", contact_id)
        empty = await _linked_project(client, "Empty", contact_id)
        await _task(client, busy, "one", done=True)
        await _task(client, busy, "two", done=True)
        for title in ("three", "four", "five"):
            await _task(client, busy, title)
        context = await client.call_tool("get_contact_context", {"contact_id": contact_id})

    assert _progress(context, busy) == (2, 5)
    assert _progress(context, empty) == (0, 0)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_context_leaves_archived_and_trashed_tasks_out_of_the_counts() -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    owner = container.auth.provision_user("owner", "Owner")

    async with Client(_server(container, owner)) as client:
        contact_id = await _contact(client, "Bo")
        project = await _linked_project(client, "Cleaned", contact_id)
        await _task(client, project, "kept", done=True)
        await _task(client, project, "open")
        archived = await _task(client, project, "archived", done=True)
        trashed = await _task(client, project, "trashed", done=True)
        await client.call_tool(
            "move_to_trash",
            {
                "kind": "task",
                "record_id": trashed["id"],
                "version": trashed["version"],
                "idempotency_key": "progress-trash",
            },
        )
        with factory() as session, session.begin():
            session.execute(
                update(TaskRow)
                .where(TaskRow.id == UUID(archived["id"]))
                .values(archived_at=datetime.now(UTC))
            )
        context = await client.call_tool("get_contact_context", {"contact_id": contact_id})

    assert _progress(context, project) == (1, 2)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_context_keeps_another_owners_projects_and_counts_out_and_needs_tasks_read() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    other = container.auth.provision_user("other-owner", "Other")

    async with Client(_server(container, other)) as client:
        foreign_contact = await _contact(client, "Främling")
        foreign_project = await _linked_project(client, "Foreign", foreign_contact)
        await _task(client, foreign_project, "theirs", done=True)

    async with Client(_server(container, owner)) as client:
        contact_id = await _contact(client, "Cecilia")
        project = await _linked_project(client, "Mine", contact_id)
        await _task(client, project, "mine")
        context = await client.call_tool("get_contact_context", {"contact_id": contact_id})
        foreign = await client.call_tool(
            "get_contact_context", {"contact_id": foreign_contact}, raise_on_error=False
        )

    assert _progress(context, project) == (0, 1)
    assert foreign_project not in str(context.structured_content)
    assert foreign.is_error
    assert foreign.structured_content["code"] == "not_found"
    assert "tasks_total" not in str(foreign.structured_content)

    # Without tasks:read the whole context is refused, so no count leaks.
    async with Client(
        _server(container, owner, frozenset({"contacts:read", "projects:read"}))
    ) as c:
        refused = await c.call_tool(
            "get_contact_context", {"contact_id": contact_id}, raise_on_error=False
        )
    assert refused.is_error
    assert "tasks_total" not in str(refused.structured_content)
