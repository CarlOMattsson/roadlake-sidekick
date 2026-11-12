"""Push subscriptions of paired devices (ADR-005; D-078): the endpoint is an SSRF
guard, a device holds at most one active subscription, and revoking the device revokes it."""

from __future__ import annotations

import logging
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import ProgrammingError

from sidekick.companion.push import (
    EndpointRejected,
    PairingNotFound,
    PushSubscriptionService,
    validate_endpoint,
)
from sidekick.companion.push_subscription_store import SqlPushSubscriptionStore
from sidekick.shared.auth import TOKEN_SCOPES
from sidekick.shared.persistence.models import AuditEventRow, PushSubscriptionRow
from tests.db import database_factory
from tests.support.companion import bearer, companion_app, devices, owner, paired_token

URL = "/companion/v1/push/subscription"
ENDPOINT = "https://ntfy.sh/upSecretTopic123abc"
SECOND_ENDPOINT = "https://ntfy.sh/upOtherTopic456def"
HOSTS = frozenset({"ntfy.sh"})
LONGEST = "https://ntfy.sh/" + "a" * (512 - len("https://ntfy.sh/"))


def subscriptions(app: FastAPI, user_id: UUID) -> list[PushSubscriptionRow]:
    # The app's own factory: `database_factory()` empties the database.
    with app.state.container.session_factory() as session:
        return list(
            session.scalars(
                select(PushSubscriptionRow)
                .where(PushSubscriptionRow.user_id == user_id)
                .order_by(PushSubscriptionRow.created_at)
            )
        )


def active(rows: list[PushSubscriptionRow]) -> list[PushSubscriptionRow]:
    return [row for row in rows if row.revoked_at is None]


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://ntfy.sh/topic",
        "https://127.0.0.1/topic",
        "https://10.0.0.5:443/topic",
        "https://[::1]/topic",
        "https://[::ffff:7f00:1]/topic",
        "https://2130706433/topic",
        "https://evil.example/topic",
        "https://ntfy.sh.evil.example/topic",
        "https://evilntfy.sh/topic",
        "https://ntfy.sh./topic",
        "https://localhost/topic",
        "https://user@ntfy.sh/topic",
        "https://user:pass@ntfy.sh/topic",
        "https://ntfy.sh@evil.example/topic",
        "https://evil.example\\@ntfy.sh/topic",
        "https://ntfy.sh:8443/topic",
        "https://ntfy.sh:80/topic",
        "https://ntfy.sh:notaport/topic",
        "https://ntfy.sh/topic#fragment",
        "https://ntfy.sh/to pic",
        "https://ntfy.sh/topic\n",
        "https://ntfy.sh/tòpic",
        "ftp://ntfy.sh/topic",
        "//ntfy.sh/topic",
        "ntfy.sh/topic",
        "https://",
        "",
        LONGEST + "a",
    ],
)
def test_endpoint_validation_rejects_everything_but_an_allowed_https_host(endpoint: str) -> None:
    with pytest.raises(EndpointRejected) as error:
        validate_endpoint(endpoint, HOSTS)
    assert endpoint not in str(error.value) or endpoint == ""


@pytest.mark.parametrize(
    "endpoint",
    [
        ENDPOINT,
        "https://NTFY.SH/topic",
        "https://ntfy.sh:443/topic",
        "https://ntfy.sh/topic?auth=x",
        LONGEST,
    ],
)
def test_endpoint_validation_accepts_an_allowed_https_host(endpoint: str) -> None:
    assert len(endpoint) <= 512
    assert validate_endpoint(endpoint, HOSTS) == "ntfy.sh"


def test_an_added_host_is_accepted_and_the_default_stays_closed() -> None:
    assert validate_endpoint("https://push.example.org/up", {"push.example.org"}) == (
        "push.example.org"
    )
    with pytest.raises(EndpointRejected):
        validate_endpoint("https://ntfy.sh/up", {"push.example.org"})


@pytest.mark.integration
def test_put_registers_replaces_in_place_and_delete_revokes() -> None:
    app = companion_app()
    user_id = owner(app)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        first = client.put(URL, json={"endpoint": ENDPOINT}, headers=bearer(token))
        assert first.status_code == 200
        assert first.json() == {"ok": True}
        assert first.headers["cache-control"] == "no-store"
        rows = subscriptions(app, user_id)
        assert [(row.endpoint, row.endpoint_host) for row in active(rows)] == [
            (ENDPOINT, "ntfy.sh")
        ]

        second = client.put(URL, json={"endpoint": SECOND_ENDPOINT}, headers=bearer(token))
        assert second.status_code == 200
        rows = subscriptions(app, user_id)
        assert [row.endpoint for row in active(rows)] == [SECOND_ENDPOINT]
        assert len(rows) == 1

        removed = client.delete(URL, headers=bearer(token))
        assert removed.status_code == 204
        assert active(subscriptions(app, user_id)) == []
        assert client.delete(URL, headers=bearer(token)).status_code == 204

        again = client.put(URL, json={"endpoint": ENDPOINT}, headers=bearer(token))
        assert again.status_code == 200
        rows = subscriptions(app, user_id)
        assert len(rows) == 2
        assert [row.endpoint for row in active(rows)] == [ENDPOINT]


