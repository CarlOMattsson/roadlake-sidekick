"""Shared helpers of the webhook entrance tests."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI

from sidekick.api.app import create_app
from sidekick.shared.types import Actor
from sidekick.webhooks.tokens import WEBHOOK_SCOPES, IssuedWebhookToken
from tests.db import database_factory
from tests.support.companion import OWNER_SCOPES
from tests.support.settings import make_settings

SHOPPING_ITEMS = "/webhooks/v1/shopping-items"
TASKS = "/webhooks/v1/tasks"
JSON = {"Content-Type": "application/json"}
ALL_WEBHOOK_SCOPES = tuple(sorted(WEBHOOK_SCOPES))


def webhook_app(*, enabled: bool = True, companion: bool = False) -> FastAPI:
    settings = make_settings().model_copy(
        update={"webhooks_enabled": enabled, "companion_enabled": companion}
    )
    return create_app(settings, database_factory())


def owner(app: FastAPI, username: str = "owner") -> UUID:
    return app.state.container.auth.provision_user(username, username.title())


def issue(
    app: FastAPI,
    user_id: UUID,
    scopes: tuple[str, ...] = ALL_WEBHOOK_SCOPES,
    **options: Any,
) -> IssuedWebhookToken:
    return app.state.container.webhook_tokens.create(user_id, "Home Assistant", scopes, **options)


def call_headers(token: str, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}", **JSON}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


def fresh_key() -> str:
    return f"hook-{uuid4().hex}"


def owner_actor(user_id: UUID) -> Actor:
    return Actor(user_id, OWNER_SCOPES)


def new_list(app: FastAPI, user_id: UUID, name: str = "Veckohandel") -> UUID:
    created = app.state.container.shopping.create_list(
        owner_actor(user_id), name, idempotency_key=fresh_key()
    )
    return created.shopping_list.id
