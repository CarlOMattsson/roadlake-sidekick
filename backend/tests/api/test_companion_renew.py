"""`POST /companion/v1/device/renew` (ADR-005, D-077): a device renews its own credential in the
last seven days, the old one lives on until the new one is first used (at most ten minutes), and
five renewals a day are the most one pairing gets. The clock is pinned for the whole app."""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text

from sidekick.api.app import create_app
from sidekick.companion.service import (
    MAX_RENEWALS_PER_DAY,
    RenewalNotDue,
    RenewalRateLimited,
)
from sidekick.shared.persistence.models import AuditEventRow, PersonalAccessTokenRow
from tests.db import database_factory
from tests.support.companion import bearer, companion_app, devices, owner, paired_token
from tests.support.settings import make_settings

START = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
RENEW = "/companion/v1/device/renew"
DEVICE = "/companion/v1/device"
AGENDA = "/companion/v1/work/agenda"


class PinnedClock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> PinnedClock:
    pinned = PinnedClock()
    monkeypatch.setattr("sidekick.companion.service.utc_now", pinned)
    monkeypatch.setattr("sidekick.shared.auth.service.utc_now", pinned)
    return pinned


def status(client: TestClient, token: str) -> int:
    return client.get(DEVICE, headers=bearer(token)).status_code


def renew(client: TestClient, token: str, **kwargs: Any) -> Any:
    return client.post(RENEW, headers=bearer(token), **kwargs)


def device_row(app: FastAPI, device_id: str) -> PersonalAccessTokenRow:
    with app.state.container.session_factory() as session:
        row = session.get(PersonalAccessTokenRow, UUID(device_id))
        assert row is not None
        session.expunge(row)
        return row


@pytest.mark.integration
def test_renewing_too_early_is_a_409_that_says_when(clock: PinnedClock) -> None:
    app = companion_app()
    user_id = owner(app)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        expires = datetime.fromisoformat(
            client.get(DEVICE, headers=bearer(token)).json()["device"]["expires_at"]
        )
        clock.advance(days=22, hours=23)
        response = renew(client, token)
        assert response.status_code == 409
        assert response.headers["content-type"].startswith("application/problem+json")
        body = response.json()
        assert body["code"] == "conflict" and body["reason"] == "renewal_not_due"
        assert datetime.fromisoformat(body["renew_after"]) == expires - timedelta(days=7)
        assert body["api_version"] == "companion.v1"
        assert "access_token" not in body
        # Nothing was issued: the credential is unchanged.
        assert status(client, token) == 200
        # The boundary itself: exactly seven days left is due.
        clock.advance(hours=1)
        renewed = renew(client, token)
        assert renewed.status_code == 200
        # The renewal keeps the app's copy of the instance's rooms current too.
        assert renewed.json()["enabled_rooms"] == [
            "work",
            "journal",
            "shopping",
            "contacts",
            "control",
        ]
        assert renewed.json()["push_enabled"] is False


@pytest.mark.integration
def test_renewal_tells_the_phone_when_the_server_delivers_push(clock: PinnedClock) -> None:
    settings = make_settings().model_copy(update={"companion_enabled": True, "push_enabled": True})
    app = create_app(settings, database_factory())
    user_id = owner(app)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        clock.advance(days=25)
        assert renew(client, token).json()["push_enabled"] is True


@pytest.mark.integration
def test_renewal_gives_a_working_token_and_the_old_one_lives_until_the_new_one_is_used(
    clock: PinnedClock,
) -> None:
    app = companion_app()
    user_id = owner(app)
    with TestClient(app) as client:
        old = paired_token(client, app, user_id)
        before = client.get(DEVICE, headers=bearer(old)).json()["device"]
        clock.advance(days=25)
        response = renew(client, old)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        body = response.json()
        assert body["api_version"] == "companion.v1" and body["token_type"] == "Bearer"
        new = body["access_token"]
        assert new.startswith("rsc_") and new != old
        device = body["device"]
        assert device["id"] == before["id"] and device["scopes"] == before["scopes"]
        assert datetime.fromisoformat(device["expires_at"]) == clock.now + timedelta(days=30)
        assert datetime.fromisoformat(device["renew_after"]) == clock.now + timedelta(days=23)

        # Stored as a keyed digest, like at pairing; the previous digest is the only other one.
        row = device_row(app, before["id"])
        auth = app.state.container.auth
        assert row.token_digest == auth.digest(new)
        assert row.previous_token_digest == auth.digest(old)
        assert new not in {row.token_digest, row.previous_token_digest}
        assert row.previous_valid_until == clock.now + timedelta(minutes=10)

        # The old credential still works (a lost answer must not strand the device) ...
        assert status(client, old) == 200
        assert status(client, old) == 200
        # ... until the new one is used for the first time.
        assert status(client, new) == 200
        assert status(client, old) == 401
        assert status(client, new) == 200
        row = device_row(app, before["id"])
        assert row.previous_token_digest is None and row.previous_valid_until is None


