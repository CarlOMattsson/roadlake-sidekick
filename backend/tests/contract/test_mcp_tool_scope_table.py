"""`sidekick.mcp.tool_scopes` names the scopes the server really asks for.

The tool reference prints that table, so it must not name fewer scopes than the server refuses on.
Every tool is called against a real server with sample arguments:

- with all scopes but one, a tool that is refused for lack of that scope must name it in its entry;
- with exactly the scopes its entry names, a tool is never refused;
- without any of the scopes of an "at least one of" entry, a tool is refused.

A call with sample arguments can fail validation before a use case checks its scope, so this proves
the table covers what the server refuses on, not that every listed scope is observed.
"""

from collections.abc import Collection
from typing import Any

import pytest
from fastmcp import Client

from sidekick.api.app import Container, create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.mcp.tool_scopes import TOOL_SCOPES
from sidekick.shared.auth import MCP_SCOPES
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.mcp_scope_gate import EXTRA_ARGUMENTS, _code, _sample
from tests.support.settings import make_settings


@pytest.fixture
def container_and_owner() -> tuple[Container, Any]:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("scope_table", "Scope Table")
    return container, owner


async def _codes(
    container: Container, actor: Actor, names: Collection[str]
) -> dict[str, str | None]:
    """The error code (None for a success) of a sample call to each named tool."""
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    codes: dict[str, str | None] = {}
    async with Client(server) as client:
        for tool in await client.list_tools():
            if tool.name in names:
                arguments = _sample(tool.inputSchema, tool.inputSchema, top=True)
                arguments |= EXTRA_ARGUMENTS.get(tool.name, {})
                result = await client.call_tool(tool.name, arguments, raise_on_error=False)
                codes[tool.name] = _code(result)
    return codes


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_table_names_every_scope_a_tool_is_refused_for(
    container_and_owner: tuple[Container, Any],
) -> None:
    container, owner = container_and_owner
    undeclared: dict[str, list[str]] = {}
    for scope in MCP_SCOPES:
        codes = await _codes(container, Actor(owner, frozenset(MCP_SCOPES) - {scope}), TOOL_SCOPES)
        assert set(codes) == set(TOOL_SCOPES)
        for name, code in codes.items():
            if code == "forbidden" and scope not in TOOL_SCOPES[name].everything():
                undeclared.setdefault(name, []).append(scope)

    assert undeclared == {}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_session_with_exactly_the_scopes_in_the_table_is_not_refused(
    container_and_owner: tuple[Container, Any],
) -> None:
    container, owner = container_and_owner
    by_scopes: dict[frozenset[str], list[str]] = {}
    for name, scopes in TOOL_SCOPES.items():
        by_scopes.setdefault(scopes.everything(), []).append(name)

    refused: list[str] = []
    for scopes, names in by_scopes.items():
        codes = await _codes(container, Actor(owner, scopes), names)
        refused += [name for name, code in codes.items() if code == "forbidden"]

    assert refused == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_session_without_any_of_the_listed_scopes_is_refused(
    container_and_owner: tuple[Container, Any],
) -> None:
    container, owner = container_and_owner
    by_any_of: dict[frozenset[str], list[str]] = {}
    for name, scopes in TOOL_SCOPES.items():
        if scopes.any_of:
            by_any_of.setdefault(frozenset(scopes.any_of), []).append(name)

    not_refused: list[str] = []
    for any_of, names in by_any_of.items():
        codes = await _codes(container, Actor(owner, frozenset(MCP_SCOPES) - any_of), names)
        not_refused += [name for name, code in codes.items() if code != "forbidden"]

    assert not_refused == []
