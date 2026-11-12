"""`GET`/`PUT /companion/v1/license` (D-081): the Android app enters the instance's license key.

Device capability `companion:license`, the installation's only owner, a capped body read after
authentication, problem+json refusals that never echo the key, and the display state in the
`/device` and `/pair` answers.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from sidekick.api.app import create_app
from sidekick.shared.persistence.models import AuditEventRow
from tests.db import database_factory
from tests.support.companion import bearer, devices, owner, paired_token
from tests.support.license_support import (
    LICENSEE,
    OWNER_PUBLIC,
    STRANGER_PRIVATE,
    assert_logs_hold_none_of,
    signature_of,
    signed_key,
    watched,
)
from tests.support.settings import make_settings

URL = "/companion/v1/license"
UNLICENSED = {"state": "unlicensed"}


def license_app() -> FastAPI:
    settings = make_settings().model_copy(
        update={"companion_enabled": True, "license_public_key": OWNER_PUBLIC}
    )
    return create_app(settings, database_factory())


def put(client: TestClient, token: str, key: str) -> Any:
    return client.put(URL, json={"key": key}, headers=bearer(token))


def audit(app: FastAPI) -> list[tuple[str, str]]:
    with app.state.container.session_factory() as session:
        return [
            (row.event, row.outcome)
            for row in session.execute(
                select(AuditEventRow.event, AuditEventRow.outcome)
                .where(AuditEventRow.target_type == "instance_license")
                .order_by(AuditEventRow.occurred_at, AuditEventRow.id)
            )
        ]


@pytest.mark.integration
def test_get_shows_the_display_state_and_put_enters_a_key() -> None:
    app = license_app()
    user_id = owner(app)
    key = signed_key(expires=date(2099, 1, 1), kind="org", licensee="Förening X")
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        before = client.get(URL, headers=bearer(token))
        assert before.status_code == 200
        assert before.headers["cache-control"] == "no-store"
        assert before.json() == {"api_version": "companion.v1", **UNLICENSED}

        entered = put(client, token, key)
        assert entered.status_code == 200
        assert entered.headers["cache-control"] == "no-store"
        shown = {
            "state": "licensed",
            "licensee": "Förening X",
            "kind": "org",
            "expires": "2099-01-01",
        }
        assert entered.json() == {"api_version": "companion.v1", "accepted": True, **shown}
        # Nothing the answer says carries the key or its signature.
        assert key not in entered.text and signature_of(key) not in entered.text

        assert client.get(URL, headers=bearer(token)).json() == {
            "api_version": "companion.v1",
            **shown,
        }
        # The same display state rides in the bootstrap answer of a device.
        assert client.get("/companion/v1/device", headers=bearer(token)).json()["license"] == shown
    assert audit(app) == [("license.set", "success")]


@pytest.mark.integration
def test_pairing_answers_with_the_display_state_too() -> None:
    app = license_app()
    user_id = owner(app)
    app.state.container.license.set_key(signed_key(expires=date(2099, 1, 1)))
    with TestClient(app) as client:
        ticket = devices(app).create_pairing(user_id, "Samsung")
        paired = client.post("/companion/v1/pair", json={"pairing_secret": ticket.secret})
        assert paired.status_code == 201
        assert paired.json()["license"]["state"] == "licensed"
        assert paired.json()["license"]["licensee"] == LICENSEE


@pytest.mark.integration
def test_a_key_that_is_not_accepted_is_200_not_accepted_and_changes_nothing() -> None:
    app = license_app()
    user_id = owner(app)
    good = signed_key(licensee="Riktig Ägare")
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        assert put(client, token, good).json()["accepted"] is True
        for bad in (signed_key(key=STRANGER_PRIVATE), "ROADLAKE-1.x.y", "hello world"):
            answer = put(client, token, bad)
            assert answer.status_code == 200
            body = answer.json()
            assert body["accepted"] is False
            assert body["licensee"] == "Riktig Ägare"
            assert bad not in answer.text
        assert client.get(URL, headers=bearer(token)).json()["state"] == "licensed"
    assert audit(app) == [
        ("license.set", "success"),
        ("license.set", "denied"),
        ("license.set", "denied"),
    ]


@pytest.mark.integration
def test_entering_the_same_key_again_is_harmless_and_audits_nothing_new() -> None:
    app = license_app()
    user_id = owner(app)
    key = signed_key()
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        first, second = put(client, token, key).json(), put(client, token, f"{key}\n").json()
    assert first == second and first["accepted"] is True
    assert audit(app) == [("license.set", "success")]


@pytest.mark.integration
def test_a_device_without_the_license_capability_is_refused_but_still_sees_the_state() -> None:
    app = license_app()
    user_id = owner(app)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id, scopes=["companion:tasks:read"])
        for refused in (
            client.get(URL, headers=bearer(token)),
            put(client, token, signed_key()),
        ):
            assert refused.status_code == 403
            assert refused.headers["content-type"] == "application/problem+json"
            assert refused.json()["reason"] == "capability_missing"
        assert client.get("/companion/v1/device", headers=bearer(token)).json()["license"] == (
            UNLICENSED
        )
    assert audit(app) == []


@pytest.mark.integration
def test_only_the_installations_only_owner_may_enter_a_key() -> None:
    app = license_app()
    first = owner(app, "owner")
    owner(app, "second")
    with TestClient(app) as client:
        token = paired_token(client, app, first)
        refused = put(client, token, signed_key())
        assert refused.status_code == 403
        assert refused.json()["code"] == "forbidden"
        # Reading the state is not restricted to the owner.
        assert client.get(URL, headers=bearer(token)).status_code == 200
    # The refusal is audited (who, and that it was denied), never the key.
    assert audit(app) == [("license.set", "denied")]


@pytest.mark.integration
def test_no_valid_credential_is_401_before_the_body_is_read() -> None:
    app = license_app()
    owner(app)
    with TestClient(app) as client:
        for headers in ({}, bearer("cht_" + "x" * 40)):
            assert client.get(URL, headers=headers).status_code == 401
            answer = client.put(URL, content=b"x" * 100_000, headers=headers)
            assert answer.status_code == 401
            assert answer.json()["code"] == "unauthorized"
    assert audit(app) == []


@pytest.mark.integration
def test_the_body_is_capped_typed_and_closed_and_a_refusal_never_echoes_the_key() -> None:
    app = license_app()
    user_id = owner(app)
    key = signed_key()
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        headers = bearer(token)
        too_large = client.put(
            URL,
            content=b'{"key":"' + b"A" * 3000 + b'"}',
            headers={**headers, "Content-Type": "application/json"},
        )
        assert too_large.status_code == 413 and too_large.json()["code"] == "payload_too_large"
        wrong_type = client.put(URL, content=key, headers={**headers, "Content-Type": "text/plain"})
        assert wrong_type.status_code == 415
        for body in (
            {"key": key, "user_id": str(UUID(int=1))},
            {"key": ""},
            {"key": "A" * 2000 + "SECRETTAIL"},
            {"license_key": key},
            {"key": 5},
            {},
        ):
            refused = client.put(URL, json=body, headers=headers)
            assert refused.status_code == 422, body
            assert refused.json()["code"] == "validation_error"
            assert key not in refused.text and "SECRETTAIL" not in refused.text
        # Nothing was stored by any of it.
        assert client.get(URL, headers=headers).json()["state"] == "unlicensed"
    assert audit(app) == []


@pytest.mark.integration
def test_no_log_line_carries_the_key_the_signature_or_the_licensee(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = license_app()
    user_id = owner(app)
    good = signed_key()
    forged = signed_key(key=STRANGER_PRIVATE, licensee="Bedragare Hemlig")
    with watched(caplog), TestClient(app) as client:
        token = paired_token(client, app, user_id)
        put(client, token, good)
        put(client, token, forged)
        put(client, token, "A" * 1500 + "SECRETTAIL")
        client.get(URL, headers=bearer(token))
        client.get("/companion/v1/device", headers=bearer(token))
    operations = {
        getattr(record, "companion_operation", None)
        for record in caplog.records
        if record.getMessage() == "companion_request"
    }
    assert {"license.show", "license.set"} <= operations
    assert_logs_hold_none_of(
        caplog,
        good,
        forged,
        signature_of(good),
        signature_of(forged),
        LICENSEE,
        "Bedragare",
        "SECRETTAIL",
        token,
    )
