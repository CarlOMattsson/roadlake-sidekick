"""The Contact address stays out of the list tools' structuredContent (D-058).

The Contact app receives the address through its own tool. This test pins the list tools.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast
from uuid import UUID

import pytest

from sidekick.api.app import Container, create_container
from sidekick.contacts.application.service import CreateContactCommand
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings

ADDRESS = "Hemlig gata 12, 111 22 Stockholm"
ORGANIZATION = "Acme AB"
SCOPES = frozenset(
    {
        "contacts:read",
        "contacts:write",
        "projects:read",
        "tasks:read",
        "tasks:write",
        "journal:read",
    }
)


def _setup() -> tuple[Container, Actor, UUID]:
    container = create_container(make_settings(), database_factory())
    owner_id = container.auth.provision_user("owner", "Owner")
    actor = Actor(owner_id, SCOPES)
    contact = container.contacts.create(
        actor,
        CreateContactCommand(
            display_name="Anna Lind",
            relationship="syster",
            organization=ORGANIZATION,
            role="VD",
            address=ADDRESS,
        ),
        "address-gateway-create",
    )
    return container, actor, contact.id


def _keys(value: Any) -> set[str]:
    """Every dict key at any depth of a JSON-compatible value."""
    if isinstance(value, Mapping):
        mapping = cast(Mapping[str, Any], value)
        return set(mapping) | {key for item in mapping.values() for key in _keys(item)}
    if isinstance(value, list):
        return {key for item in cast(list[Any], value) for key in _keys(item)}
    return set()


def _structured(result: Any) -> Mapping[str, Any]:
    structured = result.structured_content
    assert isinstance(structured, dict)
    return cast(Mapping[str, Any], structured)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_contacts_and_list_task_contacts_structured_content_has_no_address() -> None:
    container, actor, contact_id = _setup()
    task = container.tasks.create(actor, title="Ring Anna", idempotency_key="address-gateway-task")
    container.contacts.link_task(actor, contact_id, task.id, "address-gateway-link")
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    listed = await server.call_tool("list_contacts", {})
    linked = await server.call_tool("list_task_contacts", {"task_id": str(task.id)})

    assert _structured(listed)["contacts"][0]["organization"] == ORGANIZATION
    assert "address" not in _keys(_structured(listed))
    assert _structured(linked)["items"][0]["organization"] == ORGANIZATION
    assert "address" not in _keys(_structured(linked))
