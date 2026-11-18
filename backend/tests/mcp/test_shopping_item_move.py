"""update_shopping_item moves an item to another list when item.list_id names one."""

from decimal import Decimal
from typing import Any

import pytest
from fastmcp import Client
from fastmcp.client.client import CallToolResult

from sidekick.api.app import create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings


def _data(result: CallToolResult) -> dict[str, Any]:
    assert result.structured_content is not None
    return result.structured_content


async def _list(client: Client[Any], name: str, key: str) -> str:
    created = await client.call_tool("create_shopping_list", {"name": name, "idempotency_key": key})
    return _data(created)["shopping_list"]["id"]


async def _names(client: Client[Any], list_id: str) -> list[str]:
    read = await client.call_tool("get_shopping_list", {"list_id": list_id, "limit": 100})
    return [item["name"] for item in _data(read)["items"]]


async def _seed(client: Client[Any]) -> tuple[str, str, str]:
    """Groceries with one item and an empty pharmacy list; returns (groceries, pharmacy, item)."""

    groceries = await _list(client, "Matinköp", "move-list-a")
    pharmacy = await _list(client, "Apoteket", "move-list-b")
    added = await client.call_tool(
        "add_shopping_items",
        {
            "list_id": groceries,
            "items": [
                {
                    "client_ref": "paste",
                    "name": "Tandkräm",
                    "quantity": "2",
                    "unit": "st",
                    "store": "ICA",
                    "note": "Mint",
                }
            ],
            "idempotency_key": "move-add",
        },
    )
    return groceries, pharmacy, _data(added)["items"][0]["item"]["id"]


def _client(actor_scopes: frozenset[str] = frozenset({"shopping:read", "shopping:write"})):
    factory = database_factory()
    container = create_container(make_settings(), factory)
    user_id = container.auth.provision_user("owner", "Owner")
    actor = Actor(user_id, actor_scopes)
    return container, Client(
        create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_item_moves_to_another_list_with_its_fields() -> None:
    _, client = _client()
    async with client:
        groceries, pharmacy, item_id = await _seed(client)

        moved = _data(
            await client.call_tool(
                "update_shopping_item",
                {
                    "item_id": item_id,
                    "item": {"list_id": pharmacy},
                    "version": 1,
                    "idempotency_key": "move-001",
                },
            )
        )

        item = moved["item"]
        assert item["list_id"] == pharmacy
        assert item["version"] == 2
        assert (item["name"], item["unit"], item["store"], item["note"]) == (
            "Tandkräm",
            "st",
            "ICA",
            "Mint",
        )
        assert Decimal(str(item["quantity"])) == Decimal("2")
        assert moved["list_name"] == "Apoteket"
        assert moved["open_count"] == 1
        assert await _names(client, groceries) == []
        assert await _names(client, pharmacy) == ["Tandkräm"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_move_replays_with_the_same_key_and_refuses_other_arguments() -> None:
    _, client = _client()
    async with client:
        groceries, pharmacy, item_id = await _seed(client)
        arguments: dict[str, Any] = {
            "item_id": item_id,
            "item": {"list_id": pharmacy},
            "version": 1,
            "idempotency_key": "move-replay",
        }

        first = _data(await client.call_tool("update_shopping_item", arguments))
        second = _data(await client.call_tool("update_shopping_item", arguments))
        assert second == first

        other = await client.call_tool(
            "update_shopping_item",
            {**arguments, "item": {"list_id": groceries}},
            raise_on_error=False,
        )
        assert other.is_error
        assert await _names(client, pharmacy) == ["Tandkräm"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_move_to_an_archived_unknown_or_foreign_list_is_refused() -> None:
    container, client = _client()
    async with client:
        groceries, pharmacy, item_id = await _seed(client)
        archived = await _list(client, "Gammal", "move-list-old")
        await client.call_tool(
            "update_shopping_list",
            {
                "list_id": archived,
                "name": "Gammal",
                "archived": True,
                "version": 1,
                "idempotency_key": "move-archive",
            },
        )
        other_owner = container.auth.provision_user("other", "Other")
        foreign = container.shopping.create_list(
            Actor(other_owner, frozenset({"shopping:read", "shopping:write"})),
            "Någon annans",
            idempotency_key="move-foreign-list",
        ).shopping_list.id

        for target, key in (
            (archived, "move-to-archived"),
            ("00000000-0000-4000-8000-000000000000", "move-to-unknown"),
            (str(foreign), "move-to-foreign"),
        ):
            refused = await client.call_tool(
                "update_shopping_item",
                {
                    "item_id": item_id,
                    "item": {"list_id": target},
                    "version": 1,
                    "idempotency_key": key,
                },
                raise_on_error=False,
            )
            assert refused.is_error, target

        assert await _names(client, groceries) == ["Tandkräm"]
        assert await _names(client, pharmacy) == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_stale_version_stops_a_move_and_the_list_can_not_be_cleared() -> None:
    _, client = _client()
    async with client:
        groceries, pharmacy, item_id = await _seed(client)

        stale = await client.call_tool(
            "update_shopping_item",
            {
                "item_id": item_id,
                "item": {"list_id": pharmacy},
                "version": 7,
                "idempotency_key": "move-stale",
            },
            raise_on_error=False,
        )
        assert stale.is_error
        assert await _names(client, groceries) == ["Tandkräm"]

        cleared = await client.call_tool(
            "update_shopping_item",
            {
                "item_id": item_id,
                "item": {},
                "clear": ["list_id"],
                "version": 1,
                "idempotency_key": "move-clear",
            },
            raise_on_error=False,
        )
        assert cleared.is_error
