"""A malformed client value passed to an MCP tool is a validation error, never an internal one.

The MCP boundary answers only `InvalidInputError` and the pydantic validation error as a client
error (`error_result`); a stdlib `ValueError` escaping a parser of client input would be reported
as `internal_error`. Every tool that passes a client-supplied cursor through to a use case is
probed here, so a new stdlib parse in a service shows up as a failing case.
"""

import base64
from typing import Any

import pytest
from fastmcp import Client

from sidekick.api.app import create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.auth import MCP_SCOPES
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings

# Not a cursor this server issued: not base64, base64 of non-JSON, base64 of JSON that is not an
# object, the right length with a wrong signature, and non-ASCII text.
MALFORMED_CURSORS = [
    "!!!not-a-cursor",
    base64.urlsafe_b64encode(b"\xff\xfe not json").decode().rstrip("="),
    base64.urlsafe_b64encode(b'["a"]').decode().rstrip("="),
    base64.urlsafe_b64encode(b"x" * 80).decode().rstrip("="),
    "kursivå",
]


def _cursor_calls(task_id: str, contact_id: str) -> list[tuple[str, dict[str, Any]]]:
    return [
        ("list_assistant_activity", {}),
        ("list_contacts", {}),
        ("get_contact_context", {"contact_id": contact_id, "project_cursor": "{cursor}"}),
        ("get_contact_context", {"contact_id": contact_id, "task_cursor": "{cursor}"}),
        ("list_task_contacts", {"task_id": task_id}),
        ("list_task_external_references", {"task_id": task_id}),
        ("list_projects", {}),
        ("list_domains", {}),
        ("list_processes", {}),
        ("list_tags", {}),
        ("list_tasks", {}),
        ("get_work_board", {}),
        ("get_work_agenda", {}),
        ("list_trash", {}),
        ("list_journal_entries", {}),
        ("search", {"query": "malformed"}),
    ]


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("cursor", MALFORMED_CURSORS)
async def test_a_malformed_cursor_is_a_validation_error_on_every_paged_tool(cursor: str) -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("input-owner", "Owner")
    server = create_mcp_server(
        container,
        actor_provider=lambda: Actor(owner, frozenset(MCP_SCOPES)),
        enable_auth=False,
    )
    async with Client(server) as client:
        task = await client.call_tool(
            "create_task", {"title": "Probe", "idempotency_key": "input-task-0001"}
        )
        contact = await client.call_tool(
            "create_contact", {"display_name": "Probe", "idempotency_key": "input-contact-0001"}
        )
        assert task.structured_content is not None and contact.structured_content is not None
        task_id = task.structured_content["task"]["id"]
        contact_id = contact.structured_content["contact"]["id"]

        for name, arguments in _cursor_calls(task_id, contact_id):
            filled = {
                key: cursor if value == "{cursor}" else value for key, value in arguments.items()
            }
            if not any(value == cursor for value in filled.values()):
                filled["cursor"] = cursor
            result = await client.call_tool(name, filled, raise_on_error=False)
            assert result.is_error, name
            assert result.structured_content is not None, name
            assert result.structured_content["code"] == "validation_error", (name, cursor)


NUL_TEXT = "abc\x00def"


@pytest.mark.asyncio
async def test_a_nul_character_in_any_argument_of_any_tool_is_a_validation_error() -> None:
    """PostgreSQL cannot store NUL; the call is refused as a client error before any use case."""
    server = create_mcp_server(create_container(make_settings()), enable_auth=False)
    async with Client(server) as client:
        tools = await client.list_tools()
        assert len(tools) > 50
        probed = 0
        for tool in tools:
            properties = tool.input_schema.get("properties", {})
            # A text field directly, in a list, in a nested object, and as an object key.
            for name in properties:
                for value in (NUL_TEXT, [NUL_TEXT], {"field": NUL_TEXT}, {NUL_TEXT: 1}):
                    result = await client.call_tool(tool.name, {name: value}, raise_on_error=False)
                    where = (tool.name, name, value)
                    assert result.is_error, where
                    assert result.structured_content is not None, where
                    assert result.structured_content["code"] == "validation_error", where
                    assert "\x00" not in str(result.content), where
                    probed += 1
        assert probed > 100


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_nul_in_create_task_text_is_refused_and_nothing_is_stored() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("nul-owner", "Owner")
    server = create_mcp_server(
        container,
        actor_provider=lambda: Actor(owner, frozenset(MCP_SCOPES)),
        enable_auth=False,
    )
    async with Client(server) as client:
        for key, arguments in (
            ("nul-title-0001", {"title": NUL_TEXT}),
            ("nul-desc-0001", {"title": "Ok", "description": NUL_TEXT}),
            ("nul-tags-0001", {"title": "Ok", "tags": [NUL_TEXT]}),
        ):
            result = await client.call_tool(
                "create_task", {**arguments, "idempotency_key": key}, raise_on_error=False
            )
            assert result.is_error and result.structured_content is not None
            assert result.structured_content["code"] == "validation_error", arguments
            assert result.structured_content["reason"] == "nul_character"
        listed = await client.call_tool("list_tasks", {})
        assert listed.structured_content is not None
        assert listed.structured_content["tasks"] == []
