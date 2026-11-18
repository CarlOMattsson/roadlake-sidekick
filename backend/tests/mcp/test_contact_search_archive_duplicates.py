"""Contact search over what a row shows, reading an archived Contact, and same-name creates."""

from typing import Any

import pytest

from sidekick.api.app import create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings


def make_server() -> Any:
    container = create_container(make_settings(), database_factory())
    user_id = container.auth.provision_user("owner", "Owner")
    actor = Actor(
        user_id, frozenset({"contacts:read", "contacts:write", "projects:read", "tasks:read"})
    )
    return create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)


async def create(server: Any, key: str, name: str, **fields: str) -> dict[str, Any]:
    created = await server.call_tool(
        "create_contact", {"display_name": name, "idempotency_key": key, **fields}
    )
    return created.structured_content


async def archive(server: Any, contact: dict[str, Any], key: str) -> None:
    await server.call_tool(
        "archive_contact",
        {
            "contact_id": contact["id"],
            "expected_version": contact["version"],
            "idempotency_key": key,
        },
    )


async def found(server: Any, q: str) -> list[str]:
    result = await server.call_tool("list_contacts", {"q": q})
    return [contact["display_name"] for contact in result.structured_content["contacts"]]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_finds_organization_role_phone_email_and_combined_words() -> None:
    server = make_server()
    await create(
        server,
        "search-karin-0001",
        "Karin Berglund",
        organization="Berglunds Bygg AB",
        role="Vd",
        phone="070-123 45 67",
        email="karin@berglundsbygg.example",
    )
    await create(
        server, "search-anders-0001", "Anders Holm", organization="Holm Rör", role="Platschef"
    )

    assert await found(server, "bygg") == ["Karin Berglund"]
    assert await found(server, "Berglunds Bygg") == ["Karin Berglund"]
    assert await found(server, "vd") == ["Karin Berglund"]
    assert await found(server, "platschef") == ["Anders Holm"]
    assert await found(server, "0701") == ["Karin Berglund"]
    assert await found(server, "123 45") == ["Karin Berglund"]
    assert await found(server, "berglundsbygg") == ["Karin Berglund"]
    assert await found(server, "berglund karin") == ["Karin Berglund"]
    assert await found(server, "karin vd") == ["Karin Berglund"]
    assert await found(server, "anders bygg") == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_treats_wildcard_characters_as_text() -> None:
    server = make_server()
    await create(server, "search-wild-0001", "Karin Berglund", organization="Berglund AB")

    assert await found(server, "100%") == []
    assert await found(server, "a_b") == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_archived_contact_context_is_readable_and_marked_archived() -> None:
    server = make_server()
    contact = (await create(server, "archive-ctx-0001", "Björn Lund"))["contact"]
    await archive(server, contact, "archive-ctx-archive")

    context = await server.call_tool("get_contact_context", {"contact_id": contact["id"]})

    assert context.structured_content["contact"]["archived"] is True
    assert context.structured_content["contact"]["display_name"] == "Björn Lund"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_names_the_other_contacts_with_the_same_name_and_keeps_the_new_one() -> None:
    server = make_server()
    first = (await create(server, "dup-first-0001", "Karin Berglund", organization="Bygg AB"))[
        "contact"
    ]

    second = await create(server, "dup-second-0001", "  karin   BERGLUND ")

    assert second["contact"]["id"] != first["id"]
    assert [item["id"] for item in second["same_name_contacts"]] == [first["id"]]
    assert second["same_name_contacts"][0]["organization"] == "Bygg AB"
    # A retry with the same key still names only the other one, never the Contact itself.
    again = await create(server, "dup-second-0001", "  karin   BERGLUND ")
    assert again["contact"]["id"] == second["contact"]["id"]
    assert [item["id"] for item in again["same_name_contacts"]] == [first["id"]]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_does_not_name_an_archived_contact_or_a_different_name() -> None:
    server = make_server()
    old = (await create(server, "dup-old-0001", "Karin Berglund"))["contact"]
    await archive(server, old, "dup-old-archive")
    await create(server, "dup-other-0001", "Karin Berg")

    fresh = await create(server, "dup-fresh-0001", "Karin Berglund")

    assert fresh["same_name_contacts"] == []