@pytest.mark.integration
def test_put_refuses_a_bad_endpoint_with_a_closed_reason_and_stores_nothing() -> None:
    app = companion_app()
    user_id = owner(app)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        for endpoint in (
            "http://ntfy.sh/topic",
            "https://169.254.169.254/latest",
            "https://evil.example/topic",
            "https://user@ntfy.sh/topic",
            "https://ntfy.sh:8443/topic",
        ):
            response = client.put(URL, json={"endpoint": endpoint}, headers=bearer(token))
            assert response.status_code == 422, endpoint
            body = response.json()
            assert body["code"] == "validation_error"
            assert body["reason"] == "endpoint_not_allowed"
            assert endpoint not in response.text
        too_long = client.put(URL, json={"endpoint": LONGEST + "a"}, headers=bearer(token))
        assert too_long.status_code == 422
        for body_json in ({}, {"endpoint": ""}, {"endpoint": 5}, {"endpoint": ENDPOINT, "x": 1}):
            response = client.put(URL, json=body_json, headers=bearer(token))
            assert response.status_code == 422
        not_json = client.put(
            URL, content=b"endpoint", headers={**bearer(token), "Content-Type": "text/plain"}
        )
        assert not_json.status_code == 415
        too_big = client.put(
            URL,
            content=b'{"endpoint": "' + b"x" * 3000 + b'"}',
            headers={**bearer(token), "Content-Type": "application/json"},
        )
        assert too_big.status_code == 413
    assert subscriptions(app, user_id) == []


@pytest.mark.integration
def test_the_allowed_hosts_setting_decides_which_host_is_accepted() -> None:
    from sidekick.api.app import create_app
    from tests.support.settings import make_settings

    settings = make_settings().model_copy(
        update={"companion_enabled": True, "push_allowed_hosts": "push.example.org, ntfy.sh"}
    )
    app = create_app(settings, database_factory())
    user_id = owner(app)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        own = client.put(
            URL, json={"endpoint": "https://push.example.org/up123"}, headers=bearer(token)
        )
        assert own.status_code == 200
        other = client.put(
            URL, json={"endpoint": "https://other.example/up"}, headers=bearer(token)
        )
        assert other.status_code == 422
    assert [row.endpoint_host for row in active(subscriptions(app, user_id))] == [
        "push.example.org"
    ]


@pytest.mark.integration
def test_authentication_comes_before_the_body_and_the_capability_before_the_write() -> None:
    app = companion_app()
    user_id = owner(app)
    pat = app.state.container.auth.create_personal_token(user_id, "mcp", TOKEN_SCOPES)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        reader = paired_token(client, app, user_id, scopes={"companion:tasks:read"})
        for method in ("PUT", "DELETE"):
            missing = client.request(method, URL, content=b"not json at all")
            assert missing.status_code == 401
            assert missing.headers["www-authenticate"].startswith("Bearer")
            assert client.request(method, URL, headers=bearer(token + "x")).status_code == 401
            assert client.request(method, URL, headers=bearer(pat)).status_code == 401
            denied = client.request(
                method, URL, json={"endpoint": ENDPOINT}, headers=bearer(reader)
            )
            assert denied.status_code == 403
            assert denied.json()["reason"] == "capability_missing"
        # Bad body from an unauthenticated caller is refused as 401, never 415 or 422.
        junk = client.put(URL, json={"endpoint": 1}, headers={"Content-Type": "application/json"})
        assert junk.status_code == 401
    assert subscriptions(app, user_id) == []


@pytest.mark.integration
def test_each_device_has_its_own_subscription_and_a_second_owner_is_separate() -> None:
    app = companion_app()
    first_owner = owner(app)
    second_owner = owner(app, "second")
    with TestClient(app) as client:
        phone = paired_token(client, app, first_owner)
        tablet = paired_token(client, app, first_owner)
        stranger = paired_token(client, app, second_owner)
        for token, endpoint in (
            (phone, ENDPOINT),
            (tablet, SECOND_ENDPOINT),
            (stranger, "https://ntfy.sh/upThird789"),
        ):
            assert client.put(
                URL, json={"endpoint": endpoint}, headers=bearer(token)
            ).status_code == (200)
        assert len(active(subscriptions(app, first_owner))) == 2
        assert client.delete(URL, headers=bearer(phone)).status_code == 204
        assert [row.endpoint for row in active(subscriptions(app, first_owner))] == [
            SECOND_ENDPOINT
        ]
        assert len(active(subscriptions(app, second_owner))) == 1


