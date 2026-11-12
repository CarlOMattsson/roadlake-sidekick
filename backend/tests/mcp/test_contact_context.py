"""MCP relationship and contact context tools integration tests."""

import pytest
from fastmcp import Client, FastMCP

from sidekick.api.app import Container, create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.mcp.text import CONTACT_CARD_NOTE
from sidekick.shared.types import Actor, new_uuid7
from tests.db import database_factory
from tests.support.settings import make_settings


@pytest.mark.asyncio
@pytest.mark.integration
async def test_mcp_relationships_and_context() -> None:
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
                "projects:write",
                "tasks:read",
                "tasks:write",
            }
        ),
    )

    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    # 1. Create a Contact
    c_res = await server.call_tool(
        "create_contact", {"display_name": "Rasmus", "idempotency_key": "context-test-contact"}
    )
    contact = c_res.structured_content["contact"]

    # 2. Create a Project
    d_res = await server.call_tool(
        "create_domain", {"name": "Operations", "idempotency_key": "context-test-domain"}
    )
    p_res = await server.call_tool(
        "create_project",
        {
            "title": "Sidekick Project",
            "domain_id": d_res.structured_content["domain"]["id"],
            "idempotency_key": "context-test-project",
        },
    )
    project = p_res.structured_content["project"]

    # 3. Link via MCP
    link_res = await server.call_tool(
        "link_contact_to_project",
        {
            "contact_id": contact["id"],
            "project_id": project["id"],
            "idempotency_key": "mcp-link-001",
        },
    )
    assert link_res.structured_content["linked"] is True

    # 4. Get Contact Context via MCP
    ctx_res = await server.call_tool("get_contact_context", {"contact_id": contact["id"]})
    assert len(ctx_res.structured_content["projects"]["items"]) == 1
    assert ctx_res.structured_content["projects"]["items"][0]["title"] == "Sidekick Project"
    # The model text ends with CONTACT_CARD_NOTE so Claude does not repeat the card.
    assert ctx_res.content[0].text.endswith(CONTACT_CARD_NOTE)


OWNER_SCOPES = frozenset(
    {"contacts:read", "contacts:write", "projects:read", "tasks:read", "tasks:write"}
)


def _server_for(container: Container, actor: Actor) -> FastMCP:
    return create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_task_contacts_pages_only_the_contacts_linked_to_that_task() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    actor = Actor(owner, OWNER_SCOPES)
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        task = await client.call_tool(
            "create_task", {"title": "Call the plumber", "idempotency_key": "task-contacts-task"}
        )
        task_id = task.structured_content["task"]["id"]
        linked_ids = []
        for index, name in enumerate(["Anna", "Bo"]):
            contact = await client.call_tool(
                "create_contact",
                {"display_name": name, "idempotency_key": f"task-contacts-person-{index}"},
            )
            contact_id = contact.structured_content["contact"]["id"]
            linked_ids.append(contact_id)
            await client.call_tool(
                "link_contact_to_task",
                {
                    "contact_id": contact_id,
                    "task_id": task_id,
                    "idempotency_key": f"task-contacts-link-{index}",
                },
            )
        await client.call_tool(
            "create_contact", {"display_name": "Unlinked", "idempotency_key": "task-contacts-other"}
        )

        first = await client.call_tool("list_task_contacts", {"task_id": task_id, "limit": 1})
        assert len(first.structured_content["items"]) == 1
        assert first.structured_content["next_cursor"] is not None
        second = await client.call_tool(
            "list_task_contacts",
            {
                "task_id": task_id,
                "limit": 1,
                "cursor": first.structured_content["next_cursor"],
            },
        )
        assert second.structured_content["next_cursor"] is None
        returned = [
            first.structured_content["items"][0],
            second.structured_content["items"][0],
        ]
        assert {item["id"] for item in returned} == set(linked_ids)
        # A summary carries the short profile fields but never the sensitive address.
        assert set(returned[0]) == {
            "id",
            "display_name",
            "archived",
            "updated_at",
            "version",
            "relationship",
            "organization",
            "role",
        }


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_task_contacts_refuses_foreign_and_missing_tasks_like_get_task() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    other = container.auth.provision_user("other-owner", "Other")
    owner_actor = Actor(owner, OWNER_SCOPES)
    other_actor = Actor(other, OWNER_SCOPES)
    owner_server = create_mcp_server(
        container, actor_provider=lambda: owner_actor, enable_auth=False
    )
    other_server = create_mcp_server(
        container, actor_provider=lambda: other_actor, enable_auth=False
    )

    async with Client(owner_server) as client:
        task = await client.call_tool(
            "create_task", {"title": "Private", "idempotency_key": "foreign-task-contacts"}
        )
    task_id = task.structured_content["task"]["id"]

    async with Client(other_server) as client:
        foreign = await client.call_tool(
            "list_task_contacts", {"task_id": task_id}, raise_on_error=False
        )
        foreign_get = await client.call_tool("get_task", {"task_id": task_id}, raise_on_error=False)
        missing = await client.call_tool(
            "list_task_contacts", {"task_id": str(new_uuid7())}, raise_on_error=False
        )

    assert foreign.is_error and foreign_get.is_error and missing.is_error
    assert foreign.structured_content["code"] == "not_found"
    assert foreign.structured_content["code"] == foreign_get.structured_content["code"]
    assert foreign.structured_content["code"] == missing.structured_content["code"]
    assert foreign.structured_content["message"] == foreign_get.structured_content["message"]
    assert task_id not in str(foreign.structured_content)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_task_contacts_requires_both_contacts_and_tasks_read() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    full = Actor(owner, OWNER_SCOPES)
    full_server = create_mcp_server(container, actor_provider=lambda: full, enable_auth=False)
    async with Client(full_server) as client:
        task = await client.call_tool(
            "create_task", {"title": "Scoped", "idempotency_key": "scope-task-contacts"}
        )
    task_id = task.structured_content["task"]["id"]

    for scopes in (frozenset({"contacts:read"}), frozenset({"tasks:read"})):
        server = _server_for(container, Actor(owner, scopes))
        async with Client(server) as client:
            denied = await client.call_tool(
                "list_task_contacts", {"task_id": task_id}, raise_on_error=False
            )
        assert denied.is_error
        assert denied.structured_content["code"] == "forbidden"


