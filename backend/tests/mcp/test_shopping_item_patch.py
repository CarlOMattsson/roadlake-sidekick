"""update_shopping_item changes only the fields it sends; `clear` empties, null is not sent."""

from decimal import Decimal
from typing import Any

import pytest
from fastmcp import Client
from fastmcp.client.client import CallToolResult
from fastmcp.exceptions import ToolError

from sidekick.api.app import create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings


def _data(result: CallToolResult) -> dict[str, Any]:
    assert result.structured_content is not None
    return result.structured_content


@pytest.mark.asyncio
@pytest.mark.integration
async def test_update_shopping_item_changes_only_sent_fields() -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    user_id = container.auth.provision_user("owner", "Owner")
    actor = Actor(user_id, frozenset({"shopping:read", "shopping:write"}))
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    async with Client(server) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        description = tools["update_shopping_item"].description or ""
        assert "Omitted optional fields are cleared" not in description
        assert "Null in item means not sent" in description

        created = await client.call_tool(
            "create_shopping_list", {"name": "Veckohandel", "idempotency_key": "patch-list-001"}
        )
        list_id = _data(created)["shopping_list"]["id"]
        added = await client.call_tool(
            "add_shopping_items",
            {
                "list_id": list_id,
                "items": [
                    {
                        "client_ref": "milk",
                        "name": "Mjölk",
                        "store": "ICA",
                        "offer": {
                            "price": "29.90",
                            "valid_from": "2026-10-01",
                            "valid_until": "2026-12-31",
                            "source": "ICA-appen",
                            "checked_on": "2026-10-27",
                        },
                    }
                ],
                "idempotency_key": "patch-add-001",
            },
        )
        item_id = _data(added)["items"][0]["item"]["id"]

        # Sending only name and quantity keeps store and offer.
        quantified = await client.call_tool(
            "update_shopping_item",
            {
                "item_id": item_id,
                "item": {"name": "Mjölk", "quantity": "2"},
                "version": 1,
                "idempotency_key": "patch-quantity-001",
            },
        )
        item = _data(quantified)["item"]
        assert item["version"] == 2
        assert Decimal(str(item["quantity"])) == Decimal("2")
        assert item["store"] == "ICA"
        assert item["offer"] is not None
        assert Decimal(str(item["offer"]["price"])) == Decimal("29.90")

        # Naming store in clear empties it; the omitted offer is still kept.
        unstored = await client.call_tool(
            "update_shopping_item",
            {
                "item_id": item_id,
                "item": {"name": "Mjölk"},
                "clear": ["store"],
                "version": 2,
                "idempotency_key": "patch-store-null-001",
            },
        )
        item = _data(unstored)["item"]
        assert item["store"] is None
        assert item["offer"] is not None
        assert Decimal(str(item["quantity"])) == Decimal("2")

        # Naming offer in clear empties it and leaves the quantity alone.
        unoffered = await client.call_tool(
            "update_shopping_item",
            {
                "item_id": item_id,
                "item": {"name": "Mjölk"},
                "clear": ["offer"],
                "version": 3,
                "idempotency_key": "patch-offer-null-001",
            },
        )
        item = _data(unoffered)["item"]
        assert item["offer"] is None
        assert item["store"] is None
        assert Decimal(str(item["quantity"])) == Decimal("2")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_update_shopping_item_without_name_keeps_stored_name() -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    user_id = container.auth.provision_user("owner", "Owner")
    actor = Actor(user_id, frozenset({"shopping:read", "shopping:write"}))
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    async with Client(server) as client:
        created = await client.call_tool(
            "create_shopping_list", {"name": "Veckohandel", "idempotency_key": "name-list-001"}
        )
        list_id = _data(created)["shopping_list"]["id"]
        added = await client.call_tool(
            "add_shopping_items",
            {
                "list_id": list_id,
                "items": [{"client_ref": "milk", "name": "Mjölk"}],
                "idempotency_key": "name-add-001",
            },
        )
        item_id = _data(added)["items"][0]["item"]["id"]

        # Sending only quantity keeps the stored name.
        quantified = await client.call_tool(
            "update_shopping_item",
            {
                "item_id": item_id,
                "item": {"quantity": "3"},
                "version": 1,
                "idempotency_key": "name-keep-001",
            },
        )
        item = _data(quantified)["item"]
        assert item["name"] == "Mjölk"
        assert item["version"] == 2
        assert Decimal(str(item["quantity"])) == Decimal("3")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_update_shopping_item_refuses_a_blank_name() -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    user_id = container.auth.provision_user("owner", "Owner")
    actor = Actor(user_id, frozenset({"shopping:read", "shopping:write"}))
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    async with Client(server) as client:
        created = await client.call_tool(
            "create_shopping_list", {"name": "Veckohandel", "idempotency_key": "blank-list-001"}
        )
        list_id = _data(created)["shopping_list"]["id"]
        added = await client.call_tool(
            "add_shopping_items",
            {
                "list_id": list_id,
                "items": [{"client_ref": "milk", "name": "Mjölk"}],
                "idempotency_key": "blank-add-001",
            },
        )
        item_id = _data(added)["items"][0]["item"]["id"]

        for index, name in enumerate(["", "   "]):
            with pytest.raises(ToolError):
                await client.call_tool(
                    "update_shopping_item",
                    {
                        "item_id": item_id,
                        "item": {"name": name, "quantity": "5"},
                        "version": 1,
                        "idempotency_key": f"blank-name-{index}-001",
                    },
                )

        # The refused updates changed nothing: the item is still version 1 with its name.
        listed = await client.call_tool(
            "get_shopping_list", {"list_id": list_id, "limit": 100, "offset": 0}
        )
        items = _data(listed)["items"]
        assert items[0]["name"] == "Mjölk"
        assert items[0]["version"] == 1


