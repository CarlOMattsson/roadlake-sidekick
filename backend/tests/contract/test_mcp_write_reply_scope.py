"""A write tool whose reply carries a record needs that record's read scope too.

`TaskService.complete` checks only `tasks:write`, yet `complete_task` answers with the whole Task.
A token with `tasks:write` and `projects:read` but not `tasks:read` must not read the description
through that reply. The rule (`sidekick.mcp.reply_scopes`) refuses such a call before anything is
written, replayed or compared by version, so none of the three outcomes shows the record.
"""

import os
from typing import Any

import pytest
from fastmcp import Client
from mcp.types import ToolAnnotations

from sidekick.api.app import Container, create_container
from sidekick.mcp.reply_scopes import (
    RECEIPT_ONLY_WRITES,
    WRITE_REPLY_READ_SCOPES,
    missing_reply_scope,
)
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.auth import MCP_SCOPES
from sidekick.shared.types import Actor
from tests.db import _cleanup_factory_for, database_factory
from tests.support.mcp_scope_gate import (
    ALL_SCOPES,
    EXTRA_ARGUMENTS,
    _call_every_tool,
    _code,
    _digests,
    _sample,
    _seed,
)
from tests.support.settings import make_settings

SECRET = "the private description of the task"


@pytest.fixture
def container_and_owner() -> tuple[Container, Any]:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("reply_scope", "Reply Scope")
    return container, owner


def _server(container: Container, owner: Any, scopes: frozenset[str]) -> Any:
    return create_mcp_server(
        container, actor_provider=lambda: Actor(owner, scopes), enable_auth=False
    )


