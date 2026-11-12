"""Durable push delivery (ADR-005; D-078): wakes are queued in the transaction of the
Task or Step change, one pending wake per subscription, never for the device that made the change;
a worker sends them after the commit and never logs an endpoint."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text, update
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session, sessionmaker

from sidekick.api.app import create_app
from sidekick.companion import push_delivery, push_sender, push_worker
from sidekick.companion.push_delivery import PushDeliveryService
from sidekick.companion.push_delivery_store import SqlPushDeliveryStore
from sidekick.companion.push_outbox_store import (
    acting_device,
    enqueue_reminder_push,
    enqueue_wake,
    install_wake_hook,
)
from sidekick.companion.push_sender import HttpPushSender, create_client
from sidekick.lifecycle.domain import RecordKind
from sidekick.shared.observability import HTTP_CLIENT_LOGGERS
from sidekick.shared.persistence.models import (
    AuditEventRow,
    CompanionPairingRow,
    PersonalAccessTokenRow,
    PushOutboxRow,
    PushSubscriptionRow,
    UserRow,
)
from sidekick.shared.types import new_uuid7, utc_now
from sidekick.store import SqlAlchemyStore
from sidekick.tasks.application import UpdateTaskCommand
from sidekick.tasks.domain import Priority, Task, TaskStatus
from tests.db import database_factory
from tests.support.companion import (
    bearer,
    create_task,
    owner,
    owner_actor,
)
from tests.support.companion_push import (
    ENDPOINT,
    OTHER_ENDPOINT,
    SECRET_TOPIC,
    URL,
    Clock,
    factory_of,
    outbox,
    queue_wake,
    subscribed,
    subscription_of,
)
from tests.support.settings import make_settings

HOSTS = frozenset({"ntfy.sh"})

Handler = Callable[[httpx.Request], httpx.Response]


def push_app(*, enabled: bool = True) -> FastAPI:
    settings = make_settings().model_copy(
        update={"companion_enabled": True, "push_enabled": enabled}
    )
    return create_app(settings, database_factory())


def owned_by(app: FastAPI, rows: list[PushOutboxRow]) -> set[UUID | None]:
    """The device behind each queued row."""

    with factory_of(app)() as session:
        return {
            session.scalars(
                select(CompanionPairingRow.device_token_id)
                .join(PushSubscriptionRow, PushSubscriptionRow.pairing_id == CompanionPairingRow.id)
                .where(PushSubscriptionRow.id == row.subscription_id)
            ).one()
            for row in rows
        }


def new_task(user_id: UUID) -> Task:
    now = utc_now()
    return Task(
        id=new_uuid7(),
        owner_id=user_id,
        project_id=None,
        title="Hemlig titel",
        description=None,
        status=TaskStatus.TODO,
        priority=Priority.NORMAL,
        due_at=None,
        completed_at=None,
        created_at=now,
        updated_at=now,
    )


# --- enqueue -------------------------------------------------------------------------------


@pytest.mark.integration
def test_a_task_change_queues_one_wake_for_each_active_subscription() -> None:
    app = push_app()
    user_id = owner(app)
    with TestClient(app) as client:
        _, first = subscribed(client, app, user_id)
        _, second = subscribed(client, app, user_id, OTHER_ENDPOINT)
        assert outbox(app) == []
        task = create_task(app, user_id)
        rows = outbox(app)
        assert [(row.kind, row.dedup_key, row.attempts) for row in rows] == [("w", "w", 0)] * 2
        assert all(row.delivered_at is None and row.next_attempt_at for row in rows)
        assert owned_by(app, rows) == {first, second}
        # A burst of changes is still one pending wake per subscription.
        app.state.container.tasks.complete(
            owner_actor(user_id), task.id, version=task.version, idempotency_key="done-key-1"
        )
        assert len(outbox(app)) == 2


@pytest.mark.integration
def test_every_task_and_step_transition_queues_a_wake() -> None:
    app = push_app()
    user_id = owner(app)
    actor = owner_actor(user_id)
    container = app.state.container
    with TestClient(app) as client:
        subscribed(client, app, user_id)

        def after(change: Callable[[], object], key: str) -> None:
            with factory_of(app).begin() as session:
                session.execute(update(PushOutboxRow).values(delivered_at=utc_now()))
            change()
            pending = [row for row in outbox(app) if row.delivered_at is None]
            assert len(pending) == 1, key

        task = create_task(app, user_id)
        step = container.steps.create_step(actor, task.id, title="Steg", idempotency_key="step-1x")
        after(
            lambda: container.steps.complete_step(
                actor, step.id, version=step.version, idempotency_key="step-done-1"
            ),
            "step complete",
        )
        after(
            lambda: container.tasks.complete(
                actor, task.id, version=task.version, idempotency_key="task-done-1"
            ),
            "task complete",
        )
        done = container.tasks.get(actor, task.id)
        after(
            lambda: container.tasks.update(
                actor,
                task.id,
                version=done.version,
                idempotency_key="reopen-1x",
                command=UpdateTaskCommand(status=TaskStatus.TODO),
            ),
            "reopen",
        )
        reopened = container.tasks.get(actor, task.id)
        after(
            lambda: container.lifecycle.trash(
                actor,
                RecordKind.TASK,
                task.id,
                version=reopened.version,
                idempotency_key="trash-1xx",
            ),
            "trash",
        )
        trashed = container.lifecycle.list_trash(actor, kind=RecordKind.TASK, limit=10).items[0]
        after(
            lambda: container.lifecycle.restore(
                actor,
                RecordKind.TASK,
                task.id,
                version=trashed.version,
                idempotency_key="restore-1x",
            ),
            "restore",
        )


@pytest.mark.integration
def test_a_rolled_back_change_leaves_no_outbox_row() -> None:
    app = push_app()
    user_id = owner(app)
    with TestClient(app) as client:
        subscribed(client, app, user_id)
        task = new_task(user_id)

        def failing(session: Session) -> None:
            SqlAlchemyStore.save_task(session, task)
            session.flush()
            # The wake was written with the task, inside the same open transaction.
            assert session.scalars(select(PushOutboxRow.id)).all()
            raise RuntimeError("domain change failed")

        with pytest.raises(RuntimeError):
            app.state.container.tasks.store.transaction(failing)
        assert outbox(app) == []
        committed = new_task(user_id)

        def save_committed(session: Session) -> None:
            SqlAlchemyStore.save_task(session, committed)

        app.state.container.tasks.store.transaction(save_committed)
        assert len(outbox(app)) == 1


@pytest.mark.integration
def test_the_device_that_made_the_change_gets_no_wake_but_the_others_do() -> None:
    app = push_app()
    user_id = owner(app)
    with TestClient(app) as client:
        own_token, own = subscribed(client, app, user_id)
        _, other = subscribed(client, app, user_id, OTHER_ENDPOINT)
        task = create_task(app, user_id)
        with factory_of(app).begin() as session:
            session.execute(update(PushOutboxRow).values(delivered_at=utc_now()))

        done = client.post(
            f"/companion/v1/tasks/{task.id}/complete",
            headers={**bearer(own_token), "Idempotency-Key": "own-complete-1"},
            json={"version": task.version},
        )
        assert done.status_code == 200, done.text
        pending = [row for row in outbox(app) if row.delivered_at is None]
        assert owned_by(app, pending) == {other}

        with factory_of(app).begin() as session:
            session.execute(update(PushOutboxRow).values(delivered_at=utc_now()))
        reopened = client.post(
            f"/companion/v1/tasks/{task.id}/reopen",
            headers={**bearer(own_token), "Idempotency-Key": "own-reopen-1"},
            json={"version": done.json()["task"]["version"]},
        )
        assert reopened.status_code == 200, reopened.text
        pending = [row for row in outbox(app) if row.delivered_at is None]
        assert owned_by(app, pending) == {other}
        assert own not in owned_by(app, pending)


@pytest.mark.integration
def test_a_revoked_subscription_and_another_owner_get_no_wake() -> None:
    app = push_app()
    user_id = owner(app)
    stranger = owner(app, "stranger")
    with TestClient(app) as client:
        token, _ = subscribed(client, app, user_id)
        assert client.delete(URL, headers=bearer(token)).status_code == 204
        create_task(app, user_id)
        assert outbox(app) == []
        stranger_token, _ = subscribed(client, app, stranger, OTHER_ENDPOINT)
        assert stranger_token
        create_task(app, user_id)
        assert outbox(app) == []


@pytest.mark.integration
def test_with_push_disabled_nothing_is_queued() -> None:
    app = push_app(enabled=False)
    user_id = owner(app)
    with TestClient(app) as client:
        subscribed(client, app, user_id)
        task = create_task(app, user_id)
        app.state.container.tasks.complete(
            owner_actor(user_id), task.id, version=task.version, idempotency_key="done-off-1"
        )
        assert outbox(app) == []
    assert make_settings().push_enabled is False


@pytest.mark.integration
def test_the_hook_can_be_removed_and_acting_device_scopes_the_exclusion() -> None:
    app = push_app(enabled=False)
    user_id = owner(app)
    with TestClient(app) as client:
        _, device = subscribed(client, app, user_id)
        remove = install_wake_hook(factory_of(app))
        create_task(app, user_id)
        assert len(outbox(app)) == 1
        remove()
        create_task(app, user_id, title="Två")
        assert len(outbox(app)) == 1
        with factory_of(app).begin() as session, acting_device(device):
            assert enqueue_wake(session, user_id, exclude_device_id=device) == 0


# --- database ------------------------------------------------------------------------------


@pytest.mark.integration
def test_the_database_keeps_one_pending_wake_and_one_reminder_per_key() -> None:
    app = push_app()
    user_id = owner(app)
    with TestClient(app) as client:
        _, device = subscribed(client, app, user_id)
        subscription_id = subscription_of(app, device).id
        now = utc_now()

        def row(kind: str, key: str, **fields: object) -> PushOutboxRow:
            return PushOutboxRow(
                id=new_uuid7(),
                subscription_id=subscription_id,
                kind=kind,
                dedup_key=key,
                created_at=now,
                next_attempt_at=now,
                attempts=0,
                **fields,
            )

        def insert(*rows: PushOutboxRow) -> None:
            with factory_of(app).begin() as session:
                session.add_all(rows)

        insert(row("w", "w"))
        with pytest.raises(IntegrityError):
            insert(row("w", "w"))
        # A delivered or abandoned wake does not block the next one.
        with factory_of(app).begin() as session:
            session.execute(update(PushOutboxRow).values(delivered_at=now))
        insert(row("w", "w"))
        insert(row("r", "morning-2026-11-08"))
        with pytest.raises(IntegrityError):
            insert(row("r", "morning-2026-11-08", delivered_at=now))
        insert(row("r", "due-1"), row("r", "due-2"))
        with pytest.raises(IntegrityError):
            insert(row("x", "x"))


@pytest.mark.integration
def test_the_enqueue_upserts_keep_deduping_once_psycopg_prepares_statements() -> None:
    """The ON CONFLICT targets must carry no bound parameter: once psycopg prepares a statement
    server-side, Postgres no longer matches the partial index and the insert (and with it the
    caller's domain write, from the before_flush hook) fails."""

    app = push_app()
    user_id = owner(app)
    with TestClient(app) as client:
        _, device = subscribed(client, app, user_id)
        subscription_id = subscription_of(app, device).id
        url = factory_of(app).kw["bind"].url.render_as_string(hide_password=False)
    engine = create_engine(url, connect_args={"prepare_threshold": 0}, hide_parameters=True)
    try:
        with sessionmaker(engine, expire_on_commit=False).begin() as session:
            for _ in range(10):
                assert enqueue_wake(session, user_id) == 1
                reminder = new_uuid7()
                assert enqueue_reminder_push(session, user_id, reminder) == 1
                assert enqueue_reminder_push(session, user_id, reminder) == 0
            rows = list(session.scalars(select(PushOutboxRow)))
    finally:
        engine.dispose()
    assert [row.kind for row in rows].count("w") == 1
    assert [row.kind for row in rows].count("r") == 10
    assert {row.subscription_id for row in rows} == {subscription_id}


# --- coalescing ----------------------------------------------------------------------------

MIN_INTERVAL = timedelta(seconds=60)


def delivered_at_start(clock: Clock) -> tuple[FastAPI, UUID, TestClient]:
    """A subscription whose wake was delivered at `clock.now` (its `last_success_at`)."""

    app, user_id, _, client = seeded(clock)
    assert worker(app, _ok, clock).run_once() == 1
    return app, user_id, client


def pending(app: FastAPI) -> list[PushOutboxRow]:
    return [row for row in outbox(app) if row.delivered_at is None]


@pytest.mark.integration
def test_a_burst_inside_the_interval_is_one_row_due_at_the_last_success_plus_the_interval() -> None:
    clock = Clock()
    app, user_id, client = delivered_at_start(clock)
    sent_at = clock.now
    with client:
        clock.advance(seconds=10)
        queue_wake(app, user_id, clock.now, MIN_INTERVAL)
        clock.advance(seconds=10)
        queue_wake(app, user_id, clock.now, MIN_INTERVAL)
        queue_wake(app, user_id, clock.now, MIN_INTERVAL)
        (row,) = pending(app)
        assert len(outbox(app)) == 2
        assert row.next_attempt_at == sent_at + MIN_INTERVAL and row.attempts == 0
        service = worker(app, _ok, clock)
        assert service.run_once() == 0
        clock.advance(seconds=40)
        assert service.run_once() == 1
        assert pending(app) == []


@pytest.mark.integration
def test_a_wake_after_the_interval_or_without_a_prior_push_is_due_now() -> None:
    clock = Clock()
    app, user_id, client = delivered_at_start(clock)
    with client:
        clock.advance(seconds=61)
        queue_wake(app, user_id, clock.now, MIN_INTERVAL)
        (row,) = pending(app)
        assert row.next_attempt_at == clock.now
    clock = Clock()
    app, user_id, _, client = seeded(clock)
    with client:
        queue_wake(app, user_id, clock.now, MIN_INTERVAL)
        (row,) = pending(app)
        assert row.next_attempt_at == clock.now


@pytest.mark.integration
def test_a_reminder_push_is_not_held_back_by_the_wake_interval() -> None:
    clock = Clock()
    app, user_id, client = delivered_at_start(clock)
    with client:
        clock.advance(seconds=5)
        queue_wake(app, user_id, clock.now, MIN_INTERVAL)
        with factory_of(app).begin() as session:
            assert enqueue_reminder_push(session, user_id, new_uuid7(), now=clock.now) == 1
        reminders = [row for row in pending(app) if row.kind == "r"]
        assert [row.next_attempt_at for row in reminders] == [clock.now]
        assert worker(app, _ok, clock).run_once() == 1
        assert [row.kind for row in pending(app)] == ["w"]


@pytest.mark.integration
def test_the_configured_interval_reaches_the_task_change_hook() -> None:
    settings = make_settings().model_copy(
        update={
            "companion_enabled": True,
            "push_enabled": True,
            "push_wake_min_interval_seconds": 60,
        }
    )
    app = create_app(settings, database_factory())
    user_id = owner(app)
    with TestClient(app) as client:
        _, device = subscribed(client, app, user_id)
        last = utc_now()
        with factory_of(app).begin() as session:
            session.execute(
                update(PushSubscriptionRow)
                .where(PushSubscriptionRow.id == subscription_of(app, device).id)
                .values(last_success_at=last)
            )
            session.execute(update(PushOutboxRow).values(delivered_at=last))
        create_task(app, user_id)
        create_task(app, user_id, title="Två")
        (row,) = pending(app)
        assert row.next_attempt_at == last + MIN_INTERVAL


# --- worker --------------------------------------------------------------------------------


def _ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200)


