"""MCP tool discovery tests for Contacts and Relationships."""

import pytest
from mcp.types import ToolAnnotations

from sidekick.api.app import create_container
from sidekick.mcp.server import create_mcp_server
from tests.support.settings import make_settings

CONTACT_TOOLS = {
    "list_contacts",
    "get_contact_context",
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
    "list_task_contacts",
}


@pytest.mark.asyncio
async def test_discovery_contact_tools_have_exact_annotations() -> None:
    server = create_mcp_server(create_container(make_settings()), enable_auth=False)
    tools = await server.list_tools()
    contact_tools = [tool for tool in tools if tool.name in CONTACT_TOOLS]

    assert {tool.name for tool in contact_tools} == CONTACT_TOOLS
    for tool in contact_tools:
        assert tool.title
        assert tool.description and len(tool.description) >= 40
        assert tool.parameters["additionalProperties"] is False
        assert tool.output_schema is not None
        assert tool.output_schema["additionalProperties"] is False
        assert isinstance(tool.annotations, ToolAnnotations)

        # Test specific annotations based on read-only and destructive behavior
        if tool.name in ("list_contacts", "get_contact_context", "list_task_contacts"):
            assert tool.annotations.readOnlyHint is True
            assert tool.annotations.destructiveHint is False
        elif tool.name in (
            "remove_contact_alias",
            "unlink_contact_from_project",
            "unlink_contact_from_task",
        ):
            assert tool.annotations.readOnlyHint is False
            assert tool.annotations.destructiveHint is True
        else:
            assert tool.annotations.readOnlyHint is False
            assert tool.annotations.destructiveHint is False

        assert tool.annotations.idempotentHint is True
        assert tool.annotations.openWorldHint is False
