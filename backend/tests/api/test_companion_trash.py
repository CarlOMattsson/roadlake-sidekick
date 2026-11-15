"""`/companion/v1/` trash (ADR-005): delete with undo, list, restore, erase and empty.

Each route is the MCP tools' lifecycle use case under the room's own write capability; it is
refused for an unauthenticated, wrongly scoped or foreign caller before anything changes, a repeated
idempotency key replays the stored result, and nothing is removed for good without an explicit
`confirm`."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sidekick.api.app import create_app
from sidekick.lifecycle import RecordKind
from sidekick.shared.errors import NotFoundError
from sidekick.structured.journal import write_journal_entry_structured
from tests.db import database_factory
from tests.support.companion import (
    bearer,
    companion_app,
    create_task,
    owner,
    owner_actor,
    paired_token,
)
from tests.support.companion_work import seed_work
from tests.support.settings import make_settings

COMPANION = "/companion/v1"
KEY = "trash-key-0001"
SECRET = "Papperskorg-hemlig-titel"
TASK_ONLY = {"companion:work:write", "companion:tasks:read"}  # no erase
SHOPPING_ONLY = {"companion:shopping:write", "companion:shopping:read"}
READ_ONLY = {"companion:tasks:read", "companion:shopping:read", "companion:journal:read"}
WRITE_ONLY = {"companion:work:write", "companion:shopping:write", "companion:journal:write"}


def headers(token: str, key: str = KEY) -> dict[str, str]:
    return {**bearer(token), "Idempotency-Key": key}


def seed_entry(app: FastAPI, user_id: UUID, title: str = SECRET) -> dict[str, Any]:
    return write_journal_entry_structured(
        app.state.container,
        owner_actor(user_id),
        journal_date=date(2026, 7, 21),
        title=title,
        source_text="Vanlig text utan bilder.",
        idempotency_key=f"seed-{uuid4()}",
    ).model_dump(mode="json")["entry"]


def seed_item(app: FastAPI, user_id: UUID, name: str = SECRET) -> dict[str, Any]:
    from sidekick.shopping.application.schemas import BatchItem

    shopping = app.state.container.shopping
    actor = owner_actor(user_id)
    created = shopping.create_list(actor, "Veckohandel", idempotency_key=f"seed-{uuid4()}")
    added = shopping.add_items(
        actor,
        created.shopping_list.id,
        [BatchItem(name=name, client_ref="seed0")],
        idempotency_key=f"seed-{uuid4()}",
    )
    return added.items[0].item.model_dump(mode="json")


def trashed(app: FastAPI, user_id: UUID) -> dict[str, dict[str, Any]]:
    """The owner's trash as the use case lists it, by id."""

    page = app.state.container.lifecycle.list_trash(owner_actor(user_id), limit=100)
    return {str(item.id): {"kind": item.kind.value, "version": item.version} for item in page.items}


def trash_path(kind: str, record_id: Any, action: str) -> str:
    base = {
        "task": f"{COMPANION}/tasks",
        "journal_entry": f"{COMPANION}/journal/entries",
        "shopping_item": f"{COMPANION}/shopping/items",
    }[kind]
    return f"{base}/{record_id}/{action}"


def assert_problem(response: Any, status: int, code: str, reason: str | None = None) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == code
    assert body["api_version"] == "companion.v1"
    if reason is not None:
        assert body["reason"] == reason
    assert SECRET not in response.text


def records(app: FastAPI, user_id: UUID) -> dict[str, tuple[Any, int]]:
    task = create_task(app, user_id, title=SECRET)
    entry = seed_entry(app, user_id)
    item = seed_item(app, user_id)
    return {
        "task": (task.id, task.version),
        "journal_entry": (entry["id"], entry["version"]),
        "shopping_item": (item["id"], item["version"]),
    }


@pytest.mark.integration
@pytest.mark.parametrize("kind", ["task", "journal_entry", "shopping_item"])
def test_a_record_goes_to_the_trash_shows_there_and_comes_back(kind: str) -> None:
    app = companion_app()
    user_id = owner(app)
    record_id, version = records(app, user_id)[kind]
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        moved = client.post(
            trash_path(kind, record_id, "trash"), headers=headers(token), json={"version": version}
        )
        assert moved.status_code == 200, moved.text
        receipt = moved.json()
        assert receipt["kind"] == kind and receipt["id"] == str(record_id)
        assert receipt["label"] == SECRET and receipt["trashed_at"] is not None
        assert str(record_id) in trashed(app, user_id)

        listing = client.get(f"{COMPANION}/trash", headers=bearer(token))
        assert listing.status_code == 200, listing.text
        rows = {row["id"]: row for row in listing.json()["items"]}
        assert rows[str(record_id)]["kind"] == kind
        assert rows[str(record_id)]["version"] == receipt["version"]
        narrowed = client.get(f"{COMPANION}/trash", params={"kind": kind}, headers=bearer(token))
        assert [row["id"] for row in narrowed.json()["items"]] == [str(record_id)]

        back = client.post(
            trash_path(kind, record_id, "untrash"),
            headers=headers(token, "trash-key-0002"),
            json={"version": receipt["version"]},
        )
        assert back.status_code == 200, back.text
        assert back.json()["id"] == str(record_id)
    assert trashed(app, user_id) == {}