def _not_found(request: httpx.Request) -> httpx.Response:
    return httpx.Response(404)


def _server_error(request: httpx.Request) -> httpx.Response:
    return httpx.Response(500)


def _service_unavailable(request: httpx.Request) -> httpx.Response:
    return httpx.Response(503)


def _rate_limited(request: httpx.Request) -> httpx.Response:
    return httpx.Response(429)


def _retry_after(status: int, value: str) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers={"Retry-After": value})

    return handler


def _timeout(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectTimeout("slow")


def _unreachable(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("down")


def _boom(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError(f"boom {request.url}")


def worker(
    app: FastAPI,
    handler: Callable[[httpx.Request], httpx.Response],
    clock: Clock,
    hosts: frozenset[str] = HOSTS,
) -> PushDeliveryService:
    sender = HttpPushSender(create_client(httpx.MockTransport(handler)))
    return PushDeliveryService(
        SqlPushDeliveryStore(factory_of(app)), sender, hosts, clock=clock, jitter=lambda: 1.0
    )


def seeded(clock: Clock) -> tuple[FastAPI, UUID, UUID, TestClient]:
    app = push_app()
    user_id = owner(app)
    client = TestClient(app)
    client.__enter__()
    _, device = subscribed(client, app, user_id)
    queue_wake(app, user_id, clock.now)
    return app, user_id, device, client


@pytest.mark.integration
def test_a_2xx_marks_the_wake_delivered_with_the_fixed_body_and_no_redirects() -> None:
    clock = Clock()
    app, _, device, client = seeded(clock)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "x"})

    with client:
        assert worker(app, handler, clock).run_once() == 1
        assert len(seen) == 1
        assert seen[0].method == "POST" and str(seen[0].url) == ENDPOINT
        assert seen[0].content == b'{"k":"w"}'
        assert seen[0].headers["content-type"] == "application/json"
        (row,) = outbox(app)
        assert row.delivered_at == clock.now and row.attempts == 1
        assert row.last_error_kind is None
        subscription = subscription_of(app, device)
        assert subscription.last_success_at == clock.now and subscription.failure_count == 0
        assert worker(app, handler, clock).run_once() == 0
        assert len(seen) == 1


@pytest.mark.integration
def test_a_reminder_row_is_sent_with_the_r_body() -> None:
    clock = Clock()
    app, _, device, client = seeded(clock)
    with client:
        with factory_of(app).begin() as session:
            session.execute(update(PushOutboxRow).values(delivered_at=clock.now))
            session.add(
                PushOutboxRow(
                    id=new_uuid7(),
                    subscription_id=subscription_of(app, device).id,
                    kind="r",
                    dedup_key="morning-2026-11-08",
                    created_at=clock.now,
                    next_attempt_at=clock.now,
                    attempts=0,
                )
            )
        bodies: list[bytes] = []

        def handler(request: httpx.Request) -> httpx.Response:
            bodies.append(request.content)
            return httpx.Response(200)

        worker(app, handler, clock).run_once()
        assert bodies == [b'{"k":"r"}']


@pytest.mark.integration
def test_a_redirect_is_not_followed_and_closes_the_row_without_retrying() -> None:
    clock = Clock()
    app, _, device, client = seeded(clock)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://evil.example/steal"})

    with client:
        worker(app, handler, clock).run_once()
        assert calls == [ENDPOINT]
        (row,) = outbox(app)
        assert row.delivered_at is None and row.next_attempt_at is None
        assert row.last_error_kind == "rejected"
        assert subscription_of(app, device).revoked_at is None


@pytest.mark.integration
@pytest.mark.parametrize("status", [404, 410])
def test_404_and_410_revoke_the_subscription_and_close_its_rows(status: int) -> None:
    clock = Clock()
    app, user_id, device, client = seeded(clock)
    with client:
        worker(app, lambda request: httpx.Response(status), clock).run_once()
        assert subscription_of(app, device).revoked_at == clock.now
        (row,) = outbox(app)
        assert row.delivered_at is None and row.next_attempt_at is None
        assert row.last_error_kind == "gone"
        with factory_of(app)() as session:
            audit = session.scalars(
                select(AuditEventRow).where(AuditEventRow.event == "companion.push_revoked")
            ).one()
            assert (audit.reason, audit.target_id, audit.actor_id) == ("gone", device, user_id)
        # No wake is queued for the revoked subscription any more.
        create_task(app, user_id)
        assert len(outbox(app)) == 1


@pytest.mark.integration
@pytest.mark.parametrize(
    "outcome",
    [_server_error, _rate_limited, _timeout, _unreachable],
)
def test_retryable_failures_back_off_with_jitter_and_stop_at_the_attempt_cap(
    outcome: Handler,
) -> None:
    clock = Clock()
    app, _, device, client = seeded(clock)
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return outcome(request)

    with client:
        service = worker(app, handler, clock)
        assert service.run_once() == 1
        (row,) = outbox(app)
        assert row.attempts == 1 and row.delivered_at is None
        assert row.next_attempt_at == clock.now + push_delivery.BACKOFF_BASE
        assert row.last_error_kind in {"server_error", "rate_limited", "timeout", "network"}
        assert subscription_of(app, device).failure_count == 1

        # Not due yet: nothing is sent.
        assert service.run_once() == 0 and attempts == 1
        for expected in range(2, push_delivery.MAX_ATTEMPTS + 1):
            clock.advance(hours=1)
            assert service.run_once() == 1
            assert outbox(app)[0].attempts == expected
        assert attempts == push_delivery.MAX_ATTEMPTS
        (row,) = outbox(app)
        assert row.next_attempt_at is None and row.delivered_at is None
        assert row.last_error_kind is not None
        clock.advance(days=1)
        assert service.run_once() == 0
        # The subscription stays; a later change starts a fresh wake.
        assert subscription_of(app, device).revoked_at is None
        queue_wake(app, subscription_of(app, device).user_id, clock.now)
        assert len(outbox(app)) == 2


@pytest.mark.integration
def test_a_server_that_drips_its_headers_is_cut_off_at_the_total_deadline() -> None:
    """The httpx timeout is per socket operation; a slow server must not hold the delivery."""

    clock = Clock()
    app, _, device, client = seeded(clock)
    release = threading.Event()

    def slow(request: httpx.Request) -> httpx.Response:
        release.wait(30)
        return httpx.Response(200)

    with client:
        service = PushDeliveryService(
            SqlPushDeliveryStore(factory_of(app)),
            HttpPushSender(create_client(httpx.MockTransport(slow)), deadline_seconds=0.3),
            HOSTS,
            clock=clock,
            jitter=lambda: 1.0,
        )
        started = time.monotonic()
        try:
            assert service.run_once() == 1
            assert time.monotonic() - started < 5
            (row,) = outbox(app)
            assert row.delivered_at is None and row.attempts == 1
            assert row.last_error_kind == "timeout"
            assert subscription_of(app, device).failure_count == 1
        finally:
            release.set()


@pytest.mark.integration
def test_abandoned_sends_hold_their_slots_so_a_slow_host_cannot_pile_up_threads() -> None:
    clock = Clock()
    _, _, _, client = seeded(clock)
    release = threading.Event()
    started: list[int] = []

    def slow(request: httpx.Request) -> httpx.Response:
        started.append(1)
        release.wait(30)
        return httpx.Response(200)

    with client:
        sender = HttpPushSender(create_client(httpx.MockTransport(slow)), deadline_seconds=0.05)
        try:
            for _ in range(push_sender.MAX_PENDING_SENDS):
                with pytest.raises(push_delivery.SendFailed) as failed:
                    sender.send(ENDPOINT, b"{}", {})
                assert failed.value.kind == "timeout"
            with pytest.raises(push_delivery.SendsBusy):
                sender.send(ENDPOINT, b"{}", {})
            assert len(started) == push_sender.MAX_PENDING_SENDS
        finally:
            release.set()


@pytest.mark.integration
def test_a_row_that_finds_no_send_slot_is_deferred_without_counting_an_attempt() -> None:
    clock = Clock()
    app, _, device, client = seeded(clock)
    release = threading.Event()

    def slow(request: httpx.Request) -> httpx.Response:
        release.wait(30)
        return httpx.Response(200)

    with client:
        sender = HttpPushSender(create_client(httpx.MockTransport(slow)), deadline_seconds=0.05)
        service = PushDeliveryService(
            SqlPushDeliveryStore(factory_of(app)), sender, HOSTS, clock=clock, jitter=lambda: 1.0
        )
        try:
            for _ in range(push_sender.MAX_PENDING_SENDS):
                with pytest.raises(push_delivery.SendFailed):
                    sender.send(ENDPOINT, b"{}", {})
            assert service.run_once() == 1
            (row,) = outbox(app)
            assert row.attempts == 0 and row.delivered_at is None
            assert row.last_error_kind is None
            assert row.next_attempt_at == clock.now + push_delivery.BUSY_DEFER
            assert subscription_of(app, device).failure_count == 0
            assert subscription_of(app, device).revoked_at is None
        finally:
            release.set()


@pytest.mark.integration
def test_a_410_for_an_endpoint_the_device_has_since_replaced_revokes_nothing() -> None:
    clock = Clock()
    app, _, device, client = seeded(clock)

    def handler(request: httpx.Request) -> httpx.Response:
        # The device registers a new endpoint on the same row while the old one is being sent to.
        with factory_of(app).begin() as session:
            session.execute(update(PushSubscriptionRow).values(endpoint=OTHER_ENDPOINT))
        return httpx.Response(410)

    with client:
        worker(app, handler, clock).run_once()
        assert subscription_of(app, device).revoked_at is None
        (row,) = outbox(app)
        assert row.next_attempt_at is not None and row.last_error_kind is None
        with factory_of(app)() as session:
            audits = session.scalars(
                select(AuditEventRow).where(AuditEventRow.event == "companion.push_revoked")
            ).all()
            assert audits == []
        # The row is tried again, against the new endpoint.
        clock.advance(seconds=61)
        seen: list[str] = []

        def deliver(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(200)

        assert worker(app, deliver, clock).run_once() == 1
        assert seen == [OTHER_ENDPOINT]
        assert outbox(app)[0].delivered_at is not None


@pytest.mark.integration
def test_a_change_makes_a_failing_wake_start_again_with_fresh_attempts() -> None:
    clock = Clock()
    app, user_id, _, client = seeded(clock)
    with client:
        service = worker(app, lambda request: httpx.Response(503), clock)
        service.run_once()
        clock.advance(hours=1)
        service.run_once()
        assert outbox(app)[0].attempts == 2
        queue_wake(app, user_id, clock.now)
        (row,) = outbox(app)
        assert row.attempts == 0 and row.next_attempt_at == clock.now


@pytest.mark.integration
def test_a_row_that_keeps_raising_before_a_retry_is_counted_out_and_given_up() -> None:
    clock = Clock()
    app, _, device, client = seeded(clock)
    sent = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal sent
        sent += 1
        raise RuntimeError("not an httpx error: `_retry` is never reached")

    with client:
        service = worker(app, handler, clock)
        for expected in range(1, push_delivery.MAX_ATTEMPTS + 1):
            assert service.run_once() == 1
            assert outbox(app)[0].attempts == expected
            clock.advance(seconds=61)  # The lease expires.
        assert sent == push_delivery.MAX_ATTEMPTS
        # The next claim finds it used up: it is closed without a send.
        assert service.run_once() == 0
        (row,) = outbox(app)
        assert row.next_attempt_at is None and row.delivered_at is None
        assert row.last_error_kind == "gave_up"
        assert sent == push_delivery.MAX_ATTEMPTS
        assert subscription_of(app, device).revoked_at is None


@pytest.mark.integration
def test_a_failed_state_survives_empty_polls_until_a_delivery_succeeds() -> None:
    clock = Clock()
    app, _, _, client = seeded(clock)
    broken = True

    def handler(request: httpx.Request) -> httpx.Response:
        if broken:
            raise RuntimeError("not an httpx error: `_retry` is never reached")
        return httpx.Response(200)

    with client:
        service = worker(app, handler, clock)
        assert service.run_once() == 1 and service.last_run_failed is True
        # The row is leased: the next polls find nothing due, which is not a recovery.
        clock.advance(seconds=10)
        assert service.run_once() == 0 and service.last_run_failed is True
        clock.advance(seconds=20)
        assert service.run_once() == 0 and service.last_run_failed is True
        # Its lease runs out and the delivery fails again.
        clock.advance(seconds=40)
        assert service.run_once() == 1 and service.last_run_failed is True
        broken = False
        clock.advance(seconds=61)
        assert service.run_once() == 1 and service.last_run_failed is False
        # Delivered: a later empty poll stays healthy.
        assert service.run_once() == 0 and service.last_run_failed is False


@pytest.mark.integration
def test_a_failed_state_ends_when_no_failed_row_is_left_waiting() -> None:
    clock = Clock()
    app, _, _, client = seeded(clock)

    def handler(request: httpx.Request) -> httpx.Response:
        raise RuntimeError("not an httpx error: `_retry` is never reached")

    with client:
        service = worker(app, handler, clock)
        assert service.run_once() == 1 and service.last_run_failed is True
        with factory_of(app).begin() as session:  # the row is closed meanwhile (e.g. revoked)
            session.execute(update(PushOutboxRow).values(next_attempt_at=None))
        assert service.run_once() == 0 and service.last_run_failed is False


@pytest.mark.integration
def test_the_backoff_jitter_stays_between_half_and_the_whole_delay() -> None:
    clock = Clock()
    app, _, _, client = seeded(clock)
    with client:
        low = PushDeliveryService(
            SqlPushDeliveryStore(factory_of(app)),
            HttpPushSender(create_client(httpx.MockTransport(lambda request: httpx.Response(503)))),
            HOSTS,
            clock=clock,
            jitter=lambda: 0.0,
        )
        low.run_once()
        (row,) = outbox(app)
        assert row.next_attempt_at == clock.now + push_delivery.BACKOFF_BASE / 2


@pytest.mark.integration
def test_a_change_during_a_send_is_not_swallowed_by_the_finished_send() -> None:
    clock = Clock()
    app, user_id, _, client = seeded(clock)

    def handler(request: httpx.Request) -> httpx.Response:
        # Another process commits a Task change while this POST is in flight.
        later = clock.now + timedelta(seconds=1)
        queue_wake(app, user_id, later)
        return httpx.Response(200)

    with client:
        worker(app, handler, clock).run_once()
        (row,) = outbox(app)
        assert row.delivered_at is None
        assert row.next_attempt_at == clock.now + timedelta(seconds=1)
        clock.advance(seconds=2)
        assert worker(app, lambda request: httpx.Response(200), clock).run_once() == 1
        assert outbox(app)[0].delivered_at is not None


@pytest.mark.integration
@pytest.mark.parametrize("how", ["revoked", "expired", "inactive_owner"])
def test_a_dead_device_credential_revokes_the_subscription_and_sends_nothing(how: str) -> None:
    clock = Clock()
    app, _, device, client = seeded(clock)
    calls: list[httpx.Request] = []
    with client:
        with factory_of(app).begin() as session:
            token = session.get(PersonalAccessTokenRow, device)
            assert token is not None
            if how == "revoked":
                token.revoked_at = utc_now()
            elif how == "expired":
                token.expires_at = clock.now - timedelta(seconds=1)
            else:
                session.execute(update(UserRow).values(active=False))
        service = worker(app, lambda request: calls.append(request) or httpx.Response(200), clock)
        service.run_once()
        assert calls == []
        assert subscription_of(app, device).revoked_at == clock.now
        (row,) = outbox(app)
        assert row.delivered_at is None and row.next_attempt_at is None
        assert row.last_error_kind == "credential"


@pytest.mark.integration
def test_an_endpoint_no_longer_allowed_is_revoked_before_any_request() -> None:
    clock = Clock()
    app, _, device, client = seeded(clock)
    calls: list[httpx.Request] = []
    with client:
        service = worker(
            app,
            lambda request: calls.append(request) or httpx.Response(200),
            clock,
            hosts=frozenset({"push.example.org"}),
        )
        service.run_once()
        assert calls == []
        assert subscription_of(app, device).revoked_at == clock.now
        assert outbox(app)[0].last_error_kind == "endpoint"


@pytest.mark.integration
def test_the_worker_with_push_disabled_reads_nothing_and_sends_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = Clock()
    app, _, _, client = seeded(clock)
    with client:
        built: list[object] = []

        def build(settings: object) -> tuple[None, None]:
            built.append(settings)
            return None, None

        push_worker.run_worker(make_settings(), once=True, build=build)  # type: ignore[arg-type]
        assert built == []
        assert outbox(app)[0].attempts == 0


@pytest.mark.integration
def test_no_endpoint_or_topic_reaches_a_log_record(caplog: pytest.LogCaptureFixture) -> None:
    clock = Clock()
    app, user_id, device, client = seeded(clock)
    # `configure_observability` stops the `sidekick` logger from propagating to the root handler.
    sidekick_logger = logging.getLogger("sidekick")
    sidekick_logger.addHandler(caplog.handler)
    with client, caplog.at_level(logging.DEBUG), caplog.at_level(logging.DEBUG, "sidekick"):
        outcomes: list[Handler] = [_ok, _server_error, _boom, _not_found]
        for outcome in outcomes:
            service = worker(app, outcome, clock)
            service.run_once()
            clock.advance(hours=1)
            queue_wake(app, user_id, clock.now)
            if subscription_of(app, device).revoked_at is not None:
                break
    sidekick_logger.removeHandler(caplog.handler)
    records = caplog.records
    delivery = [record for record in records if record.name == "sidekick.companion.push_delivery"]
    assert delivery, "the worker logged nothing"
    for record in records:
        rendered = json.dumps(
            [record.getMessage(), record.__dict__.get("push_host"), repr(record.args)],
            default=str,
        )
        assert SECRET_TOPIC not in rendered and "https://" not in rendered
        assert SECRET_TOPIC not in record.exc_text if record.exc_text else True
    assert {record.__dict__.get("push_host") for record in delivery} == {"ntfy.sh"}
    # Any HTTP client library (httpx, httpcore and their httpx2/httpcore2 copies) logs request URLs,
    # so none of its records may name the endpoint or the topic, and its loggers must be held back.
    for record in records:
        if record.name.startswith(("httpx", "httpcore")):
            rendered = json.dumps(
                [record.getMessage(), repr(record.args), record.exc_text], default=str
            )
            assert SECRET_TOPIC not in rendered and "ntfy.sh" not in rendered, record.name
    for name in HTTP_CLIENT_LOGGERS:
        assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING, name


@pytest.mark.integration
def test_the_app_role_cannot_delete_outbox_rows() -> None:
    app = push_app()
    owner(app)
    with pytest.raises(ProgrammingError), factory_of(app).begin() as session:
        session.execute(text("DELETE FROM sidekick.push_outbox"))


# --- Retry-After ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize(
    ("status", "header", "expected_wait"),
    [
        (429, "120", timedelta(seconds=120)),
        (503, "90", timedelta(seconds=90)),
        (429, "10", push_delivery.BACKOFF_BASE),
        (429, "1800", push_delivery.BACKOFF_CAP),
        (429, "Sun, 08 Nov 2026 12:10:00 GMT", timedelta(minutes=10)),
        (429, "Sun, 08 Nov 2026 11:00:00 GMT", push_delivery.BACKOFF_BASE),
        (429, "soon", push_delivery.BACKOFF_BASE),
        (429, "-5", push_delivery.BACKOFF_BASE),
        (503, "", push_delivery.BACKOFF_BASE),
    ],
)
def test_retry_after_postpones_the_retry_to_the_longer_of_it_and_the_backoff(
    status: int, header: str, expected_wait: timedelta
) -> None:
    clock = Clock()
    app, _, device, client = seeded(clock)
    with client:
        service = worker(app, _retry_after(status, header), clock)
        assert service.run_once() == 1
        (row,) = outbox(app)
        assert row.attempts == 1 and row.delivered_at is None
        assert row.next_attempt_at == clock.now + expected_wait
        assert row.last_error_kind == ("rate_limited" if status == 429 else "server_error")
        assert subscription_of(app, device).revoked_at is None


@pytest.mark.integration
@pytest.mark.parametrize(
    ("status", "header"),
    [(429, "1801"), (503, "86400"), (429, "Mon, 09 Nov 2026 12:00:00 GMT")],
)
def test_a_retry_after_beyond_the_cap_gives_the_row_up_at_once_without_revoking(
    status: int, header: str, caplog: pytest.LogCaptureFixture
) -> None:
    clock = Clock()
    app, user_id, device, client = seeded(clock)
    # `configure_observability` stops the `sidekick` logger from propagating to the root handler.
    sidekick_logger = logging.getLogger("sidekick")
    sidekick_logger.addHandler(caplog.handler)
    with client, caplog.at_level(logging.INFO, "sidekick"):
        service = worker(app, _retry_after(status, header), clock)
        assert service.run_once() == 1
        (row,) = outbox(app)
        assert row.attempts == 1 and row.next_attempt_at is None and row.delivered_at is None
        assert row.last_error_kind in {"rate_limited", "server_error"}
        subscription = subscription_of(app, device)
        assert subscription.revoked_at is None and subscription.failure_count == 1
        clock.advance(days=2)
        assert service.run_once() == 0
        # A later change starts a fresh wake.
        queue_wake(app, user_id, clock.now)
        assert [row.next_attempt_at for row in outbox(app)].count(clock.now) == 1
    sidekick_logger.removeHandler(caplog.handler)
    records = [r for r in caplog.records if r.getMessage() == "push_delivery"]
    assert [(r.__dict__["push_outcome"], r.__dict__["push_status"]) for r in records] == [
        ("gave_up", status)
    ]
    assert SECRET_TOPIC not in caplog.text and "ntfy.sh/" not in caplog.text


def test_parse_retry_after_reads_seconds_or_a_http_date_and_ignores_the_rest() -> None:
    now = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
    parse = push_delivery.parse_retry_after
    assert parse("45794", now) == timedelta(seconds=45794)
    assert parse(" 0 ", now) == timedelta(0)
    assert parse("Sun, 08 Nov 2026 12:01:30 GMT", now) == timedelta(seconds=90)
    assert parse("Sun, 08 Nov 2026 11:00:00 GMT", now) == timedelta(0)
    assert parse(None, now) is None
    for bad in ("", "soon", "-5", "1.5", "12 minutes", "٣"):
        assert parse(bad, now) is None


# --- host block ----------------------------------------------------------------------------

OTHER_HOST_ENDPOINT = "https://ntfy.example.org/upThirdTopic789ghi"


def two_subscriptions(
    clock: Clock, *, second_endpoint: str = OTHER_ENDPOINT
) -> tuple[FastAPI, TestClient]:
    settings = make_settings().model_copy(
        update={
            "companion_enabled": True,
            "push_enabled": True,
            "push_allowed_hosts": "ntfy.sh,ntfy.example.org",
        }
    )
    app = create_app(settings, database_factory())
    user_id = owner(app)
    client = TestClient(app)
    client.__enter__()
    subscribed(client, app, user_id)
    subscribed(client, app, user_id, second_endpoint)
    queue_wake(app, user_id, clock.now)
    assert len(outbox(app)) == 2
    return app, client


def counting(handler: Handler, seen: list[str]) -> Handler:
    def counted(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url.host))
        return handler(request)

    return counted


