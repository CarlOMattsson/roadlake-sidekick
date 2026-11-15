"""`/companion/v1/` Work writes (ADR-005): create and edit a Task, change a Project's title or
status. Each route is the MCP tool's use case under `companion:work:write`; it is refused for an
unauthenticated, wrongly scoped or foreign caller before anything changes, and a repeated
idempotency key replays the stored result."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sidekick.shared.auth import TOKEN_SCOPES
from tests.support.companion import (
    bearer,
    companion_app,
    create_task,
    owner,
    owner_actor,
    paired_token,
)
from tests.support.companion_work import SECRET_NAMES, seed_work

READ = {"companion:tasks:read"}
WRITE_ONLY = {"companion:work:write"}
FULL = {"companion:tasks:read", "companion:work:write"}
TASKS = "/companion/v1/tasks"
NEW_TITLE = "Boka möte med revisorn"
KEY = "work-write-key-0001"


def headers(token: str, key: str = KEY) -> dict[str, str]:
    return {**bearer(token), "Idempotency-Key": key}


def get_task(app: FastAPI, user_id: UUID, task_id: UUID) -> Any:
    return app.state.container.tasks.get(owner_actor(user_id), task_id)


def get_project(app: FastAPI, user_id: UUID, project_id: UUID) -> Any:
    return app.state.container.projects.get(owner_actor(user_id), project_id)


def assert_problem(response: Any, status: int, code: str, reason: str | None = None) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == code
    assert body["api_version"] == "companion.v1"
    if reason is not None:
        assert body["reason"] == reason
    for secret in (NEW_TITLE, *SECRET_NAMES.values()):
        assert secret not in response.text


@pytest.mark.integration
def test_a_task_is_created_with_a_due_date_and_a_project_through_the_use_case() -> None:
    app = companion_app()
    user_id = owner(app)
    work = seed_work(app, user_id)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        created = client.post(
            TASKS,
            headers=headers(token),
            json={
                "title": NEW_TITLE,
                "due_at": "2026-12-01",
                "project_id": str(work.project.id),
                "priority": "high",
            },
        )
        assert created.status_code == 200, created.text
        task = created.json()["task"]
        assert task["title"] == NEW_TITLE
        assert task["project_id"] == str(work.project.id)
        assert task["priority"] == "high"
        # A bare date is the end of that day in the owner's zone, as for `create_task`.
        assert datetime.fromisoformat(task["due_at"]).astimezone(UTC).date().isoformat() in {
            "2026-12-01",
            "2026-11-30",
        }

        replay = client.post(
            TASKS,
            headers=headers(token),
            json={
                "title": NEW_TITLE,
                "due_at": "2026-12-01",
                "project_id": str(work.project.id),
                "priority": "high",
            },
        )
        assert replay.status_code == 200
        assert replay.json()["task"]["id"] == task["id"]

        in_process = client.post(
            TASKS,
            headers=headers(token, "work-write-key-0003"),
            json={"title": "I processen", "process_id": str(work.process.id)},
        )
        assert in_process.json()["task"]["process_id"] == str(work.process.id)
        bare = client.post(
            TASKS, headers=headers(token, "work-write-key-0002"), json={"title": "x"}
        )
        assert bare.json()["task"]["project_id"] is None
        assert bare.json()["task"]["priority"] == "normal"


@pytest.mark.integration
def test_a_task_is_edited_field_by_field_at_its_version() -> None:
    app = companion_app()
    user_id = owner(app)
    work = seed_work(app, user_id)
    task = create_task(app, user_id, title="Gammal titel")
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        path = f"{TASKS}/{task.id}/update"
        renamed = client.post(
            path,
            headers=headers(token),
            json={"version": task.version, "title": NEW_TITLE, "due_at": "2026-12-24"},
        )
        assert renamed.status_code == 200, renamed.text
        body = renamed.json()["task"]
        assert body["title"] == NEW_TITLE and body["due_at"] is not None
        assert body["version"] == task.version + 1

        moved = client.post(
            path,
            headers=headers(token, "work-write-key-0002"),
            json={"version": body["version"], "project_id": str(work.project.id)},
        )
        assert moved.json()["task"]["project_id"] == str(work.project.id)
        assert moved.json()["task"]["title"] == NEW_TITLE

        cleared = client.post(
            path,
            headers=headers(token, "work-write-key-0003"),
            json={"version": moved.json()["task"]["version"], "due_at": None, "project_id": None},
        )
        assert cleared.json()["task"]["due_at"] is None
        assert cleared.json()["task"]["project_id"] is None

        stale = client.post(
            path, headers=headers(token, "work-write-key-0004"), json={"version": 1, "title": "Sen"}
        )
        assert_problem(stale, 409, "conflict", "stale_version")
    assert get_task(app, user_id, task.id).title == NEW_TITLE


@pytest.mark.integration
def test_a_project_changes_its_title_and_status_and_nothing_else() -> None:
    app = companion_app()
    user_id = owner(app)
    work = seed_work(app, user_id)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        path = f"/companion/v1/projects/{work.project.id}/update"
        done = client.post(
            path,
            headers=headers(token),
            json={
                "version": work.project.version,
                "title": "Nytt namn",
                "status": "paused",
                "description": "Ny beskrivning",
                "target_date": "2027-01-31",
            },
        )
        assert done.status_code == 200, done.text
        project = done.json()["project"]
        assert project["title"] == "Nytt namn" and project["status"] == "paused"
        assert project["description"] == "Ny beskrivning"
        assert project["target_date"] == "2027-01-31"
        assert project["domain_id"] == str(work.domain.id)
        for forbidden in ({"domain_id": str(uuid4())}, {"tags": ["x"]}, {"status": None}):
            refused = client.post(
                path,
                headers=headers(token, "work-write-key-0002"),
                json={"version": project["version"], **forbidden},
            )
            assert_problem(refused, 422, "validation_error")
        cleared = client.post(
            path,
            headers=headers(token, "work-write-key-0003"),
            json={"version": project["version"], "description": None, "target_date": None},
        )
        assert cleared.json()["project"]["description"] is None
        assert cleared.json()["project"]["target_date"] is None
    assert get_project(app, user_id, work.project.id).title == "Nytt namn"


@pytest.mark.integration
@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("create", {"title": NEW_TITLE}),
        ("update-task", {"version": 1, "title": NEW_TITLE}),
        ("update-project", {"version": 1, "title": NEW_TITLE}),
    ],
)
def test_the_writes_are_refused_before_anything_changes(path: str, body: dict[str, Any]) -> None:
    app = companion_app()
    user_id = owner(app)
    stranger = owner(app, "annan")
    work = seed_work(app, stranger, {key: f"Annans {key}" for key in SECRET_NAMES})
    task = create_task(app, user_id, title="Min uppgift")
    urls = {
        "create": TASKS,
        "update-task": f"{TASKS}/{task.id}/update",
        "update-project": f"/companion/v1/projects/{work.project.id}/update",
    }
    url = urls[path]
    pat = app.state.container.auth.create_personal_token(user_id, "mcp", TOKEN_SCOPES)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        reader = paired_token(client, app, user_id, scopes=READ)
        writer = paired_token(client, app, user_id, scopes=WRITE_ONLY)

        assert_problem(
            client.post(url, headers={"Idempotency-Key": KEY}, json=body), 401, "unauthorized"
        )
        for broken in ("rsc_" + "x" * 40, pat):
            assert_problem(
                client.post(url, headers=headers(broken), json=body), 401, "unauthorized"
            )
        # No capability, or the write capability without the read one the answer needs.
        for weak in (reader, writer):
            denied = client.post(url, headers=headers(weak), json=body)
            assert_problem(denied, 403, "forbidden", "capability_missing")
        no_key = client.post(url, headers=bearer(token), json=body)
        assert_problem(no_key, 422, "validation_error")
        assert client.get(url, headers=bearer(token)).status_code == 405
        # The caller's own credential cannot reach another owner's Project.
        if path == "update-project":
            full = paired_token(client, app, user_id, scopes=FULL)
            assert_problem(client.post(url, headers=headers(full), json=body), 404, "not_found")

    assert get_task(app, user_id, task.id).title == "Min uppgift"


@pytest.mark.integration
@pytest.mark.parametrize(
    "body",
    [
        {},
        {"title": ""},
        {"title": "x" * 201},
        {"title": "ok", "status": "done"},
        {"title": "ok", "unknown": 1},
        {"title": "ok", "due_at": "not a date"},
        {"title": "ok", "priority": "urgent"},
        {"title": "Bild ![x](data:image/png;base64,AAAA)"},
    ],
)
def test_a_create_body_that_is_not_valid_is_a_plain_422_that_echoes_nothing(
    body: dict[str, Any],
) -> None:
    app = companion_app()
    user_id = owner(app)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        refused = client.post(TASKS, headers=headers(token), json=body)
        assert_problem(refused, 422, "validation_error")
        assert "not a date" not in refused.text and "unknown" not in refused.text


@pytest.mark.integration
@pytest.mark.parametrize(
    "body",
    [
        {"version": 1},
        {"version": 0, "title": "ok"},
        {"version": 1, "title": None},
        {"version": 1, "priority": None},
        {"version": 1, "status": "done"},
        {"title": "ok"},
    ],
)
def test_an_update_body_needs_a_version_and_a_change_that_can_be_applied(
    body: dict[str, Any],
) -> None:
    app = companion_app()
    user_id = owner(app)
    task = create_task(app, user_id)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        refused = client.post(f"{TASKS}/{task.id}/update", headers=headers(token), json=body)
        assert_problem(refused, 422, "validation_error")
    assert get_task(app, user_id, task.id).version == task.version


@pytest.mark.integration
def test_no_log_record_carries_a_title_or_an_id_for_the_work_writes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = companion_app()
    user_id = owner(app)
    with caplog.at_level(logging.DEBUG), TestClient(app) as client:
        token = paired_token(client, app, user_id)
        created = client.post(TASKS, headers=headers(token), json={"title": NEW_TITLE})
        task_id = created.json()["task"]["id"]
        client.post(
            f"{TASKS}/{task_id}/update",
            headers=headers(token, "work-write-key-0002"),
            json={"version": 1, "title": "Ändrad-hemlig-titel"},
        )
    logged = "\n".join(record.getMessage() + str(record.__dict__) for record in caplog.records)
    assert NEW_TITLE not in logged
    assert "Ändrad-hemlig-titel" not in logged
    assert task_id not in logged
