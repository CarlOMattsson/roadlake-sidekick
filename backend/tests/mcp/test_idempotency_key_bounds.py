"""Every MCP write tool bounds its `idempotency_key` the same way, Contact tools included.

The bound lives in one type (`sidekick.mcp.idempotency.IdempotencyKey`): a required string of
8 to 128 characters, which is what the write path accepts. A key outside it is a validation error
before any use case runs.
"""

from typing import Any
from uuid import uuid4

import pytest
from fastmcp import Client

from sidekick.api.app import create_container
from sidekick.mcp.idempotency import IdempotencyKey
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.auth import MCP_SCOPES
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings

CONTACT_WRITES = (
    "create_contact",
    "update_contact",
    "archive_contact",
    "restore_contact",
    "add_contact_alias",
    "remove_contact_alias",
    "link_contact_to_project",
    "unlink_contact_from_project",
    "link_contact_to_task",
    "unlink_contact_from_task",
)

BAD_KEYS = ("", "short", "x" * 7, "y" * 129, "z" * 1000)


def _arguments(tool: str, key: str) -> dict[str, Any]:
    """Valid arguments but for the key, so a refusal can only come from the key."""

    some = str(uuid4())
    arguments: dict[str, Any] = {"idempotency_key": key}
    if tool == "create_contact":
        arguments["display_name"] = "Probe"
    else:
        arguments["contact_id"] = some
    if tool == "update_contact":
        arguments["changes"] = {"display_name": "Other"}
    if tool in {"update_contact", "archive_contact", "restore_contact"}:
        arguments["expected_version"] = 1
    if tool == "add_contact_alias":
        arguments.update(value="Alias", expected_version=1)
    if tool == "remove_contact_alias":
        arguments.update(alias_id=some, expected_version=1)
    if tool.endswith("_project"):
        arguments["project_id"] = some
    if tool.endswith("_task"):
        arguments["task_id"] = some
    return arguments


def test_the_shared_type_is_a_required_string_of_8_to_128_characters() -> None:
    from pydantic import TypeAdapter, ValidationError

    adapter = TypeAdapter(IdempotencyKey)
    schema = adapter.json_schema()
    assert (schema["type"], schema["minLength"], schema["maxLength"]) == ("string", 8, 128)
    for accepted in ("a" * 8, "b" * 128, "create-contact-0001"):
        assert adapter.validate_python(accepted) == accepted
    for refused in (*BAD_KEYS, None, 12345678):
        with pytest.raises(ValidationError):
            adapter.validate_python(refused)


@pytest.mark.asyncio
async def test_every_tool_with_an_idempotency_key_declares_the_same_bound() -> None:
    server = create_mcp_server(create_container(make_settings()), enable_auth=False)
    async with Client(server) as client:
        tools = await client.list_tools()
    keyed = [tool for tool in tools if "idempotency_key" in tool.input_schema["properties"]]
    assert {*CONTACT_WRITES} <= {tool.name for tool in keyed}
    for tool in keyed:
        schema = tool.input_schema
        assert "idempotency_key" in schema["required"], tool.name
        key = schema["properties"]["idempotency_key"]
        assert (key["type"], key["minLength"], key["maxLength"]) == ("string", 8, 128), tool.name


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_contact_tool_refuses_an_idempotency_key_outside_the_bound() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("key-owner", "Owner")
    server = create_mcp_server(
        container,
        actor_provider=lambda: Actor(owner, frozenset(MCP_SCOPES)),
        enable_auth=False,
    )
    async with Client(server) as client:
        for tool in CONTACT_WRITES:
            for key in BAD_KEYS:
                result = await client.call_tool(tool, _arguments(tool, key), raise_on_error=False)
                assert result.is_error, (tool, len(key))
                # The schema check answers before the tool runs and names the field.
                assert "idempotency_key" in result.content[0].text, (tool, len(key))

        # The bounds themselves are accepted: 8 and 128 characters.
        for key in ("k" * 8, "j" * 128):
            created = await client.call_tool(
                "create_contact", {"display_name": f"Edge {len(key)}", "idempotency_key": key}
            )
            assert created.structured_content is not None
            assert created.structured_content["contact"]["display_name"] == f"Edge {len(key)}"

        # No contact was written by a refused call.
        listed = await client.call_tool("list_contacts", {})
        assert listed.structured_content is not None
        names = {c["display_name"] for c in listed.structured_content["contacts"]}
        assert names == {"Edge 8", "Edge 128"}