ALL_HOSTS = frozenset({"ntfy.sh", "ntfy.example.org"})


@pytest.mark.integration
def test_a_429_blocks_the_host_and_the_other_due_rows_are_moved_without_a_request() -> None:
    clock = Clock()
    app, client = two_subscriptions(clock)
    seen: list[str] = []
    with client:
        service = worker(app, counting(_retry_after(429, "120"), seen), clock, ALL_HOSTS)
        assert service.run_once() == 2
        assert seen == ["ntfy.sh"]
        rows = outbox(app)
        assert sorted(row.attempts for row in rows) == [0, 1]
        assert {row.next_attempt_at for row in rows} == {clock.now + timedelta(seconds=120)}
        # Nothing is due while the block lasts, and nothing is sent.
        clock.advance(seconds=119)
        assert service.run_once() == 0 and seen == ["ntfy.sh"]


@pytest.mark.integration
def test_a_block_beyond_the_cap_gives_up_the_rows_that_were_never_sent() -> None:
    clock = Clock()
    app, client = two_subscriptions(clock)
    seen: list[str] = []
    with client:
        service = worker(app, counting(_retry_after(429, "3600"), seen), clock, ALL_HOSTS)
        assert service.run_once() == 2
        assert seen == ["ntfy.sh"]
        rows = outbox(app)
        assert sorted(row.attempts for row in rows) == [0, 1]
        assert all(row.next_attempt_at is None and row.delivered_at is None for row in rows)
        assert {row.last_error_kind for row in rows} == {"rate_limited"}


