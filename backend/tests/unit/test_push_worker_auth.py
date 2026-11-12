"""Authenticated publishing to a self-hosted ntfy server (D-080): the token goes only to the auth
host, a refused token backs off without revoking, and the token never reaches a log, repr or row."""

from __future__ import annotations

import logging
from collections.abc import Callable
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import text

from sidekick.api.app import create_app
from sidekick.companion.push_delivery import PushDeliveryService
from sidekick.companion.push_delivery_store import SqlPushDeliveryStore
from sidekick.companion.push_sender import HttpPushSender, create_client
from sidekick.shared.config import Settings
from tests.db import database_factory
from tests.support.companion import owner
from tests.support.companion_push import (
    ENDPOINT,
    Clock,
    factory_of,
    outbox,
    queue_wake,
    subscribed,
    subscription_of,
)
from tests.support.settings import make_settings

OWN_HOST = "push.example.org"
OWN_ENDPOINT = f"https://{OWN_HOST}/upOwnTopic123abc"
TOKEN = "tk_abcdefghijklmnopqrstuvwxyz012"
HOSTS = frozenset({OWN_HOST, "ntfy.sh"})


def settings_with(**update: object) -> Settings:
    return make_settings().model_copy(update=update)


def validated(**fields: object) -> Settings:
    base = make_settings().model_dump()
    base.update(fields)
    return Settings(**base)


# --- configuration -------------------------------------------------------------------------


def test_a_token_with_its_host_in_the_allowlist_is_accepted_and_masked() -> None:
    settings = validated(
        push_allowed_hosts=f"{OWN_HOST},ntfy.sh",
        push_auth_host=f"  {OWN_HOST.upper()} ",
        push_auth_token=SecretStr(TOKEN),
    )
    assert settings.push_auth_host == OWN_HOST
    assert settings.push_auth_token is not None
    assert settings.push_auth_token.get_secret_value() == TOKEN
    assert TOKEN not in repr(settings) and TOKEN not in str(settings)


def test_blank_values_mean_not_configured() -> None:
    settings = validated(push_auth_host="", push_auth_token="  ")
    assert settings.push_auth_host is None and settings.push_auth_token is None


@pytest.mark.parametrize(
    "fields",
    [
        {"push_auth_token": TOKEN},  # token without a host
        {"push_auth_host": "other.example.org", "push_auth_token": TOKEN},  # host not allowed
        {"push_auth_host": OWN_HOST, "push_auth_token": f"{TOKEN}\n"},
        {"push_auth_host": OWN_HOST, "push_auth_token": f"{TOKEN}\r\nX-Evil: 1"},
        {"push_auth_host": OWN_HOST, "push_auth_token": f"tk_ab {TOKEN}"},
    ],
)
def test_an_invalid_combination_is_rejected_without_repeating_the_token(
    fields: dict[str, object],
) -> None:
    with pytest.raises(ValidationError) as caught:
        validated(push_allowed_hosts=f"{OWN_HOST},ntfy.sh", **fields)
    assert TOKEN not in str(caught.value) and TOKEN not in repr(caught.value)


# --- delivery ------------------------------------------------------------------------------


def auth_app() -> FastAPI:
    settings = settings_with(
        companion_enabled=True, push_enabled=True, push_allowed_hosts=f"{OWN_HOST},ntfy.sh"
    )
    return create_app(settings, database_factory())


def service_for(
    app: FastAPI, handler: Callable[[httpx.Request], httpx.Response], clock: Clock
) -> PushDeliveryService:
    return PushDeliveryService(
        SqlPushDeliveryStore(factory_of(app)),
        HttpPushSender(create_client(httpx.MockTransport(handler))),
        HOSTS,
        clock=clock,
        jitter=lambda: 1.0,
        auth_host=OWN_HOST,
        auth_token=SecretStr(TOKEN),
    )


