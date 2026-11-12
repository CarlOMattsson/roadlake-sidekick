"""`SIDEKICK_ENABLED_ROOMS`: parsing, a room's scopes, the app declaration, the companion routes.

The MCP side (the tools a room takes with it) is in tests/mcp/test_enabled_rooms.py.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from sidekick.api.companion import create_companion_router
from sidekick.api.public_surface import PublicSurfaceAllowlistMiddleware, is_companion_route
from sidekick.mcp.app_meta import with_app_context, with_enabled_rooms
from sidekick.mcp.rooms import room_actor_provider
from sidekick.shared.config import Settings
from sidekick.shared.observability import NoopTelemetryAdapter
from sidekick.shared.rooms import ROOM_SCOPES, ROOMS, disabled_scopes, parse_enabled_rooms
from sidekick.shared.types import Actor, new_uuid7

SHOPPING = "/companion/v1/shopping/lists"
JOURNAL = "/companion/v1/journal/entries"
WORK = "/companion/v1/work/agenda"


def test_every_room_is_on_by_default() -> None:
    assert Settings().enabled_room_set == frozenset(ROOMS)
    assert parse_enabled_rooms("") == frozenset(ROOMS)
    assert parse_enabled_rooms("  ,, ") == frozenset(ROOMS)


def test_a_comma_list_names_the_rooms_that_are_on() -> None:
    assert parse_enabled_rooms("work") == {"work"}
    assert parse_enabled_rooms(" Work , contacts,control ") == {"work", "contacts", "control"}
    assert parse_enabled_rooms("work,work,journal") == {"work", "journal"}


def test_the_setting_is_read_from_its_environment_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIDEKICK_ENABLED_ROOMS", "work,shopping")
    assert Settings().enabled_room_set == {"work", "shopping"}


def test_an_unknown_room_is_refused_and_named(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match=r"unknown room \(kitchen, pantry\)"):
        parse_enabled_rooms("work,kitchen,pantry")
    monkeypatch.setenv("SIDEKICK_ENABLED_ROOMS", "work,kitchen")
    with pytest.raises(ValidationError, match="SIDEKICK_ENABLED_ROOMS names an unknown room"):
        Settings()


def test_the_work_room_cannot_be_switched_off(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="must keep the work room switched on"):
        parse_enabled_rooms("journal,shopping")
    monkeypatch.setenv("SIDEKICK_ENABLED_ROOMS", "journal")
    with pytest.raises(ValidationError, match="must keep the work room switched on"):
        Settings()


def test_a_room_that_is_off_loses_exactly_its_own_scopes() -> None:
    assert disabled_scopes(ROOMS) == frozenset()
    assert disabled_scopes({"work", "journal", "shopping", "contacts", "control"}) == frozenset()
    assert disabled_scopes({"work"}) == frozenset().union(*ROOM_SCOPES.values())
    assert disabled_scopes({"work", "journal"}) == {
        "shopping:read",
        "shopping:write",
        "contacts:read",
        "contacts:write",
    }


def test_the_actor_of_a_narrowed_server_holds_no_scope_of_an_off_room() -> None:
    held = frozenset({"tasks:read", "journal:read", "journal:write", "contacts:read"})
    actor = Actor(new_uuid7(), held)

    narrowed = room_actor_provider(lambda: actor, {"work", "contacts"})()

    assert narrowed.user_id == actor.user_id
    assert narrowed.scopes == {"tasks:read", "contacts:read"}


def test_with_every_room_on_the_actor_provider_is_the_one_given() -> None:
    def provider() -> Actor:
        return Actor(new_uuid7(), frozenset({"journal:read"}))

    assert room_actor_provider(provider, ROOMS) is provider


def test_the_app_document_declares_its_rooms_once_in_app_order() -> None:
    html = '<!doctype html><html><head><meta charset="utf-8"></head><body></body></html>'
    declared = with_enabled_rooms(html, {"control", "work", "contacts"})
    assert declared.count('name="sidekick-rooms"') == 1
    assert '<head><meta name="sidekick-rooms" content="work,contacts,control">' in declared


def test_the_app_document_declares_locale_and_rooms_together() -> None:
    html = "<html><head></head></html>"
    declared = with_app_context(html, "en", {"work"}, None)
    assert 'name="sidekick-app-locale" content="en"' in declared
    assert 'name="sidekick-rooms" content="work"' in declared


@pytest.mark.parametrize("path", [SHOPPING, JOURNAL])
def test_a_room_that_is_off_has_no_companion_route(path: str) -> None:
    app = FastAPI()
    app.include_router(create_companion_router(rooms={"work"}))
    client = TestClient(app)

    assert client.get(path).status_code == 404


def _paths(**kwargs: Any) -> set[str]:
    return {route.path for route in create_companion_router(**kwargs).routes}  # type: ignore[attr-defined]


def test_a_room_that_is_on_has_its_companion_routes() -> None:
    paths = _paths(rooms={"work", "shopping"})

    assert any(path.startswith("/companion/v1/shopping/") for path in paths)
    assert not any(path.startswith("/companion/v1/journal/") for path in paths)
    assert "/companion/v1/work/agenda" in paths


def test_every_room_is_on_for_the_companion_router_by_default() -> None:
    paths = _paths()

    assert any(path.startswith("/companion/v1/shopping/") for path in paths)
    assert any(path.startswith("/companion/v1/journal/") for path in paths)


def test_the_companion_allowlist_leaves_out_the_routes_of_an_off_room() -> None:
    assert is_companion_route("GET", SHOPPING)
    assert is_companion_route("GET", SHOPPING, {"work", "shopping"})
    assert not is_companion_route("GET", SHOPPING, {"work", "journal"})
    assert not is_companion_route("GET", JOURNAL, {"work", "shopping"})
    assert not is_companion_route(
        "POST", "/companion/v1/shopping/lists", {"work", "journal", "contacts"}
    )
    # The work routes and the device routes do not belong to a switchable room.
    assert is_companion_route("GET", WORK, {"work"})
    assert is_companion_route("POST", "/companion/v1/pair", {"work"})


class _Recorder:
    def __init__(self) -> None:
        self.reached = False
        self.sent: list[dict[str, Any]] = []

    async def app(self, scope: Any, receive: Any, send: Any) -> None:
        self.reached = True
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def send(self, message: dict[str, Any]) -> None:
        self.sent.append(message)

    @property
    def status(self) -> int:
        return int(self.sent[0]["status"])

    @property
    def body(self) -> dict[str, Any]:
        return json.loads(b"".join(m.get("body", b"") for m in self.sent))


async def _receive() -> dict[str, Any]:
    return {"type": "http.request", "body": b"", "more_body": False}


async def _through_the_surface(path: str, rooms: set[str]) -> _Recorder:
    recorder = _Recorder()
    middleware = PublicSurfaceAllowlistMiddleware(
        recorder.app, NoopTelemetryAdapter(), companion=True, rooms=rooms
    )
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "raw_path": path.encode(),
        "headers": [],
        "query_string": b"",
        "sidekick.correlation_id": "corr-rooms",
    }
    await middleware(scope, _receive, recorder.send)
    return recorder


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [SHOPPING, JOURNAL])
async def test_the_public_surface_answers_404_for_the_route_of_an_off_room(path: str) -> None:
    recorder = await _through_the_surface(path, {"work"})

    assert not recorder.reached
    assert recorder.status == 404
    assert recorder.body["code"] == "not_found"


@pytest.mark.asyncio
async def test_the_public_surface_lets_the_routes_of_the_rooms_that_are_on_through() -> None:
    on = {"work", "shopping", "journal"}
    for path in (SHOPPING, JOURNAL, WORK):
        recorder = await _through_the_surface(path, on)
        assert recorder.reached, path
    assert (await _through_the_surface(WORK, {"work"})).reached