@pytest.mark.integration
def test_the_block_ends_with_its_time_and_a_503_without_retry_after_uses_the_backoff() -> None:
    clock = Clock()
    app, client = two_subscriptions(clock)
    seen: list[str] = []
    state: dict[str, Handler] = {"handler": _service_unavailable}

    def handler(request: httpx.Request) -> httpx.Response:
        return state["handler"](request)

    with client:
        service = worker(app, counting(handler, seen), clock, ALL_HOSTS)
        assert service.run_once() == 2
        assert seen == ["ntfy.sh"]
        assert {row.next_attempt_at for row in outbox(app)} == {
            clock.now + push_delivery.BACKOFF_BASE
        }
        state["handler"] = _ok
        clock.advance(seconds=29)
        assert service.run_once() == 0
        clock.advance(seconds=1)
        assert service.run_once() == 2
        assert seen == ["ntfy.sh"] * 3
        assert all(row.delivered_at is not None for row in outbox(app))


@pytest.mark.integration
def test_a_block_on_one_host_does_not_stop_another_host() -> None:
    clock = Clock()
    app, client = two_subscriptions(clock, second_endpoint=OTHER_HOST_ENDPOINT)
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return (
            httpx.Response(429, headers={"Retry-After": "120"})
            if request.url.host == "ntfy.sh"
            else httpx.Response(200)
        )

    with client:
        service = worker(app, counting(handler, seen), clock, ALL_HOSTS)
        assert service.run_once() == 2
        assert sorted(seen) == ["ntfy.example.org", "ntfy.sh"]
        by_host = {row.subscription_id: row for row in outbox(app)}
        delivered = [row for row in by_host.values() if row.delivered_at is not None]
        waiting = [row for row in by_host.values() if row.delivered_at is None]
        assert len(delivered) == 1 and len(waiting) == 1
        assert waiting[0].next_attempt_at == clock.now + timedelta(seconds=120)


