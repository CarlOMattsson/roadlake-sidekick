"""`/companion/v1/` Start and the suggestion inbox (ADR-005, ADR-013).

Each route is the use case the MCP tool of the same name calls. Reading needs the read
capabilities; deciding is the owner's act and needs `companion:suggestions:decide`, which is never
part of reading. A decision from the phone is recorded on the `companion` channel, every write
carries an idempotency key, and the card's payload cannot be edited from here.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastmcp import Client

from sidekick.api.app import create_app
from sidekick.companion.operations import START_READ
from sidekick.contacts.application.models import CreateContactCommand
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.companion import (
    FixedClock,
    bearer,
    companion_app,
    create_task,
    owner,
    owner_actor,
    paired_token,
)
from tests.support.companion_suggestions import card_row, count_rows, seed_cards
from tests.support.settings import make_settings

COMPANION = "/companion/v1"
SECRET = "Förslag-hemlig-titel"
NOON = datetime(2026, 11, 23, 11, 0, tzinfo=UTC)
START_ONLY = {"companion:start:read", "companion:tasks:read"}
READER = {"companion:suggestions:read"}
DECIDER = {"companion:suggestions:read", "companion:suggestions:decide"}
DECIDE_ONLY = {"companion:suggestions:decide"}
READ_PRESET = {
    "companion:start:read",
    "companion:suggestions:read",
    "companion:tasks:read",
}


def headers(token: str, key: str | None = None) -> dict[str, str]:
    return {**bearer(token), "Idempotency-Key": key or f"key-{uuid4().hex}"}


def assert_problem(response: Any, status: int, code: str, reason: str | None = None) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == code
    assert body["api_version"] == "companion.v1"
    if reason is not None:
        assert body["reason"] == reason
    assert SECRET not in response.text


def listed(client: TestClient, token: str, **params: Any) -> dict[str, Any]:
    response = client.get(f"{COMPANION}/suggestions", params=params, headers=bearer(token))
    assert response.status_code == 200, response.text
    return dict(response.json())


def decision(card: dict[str, Any], kind: str = "approve", **extra: Any) -> dict[str, Any]:
    return {
        "suggestion_id": card["id"],
        "expected_version": card["version"],
        "decision": kind,
        **extra,
    }


def group_of(client: TestClient, token: str) -> dict[str, Any]:
    (group,) = listed(client, token, group="high_confidence")["groups"]
    return group


# --- Start ------------------------------------------------------------------------------------


async def _tool_start(app: FastAPI, user_id: UUID) -> dict[str, Any]:
    actor = Actor(user_id, START_READ.application_scopes)
    server = create_mcp_server(app.state.container, actor_provider=lambda: actor, enable_auth=False)
    async with Client(server) as client:
        result = await client.call_tool("get_start", {})
    assert result.structured_content is not None
    return dict(result.structured_content)


@pytest.mark.integration
def test_start_answers_the_structure_the_mcp_tool_answers() -> None:
    app = companion_app()
    app.state.container.work_lists.clock = FixedClock(NOON)
    user_id = owner(app)
    create_task(app, user_id, title=SECRET, due_at=NOON)
    seed_cards(app, user_id, "Ring tandläkaren")
    with TestClient(app) as client:
        token = paired_token(client, app, user_id, scopes=START_ONLY)
        response = client.get(f"{COMPANION}/start", headers=bearer(token))
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        body = response.json()
    assert body == asyncio.run(_tool_start(app, user_id))
    assert body["day"] == "2026-11-23"
    assert body["today"] is not None and SECRET in str(body["today"])
    assert body["suggestions"] is not None
    # A part with nothing to say is left out rather than sent empty.
    assert "insight" not in body and "unavailable" not in body


@pytest.mark.integration
def test_start_leaves_out_the_parts_with_nothing_to_show() -> None:
    app = companion_app()
    app.state.container.work_lists.clock = FixedClock(NOON)
    user_id = owner(app)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id, scopes=START_ONLY)
        body = client.get(f"{COMPANION}/start", headers=bearer(token)).json()
    assert body["day"] == "2026-11-23"
    assert "suggestions" not in body and "waiting" not in body and "insight" not in body


@pytest.mark.integration
@pytest.mark.parametrize(
    "scopes",
    [
        {"companion:tasks:read"},
        {"companion:start:read"},
        {"companion:suggestions:read", "companion:suggestions:decide"},
    ],
)
def test_start_needs_the_start_and_the_task_read_capability(scopes: set[str]) -> None:
    app = companion_app()
    user_id = owner(app)
    create_task(app, user_id, title=SECRET)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id, scopes=scopes)
        assert_problem(
            client.get(f"{COMPANION}/start", headers=bearer(token)),
            403,
            "forbidden",
            "capability_missing",
        )
        assert_problem(client.get(f"{COMPANION}/start"), 401, "unauthorized")


# --- reading the inbox ------------------------------------------------------------------------


@pytest.mark.integration
def test_the_inbox_lists_a_card_and_gives_it_in_full() -> None:
    app = companion_app()
    user_id = owner(app)
    (card,) = seed_cards(app, user_id, SECRET)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id, scopes=READER)
        page = listed(client, token)
        assert [item["id"] for item in page["items"]] == [card["id"]]
        assert page["items"][0]["summary"] == f"Create task: {SECRET}"
        assert page["items"][0]["state"] == "pending" and page["groups"] == []
        detail = client.get(f"{COMPANION}/suggestions/{card['id']}", headers=bearer(token))
        assert detail.status_code == 200, detail.text
        assert detail.headers["cache-control"] == "no-store"
        assert detail.json()["suggestion"]["payload"] == {"title": SECRET}
        # The state filter is the use case's own: nothing is dismissed yet.
        assert listed(client, token, state="dismissed")["items"] == []
        too_many = client.get(
            f"{COMPANION}/suggestions", params={"limit": 26}, headers=bearer(token)
        )
        assert_problem(too_many, 422, "validation_error")


@pytest.mark.integration
def test_reading_the_inbox_needs_the_suggestions_read_capability() -> None:
    app = companion_app()
    user_id = owner(app)
    (card,) = seed_cards(app, user_id, SECRET)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id, scopes=START_ONLY | DECIDE_ONLY)
        for path in ("", f"/{card['id']}"):
            assert_problem(
                client.get(f"{COMPANION}/suggestions{path}", headers=bearer(token)),
                403,
                "forbidden",
                "capability_missing",
            )
            assert_problem(client.get(f"{COMPANION}/suggestions{path}"), 401, "unauthorized")


@pytest.mark.integration
def test_another_owners_card_is_not_found_and_not_listed() -> None:
    app = companion_app()
    user_id = owner(app)
    stranger = owner(app, "stranger")
    (foreign,) = seed_cards(app, stranger, SECRET)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id, scopes=DECIDER)
        assert listed(client, token)["items"] == []
        assert_problem(
            client.get(f"{COMPANION}/suggestions/{foreign['id']}", headers=bearer(token)),
            404,
            "not_found",
        )
        refused = client.post(
            f"{COMPANION}/suggestions/decisions",
            headers=headers(token),
            json={"items": [decision(foreign)]},
        )
        assert_problem(refused, 404, "not_found")
        undone = client.post(
            f"{COMPANION}/suggestions/{foreign['id']}/undo",
            headers=headers(token),
            json={"expected_version": 1},
        )
        assert_problem(undone, 404, "not_found")
    assert card_row(app, foreign["id"])["state"] == "pending"
    assert count_rows(app, "tasks") == 0


# --- deciding ---------------------------------------------------------------------------------


@pytest.mark.integration
def test_the_owner_approves_a_card_on_the_phone_and_the_channel_is_recorded() -> None:
    app = companion_app()
    user_id = owner(app)
    (card,) = seed_cards(app, user_id, SECRET)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id, scopes=DECIDER)
        response = client.post(
            f"{COMPANION}/suggestions/decisions",
            headers=headers(token),
            json={"items": [decision(card)]},
        )
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        (item,) = response.json()["items"]
        assert item["state"] == "applied" and item["error_code"] is None
        assert item["applied"]["kind"] == "task"
        detail = client.get(f"{COMPANION}/suggestions/{card['id']}", headers=bearer(token))
    stored = card_row(app, card["id"])
    assert (stored["state"], stored["decided_by"], stored["decision_channel"]) == (
        "applied",
        "you",
        "companion",
    )
    assert detail.json()["suggestion"]["decision_channel"] == "companion"
    assert count_rows(app, "tasks") == 1


@pytest.mark.integration
def test_the_owner_dismisses_a_card_and_nothing_is_created() -> None:
    app = companion_app()
    user_id = owner(app)
    (card,) = seed_cards(app, user_id, SECRET)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id, scopes=DECIDER)
        response = client.post(
            f"{COMPANION}/suggestions/decisions",
            headers=headers(token),
            json={"items": [decision(card, "dismiss")]},
        )
        assert response.status_code == 200, response.text
        assert response.json()["items"][0]["state"] == "dismissed"
    assert card_row(app, card["id"])["decision_channel"] == "companion"
    assert count_rows(app, "tasks") == 0


@pytest.mark.integration
def test_a_stale_version_is_refused_inside_the_answer_and_changes_nothing() -> None:
    app = companion_app()
    user_id = owner(app)
    one, two = seed_cards(app, user_id, "Ett", "Två")
    with TestClient(app) as client:
        token = paired_token(client, app, user_id, scopes=DECIDER)
        response = client.post(
            f"{COMPANION}/suggestions/decisions",
            headers=headers(token),
            json={"items": [decision({**one, "version": 7}), decision(two)]},
        )
        assert response.status_code == 200, response.text
        items = {item["suggestion_id"]: item for item in response.json()["items"]}
    assert items[one["id"]]["error_code"] == "stale"
    assert items[two["id"]]["state"] == "applied"
    assert card_row(app, one["id"])["state"] == "pending"
    assert count_rows(app, "tasks") == 1


@pytest.mark.integration
def test_the_same_key_twice_answers_the_same_and_applies_once() -> None:
    app = companion_app()
    user_id = owner(app)
    (card,) = seed_cards(app, user_id, SECRET)
    body = {"items": [decision(card)]}
    with TestClient(app) as client:
        token = paired_token(client, app, user_id, scopes=DECIDER)
        first = client.post(
            f"{COMPANION}/suggestions/decisions", headers=headers(token, "same-key-1"), json=body
        )
        second = client.post(
            f"{COMPANION}/suggestions/decisions", headers=headers(token, "same-key-1"), json=body
        )
        assert first.status_code == second.status_code == 200
        assert second.json() == first.json()
        # The same key for another request is a different request, refused as such.
        other = client.post(
            f"{COMPANION}/suggestions/decisions",
            headers=headers(token, "same-key-1"),
            json={"items": [decision(card, "dismiss")]},
        )
        assert_problem(other, 409, "conflict", "idempotency_key_reused")
    assert count_rows(app, "tasks") == 1
    assert card_row(app, card["id"])["state"] == "applied"


@pytest.mark.integration
def test_a_decision_is_refused_without_a_key_with_too_many_cards_or_with_edits() -> None:
    app = companion_app()
    user_id = owner(app)
    cards = seed_cards(app, user_id, "Ett", "Två", "Tre", "Fyra")
    with TestClient(app) as client:
        token = paired_token(client, app, user_id, scopes=DECIDER)
        url = f"{COMPANION}/suggestions/decisions"
        no_key = client.post(url, headers=bearer(token), json={"items": [decision(cards[0])]})
        assert_problem(no_key, 422, "validation_error")
        four = client.post(
            url, headers=headers(token), json={"items": [decision(card) for card in cards]}
        )
        assert_problem(four, 422, "validation_error")
        none = client.post(url, headers=headers(token), json={"items": []})
        assert_problem(none, 422, "validation_error")
        edited = client.post(
            url,
            headers=headers(token),
            json={"items": [decision(cards[0], edits={"title": "Något annat"})]},
        )
        assert_problem(edited, 422, "validation_error")
        # The owner is the credential's: the body names no owner.
        owned = client.post(
            url,
            headers=headers(token),
            json={"items": [decision(cards[0])], "owner_id": str(uuid4())},
        )
        assert_problem(owned, 422, "validation_error")
    assert count_rows(app, "tasks") == 0
    assert {card_row(app, card["id"])["state"] for card in cards} == {"pending"}


@pytest.mark.integration
@pytest.mark.parametrize("scopes", [READER | START_ONLY, DECIDE_ONLY, {"companion:work:write"}])
def test_deciding_needs_its_own_capability_besides_reading(scopes: set[str]) -> None:
    app = companion_app()
    user_id = owner(app)
    one, two = seed_cards(app, user_id, SECRET, "Två", checked=True)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id, scopes=scopes)
        assert_problem(
            client.post(
                f"{COMPANION}/suggestions/decisions",
                headers=headers(token),
                json={"items": [decision(one)]},
            ),
            403,
            "forbidden",
            "capability_missing",
        )
        assert_problem(
            client.post(
                f"{COMPANION}/suggestions/group-approvals",
                headers=headers(token),
                json={"group_digest": "0" * 64, "suggestion_ids": [one["id"], two["id"]]},
            ),
            403,
            "forbidden",
            "capability_missing",
        )
        assert_problem(
            client.post(
                f"{COMPANION}/suggestions/{one['id']}/undo",
                headers=headers(token),
                json={"expected_version": 2},
            ),
            403,
            "forbidden",
            "capability_missing",
        )
        for path in ("decisions", "group-approvals", f"{one['id']}/undo"):
            assert_problem(
                client.post(f"{COMPANION}/suggestions/{path}", json={}), 401, "unauthorized"
            )
    assert {card_row(app, card["id"])["state"] for card in (one, two)} == {"pending"}
    assert count_rows(app, "tasks") == 0


# --- a group ----------------------------------------------------------------------------------


@pytest.mark.integration
def test_the_owner_approves_the_group_they_saw_and_the_channel_is_the_phone() -> None:
    app = companion_app()
    user_id = owner(app)
    one, two = seed_cards(app, user_id, "Ett", "Två", checked=True)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id, scopes=DECIDER)
        group = group_of(client, token)
        assert sorted(group["suggestion_ids"]) == sorted([one["id"], two["id"]])
        response = client.post(
            f"{COMPANION}/suggestions/group-approvals",
            headers=headers(token),
            json={
                "group_digest": group["group_digest"],
                "suggestion_ids": group["suggestion_ids"],
            },
        )
        assert response.status_code == 200, response.text
        assert [item["state"] for item in response.json()["items"]] == ["applied", "applied"]
    for card in (one, two):
        stored = card_row(app, card["id"])
        assert (stored["state"], stored["decided_by"], stored["decision_channel"]) == (
            "applied",
            "you",
            "companion",
        )
    assert count_rows(app, "tasks") == 2


@pytest.mark.integration
def test_a_group_that_changed_is_refused_as_a_whole() -> None:
    app = companion_app()
    user_id = owner(app)
    one, two = seed_cards(app, user_id, "Ett", "Två", checked=True)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id, scopes=DECIDER)
        group = group_of(client, token)
        # One card is decided elsewhere between the list and the approval.
        dismissed = client.post(
            f"{COMPANION}/suggestions/decisions",
            headers=headers(token),
            json={"items": [decision(two, "dismiss")]},
        )
        assert dismissed.status_code == 200, dismissed.text
        refused = client.post(
            f"{COMPANION}/suggestions/group-approvals",
            headers=headers(token),
            json={
                "group_digest": group["group_digest"],
                "suggestion_ids": group["suggestion_ids"],
            },
        )
        assert_problem(refused, 409, "conflict")
        wrong_digest = client.post(
            f"{COMPANION}/suggestions/group-approvals",
            headers=headers(token),
            json={"group_digest": "0" * 64, "suggestion_ids": [one["id"]]},
        )
        assert_problem(wrong_digest, 409, "conflict")
        malformed = client.post(
            f"{COMPANION}/suggestions/group-approvals",
            headers=headers(token),
            json={"group_digest": "not-a-digest", "suggestion_ids": [one["id"]]},
        )
        assert_problem(malformed, 422, "validation_error")
    assert card_row(app, one["id"])["state"] == "pending"
    assert count_rows(app, "tasks") == 0


# --- undo -------------------------------------------------------------------------------------


@pytest.mark.integration
def test_an_approved_card_is_undone_and_its_task_goes_to_the_trash() -> None:
    app = companion_app()
    user_id = owner(app)
    (card,) = seed_cards(app, user_id, SECRET)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id, scopes=DECIDER)
        approved = client.post(
            f"{COMPANION}/suggestions/decisions",
            headers=headers(token),
            json={"items": [decision(card)]},
        ).json()["items"][0]
        undone = client.post(
            f"{COMPANION}/suggestions/{card['id']}/undo",
            headers=headers(token, "undo-key-1"),
            json={"expected_version": approved["version"]},
        )
        assert undone.status_code == 200, undone.text
        body = undone.json()
        assert body["suggestion_id"] == card["id"] and body["state"] == "undone"
        assert body["trashed"] == approved["applied"]
        replay = client.post(
            f"{COMPANION}/suggestions/{card['id']}/undo",
            headers=headers(token, "undo-key-1"),
            json={"expected_version": approved["version"]},
        )
        assert replay.json() == body
        stale = client.post(
            f"{COMPANION}/suggestions/{card['id']}/undo",
            headers=headers(token),
            json={"expected_version": approved["version"]},
        )
        assert stale.status_code == 409, stale.text
    assert card_row(app, card["id"])["state"] == "undone"
    assert card_row(app, card["id"])["decision_channel"] == "companion"


@pytest.mark.integration
def test_a_dismissed_card_is_undone_and_pending_again() -> None:
    app = companion_app()
    user_id = owner(app)
    (card,) = seed_cards(app, user_id, SECRET)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id, scopes=DECIDER)
        dismissed = client.post(
            f"{COMPANION}/suggestions/decisions",
            headers=headers(token),
            json={"items": [decision(card, "dismiss")]},
        ).json()["items"][0]
        undone = client.post(
            f"{COMPANION}/suggestions/{card['id']}/undo",
            headers=headers(token),
            json={"expected_version": dismissed["version"]},
        )
        assert undone.status_code == 200, undone.text
        assert undone.json()["state"] == "pending" and undone.json()["trashed"] is None
        no_key = client.post(
            f"{COMPANION}/suggestions/{card['id']}/undo",
            headers=bearer(token),
            json={"expected_version": 1},
        )
        assert_problem(no_key, 422, "validation_error")
    assert card_row(app, card["id"])["state"] == "pending"
    assert count_rows(app, "tasks") == 0


# --- a room that is switched off --------------------------------------------------------------


def _without_contacts() -> FastAPI:
    settings = make_settings().model_copy(
        update={"companion_enabled": True, "enabled_rooms": "work,journal,shopping"}
    )
    return create_app(settings, database_factory())


def _add_contact(app: FastAPI, user_id: UUID) -> None:
    app.state.container.contacts.create(
        owner_actor(user_id), CreateContactCommand(display_name=SECRET), "seed-contact"
    )


@pytest.mark.integration
def test_start_shows_the_contact_count_only_while_the_contacts_room_is_on() -> None:
    on, off = companion_app(), _without_contacts()
    shown: dict[str, dict[str, Any]] = {}
    for name, app in (("on", on), ("off", off)):
        user_id = owner(app, name)
        _add_contact(app, user_id)
        with TestClient(app) as client:
            token = paired_token(client, app, user_id, scopes=START_ONLY)
            shown[name] = client.get(f"{COMPANION}/start", headers=bearer(token)).json()
    assert shown["on"]["more"]["contacts"] == 1
    assert "contacts" not in shown["off"].get("more", {})
    assert SECRET not in str(shown["off"])


@pytest.mark.integration
def test_a_contact_card_is_neither_shown_nor_decided_while_the_contacts_room_is_off() -> None:
    app = _without_contacts()
    user_id = owner(app)
    (task_card,) = seed_cards(app, user_id, "En uppgift")
    (contact_card,) = seed_cards(app, user_id, SECRET, effect="create_contact")
    with TestClient(app) as client:
        token = paired_token(client, app, user_id, scopes=DECIDER)
        page = listed(client, token)
        detail = client.get(f"{COMPANION}/suggestions/{contact_card['id']}", headers=bearer(token))
        approved = client.post(
            f"{COMPANION}/suggestions/decisions",
            headers=headers(token),
            json={"items": [decision(contact_card)]},
        )
    assert [item["id"] for item in page["items"]] == [task_card["id"]]
    assert page["hidden"] == 1
    assert SECRET not in str(page)
    assert detail.status_code in (403, 404) and SECRET not in detail.text
    assert approved.status_code in (403, 404), approved.text
    assert card_row(app, contact_card["id"])["state"] == "pending"
    assert count_rows(app, "contacts") == 0
