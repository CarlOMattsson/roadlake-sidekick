"""Shared test helpers moved out of `tests/api/test_companion_push_delivery.py`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from sidekick.companion.push_outbox_store import (
    enqueue_wake,
)
from sidekick.shared.persistence.models import (
    CompanionPairingRow,
    PushOutboxRow,
    PushSubscriptionRow,
)
from tests.support.companion import (
    bearer,
    paired_token,
)

URL = "/companion/v1/push/subscription"


SECRET_TOPIC = "upSecretTopic123abc"


ENDPOINT = f"https://ntfy.sh/{SECRET_TOPIC}"


OTHER_ENDPOINT = "https://ntfy.sh/upOtherTopic456def"


def factory_of(app: FastAPI) -> sessionmaker[Session]:
    factory: sessionmaker[Session] = app.state.container.session_factory
    return factory


def device_id(client: TestClient, token: str) -> UUID:
    return UUID(client.get("/companion/v1/device", headers=bearer(token)).json()["device"]["id"])


def subscribed(
    client: TestClient, app: FastAPI, user_id: UUID, endpoint: str = ENDPOINT
) -> tuple[str, UUID]:
    token = paired_token(client, app, user_id)
    assert client.put(URL, json={"endpoint": endpoint}, headers=bearer(token)).status_code == 200
    return token, device_id(client, token)


def outbox(app: FastAPI) -> list[PushOutboxRow]:
    with factory_of(app)() as session:
        return list(session.scalars(select(PushOutboxRow).order_by(PushOutboxRow.created_at)))


def subscription_of(app: FastAPI, device: UUID) -> PushSubscriptionRow:
    with factory_of(app)() as session:
        return session.scalars(
            select(PushSubscriptionRow)
            .join(CompanionPairingRow, CompanionPairingRow.id == PushSubscriptionRow.pairing_id)
            .where(CompanionPairingRow.device_token_id == device)
        ).one()


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


def queue_wake(
    app: FastAPI, user_id: UUID, now: datetime, min_interval: timedelta = timedelta(0)
) -> None:
    with factory_of(app).begin() as session:
        enqueue_wake(session, user_id, now=now, min_interval=min_interval)
