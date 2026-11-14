"""Visible push reminders (ADR-005; D-078): the scheduler's summary and due reminders in
the owner's zone, quiet hours, dedup, and the pending / ack / test routes of a paired device. All
with a fixed clock. The push and the outbox never carry a title."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import ProgrammingError

from sidekick.api.app import create_app
from sidekick.companion.push_reminder_models import PushTestRateLimited
from sidekick.companion.push_reminder_store import SqlReminderStore
from sidekick.companion.push_reminders import (
    TEST_TITLES,
    TESTS_PER_HOUR,
    ReminderScheduler,
    ReminderService,
)
from sidekick.shared.persistence.models import (
    DomainRow,
    ProjectRow,
    PushOutboxRow,
    PushReminderRow,
    TaskRow,
)
from sidekick.shared.types import new_uuid7
from sidekick.work.persistence.store import SqlWorkStore
from tests.db import database_factory
from tests.support.companion import bearer, create_task, owner, paired_token
from tests.support.companion_push import (
    ENDPOINT,
    OTHER_ENDPOINT,
    URL,
    factory_of,
    subscribed,
)
from tests.support.settings import make_settings

SECRET = "Hemlig påminnelsetitel 7Q"
NOON = datetime(2026, 11, 9, 7, 0, tzinfo=UTC)  # 08:00 in Stockholm (UTC+1)


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def push_app(**overrides: object) -> FastAPI:
    settings = make_settings().model_copy(
        update={"companion_enabled": True, "push_enabled": True, **overrides}
    )
    return create_app(settings, database_factory())


def scheduler(app: FastAPI, clock: Clock) -> ReminderScheduler:
    return ReminderScheduler.from_settings(
        app.state.container.settings,
        SqlReminderStore(factory_of(app)),
        SqlWorkStore(factory_of(app)),
        clock=clock,
    )


def reminders(app: FastAPI, user_id: UUID | None = None) -> list[PushReminderRow]:
    with factory_of(app)() as session:
        statement = select(PushReminderRow).order_by(PushReminderRow.created_at, PushReminderRow.id)
        if user_id is not None:
            statement = statement.where(PushReminderRow.user_id == user_id)
        return list(session.scalars(statement))


def reminder_pushes(app: FastAPI) -> list[PushOutboxRow]:
    with factory_of(app)() as session:
        return list(
            session.scalars(
                select(PushOutboxRow).where(PushOutboxRow.kind == "r").order_by(PushOutboxRow.id)
            )
        )


def setup(
    clock: Clock | None = None,
) -> tuple[FastAPI, TestClient, UUID, str, UUID, Clock]:
    app = push_app()
    user_id = owner(app)
    client = TestClient(app)
    token, device = subscribed(client, app, user_id)
    clock = clock or Clock(NOON)
    # The routes use the container's `ReminderService`, which reads the real clock; reminders older
    # than a day are stale, so a test pinned to a fixed day would start failing once that day is
    # past. The test's clock replaces the service the routes read.
    container = app.state.container
    container.reminders = ReminderService(
        SqlReminderStore(factory_of(app)), clock=clock, locale=container.settings.mcp_app_locale
    )
    return app, client, user_id, token, device, clock


LONG_AGO = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def task_due(
    app: FastAPI,
    user_id: UUID,
    due: datetime,
    title: str = SECRET,
    created_at: datetime = LONG_AGO,
) -> UUID:
    """A Task due at `due`, created (by its `created_at`) before every fixed clock of the tests."""

    task_id: UUID = create_task(app, user_id, title, due_at=due).id
    set_task(app, task_id, created_at=created_at)
    return task_id


def set_task(app: FastAPI, task_id: UUID, **values: Any) -> None:
    with factory_of(app).begin() as session:
        session.execute(update(TaskRow).where(TaskRow.id == task_id).values(**values))


def parent_of(app: FastAPI, user_id: UUID, task_id: UUID, kind: str) -> tuple[type[Any], UUID]:
    """Put the Task under a new live Project or Domain; returns the parent's row type and id."""

    domain = DomainRow(
        id=new_uuid7(),
        owner_id=user_id,
        name="Hem",
        status="active",
        created_at=LONG_AGO,
        updated_at=LONG_AGO,
        version=1,
    )
    project = ProjectRow(
        id=new_uuid7(),
        owner_id=user_id,
        domain_id=domain.id,
        title="Renovering",
        status="active",
        created_at=LONG_AGO,
        updated_at=LONG_AGO,
        version=1,
    )
    with factory_of(app).begin() as session:
        session.add(domain)
        session.flush()
        session.add(project)
        session.flush()
    if kind == "project":
        set_task(app, task_id, project_id=project.id)
        return ProjectRow, project.id
    set_task(app, task_id, domain_id=domain.id)
    return DomainRow, domain.id