async def _seed_task_with_description(container: Container, owner: Any) -> dict[str, Any]:
    async with Client(_server(container, owner, ALL_SCOPES)) as client:
        result = await client.call_tool(
            "create_task",
            {"title": "Private", "description": SECRET, "idempotency_key": "reply-seed-task"},
        )
    return (result.structured_content or {})["task"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_every_write_tool_is_classified_exactly_once(
    container_and_owner: tuple[Container, Any],
) -> None:
    container, owner = container_and_owner
    async with Client(_server(container, owner, ALL_SCOPES)) as client:
        tools = await client.list_tools()
    write_tools = {
        tool.name for tool in tools if not (tool.annotations and tool.annotations.readOnlyHint)
    }

    assert set(WRITE_REPLY_READ_SCOPES) & RECEIPT_ONLY_WRITES == set()
    assert write_tools == set(WRITE_REPLY_READ_SCOPES) | RECEIPT_ONLY_WRITES
    assert set(WRITE_REPLY_READ_SCOPES.values()) <= set(MCP_SCOPES)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_complete_task_with_write_and_project_read_but_no_task_read_is_refused_everywhere(
    container_and_owner: tuple[Container, Any],
) -> None:
    """First write, idempotent replay and version conflict all answer `forbidden`, with no
    description in the answer and no change to any table."""

    container, owner = container_and_owner
    task = await _seed_task_with_description(container, owner)
    admin = _cleanup_factory_for(os.environ["SIDEKICK_TEST_ADMIN_DATABASE_URL"])
    narrow = frozenset({"tasks:write", "projects:read"})

    # The owner completes the task once with every scope, so a replay and a conflict both exist.
    async with Client(_server(container, owner, ALL_SCOPES)) as client:
        done = await client.call_tool(
            "complete_task",
            {"task_id": task["id"], "version": task["version"], "idempotency_key": "reply-done-1"},
        )
    assert (done.structured_content or {})["task"]["status"] == "completed"

    calls = {
        "first write": {"version": task["version"], "idempotency_key": "reply-first-1"},
        "idempotent replay": {"version": task["version"], "idempotency_key": "reply-done-1"},
        "version conflict": {"version": task["version"] + 7, "idempotency_key": "reply-other-1"},
    }
    async with Client(_server(container, owner, narrow)) as client:
        for label, arguments in calls.items():
            before = _digests(admin)
            result = await client.call_tool(
                "complete_task", {"task_id": task["id"], **arguments}, raise_on_error=False
            )
            assert _code(result) == "forbidden", label
            assert SECRET not in str(result.structured_content) + str(result.content), label
            assert _digests(admin) == before, label


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_other_task_writes_refuse_a_caller_without_task_read(
    container_and_owner: tuple[Container, Any],
) -> None:
    container, owner = container_and_owner
    task = await _seed_task_with_description(container, owner)
    admin = _cleanup_factory_for(os.environ["SIDEKICK_TEST_ADMIN_DATABASE_URL"])
    narrow = frozenset({"tasks:write", "projects:read"})
    calls: dict[str, dict[str, Any]] = {
        "create_task": {"title": "New", "idempotency_key": "reply-create-1"},
        "create_tasks": {"tasks": [{"title": "New"}], "idempotency_key": "reply-create-2"},
        "update_task": {
            "task_id": task["id"],
            "version": task["version"],
            "idempotency_key": "reply-update-1",
            "changes": {"title": "Renamed"},
        },
        "reschedule_tasks": {
            "items": [
                {"task_id": task["id"], "expected_version": task["version"], "when": "tomorrow"}
            ],
            "idempotency_key": "reply-resched-1",
        },
        "create_task_step": {
            "task_id": task["id"],
            "title": "Step",
            "idempotency_key": "reply-step-1",
        },
    }
    async with Client(_server(container, owner, narrow)) as client:
        for name, arguments in calls.items():
            before = _digests(admin)
            result = await client.call_tool(name, arguments, raise_on_error=False)
            assert _code(result) == "forbidden", name
            assert SECRET not in str(result.structured_content) + str(result.content), name
            assert _digests(admin) == before, name


@pytest.mark.asyncio
@pytest.mark.integration
async def test_each_classified_tool_is_refused_without_its_read_scope_and_writes_nothing(
    container_and_owner: tuple[Container, Any],
) -> None:
    """Every scope but the tool's own read scope: `forbidden`, and the database is unchanged."""

    container, owner = container_and_owner
    await _seed(container, owner)
    admin = _cleanup_factory_for(os.environ["SIDEKICK_TEST_ADMIN_DATABASE_URL"])
    refused: dict[str, str | None] = {}
    for scope in sorted(set(WRITE_REPLY_READ_SCOPES.values())):
        actor = Actor(owner, ALL_SCOPES - {scope})
        async with Client(_server(container, owner, actor.scopes)) as client:
            for tool in await client.list_tools():
                if WRITE_REPLY_READ_SCOPES.get(tool.name) != scope:
                    continue
                arguments = _sample(tool.inputSchema, tool.inputSchema, top=True)
                arguments |= EXTRA_ARGUMENTS.get(tool.name, {})
                before = _digests(admin)
                result = await client.call_tool(tool.name, arguments, raise_on_error=False)
                refused[tool.name] = _code(result)
                assert _digests(admin) == before, tool.name
    assert refused.keys() == WRITE_REPLY_READ_SCOPES.keys()
    assert {name: code for name, code in refused.items() if code != "forbidden"} == {}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_caller_with_the_read_scope_still_gets_the_full_task_back(
    container_and_owner: tuple[Container, Any],
) -> None:
    container, owner = container_and_owner
    task = await _seed_task_with_description(container, owner)
    scopes = frozenset({"tasks:write", "tasks:read", "projects:read"})
    async with Client(_server(container, owner, scopes)) as client:
        result = await client.call_tool(
            "complete_task",
            {"task_id": task["id"], "version": task["version"], "idempotency_key": "reply-ok-1"},
        )
    assert (result.structured_content or {})["task"]["description"] == SECRET


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_rule_does_not_deny_anything_to_a_caller_with_every_scope(
    container_and_owner: tuple[Container, Any],
) -> None:
    container, owner = container_and_owner
    results = await _call_every_tool(container, Actor(owner, ALL_SCOPES))
    assert [name for name in WRITE_REPLY_READ_SCOPES if _code(results[name]) == "forbidden"] == []


def test_missing_reply_scope_names_only_the_scope_the_actor_lacks() -> None:
    owner = object()
    narrow = Actor(owner, frozenset({"tasks:write"}))  # type: ignore[arg-type]
    assert missing_reply_scope("complete_task", narrow) == "tasks:read"
    assert missing_reply_scope("get_task", narrow) is None
    full = Actor(owner, frozenset({"tasks:write", "tasks:read"}))  # type: ignore[arg-type]
    assert missing_reply_scope("complete_task", full) is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_write_tool_missing_from_the_mapping_is_refused_and_a_read_tool_is_not(
    container_and_owner: tuple[Container, Any],
) -> None:
    """Fail closed: a tool added without a reply-scope rule never answers with a record."""

    container, owner = container_and_owner
    server = _server(container, owner, ALL_SCOPES)
    calls: list[str] = []

    @server.tool(name="zz_unclassified_write", annotations=ToolAnnotations(readOnlyHint=False))
    def unclassified_write() -> dict[str, str]:
        calls.append("write")
        return {"secret": SECRET}

    @server.tool(name="zz_unclassified_read", annotations=ToolAnnotations(readOnlyHint=True))
    def unclassified_read() -> dict[str, str]:
        calls.append("read")
        return {"ok": "yes"}

    @server.tool(name="zz_unannotated")
    def unannotated() -> dict[str, str]:
        calls.append("unannotated")
        return {"secret": SECRET}

    async with Client(server) as client:
        refused = await client.call_tool("zz_unclassified_write", {}, raise_on_error=False)
        unannotated_refused = await client.call_tool("zz_unannotated", {}, raise_on_error=False)
        allowed = await client.call_tool("zz_unclassified_read", {}, raise_on_error=False)

    assert _code(refused) == "forbidden"
    assert (refused.structured_content or {}).get("correlation_id")
    assert _code(unannotated_refused) == "forbidden"
    assert SECRET not in str(refused.structured_content) + str(refused.content)
    assert not allowed.is_error
    assert calls == ["read"]