def test_the_wake_due_time_is_added_in_utc_across_a_clock_change() -> None:
    from zoneinfo import ZoneInfo

    from sidekick.companion.push_outbox_store import _wake_due

    stockholm = ZoneInfo("Europe/Stockholm")
    last = datetime(2026, 10, 25, 2, 59, 50, tzinfo=stockholm, fold=0)  # CEST, just before the end
    moment = last.astimezone(UTC)
    assert _wake_due(moment, last, timedelta(seconds=20)) == moment + timedelta(seconds=20)
    assert _wake_due(moment, last, timedelta(seconds=20)).utcoffset() == timedelta(0)


@pytest.mark.integration
def test_the_interval_holds_across_a_clock_change_with_a_non_utc_session() -> None:
    clock = Clock()
    app, user_id, client = delivered_at_start(clock)
    last = datetime(2026, 10, 25, 0, 59, 50, tzinfo=UTC)  # 02:59:50 CEST
    with client:
        with factory_of(app).begin() as session:
            session.execute(update(PushSubscriptionRow).values(last_success_at=last))
            session.execute(update(PushOutboxRow).values(delivered_at=last))
        with factory_of(app).begin() as session:
            session.execute(text("SET LOCAL TIME ZONE 'Europe/Stockholm'"))
            enqueue_wake(
                session,
                user_id,
                now=last + timedelta(seconds=1),
                min_interval=timedelta(seconds=20),
            )
        (row,) = pending(app)
        assert row.next_attempt_at == last + timedelta(seconds=20)