def set_trashed(
    app: FastAPI, row_type: type[Any], row_id: UUID, trashed_at: datetime | None
) -> None:
    with factory_of(app).begin() as session:
        session.execute(update(row_type).where(row_type.id == row_id).values(trashed_at=trashed_at))


# --- summary -------------------------------------------------------------------------------


@pytest.mark.integration
def test_the_summary_is_queued_at_eight_in_stockholm_counting_the_agendas_own_selection() -> None:
    app, client, user_id, _token, _device, clock = setup()
    with client:
        # Due today at 23:59 (bare date) and 'today' at 00:30 local, which is still the 8th in UTC.
        task_due(app, user_id, datetime(2026, 11, 9, 22, 59, tzinfo=UTC), "i dag")
        task_due(app, user_id, datetime(2026, 11, 8, 23, 30, tzinfo=UTC), "i dag natt")
        task_due(app, user_id, datetime(2026, 11, 7, 10, 0, tzinfo=UTC), "försenad")
        task_due(app, user_id, datetime(2026, 11, 10, 22, 59, tzinfo=UTC), "i morgon")
        completed = task_due(app, user_id, datetime(2026, 11, 7, 10, 0, tzinfo=UTC), "klar")
        set_task(app, completed, status="completed", completed_at=NOON)

        # The 00:30 task also has a clock time: its own due reminder is shown from 07:00 on.
        clock.now = NOON - timedelta(seconds=1)
        scheduler(app, clock).run_once()
        assert [item.kind for item in reminders(app)] == ["due"]

        clock.now = NOON
        assert scheduler(app, clock).run_once() == 1
        [due_reminder, summary] = reminders(app)
        assert (summary.kind, summary.dedup_key) == ("summary", "s:2026-11-09")
        # The 00:30 task is already past at 08:00, so the agenda counts it as overdue.
        assert (summary.summary_today, summary.summary_overdue) == (1, 2)
        assert summary.task_id is None and summary.payload_title is None
        assert {push.dedup_key for push in reminder_pushes(app)} == {
            str(due_reminder.id),
            str(summary.id),
        }


@pytest.mark.integration
def test_the_summary_is_queued_once_per_day_and_again_the_next_day() -> None:
    app, client, user_id, _token, _device, clock = setup()
    with client:
        task_due(app, user_id, datetime(2026, 11, 7, 10, 0, tzinfo=UTC))
        service = scheduler(app, clock)
        assert service.run_once() == 1
        clock.now += timedelta(minutes=30)
        assert service.run_once() == 0
        clock.now += timedelta(days=1)
        assert service.run_once() == 1
        assert [item.dedup_key for item in reminders(app)] == ["s:2026-11-09", "s:2026-11-10"]
        assert len(reminder_pushes(app)) == 2


@pytest.mark.integration
def test_an_empty_day_has_no_summary() -> None:
    app, client, user_id, _token, _device, clock = setup()
    with client:
        task_due(app, user_id, datetime(2026, 11, 11, 22, 59, tzinfo=UTC), "senare")
        assert scheduler(app, clock).run_once() == 0
        assert reminders(app) == [] and reminder_pushes(app) == []


@pytest.mark.integration
def test_no_summary_without_an_active_subscription() -> None:
    app = push_app()
    user_id = owner(app)
    task_due(app, user_id, datetime(2026, 11, 7, 10, 0, tzinfo=UTC))
    assert scheduler(app, Clock(NOON)).run_once() == 0
    assert reminders(app) == []