def seeded(clock: Clock, endpoint: str) -> tuple[FastAPI, UUID, TestClient]:
    app = auth_app()
    user_id = owner(app)
    client = TestClient(app)
    client.__enter__()
    _, device = subscribed(client, app, user_id, endpoint)
    queue_wake(app, user_id, clock.now)
    return app, device, client


@pytest.mark.integration
def test_the_auth_host_gets_a_bearer_header_and_another_host_gets_none() -> None:
    for endpoint, expected in ((OWN_ENDPOINT, f"Bearer {TOKEN}"), (ENDPOINT, None)):
        clock = Clock()
        app, _, client = seeded(clock, endpoint)
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request, seen: list[httpx.Request] = seen) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200)

        with client:
            assert service_for(app, handler, clock).run_once() == 1
        (request,) = seen
        assert request.headers.get("authorization") == expected
        if expected is None:
            assert TOKEN not in str(request.headers)
        assert request.content == b'{"k":"w"}'


@pytest.mark.integration
def test_without_a_configured_token_no_host_gets_an_authorization_header() -> None:
    clock = Clock()
    app, _, client = seeded(clock, OWN_ENDPOINT)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    with client:
        bare = PushDeliveryService(
            SqlPushDeliveryStore(factory_of(app)),
            HttpPushSender(create_client(httpx.MockTransport(handler))),
            HOSTS,
            clock=clock,
            auth_host=OWN_HOST,
        )
        assert bare.run_once() == 1
    assert "authorization" not in seen[0].headers


@pytest.mark.integration
@pytest.mark.parametrize("status", [401, 403])
def test_a_refused_token_backs_off_without_revoking_and_hides_the_token(
    status: int, caplog: pytest.LogCaptureFixture
) -> None:
    clock = Clock()
    app, device, client = seeded(clock, OWN_ENDPOINT)
    sidekick_logger = logging.getLogger("sidekick")
    sidekick_logger.addHandler(caplog.handler)
    with client, caplog.at_level(logging.DEBUG), caplog.at_level(logging.DEBUG, "sidekick"):
        service = service_for(app, lambda request: httpx.Response(status), clock)
        assert service.run_once() == 1
        (row,) = outbox(app)
        assert row.last_error_kind == "unauthorized" and row.delivered_at is None
        assert row.next_attempt_at is not None and row.next_attempt_at > clock.now
        subscription = subscription_of(app, device)
        assert subscription.revoked_at is None and subscription.failure_count == 1
        # Not due yet; after the backoff the row is tried again and succeeds once fixed.
        assert service.run_once() == 0
        clock.advance(minutes=31)
        fixed = service_for(app, lambda request: httpx.Response(200), clock)
        assert fixed.run_once() == 1
        assert outbox(app)[0].delivered_at is not None
        # A token that is refused never lands in a row, an audit row or the log.
        with factory_of(app)() as session:
            dumped = (
                session.execute(
                    text(
                        "SELECT coalesce(string_agg(o::text, ' '), '') FROM sidekick.push_outbox o"
                        " UNION ALL SELECT coalesce(string_agg(s::text, ' '), '')"
                        " FROM sidekick.push_subscriptions s"
                    )
                )
                .scalars()
                .all()
            )
        assert TOKEN not in " ".join(dumped)
    sidekick_logger.removeHandler(caplog.handler)
    records = [r for r in caplog.records if r.getMessage() == "push_delivery"]
    assert [r.__dict__["push_outcome"] for r in records] == ["retry", "delivered"]
    assert {r.__dict__["push_host"] for r in records} == {OWN_HOST}
    assert (
        TOKEN not in caplog.text and TOKEN not in repr(service) and "upOwnTopic" not in caplog.text
    )


@pytest.mark.integration
def test_401_from_another_host_is_not_an_auth_failure() -> None:
    clock = Clock()
    app, device, client = seeded(clock, ENDPOINT)
    with client:
        service_for(app, lambda request: httpx.Response(401), clock).run_once()
        (row,) = outbox(app)
        assert row.last_error_kind == "rejected" and row.next_attempt_at is None
        assert subscription_of(app, device).revoked_at is None
