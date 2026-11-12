"""MCP behavior tests for Contact tools (create, update, archive, restore, aliases)."""

import re

import pytest

from sidekick.api.app import create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.mcp.sidekick_app import SIDEKICK_APP_URI
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings


@pytest.mark.asyncio
@pytest.mark.integration
async def test_mcp_contact_lifecycle_tools() -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    user_id = container.auth.provision_user("owner", "Owner")
    actor = Actor(user_id, frozenset({"contacts:read", "contacts:write"}))

    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    # 1. Create a Contact via MCP
    result = await server.call_tool(
        "create_contact",
        {
            "display_name": "Rasmus",
            "idempotency_key": "mcp-contact-create-001",
            "context_note": "MCP Created",
            "aliases": ["Raz"],
        },
    )
    contact = result.structured_content["contact"]
    assert result.content[0].text == f"Created contact Rasmus.\nContact {contact['id']} v1."
    assert contact["display_name"] == "Rasmus"
    assert len(contact["aliases"]) == 1

    # 2. Update the Contact via MCP
    update_res = await server.call_tool(
        "update_contact",
        {
            "contact_id": contact["id"],
            "expected_version": contact["version"],
            "idempotency_key": "mcp-contact-update-001",
            "changes": {"display_name": "Rasmus Updated"},
        },
    )
    updated = update_res.structured_content["contact"]
    assert update_res.content[0].text == (
        f"Updated contact Rasmus Updated.\nContact {contact['id']} v2."
    )
    assert updated["display_name"] == "Rasmus Updated"
    assert updated["version"] == 2