@pytest.mark.integration
def test_a_further_change_never_moves_a_waiting_wake_later() -> None:
    clock = Clock()
    app, user_id, client = delivered_at_start(clock)
    sent_at = clock.now
    interval = timedelta(seconds=20)
    with client:
        clock.advance(seconds=5)
        queue_wake(app, user_id, clock.now, interval)
        (row,) = pending(app)
        assert row.next_attempt_at == sent_at + interval
        # A reminder succeeds at +18 s, then another change arrives at +19 s.
        with factory_of(app).begin() as session:
            session.execute(
                update(PushSubscriptionRow).values(last_success_at=sent_at + timedelta(seconds=18))
            )
        clock.advance(seconds=14)
        queue_wake(app, user_id, clock.now, interval)
        (row,) = pending(app)
        assert row.next_attempt_at == sent_at + interval and row.attempts == 0


@pytest.mark.integration
def test_a_change_during_a_send_waits_for_the_interval_after_that_send() -> None:
    clock = Clock()
    app, user_id, _, client = seeded(clock)
    interval = timedelta(seconds=20)

    def handler(request: httpx.Request) -> httpx.Response:
        # A change commits while the POST is in flight; the last success it saw is older.
        queue_wake(app, user_id, clock.now + timedelta(seconds=1), interval)
        return httpx.Response(200)

    with client:
        service = PushDeliveryService(
            SqlPushDeliveryStore(factory_of(app)),
            HttpPushSender(create_client(httpx.MockTransport(handler))),
            HOSTS,
            clock=clock,
            jitter=lambda: 1.0,
            wake_min_interval=interval,
        )
        assert service.run_once() == 1
        (row,) = outbox(app)
        assert row.delivered_at is None and row.attempts == 0
        assert row.next_attempt_at == clock.now + interval
        clock.advance(seconds=19)
        assert worker(app, _ok, clock).run_once() == 0
        clock.advance(seconds=1)
        assert worker(app, _ok, clock).run_once() == 1


