"""Security contract tests for Contact isolation and scope denial (MCP, D-082)."""

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from sidekick.api.app import create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings


@pytest.mark.asyncio
@pytest.mark.integration
async def test_threat_model_matrix() -> None:
    container = create_container(make_settings(), database_factory())
    owner_id = container.auth.provision_user("private-owner", "Owner")
    other_id = container.auth.provision_user("private-other", "Other")
    owner = Actor(owner_id, frozenset({"contacts:read", "contacts:write"}))
    other = Actor(other_id, frozenset({"contacts:read", "contacts:write"}))

    def server(actor: Actor):
        return create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server(owner)) as client:
        created = await client.call_tool(
            "create_contact",
            {
                "display_name": "SECRET-RASMUS",
                "email": "private@example.com",
                "idempotency_key": "security-contact",
            },
        )
        contact = created.structured_content["contact"]

    async with Client(server(other)) as client:
        with pytest.raises(ToolError) as denied:
            await client.call_tool("get_contact_context", {"contact_id": contact["id"]})
        assert "SECRET-RASMUS" not in str(denied.value)
        assert "private@example.com" not in str(denied.value)
        searched = await client.call_tool("list_contacts", {"q": "SECRET-RASMUS"})
        assert searched.structured_content["contacts"] == []
        with pytest.raises(ToolError) as cross_write:
            await client.call_tool(
                "update_contact",
                {
                    "contact_id": contact["id"],
                    "expected_version": contact["version"],
                    "changes": {"display_name": "Changed"},
                    "idempotency_key": "security-cross-write",
                },
            )
        assert "SECRET-RASMUS" not in str(cross_write.value)

    # Without the write scope the owner cannot change their own Contact.
    read_only = Actor(owner_id, frozenset({"contacts:read"}))
    async with Client(server(read_only)) as client:
        with pytest.raises(ToolError):
            await client.call_tool(
                "update_contact",
                {
                    "contact_id": contact["id"],
                    "expected_version": contact["version"],
                    "changes": {"display_name": "Changed"},
                    "idempotency_key": "security-read-only",
                },
            )