JOURNAL_OWNER_SCOPES = OWNER_SCOPES | {"journal:read", "journal:write"}
SECRET_BODY = "Hemlig dagboksbrödtext"
SECRET_SUMMARY = "Hemlig dagboksammanfattning"


async def _linked_journal_entry(
    client: Client, *, key: str, journal_date: str, title: str, contact_id: str
) -> str:
    source = await client.call_tool(
        "create_journal_source",
        {
            "source_type": "manual_text",
            "journal_date": journal_date,
            "raw_text": f"{SECRET_BODY} {key}",
            "idempotency_key": f"{key}-source",
        },
    )
    entry = await client.call_tool(
        "create_manual_journal_entry",
        {
            "source_id": source.structured_content["source"]["id"],
            "title": title,
            "summary": f"{SECRET_SUMMARY} {key}",
            "key_points": [],
            "project_ids": [],
            "task_ids": [],
            "contact_ids": [contact_id],
            "idempotency_key": f"{key}-entry",
        },
    )
    return str(entry.structured_content["entry"]["id"])


@pytest.mark.asyncio
@pytest.mark.integration
async def test_contact_context_lists_linked_journal_entries_newest_first_without_content() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    server = _server_for(container, Actor(owner, JOURNAL_OWNER_SCOPES))

    async with Client(server) as client:
        contact = await client.call_tool(
            "create_contact", {"display_name": "Rasmus", "idempotency_key": "journal-ctx-person"}
        )
        contact_id = contact.structured_content["contact"]["id"]
        older_id = await _linked_journal_entry(
            client,
            key="journal-ctx-older",
            journal_date="2026-10-01",
            title="Samtal om offerten",
            contact_id=contact_id,
        )
        newer_id = await _linked_journal_entry(
            client,
            key="journal-ctx-newer",
            journal_date="2026-10-20",
            title="Uppföljning med Rasmus",
            contact_id=contact_id,
        )
        other_contact = await client.call_tool(
            "create_contact", {"display_name": "Annan", "idempotency_key": "journal-ctx-other"}
        )
        await _linked_journal_entry(
            client,
            key="journal-ctx-unlinked",
            journal_date="2026-10-25",
            title="Ingen koppling",
            contact_id=other_contact.structured_content["contact"]["id"],
        )

        ctx = await client.call_tool("get_contact_context", {"contact_id": contact_id})

    journal = ctx.structured_content["journal_entries"]
    assert journal["readable"] is True
    assert journal["has_more"] is False
    assert [item["id"] for item in journal["items"]] == [newer_id, older_id]
    assert [item["journal_date"] for item in journal["items"]] == ["2026-10-20", "2026-10-01"]
    assert all(set(item) == {"id", "journal_date", "title"} for item in journal["items"])
    assert "Ingen koppling" not in str(ctx.structured_content)
    assert SECRET_BODY not in str(ctx.structured_content)
    assert SECRET_SUMMARY not in str(ctx.structured_content)
    assert SECRET_BODY not in str(ctx.content)
    assert SECRET_SUMMARY not in str(ctx.content)
    # D-060: linked entry titles reach the model in block 2 (the JSON), not only structuredContent.
    assert "Uppföljning med Rasmus" in str(ctx.content)
    assert "Uppföljning med Rasmus" in ctx.content[1].text
    assert newer_id in str(ctx.content)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_contact_context_caps_journal_entries_at_ten_and_says_more_exist() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    server = _server_for(container, Actor(owner, JOURNAL_OWNER_SCOPES))

    async with Client(server) as client:
        contact = await client.call_tool(
            "create_contact", {"display_name": "Bo", "idempotency_key": "journal-cap-person"}
        )
        contact_id = contact.structured_content["contact"]["id"]
        for index in range(11):
            await _linked_journal_entry(
                client,
                key=f"journal-cap-{index:02d}",
                journal_date=f"2026-09-{index + 1:02d}",
                title=f"Post {index + 1}",
                contact_id=contact_id,
            )

        ctx = await client.call_tool("get_contact_context", {"contact_id": contact_id})

    journal = ctx.structured_content["journal_entries"]
    assert len(journal["items"]) == 10
    assert journal["has_more"] is True
    assert journal["items"][0]["journal_date"] == "2026-09-11"
    assert "older links not shown" in str(ctx.content)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_contact_context_hides_another_owners_journal_entries() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    other = container.auth.provision_user("other-owner", "Other")
    owner_server = _server_for(container, Actor(owner, JOURNAL_OWNER_SCOPES))
    other_server = _server_for(container, Actor(other, JOURNAL_OWNER_SCOPES))

    async with Client(other_server) as client:
        foreign_contact = await client.call_tool(
            "create_contact", {"display_name": "Främling", "idempotency_key": "foreign-journal-p"}
        )
        foreign_entry_id = await _linked_journal_entry(
            client,
            key="foreign-journal-entry",
            journal_date="2026-10-10",
            title="Främlingens inlägg",
            contact_id=foreign_contact.structured_content["contact"]["id"],
        )

    async with Client(owner_server) as client:
        own_contact = await client.call_tool(
            "create_contact", {"display_name": "Egen", "idempotency_key": "own-journal-person"}
        )
        own_contact_id = own_contact.structured_content["contact"]["id"]
        own_entry_id = await _linked_journal_entry(
            client,
            key="own-journal-entry",
            journal_date="2026-10-11",
            title="Egen post",
            contact_id=own_contact_id,
        )
        ctx = await client.call_tool("get_contact_context", {"contact_id": own_contact_id})
        foreign = await client.call_tool(
            "get_contact_context",
            {"contact_id": foreign_contact.structured_content["contact"]["id"]},
            raise_on_error=False,
        )

    assert [item["id"] for item in ctx.structured_content["journal_entries"]["items"]] == [
        own_entry_id
    ]
    assert foreign_entry_id not in str(ctx.structured_content)
    assert foreign.is_error
    assert foreign.structured_content["code"] == "not_found"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_contact_context_without_journal_scope_shows_no_entries_and_no_error() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    full_server = _server_for(container, Actor(owner, JOURNAL_OWNER_SCOPES))

    async with Client(full_server) as client:
        contact = await client.call_tool(
            "create_contact", {"display_name": "Cecilia", "idempotency_key": "scope-journal-p"}
        )
        contact_id = contact.structured_content["contact"]["id"]
        await _linked_journal_entry(
            client,
            key="scope-journal-entry",
            journal_date="2026-10-12",
            title="Dold post",
            contact_id=contact_id,
        )

    no_journal = _server_for(container, Actor(owner, OWNER_SCOPES))
    async with Client(no_journal) as client:
        ctx = await client.call_tool("get_contact_context", {"contact_id": contact_id})

    assert ctx.structured_content["journal_entries"] == {
        "items": [],
        "has_more": False,
        "readable": False,
    }
    assert "Dold post" not in str(ctx.structured_content)
    assert "Dold post" not in str(ctx.content)
    assert "not readable with this session's scopes" in str(ctx.content)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_contact_context_says_when_a_contact_has_no_linked_journal_entries() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    server = _server_for(container, Actor(owner, JOURNAL_OWNER_SCOPES))

    async with Client(server) as client:
        contact = await client.call_tool(
            "create_contact", {"display_name": "Dora", "idempotency_key": "empty-journal-p"}
        )
        ctx = await client.call_tool(
            "get_contact_context", {"contact_id": contact.structured_content["contact"]["id"]}
        )

    assert ctx.structured_content["journal_entries"] == {
        "items": [],
        "has_more": False,
        "readable": True,
    }
    assert "Journal entries: no linked journal entries" in str(ctx.content)