@pytest.mark.integration
def test_two_workers_with_slow_sends_deliver_each_notification_exactly_once() -> None:
    """Worker A leases a batch of three rows and sends them one after another, each send slow
    (40 s of the shared clock). While A is inside its second send the lease A took on the third
    row at claim time has run out, so worker B claims and sends it. A must then skip that row
    instead of sending it again."""

    clock = Clock()
    settings = make_settings().model_copy(update={"companion_enabled": True, "push_enabled": True})
    app = create_app(settings, database_factory())
    user_id = owner(app)
    topics = [f"{ENDPOINT}{n}" for n in range(3)]
    with TestClient(app) as client:
        for endpoint in topics:
            subscribed(client, app, user_id, endpoint)
        queue_wake(app, user_id, clock.now)
        assert len(outbox(app)) == 3

        sent: list[str] = []
        in_second_send = threading.Event()
        b_finished = threading.Event()

        def slow_a(request: httpx.Request) -> httpx.Response:
            sent.append(str(request.url))
            clock.advance(seconds=40)
            if len(sent) == 2:
                in_second_send.set()
                assert b_finished.wait(timeout=30)
            return httpx.Response(200)

        def fast_b(request: httpx.Request) -> httpx.Response:
            sent.append(str(request.url))
            return httpx.Response(200)

        worker_a = worker(app, slow_a, clock)
        worker_b = worker(app, fast_b, clock)
        outcome: list[int] = []
        thread = threading.Thread(target=lambda: outcome.append(worker_a.run_once()))
        thread.start()
        try:
            assert in_second_send.wait(timeout=30)
            # A's claim lease (60 s) on the third row has expired by now (clock +80 s); B takes it.
            assert worker_b.run_once() == 1
        finally:
            b_finished.set()
            thread.join(timeout=30)
        assert not thread.is_alive() and outcome == [3]
        assert sorted(sent) == sorted(topics)
        rows = outbox(app)
        assert len(rows) == 3 and all(row.delivered_at is not None for row in rows)


def test_the_default_wake_interval_is_twenty_seconds() -> None:
    from sidekick.shared.config import Settings

    assert Settings.model_fields["push_wake_min_interval_seconds"].default == 20
