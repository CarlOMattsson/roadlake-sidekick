"""`/companion/v1/` (ADR-005): purpose-separated device credentials, pairing, and routes
that answer exactly the MCP tools' structured content through the same use cases."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastmcp import Client
from sqlalchemy import func, select, update

from sidekick.api.app import create_app
from sidekick.api.companion import PAIR_FAILURES_PER_MINUTE
from sidekick.companion.persistence import CompanionDeviceStore
from sidekick.companion.service import CompanionDeviceService
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.auth import COMPANION_SCOPES, TOKEN_SCOPES
from sidekick.shared.errors import InvalidInputError
from sidekick.shared.persistence.models import (
    AuditEventRow,
    CompanionPairingRow,
    PersonalAccessTokenRow,
    TaskRow,
)
from sidekick.shared.types import MAX_CURSOR_LENGTH, utc_now
from tests.db import database_factory
from tests.support.companion import (
    TITLE,
    FixedClock,
    bearer,
    companion_app,
    create_task,
    devices,
    owner,
    owner_actor,
    paired_token,
)
from tests.support.settings import make_settings


@pytest.mark.integration
def test_routes_are_absent_unless_enabled() -> None:
    app = create_app(make_settings(), database_factory())
    with TestClient(app) as client:
        assert client.post("/companion/v1/pair", json={"pairing_secret": "x" * 40}).status_code == (
            404
        )
        assert client.get("/companion/v1/work/agenda").status_code == 404


@pytest.mark.integration
def test_pairing_exchanges_once_and_the_device_credential_works() -> None:
    app = companion_app()
    user_id = owner(app)
    ticket = devices(app).create_pairing(user_id, "  Samsung  ")
    assert ticket.secret.startswith("rspair_") and len(ticket.secret) >= 43
    assert ticket.expires_at - utc_now() <= timedelta(minutes=10)
    with TestClient(app) as client:
        first = client.post("/companion/v1/pair", json={"pairing_secret": ticket.secret})
        replay = client.post("/companion/v1/pair", json={"pairing_secret": ticket.secret})
        assert first.status_code == 201
        assert first.headers["cache-control"] == "no-store"
        body = first.json()
        assert body["api_version"] == "companion.v1"
        assert body["token_type"] == "Bearer"
        assert body["device"]["label"] == "Samsung"
        assert body["device"]["scopes"] == [
            "companion:journal:read",
            "companion:journal:write",
            "companion:license",
            "companion:push",
            "companion:shopping:read",
            "companion:shopping:write",
            "companion:tasks:complete",
            "companion:tasks:read",
        ]
        # A scope added to or removed from the device vocabulary must be a deliberate edit here.
        assert sorted(COMPANION_SCOPES) == body["device"]["scopes"]
        expires = datetime.fromisoformat(body["device"]["expires_at"])
        assert timedelta(days=29) < expires - utc_now() <= timedelta(days=30)
        assert replay.status_code == 401
        assert replay.json()["code"] == "pairing_invalid"
        assert replay.json()["api_version"] == "companion.v1"
        status = client.get("/companion/v1/device", headers=bearer(body["access_token"]))
        assert status.status_code == 200
        assert status.json()["device"]["id"] == body["device"]["id"]


@pytest.mark.integration
def test_the_device_answers_include_every_room_by_default() -> None:
    app = companion_app()
    user_id = owner(app)
    ticket = devices(app).create_pairing(user_id, "Samsung")
    every_room = ["work", "journal", "shopping", "contacts", "control"]
    with TestClient(app) as client:
        paired = client.post("/companion/v1/pair", json={"pairing_secret": ticket.secret}).json()
        assert paired["enabled_rooms"] == every_room
        token = paired["access_token"]
        status = client.get("/companion/v1/device", headers=bearer(token))
        assert status.json()["enabled_rooms"] == every_room
        # The owner's zone rides on every device answer, for the phone's dates and reminder times.
        assert paired["timezone"] == status.json()["timezone"] == "Europe/Stockholm"
        # The field is additive: the device object an older app reads is unchanged.
        assert status.json()["device"]["id"] == paired["device"]["id"]
        # Push is off by default, and the phone is told so it hides its push row.
        assert paired["push_enabled"] is False
        assert status.json()["push_enabled"] is False


@pytest.mark.integration
def test_the_device_answers_say_when_the_server_delivers_push() -> None:
    settings = make_settings().model_copy(update={"companion_enabled": True, "push_enabled": True})
    app = create_app(settings, database_factory())
    user_id = owner(app)
    ticket = devices(app).create_pairing(user_id, "Samsung")
    with TestClient(app) as client:
        paired = client.post("/companion/v1/pair", json={"pairing_secret": ticket.secret}).json()
        status = client.get("/companion/v1/device", headers=bearer(paired["access_token"]))
        assert paired["push_enabled"] is True
        assert status.json()["push_enabled"] is True


@pytest.mark.integration
def test_the_device_answers_name_only_the_rooms_the_instance_shows() -> None:
    settings = make_settings().model_copy(
        update={"companion_enabled": True, "enabled_rooms": "work,journal"}
    )
    app = create_app(settings, database_factory())
    user_id = owner(app)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        status = client.get("/companion/v1/device", headers=bearer(token))
        assert status.status_code == 200
        assert status.json()["enabled_rooms"] == ["work", "journal"]
        # The room that is off has no route, the one that is on has.
        assert client.get("/companion/v1/shopping/lists", headers=bearer(token)).status_code == 404
        assert client.get("/companion/v1/device", headers=bearer(token)).status_code == 200


@pytest.mark.integration
def test_expired_unknown_and_malformed_pairing_secrets_are_refused() -> None:
    app = companion_app()
    user_id = owner(app)
    container = app.state.container
    past = CompanionDeviceService(
        CompanionDeviceStore(container.session_factory),
        container.auth,
        clock=lambda: utc_now() - timedelta(minutes=11),
    )
    expired = past.create_pairing(user_id, "Old phone")
    with TestClient(app) as client:
        for secret in (expired.secret, "rspair_" + "A" * 43):
            response = client.post("/companion/v1/pair", json={"pairing_secret": secret})
            assert response.status_code == 401
            assert response.json()["code"] == "pairing_invalid"
        malformed = client.post("/companion/v1/pair", json={"pairing_secret": "short"})
        assert malformed.status_code == 422
        assert malformed.json()["api_version"] == "companion.v1"
        extra = client.post(
            "/companion/v1/pair", json={"pairing_secret": "x" * 40, "user_id": str(user_id)}
        )
        assert extra.status_code == 422
        too_big = client.post(
            "/companion/v1/pair",
            content=b'{"pairing_secret": "' + b"x" * 2000 + b'"}',
            headers={"Content-Type": "application/json"},
        )
        assert too_big.status_code == 413


@pytest.mark.integration
def test_concurrent_exchanges_of_one_secret_create_exactly_one_device() -> None:
    app = companion_app()
    user_id = owner(app)
    service = devices(app)
    ticket = service.create_pairing(user_id, "Samsung")
    barrier = threading.Barrier(8)
    results: list[Any] = []
    lock = threading.Lock()

    def exchange() -> None:
        barrier.wait()
        paired = service.exchange(ticket.secret)
        with lock:
            results.append(paired)

    threads = [threading.Thread(target=exchange) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len([item for item in results if item is not None]) == 1
    with app.state.container.session_factory() as session:
        count = session.scalar(
            select(func.count())
            .select_from(PersonalAccessTokenRow)
            .where(PersonalAccessTokenRow.purpose == "companion")
        )
        pairing = session.scalar(select(CompanionPairingRow))
    assert count == 1
    assert pairing is not None and pairing.consumed_at is not None
    assert pairing.device_token_id == next(item for item in results if item).device.id


@pytest.mark.integration
def test_failed_pairings_are_rate_limited_and_a_spent_budget_refuses_before_any_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = companion_app()
    user_id = owner(app)
    ticket = devices(app).create_pairing(user_id, "Samsung")
    exchanged: list[str] = []
    real_exchange = CompanionDeviceService.exchange

    def spy(self: CompanionDeviceService, secret: str, **kwargs: Any) -> Any:
        exchanged.append(secret)
        return real_exchange(self, secret, **kwargs)

    monkeypatch.setattr(CompanionDeviceService, "exchange", spy)
    with TestClient(app) as client:
        statuses = [
            client.post("/companion/v1/pair", json={"pairing_secret": "x" * 40}).status_code
            for _ in range(PAIR_FAILURES_PER_MINUTE + 5)
        ]
        calls_when_spent = len(exchanged)
        refused = client.post("/companion/v1/pair", json={"pairing_secret": ticket.secret})
    assert statuses[: PAIR_FAILURES_PER_MINUTE - 1] == [401] * (PAIR_FAILURES_PER_MINUTE - 1)
    assert statuses[-1] == 429
    # Only the attempts inside the budget reached the exchange service; the rest were refused
    # first, including a request carrying a real secret, which is left unused.
    assert calls_when_spent == PAIR_FAILURES_PER_MINUTE
    assert len(exchanged) == calls_when_spent
    assert refused.status_code == 429
    # One token refills every 2 s, so the wait is 1 or 2 s, never the old fixed minute.
    assert refused.headers["retry-after"] in {"1", "2"}
    with app.state.container.session_factory() as session:
        pairing = session.scalar(
            select(CompanionPairingRow).where(CompanionPairingRow.id == ticket.pairing_id)
        )
    assert pairing is not None and pairing.consumed_at is None


@pytest.mark.integration
def test_concurrent_bad_pairings_cannot_overshoot_the_failure_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = companion_app()
    attempts = PAIR_FAILURES_PER_MINUTE * 3
    reached = 0
    lock = threading.Lock()
    gate = threading.Event()  # no exchange returns before every refused request has been refused

    def slow_failure(self: CompanionDeviceService, secret: str, **kwargs: Any) -> None:
        nonlocal reached
        with lock:
            reached += 1
        gate.wait(10)

    monkeypatch.setattr(CompanionDeviceService, "exchange", slow_failure)

    async def fire() -> list[int]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            tasks = [
                asyncio.create_task(
                    client.post("/companion/v1/pair", json={"pairing_secret": "x" * 40})
                )
                for _ in range(attempts)
            ]
            # Every request past the budget is refused without waiting for an exchange. Once those
            # have answered, all the others are in flight, and the exchanges may finish. If the
            # budget overshoots, fewer are refused; the deadline then releases the gate and the
            # assertions below report the overshoot.
            refused = attempts - PAIR_FAILURES_PER_MINUTE
            try:
                deadline = time.monotonic() + 5
                while sum(task.done() for task in tasks) < refused and time.monotonic() < deadline:
                    await asyncio.sleep(0.01)  # polling interval
            finally:
                gate.set()
            responses = await asyncio.gather(*tasks)
        return [response.status_code for response in responses]

    with TestClient(app):  # runs the app lifespan
        statuses = asyncio.run(fire())
    assert reached <= PAIR_FAILURES_PER_MINUTE
    assert statuses.count(401) == reached
    assert statuses.count(429) == attempts - reached
    assert statuses.count(429) >= attempts - PAIR_FAILURES_PER_MINUTE


@pytest.mark.integration
def test_successful_pairings_do_not_consume_the_failure_budget() -> None:
    app = companion_app()
    user_id = owner(app)
    with TestClient(app) as client:
        for _ in range(PAIR_FAILURES_PER_MINUTE + 5):
            paired_token(client, app, user_id)
        # Every success refunded its reservation, so a full budget of failures is still available.
        statuses = [
            client.post("/companion/v1/pair", json={"pairing_secret": "x" * 40}).status_code
            for _ in range(PAIR_FAILURES_PER_MINUTE - 1)
        ]
    assert statuses == [401] * (PAIR_FAILURES_PER_MINUTE - 1)


@pytest.mark.integration
def test_unknown_secrets_write_no_audit_row_but_a_real_pairing_does() -> None:
    app = companion_app()
    user_id = owner(app)
    ticket = devices(app).create_pairing(user_id, "Samsung")

    def events() -> list[str]:
        with app.state.container.session_factory() as session:
            return list(
                session.scalars(
                    select(AuditEventRow.event).where(AuditEventRow.event.like("companion.%"))
                )
            )

    before = events()
    with TestClient(app) as client:
        for index in range(5):
            refused = client.post(
                "/companion/v1/pair", json={"pairing_secret": f"rspair_{index:043d}"}
            )
            assert refused.status_code == 401
        assert events() == before
        paired = client.post("/companion/v1/pair", json={"pairing_secret": ticket.secret})
        assert paired.status_code == 201
        replay = client.post("/companion/v1/pair", json={"pairing_secret": ticket.secret})
        assert replay.status_code == 401
    after = events()
    assert after.count("companion.device_paired") == 1
    assert len(after) == len(before) + 1
    with app.state.container.session_factory() as session:
        row = session.scalar(
            select(AuditEventRow).where(AuditEventRow.event == "companion.device_paired")
        )
    assert row is not None and row.outcome == "success"
    assert str(row.target_id) == paired.json()["device"]["id"]


@pytest.mark.integration
def test_a_disabled_owners_pairing_is_used_up_without_a_device() -> None:
    app = companion_app()
    user_id = owner(app)
    ticket = devices(app).create_pairing(user_id, "Samsung")
    app.state.container.auth.disable_user(user_id)
    assert devices(app).exchange(ticket.secret) is None
    with app.state.container.session_factory() as session:
        assert session.scalar(select(CompanionPairingRow.consumed_at)) is not None
        assert session.scalar(select(func.count()).select_from(PersonalAccessTokenRow)) == 0


@pytest.mark.integration
def test_pairing_scopes_and_lifetime_are_bounded() -> None:
    app = companion_app()
    user_id = owner(app)
    service = devices(app)
    for kwargs in (
        {"scopes": {"tasks:write"}},
        {"scopes": set()},
        {"device_lifetime_days": 0},
        {"device_lifetime_days": 91},
        {"ttl": timedelta(minutes=11)},
    ):
        with pytest.raises(InvalidInputError):
            service.create_pairing(user_id, "Samsung", **kwargs)
    with pytest.raises(InvalidInputError):
        service.create_pairing(user_id, "bad\nlabel")
    with pytest.raises(ValueError):
        app.state.container.auth.create_personal_token(
            user_id, "no", scopes=frozenset({"companion:tasks:read"})
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_companion_credential_is_refused_by_mcp_and_a_pat_by_companion() -> None:
    app = companion_app()
    user_id = owner(app)
    pat = app.state.container.auth.create_personal_token(user_id, "mcp", TOKEN_SCOPES)
    with TestClient(app) as client:
        device = paired_token(client, app, user_id)
        refused = client.get("/companion/v1/work/agenda", headers=bearer(pat))
        assert refused.status_code == 401
        assert refused.json()["code"] == "unauthorized"
        assert "Bearer" in refused.headers["www-authenticate"]
        assert client.get("/companion/v1/work/agenda").status_code == 401
        # There is no REST API or web session for a companion credential to open (D-082).
        assert client.get("/api/v1/session", headers=bearer(device)).status_code == 404
    assert app.state.container.auth.verify_personal_token(device) is None
    assert app.state.container.auth.verify_companion_token(pat) is None
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        response = await client.post(
            "/mcp/",
            headers={**bearer(device), "Accept": "application/json, text/event-stream"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "t", "version": "1"},
                },
            },
        )
        accepted = await client.post(
            "/mcp/",
            headers={**bearer(pat), "Accept": "application/json, text/event-stream"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "t", "version": "1"},
                },
            },
        )
    assert response.status_code == 401
    assert accepted.status_code == 200


@pytest.mark.integration
def test_revoked_expired_and_inactive_devices_are_refused_on_the_next_call() -> None:
    app = companion_app()
    user_id = owner(app)
    with TestClient(app) as client:
        revoked = paired_token(client, app, user_id)
        expired = paired_token(client, app, user_id)
        unpaired = paired_token(client, app, user_id)
        disabled = paired_token(client, app, user_id)
        for token in (revoked, expired, unpaired, disabled):
            assert client.get("/companion/v1/work/agenda", headers=bearer(token)).status_code == (
                200
            )
        service = devices(app)
        listed = {item.id for item in service.list_devices(user_id)}
        revoked_id = UUID(
            client.get("/companion/v1/device", headers=bearer(revoked)).json()["device"]["id"]
        )
        expired_id = UUID(
            client.get("/companion/v1/device", headers=bearer(expired)).json()["device"]["id"]
        )
        assert {revoked_id, expired_id} <= listed
        assert service.revoke_device(user_id, revoked_id)
        with app.state.container.session_factory.begin() as session:
            session.execute(
                update(PersonalAccessTokenRow)
                .where(PersonalAccessTokenRow.id == expired_id)
                .values(expires_at=utc_now() - timedelta(seconds=1))
            )
        assert client.delete("/companion/v1/device", headers=bearer(unpaired)).status_code == 204
        for token in (revoked, expired, unpaired):
            assert client.get("/companion/v1/work/agenda", headers=bearer(token)).status_code == (
                401
            )
        assert client.delete("/companion/v1/device", headers=bearer(unpaired)).status_code == 401
        app.state.container.auth.disable_user(user_id)
        assert client.get("/companion/v1/device", headers=bearer(disabled)).status_code == 401


@pytest.mark.integration
def test_another_owners_task_is_not_found_and_a_read_only_device_cannot_complete() -> None:
    app = companion_app()
    user_id = owner(app)
    stranger = owner(app, "stranger")
    foreign = create_task(app, stranger, due_at=utc_now())
    mine = create_task(app, user_id, due_at=utc_now())
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        reader = paired_token(client, app, user_id, scopes={"companion:tasks:read"})
        assert (
            client.get(f"/companion/v1/tasks/{foreign.id}", headers=bearer(token)).json()["code"]
            == "not_found"
        )
        completed = client.post(
            f"/companion/v1/tasks/{foreign.id}/complete",
            headers={**bearer(token), "Idempotency-Key": "foreign-complete-1"},
            json={"version": foreign.version},
        )
        assert completed.status_code == 404
        agenda = client.get("/companion/v1/work/agenda", headers=bearer(token)).json()
        assert [item["id"] for item in agenda["items"]] == [str(mine.id)]
        denied = client.post(
            f"/companion/v1/tasks/{mine.id}/complete",
            headers={**bearer(reader), "Idempotency-Key": "reader-complete-1"},
            json={"version": mine.version},
        )
        assert denied.status_code == 403
        assert denied.json()["reason"] == "capability_missing"
        assert client.get(f"/companion/v1/tasks/{mine.id}", headers=bearer(reader)).status_code == (
            200
        )
    assert app.state.container.tasks.get(owner_actor(user_id), mine.id).status.value == "todo"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_agenda_task_and_steps_equal_the_mcp_structured_content() -> None:
    app = companion_app()
    user_id = owner(app)
    actor = owner_actor(user_id)
    now = utc_now()
    mcp = create_mcp_server(app.state.container, actor_provider=lambda: actor, enable_auth=False)
    async with Client(mcp) as mcp_client:
        contact = await mcp_client.call_tool(
            "create_contact",
            {"display_name": "Anna Andersson", "idempotency_key": "contact-key-0001"},
        )
        waiting = create_task(app, user_id, title="Vänta på Anna", due_at=now + timedelta(days=2))
        await mcp_client.call_tool(
            "update_task",
            {
                "task_id": str(waiting.id),
                "version": waiting.version,
                "idempotency_key": "waiting-key-0001",
                "changes": {
                    "waiting_on_contact_id": contact.structured_content["contact"]["id"],
                    "waiting_since": now.isoformat(),
                },
            },
        )
        overdue = create_task(app, user_id, due_at=now - timedelta(days=1), tags=("hemma",))
        create_task(app, user_id, title="Idag", due_at=now + timedelta(minutes=5))
        create_task(app, user_id, title="Odaterad", estimated_minutes=10)
        await mcp_client.call_tool(
            "create_task_step",
            {
                "task_id": str(overdue.id),
                "title": "Första steget",
                "idempotency_key": "step-key-0001",
            },
        )
        cases: list[tuple[dict[str, Any], str]] = [
            ({}, ""),
            ({"limit": 2}, "limit=2"),
            ({"include_undated": True, "max_minutes": 15}, "include_undated=true&max_minutes=15"),
            ({"tags": ["hemma"], "sort": "title_asc"}, "tags=hemma&sort=title_asc"),
            ({"waiting": "waiting"}, "waiting=waiting"),
        ]
        expected = [
            (await mcp_client.call_tool("get_work_agenda", arguments)).structured_content
            for arguments, _query in cases
        ]
        task = await mcp_client.call_tool("get_task", {"task_id": str(overdue.id)})
        steps = await mcp_client.call_tool("list_task_steps", {"task_id": str(overdue.id)})
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        for (arguments, query), wanted in zip(cases, expected, strict=True):
            response = client.get(f"/companion/v1/work/agenda?{query}", headers=bearer(token))
            assert response.status_code == 200, arguments
            assert response.json() == wanted, arguments
        assert any(
            item.get("waiting_on_contact_name") == "Anna Andersson" for item in expected[4]["items"]
        )
        assert expected[1]["next_cursor"]
        follow = client.get(
            "/companion/v1/work/agenda",
            params={"limit": 2, "cursor": expected[1]["next_cursor"]},
            headers=bearer(token),
        )
        assert follow.status_code == 200
        detail = client.get(f"/companion/v1/tasks/{overdue.id}", headers=bearer(token))
        assert detail.json() == task.structured_content
        listed = client.get(f"/companion/v1/tasks/{overdue.id}/steps", headers=bearer(token))
        assert listed.json() == steps.structured_content
        assert listed.json()["items"][0]["title"] == "Första steget"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_task_contacts_and_external_references_equal_the_mcp_structured_content() -> None:
    app = companion_app()
    user_id = owner(app)
    actor = owner_actor(user_id)
    task = create_task(app, user_id)
    mcp = create_mcp_server(app.state.container, actor_provider=lambda: actor, enable_auth=False)
    async with Client(mcp) as mcp_client:
        for index in range(3):
            contact = await mcp_client.call_tool(
                "create_contact",
                {
                    "display_name": f"Kontakt {index}",
                    "idempotency_key": f"contact-key-000{index}",
                    "email": f"kontakt{index}@example.test",
                    "phone": f"+4670000000{index}",
                },
            )
            await mcp_client.call_tool(
                "link_contact_to_task",
                {
                    "contact_id": contact.structured_content["contact"]["id"],
                    "task_id": str(task.id),
                    "idempotency_key": f"link-contact-000{index}",
                },
            )
            await mcp_client.call_tool(
                "link_external_reference_to_task",
                {
                    "task_id": str(task.id),
                    "kind": "mail",
                    "provider": "google_gmail",
                    "account_ref": "konto@example.test",
                    "external_id": f"mail-{index}",
                    "title": f"Mejl {index}",
                    "url": f"https://mail.google.com/mail/u/0/#inbox/ref{index}",
                    "idempotency_key": f"link-ref-000{index}",
                },
            )
        contacts = await mcp_client.call_tool("list_task_contacts", {"task_id": str(task.id)})
        contacts_page = await mcp_client.call_tool(
            "list_task_contacts", {"task_id": str(task.id), "limit": 2}
        )
        refs = await mcp_client.call_tool(
            "list_task_external_references", {"task_id": str(task.id)}
        )
        refs_page = await mcp_client.call_tool(
            "list_task_external_references", {"task_id": str(task.id), "limit": 2}
        )
    assert len(contacts.structured_content["items"]) == 3
    assert contacts_page.structured_content["next_cursor"]
    assert refs_page.structured_content["next_cursor"]
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        base = f"/companion/v1/tasks/{task.id}"
        got = client.get(f"{base}/contacts", headers=bearer(token))
        assert got.status_code == 200
        assert got.json() == contacts.structured_content
        # Summaries only: no address leaves through the companion route.
        assert "example.test" not in got.text and "+46700" not in got.text
        paged = client.get(f"{base}/contacts?limit=2", headers=bearer(token))
        assert paged.json() == contacts_page.structured_content
        follow = client.get(
            f"{base}/contacts",
            params={"limit": 2, "cursor": contacts_page.structured_content["next_cursor"]},
            headers=bearer(token),
        )
        assert follow.status_code == 200 and len(follow.json()["items"]) == 1
        got = client.get(f"{base}/external-references", headers=bearer(token))
        assert got.json() == refs.structured_content
        paged = client.get(f"{base}/external-references?limit=2", headers=bearer(token))
        assert paged.json() == refs_page.structured_content
        follow = client.get(
            f"{base}/external-references",
            params={"limit": 2, "cursor": refs_page.structured_content["next_cursor"]},
            headers=bearer(token),
        )
        assert follow.status_code == 200 and len(follow.json()["items"]) == 1


@pytest.mark.integration
@pytest.mark.parametrize("suffix", ["contacts", "external-references"])
def test_linked_record_reads_deny_foreign_owners_and_missing_scope(suffix: str) -> None:
    app = companion_app()
    user_id = owner(app)
    other_id = owner(app, "other")
    foreign = create_task(app, other_id, title="Annans uppgift")
    mine = create_task(app, user_id)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        writer = paired_token(client, app, user_id, scopes={"companion:tasks:complete"})
        denied = client.get(f"/companion/v1/tasks/{mine.id}/{suffix}", headers=bearer(writer))
        assert denied.status_code == 403
        assert denied.json()["reason"] == "capability_missing"
        # Another owner's Task is indistinguishable from a missing one, and never echoed.
        for task_id in (foreign.id, uuid4()):
            response = client.get(f"/companion/v1/tasks/{task_id}/{suffix}", headers=bearer(token))
            assert response.status_code == 404
            assert response.json()["code"] == "not_found"
            assert "Annans uppgift" not in response.text
        assert client.get(f"/companion/v1/tasks/{mine.id}/{suffix}").status_code == 401
        assert (
            client.get(f"/companion/v1/tasks/{mine.id}/{suffix}", headers=bearer(token)).json()[
                "items"
            ]
            == []
        )


@pytest.mark.integration
@pytest.mark.parametrize(("suffix", "ceiling"), [("contacts", 50), ("external-references", 50)])
def test_linked_record_query_bounds_are_the_mcp_bounds(suffix: str, ceiling: int) -> None:
    app = companion_app()
    user_id = owner(app)
    task = create_task(app, user_id)
    path = f"/companion/v1/tasks/{task.id}/{suffix}"
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        for query in ("limit=0", f"limit={ceiling + 1}", "cursor=" + "c" * (MAX_CURSOR_LENGTH + 1)):
            response = client.get(f"{path}?{query}", headers=bearer(token))
            assert response.status_code == 422, query
            assert response.json()["api_version"] == "companion.v1"
        assert client.get(f"{path}?limit={ceiling}", headers=bearer(token)).status_code == 200
        bad_cursor = client.get(f"{path}?cursor=nope", headers=bearer(token))
        assert bad_cursor.status_code in {400, 422}


@pytest.mark.integration
def test_agenda_query_bounds_are_the_mcp_bounds() -> None:
    app = companion_app()
    user_id = owner(app)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        for query in (
            "limit=0",
            "limit=101",
            "q=" + "x" * 201,
            "kind=board",
            "tags=a&tags=b&tags=c&tags=d&tags=e&tags=f",
            "max_minutes=0",
            "max_minutes=12001",
            "cursor=" + "c" * (MAX_CURSOR_LENGTH + 1),
        ):
            response = client.get(f"/companion/v1/work/agenda?{query}", headers=bearer(token))
            assert response.status_code == 422, query
            assert response.json()["api_version"] == "companion.v1"
        bad_cursor = client.get("/companion/v1/work/agenda?cursor=nope", headers=bearer(token))
        assert bad_cursor.status_code in {400, 422}


# 2026-11-08 12:00 UTC is 01:00 on 9 November in Auckland (NZDT, UTC+13): the owner's day and
# the UTC day differ, so a selection by UTC date would give another answer.
AUCKLAND_NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


def today_app(timezone: str = "Pacific/Auckland", now: datetime = AUCKLAND_NOW) -> FastAPI:
    settings = make_settings().model_copy(
        update={"companion_enabled": True, "owner_timezone": timezone}
    )
    app = create_app(settings, database_factory())
    app.state.container.contexts.clock = FixedClock(now)
    return app


def get_today(client: TestClient, token: str, query: str = "") -> httpx.Response:
    suffix = f"?{query}" if query else ""
    return client.get(f"/companion/v1/work/today{suffix}", headers=bearer(token))


@pytest.mark.integration
def test_today_lists_overdue_apart_from_today_and_leaves_out_everything_else() -> None:
    app = today_app()
    user_id = owner(app)
    stranger = owner(app, "stranger")
    now = AUCKLAND_NOW
    overdue_old = create_task(app, user_id, "Äldst", due_at=now - timedelta(days=3))
    overdue = create_task(app, user_id, "Försenad", due_at=now - timedelta(hours=2))
    today_late = create_task(
        app, user_id, "Senare idag", due_at=datetime(2026, 11, 9, 8, 0, tzinfo=UTC)
    )
    # Not listed: completed, not yet startable (due today but scheduled later), due on a
    # later owner day, undated, and another owner's Task.
    done = create_task(app, user_id, "Klar", due_at=now - timedelta(days=1))
    app.state.container.tasks.complete(
        owner_actor(user_id), done.id, version=done.version, idempotency_key="today-done-0001"
    )
    create_task(
        app,
        user_id,
        "Startar senare",
        due_at=datetime(2026, 11, 9, 8, 0, tzinfo=UTC),
        not_before=now + timedelta(hours=1),
    )
    create_task(app, user_id, "Imorgon", due_at=datetime(2026, 11, 9, 11, 30, tzinfo=UTC))
    create_task(app, user_id, "Utan datum")
    create_task(app, stranger, "Främmande", due_at=now - timedelta(days=1))
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        response = get_today(client, token)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        body = response.json()
        agenda = client.get(
            "/companion/v1/work/agenda?kind=task&limit=100", headers=bearer(token)
        ).json()
    assert body["api_version"] == "companion.v1"
    assert body["day"] == "2026-11-09"
    assert body["timezone"] == "Pacific/Auckland"
    assert datetime.fromisoformat(body["calculated_at"]) == now
    assert body["limit"] == 20
    assert (body["total"], body["overdue_total"], body["today_total"]) == (3, 2, 1)
    assert (body["has_more"], body["next_cursor"]) == (False, None)
    assert [(item["title"], item["group"]) for item in body["items"]] == [
        ("Senare idag", "today"),
        ("Äldst", "overdue"),
        ("Försenad", "overdue"),
    ]
    assert body["items"][1] == {
        "id": str(overdue_old.id),
        "title": "Äldst",
        "version": overdue_old.version,
        "status": "todo",
        "group": "overdue",
        "due_at": (now - timedelta(days=3)).isoformat(),
        "project_title": None,
    }
    assert {item["id"] for item in body["items"]} == {
        str(overdue_old.id),
        str(overdue.id),
        str(today_late.id),
    }
    # Today's Tasks come first, then the overdue ones (the app's Idag); inside each group the
    # same Tasks, in the same order, as the agenda's own group.
    agenda_groups = [
        [
            (item["id"], item["agenda_group"])
            for item in agenda["items"]
            if item["agenda_group"] == g
        ]
        for g in ("today", "overdue")
    ]
    assert [(item["id"], item["group"]) for item in body["items"]] == agenda_groups[
        0
    ] + agenda_groups[1]


@pytest.mark.integration
def test_today_is_the_owners_calendar_day_not_the_utc_day() -> None:
    # 2026-11-08 23:30 UTC is 00:30 on 9 November in Auckland but still 8 November in UTC.
    app = today_app(now=datetime(2026, 11, 8, 23, 30, tzinfo=UTC))
    user_id = owner(app)
    # 09:00 UTC on the 9th is 22:00 that day in Auckland: today for the owner, tomorrow in UTC.
    create_task(app, user_id, "Idag lokalt", due_at=datetime(2026, 11, 9, 9, 0, tzinfo=UTC))
    # 11:30 UTC on the 9th is 00:30 on the 10th in Auckland: tomorrow for the owner.
    create_task(app, user_id, "Imorgon lokalt", due_at=datetime(2026, 11, 9, 11, 30, tzinfo=UTC))
    # 01:00 UTC on the 8th is 14:00 on the 8th in Auckland: overdue, and also in UTC.
    create_task(app, user_id, "Igår lokalt", due_at=datetime(2026, 11, 8, 1, 0, tzinfo=UTC))
    with TestClient(app) as client:
        body = get_today(client, paired_token(client, app, user_id)).json()
    assert body["day"] == "2026-11-09"
    assert [(item["title"], item["group"]) for item in body["items"]] == [
        ("Idag lokalt", "today"),
        ("Igår lokalt", "overdue"),
    ]
    other = today_app("America/Los_Angeles", now=datetime(2026, 11, 8, 23, 30, tzinfo=UTC))
    other_owner = owner(other)
    create_task(other, other_owner, "Idag i LA", due_at=datetime(2026, 11, 9, 5, 0, tzinfo=UTC))
    with TestClient(other) as client:
        body = get_today(client, paired_token(client, other, other_owner)).json()
    # 15:30 on the 8th in Los Angeles: the same instant is another day there.
    assert (body["day"], body["timezone"]) == ("2026-11-08", "America/Los_Angeles")
    assert [(item["title"], item["group"]) for item in body["items"]] == [("Idag i LA", "today")]


@pytest.mark.integration
def test_today_pages_through_the_whole_selection_with_stable_totals() -> None:
    app = today_app()
    user_id = owner(app)
    now = AUCKLAND_NOW
    for index in range(5):
        create_task(app, user_id, f"Försenad {index}", due_at=now - timedelta(hours=10 - index))
    create_task(app, user_id, "Idag", due_at=datetime(2026, 11, 9, 8, 0, tzinfo=UTC))
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        first = get_today(client, token, "limit=4").json()
        assert first["has_more"] is True and first["next_cursor"]
        assert (first["total"], first["overdue_total"], first["today_total"]) == (6, 5, 1)
        second = get_today(client, token, f"limit=4&cursor={first['next_cursor']}").json()
        assert second["has_more"] is False and second["next_cursor"] is None
        assert (second["total"], second["overdue_total"], second["today_total"]) == (6, 5, 1)
        assert len(first["items"]) == 4 and len(second["items"]) == 2
        titles = [item["title"] for item in first["items"] + second["items"]]
        assert titles == ["Idag"] + [f"Försenad {index}" for index in range(5)]
        # A cursor of another route, a changed limit and garbage are refused.
        agenda_cursor = client.get(
            "/companion/v1/work/agenda?kind=task&limit=1", headers=bearer(token)
        ).json()["next_cursor"]
        for cursor in (agenda_cursor, "nope"):
            refused = get_today(client, token, f"limit=4&cursor={cursor}")
            assert refused.status_code in {400, 422}
            assert refused.json()["api_version"] == "companion.v1"
        assert get_today(client, token, "limit=50").json()["limit"] == 50


@pytest.mark.integration
def test_today_query_bounds_are_one_to_fifty() -> None:
    app = today_app()
    user_id = owner(app)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        for query in ("limit=0", "limit=51", "limit=x", "cursor=" + "c" * (MAX_CURSOR_LENGTH + 1)):
            response = get_today(client, token, query)
            assert response.status_code == 422, query
            assert response.json()["api_version"] == "companion.v1"
        empty = get_today(client, token, "limit=1").json()
    assert (empty["total"], empty["has_more"], empty["items"]) == (0, False, [])


@pytest.mark.integration
def test_today_names_the_project_and_carries_no_description() -> None:
    app = today_app()
    user_id = owner(app)
    container = app.state.container
    domain = container.contexts.create_domain(
        owner_actor(user_id), name="Hem", description=None, idempotency_key="today-domain-1"
    )
    project = container.projects.create(
        owner_actor(user_id),
        title="Köksrenovering",
        domain_id=domain.id,
        idempotency_key="today-project-1",
    )
    create_task(
        app,
        user_id,
        "Beställ kranar",
        project_id=project.id,
        description="hemlig beskrivning",
        due_at=AUCKLAND_NOW - timedelta(hours=1),
    )
    with TestClient(app) as client:
        response = get_today(client, paired_token(client, app, user_id))
    assert [item["project_title"] for item in response.json()["items"]] == ["Köksrenovering"]
    assert "hemlig beskrivning" not in response.text
    assert set(response.json()["items"][0]) == {
        "id",
        "title",
        "version",
        "status",
        "group",
        "due_at",
        "project_title",
    }


@pytest.mark.integration
def test_today_needs_a_valid_companion_credential_with_the_read_capability() -> None:
    app = today_app()
    user_id = owner(app)
    create_task(app, user_id, "Försenad", due_at=AUCKLAND_NOW - timedelta(hours=1))
    pat = app.state.container.auth.create_personal_token(user_id, "mcp", TOKEN_SCOPES)
    with TestClient(app) as client:
        assert client.get("/companion/v1/work/today").status_code == 401
        assert get_today(client, pat).status_code == 401
        assert get_today(client, "rsc_" + "x" * 40).status_code == 401
        writer = paired_token(client, app, user_id, scopes={"companion:tasks:complete"})
        denied = get_today(client, writer)
        assert denied.status_code == 403
        assert denied.json()["reason"] == "capability_missing"
        assert "Försenad" not in denied.text
        reader = paired_token(client, app, user_id, scopes={"companion:tasks:read"})
        assert get_today(client, reader).status_code == 200
        assert client.post("/companion/v1/work/today", headers=bearer(reader)).status_code == 405


@pytest.mark.asyncio
@pytest.mark.integration
async def test_complete_is_idempotent_versioned_and_shares_the_mcp_use_case() -> None:
    app = companion_app()
    user_id = owner(app)
    task = create_task(app, user_id, due_at=utc_now())
    stale = create_task(app, user_id, title="Gammal version", due_at=utc_now())
    actor = owner_actor(user_id)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        headers = {**bearer(token), "Idempotency-Key": "complete-key-0001"}
        first = client.post(
            f"/companion/v1/tasks/{task.id}/complete", headers=headers, json={"version": 1}
        )
        replay = client.post(
            f"/companion/v1/tasks/{task.id}/complete", headers=headers, json={"version": 1}
        )
        other_body = client.post(
            f"/companion/v1/tasks/{task.id}/complete", headers=headers, json={"version": 2}
        )
        conflict = client.post(
            f"/companion/v1/tasks/{stale.id}/complete",
            headers={**bearer(token), "Idempotency-Key": "complete-key-0002"},
            json={"version": stale.version + 1},
        )
        missing_key = client.post(
            f"/companion/v1/tasks/{task.id}/complete", headers=bearer(token), json={"version": 1}
        )
    assert first.status_code == 200
    assert first.json()["task"]["status"] == "completed"
    assert replay.json() == first.json()
    assert other_body.status_code == 409
    assert other_body.json()["reason"] == "idempotency_key_reused"
    assert conflict.status_code == 409
    assert conflict.json()["reason"] == "stale_version"
    assert TITLE not in conflict.text and "Gammal version" not in conflict.text
    assert missing_key.status_code == 422
    history = app.state.container.tasks.history(actor, task.id, limit=10)
    assert [event.to_status.value for event in history].count("completed") == 1
    mcp = create_mcp_server(app.state.container, actor_provider=lambda: actor, enable_auth=False)
    async with Client(mcp) as mcp_client:
        same = await mcp_client.call_tool(
            "complete_task",
            {"task_id": str(task.id), "version": 1, "idempotency_key": "complete-key-0001"},
        )
    # The MCP tool replays the companion call's durable result: one use case, one record.
    assert same.structured_content == first.json()


@pytest.mark.integration
@pytest.mark.parametrize("action", ["complete", "reopen"])
def test_task_post_bodies_are_capped_and_read_only_after_authentication(
    action: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sidekick.api.companion as companion

    app = companion_app()
    user_id = owner(app)
    task = create_task(app, user_id, due_at=utc_now())
    path = f"/companion/v1/tasks/{task.id}/{action}"
    json_type = {"Content-Type": "application/json"}
    oversized = b'{"version": 1, "pad": "' + b"x" * 8000 + b'"}'
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        key = {"Idempotency-Key": f"cap-key-{action}-1"}
        too_big = client.post(
            path, headers={**bearer(token), **key, **json_type}, content=oversized
        )
        assert too_big.status_code == 413
        assert too_big.json()["code"] == "payload_too_large"
        assert too_big.json()["api_version"] == "companion.v1"

        reads: list[int] = []
        original = companion._bounded_body

        async def spy(request: Any, limit: int) -> bytes:
            reads.append(limit)
            return await original(request, limit)

        monkeypatch.setattr(companion, "_bounded_body", spy)
        for headers in ({}, {"Authorization": "Bearer chcompanion_unknown"}):
            for content in (oversized, b"not json"):
                refused = client.post(
                    path, headers={**headers, **key, **json_type}, content=content
                )
                assert refused.status_code == 401
                assert refused.json()["code"] == "unauthorized"
        assert reads == []

        ok_body = client.post(
            path, headers={**bearer(token), **key, **json_type}, content=b'{"version": 1}'
        )
        assert ok_body.status_code in {200, 409}
        assert reads == [companion.MAX_TASK_BODY_BYTES]


@pytest.mark.integration
def test_write_only_device_gets_a_receipt_and_a_reader_gets_the_task() -> None:
    app = companion_app()
    user_id = owner(app)
    secret = "privat-beskrivning-hemlig"
    first = create_task(app, user_id, description=secret, due_at=utc_now())
    second = create_task(app, user_id, title="Andra", description=secret, due_at=utc_now())
    with TestClient(app) as client:
        writer = paired_token(client, app, user_id, scopes={"companion:tasks:complete"})
        full = paired_token(client, app, user_id)
        receipt = client.post(
            f"/companion/v1/tasks/{first.id}/complete",
            headers={**bearer(writer), "Idempotency-Key": "receipt-complete-1"},
            json={"version": first.version},
        )
        replay = client.post(
            f"/companion/v1/tasks/{first.id}/complete",
            headers={**bearer(writer), "Idempotency-Key": "receipt-complete-1"},
            json={"version": first.version},
        )
        reopen = client.post(
            f"/companion/v1/tasks/{first.id}/reopen",
            headers={**bearer(writer), "Idempotency-Key": "receipt-reopen-01"},
            json={"version": receipt.json()["version"]},
        )
        # The task is already open again; a stale/wrong version must not return data either.
        wrong = client.post(
            f"/companion/v1/tasks/{first.id}/complete",
            headers={**bearer(writer), "Idempotency-Key": "receipt-complete-2"},
            json={"version": 99},
        )
        wrong_reopen = client.post(
            f"/companion/v1/tasks/{first.id}/reopen",
            headers={**bearer(writer), "Idempotency-Key": "receipt-reopen-02"},
            json={"version": 99},
        )
        whole = client.post(
            f"/companion/v1/tasks/{second.id}/complete",
            headers={**bearer(full), "Idempotency-Key": "receipt-complete-3"},
            json={"version": second.version},
        )
    assert receipt.status_code == 200
    assert receipt.json() == {
        "ok": True,
        "id": str(first.id),
        "version": first.version + 1,
        "status": "completed",
    }
    assert replay.json() == receipt.json()
    assert reopen.status_code == 200
    assert reopen.json() == {
        "ok": True,
        "id": str(first.id),
        "version": first.version + 2,
        "status": "todo",
    }
    for response in (receipt, replay, reopen, wrong, wrong_reopen):
        assert TITLE not in response.text and secret not in response.text
    for response in (wrong, wrong_reopen):
        assert response.status_code == 409
        assert "task" not in response.json() and "description" not in response.json()
    for receipt_like in (receipt, replay, reopen):
        assert set(receipt_like.json()) == {"ok", "id", "version", "status"}
    assert whole.status_code == 200
    assert whole.json()["task"]["title"] == "Andra"
    assert whole.json()["task"]["description"] == secret
    assert whole.json()["task"]["status"] == "completed"


@pytest.mark.integration
def test_completing_a_recurring_task_advances_it_like_mcp() -> None:
    app = companion_app()
    user_id = owner(app)
    due = datetime(2026, 8, 21, 10, tzinfo=UTC)
    task = create_task(
        app, user_id, due_at=due, recurrence={"frequency": "weekly", "weekdays": [4]}
    )
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        response = client.post(
            f"/companion/v1/tasks/{task.id}/complete",
            headers={**bearer(token), "Idempotency-Key": "recurring-0001"},
            json={"version": task.version},
        )
    body = response.json()["task"]
    assert response.status_code == 200
    assert body["id"] == str(task.id)
    assert body["status"] == "todo"
    assert body["last_completed_at"] is not None
    assert datetime.fromisoformat(body["due_at"]) > due


@pytest.mark.asyncio
@pytest.mark.integration
async def test_reopen_undoes_only_a_completion_like_update_task() -> None:
    app = companion_app()
    user_id = owner(app)
    task = create_task(app, user_id, due_at=utc_now())
    open_task = create_task(app, user_id, title="Fortfarande öppen", due_at=utc_now())
    actor = owner_actor(user_id)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        reader = paired_token(client, app, user_id, scopes={"companion:tasks:read"})
        done = client.post(
            f"/companion/v1/tasks/{task.id}/complete",
            headers={**bearer(token), "Idempotency-Key": "undo-complete-1"},
            json={"version": task.version},
        ).json()["task"]
        headers = {**bearer(token), "Idempotency-Key": "undo-reopen-001"}
        reopened = client.post(
            f"/companion/v1/tasks/{task.id}/reopen",
            headers=headers,
            json={"version": done["version"]},
        )
        replay = client.post(
            f"/companion/v1/tasks/{task.id}/reopen",
            headers=headers,
            json={"version": done["version"]},
        )
        not_completed = client.post(
            f"/companion/v1/tasks/{open_task.id}/reopen",
            headers={**bearer(token), "Idempotency-Key": "undo-reopen-002"},
            json={"version": open_task.version},
        )
        denied = client.post(
            f"/companion/v1/tasks/{task.id}/reopen",
            headers={**bearer(reader), "Idempotency-Key": "undo-reopen-003"},
            json={"version": done["version"]},
        )
    assert reopened.status_code == 200
    assert reopened.json()["task"]["status"] == "todo"
    assert replay.json() == reopened.json()
    assert not_completed.status_code == 409
    assert not_completed.json()["reason"] == "not_completed"
    assert denied.status_code == 403
    mcp = create_mcp_server(app.state.container, actor_provider=lambda: actor, enable_auth=False)
    async with Client(mcp) as mcp_client:
        same = await mcp_client.call_tool(
            "update_task",
            {
                "task_id": str(task.id),
                "version": done["version"],
                "idempotency_key": "undo-reopen-001",
                "changes": {"status": "todo"},
            },
        )
    # The same `update_task` use case and idempotency record as the MCP undo.
    assert same.structured_content == reopened.json()


@pytest.mark.integration
def test_reopen_cannot_reopen_a_task_the_owner_edits_to_the_requested_version() -> None:
    """The status guard holds on the row locked in the write's transaction.

    The device guesses version N+1 while the Task is open at N; the owner's edit to N+1 is
    pending (row locked) when the reopen starts, and commits while it waits. The reopen must
    then see an open Task and answer 409 `not_completed`, never reopen anything.
    """

    app = companion_app()
    user_id = owner(app)
    task = create_task(app, user_id, due_at=utc_now())
    answers: list[httpx.Response] = []
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)

        def reopen() -> None:
            answers.append(
                client.post(
                    f"/companion/v1/tasks/{task.id}/reopen",
                    headers={**bearer(token), "Idempotency-Key": "race-reopen-001"},
                    json={"version": task.version + 1},
                )
            )

        with app.state.container.session_factory() as session:
            row = session.scalar(select(TaskRow).where(TaskRow.id == task.id).with_for_update())
            assert row is not None
            row.version = task.version + 1
            row.updated_at = utc_now()
            session.flush()
            thread = threading.Thread(target=reopen)
            thread.start()
            thread.join(timeout=1.0)
            assert thread.is_alive(), "the reopen must wait for the owner's pending edit"
            session.commit()
        thread.join(timeout=30)
        assert not thread.is_alive()
        after = client.get(f"/companion/v1/tasks/{task.id}", headers=bearer(token)).json()
    assert answers[0].status_code == 409
    assert answers[0].json()["reason"] == "not_completed"
    assert after["task"]["status"] == "todo"
    assert after["task"]["version"] == task.version + 1


@pytest.mark.integration
def test_no_log_record_carries_a_title_token_or_pairing_secret(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = companion_app()
    user_id = owner(app)
    task = create_task(app, user_id, due_at=utc_now())
    ticket = devices(app).create_pairing(user_id, "Samsung")
    caplog.set_level(logging.DEBUG)
    # Sidekick's loggers may not propagate to the root logger; listen on them directly.
    watched = [logging.getLogger(name) for name in ("sidekick", "uvicorn", "fastapi", "fastmcp")]
    for logger in watched:
        logger.addHandler(caplog.handler)
    try:
        token = _exercise_companion_routes(app, ticket.secret, task)
    finally:
        for logger in watched:
            logger.removeHandler(caplog.handler)
    _check_records(caplog, token, ticket.secret, task)


def _exercise_companion_routes(app: FastAPI, secret: str, task: Any) -> str:
    with TestClient(app) as client:
        paired = client.post("/companion/v1/pair", json={"pairing_secret": secret}).json()
        token = paired["access_token"]
        client.post("/companion/v1/pair", json={"pairing_secret": secret})
        client.get("/companion/v1/work/agenda?q=tandl", headers=bearer(token))
        client.get("/companion/v1/work/today", headers=bearer(token))
        client.get("/companion/v1/work/today?cursor=nope", headers=bearer(token))
        client.get(f"/companion/v1/tasks/{task.id}", headers=bearer(token))
        client.post(
            f"/companion/v1/tasks/{task.id}/complete",
            headers={**bearer(token), "Idempotency-Key": "log-check-0001"},
            json={"version": task.version + 5},
        )
        client.post(
            f"/companion/v1/tasks/{task.id}/complete",
            headers={**bearer(token), "Idempotency-Key": "log-check-0002"},
            json={"version": task.version},
        )
        client.get("/companion/v1/work/agenda", headers=bearer(token + "x"))
    return str(token)


def _check_records(caplog: pytest.LogCaptureFixture, token: str, secret: str, task: Any) -> None:
    records = [record for record in caplog.records if record.name.startswith("sidekick")]
    assert any(record.getMessage() == "companion_request" for record in records)
    # The test client's own request log (httpx) is the caller's, not the server's.
    server_records = [
        record for record in caplog.records if not record.name.startswith(("httpx", "httpcore"))
    ]
    for record in server_records:
        rendered = f"{record.getMessage()} {record.__dict__}"
        for forbidden in (TITLE, "tandl", token, secret, "Samsung", str(task.id)):
            assert forbidden not in rendered, (record.name, record.getMessage())
