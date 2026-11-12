"""Shared test helpers moved out of `tests/api/test_companion.py`."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from sidekick.api.app import create_app
from sidekick.companion.persistence import CompanionDeviceStore
from sidekick.companion.service import CompanionDeviceService
from sidekick.shared.auth import MCP_SCOPES
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings

TITLE = "Ring tandläkaren companion-hemlig-titel"


OWNER_SCOPES = frozenset(MCP_SCOPES)


def companion_app() -> FastAPI:
    settings = make_settings().model_copy(update={"companion_enabled": True})
    return create_app(settings, database_factory())


def devices(app: FastAPI) -> CompanionDeviceService:
    container = app.state.container
    return CompanionDeviceService(CompanionDeviceStore(container.session_factory), container.auth)


def owner(app: FastAPI, username: str = "owner") -> UUID:
    return app.state.container.auth.provision_user(username, username.title())


def paired_token(client: TestClient, app: FastAPI, user_id: UUID, **pairing: Any) -> str:
    ticket = devices(app).create_pairing(user_id, "Samsung", **pairing)
    response = client.post("/companion/v1/pair", json={"pairing_secret": ticket.secret})
    assert response.status_code == 201, response.text
    return str(response.json()["access_token"])


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def owner_actor(user_id: UUID) -> Actor:
    return Actor(user_id, OWNER_SCOPES)


def create_task(app: FastAPI, user_id: UUID, title: str = TITLE, **fields: Any) -> Any:
    return app.state.container.tasks.create(
        owner_actor(user_id), title=title, idempotency_key=f"seed-{uuid4()}", **fields
    )


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now