# --- due -----------------------------------------------------------------------------------


@pytest.mark.integration
def test_a_due_reminder_is_queued_fifteen_minutes_before_the_clock_time() -> None:
    app, client, user_id, _token, _device, clock = setup()
    with client:
        due = datetime(2026, 11, 9, 13, 0, tzinfo=UTC)  # 14:00 in Stockholm
        task_id = task_due(app, user_id, due)
        clock.now = due - timedelta(minutes=15, seconds=1)
        assert scheduler(app, clock).run_once() == 0
        clock.now = due - timedelta(minutes=15)
        assert scheduler(app, clock).run_once() == 1
        [reminder] = reminders(app)
        assert reminder.kind == "due" and reminder.task_id == task_id
        assert reminder.payload_title == SECRET and reminder.due_at == due
        assert reminder.scheduled_for == due - timedelta(minutes=15)


@pytest.mark.integration
def test_a_task_created_after_its_reminder_moment_and_due_time_gets_no_reminder() -> None:
    app, client, user_id, _token, _device, clock = setup()
    with client:
        # Created 10:30 (Stockholm), due 09:00: the moment 08:45 is behind it, so is the due time.
        due = datetime(2026, 11, 9, 8, 0, tzinfo=UTC)
        created = datetime(2026, 11, 9, 9, 30, tzinfo=UTC)
        task_due(app, user_id, due, created_at=created)
        clock.now = created + timedelta(minutes=1)
        assert scheduler(app, clock).run_once() == 0
        assert reminders(app) == []


@pytest.mark.integration
def test_a_night_due_at_of_a_task_created_after_seven_is_left_to_the_summary() -> None:
    app, client, user_id, _token, _device, clock = setup()
    with client:
        # Due 02:00 on the 10th (01:45 is quiet: moved to 07:00), created 07:05 that morning.
        due = datetime(2026, 11, 10, 1, 0, tzinfo=UTC)
        task_due(app, user_id, due, "sent", created_at=datetime(2026, 11, 10, 6, 5, tzinfo=UTC))
        task_due(app, user_id, due, "tidigt", created_at=datetime(2026, 11, 9, 12, 0, tzinfo=UTC))
        clock.now = datetime(2026, 11, 10, 6, 10, tzinfo=UTC)  # 07:10 in Stockholm
        assert scheduler(app, clock).run_once() == 1
        [reminder] = reminders(app)
        assert reminder.payload_title == "tidigt"


@pytest.mark.integration
def test_a_bare_date_has_no_due_reminder_and_neither_has_a_task_without_a_due_time() -> None:
    app, client, user_id, _token, _device, clock = setup()
    with client:
        task_due(app, user_id, datetime(2026, 11, 9, 22, 59, tzinfo=UTC), "bara datum")
        create_task(app, user_id, "utan datum")
        clock.now = datetime(2026, 11, 9, 22, 50, tzinfo=UTC)
        assert scheduler(app, clock).run_once() == 0


@pytest.mark.integration
def test_a_due_reminder_in_quiet_hours_waits_for_seven() -> None:
    app, client, user_id, _token, _device, clock = setup()
    with client:
        due = datetime(2026, 11, 9, 21, 30, tzinfo=UTC)  # 22:30 in Stockholm, reminder 22:15
        task_due(app, user_id, due)
        clock.now = datetime(2026, 11, 9, 21, 20, tzinfo=UTC)
        assert scheduler(app, clock).run_once() == 0
        clock.now = datetime(2026, 11, 10, 5, 59, tzinfo=UTC)
        assert scheduler(app, clock).run_once() == 0
        clock.now = datetime(2026, 11, 10, 6, 0, tzinfo=UTC)  # 07:00 in Stockholm
        assert scheduler(app, clock).run_once() == 1
        [reminder] = reminders(app)
        assert reminder.scheduled_for == datetime(2026, 11, 10, 6, 0, tzinfo=UTC)


