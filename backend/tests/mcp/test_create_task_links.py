"""MCP create_task links a Domain and Contacts in the same transaction as the Task.

One call replaces the 4-6 calls the owner needed before: create the Task, then link each Contact.
An unknown Contact fails the whole call, so no Task is left behind.
"""

from typing import Any

import pytest
from fastmcp import Client

from sidekick.api.app import create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.types import Actor, new_uuid7
from tests.db import database_factory
from tests.support.settings import make_settings

SCOPES = frozenset(
    {
        "projects:read",
        "projects:write",
        "tasks:read",
        "tasks:write",
        "contacts:read",
        "contacts:write",
    }
)


def _structured(tool_result: Any) -> dict[str, Any]:
    assert tool_result.structured_content is not None
    structured: dict[str, Any] = tool_result.structured_content
    return structured


@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_task_links_domain_and_two_contacts_in_one_call() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    actor = Actor(owner, SCOPES)
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        domain = _structured(
            await client.call_tool(
                "create_domain", {"name": "Hem", "idempotency_key": "link-task-domain"}
            )
        )["domain"]
        contact_ids: list[str] = []
        for index, name in enumerate(["Sara", "Bo"]):
            contact = _structured(
                await client.call_tool(
                    "create_contact",
                    {"display_name": name, "idempotency_key": f"link-task-contact-{index}"},
                )
            )["contact"]
            contact_ids.append(contact["id"])

        created = _structured(
            await client.call_tool(
                "create_task",
                {
                    "title": "Ring Sara om offerten",
                    "domain_id": domain["id"],
                    "contact_ids": contact_ids,
                    "idempotency_key": "link-task-create-001",
                },
            )
        )["task"]

        assert created["domain_id"] == domain["id"]
        assert created["project_id"] is None

        linked = _structured(
            await client.call_tool("list_task_contacts", {"task_id": created["id"]})
        )
        assert len(linked["items"]) == 2
        assert {item["id"] for item in linked["items"]} == set(contact_ids)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_task_with_unknown_contact_fails_and_creates_no_task() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    actor = Actor(owner, SCOPES)
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    title = "Ring okänd kontakt"

    async with Client(server) as client:
        contact = _structured(
            await client.call_tool(
                "create_contact",
                {"display_name": "Sara", "idempotency_key": "link-task-unknown-contact"},
            )
        )["contact"]
        unknown_id = str(new_uuid7())

        failed = await client.call_tool(
            "create_task",
            {
                "title": title,
                "contact_ids": [contact["id"], unknown_id],
                "idempotency_key": "link-task-unknown-001",
            },
            raise_on_error=False,
        )

        assert failed.is_error is True
        assert _structured(failed)["message"] == (
            "I could not find that. Check the name or search again."
        )
        assert [task for task in container.tasks.list(actor).items if task.title == title] == []

        # The failed attempt left no idempotency record behind either, so the same key
        # succeeds once the Contact list is valid.
        retried = _structured(
            await client.call_tool(
                "create_task",
                {
                    "title": title,
                    "contact_ids": [contact["id"]],
                    "idempotency_key": "link-task-unknown-001",
                },
            )
        )["task"]
        assert retried["title"] == title

        linked = _structured(
            await client.call_tool("list_task_contacts", {"task_id": retried["id"]})
        )
        assert [item["id"] for item in linked["items"]] == [contact["id"]]