async def _seed_item(client: Client[Any], key: str) -> tuple[str, str]:
    """One list with one ICA milk row that has quantity 2 and a note; returns (list_id, item_id)."""

    created = await client.call_tool(
        "create_shopping_list", {"name": "Veckohandel", "idempotency_key": f"{key}-list"}
    )
    list_id = _data(created)["shopping_list"]["id"]
    added = await client.call_tool(
        "add_shopping_items",
        {
            "list_id": list_id,
            "items": [
                {
                    "client_ref": "milk",
                    "name": "Mjölk",
                    "quantity": "2",
                    "store": "ICA",
                    "note": "Ekologisk",
                }
            ],
            "idempotency_key": f"{key}-add",
        },
    )
    return list_id, _data(added)["items"][0]["item"]["id"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_rename_keeps_quantity_store_and_note() -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    user_id = container.auth.provision_user("owner", "Owner")
    actor = Actor(user_id, frozenset({"shopping:read", "shopping:write"}))
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    async with Client(server) as client:
        _, item_id = await _seed_item(client, "rename")

        renamed = await client.call_tool(
            "update_shopping_item",
            {
                "item_id": item_id,
                "item": {"name": "Hushållsmjölk"},
                "version": 1,
                "idempotency_key": "rename-name-001",
            },
        )
        item = _data(renamed)["item"]
        assert item["name"] == "Hushållsmjölk"
        assert item["version"] == 2
        assert Decimal(str(item["quantity"])) == Decimal("2")
        assert item["store"] == "ICA"
        assert item["note"] == "Ekologisk"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_clearing_the_note_empties_only_the_note() -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    user_id = container.auth.provision_user("owner", "Owner")
    actor = Actor(user_id, frozenset({"shopping:read", "shopping:write"}))
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    async with Client(server) as client:
        _, item_id = await _seed_item(client, "clear-note")

        cleared = await client.call_tool(
            "update_shopping_item",
            {
                "item_id": item_id,
                "item": {},
                "clear": ["note"],
                "version": 1,
                "idempotency_key": "clear-note-001",
            },
        )
        item = _data(cleared)["item"]
        assert item["note"] is None
        assert item["name"] == "Mjölk"
        assert item["store"] == "ICA"
        assert Decimal(str(item["quantity"])) == Decimal("2")
        assert item["version"] == 2


@pytest.mark.asyncio
@pytest.mark.integration
async def test_stale_version_is_refused_and_changes_nothing() -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    user_id = container.auth.provision_user("owner", "Owner")
    actor = Actor(user_id, frozenset({"shopping:read", "shopping:write"}))
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    async with Client(server) as client:
        list_id, item_id = await _seed_item(client, "stale")
        await client.call_tool(
            "update_shopping_item",
            {
                "item_id": item_id,
                "item": {"quantity": "3"},
                "version": 1,
                "idempotency_key": "stale-first-001",
            },
        )

        stale = await client.call_tool(
            "update_shopping_item",
            {
                "item_id": item_id,
                "item": {"name": "Annan mjölk"},
                "version": 1,
                "idempotency_key": "stale-second-001",
            },
            raise_on_error=False,
        )
        assert stale.is_error
        assert stale.structured_content is not None
        assert stale.structured_content["code"] == "conflict"

        listed = await client.call_tool(
            "get_shopping_list", {"list_id": list_id, "limit": 100, "offset": 0}
        )
        item = _data(listed)["items"][0]
        assert item["name"] == "Mjölk"
        assert item["version"] == 2
        assert Decimal(str(item["quantity"])) == Decimal("3")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_same_key_and_arguments_replay_without_a_second_change() -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    user_id = container.auth.provision_user("owner", "Owner")
    actor = Actor(user_id, frozenset({"shopping:read", "shopping:write"}))
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    async with Client(server) as client:
        list_id, item_id = await _seed_item(client, "replay")
        arguments: dict[str, Any] = {
            "item_id": item_id,
            "item": {"quantity": "4"},
            "version": 1,
            "idempotency_key": "replay-qty-001",
        }

        first = _data(await client.call_tool("update_shopping_item", arguments))
        second = _data(await client.call_tool("update_shopping_item", arguments))
        assert second == first
        assert first["item"]["version"] == 2

        # The same key with other arguments is refused and the stored item is unchanged.
        other = await client.call_tool(
            "update_shopping_item",
            {**arguments, "item": {"quantity": "5"}},
            raise_on_error=False,
        )
        assert other.is_error

        listed = await client.call_tool(
            "get_shopping_list", {"list_id": list_id, "limit": 100, "offset": 0}
        )
        item = _data(listed)["items"][0]
        assert item["version"] == 2
        assert Decimal(str(item["quantity"])) == Decimal("4")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_null_fields_are_ignored_and_listed_and_change_nothing() -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    user_id = container.auth.provision_user("owner", "Owner")
    actor = Actor(user_id, frozenset({"shopping:read", "shopping:write"}))
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    async with Client(server) as client:
        list_id, item_id = await _seed_item(client, "null-ignored")

        # A client that fills in null for every optional property changes nothing.
        result = _data(
            await client.call_tool(
                "update_shopping_item",
                {
                    "item_id": item_id,
                    "item": {"name": None, "note": None, "store": None},
                    "version": 1,
                    "idempotency_key": "null-ignored-001",
                },
            )
        )
        assert sorted(result["ignored_nulls"]) == ["name", "note", "store"]

        listed = await client.call_tool(
            "get_shopping_list", {"list_id": list_id, "limit": 100, "offset": 0}
        )
        item = _data(listed)["items"][0]
        assert item["name"] == "Mjölk"
        assert item["note"] == "Ekologisk"
        assert item["store"] == "ICA"
        assert Decimal(str(item["quantity"])) == Decimal("2")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_field_given_in_item_and_named_in_clear_is_refused() -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    user_id = container.auth.provision_user("owner", "Owner")
    actor = Actor(user_id, frozenset({"shopping:read", "shopping:write"}))
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    async with Client(server) as client:
        list_id, item_id = await _seed_item(client, "conflict")

        refused = await client.call_tool(
            "update_shopping_item",
            {
                "item_id": item_id,
                "item": {"note": "Laktosfri"},
                "clear": ["note"],
                "version": 1,
                "idempotency_key": "conflict-001",
            },
            raise_on_error=False,
        )
        assert refused.is_error
        assert "note: also named in clear" in str(refused.content)

        listed = await client.call_tool(
            "get_shopping_list", {"list_id": list_id, "limit": 100, "offset": 0}
        )
        item = _data(listed)["items"][0]
        assert item["note"] == "Ekologisk"
        assert item["version"] == 1
