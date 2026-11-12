"""MCP Work hierarchy read and saved Work view tools: same use cases as the REST routes.

The hierarchy needs `projects:read`. Saved views need `projects:read` to list and
`projects:write` to change; every call is owner-scoped, versioned, idempotent and closed
over the same filter fields REST allows. Saved views are Work content, not interface
preferences, so no session-only scope is involved.
"""

from typing import Any

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from sidekick.api.app import Container, create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.mcp_logging import (
    _all_logs,  # noqa: F401
    _Collector,
)
from tests.support.settings import make_settings

WRITE_SCOPES = frozenset({"projects:read", "projects:write", "tasks:read", "tasks:write"})
READ_SCOPES = frozenset({"projects:read"})
VIEW = {"view": "agenda", "context": "all", "sort": "due_asc", "tags": ["home"]}
SENTINEL = "sentinel-saved-view-name-4c1e"


def _server_for(container: Container, actor: Actor) -> FastMCP:
    return create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)


def _setup() -> tuple[Container, Any, Any]:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    other = container.auth.provision_user("other-owner", "Other")
    return container, owner, other


def _structured(result: Any) -> dict[str, Any]:
    assert result.structured_content is not None
    structured: dict[str, Any] = result.structured_content
    return structured


async def _create(client: Client, name: str, key: str) -> dict[str, Any]:
    created = await client.call_tool(
        "create_saved_work_view", {"name": name, "definition": VIEW, "idempotency_key": key}
    )
    return created.structured_content["saved_view"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_hierarchy_returns_owned_nodes_and_never_another_owners() -> None:
    container, owner, other = _setup()
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        domain = (
            await client.call_tool(
                "create_domain", {"name": "Home", "idempotency_key": "hier-domain"}
            )
        ).structured_content["domain"]
        project = (
            await client.call_tool(
                "create_project",
                {"domain_id": domain["id"], "title": "Garden", "idempotency_key": "hier-project"},
            )
        ).structured_content["project"]
    async with Client(_server_for(container, Actor(other, WRITE_SCOPES))) as client:
        await client.call_tool(
            "create_domain", {"name": "Other secret", "idempotency_key": "hier-other"}
        )

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        tree = await client.call_tool("get_work_hierarchy", {})
    nodes = {node["id"]: node for node in tree.structured_content["nodes"]}
    assert set(nodes) == {domain["id"], project["id"]}
    assert nodes[domain["id"]]["parent_id"] is None
    assert nodes[project["id"]]["parent_id"] == domain["id"]
    assert nodes[project["id"]]["kind"] == "project"
    assert "Other secret" not in str(tree.structured_content)
    assert "owner_id" not in str(tree.structured_content)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_hierarchy_domain_nodes_carry_their_accent_or_null() -> None:
    container, owner, _other = _setup()
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        teal = await client.call_tool(
            "create_domain",
            {"name": "Jobb", "accent": "teal", "idempotency_key": "hier-accent-teal"},
        )
        plain = await client.call_tool(
            "create_domain", {"name": "Hem", "idempotency_key": "hier-accent-plain"}
        )
        teal_id = teal.structured_content["domain"]["id"]
        plain_id = plain.structured_content["domain"]["id"]

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        tree = await client.call_tool("get_work_hierarchy", {})
    nodes = {node["id"]: node for node in tree.structured_content["nodes"]}
    assert nodes[teal_id]["accent"] == "teal"
    assert nodes[plain_id]["accent"] is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_hierarchy_is_bounded_and_forbidden_without_projects_read() -> None:
    container, owner, _ = _setup()
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        for index in range(3):
            await client.call_tool(
                "create_domain", {"name": f"Domain {index}", "idempotency_key": f"hier-b-{index}"}
            )

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        cut = await client.call_tool("get_work_hierarchy", {"limit": 2})
        with pytest.raises(ToolError):
            await client.call_tool("get_work_hierarchy", {"limit": 101})
        with pytest.raises(ToolError):
            await client.call_tool("get_work_hierarchy", {"limit": 0})
    assert len(cut.structured_content["nodes"]) == 2

    async with Client(_server_for(container, Actor(owner, frozenset({"tasks:read"})))) as client:
        denied = await client.call_tool("get_work_hierarchy", {}, raise_on_error=False)
    assert denied.is_error and denied.structured_content["code"] == "forbidden"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_hierarchy_reports_truncation_only_when_nodes_were_cut() -> None:
    container, owner, _ = _setup()
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        for index in range(3):
            await client.call_tool(
                "create_domain",
                {"name": f"Truncation {index}", "idempotency_key": f"hier-t-{index}"},
            )

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        cut = await client.call_tool("get_work_hierarchy", {"limit": 2})
        exact = await client.call_tool("get_work_hierarchy", {"limit": 3})
        roomy = await client.call_tool("get_work_hierarchy", {})
    assert len(cut.structured_content["nodes"]) == 2
    assert cut.structured_content["truncated"] is True
    assert len(exact.structured_content["nodes"]) == 3
    assert exact.structured_content["truncated"] is False
    assert len(roomy.structured_content["nodes"]) == 3
    assert roomy.structured_content["truncated"] is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_saved_view_lifecycle_create_update_archive_restore() -> None:
    container, owner, _ = _setup()
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        created = await _create(client, "Morning", "sv-create-001")
        assert created["version"] == 1 and created["archived_at"] is None
        assert created["definition"]["view"] == "agenda"
        assert created["definition"]["tags"] == ["home"]

        updated = (
            await client.call_tool(
                "update_saved_work_view",
                {
                    "view_id": created["id"],
                    "version": 1,
                    "idempotency_key": "sv-update-001",
                    "name": "Evening",
                    "definition": {"view": "board", "context": "task", "status": "todo"},
                },
            )
        ).structured_content["saved_view"]
        assert updated["version"] == 2 and updated["name"] == "Evening"
        assert updated["definition"]["view"] == "board"
        assert updated["definition"]["tags"] is None

        archived = (
            await client.call_tool(
                "archive_saved_work_view",
                {"view_id": created["id"], "version": 2, "idempotency_key": "sv-archive-001"},
            )
        ).structured_content["saved_view"]
        assert archived["archived_at"] is not None and archived["version"] == 3

        blocked = await client.call_tool(
            "update_saved_work_view",
            {
                "view_id": created["id"],
                "version": 3,
                "idempotency_key": "sv-update-002",
                "name": "Nope",
            },
            raise_on_error=False,
        )
        assert blocked.is_error and blocked.structured_content["code"] == "validation_error"

        restored = (
            await client.call_tool(
                "restore_saved_work_view",
                {"view_id": created["id"], "version": 3, "idempotency_key": "sv-restore-001"},
            )
        ).structured_content["saved_view"]
        assert restored["archived_at"] is None and restored["version"] == 4

        listed = await client.call_tool("list_saved_work_views", {})
    assert [v["id"] for v in listed.structured_content["saved_views"]] == [created["id"]]
    assert "owner_id" not in str(listed.structured_content)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_archived_saved_view_is_listed_only_on_request_and_can_be_restored() -> None:
    container, owner, _ = _setup()
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        created = await _create(client, "Shelved", "sv-arch-list-001")
        await client.call_tool(
            "archive_saved_work_view",
            {"view_id": created["id"], "version": 1, "idempotency_key": "sv-arch-list-002"},
        )

        default = _structured(await client.call_tool("list_saved_work_views", {}))
        assert default["saved_views"] == []

        listed = _structured(
            await client.call_tool("list_saved_work_views", {"include_archived": True})
        )
        found = listed["saved_views"]
        assert [v["id"] for v in found] == [created["id"]]
        assert found[0]["archived_at"] is not None and found[0]["version"] == 2

        restored = _structured(
            await client.call_tool(
                "restore_saved_work_view",
                {
                    "view_id": found[0]["id"],
                    "version": found[0]["version"],
                    "idempotency_key": "sv-arch-list-003",
                },
            )
        )["saved_view"]
        assert restored["archived_at"] is None and restored["version"] == 3

        active = _structured(await client.call_tool("list_saved_work_views", {}))
    assert [v["id"] for v in active["saved_views"]] == [created["id"]]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_saved_view_writes_replay_and_reject_a_stale_version() -> None:
    container, owner, _ = _setup()
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        first = await _create(client, "Replay", "sv-replay-001")
        again = await _create(client, "Replay", "sv-replay-001")
        assert again["id"] == first["id"]
        listed = await client.call_tool("list_saved_work_views", {})
        assert len(listed.structured_content["saved_views"]) == 1

        changed = await client.call_tool(
            "create_saved_work_view",
            {"name": "Different", "definition": VIEW, "idempotency_key": "sv-replay-001"},
            raise_on_error=False,
        )
        assert changed.is_error
        assert changed.structured_content["code"] == "conflict"

        args = {
            "view_id": first["id"],
            "version": 1,
            "idempotency_key": "sv-update-r1",
            "name": "Renamed",
        }
        one = await client.call_tool("update_saved_work_view", args)
        two = await client.call_tool("update_saved_work_view", args)
        assert one.structured_content == two.structured_content
        assert one.structured_content["saved_view"]["version"] == 2

        stale = await client.call_tool(
            "update_saved_work_view",
            {**args, "idempotency_key": "sv-update-r2", "name": "Stale"},
            raise_on_error=False,
        )
        assert stale.is_error and stale.structured_content["code"] == "conflict"
        stale_archive = await client.call_tool(
            "archive_saved_work_view",
            {"view_id": first["id"], "version": 1, "idempotency_key": "sv-archive-r1"},
            raise_on_error=False,
        )
        assert stale_archive.is_error and stale_archive.structured_content["code"] == "conflict"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_saved_views_are_owner_scoped_and_foreign_ids_look_missing() -> None:
    container, owner, other = _setup()
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        mine = await _create(client, "Private view", "sv-owner-001")

    async with Client(_server_for(container, Actor(other, WRITE_SCOPES))) as client:
        listed = await client.call_tool("list_saved_work_views", {})
        assert listed.structured_content["saved_views"] == []
        for tool, extra in (
            ("update_saved_work_view", {"name": "Leaked"}),
            ("archive_saved_work_view", {}),
            ("restore_saved_work_view", {}),
        ):
            denied = await client.call_tool(
                tool,
                {"view_id": mine["id"], "version": 1, "idempotency_key": f"sv-x-{tool}", **extra},
                raise_on_error=False,
            )
            assert denied.is_error, tool
            assert denied.structured_content["code"] == "not_found", tool
            assert "Private view" not in str(denied.structured_content), tool


@pytest.mark.asyncio
@pytest.mark.integration
async def test_saved_view_scopes_and_closed_definition() -> None:
    container, owner, _ = _setup()
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        mine = await _create(client, "Scoped", "sv-scope-001")

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        readable = await client.call_tool("list_saved_work_views", {})
        assert readable.structured_content["saved_views"]
        for tool, args in (
            ("create_saved_work_view", {"name": "No", "definition": VIEW}),
            ("update_saved_work_view", {"view_id": mine["id"], "version": 1, "name": "No"}),
            ("archive_saved_work_view", {"view_id": mine["id"], "version": 1}),
            ("restore_saved_work_view", {"view_id": mine["id"], "version": 1}),
        ):
            denied = await client.call_tool(
                tool, {**args, "idempotency_key": f"sv-deny-{tool}"}, raise_on_error=False
            )
            assert denied.is_error, tool
            assert denied.structured_content["code"] == "forbidden", tool

    async with Client(_server_for(container, Actor(owner, frozenset({"tasks:read"})))) as client:
        denied = await client.call_tool("list_saved_work_views", {}, raise_on_error=False)
    assert denied.is_error and denied.structured_content["code"] == "forbidden"

    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        for definition in (
            {**VIEW, "sql": "DROP TABLE"},
            {**VIEW, "view": "kanban"},
            {**VIEW, "actionable": "sometimes"},
            {**VIEW, "tags": ["a", "b", "c", "d", "e", "f"]},
            {"context": "all"},
        ):
            with pytest.raises(ToolError):
                await client.call_tool(
                    "create_saved_work_view",
                    {"name": "Bad", "definition": definition, "idempotency_key": "sv-bad-001"},
                )
        for bad_name in ("", "x" * 121):
            with pytest.raises(ToolError):
                await client.call_tool(
                    "create_saved_work_view",
                    {"name": bad_name, "definition": VIEW, "idempotency_key": "sv-bad-002"},
                )
        empty = await client.call_tool(
            "update_saved_work_view",
            {"view_id": mine["id"], "version": 1, "idempotency_key": "sv-empty-001"},
            raise_on_error=False,
        )
        assert empty.is_error and empty.structured_content["code"] == "validation_error"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_saved_view_values_never_reach_logs(all_logs: _Collector) -> None:
    container, owner, _ = _setup()
    async with Client(_server_for(container, Actor(owner, WRITE_SCOPES))) as client:
        await client.call_tool_mcp(
            "create_saved_work_view",
            {
                "name": SENTINEL,
                "definition": {**VIEW, "view": SENTINEL},
                "idempotency_key": "sv-log-probe-001",
            },
        )
        await client.call_tool_mcp(
            "update_saved_work_view",
            {
                "view_id": "00000000-0000-7000-8000-000000000000",
                "version": 1,
                "idempotency_key": "sv-log-probe-002",
                "name": SENTINEL,
            },
        )
    assert SENTINEL not in all_logs.rendered()