@pytest.mark.integration
def test_a_repeated_key_replays_and_a_stale_version_conflicts() -> None:
    app = companion_app()
    user_id = owner(app)
    task = create_task(app, user_id, title=SECRET)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        path = trash_path("task", task.id, "trash")
        first = client.post(path, headers=headers(token), json={"version": task.version})
        replay = client.post(path, headers=headers(token), json={"version": task.version})
        assert first.status_code == replay.status_code == 200
        assert replay.json()["id"] == first.json()["id"]
        stale = client.post(
            path, headers=headers(token, "trash-key-0002"), json={"version": task.version}
        )
        assert_problem(stale, 409, "conflict", "stale_version")
        reused = client.post(path, headers=headers(token), json={"version": task.version + 5})
        assert_problem(reused, 409, "conflict", "idempotency_key_reused")
    assert list(trashed(app, user_id)) == [str(task.id)]


@pytest.mark.integration
@pytest.mark.parametrize("kind", ["task", "journal_entry", "shopping_item"])
def test_the_routes_are_refused_before_anything_changes(kind: str) -> None:
    app = companion_app()
    user_id = owner(app)
    stranger = owner(app, "annan")
    mine = records(app, user_id)[kind]
    theirs = records(app, stranger)[kind]
    path = trash_path(kind, mine[0], "trash")
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        reader = paired_token(client, app, user_id, scopes=READ_ONLY)
        writer = paired_token(client, app, user_id, scopes=WRITE_ONLY)
        body = {"version": mine[1]}

        assert_problem(
            client.post(path, headers={"Idempotency-Key": KEY}, json=body), 401, "unauthorized"
        )
        # No capability at all, or the write capability without the read capability of the room.
        for weak in (reader, writer):
            denied = client.post(path, headers=headers(weak), json=body)
            assert_problem(denied, 403, "forbidden", "capability_missing")
        assert_problem(client.post(path, headers=bearer(token), json=body), 422, "validation_error")
        assert client.get(path, headers=bearer(token)).status_code == 405
        # Another owner's record is not found, whatever its version is.
        foreign = client.post(
            trash_path(kind, theirs[0], "trash"),
            headers=headers(token),
            json={"version": theirs[1]},
        )
        assert_problem(foreign, 404, "not_found")
    assert trashed(app, user_id) == {} and trashed(app, stranger) == {}


@pytest.mark.integration
def test_a_device_trashes_only_what_its_capabilities_cover() -> None:
    app = companion_app()
    user_id = owner(app)
    held = records(app, user_id)
    with TestClient(app) as client:
        shopping = paired_token(client, app, user_id, scopes=SHOPPING_ONLY)
        task_id, task_version = held["task"]
        denied = client.post(
            trash_path("task", task_id, "trash"),
            headers=headers(shopping),
            json={"version": task_version},
        )
        assert_problem(denied, 403, "forbidden", "capability_missing")
        item_id, item_version = held["shopping_item"]
        assert (
            client.post(
                trash_path("shopping_item", item_id, "trash"),
                headers=headers(shopping),
                json={"version": item_version},
            ).status_code
            == 200
        )
        # The list shows what this device may trash and restore, never the Task or the entry.
        for record_id, version in (held["task"], held["journal_entry"]):
            owner_token = paired_token(client, app, user_id)
            kind = "task" if record_id == task_id else "journal_entry"
            client.post(
                trash_path(kind, record_id, "trash"),
                headers=headers(owner_token, f"owner-{kind}-key"),
                json={"version": version},
            )
        listed = client.get(f"{COMPANION}/trash", headers=bearer(shopping)).json()["items"]
        assert [row["kind"] for row in listed] == ["shopping_item"]
        # A device that may trash nothing may not list.
        reader = paired_token(client, app, user_id, scopes=READ_ONLY)
        assert_problem(
            client.get(f"{COMPANION}/trash", headers=bearer(reader)),
            403,
            "forbidden",
            "capability_missing",
        )
        # A kind the device may not read is refused, not silently empty.
        refused = client.get(
            f"{COMPANION}/trash", params={"kind": "task"}, headers=bearer(shopping)
        )
        assert_problem(refused, 403, "forbidden")


