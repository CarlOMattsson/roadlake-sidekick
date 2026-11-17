"""MCP and persistence behaviour of the Contact profile fields and the address (D-060)."""

import json
from typing import Any

import pytest
from fastmcp.exceptions import ToolError

from sidekick.api.app import create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings

ADDRESS = "Hemlig gata 12, 111 22 Stockholm"


def model_text(result: Any) -> str:
    """Everything the model client reads: every text block."""
    return "\n".join(block.text for block in result.content)


def make_server() -> Any:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    user_id = container.auth.provision_user("owner", "Owner")
    actor = Actor(
        user_id, frozenset({"contacts:read", "contacts:write", "projects:read", "tasks:read"})
    )
    return create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_profile_fields_are_saved_updated_and_cleared() -> None:
    server = make_server()

    created = await server.call_tool(
        "create_contact",
        {
            "display_name": "Anna Lind",
            "idempotency_key": "profile-create-0001",
            "relationship": "syster",
            "organization": "Acme AB",
            "role": "VD",
            "address": ADDRESS,
        },
    )
    contact = created.structured_content["contact"]
    assert (contact["relationship"], contact["organization"], contact["role"]) == (
        "syster",
        "Acme AB",
        "VD",
    )
    assert contact["address"] == ADDRESS

    # Omitted fields stay unchanged; a field named in clear is emptied.
    updated = await server.call_tool(
        "update_contact",
        {
            "contact_id": contact["id"],
            "expected_version": contact["version"],
            "idempotency_key": "profile-update-0001",
            "changes": {"role": "Styrelseordförande"},
            "clear": ["address"],
        },
    )
    after = updated.structured_content["contact"]
    assert after["role"] == "Styrelseordförande"
    assert after["address"] is None
    assert after["relationship"] == "syster"
    assert after["organization"] == "Acme AB"

    context = await server.call_tool("get_contact_context", {"contact_id": contact["id"]})
    stored = context.structured_content["contact"]
    assert (stored["relationship"], stored["organization"], stored["role"]) == (
        "syster",
        "Acme AB",
        "Styrelseordförande",
    )
    assert stored["address"] is None

    cleared = await server.call_tool(
        "update_contact",
        {
            "contact_id": contact["id"],
            "expected_version": after["version"],
            "idempotency_key": "profile-update-0002",
            "changes": {},
            "clear": ["relationship", "organization", "role"],
        },
    )
    final = cleared.structured_content["contact"]
    assert (final["relationship"], final["organization"], final["role"]) == (None, None, None)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_address_reaches_model_text_with_organization_and_role() -> None:
    server = make_server()
    created = await server.call_tool(
        "create_contact",
        {
            "display_name": "Anna Lind",
            "idempotency_key": "profile-redact-0001",
            "relationship": "syster",
            "organization": "Acme AB",
            "role": "VD",
            "address": ADDRESS,
        },
    )
    contact = created.structured_content["contact"]
    # D-060: the Contact app and the model both receive the address (block 2 is the full result).
    assert created.structured_content["contact"]["address"] == ADDRESS
    assert ADDRESS in model_text(created)
    assert '"address"' in model_text(created)

    context = await server.call_tool("get_contact_context", {"contact_id": contact["id"]})
    text = model_text(context)
    assert context.structured_content["contact"]["address"] == ADDRESS
    assert ADDRESS in text
    assert json.loads(context.content[1].text)["contact"]["address"] == ADDRESS
    assert "Organization: Acme AB" in text
    assert "Role: VD" in text
    assert "Relationship: syster" in text

    updated = await server.call_tool(
        "update_contact",
        {
            "contact_id": contact["id"],
            "expected_version": contact["version"],
            "idempotency_key": "profile-redact-0002",
            "changes": {"address": "Annan väg 9"},
        },
    )
    assert "Annan väg 9" in model_text(updated)

    listed = await server.call_tool("list_contacts", {})
    row = listed.structured_content["contacts"][0]
    assert (row["relationship"], row["organization"], row["role"]) == ("syster", "Acme AB", "VD")
    assert "address" not in row
    assert "Acme AB" in model_text(listed)
    assert "Annan väg" not in model_text(listed)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    ("field", "limit"),
    [("relationship", 80), ("organization", 200), ("role", 120), ("address", 500)],
)
async def test_over_long_profile_values_are_rejected(field: str, limit: int) -> None:
    server = make_server()

    with pytest.raises(ToolError):
        await server.call_tool(
            "create_contact",
            {
                "display_name": "Anna",
                "idempotency_key": "profile-long-create-1",
                field: "x" * (limit + 1),
            },
        )
    ok = await server.call_tool(
        "create_contact",
        {"display_name": "Anna", "idempotency_key": "profile-long-create-2", field: "x" * limit},
    )
    contact = ok.structured_content["contact"]
    with pytest.raises(ToolError):
        await server.call_tool(
            "update_contact",
            {
                "contact_id": contact["id"],
                "expected_version": contact["version"],
                "idempotency_key": "profile-long-update-1",
                "changes": {field: "x" * (limit + 1)},
            },
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_create_replay_with_the_same_profile_returns_the_same_contact() -> None:
    server = make_server()
    args = {
        "display_name": "Anna",
        "idempotency_key": "profile-replay-0001",
        "organization": "Acme AB",
    }
    first = await server.call_tool("create_contact", args)
    second = await server.call_tool("create_contact", args)
    assert first.structured_content["contact"]["id"] == second.structured_content["contact"]["id"]

    # The same key with a different profile is an idempotency conflict, not a silent overwrite.
    conflict = await server.call_tool("create_contact", {**args, "organization": "Other AB"})
    assert conflict.is_error
    assert conflict.structured_content["code"] == "conflict"


SLACK = "https://acme.slack.com/team/U01ABC23DEF"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_slack_profile_is_normalized_updated_cleared_and_checked() -> None:
    server = make_server()

    created = await server.call_tool(
        "create_contact",
        {
            "display_name": "Anna Lind",
            "idempotency_key": "slack-create-0001",
            "slack": "acme.slack.com/team/U01ABC23DEF?utm=1",
        },
    )
    contact = created.structured_content["contact"]
    assert contact["slack"] == SLACK

    # The link is a contact detail like the address: the Contact app and the model read it.
    context = await server.call_tool("get_contact_context", {"contact_id": contact["id"]})
    assert context.structured_content["contact"]["slack"] == SLACK

    refused_update = await server.call_tool(
        "update_contact",
        {
            "contact_id": contact["id"],
            "expected_version": contact["version"],
            "idempotency_key": "slack-update-0001",
            "changes": {"slack": "https://evil.com/team/U01ABC23DEF"},
        },
    )
    assert refused_update.is_error
    assert refused_update.structured_content["code"] == "validation_error"

    # Another field is changed: the link stays. Naming it in clear empties it.
    renamed = await server.call_tool(
        "update_contact",
        {
            "contact_id": contact["id"],
            "expected_version": contact["version"],
            "idempotency_key": "slack-update-0002",
            "changes": {"role": "VD"},
        },
    )
    after = renamed.structured_content["contact"]
    assert after["slack"] == SLACK
    cleared = await server.call_tool(
        "update_contact",
        {
            "contact_id": contact["id"],
            "expected_version": after["version"],
            "idempotency_key": "slack-update-0003",
            "changes": {},
            "clear": ["slack"],
        },
    )
    assert cleared.structured_content["contact"]["slack"] is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_slack_link_that_is_not_a_slack_profile_is_refused_on_create() -> None:
    server = make_server()

    refused = await server.call_tool(
        "create_contact",
        {
            "display_name": "Anna Lind",
            "idempotency_key": "slack-create-0002",
            "slack": "javascript:alert(1)",
        },
    )
    assert refused.is_error
    assert refused.structured_content["code"] == "validation_error"
