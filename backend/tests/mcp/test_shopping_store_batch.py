"""Shop mode (store filter), batch purchase and merge_duplicates for the shopping MCP tools."""

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


def _text(result: CallToolResult) -> str:
    return result.content[0].text


async def _client_with_list(prefix: str) -> tuple[Client, str]:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    user_id = container.auth.provision_user("owner", "Owner")
    actor = Actor(user_id, frozenset({"shopping:read", "shopping:write"}))
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    client = Client(server)
    await client.__aenter__()
    created = await client.call_tool(
        "create_shopping_list", {"name": "Veckohandel", "idempotency_key": f"{prefix}-list-001"}
    )
    return client, _data(created)["shopping_list"]["id"]


async def _add(
    client: Client, list_id: str, key: str, items: list[dict[str, Any]], **extra: Any
) -> CallToolResult:
    batch = [{"client_ref": f"r{number}", **item} for number, item in enumerate(items)]
    return await client.call_tool(
        "add_shopping_items",
        {"list_id": list_id, "items": batch, "idempotency_key": key, **extra},
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_shopping_list_store_keeps_that_store_and_unmarked_items() -> None:
    client, list_id = await _client_with_list("store")
    try:
        await _add(
            client,
            list_id,
            "store-add-001",
            [
                {"name": "Mjölk", "store": "ICA"},
                {"name": "Skruv", "store": "Bauhaus"},
                {"name": "Bröd"},
                {"name": "Ost", "store": "ica"},
            ],
        )
        shown = await client.call_tool("get_shopping_list", {"list_id": list_id, "store": " Ica "})
        data = _data(shown)
        assert sorted(item["name"] for item in data["items"]) == ["Bröd", "Mjölk", "Ost"]
        assert data["store"] == "Ica"
        lines = _text(shown).splitlines()
        # Line 1 is a spoken sentence without ids; the shop is named in it.
        assert (
            lines[0] == "Shopping list Veckohandel at Ica has 3 items to buy and 0 already bought."
        )
        assert list_id not in lines[0]
        assert "Skruv" not in _text(shown)

        whole = await client.call_tool("get_shopping_list", {"list_id": list_id})
        assert len(_data(whole)["items"]) == 4
        assert _data(whole)["store"] is None
        blank = await client.call_tool("get_shopping_list", {"list_id": list_id, "store": "  "})
        assert len(_data(blank)["items"]) == 4
    finally:
        await client.__aexit__(None, None, None)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_set_shopping_items_purchased_is_atomic_and_idempotent() -> None:
    client, list_id = await _client_with_list("batch")
    try:
        added = await _add(
            client, list_id, "batch-add-001", [{"name": "Mjölk"}, {"name": "Bröd"}, {"name": "Ost"}]
        )
        items = [entry["item"] for entry in _data(added)["items"]]
        targets = [{"item_id": item["id"], "version": item["version"]} for item in items[:2]]
        arguments = {"items": targets, "purchased": True, "idempotency_key": "batch-buy-001"}

        bought = await client.call_tool("set_shopping_items_purchased", arguments)
        assert [item["purchased"] for item in _data(bought)["items"]] == [True, True]
        assert [item["version"] for item in _data(bought)["items"]] == [2, 2]
        first_line = _text(bought).splitlines()[0]
        assert first_line == "Marked Mjölk and Bröd as bought."

        # The same key and arguments replay the first answer; nothing changes again.
        replay = await client.call_tool("set_shopping_items_purchased", arguments)
        assert _data(replay) == _data(bought)

        # A stale version on an item that is not yet bought fails the whole call: the fresh item
        # stays wanted. (A stale version on an already-bought item is skipped instead.)
        stale = {
            "items": [
                {"item_id": items[0]["id"], "version": 1},
                {"item_id": items[2]["id"], "version": 99},
            ],
            "purchased": True,
            "idempotency_key": "batch-buy-002",
        }
        failed = await client.call_tool("set_shopping_items_purchased", stale, raise_on_error=False)
        assert failed.is_error
        # The conflict names the item and says what to do; no id or version on line 1.
        assert _text(failed) == "Ost changed (bought in the app?). Re-read the list and retry."
        shown = _data(await client.call_tool("get_shopping_list", {"list_id": list_id}))
        by_name = {item["name"]: item for item in shown["items"]}
        assert by_name["Ost"]["purchased"] is False
        assert by_name["Ost"]["version"] == 1

        # Wanted again, from the versions the purchase returned.
        reopen = {
            "items": [
                {"item_id": item["id"], "version": item["version"]}
                for item in _data(bought)["items"]
            ],
            "purchased": False,
            "idempotency_key": "batch-reopen-001",
        }
        reopened = await client.call_tool("set_shopping_items_purchased", reopen)
        assert [item["purchased"] for item in _data(reopened)["items"]] == [False, False]

        with pytest.raises(ToolError):
            await client.call_tool(
                "set_shopping_items_purchased",
                {"items": [], "purchased": True, "idempotency_key": "batch-empty-001"},
            )
        with pytest.raises(ToolError):
            await client.call_tool(
                "set_shopping_items_purchased",
                {
                    "items": [targets[0], targets[0]],
                    "purchased": True,
                    "idempotency_key": "batch-twice-001",
                },
            )
    finally:
        await client.__aexit__(None, None, None)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_set_shopping_items_purchased_skips_items_already_bought() -> None:
    client, list_id = await _client_with_list("skip")
    try:
        added = await _add(
            client, list_id, "skip-add-001", [{"name": "Mjölk"}, {"name": "Ägg"}, {"name": "Ost"}]
        )
        items = {e["item"]["name"]: e["item"] for e in _data(added)["items"]}
        milk, eggs, cheese = items["Mjölk"], items["Ägg"], items["Ost"]
        # Milk is ticked in the card first, so the version Claude holds for it is stale.
        await client.call_tool(
            "set_shopping_item_purchased",
            {
                "item_id": milk["id"],
                "purchased": True,
                "version": milk["version"],
                "idempotency_key": "skip-card-001",
            },
        )

        arguments = {
            "items": [
                {"item_id": milk["id"], "version": milk["version"]},
                {"item_id": eggs["id"], "version": eggs["version"]},
            ],
            "purchased": True,
            "idempotency_key": "skip-buy-001",
        }
        bought = await client.call_tool("set_shopping_items_purchased", arguments)
        data = _data(bought)
        assert data["unchanged_item_ids"] == [milk["id"]]
        by_name = {item["name"]: item for item in data["items"]}
        assert by_name["Mjölk"]["purchased"] is True
        assert by_name["Mjölk"]["version"] == 2  # the card's change, not bumped again
        assert by_name["Ägg"]["purchased"] is True
        assert by_name["Ägg"]["version"] == 2
        first_line = _text(bought).splitlines()[0]
        assert first_line == "Marked Ägg as bought. Mjölk was already bought."
        assert milk["id"] not in first_line

        # Replay of the same key gives the same answer.
        replay = await client.call_tool("set_shopping_items_purchased", arguments)
        assert _data(replay) == data

        # Only already-bought items: nothing changes and the answer says so.
        again = await client.call_tool(
            "set_shopping_items_purchased",
            {
                "items": [
                    {"item_id": milk["id"], "version": 1},
                    {"item_id": eggs["id"], "version": 1},
                ],
                "purchased": True,
                "idempotency_key": "skip-buy-002",
            },
        )
        assert _data(again)["unchanged_item_ids"] == [milk["id"], eggs["id"]]
        assert _text(again).splitlines()[0] == (
            "Nothing to mark: Mjölk and Ägg were already bought."
        )

        # A stale version on an item that is NOT in the asked state still fails the whole call,
        # and the others in the call stay as they were.
        await client.call_tool(
            "update_shopping_item",
            {
                "item_id": cheese["id"],
                "item": {"quantity": "2"},
                "version": cheese["version"],
                "idempotency_key": "skip-edit-001",
            },
        )
        mixed = await client.call_tool(
            "set_shopping_items_purchased",
            {
                "items": [
                    {"item_id": eggs["id"], "version": 1},
                    {"item_id": cheese["id"], "version": cheese["version"]},
                ],
                "purchased": True,
                "idempotency_key": "skip-buy-003",
            },
            raise_on_error=False,
        )
        assert mixed.is_error
        assert _text(mixed) == "Ost changed (bought in the app?). Re-read the list and retry."
        shown = _data(await client.call_tool("get_shopping_list", {"list_id": list_id}))
        by_name = {item["name"]: item for item in shown["items"]}
        assert by_name["Ost"]["purchased"] is False
        assert by_name["Ägg"]["purchased"] is True
    finally:
        await client.__aexit__(None, None, None)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_set_shopping_item_purchased_again_with_old_version_says_already() -> None:
    client, list_id = await _client_with_list("single")
    try:
        added = await _add(client, list_id, "single-add-001", [{"name": "Mjölk"}])
        milk = _data(added)["items"][0]["item"]
        bought = await client.call_tool(
            "set_shopping_item_purchased",
            {
                "item_id": milk["id"],
                "purchased": True,
                "version": milk["version"],
                "idempotency_key": "single-buy-001",
            },
        )
        assert _data(bought)["item"]["version"] == 2
        assert _text(bought).splitlines()[0] == "Marked Mjölk as bought."

        # Said again with the version from before: nothing changes and no conflict is raised.
        again = await client.call_tool(
            "set_shopping_item_purchased",
            {
                "item_id": milk["id"],
                "purchased": True,
                "version": milk["version"],
                "idempotency_key": "single-buy-002",
            },
        )
        assert not again.is_error
        assert _data(again)["item"]["version"] == 2
        assert _text(again).splitlines()[0] == "Mjölk was already bought."

        reopened = await client.call_tool(
            "set_shopping_item_purchased",
            {
                "item_id": milk["id"],
                "purchased": False,
                "version": 2,
                "idempotency_key": "single-back-001",
            },
        )
        assert _data(reopened)["item"]["version"] == 3
        assert _text(reopened).splitlines()[0] == "Put Mjölk back on the list."
        again_open = await client.call_tool(
            "set_shopping_item_purchased",
            {
                "item_id": milk["id"],
                "purchased": False,
                "version": 2,
                "idempotency_key": "single-back-002",
            },
        )
        assert not again_open.is_error
        assert _data(again_open)["item"]["version"] == 3
        assert _text(again_open).splitlines()[0] == "Mjölk was already not bought."

        # A real change (bought) with the version from before still conflicts.
        failed = await client.call_tool(
            "set_shopping_item_purchased",
            {
                "item_id": milk["id"],
                "purchased": True,
                "version": 2,
                "idempotency_key": "single-buy-003",
            },
            raise_on_error=False,
        )
        assert failed.is_error
        assert _text(failed) == "Mjölk changed (bought in the app?). Re-read the list and retry."
    finally:
        await client.__aexit__(None, None, None)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_add_shopping_items_merge_duplicates_adds_to_the_open_item() -> None:
    client, list_id = await _client_with_list("merge")
    try:
        await _add(
            client,
            list_id,
            "merge-add-001",
            [
                {"name": "Mjölk", "unit": "l", "quantity": "1"},
                {"name": "Mjölk", "unit": "st"},
                {"name": "Smör"},
            ],
        )
        merged = await _add(
            client,
            list_id,
            "merge-add-002",
            [
                {"name": "mjölk", "unit": "L", "quantity": "2"},
                {"name": "Smör"},
                {"name": "Smör", "quantity": "3"},
                {"name": "Kaffe"},
            ],
            merge_duplicates=True,
        )
        data = _data(merged)
        assert data["merged_count"] == 3
        assert [entry["merged"] for entry in data["items"]] == [True, True, True, False]
        milk = data["items"][0]["item"]
        assert Decimal(str(milk["quantity"])) == Decimal("3")
        assert milk["version"] == 2
        butter = data["items"][2]["item"]
        assert Decimal(str(butter["quantity"])) == Decimal("5")
        sentence = _text(merged).splitlines()[0]
        assert (
            sentence == "Added Kaffe to Veckohandel. "
            "Mjölk (now 3 l) and Smör (now 5) were already on the list."
        )
        assert "(merged, now 3 l" in _text(merged)

        shown = _data(await client.call_tool("get_shopping_list", {"list_id": list_id}))
        # "Mjölk" (l), "Mjölk" (st), "Smör" and the new "Kaffe": no extra rows for merged inputs.
        assert len(shown["items"]) == 4

        # Without the flag the same names make new rows, and a bought item is not a merge target.
        plain = await _add(client, list_id, "merge-add-003", [{"name": "Kaffe"}])
        assert _data(plain)["merged_count"] == 0
        assert _data(plain)["items"][0]["merged"] is False
        bought = next(item for item in shown["items"] if item["name"] == "Kaffe")
        await client.call_tool(
            "set_shopping_item_purchased",
            {
                "item_id": bought["id"],
                "purchased": True,
                "version": bought["version"],
                "idempotency_key": "merge-buy-001",
            },
        )
        again = await _add(
            client,
            list_id,
            "merge-add-004",
            [{"name": "Te"}, {"name": "Te"}],
            merge_duplicates=True,
        )
        assert _data(again)["merged_count"] == 1
        assert _data(again)["items"][1]["item"]["id"] == _data(again)["items"][0]["item"]["id"]
        assert _data(again)["items"][1]["item"]["version"] == 1
    finally:
        await client.__aexit__(None, None, None)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_open_count_follows_adds_merges_and_purchases() -> None:
    client, list_id = await _client_with_list("open")
    try:
        added = await _add(
            client,
            list_id,
            "open-add-001",
            [{"name": "Mjölk"}, {"name": "Smör"}, {"name": "Ägg"}],
        )
        assert _data(added)["open_count"] == 3

        more = await _add(client, list_id, "open-add-002", [{"name": "Kaffe"}])
        assert _data(more)["open_count"] == 4

        milk = _data(added)["items"][0]["item"]
        bought = await client.call_tool(
            "set_shopping_item_purchased",
            {
                "item_id": milk["id"],
                "purchased": True,
                "version": milk["version"],
                "idempotency_key": "open-buy-001",
            },
        )
        assert _data(bought)["open_count"] == 3

        # A merge into an open item adds no open row; a bought item is not a merge target.
        merged = await _add(
            client,
            list_id,
            "open-add-003",
            [{"name": "Smör"}, {"name": "Mjölk"}],
            merge_duplicates=True,
        )
        assert _data(merged)["merged_count"] == 1
        assert _data(merged)["open_count"] == 4
    finally:
        await client.__aexit__(None, None, None)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_open_count_on_batch_purchase_counts_the_one_list() -> None:
    client, list_id = await _client_with_list("batchopen")
    try:
        added = await _add(
            client,
            list_id,
            "batchopen-add-001",
            [{"name": "Mjölk"}, {"name": "Smör"}, {"name": "Ägg"}],
        )
        first, second, _third = (entry["item"] for entry in _data(added)["items"])
        bought = await client.call_tool(
            "set_shopping_items_purchased",
            {
                "items": [
                    {"item_id": first["id"], "version": first["version"]},
                    {"item_id": second["id"], "version": second["version"]},
                ],
                "purchased": True,
                "idempotency_key": "batchopen-buy-001",
            },
        )
        assert _data(bought)["open_count"] == 1
    finally:
        await client.__aexit__(None, None, None)
