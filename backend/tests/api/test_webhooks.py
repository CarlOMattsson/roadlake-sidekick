"""`/webhooks/v1/`: the token, its scopes, idempotent writes, the per-token rate limit, the body cap
and the content-free log of the webhook entrance."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from sidekick.shared.auth import COMPANION_SCOPES, TOKEN_SCOPES
from sidekick.shared.persistence.models import ActivityEntryRow, AuditEventRow
from sidekick.webhooks.store import WebhookTokenStore
from sidekick.webhooks.tokens import (
    WEBHOOK_SHOPPING_ADD,
    WEBHOOK_TASKS_CREATE,
    WebhookTokenService,
)
from tests.support.companion import bearer, paired_token
from tests.support.webhooks import (
    JSON,
    SHOPPING_ITEMS,
    TASKS,
    call_headers,
    fresh_key,
    issue,
    new_list,
    owner,
    owner_actor,
    webhook_app,
)

ALL_WRITES = [(SHOPPING_ITEMS, {"name": "Mjölk"}), (TASKS, {"title": "Ring tandläkaren"})]


def open_items(app: FastAPI, user_id: UUID) -> int:
    shopping = app.state.container.shopping
    actor = owner_actor(user_id)
    return sum(entry.open_count for entry in shopping.list_lists(actor).lists)


def task_count(app: FastAPI, user_id: UUID) -> int:
    page = app.state.container.tasks.list(owner_actor(user_id), limit=100)
    return len(page.items)


def nothing_written(app: FastAPI, user_id: UUID) -> bool:
    return open_items(app, user_id) == 0 and task_count(app, user_id) == 0


@pytest.mark.integration
def test_the_entrance_is_off_unless_it_is_switched_on() -> None:
    app = webhook_app(enabled=False)
    user_id = owner(app)
    token = issue(app, user_id).token
    with TestClient(app) as client:
        responses = [
            client.post(path, headers=call_headers(token, fresh_key()), json=body)
            for path, body in ALL_WRITES
        ]
    assert [response.status_code for response in responses] == [404, 404]
    assert nothing_written(app, user_id)


@pytest.mark.integration
@pytest.mark.parametrize("path,body", ALL_WRITES)
@pytest.mark.parametrize("credential", ["none", "basic", "unknown", "mcp", "companion"])
def test_a_missing_wrong_or_foreign_credential_is_401_and_writes_nothing(
    path: str, body: dict[str, Any], credential: str
) -> None:
    app = webhook_app(companion=True)
    user_id = owner(app)
    container = app.state.container
    mcp_token = container.auth.create_personal_token(user_id, "mcp", frozenset(TOKEN_SCOPES))
    with TestClient(app) as client:
        device_token = paired_token(client, app, user_id, scopes=COMPANION_SCOPES)
        authorization: dict[str, str] = {
            "none": {},
            "basic": {"Authorization": "Basic Zm9vOmJhcg=="},
            "unknown": bearer("rsw_unknown"),
            "mcp": bearer(mcp_token),
            "companion": bearer(device_token),
        }[credential]
        headers = {**JSON, "Idempotency-Key": fresh_key(), **authorization}
        response = client.post(path, headers=headers, json=body)
    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"
    assert response.json()["api_version"] == "webhooks.v1"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["www-authenticate"].startswith("Bearer")
    assert nothing_written(app, user_id)


@pytest.mark.integration
def test_a_webhook_token_is_not_another_kind_of_credential_and_they_are_not_its_kind() -> None:
    app = webhook_app()
    user_id = owner(app)
    container = app.state.container
    token = issue(app, user_id).token
    mcp_token = container.auth.create_personal_token(user_id, "mcp", frozenset(TOKEN_SCOPES))
    assert container.auth.verify_personal_token(token) is None
    assert container.auth.verify_companion_token(token) is None
    assert container.webhook_tokens.verify(mcp_token) is None
    assert container.webhook_tokens.verify(token) is not None


@pytest.mark.integration
@pytest.mark.parametrize("path,body", ALL_WRITES)
def test_a_revoked_expired_or_disabled_owner_token_is_401(path: str, body: dict[str, Any]) -> None:
    app = webhook_app()
    container = app.state.container
    user_id = owner(app)
    revoked = issue(app, user_id)
    assert container.webhook_tokens.revoke(user_id, revoked.record.id) is True
    long_ago = WebhookTokenService(
        WebhookTokenStore(container.session_factory),
        container.auth,
        clock=lambda: datetime.now(UTC) - timedelta(days=30),
    )
    expired = long_ago.create(
        user_id, "Old", [WEBHOOK_SHOPPING_ADD, WEBHOOK_TASKS_CREATE], lifetime_days=1
    )
    disabled_owner = owner(app, "other")
    disabled = issue(app, disabled_owner)
    container.auth.disable_user(disabled_owner)
    with TestClient(app) as client:
        for token in (revoked.token, expired.token, disabled.token):
            response = client.post(path, headers=call_headers(token, fresh_key()), json=body)
            assert response.status_code == 401, response.text
            assert response.json()["code"] == "unauthorized"
    assert nothing_written(app, user_id)


@pytest.mark.integration
def test_a_token_holds_only_the_scopes_it_was_given() -> None:
    app = webhook_app()
    user_id = owner(app)
    new_list(app, user_id)
    shopping_only = issue(app, user_id, (WEBHOOK_SHOPPING_ADD,)).token
    tasks_only = issue(app, user_id, (WEBHOOK_TASKS_CREATE,)).token
    with TestClient(app) as client:
        denied = [
            client.post(
                TASKS, headers=call_headers(shopping_only, fresh_key()), json={"title": "T"}
            ),
            client.post(
                SHOPPING_ITEMS, headers=call_headers(tasks_only, fresh_key()), json={"name": "N"}
            ),
        ]
        allowed = [
            client.post(
                SHOPPING_ITEMS, headers=call_headers(shopping_only, fresh_key()), json={"name": "N"}
            ),
            client.post(TASKS, headers=call_headers(tasks_only, fresh_key()), json={"title": "T"}),
        ]
    for response in denied:
        assert response.status_code == 403, response.text
        assert response.json()["code"] == "forbidden"
        assert response.json()["reason"] == "scope_missing"
    assert [response.status_code for response in allowed] == [201, 201]
    assert open_items(app, user_id) == 1
    assert task_count(app, user_id) == 1


@pytest.mark.integration
def test_an_item_lands_on_the_oldest_active_list_or_the_one_named() -> None:
    app = webhook_app()
    user_id = owner(app)
    first = new_list(app, user_id, "Första")
    second = new_list(app, user_id, "Andra")
    token = issue(app, user_id).token
    shopping = app.state.container.shopping
    actor = owner_actor(user_id)
    with TestClient(app) as client:
        default = client.post(
            SHOPPING_ITEMS,
            headers=call_headers(token, fresh_key()),
            json={"name": "Mjölk", "quantity": "2", "unit": "l", "note": "ekologisk"},
        )
        named = client.post(
            SHOPPING_ITEMS,
            headers=call_headers(token, fresh_key()),
            json={"name": "Bröd", "list_id": str(second)},
        )
    assert default.status_code == 201, default.text
    assert default.json().keys() == {"list_id", "item_id"}
    assert default.json()["list_id"] == str(first)
    assert named.json()["list_id"] == str(second)
    stored = shopping.get_list(actor, first).items
    assert [(row.name, str(row.quantity), row.unit, row.note) for row in stored] == [
        ("Mjölk", "2.000", "l", "ekologisk")
    ]
    assert [row.name for row in shopping.get_list(actor, second).items] == ["Bröd"]


@pytest.mark.integration
def test_an_owner_without_a_list_or_another_owners_list_is_404_and_nothing_is_created() -> None:
    app = webhook_app()
    user_id = owner(app)
    stranger = owner(app, "stranger")
    stranger_list = new_list(app, stranger)
    token = issue(app, user_id).token
    with TestClient(app) as client:
        without_list = client.post(
            SHOPPING_ITEMS, headers=call_headers(token, fresh_key()), json={"name": "Mjölk"}
        )
        other_list = client.post(
            SHOPPING_ITEMS,
            headers=call_headers(token, fresh_key()),
            json={"name": "Mjölk", "list_id": str(stranger_list)},
        )
        unknown_list = client.post(
            SHOPPING_ITEMS,
            headers=call_headers(token, fresh_key()),
            json={"name": "Mjölk", "list_id": str(uuid4())},
        )
    for response in (without_list, other_list, unknown_list):
        assert response.status_code == 404, response.text
        assert response.json()["code"] == "not_found"
    assert app.state.container.shopping.list_lists(owner_actor(user_id)).lists == []
    stranger_actor = owner_actor(stranger)
    assert app.state.container.shopping.get_list(stranger_actor, stranger_list).items == []


@pytest.mark.integration
def test_a_task_gets_its_title_and_an_optional_due_date_in_the_owners_zone() -> None:
    app = webhook_app()
    user_id = owner(app)
    token = issue(app, user_id).token
    zone = app.state.container.settings.owner_zone
    with TestClient(app) as client:
        plain = client.post(TASKS, headers=call_headers(token, fresh_key()), json={"title": "A"})
        dated = client.post(
            TASKS,
            headers=call_headers(token, fresh_key()),
            json={"title": "B", "due": "2030-05-17"},
        )
        timed = client.post(
            TASKS,
            headers=call_headers(token, fresh_key()),
            json={"title": "C", "due": "2030-05-17T08:30:00+00:00"},
        )
    assert [r.status_code for r in (plain, dated, timed)] == [201, 201, 201]
    assert plain.json().keys() == {"task_id"}
    tasks = app.state.container.tasks
    actor = owner_actor(user_id)
    by_title = {
        task.title: task.due_at
        for task in (tasks.get(actor, UUID(r.json()["task_id"])) for r in (plain, dated, timed))
    }
    assert by_title["A"] is None
    assert by_title["B"] == datetime(2030, 5, 17, 23, 59, tzinfo=zone)
    assert by_title["C"] == datetime(2030, 5, 17, 8, 30, tzinfo=UTC)


@pytest.mark.integration
@pytest.mark.parametrize(
    "path,body",
    [
        (SHOPPING_ITEMS, {}),
        (SHOPPING_ITEMS, {"name": ""}),
        (SHOPPING_ITEMS, {"name": "Mjölk", "price": 3}),
        (SHOPPING_ITEMS, {"name": "Mjölk", "quantity": 0}),
        (SHOPPING_ITEMS, {"name": "Mjö\u0000lk"}),
        (SHOPPING_ITEMS, {"name": "x" * 201}),
        (TASKS, {}),
        (TASKS, {"title": "T", "due": "not a date"}),
        (TASKS, {"title": "T", "project_id": str(uuid4())}),
        (TASKS, {"title": "x" * 201}),
    ],
)
def test_an_invalid_body_is_a_closed_422_that_echoes_nothing(
    path: str, body: dict[str, Any]
) -> None:
    app = webhook_app()
    user_id = owner(app)
    new_list(app, user_id)
    token = issue(app, user_id).token
    with TestClient(app) as client:
        response = client.post(path, headers=call_headers(token, fresh_key()), json=body)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "validation_error"
    assert "Mjö" not in response.text
    assert open_items(app, user_id) == 0
    assert task_count(app, user_id) == 0


@pytest.mark.integration
def test_the_body_must_be_json_and_is_capped() -> None:
    app = webhook_app()
    user_id = owner(app)
    token = issue(app, user_id).token
    with TestClient(app) as client:
        text = client.post(
            TASKS,
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": fresh_key()},
            content=b"title=T",
        )
        large = client.post(
            TASKS,
            headers=call_headers(token, fresh_key()),
            content=b'{"title": "' + b"x" * 9000 + b'"}',
        )
    assert text.status_code == 415
    assert large.status_code == 413
    assert task_count(app, user_id) == 0


@pytest.mark.integration
@pytest.mark.parametrize("key", [None, "short", "k" * 129])
def test_a_missing_or_malformed_idempotency_key_is_422(key: str | None) -> None:
    app = webhook_app()
    user_id = owner(app)
    new_list(app, user_id)
    token = issue(app, user_id).token
    with TestClient(app) as client:
        responses = [
            client.post(path, headers=call_headers(token, key), json=body)
            for path, body in ALL_WRITES
        ]
    assert [response.status_code for response in responses] == [422, 422]
    assert nothing_written(app, user_id)


@pytest.mark.integration
def test_a_retry_with_the_same_key_answers_the_first_answer_and_writes_once() -> None:
    app = webhook_app()
    user_id = owner(app)
    new_list(app, user_id)
    token = issue(app, user_id).token
    item_key, task_key = fresh_key(), fresh_key()
    with TestClient(app) as client:
        first = [
            client.post(
                SHOPPING_ITEMS, headers=call_headers(token, item_key), json={"name": "Mjölk"}
            ),
            client.post(TASKS, headers=call_headers(token, task_key), json={"title": "Ring"}),
        ]
        again = [
            client.post(
                SHOPPING_ITEMS, headers=call_headers(token, item_key), json={"name": "Mjölk"}
            ),
            client.post(TASKS, headers=call_headers(token, task_key), json={"title": "Ring"}),
        ]
        reused = [
            client.post(
                SHOPPING_ITEMS, headers=call_headers(token, item_key), json={"name": "Ost"}
            ),
            client.post(TASKS, headers=call_headers(token, task_key), json={"title": "Annat"}),
        ]
    assert [r.status_code for r in first] == [201, 201]
    assert [r.json() for r in again] == [r.json() for r in first]
    for response in reused:
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "conflict"
        assert response.json()["reason"] == "idempotency_key_reused"
    assert open_items(app, user_id) == 1
    assert task_count(app, user_id) == 1


@pytest.mark.integration
def test_each_token_has_its_own_rate_limit_and_a_refused_call_writes_nothing() -> None:
    app = webhook_app()
    user_id = owner(app)
    new_list(app, user_id)
    slow = issue(app, user_id, rate_limit_per_minute=2).token
    other = issue(app, user_id, rate_limit_per_minute=2).token
    with TestClient(app) as client:
        slow_answers = [
            client.post(TASKS, headers=call_headers(slow, fresh_key()), json={"title": f"T{n}"})
            for n in range(3)
        ]
        other_answer = client.post(
            TASKS, headers=call_headers(other, fresh_key()), json={"title": "Other"}
        )
    assert [r.status_code for r in slow_answers] == [201, 201, 429]
    refused = slow_answers[2]
    assert refused.json()["code"] == "rate_limited"
    assert int(refused.headers["retry-after"]) >= 1
    assert other_answer.status_code == 201
    assert task_count(app, user_id) == 3


@pytest.mark.integration
def test_the_writes_are_ordinary_writes_in_the_activity_and_audit_trail() -> None:
    app = webhook_app()
    user_id = owner(app)
    list_id = new_list(app, user_id)
    token = issue(app, user_id).token
    with TestClient(app) as client:
        task = client.post(TASKS, headers=call_headers(token, fresh_key()), json={"title": "Ring"})
        item = client.post(
            SHOPPING_ITEMS, headers=call_headers(token, fresh_key()), json={"name": "Mjölk"}
        )
    task_id, item_id = UUID(task.json()["task_id"]), UUID(item.json()["item_id"])
    assert item.json()["list_id"] == str(list_id)
    with app.state.container.session_factory() as session:
        activity = session.scalar(
            select(func.count()).where(
                ActivityEntryRow.owner_id == user_id, ActivityEntryRow.aggregate_id == task_id
            )
        )
        audited = session.scalar(
            select(func.count()).where(
                AuditEventRow.actor_id == user_id,
                AuditEventRow.event == "shopping.item_added",
                AuditEventRow.target_id == item_id,
            )
        )
    assert activity == 1
    assert audited == 1


@pytest.mark.integration
def test_no_log_record_carries_a_token_a_payload_value_or_an_idempotency_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = webhook_app()
    user_id = owner(app)
    list_name = f"Hemlig lista {uuid4().hex}"
    new_list(app, user_id, list_name)
    issued = issue(app, user_id)
    token = issued.token
    item_name, note, title = (
        f"Hemlig vara {uuid4().hex}",
        f"Hemlig not {uuid4().hex}",
        f"Hemlig titel {uuid4().hex}",
    )
    keys = [f"log-{uuid4().hex}" for _ in range(4)]
    caplog.set_level(logging.INFO)
    # Sidekick's loggers do not propagate to the root logger; listen on them directly.
    watched = [logging.getLogger(name) for name in ("sidekick", "uvicorn", "fastapi")]
    for logger in watched:
        logger.addHandler(caplog.handler)
    try:
        with TestClient(app) as client:
            client.post(
                SHOPPING_ITEMS,
                headers=call_headers(token, keys[0]),
                json={"name": item_name, "note": note},
            )
            client.post(TASKS, headers=call_headers(token, keys[1]), json={"title": title})
            client.post(TASKS, headers=call_headers(token, keys[1]), json={"title": "Annan titel"})
            client.post(TASKS, headers=call_headers(token + "x", keys[2]), json={"title": title})
            client.post(TASKS, headers=call_headers(token, keys[3]), json={"title": title, "x": 1})
    finally:
        for logger in watched:
            logger.removeHandler(caplog.handler)
    operations = {getattr(record, "webhook_operation", None) for record in caplog.records}
    assert {"shopping.item_add", "task.create"} <= operations
    token_ids = {getattr(record, "webhook_token_id", None) for record in caplog.records}
    assert str(issued.record.id) in token_ids
    secrets = (
        list_name,
        item_name,
        note,
        title,
        "Annan titel",
        token,
        issued.record.token_prefix,
        *keys,
    )
    for record in caplog.records:
        rendered = f"{record.getMessage()} {record.__dict__}"
        for secret in secrets:
            assert secret not in rendered, (record.name, record.getMessage())
