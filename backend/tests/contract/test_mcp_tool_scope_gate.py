"""Every registered MCP tool is gated by a scope, and a caller without it is denied.

The tool list comes from the running server (`list_tools`), never from a handwritten list, so a
tool added later is covered the moment it is registered. A tool cannot be called without a scope
and still return data:

- With no MCP scope at all, and with only a session-only scope that no MCP credential can hold,
  every tool answers `forbidden`. The two exceptions below read per part and leave a part out when
  its scope is missing; they must then return nothing of the owner's.
- With every MCP scope, no tool answers `forbidden`. That proves the denial above comes from the
  missing scope and not from a rejected sample argument.
- A caller with some of the scopes is refused before anything is written. A tool that answers with
  a part it needs a second scope for (the tags of the record it wrote) must check that scope
  first; otherwise it commits the write and then says `forbidden`.
"""

import os
from collections.abc import Callable
from typing import Any

import pytest
from fastmcp import Client

from sidekick.api.app import Container, create_container
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

# Tools without one scope of their own: they assemble parts and drop each part whose read scope is
# missing, so a caller with no scope gets an empty answer. Each entry states what "empty" means.
PER_PART_TOOLS: dict[str, Callable[[dict[str, Any]], bool]] = {
    "get_today_brief": lambda out: set(out) == {"day"},
    "list_recent_changes": lambda out: out == {"changes": []},
}


@pytest.fixture
def container_and_owner() -> tuple[Container, Any]:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("scope_gate", "Scope Gate")
    return container, owner


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    "scopes",
    [frozenset(), frozenset({"preferences:read", "preferences:write"})],
    ids=["no-scopes", "retired-scopes"],
)
async def test_every_registered_tool_denies_a_caller_without_an_mcp_scope(
    container_and_owner: tuple[Container, Any], scopes: frozenset[str]
) -> None:
    container, owner = container_and_owner
    results = await _call_every_tool(container, Actor(owner, scopes))

    assert len(results) > 50  # the registry is read, not an empty or truncated list
    assert set(PER_PART_TOOLS) <= set(results), "a per-part exception names a tool that is gone"
    not_denied = {
        name: _code(result)
        for name, result in results.items()
        if name not in PER_PART_TOOLS and _code(result) != "forbidden"
    }
    assert not_denied == {}
    for name, is_empty in PER_PART_TOOLS.items():
        assert not results[name].is_error, name
        assert is_empty(results[name].structured_content or {}), name
    for name, result in results.items():
        if _code(result) == "forbidden":
            assert (result.structured_content or {}).get("correlation_id"), name


@pytest.mark.asyncio
@pytest.mark.integration
async def test_every_registered_tool_is_reachable_with_the_full_scope_set(
    container_and_owner: tuple[Container, Any],
) -> None:
    container, owner = container_and_owner
    results = await _call_every_tool(container, Actor(owner, frozenset(MCP_SCOPES)))

    assert {
        name: _code(result) for name, result in results.items() if _code(result) == "forbidden"
    } == {}


# --- a refused call writes nothing -------------------------------------------------------------

WRITE_SCOPES = frozenset(scope for scope in MCP_SCOPES if scope.endswith(":write"))


TAG_WRITING_TOOLS = (
    "create_task",
    "create_tasks",
    "update_task",
    "complete_task",
    "create_project",
    "update_project",
    "update_domain",
    "update_process",
)