@pytest.mark.integration
def test_a_task_is_only_erased_when_trashed_and_confirmed() -> None:
    app = companion_app()
    user_id = owner(app)
    task = create_task(app, user_id, title=SECRET)
    erase = trash_path("task", task.id, "erase")
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        # Not in the trash yet: refused, whatever the confirmation says.
        early = client.post(
            erase, headers=headers(token), json={"version": task.version, "confirm": True}
        )
        assert_problem(early, 422, "validation_error")
        moved = client.post(
            trash_path("task", task.id, "trash"),
            headers=headers(token, "trash-key-0002"),
            json={"version": task.version},
        ).json()
        for missing in ({}, {"confirm": False}, {"confirm": "yes"}, {"confirm": None}):
            refused = client.post(
                erase,
                headers=headers(token, "trash-key-0003"),
                json={"version": moved["version"], **missing},
            )
            assert_problem(refused, 422, "validation_error")
        assert str(task.id) in trashed(app, user_id)

        stale = client.post(
            erase,
            headers=headers(token, "trash-key-0004"),
            json={"version": moved["version"] + 3, "confirm": True},
        )
        assert_problem(stale, 409, "conflict", "stale_version")
        gone = client.post(
            erase,
            headers=headers(token, "trash-key-0005"),
            json={"version": moved["version"], "confirm": True},
        )
        assert gone.status_code == 200, gone.text
        assert gone.json() == {"removed": True}
        replay = client.post(
            erase,
            headers=headers(token, "trash-key-0005"),
            json={"version": moved["version"], "confirm": True},
        )
        assert replay.status_code == 200
    with pytest.raises(NotFoundError):
        app.state.container.tasks.get(owner_actor(user_id), task.id)


@pytest.mark.integration
def test_a_device_without_the_erase_right_trashes_and_restores_but_cannot_remove() -> None:
    app = companion_app()
    user_id = owner(app)
    task = create_task(app, user_id, title=SECRET)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id, scopes=TASK_ONLY)
        moved = client.post(
            trash_path("task", task.id, "trash"),
            headers=headers(token),
            json={"version": task.version},
        )
        assert moved.status_code == 200, moved.text
        listed = client.get(f"{COMPANION}/trash", headers=bearer(token)).json()
        assert listed["can_erase"] is False and len(listed["items"]) == 1
        erase = client.post(
            trash_path("task", task.id, "erase"),
            headers=headers(token, "trash-key-0002"),
            json={"version": moved.json()["version"], "confirm": True},
        )
        assert_problem(erase, 403, "forbidden", "capability_missing")
        emptied = client.post(
            f"{COMPANION}/trash/empty", headers=bearer(token), json={"confirm": True}
        )
        assert_problem(emptied, 403, "forbidden", "capability_missing")
        assert str(task.id) in trashed(app, user_id)
        restored = client.post(
            trash_path("task", task.id, "untrash"),
            headers=headers(token, "trash-key-0003"),
            json={"version": moved.json()["version"]},
        )
        assert restored.status_code == 200
        # The erase capability alone is not enough: it needs the write capability too.
        erase_only = paired_token(
            client, app, user_id, scopes={"companion:work:erase", "companion:tasks:read"}
        )
        assert_problem(
            client.post(
                f"{COMPANION}/trash/empty", headers=bearer(erase_only), json={"confirm": True}
            ),
            403,
            "forbidden",
            "capability_missing",
        )
        full = paired_token(client, app, user_id)
        assert client.get(f"{COMPANION}/trash", headers=bearer(full)).json()["can_erase"] is True


@pytest.mark.integration
def test_a_journal_entry_and_a_shopping_item_can_never_be_erased_from_the_app() -> None:
    app = companion_app()
    user_id = owner(app)
    held = records(app, user_id)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        for kind in ("journal_entry", "shopping_item"):
            record_id, version = held[kind]
            client.post(
                trash_path(kind, record_id, "trash"),
                headers=headers(token, f"trash-{kind}"),
                json={"version": version},
            )
            erase = client.post(
                trash_path(kind, record_id, "erase"),
                headers=headers(token, f"erase-{kind}"),
                json={"version": version + 1, "confirm": True},
            )
            assert erase.status_code == 404, erase.text
        emptied = client.post(
            f"{COMPANION}/trash/empty", headers=bearer(token), json={"confirm": True}
        )
        assert emptied.json() == {"removed": 0, "kept": 0}
    assert {row["kind"] for row in trashed(app, user_id).values()} == {
        "journal_entry",
        "shopping_item",
    }