@pytest.mark.integration
def test_the_same_due_reminder_is_never_queued_twice_but_a_moved_due_at_is_a_new_one() -> None:
    app, client, user_id, token, _device, clock = setup()
    with client:
        due = datetime(2026, 11, 9, 13, 0, tzinfo=UTC)
        task_id = task_due(app, user_id, due)
        clock.now = due - timedelta(minutes=10)
        service = scheduler(app, clock)
        assert service.run_once() == 1
        assert service.run_once() == 0
        clock.now += timedelta(minutes=1)
        assert service.run_once() == 0

        moved = due + timedelta(minutes=20)
        set_task(app, task_id, due_at=moved)
        clock.now = moved - timedelta(minutes=10)
        assert service.run_once() == 1
        assert len(reminders(app)) == 2 and len(reminder_pushes(app)) == 2
        # The phone only sees the reminder for the due time the Task has now.
        pending = client.get("/companion/v1/reminders/pending", headers=bearer(token)).json()
        assert [item["due_at"] for item in pending["items"]] == [moved.isoformat()]


@pytest.mark.integration
@pytest.mark.parametrize("change", ["completed", "trashed", "archived"])
def test_a_finished_or_removed_task_gets_no_reminder(change: str) -> None:
    app, client, user_id, token, _device, clock = setup()
    with client:
        due = datetime(2026, 11, 9, 13, 0, tzinfo=UTC)
        task_id = task_due(app, user_id, due)
        clock.now = due - timedelta(minutes=10)
        fields = {
            "completed": {"status": "completed", "completed_at": clock.now},
            "trashed": {"trashed_at": clock.now},
            "archived": {"archived_at": clock.now},
        }[change]
        set_task(app, task_id, **fields)
        assert scheduler(app, clock).run_once() == 0
        assert reminders(app) == []

        # Finished only after the reminder was queued: it is no longer pending for the phone.
        set_task(app, task_id, status="todo", completed_at=None, trashed_at=None, archived_at=None)
        assert scheduler(app, clock).run_once() == 1
        set_task(app, task_id, **fields)
        pending = client.get("/companion/v1/reminders/pending", headers=bearer(token)).json()
        assert pending["items"] == []


@pytest.mark.integration
def test_another_owners_tasks_never_reach_this_owner() -> None:
    app, client, _user_id, _token, _device, clock = setup()
    with client:
        other = owner(app, "someone-else")
        due = datetime(2026, 11, 9, 13, 0, tzinfo=UTC)
        task_due(app, other, due, "den andres titel")
        clock.now = due - timedelta(minutes=10)
        assert scheduler(app, clock).run_once() == 0
        assert reminders(app) == []


@pytest.mark.integration
def test_each_active_subscription_gets_one_r_and_a_revoked_one_none() -> None:
    app, client, user_id, _token, _device, clock = setup()
    with client:
        second_token, second_device = subscribed(client, app, user_id, OTHER_ENDPOINT)
        third_token, _third = subscribed(client, app, user_id, "https://ntfy.sh/upThirdTopic789ghi")
        assert client.delete(URL, headers=bearer(third_token)).status_code == 204
        task_due(app, user_id, datetime(2026, 11, 7, 10, 0, tzinfo=UTC))
        assert scheduler(app, clock).run_once() == 1
        assert len(reminder_pushes(app)) == 2
        assert second_token and second_device


# --- pending and ack -----------------------------------------------------------------------


def seeded_pending(app: FastAPI, client: TestClient, user_id: UUID, clock: Clock) -> dict[str, Any]:
    due = datetime(2026, 11, 9, 13, 0, tzinfo=UTC)
    task_due(app, user_id, due)
    task_due(app, user_id, datetime(2026, 11, 7, 10, 0, tzinfo=UTC), "försenad")
    service = scheduler(app, clock)
    service.run_once()  # the summary at 08:00
    clock.now = due - timedelta(minutes=5)
    service.run_once()  # the due reminder
    return {"due": due}


