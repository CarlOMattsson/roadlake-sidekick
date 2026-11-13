"""`/companion/v1/shopping` (Inköp, ADR-005): the device credential, the two shopping capabilities,
versioned and idempotent writes, the body caps and the content-free log of the shopping routes.
Every answer is the shopping use case's own result, so the room reads what the MCP tools return."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic_core import to_jsonable_python

from sidekick.shared.auth import TOKEN_SCOPES
from sidekick.shopping.application.schemas import BatchItem
from tests.support.companion import bearer, companion_app, owner, owner_actor, paired_token

LISTS = "/companion/v1/shopping/lists"
ITEMS = "/companion/v1/shopping/items"
JSON = {"Content-Type": "application/json"}
READ_ONLY = frozenset({"companion:shopping:read"})
WRITE_ONLY = frozenset({"companion:shopping:write"})


def write(token: str, idempotency_key: str) -> dict[str, str]:
    return {**bearer(token), **JSON, "Idempotency-Key": idempotency_key}


def new_list(app: FastAPI, user_id: UUID, name: str = "Veckohandel") -> dict[str, Any]:
    shopping = app.state.container.shopping
    created = shopping.create_list(owner_actor(user_id), name, idempotency_key=f"seed-{uuid4()}")
    return created.shopping_list.model_dump(mode="json")


def seed_items(app: FastAPI, user_id: UUID, list_id: str, *names: str) -> list[dict[str, Any]]:
    batch = [BatchItem(name=name, client_ref=f"seed{index}") for index, name in enumerate(names)]
    shopping = app.state.container.shopping
    added = shopping.add_items(
        owner_actor(user_id), UUID(list_id), batch, idempotency_key=f"seed-{uuid4()}"
    )
    return [row.item.model_dump(mode="json") for row in added.items]


@pytest.mark.integration
@pytest.mark.parametrize("credential", ["none", "basic", "personal", "unknown"])
def test_missing_wrong_or_personal_credentials_are_401_on_a_read_and_a_write(
    credential: str,
) -> None:
    app = companion_app()
    user_id = owner(app)
    pat = app.state.container.auth.create_personal_token(user_id, "mcp", TOKEN_SCOPES)
    headers: dict[str, str] = {
        "none": {},
        "basic": {"Authorization": "Basic Zm9vOmJhcg=="},
        "personal": bearer(pat),
        "unknown": bearer("chcompanion_unknown"),
    }[credential]
    with TestClient(app) as client:
        read = client.get(LISTS, headers=headers)
        created = client.post(
            LISTS,
            headers={**headers, **JSON, "Idempotency-Key": "shop-unauth-0001"},
            json={"name": "A"},
        )
    for response in (read, created):
        assert response.status_code == 401
        assert response.json()["code"] == "unauthorized"
        assert response.json()["api_version"] == "companion.v1"
        assert response.headers["cache-control"] == "no-store"
    assert app.state.container.shopping.list_lists(owner_actor(user_id)).lists == []


@pytest.mark.integration
def test_reads_need_the_read_capability_and_writes_need_write_and_read() -> None:
    app = companion_app()
    user_id = owner(app)
    shopping_list = new_list(app, user_id)
    list_id, item_id = (
        shopping_list["id"],
        seed_items(app, user_id, shopping_list["id"], "Mjölk")[0]["id"],
    )
    with TestClient(app) as client:
        tasks_only = paired_token(
            client, app, user_id, scopes={"companion:tasks:read", "companion:tasks:complete"}
        )
        write_only = paired_token(client, app, user_id, scopes=WRITE_ONLY)
        reader = paired_token(client, app, user_id, scopes=READ_ONLY)
        denied = [
            client.get(LISTS, headers=bearer(tasks_only)),
            client.get(f"{LISTS}/{list_id}", headers=bearer(tasks_only)),
            client.post(LISTS, headers=write(write_only, "shop-cap-000001"), json={"name": "N"}),
            client.post(
                f"{LISTS}/{list_id}/items",
                headers=write(write_only, "shop-cap-000002"),
                json={"items": [{"name": "N", "client_ref": "no"}]},
            ),
            client.post(LISTS, headers=write(reader, "shop-cap-000003"), json={"name": "N"}),
            client.post(
                f"{ITEMS}/{item_id}/purchased",
                headers=write(reader, "shop-cap-000004"),
                json={"purchased": True, "version": 1},
            ),
        ]
        allowed = client.get(LISTS, headers=bearer(reader))
    for response in denied:
        assert response.status_code == 403, response.text
        assert response.json()["code"] == "forbidden"
        assert response.json()["reason"] == "capability_missing"
    assert allowed.status_code == 200
    shopping = app.state.container.shopping
    actor = owner_actor(user_id)
    assert [str(row.id) for row in shopping.list_lists(actor).lists] == [list_id]
    stored = shopping.get_list(actor, UUID(list_id))
    assert [(row.name, row.purchased) for row in stored.items] == [("Mjölk", False)]


@pytest.mark.integration
def test_list_lists_counts_the_unpurchased_items_of_each_list() -> None:
    app = companion_app()
    user_id = owner(app)
    busy = new_list(app, user_id, "Veckohandel")
    empty = new_list(app, user_id, "Tomt")
    items = seed_items(app, user_id, busy["id"], "Mjölk", "Bröd", "Ägg")
    shopping = app.state.container.shopping
    actor = owner_actor(user_id)
    shopping.set_purchased(
        actor, UUID(items[0]["id"]), purchased=True, version=1, idempotency_key=f"seed-{uuid4()}"
    )
    expected = {busy["id"]: 2, empty["id"]: 0}
    rows = {str(row.id): row.open_count for row in shopping.list_lists(actor).lists}
    assert rows == expected
    # create/update/get keep the plain list record without the count.
    assert "open_count" not in busy
    with TestClient(app) as client:
        token = paired_token(client, app, user_id, scopes=READ_ONLY)
        response = client.get(LISTS, headers=bearer(token))
    assert response.status_code == 200
    assert {row["id"]: row["open_count"] for row in response.json()["lists"]} == expected


@pytest.mark.integration
def test_reads_equal_the_use_case_and_refuse_foreign_unknown_and_bad_bounds() -> None:
    app = companion_app()
    user_id = owner(app)
    stranger = owner(app, "stranger")
    mine = new_list(app, user_id)
    seed_items(app, user_id, mine["id"], "Mjölk", "Bröd")
    foreign = new_list(app, stranger, "Främmande lista")
    shopping = app.state.container.shopping
    actor = owner_actor(user_id)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        lists = client.get(LISTS, headers=bearer(token))
        detail = client.get(f"{LISTS}/{mine['id']}", headers=bearer(token))
        assert lists.status_code == 200 and detail.status_code == 200
        assert lists.json() == to_jsonable_python(shopping.list_lists(actor))
        assert detail.json() == to_jsonable_python(shopping.get_list(actor, UUID(mine["id"])))
        assert [row["name"] for row in detail.json()["items"]] == ["Mjölk", "Bröd"]
        for path in (f"{LISTS}/{foreign['id']}", f"{LISTS}/{uuid4()}"):
            missing = client.get(path, headers=bearer(token))
            assert missing.status_code == 404
            assert missing.json()["code"] == "not_found"
            assert "Främmande lista" not in missing.text
        assert client.get(f"{LISTS}/not-a-uuid", headers=bearer(token)).status_code == 422
        for query in ("limit=0", "limit=101"):
            bounded = client.get(f"{LISTS}?{query}", headers=bearer(token))
            assert bounded.status_code == 422, query
            assert bounded.json()["api_version"] == "companion.v1"
            on_detail = client.get(f"{LISTS}/{mine['id']}?{query}", headers=bearer(token))
            assert on_detail.status_code == 422, query


@pytest.mark.integration
def test_create_and_add_replay_the_same_answer_and_a_reused_key_is_409() -> None:
    app = companion_app()
    user_id = owner(app)
    shopping = app.state.container.shopping
    actor = owner_actor(user_id)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        create_key = "shop-create-0001"
        created = client.post(LISTS, headers=write(token, create_key), json={"name": "Hem"})
        assert created.status_code == 200
        list_id = created.json()["shopping_list"]["id"]
        replay = client.post(LISTS, headers=write(token, create_key), json={"name": "Hem"})
        assert replay.json() == created.json()
        assert len(shopping.list_lists(actor).lists) == 1
        reused = client.post(LISTS, headers=write(token, create_key), json={"name": "Annat"})
        assert reused.status_code == 409
        assert reused.json()["reason"] == "idempotency_key_reused"

        batch = {
            "items": [
                {"name": "Mjölk", "client_ref": "milk", "quantity": 2, "unit": "l"},
                {"name": "Smör", "client_ref": "butter", "store": "ICA"},
            ]
        }
        add_key = "shop-add-0000001"
        items_url = f"{LISTS}/{list_id}/items"
        added = client.post(items_url, headers=write(token, add_key), json=batch)
        assert added.status_code == 200
        assert [row["client_ref"] for row in added.json()["items"]] == ["milk", "butter"]
        assert [row["item"]["name"] for row in added.json()["items"]] == ["Mjölk", "Smör"]
        assert added.json()["open_count"] == 2
        again = client.post(items_url, headers=write(token, add_key), json=batch)
        assert again.json() == added.json()
        other_body = {"items": [{"name": "Ost", "client_ref": "cheese"}]}
        other = client.post(items_url, headers=write(token, add_key), json=other_body)
        assert other.status_code == 409
        assert other.json()["reason"] == "idempotency_key_reused"
    stored = shopping.get_list(actor, UUID(list_id))
    assert [row.name for row in stored.items] == ["Mjölk", "Smör"]


@pytest.mark.integration
def test_purchased_is_versioned_undoable_and_a_foreign_item_is_404() -> None:
    app = companion_app()
    user_id = owner(app)
    stranger = owner(app, "stranger")
    shopping_list = new_list(app, user_id)
    item = seed_items(app, user_id, shopping_list["id"], "Kaffe")[0]
    foreign_list = new_list(app, stranger, "Annans lista")
    foreign = seed_items(app, stranger, foreign_list["id"], "Annans vara")[0]
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        url = f"{ITEMS}/{item['id']}/purchased"
        bought = client.post(
            url, headers=write(token, "shop-buy-0000001"), json={"purchased": True, "version": 1}
        )
        assert bought.status_code == 200
        assert bought.json()["item"]["purchased"] is True
        assert bought.json()["item"]["version"] > 1
        assert "unchanged" not in bought.json()
        new_version = bought.json()["item"]["version"]
        # The stale call asks for the other state, so its version is checked (not a no-op).
        stale = client.post(
            url, headers=write(token, "shop-buy-0000002"), json={"purchased": False, "version": 1}
        )
        assert stale.status_code == 409
        assert stale.json()["reason"] == "stale_version"
        assert "Kaffe" not in stale.text
        undo = client.post(
            url,
            headers=write(token, "shop-buy-0000003"),
            json={"purchased": False, "version": new_version},
        )
        assert undo.status_code == 200
        assert undo.json()["item"]["purchased"] is False
        assert undo.json()["item"]["version"] > new_version
        denied = client.post(
            f"{ITEMS}/{foreign['id']}/purchased",
            headers=write(token, "shop-buy-0000004"),
            json={"purchased": True, "version": 1},
        )
    assert denied.status_code == 404
    assert denied.json()["code"] == "not_found"
    assert "Annans vara" not in denied.text


@pytest.mark.integration
def test_item_and_list_updates_change_only_what_is_sent_and_stale_versions_conflict() -> None:
    app = companion_app()
    user_id = owner(app)
    shopping_list = new_list(app, user_id)
    item = seed_items(app, user_id, shopping_list["id"], "Mjölk")[0]
    list_url = f"{LISTS}/{shopping_list['id']}/update"
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        item_url = f"{ITEMS}/{item['id']}/update"
        changed = client.post(
            item_url,
            headers=write(token, "shop-item-0000001"),
            json={"item": {"note": "Ekologisk"}, "version": 1},
        )
        assert changed.status_code == 200
        row = changed.json()["item"]
        assert row["note"] == "Ekologisk"
        assert row["name"] == item["name"] and float(row["quantity"]) == float(item["quantity"])
        assert row["version"] == 2
        stale_item = client.post(
            item_url,
            headers=write(token, "shop-item-0000002"),
            json={"item": {"name": "Havremjölk"}, "version": 1},
        )
        assert stale_item.status_code == 409
        assert stale_item.json()["reason"] == "stale_version"
        assert "Havremjölk" not in stale_item.text
        cleared_name = client.post(
            item_url,
            headers=write(token, "shop-item-0000003"),
            json={"item": {"name": None}, "version": 2},
        )
        assert cleared_name.status_code == 422

        renamed = client.post(
            list_url,
            headers=write(token, "shop-list-0000001"),
            json={"name": "Nytt namn", "archived": False, "version": 1},
        )
        assert renamed.status_code == 200
        assert renamed.json()["shopping_list"]["name"] == "Nytt namn"
        assert renamed.json()["shopping_list"]["version"] == 2
        stale_list = client.post(
            list_url,
            headers=write(token, "shop-list-0000002"),
            json={"name": "Gammalt", "archived": True, "version": 1},
        )
        assert stale_list.status_code == 409
        assert stale_list.json()["code"] == "conflict"
        archived = client.post(
            list_url,
            headers=write(token, "shop-list-0000003"),
            json={"name": "Nytt namn", "archived": True, "version": 2},
        )
        assert archived.status_code == 200
        assert archived.json()["shopping_list"]["archived"] is True
        assert client.get(LISTS, headers=bearer(token)).json()["lists"] == []
        shown = client.get(f"{LISTS}?include_archived=true", headers=bearer(token))
        assert [row["id"] for row in shown.json()["lists"]] == [shopping_list["id"]]


@pytest.mark.integration
def test_bodies_are_closed_typed_capped_and_read_only_after_authentication() -> None:
    app = companion_app()
    user_id = owner(app)
    shopping_list = new_list(app, user_id)
    add_url = f"{LISTS}/{shopping_list['id']}/items"
    huge = b'{"name": "' + b"x" * (128 * 1024) + b'"}'
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        unknown_field = client.post(
            LISTS, headers=write(token, "shop-body-0000001"), json={"name": "x", "owner": "y"}
        )
        assert unknown_field.status_code == 422
        assert unknown_field.json()["api_version"] == "companion.v1"
        unknown_item = client.post(
            add_url,
            headers=write(token, "shop-body-0000002"),
            json={"items": [{"name": "x", "client_ref": "a", "price": 1}]},
        )
        assert unknown_item.status_code == 422
        too_many = client.post(
            add_url,
            headers=write(token, "shop-body-0000003"),
            json={"items": [{"name": f"v{i}", "client_ref": f"r{i}"} for i in range(51)]},
        )
        assert too_many.status_code == 422
        plain = client.post(
            LISTS,
            headers={
                **bearer(token),
                "Content-Type": "text/plain",
                "Idempotency-Key": "shop-body-0000004",
            },
            content=b'{"name": "Text"}',
        )
        assert plain.status_code == 415
        assert plain.json()["code"] == "unsupported_media_type"
        too_big = client.post(LISTS, headers=write(token, "shop-body-0000005"), content=huge)
        assert too_big.status_code == 413
        assert too_big.json()["code"] == "payload_too_large"
        assert too_big.json()["api_version"] == "companion.v1"
        unauthenticated = client.post(
            LISTS, headers={**JSON, "Idempotency-Key": "shop-body-0000006"}, content=huge
        )
        assert unauthenticated.status_code == 401
        no_key = client.post(LISTS, headers={**bearer(token), **JSON}, json={"name": "Nyckel"})
        assert no_key.status_code == 422
        short_key = client.post(
            LISTS, headers={**bearer(token), **JSON, "Idempotency-Key": "short"}, json={"name": "K"}
        )
        assert short_key.status_code == 422
    shopping = app.state.container.shopping
    actor = owner_actor(user_id)
    assert len(shopping.list_lists(actor).lists) == 1
    assert shopping.get_list(actor, UUID(shopping_list["id"])).items == []


@pytest.mark.integration
def test_no_log_record_carries_a_list_name_an_item_name_a_token_or_an_idempotency_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = companion_app()
    user_id = owner(app)
    list_name = f"Hemlig lista {uuid4().hex}"
    item_name = f"Hemlig vara {uuid4().hex}"
    list_key = f"log-list-{uuid4().hex}"
    caplog.set_level(logging.INFO)
    # Sidekick's loggers do not propagate to the root logger; listen on them directly.
    watched = [logging.getLogger(name) for name in ("sidekick", "uvicorn", "fastapi", "fastmcp")]
    for logger in watched:
        logger.addHandler(caplog.handler)
    try:
        with TestClient(app) as client:
            token = paired_token(client, app, user_id)
            created = client.post(LISTS, headers=write(token, list_key), json={"name": list_name})
            list_id = created.json()["shopping_list"]["id"]
            client.post(LISTS, headers=write(token, list_key), json={"name": "Annat namn"})
            client.get(LISTS, headers=bearer(token))
            client.get(f"{LISTS}/{list_id}", headers=bearer(token))
            added = client.post(
                f"{LISTS}/{list_id}/items",
                headers=write(token, f"log-add-{uuid4().hex}"),
                json={"items": [{"name": item_name, "client_ref": "milk"}]},
            )
            item_id = added.json()["items"][0]["item"]["id"]
            client.post(
                f"{ITEMS}/{item_id}/purchased",
                headers=write(token, f"log-buy-{uuid4().hex}"),
                json={"purchased": True, "version": 1},
            )
            client.get(LISTS, headers=bearer(token + "x"))
    finally:
        for logger in watched:
            logger.removeHandler(caplog.handler)
    operations = {getattr(record, "companion_operation", None) for record in caplog.records}
    for expected in ("shopping.list_create", "shopping.lists", "shopping.items_add"):
        assert expected in operations
    assert "shopping.item_purchased" in operations
    secrets = (list_name, item_name, list_key, token, "Annat namn")
    for record in caplog.records:
        rendered = f"{record.getMessage()} {record.__dict__}"
        for secret in secrets:
            assert secret not in rendered, (record.name, record.getMessage())