@pytest.mark.integration
def test_revoking_or_unpairing_the_device_revokes_its_subscription() -> None:
    app = companion_app()
    user_id = owner(app)
    with TestClient(app) as client:
        revoked = paired_token(client, app, user_id)
        unpaired = paired_token(client, app, user_id)
        kept = paired_token(client, app, user_id)
        for token in (revoked, unpaired, kept):
            assert client.put(
                URL, json={"endpoint": ENDPOINT}, headers=bearer(token)
            ).status_code == (200)
        assert len(active(subscriptions(app, user_id))) == 3
        service = devices(app)
        revoked_id = UUID(
            client.get("/companion/v1/device", headers=bearer(revoked)).json()["device"]["id"]
        )
        assert service.revoke_device(user_id, revoked_id)
        assert len(active(subscriptions(app, user_id))) == 2
        assert client.delete("/companion/v1/device", headers=bearer(unpaired)).status_code == 204
        remaining = active(subscriptions(app, user_id))
        assert len(remaining) == 1
        # Revoking again is idempotent, and the surviving device is untouched.
        assert service.revoke_device(user_id, revoked_id)
        assert len(active(subscriptions(app, user_id))) == 1
        assert client.delete(URL, headers=bearer(kept)).status_code == 204


@pytest.mark.integration
def test_the_app_role_can_read_insert_and_update_but_never_delete_a_subscription() -> None:
    app = companion_app()
    user_id = owner(app)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        client.put(URL, json={"endpoint": ENDPOINT}, headers=bearer(token))
    factory = app.state.container.session_factory
    with pytest.raises(ProgrammingError), factory.begin() as session:
        session.execute(text("DELETE FROM sidekick.push_subscriptions"))
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(PushSubscriptionRow)) == 1


@pytest.mark.integration
def test_audit_and_logs_never_carry_the_endpoint(caplog: pytest.LogCaptureFixture) -> None:
    app = companion_app()
    user_id = owner(app)
    caplog.set_level(logging.DEBUG)
    watched = [logging.getLogger(name) for name in ("sidekick", "uvicorn", "fastapi", "fastmcp")]
    for logger in watched:
        logger.addHandler(caplog.handler)
    try:
        with TestClient(app) as client:
            token = paired_token(client, app, user_id)
            client.put(URL, json={"endpoint": ENDPOINT}, headers=bearer(token))
            client.put(
                URL, json={"endpoint": "https://evil.example/upLeak999"}, headers=bearer(token)
            )
            client.put(URL, json={"endpoint": SECOND_ENDPOINT}, headers=bearer(token))
            client.delete(URL, headers=bearer(token))
    finally:
        for logger in watched:
            logger.removeHandler(caplog.handler)
    records = [
        record for record in caplog.records if not record.name.startswith(("httpx", "httpcore"))
    ]
    operations = {
        getattr(record, "companion_operation", None)
        for record in records
        if record.getMessage() == "companion_request"
    }
    assert {"push.subscription", "push.subscription.remove"} <= operations
    for record in records:
        rendered = f"{record.getMessage()} {record.__dict__}"
        for forbidden in (
            ENDPOINT,
            SECOND_ENDPOINT,
            "upSecretTopic123abc",
            "upOtherTopic456def",
            "upLeak999",
            "evil.example",
            token,
        ):
            assert forbidden not in rendered, (record.name, record.getMessage())
    with app.state.container.session_factory() as session:
        events = list(
            session.scalars(
                select(AuditEventRow).where(AuditEventRow.event.like("companion.push_%"))
            )
        )
    assert sorted(event.event for event in events) == [
        "companion.push_subscribed",
        "companion.push_subscribed",
        "companion.push_unsubscribed",
    ]
    for event in events:
        rendered = str(event.__dict__)
        assert "ntfy.sh" not in rendered and "upSecret" not in rendered


def test_the_app_preset_carries_the_push_scope_with_a_swedish_description() -> None:
    from sidekick.companion.cli import PRESETS, SCOPE_DESCRIPTIONS

    assert "companion:push" in PRESETS["app"]
    assert "avisering" in SCOPE_DESCRIPTIONS["companion:push"]["sv"]


@pytest.mark.integration
def test_an_unknown_pairing_is_a_401_but_an_unexpected_lookup_error_is_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = companion_app()
    user_id = owner(app)
    service = PushSubscriptionService.from_settings(
        SqlPushSubscriptionStore(app.state.container.session_factory),
        app.state.container.settings,
    )
    with pytest.raises(PairingNotFound):
        service.subscribe(user_id, UUID(int=1), ENDPOINT)

    def unpaired(*_args: object, **_kwargs: object) -> str:
        raise PairingNotFound

    def broken(*_args: object, **_kwargs: object) -> str:
        raise KeyError("a bug, not a missing pairing")

    with TestClient(app, raise_server_exceptions=False) as client:
        token = paired_token(client, app, user_id)
        monkeypatch.setattr(PushSubscriptionService, "subscribe", unpaired)
        assert (
            client.put(URL, json={"endpoint": ENDPOINT}, headers=bearer(token)).status_code == 401
        )
        monkeypatch.setattr(PushSubscriptionService, "subscribe", broken)
        assert (
            client.put(URL, json={"endpoint": ENDPOINT}, headers=bearer(token)).status_code == 500
        )