@pytest.mark.integration
def test_a_late_verify_does_not_clear_a_grace_window_set_after_it_read_the_row(
    clock: PinnedClock,
) -> None:
    app = companion_app()
    user_id = owner(app)
    with TestClient(app) as client:
        old = paired_token(client, app, user_id)
        device_id = client.get(DEVICE, headers=bearer(old)).json()["device"]["id"]
        clock.advance(days=25)
        new = renew(client, old).json()["access_token"]
        auth = app.state.container.auth
        newer_previous = auth.digest("a-later-previous-token")
        with app.state.container.session_factory() as session:
            engine = session.get_bind()
        armed = [True]

        def interleave(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
            # A concurrent renewal commits between verify's read and its bookkeeping UPDATE.
            if armed[0] and statement.lstrip().upper().startswith("SELECT"):
                armed[0] = False
                with engine.begin() as other:  # type: ignore[union-attr]
                    other.execute(
                        text(
                            "UPDATE sidekick.personal_access_tokens "
                            "SET previous_token_digest = :d, previous_valid_until = :u "
                            "WHERE id = :id"
                        ),
                        {
                            "d": newer_previous,
                            "u": clock.now + timedelta(minutes=10),
                            "id": device_id,
                        },
                    )

        event.listen(engine, "after_cursor_execute", interleave)
        try:
            assert status(client, new) == 200
        finally:
            event.remove(engine, "after_cursor_execute", interleave)
        assert not armed[0]
        row = device_row(app, device_id)
        assert row.previous_token_digest == newer_previous
        assert row.previous_valid_until == clock.now + timedelta(minutes=10)


@pytest.mark.integration
def test_the_old_token_stops_after_ten_minutes_even_if_the_new_one_was_never_used(
    clock: PinnedClock,
) -> None:
    app = companion_app()
    user_id = owner(app)
    with TestClient(app) as client:
        old = paired_token(client, app, user_id)
        clock.advance(days=25)
        new = renew(client, old).json()["access_token"]
        clock.advance(minutes=9, seconds=59)
        assert status(client, old) == 200
        clock.advance(seconds=1)
        assert status(client, old) == 401
        assert status(client, new) == 200


@pytest.mark.integration
def test_retrying_with_the_old_token_in_its_window_leaves_exactly_one_valid_new_token(
    clock: PinnedClock,
) -> None:
    app = companion_app()
    user_id = owner(app)
    with TestClient(app) as client:
        old = paired_token(client, app, user_id)
        clock.advance(days=25)
        first = renew(client, old).json()["access_token"]
        # The answer was lost; the device asks again with what it still has.
        clock.advance(minutes=2)
        retry = renew(client, old)
        assert retry.status_code == 200
        second = retry.json()["access_token"]
        assert second not in {old, first}
        # The token nobody saw is gone; the window is the original ten minutes.
        assert status(client, first) == 401
        assert status(client, old) == 200
        clock.advance(minutes=8)
        assert status(client, old) == 401
        assert status(client, second) == 200
        # Once the new token has been used, the old one cannot renew at all.
        assert renew(client, old).status_code == 401


@pytest.mark.integration
def test_the_new_token_cannot_renew_again_straight_away(clock: PinnedClock) -> None:
    app = companion_app()
    user_id = owner(app)
    with TestClient(app) as client:
        old = paired_token(client, app, user_id)
        clock.advance(days=25)
        new = renew(client, old).json()["access_token"]
        again = renew(client, new)
        assert again.status_code == 409 and again.json()["reason"] == "renewal_not_due"


@pytest.mark.integration
def test_expired_revoked_unknown_and_disabled_credentials_cannot_renew(clock: PinnedClock) -> None:
    app = companion_app()
    user_id = owner(app)
    with TestClient(app) as client:
        expired = paired_token(client, app, user_id)
        revoked = paired_token(client, app, user_id)
        unpaired = paired_token(client, app, user_id)
        revoked_id = UUID(client.get(DEVICE, headers=bearer(revoked)).json()["device"]["id"])
        assert devices(app).revoke_device(user_id, revoked_id)
        assert client.delete(DEVICE, headers=bearer(unpaired)).status_code == 204
        clock.advance(days=30, seconds=1)
        # Everything lapsed with the clock: expired, and the later pairings too.
        assert renew(client, expired).status_code == 401
        assert renew(client, revoked).status_code == 401
        assert renew(client, unpaired).status_code == 401
        assert renew(client, "rsc_" + "A" * 50).status_code == 401
        assert client.post(RENEW).status_code == 401
        # Disabled owner with a credential that is otherwise due.
        clock.now = START
        fresh = paired_token(client, app, user_id)
        clock.advance(days=25)
        app.state.container.auth.disable_user(user_id)
        assert renew(client, fresh).status_code == 401
        for response in (renew(client, expired), renew(client, revoked)):
            assert response.json()["code"] == "unauthorized"
            assert "access_token" not in response.json()


@pytest.mark.integration
def test_a_renewal_the_clock_has_overtaken_is_refused_under_the_lock(clock: PinnedClock) -> None:
    app = companion_app()
    user_id = owner(app)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        device_id = UUID(client.get(DEVICE, headers=bearer(token)).json()["device"]["id"])
        clock.advance(days=30, seconds=1)
        assert devices(app).renew(user_id, device_id, token) is None


@pytest.mark.integration
def test_auth_comes_before_the_body_and_the_body_is_capped(clock: PinnedClock) -> None:
    app = companion_app()
    user_id = owner(app)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        clock.advance(days=25)
        big = b'{"x": "' + b"a" * 1000 + b'"}'
        assert client.post(RENEW, content=big).status_code == 401
        assert renew(client, token, content=big).status_code == 413
        junk = renew(client, token, content=b'{"user_id": "x"}')
        assert junk.status_code == 422 and junk.json()["code"] == "validation_error"
        assert status(client, token) == 200
        assert renew(client, token, content=b"{}").status_code == 200


@pytest.mark.integration
def test_two_simultaneous_renewals_leave_one_valid_new_token(clock: PinnedClock) -> None:
    app = companion_app()
    user_id = owner(app)
    with TestClient(app) as client:
        old = paired_token(client, app, user_id)
        device_id = UUID(client.get(DEVICE, headers=bearer(old)).json()["device"]["id"])
        clock.advance(days=25)
        service = devices(app)
        barrier = threading.Barrier(2)
        issued: list[str] = []
        errors: list[BaseException] = []
        lock = threading.Lock()

        def run() -> None:
            barrier.wait()
            try:
                paired = service.renew(user_id, device_id, old)
            except BaseException as error:
                with lock:
                    errors.append(error)
                return
            assert paired is not None
            with lock:
                issued.append(paired.token)

        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert not errors and len(issued) == 2 and issued[0] != issued[1]
        # Renewed twice; only the last token issued is alive, the old one is still in its window.
        row = device_row(app, str(device_id))
        auth = app.state.container.auth
        valid = [token for token in issued if auth.verify_companion_token(token) is not None]
        assert len(valid) == 1 and row.token_digest == auth.digest(valid[0])
        assert row.previous_token_digest == auth.digest(old)
        with app.state.container.session_factory() as session:
            events = session.scalars(
                select(AuditEventRow).where(AuditEventRow.event == "companion.device_renewed")
            ).all()
        assert len(events) == 2


@pytest.mark.integration
def test_five_renewals_a_day_then_429_with_retry_after(clock: PinnedClock) -> None:
    app = companion_app()
    user_id = owner(app)
    with TestClient(app) as client:
        ticket = devices(app).create_pairing(user_id, "Samsung", device_lifetime_days=1)
        token = client.post("/companion/v1/pair", json={"pairing_secret": ticket.secret}).json()[
            "access_token"
        ]
        for step in range(MAX_RENEWALS_PER_DAY):
            clock.advance(minutes=30)
            response = renew(client, token)
            assert response.status_code == 200, step
            token = response.json()["access_token"]
            assert status(client, token) == 200
        clock.advance(minutes=30)
        limited = renew(client, token)
        assert limited.status_code == 429
        assert limited.json()["code"] == "rate_limited"
        # The first renewal was 2h30m ago, so the budget frees up in 21h30m.
        assert limited.headers["retry-after"] == str(21 * 3600 + 30 * 60 + 1)
        assert limited.headers["cache-control"] == "no-store"
        assert "access_token" not in limited.json()
        # The credential is untouched and the next day's budget works.
        assert status(client, token) == 200
        clock.advance(hours=21, minutes=31)
        assert renew(client, token).status_code == 200


@pytest.mark.integration
def test_scopes_do_not_change_and_a_push_only_device_may_renew(clock: PinnedClock) -> None:
    app = companion_app()
    user_id = owner(app)
    with TestClient(app) as client:
        read_only = paired_token(client, app, user_id, scopes=["companion:tasks:read"])
        push_only = paired_token(client, app, user_id, scopes=["companion:push"])
        clock.advance(days=25)
        renewed_read = renew(client, read_only).json()
        renewed_push = renew(client, push_only)
        assert renewed_read["device"]["scopes"] == ["companion:tasks:read"]
        assert renewed_push.status_code == 200
        assert renewed_push.json()["device"]["scopes"] == ["companion:push"]
        new_read = renewed_read["access_token"]
        assert client.get(AGENDA, headers=bearer(new_read)).status_code == 200
        assert client.get(DEVICE, headers=bearer(new_read)).json()["device"]["scopes"] == [
            "companion:tasks:read"
        ]
        # The renewed device does not gain a capability it was never given.
        denied = client.post("/companion/v1/push/test", headers=bearer(new_read))
        assert denied.status_code == 403
        row = device_row(app, renewed_read["device"]["id"])
        assert row.scopes == ["companion:tasks:read"]


@pytest.mark.integration
def test_device_status_shows_expires_at_and_renew_after(clock: PinnedClock) -> None:
    app = companion_app()
    user_id = owner(app)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        device = client.get(DEVICE, headers=bearer(token)).json()["device"]
        assert datetime.fromisoformat(device["expires_at"]) == START + timedelta(days=30)
        assert datetime.fromisoformat(device["renew_after"]) == START + timedelta(days=23)


@pytest.mark.integration
def test_a_renewal_is_audited_without_a_token_and_logs_carry_no_secret(
    clock: PinnedClock, caplog: pytest.LogCaptureFixture
) -> None:
    app = companion_app()
    user_id = owner(app)
    caplog.set_level(logging.DEBUG)
    names = ["sidekick", "sidekick.companion", "uvicorn", "uvicorn.access", "fastapi", "sqlalchemy"]
    for name in names:
        logging.getLogger(name).addHandler(caplog.handler)
    try:
        with TestClient(app) as client:
            old = paired_token(client, app, user_id)
            clock.advance(days=25)
            early = renew(client, old, content=b'{"x": 1}')
            assert early.status_code == 422
            new = renew(client, old).json()["access_token"]
            assert renew(client, new).status_code == 409
    finally:
        for name in names:
            logging.getLogger(name).removeHandler(caplog.handler)
    auth = app.state.container.auth
    secrets_ = [old, new, auth.digest(old), auth.digest(new)]
    text = "\n".join(f"{record.getMessage()} {record.__dict__}" for record in caplog.records)
    assert "device.renew" in text
    for secret in secrets_:
        assert secret not in text
    with app.state.container.session_factory() as session:
        rows = session.scalars(
            select(AuditEventRow).where(AuditEventRow.event == "companion.device_renewed")
        ).all()
        everything = " ".join(
            str(value)
            for row in session.scalars(select(AuditEventRow))
            for value in (row.event, row.reason, row.target_type, row.target_id, row.correlation_id)
        )
    assert len(rows) == 1
    assert rows[0].actor_id == user_id and rows[0].outcome == "success"
    assert rows[0].target_type == "companion_device" and rows[0].occurred_at == clock.now
    for secret in secrets_:
        assert secret not in everything


@pytest.mark.integration
def test_audit_marks_a_renewal_made_through_the_previous_token(clock: PinnedClock) -> None:
    app = companion_app()
    user_id = owner(app)
    with TestClient(app) as client:
        old = paired_token(client, app, user_id)
        clock.advance(days=25)
        first = renew(client, old).json()["access_token"]
        clock.advance(minutes=2)
        assert renew(client, old).status_code == 200
    auth = app.state.container.auth
    with app.state.container.session_factory() as session:
        reasons = session.scalars(
            select(AuditEventRow.reason)
            .where(AuditEventRow.event == "companion.device_renewed")
            .order_by(AuditEventRow.id)
        ).all()
    # The normal renewal has no mark; the one through the replaced token does, and only that.
    assert reasons == [None, "via_previous_token"]
    assert first not in str(reasons) and auth.digest(old) not in str(reasons)


def test_service_errors_carry_only_the_when() -> None:
    assert RenewalNotDue(START).renew_after == START
    assert RenewalRateLimited(5).retry_after_seconds == 5