@pytest.mark.integration
def test_pending_lists_the_summary_and_the_items_without_a_description() -> None:
    app, client, user_id, token, _device, clock = setup()
    with client:
        create_task(
            app,
            user_id,
            "med beskrivning",
            description="Hemlig beskrivning 9Z",
            due_at=datetime(2026, 11, 9, 13, 0, tzinfo=UTC),
        )
        task_due(app, user_id, datetime(2026, 11, 7, 10, 0, tzinfo=UTC), "försenad")
        service = scheduler(app, clock)
        service.run_once()
        clock.now = datetime(2026, 11, 9, 12, 55, tzinfo=UTC)
        service.run_once()
        response = client.get("/companion/v1/reminders/pending", headers=bearer(token))
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        body = response.json()
        assert body["timezone"] == "Europe/Stockholm"
        assert set(body["summary"]) == {"id", "today", "overdue"}
        assert (body["summary"]["today"], body["summary"]["overdue"]) == (1, 1)
        [item] = body["items"]
        assert set(item) == {"id", "kind", "title", "task_id", "due_at"}
        assert item["kind"] == "due" and item["title"] == "med beskrivning"
        assert item["due_at"] == datetime(2026, 11, 9, 13, 0, tzinfo=UTC).isoformat()
        assert "Hemlig beskrivning" not in response.text


@pytest.mark.integration
def test_pending_is_empty_without_reminders_and_caps_at_twenty_items_newest_kept() -> None:
    app, client, user_id, token, _device, clock = setup()
    with client:
        assert client.get("/companion/v1/reminders/pending", headers=bearer(token)).json() == {
            "timezone": "Europe/Stockholm",
            "items": [],
            "summary": None,
        }
        factory = factory_of(app)
        service = ReminderService(SqlReminderStore(factory), clock=clock)
        with factory.begin() as session:
            for index in range(25):
                session.add(
                    PushReminderRow(
                        id=uuid4(),
                        user_id=user_id,
                        kind="test",
                        dedup_key=f"t:x:{index}",
                        payload_title=f"test {index}",
                        scheduled_for=NOON + timedelta(minutes=index),
                        created_at=NOON,
                    )
                )
        clock.now = NOON + timedelta(minutes=30)
        pending = service.pending(user_id)
        assert [item.title for item in pending.items] == [f"test {i}" for i in range(5, 25)]


@pytest.mark.integration
def test_a_reminder_nobody_fetched_for_a_day_is_stale() -> None:
    app, client, user_id, _token, _device, clock = setup()
    with client:
        task_due(app, user_id, datetime(2026, 11, 7, 10, 0, tzinfo=UTC))
        scheduler(app, clock).run_once()
        service = ReminderService(SqlReminderStore(factory_of(app)), clock=clock)
        clock.now = NOON + timedelta(hours=23)
        assert service.pending(user_id).summary is not None
        clock.now = NOON + timedelta(hours=25)
        assert service.pending(user_id).summary is None


@pytest.mark.integration
def test_ack_hides_the_reminders_is_idempotent_and_touches_only_the_owners_own() -> None:
    app, client, user_id, token, _device, clock = setup()
    with client:
        seeded_pending(app, client, user_id, clock)
        other = owner(app, "someone-else")
        other_token = paired_token(client, app, other)
        stranger = ReminderService(SqlReminderStore(factory_of(app)), clock=clock)
        with factory_of(app).begin() as session:
            foreign = uuid4()
            session.add(
                PushReminderRow(
                    id=foreign,
                    user_id=other,
                    kind="test",
                    dedup_key="t:z:1",
                    payload_title=TEST_TITLES["sv"],
                    scheduled_for=clock.now,
                    created_at=clock.now,
                )
            )
        mine = [row.id for row in reminders(app, user_id)]
        assert len(mine) == 2
        response = client.post(
            "/companion/v1/reminders/ack",
            json={"ids": [str(mine[0]), str(foreign), str(uuid4())]},
            headers=bearer(token),
        )
        assert response.status_code == 204 and response.content == b""
        again = client.post(
            "/companion/v1/reminders/ack", json={"ids": [str(mine[0])]}, headers=bearer(token)
        )
        assert again.status_code == 204
        by_id = {row.id: row for row in reminders(app)}
        assert by_id[mine[0]].acked_at is not None
        assert by_id[mine[1]].acked_at is None
        assert by_id[foreign].acked_at is None
        first_ack = by_id[mine[0]].acked_at
        assert stranger.ack(user_id, [mine[0]]) == 0
        assert {row.id: row for row in reminders(app)}[mine[0]].acked_at == first_ack
        # The other owner's device cannot ack mine either.
        client.post(
            "/companion/v1/reminders/ack", json={"ids": [str(mine[1])]}, headers=bearer(other_token)
        )
        assert {row.id: row for row in reminders(app)}[mine[1]].acked_at is None
        assert stranger.ack(user_id, [mine[1]]) == 1
        assert stranger.pending(user_id).summary is None