def _tag_writing_calls(seed: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The write tools whose reply lists tags (projects:read), each with a well-formed call."""

    key = "refused-write-key"
    return {
        "create_task": {"title": "New task", "idempotency_key": key},
        "create_tasks": {"tasks": [{"title": "New task"}], "idempotency_key": key},
        "update_task": {
            "task_id": seed["task"]["id"],
            "version": seed["task"]["version"],
            "idempotency_key": key,
            "changes": {"title": "Renamed"},
        },
        "complete_task": {
            "task_id": seed["task"]["id"],
            "version": seed["task"]["version"],
            "idempotency_key": key,
        },
        "create_project": {
            "domain_id": seed["domain"]["id"],
            "title": "New project",
            "idempotency_key": key,
        },
        "update_project": {
            "project_id": seed["project"]["id"],
            "version": seed["project"]["version"],
            "idempotency_key": key,
            "changes": {"title": "Renamed"},
        },
        "update_domain": {
            "domain_id": seed["domain"]["id"],
            "version": seed["domain"]["version"],
            "idempotency_key": key,
            "changes": {"name": "Renamed"},
        },
        "update_process": {
            "process_id": seed["process"]["id"],
            "version": seed["process"]["version"],
            "idempotency_key": key,
            "changes": {"name": "Renamed"},
        },
    }


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    "scopes",
    [
        frozenset({"tasks:write"}),
        frozenset({"projects:write"}),
        WRITE_SCOPES,
        ALL_SCOPES - {"projects:read"},
    ],
    ids=["tasks-write-only", "projects-write-only", "every-write-scope", "all-but-projects-read"],
)
async def test_a_write_tool_that_lists_tags_refuses_before_it_writes(
    container_and_owner: tuple[Container, Any], scopes: frozenset[str]
) -> None:
    """The reply names the record's tags, which needs `projects:read`. Without it the call is
    refused up front and no row, audit event or idempotency key is committed."""

    container, owner = container_and_owner
    seed = await _seed(container, owner)
    admin = _cleanup_factory_for(os.environ["SIDEKICK_TEST_ADMIN_DATABASE_URL"])
    calls = _tag_writing_calls(seed)
    assert tuple(calls) == TAG_WRITING_TOOLS
    server = create_mcp_server(
        container, actor_provider=lambda: Actor(owner, scopes), enable_auth=False
    )
    async with Client(server) as client:
        assert {tool.name for tool in await client.list_tools()} >= set(calls)
        for name, arguments in calls.items():
            before = _digests(admin)
            result = await client.call_tool(name, arguments, raise_on_error=False)
            assert _code(result) == "forbidden", name
            assert _digests(admin) == before, f"{name} changed data and then answered forbidden"


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("name", TAG_WRITING_TOOLS)
async def test_each_tag_writing_call_succeeds_with_every_scope(
    container_and_owner: tuple[Container, Any], name: str
) -> None:
    """The calls above succeed with every scope, so their refusal comes from the missing scope."""

    container, owner = container_and_owner
    seed = await _seed(container, owner)
    server = create_mcp_server(
        container, actor_provider=lambda: Actor(owner, ALL_SCOPES), enable_auth=False
    )
    async with Client(server) as client:
        result = await client.call_tool(name, _tag_writing_calls(seed)[name], raise_on_error=False)
    assert not result.is_error, result.structured_content


@pytest.mark.asyncio
@pytest.mark.integration
async def test_no_tool_commits_a_write_and_then_answers_forbidden_when_one_scope_is_missing(
    container_and_owner: tuple[Container, Any],
) -> None:
    """Every tool with all scopes but one: a `forbidden` answer leaves the data as it was."""

    container, owner = container_and_owner
    admin = _cleanup_factory_for(os.environ["SIDEKICK_TEST_ADMIN_DATABASE_URL"])
    changed: list[tuple[str, str]] = []
    for missing in MCP_SCOPES:
        actor = Actor(owner, ALL_SCOPES - {missing})
        server = create_mcp_server(
            container, actor_provider=lambda actor=actor: actor, enable_auth=False
        )
        async with Client(server) as client:
            for tool in await client.list_tools():
                arguments = _sample(tool.inputSchema, tool.inputSchema, top=True)
                arguments |= EXTRA_ARGUMENTS.get(tool.name, {})
                before = _digests(admin)
                result = await client.call_tool(tool.name, arguments, raise_on_error=False)
                if _code(result) == "forbidden" and _digests(admin) != before:
                    changed.append((missing, tool.name))
    assert changed == []
