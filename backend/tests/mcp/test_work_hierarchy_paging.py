"""get_work_hierarchy pages through nodes of every kind with a cursor, owner-scoped.

Nodes come Domains first, then Processes, then Projects. A page may end in the middle of a kind
or exactly at a kind boundary; the cursor continues from there, and no node is lost or repeated.
"""

from typing import Any

import pytest
from fastmcp import Client, FastMCP

from sidekick.api.app import Container, create_container
from sidekick.mcp.server import create_mcp_server
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


async def _seed(client: Client[Any], key: str, *, domains: int, per_domain: int) -> list[str]:
    """`domains` Domains, each with `per_domain` Processes and Projects; returns all node ids."""

    ids: list[str] = []
    for d in range(domains):
        domain = _structured(
            await client.call_tool(
                "create_domain", {"name": f"Domain {d}", "idempotency_key": f"{key}-d{d}"}
            )
        )["domain"]
        ids.append(domain["id"])
        for n in range(per_domain):
            process = _structured(
                await client.call_tool(
                    "create_process",
                    {
                        "domain_id": domain["id"],
                        "name": f"Process {d}.{n}",
                        "idempotency_key": f"{key}-pr{d}-{n}",
                    },
                )
            )["process"]
            project = _structured(
                await client.call_tool(
                    "create_project",
                    {
                        "domain_id": domain["id"],
                        "title": f"Project {d}.{n}",
                        "idempotency_key": f"{key}-pj{d}-{n}",
                    },
                )
            )["project"]
            ids.extend([process["id"], project["id"]])
    return ids


async def _pages(client: Client[Any], limit: int) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(50):
        args: dict[str, Any] = {"limit": limit}
        if cursor is not None:
            args["cursor"] = cursor
        page = _structured(await client.call_tool("get_work_hierarchy", args))
        pages.append(page)
        cursor = page["next_cursor"]
        if cursor is None:
            return pages
    raise AssertionError("the cursor never ended")


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("limit", [1, 2, 3, 4, 5])
async def test_cursor_returns_every_node_of_mixed_kinds_once_across_page_boundaries(
    limit: int,
) -> None:
    # 2 Domains + 4 Processes + 4 Projects = 10 nodes, so limits 1-5 cut in and between kinds.
    container, owner, _ = _setup()
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        seeded = await _seed(client, f"page-{limit}", domains=2, per_domain=2)

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        pages = await _pages(client, limit)

    nodes = [node for page in pages for node in page["nodes"]]
    assert sorted(node["id"] for node in nodes) == sorted(seeded)
    assert len({node["id"] for node in nodes}) == len(seeded)
    kinds = [node["kind"] for node in nodes]
    assert kinds == ["domain"] * 2 + ["process"] * 4 + ["project"] * 4
    assert all(len(page["nodes"]) <= limit for page in pages)
    for page in pages[:-1]:
        assert page["truncated"] is True and page["next_cursor"] is not None
    assert pages[-1]["truncated"] is False and pages[-1]["next_cursor"] is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_without_cursor_and_with_room_the_result_is_unchanged() -> None:
    container, owner, _ = _setup()
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        seeded = await _seed(client, "compat-page", domains=1, per_domain=1)

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        whole = _structured(await client.call_tool("get_work_hierarchy", {}))
        exact = _structured(await client.call_tool("get_work_hierarchy", {"limit": 3}))
    assert {node["id"] for node in whole["nodes"]} == set(seeded)
    assert whole["truncated"] is False and whole["next_cursor"] is None
    assert exact["truncated"] is False and exact["next_cursor"] is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_cut_result_says_how_to_get_the_rest_in_text_too() -> None:
    container, owner, _ = _setup()
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        await _seed(client, "text-card", domains=1, per_domain=1)

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        cut = await client.call_tool("get_work_hierarchy", {"limit": 1})
    assert "cursor=next_cursor" in cut.content[0].text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_include_tasks_on_a_later_page_shows_the_tasks_of_that_pages_projects() -> None:
    container, owner, _ = _setup()
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        domain = _structured(
            await client.call_tool(
                "create_domain", {"name": "Home", "idempotency_key": "tasks-page-domain"}
            )
        )["domain"]
        project = _structured(
            await client.call_tool(
                "create_project",
                {
                    "domain_id": domain["id"],
                    "title": "Garden",
                    "idempotency_key": "tasks-page-project",
                },
            )
        )["project"]
        task = _structured(
            await client.call_tool(
                "create_task",
                {
                    "title": "Plant",
                    "project_id": project["id"],
                    "idempotency_key": "tasks-page-task",
                },
            )
        )["task"]

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        first = _structured(
            await client.call_tool("get_work_hierarchy", {"limit": 1, "include_tasks": True})
        )
        second = _structured(
            await client.call_tool(
                "get_work_hierarchy",
                {"limit": 1, "include_tasks": True, "cursor": first["next_cursor"]},
            )
        )
    assert first["tasks"] == [] and first["next_cursor"] is not None
    assert [node["id"] for node in second["nodes"]] == [project["id"]]
    assert [item["id"] for item in second["tasks"]] == [task["id"]]
    assert second["next_cursor"] is None and second["truncated"] is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_foreign_or_tampered_cursor_is_refused_and_leaks_nothing() -> None:
    container, owner, other = _setup()
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        await _seed(client, "mine-owner", domains=2, per_domain=0)
    async with Client(_server_for(container, Actor(other, WRITE_SCOPES))) as client:
        await _seed(client, "theirs-other", domains=2, per_domain=0)

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        cursor = _structured(await client.call_tool("get_work_hierarchy", {"limit": 1}))[
            "next_cursor"
        ]
    async with Client(_server_for(container, Actor(other, READ_SCOPES))) as client:
        foreign = await client.call_tool(
            "get_work_hierarchy", {"cursor": cursor}, raise_on_error=False
        )
        garbage = await client.call_tool(
            "get_work_hierarchy", {"cursor": "not-a-cursor"}, raise_on_error=False
        )
    for refused in (foreign, garbage):
        assert refused.is_error and _structured(refused)["code"] == "validation_error"
        assert "Domain" not in str(_structured(refused))


@pytest.mark.asyncio
@pytest.mark.integration
async def test_cursor_does_not_bypass_the_projects_read_scope() -> None:
    container, owner, _ = _setup()
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        await _seed(client, "scope-page", domains=2, per_domain=0)
    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        cursor = _structured(await client.call_tool("get_work_hierarchy", {"limit": 1}))[
            "next_cursor"
        ]
    async with Client(_server_for(container, Actor(owner, frozenset({"tasks:read"})))) as client:
        denied = await client.call_tool(
            "get_work_hierarchy", {"cursor": cursor}, raise_on_error=False
        )
    assert denied.is_error and _structured(denied)["code"] == "forbidden"