@pytest.mark.integration
def test_pending_shows_only_the_callers_own_reminders() -> None:
    app, client, user_id, _token, _device, clock = setup()
    with client:
        task_due(app, user_id, datetime(2026, 11, 7, 10, 0, tzinfo=UTC))
        scheduler(app, clock).run_once()
        other = owner(app, "someone-else")
        other_token = paired_token(client, app, other)
        assert (
            client.get("/companion/v1/reminders/pending", headers=bearer(other_token)).json()[
                "summary"
            ]
            is None
        )


@pytest.mark.integration
def test_pending_and_ack_refuse_without_a_valid_token_or_the_push_capability() -> None:
    app, client, user_id, _token, _device, _clock = setup()
    with client:
        for method, path, body in (
            ("get", "/companion/v1/reminders/pending", None),
            ("post", "/companion/v1/reminders/ack", {"ids": [str(uuid4())]}),
            ("post", "/companion/v1/push/test", None),
        ):
            missing = getattr(client, method)(path, **({"json": body} if body else {}))
            assert missing.status_code == 401, path
            bad = getattr(client, method)(
                path, headers=bearer("rsc_nope"), **({"json": body} if body else {})
            )
            assert bad.status_code == 401, path
        no_push = paired_token(client, app, user_id, scopes={"companion:tasks:read"})
        for method, path, body in (
            ("get", "/companion/v1/reminders/pending", None),
            ("post", "/companion/v1/reminders/ack", {"ids": [str(uuid4())]}),
            ("post", "/companion/v1/push/test", None),
        ):
            response = getattr(client, method)(
                path, headers=bearer(no_push), **({"json": body} if body else {})
            )
            assert response.status_code == 403, path
            assert response.json()["reason"] == "capability_missing"


@pytest.mark.integration
@pytest.mark.parametrize(
    "body",
    [
        {},
        {"ids": []},
        {"ids": ["not-a-uuid"]},
        {"ids": [str(uuid4())] * 51},
        {"ids": [str(uuid4())], "extra": 1},
        {"ids": "x"},
    ],
)
def test_ack_validates_its_body(body: dict[str, Any]) -> None:
    _app, client, _user, token, _device, _clock = setup()
    with client:
        response = client.post("/companion/v1/reminders/ack", json=body, headers=bearer(token))
        assert response.status_code == 422
        assert response.json()["code"] == "validation_error"
        assert "not-a-uuid" not in response.text


@pytest.mark.integration
def test_ack_takes_fifty_ids_and_requires_json_and_a_small_body() -> None:
    _app, client, _user, token, _device, _clock = setup()
    with client:
        ids = [str(uuid4()) for _ in range(50)]
        assert (
            client.post(
                "/companion/v1/reminders/ack", json={"ids": ids}, headers=bearer(token)
            ).status_code
            == 204
        )
        plain = client.post("/companion/v1/reminders/ack", content=b"{}", headers=bearer(token))
        assert plain.status_code == 415
        big = client.post(
            "/companion/v1/reminders/ack",
            content=b'{"ids": ["' + b"x" * 5000 + b'"]}',
            headers={**bearer(token), "Content-Type": "application/json"},
        )
        assert big.status_code == 413


# --- test notification ---------------------------------------------------------------------