@pytest.mark.integration
def test_emptying_removes_trashed_tasks_only_and_asks_for_confirmation() -> None:
    app = companion_app()
    user_id = owner(app)
    stranger = owner(app, "annan")
    work = seed_work(app, user_id)
    lifecycle = app.state.container.lifecycle
    actor = owner_actor(user_id)
    gone = [create_task(app, user_id, title=f"Borta {index}") for index in range(2)]
    stays = create_task(app, user_id, title="Aktiv kvar")
    theirs = create_task(app, stranger, title="Annans papperskorg")
    for task in (*gone, work.task):
        lifecycle.trash(
            actor, RecordKind.TASK, task.id, version=task.version, idempotency_key=f"seed-{task.id}"
        )
    lifecycle.trash(
        owner_actor(stranger),
        RecordKind.TASK,
        theirs.id,
        version=theirs.version,
        idempotency_key="seed-theirs",
    )
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        url = f"{COMPANION}/trash/empty"
        for refused in ({}, {"confirm": False}, {"confirm": 1}):
            assert_problem(
                client.post(url, headers=bearer(token), json=refused), 422, "validation_error"
            )
        assert len(trashed(app, user_id)) == 3
        reader = paired_token(client, app, user_id, scopes=READ_ONLY)
        assert_problem(
            client.post(url, headers=bearer(reader), json={"confirm": True}),
            403,
            "forbidden",
            "capability_missing",
        )
        emptied = client.post(url, headers=bearer(token), json={"confirm": True})
        assert emptied.status_code == 200, emptied.text
        # The Task with a Step cannot be removed and stays, counted as kept.
        assert emptied.json() == {"removed": 2, "kept": 1}
        again = client.post(url, headers=bearer(token), json={"confirm": True})
        assert again.json() == {"removed": 0, "kept": 1}
    assert list(trashed(app, user_id)) == [str(work.task.id)]
    assert list(trashed(app, stranger)) == [str(theirs.id)]
    assert app.state.container.tasks.get(actor, stays.id).title == "Aktiv kvar"


@pytest.mark.integration
def test_a_room_that_is_off_has_no_trash_route_and_lists_nothing_of_its_kind() -> None:
    settings = make_settings().model_copy(
        update={"companion_enabled": True, "enabled_rooms": "work,shopping"}
    )
    app = create_app(settings, database_factory())
    user_id = owner(app)
    entry = seed_entry(app, user_id)
    item = seed_item(app, user_id)
    lifecycle = app.state.container.lifecycle
    lifecycle.trash(
        owner_actor(user_id),
        RecordKind.JOURNAL_ENTRY,
        UUID(entry["id"]),
        version=entry["version"],
        idempotency_key="seed-entry",
    )
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        off = client.post(
            trash_path("journal_entry", entry["id"], "untrash"),
            headers=headers(token),
            json={"version": entry["version"] + 1},
        )
        assert off.status_code == 404
        on = client.post(
            trash_path("shopping_item", item["id"], "trash"),
            headers=headers(token, "trash-key-0002"),
            json={"version": item["version"]},
        )
        assert on.status_code == 200
        listed = client.get(f"{COMPANION}/trash", headers=bearer(token)).json()["items"]
        assert [row["kind"] for row in listed] == ["shopping_item"]


@pytest.mark.integration
def test_the_list_pages_with_a_cursor_and_bounds_its_limit() -> None:
    app = companion_app()
    user_id = owner(app)
    lifecycle = app.state.container.lifecycle
    for index in range(3):
        task = create_task(app, user_id, title=f"Rad {index}")
        lifecycle.trash(
            owner_actor(user_id),
            RecordKind.TASK,
            task.id,
            version=task.version,
            idempotency_key=f"seed-{index}-{task.id}",
        )
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        first = client.get(f"{COMPANION}/trash", params={"limit": 2}, headers=bearer(token)).json()
        assert len(first["items"]) == 2 and first["has_more"] is True
        second = client.get(
            f"{COMPANION}/trash",
            params={"limit": 2, "cursor": first["next_cursor"]},
            headers=bearer(token),
        ).json()
        assert len(second["items"]) == 1 and second["has_more"] is False
        for bad in ({"limit": 0}, {"limit": 101}, {"kind": "project"}, {"cursor": "x" * 600}):
            assert_problem(
                client.get(f"{COMPANION}/trash", params=bad, headers=bearer(token)),
                422,
                "validation_error",
            )