@pytest.mark.asyncio
@pytest.mark.integration
async def test_mcp_list_contacts_echoes_the_search_it_answered() -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    user_id = container.auth.provision_user("owner", "Owner")
    actor = Actor(user_id, frozenset({"contacts:read", "contacts:write"}))

    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    for name, key in (
        ("Anna Lind", "mcp-list-echo-create-001"),
        ("Anna Berg", "mcp-list-echo-create-002"),
    ):
        await server.call_tool("create_contact", {"display_name": name, "idempotency_key": key})

    # Without filters the page says so: no search text and active Contacts only.
    plain = await server.call_tool("list_contacts", {})
    assert plain.structured_content["q"] is None
    assert plain.structured_content["include_archived"] is False

    # The first page of a search echoes the search, and so does the page its cursor leads to.
    first = await server.call_tool("list_contacts", {"q": "anna", "limit": 1})
    assert first.structured_content["q"] == "anna"
    assert first.structured_content["include_archived"] is False
    assert first.structured_content["next_cursor"] is not None

    second = await server.call_tool(
        "list_contacts",
        {"q": "anna", "limit": 1, "cursor": first.structured_content["next_cursor"]},
    )
    assert second.structured_content["q"] == "anna"
    assert second.structured_content["include_archived"] is False
    assert len(second.structured_content["contacts"]) == 1

    archived = await server.call_tool("list_contacts", {"q": "berg", "include_archived": True})
    assert archived.structured_content["q"] == "berg"
    assert archived.structured_content["include_archived"] is True
    assert [c["display_name"] for c in archived.structured_content["contacts"]] == ["Anna Berg"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_mcp_list_contacts_zero_hits_points_to_search_before_creating() -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    user_id = container.auth.provision_user("owner", "Owner")
    actor = Actor(user_id, frozenset({"contacts:read", "contacts:write"}))

    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    await server.call_tool(
        "create_contact",
        {"display_name": "Anna Lind", "idempotency_key": "mcp-list-nomatch-create-001"},
    )

    # A search with no hits ends with the hint to try the fuzzy search before creating.
    miss = await server.call_tool("list_contacts", {"q": "Sarah"})
    assert miss.structured_content["contacts"] == []
    assert miss.content[0].text == (
        "No contacts found.\n"
        "No match by name or alias; try search (kinds contacts) before creating."
    )

    # A search with hits does not carry the hint, and the first line names the hit.
    hit = await server.call_tool("list_contacts", {"q": "anna"})
    assert "No match" not in hit.content[0].text
    assert hit.content[0].text.startswith("1 contact: Anna Lind.\n")

    # The tool description names the same fallback.
    tools = {tool.name: tool for tool in await server.list_tools()}
    assert 'kinds=["contacts"]' in (tools["list_contacts"].description or "")


# The Contact and relationship tools in contacts.py. Only the ones named in CARD_TOOLS open the
# work card; the rest stay card-less, so a host never opens a card for a plain list or link.
CONTACT_TOOLS = {
    "list_contacts",
    "get_contact_context",
    "list_task_contacts",
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
}
CARD_TOOLS = {"get_contact_context", "create_contact", "update_contact"}


@pytest.mark.asyncio
async def test_contact_card_is_opened_only_by_create_update_and_context() -> None:
    server = create_mcp_server(create_container(make_settings()), enable_auth=False)
    tools = {tool.name: tool for tool in await server.list_tools()}

    assert set(tools) >= CONTACT_TOOLS
    with_card = {
        name
        for name in CONTACT_TOOLS
        if (tools[name].meta or {}).get("ui", {}).get("resourceUri") == SIDEKICK_APP_URI
    }
    assert with_card == CARD_TOOLS


CONTACT_UUID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_mcp_contact_first_text_line_is_a_sentence_without_ids() -> None:
    # Voice mode reads block 1 only: the first line is a sentence, and the ids sit on line 2.
    factory = database_factory()
    container = create_container(make_settings(), factory)
    user_id = container.auth.provision_user("owner", "Owner")
    actor = Actor(
        user_id,
        frozenset(
            {
                "contacts:read",
                "contacts:write",
                "projects:read",
                "tasks:read",
            }
        ),
    )
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    created = await server.call_tool(
        "create_contact",
        {
            "display_name": "Rasmus",
            "relationship": "syster",
            "idempotency_key": "mcp-voice-contact-create-001",
        },
    )
    contact_id = created.structured_content["contact"]["id"]
    shown = await server.call_tool("get_contact_context", {"contact_id": contact_id})
    updated = await server.call_tool(
        "update_contact",
        {
            "contact_id": contact_id,
            "expected_version": 1,
            "idempotency_key": "mcp-voice-contact-update-001",
            "changes": {"display_name": "Rasmus Lind"},
        },
    )
    archived = await server.call_tool(
        "archive_contact",
        {
            "contact_id": contact_id,
            "expected_version": updated.structured_content["contact"]["version"],
            "idempotency_key": "mcp-voice-contact-archive-001",
        },
    )
    archived_version = archived.structured_content["contact"]["version"]
    restored = await server.call_tool(
        "restore_contact",
        {
            "contact_id": contact_id,
            "expected_version": archived_version,
            "idempotency_key": "mcp-voice-contact-restore-001",
        },
    )

    changed = {
        "create_contact": created,
        "get_contact_context": shown,
        "update_contact": updated,
        "archive_contact": archived,
        "restore_contact": restored,
    }
    for name, tool_result in changed.items():
        first_line = tool_result.content[0].text.split("\n", 1)[0]
        assert CONTACT_UUID.search(first_line) is None, name

    assert created.content[0].text == f"Created contact Rasmus.\nContact {contact_id} v1."
    assert shown.content[0].text.splitlines()[0] == "Rasmus (syster). No open tasks."
    assert updated.content[0].text.splitlines()[0] == "Updated contact Rasmus Lind."
    assert archived.content[0].text.splitlines()[0] == (
        "Archived contact Rasmus Lind; its data and links remain restorable."
    )
    assert restored.content[0].text.splitlines()[0] == "Restored contact Rasmus Lind."
    # Archive changes the version, so the new version must be on line 2 for the restore call.
    assert archived.content[0].text.splitlines()[1] == f"Contact {contact_id} v{archived_version}."
    assert restored.content[0].text.splitlines()[1].startswith(f"Contact {contact_id} v")