@pytest.mark.integration
def test_the_test_route_queues_a_visible_test_and_an_r_for_this_device_only() -> None:
    app, client, user_id, token, device, _clock = setup()
    with client:
        _other_token, other_device = subscribed(client, app, user_id, OTHER_ENDPOINT)
        response = client.post("/companion/v1/push/test", headers=bearer(token))
        assert response.status_code == 202
        assert response.headers["cache-control"] == "no-store"
        [test] = reminders(app)
        assert (test.kind, test.payload_title) == ("test", TEST_TITLES["sv"])
        [push] = reminder_pushes(app)
        assert push.dedup_key == str(test.id) and push.kind == "r"
        pending = client.get("/companion/v1/reminders/pending", headers=bearer(token)).json()
        assert [
            (item["kind"], item["title"], item["task_id"], item["due_at"])
            for item in pending["items"]
        ] == [("test", TEST_TITLES["sv"], None, None)]
        assert device != other_device


@pytest.mark.integration
def test_the_test_route_allows_five_an_hour_per_device() -> None:
    app, client, user_id, token, _device, _clock = setup()
    with client:
        other_token, _ = subscribed(client, app, user_id, OTHER_ENDPOINT)
        statuses = [
            client.post("/companion/v1/push/test", headers=bearer(token)).status_code
            for _ in range(TESTS_PER_HOUR + 1)
        ]
        assert statuses == [202] * TESTS_PER_HOUR + [429]
        limited = client.post("/companion/v1/push/test", headers=bearer(token))
        assert limited.json()["code"] == "rate_limited"
        assert limited.headers["retry-after"] == "3600"
        # Another device has its own budget.
        assert (
            client.post("/companion/v1/push/test", headers=bearer(other_token)).status_code == 202
        )
        assert len(reminders(app)) == TESTS_PER_HOUR + 1


@pytest.mark.integration
def test_the_test_budget_frees_up_after_an_hour() -> None:
    app, client, user_id, _token, device, clock = setup()
    with client:
        service = ReminderService(SqlReminderStore(factory_of(app)), clock=clock)
        for _ in range(TESTS_PER_HOUR):
            service.queue_test(user_id, device)
        with pytest.raises(PushTestRateLimited):
            service.queue_test(user_id, device)
        clock.now += timedelta(hours=1, seconds=1)
        service.queue_test(user_id, device)


@pytest.mark.integration
def test_the_test_notification_is_titled_in_the_app_language() -> None:
    app = push_app(mcp_app_locale="en")
    user_id = owner(app)
    with TestClient(app) as client:
        token, _device = subscribed(client, app, user_id)
        assert client.post("/companion/v1/push/test", headers=bearer(token)).status_code == 202
        [test] = reminders(app)
        assert test.payload_title == TEST_TITLES["en"] == "Test notification from Sidekick"
        pending = client.get("/companion/v1/reminders/pending", headers=bearer(token)).json()
        assert [item["title"] for item in pending["items"]] == [TEST_TITLES["en"]]


@pytest.mark.integration
def test_the_test_route_without_a_subscription_is_a_conflict_and_queues_nothing() -> None:
    app = push_app()
    user_id = owner(app)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        response = client.post("/companion/v1/push/test", headers=bearer(token))
        assert response.status_code == 409 and response.json()["reason"] == "no_subscription"
        assert reminders(app) == [] and reminder_pushes(app) == []


@pytest.mark.integration
def test_with_push_disabled_the_test_route_is_not_found_and_pending_is_empty() -> None:
    settings = make_settings().model_copy(update={"companion_enabled": True})
    app = create_app(settings, database_factory())
    user_id = owner(app)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        assert client.post("/companion/v1/push/test", headers=bearer(token)).status_code == 404
        assert (
            client.get("/companion/v1/reminders/pending", headers=bearer(token)).json()["items"]
            == []
        )
        assert reminders(app) == []


# --- privacy -------------------------------------------------------------------------------


@pytest.mark.integration
def test_no_title_reaches_the_outbox_or_a_log_record(caplog: pytest.LogCaptureFixture) -> None:
    app, client, user_id, token, _device, clock = setup()
    sidekick_logger = logging.getLogger("sidekick")
    sidekick_logger.addHandler(caplog.handler)
    with client, caplog.at_level(logging.DEBUG), caplog.at_level(logging.DEBUG, "sidekick"):
        due = datetime(2026, 11, 9, 13, 0, tzinfo=UTC)
        task_due(app, user_id, due)
        task_due(app, user_id, datetime(2026, 11, 7, 10, 0, tzinfo=UTC), SECRET + " försenad")
        service = scheduler(app, clock)
        service.run_once()
        clock.now = due - timedelta(minutes=5)
        service.run_once()
        client.post("/companion/v1/push/test", headers=bearer(token))
        client.get("/companion/v1/reminders/pending", headers=bearer(token))
        client.post(
            "/companion/v1/reminders/ack", json={"ids": [str(uuid4())]}, headers=bearer(token)
        )
    sidekick_logger.removeHandler(caplog.handler)
    with factory_of(app)() as session:
        outbox_text = json.dumps(
            [
                dict(row)
                for row in session.execute(text("SELECT * FROM sidekick.push_outbox")).mappings()
            ],
            default=str,
        )
    assert SECRET not in outbox_text and TEST_TITLES["sv"] not in outbox_text
    assert "Hemlig" not in outbox_text and ENDPOINT not in outbox_text
    names = {name for name in json.loads(outbox_text)[0]}
    assert "payload_title" not in names and "title" not in names
    scheduler_records = [r for r in caplog.records if r.name.startswith("sidekick.companion")]
    assert scheduler_records
    for record in caplog.records:
        rendered = json.dumps(
            [record.getMessage(), repr(record.args), record.exc_text, record.__dict__], default=str
        )
        assert "Hemlig" not in rendered and TEST_TITLES["sv"] not in rendered
        assert "https://ntfy.sh" not in rendered


@pytest.mark.integration
def test_the_app_role_cannot_delete_reminders_and_the_content_lives_only_there() -> None:
    app, client, user_id, _token, _device, clock = setup()
    with client:
        task_due(app, user_id, datetime(2026, 11, 7, 10, 0, tzinfo=UTC))
        scheduler(app, clock).run_once()
        with pytest.raises(ProgrammingError), factory_of(app).begin() as session:
            session.execute(text("DELETE FROM sidekick.push_reminders"))
        with factory_of(app)() as session:
            assert session.scalar(select(func.count()).select_from(PushReminderRow)) == 1


@pytest.mark.integration
@pytest.mark.parametrize("kind", ["project", "domain"])
def test_a_task_of_a_trashed_parent_gets_no_due_reminder_until_the_parent_is_restored(
    kind: str,
) -> None:
    app, client, user_id, _token, _device, clock = setup()
    with client:
        due = datetime(2026, 11, 9, 13, 0, tzinfo=UTC)
        task_id = task_due(app, user_id, due)
        row_type, parent_id = parent_of(app, user_id, task_id, kind)
        set_trashed(app, row_type, parent_id, NOON)
        clock.now = due - timedelta(minutes=15)

        assert scheduler(app, clock).run_once() == 0
        assert reminders(app) == []

        set_trashed(app, row_type, parent_id, None)
        assert scheduler(app, clock).run_once() == 1
        [reminder] = reminders(app)
        assert reminder.kind == "due" and reminder.task_id == task_id


@pytest.mark.integration
@pytest.mark.parametrize("kind", ["project", "domain"])
def test_a_queued_due_reminder_drops_out_of_pending_while_its_parent_is_trashed(
    kind: str,
) -> None:
    app, client, user_id, token, _device, clock = setup()
    with client:
        due = datetime(2026, 11, 9, 13, 0, tzinfo=UTC)
        task_id = task_due(app, user_id, due)
        row_type, parent_id = parent_of(app, user_id, task_id, kind)
        clock.now = due - timedelta(minutes=15)
        assert scheduler(app, clock).run_once() == 1

        def pending_items() -> list[Any]:
            response = client.get("/companion/v1/reminders/pending", headers=bearer(token))
            return list(response.json()["items"])

        assert [item["task_id"] for item in pending_items()] == [str(task_id)]
        set_trashed(app, row_type, parent_id, clock.now)
        assert pending_items() == []
        set_trashed(app, row_type, parent_id, None)
        assert [item["task_id"] for item in pending_items()] == [str(task_id)]
