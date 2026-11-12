"""`/companion/v1/` Arbete routes (ADR-005): the hierarchy, a Project (and its Tasks), a
Domain, a Process, and the tick and undo of a Step. Each route answers exactly the MCP tool's
structured content through the same use case, and is refused for an unauthenticated, wrongly
scoped or foreign caller before anything changes."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastmcp import Client

from sidekick.mcp.server import create_mcp_server
from sidekick.shared.auth import TOKEN_SCOPES
from sidekick.shared.types import MAX_CURSOR_LENGTH, CursorCodec
from tests.support.companion import (
    bearer,
    companion_app,
    create_task,
    owner,
    owner_actor,
    paired_token,
)
from tests.support.companion_work import (
    SECRET_NAMES,
    Work,
    seed_work,
)

READ = {"companion:tasks:read"}
COMPLETE = {"companion:tasks:complete"}
PUSH = {"companion:push"}

STRANGER_NAMES = {
    "domain": "Annans domän Alfa",
    "process": "Annans process Beta",
    "project": "Annans projekt Gamma",
    "task": "Annans uppgift Delta",
    "step": "Annans steg Epsilon",
}


def make_step(
    app: FastAPI,
    user_id: UUID,
    *,
    done: bool = False,
    title: str = SECRET_NAMES["step"],
) -> Any:
    """A fresh Step on a fresh Task; completed through the use case when `done`."""

    container = app.state.container
    actor = owner_actor(user_id)
    task = create_task(app, user_id, title=SECRET_NAMES["task"])
    step = container.steps.create_step(
        actor, task.id, title=title, idempotency_key=f"step-{uuid4()}"
    )
    if done:
        step = container.steps.complete_step(
            actor, step.id, version=step.version, idempotency_key=f"done-{uuid4()}"
        )
    return step


def step_state(app: FastAPI, user_id: UUID, step_id: UUID) -> tuple[str, int]:
    step = app.state.container.steps.get_step(owner_actor(user_id), step_id)
    return step.status.value, step.version


def read_paths(work: Work) -> dict[str, str]:
    return {
        "hierarchy": "/companion/v1/work/hierarchy",
        "project": f"/companion/v1/projects/{work.project.id}",
        "project_tasks": f"/companion/v1/projects/{work.project.id}/tasks",
        "domain": f"/companion/v1/domains/{work.domain.id}",
        "process": f"/companion/v1/processes/{work.process.id}",
    }


def without_calculated_at(structured: dict[str, Any]) -> dict[str, Any]:
    project = dict(structured["project"])
    totals = {k: v for k, v in project["estimate_totals"].items() if k != "calculated_at"}
    return {**structured, "project": {**project, "estimate_totals": totals}}


def assert_problem(response: Any, status: int, code: str, reason: str | None = None) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == code
    assert body["api_version"] == "companion.v1"
    assert body["correlation_id"]
    if reason is not None:
        assert body["reason"] == reason
    for secret in (*SECRET_NAMES.values(), *STRANGER_NAMES.values()):
        assert secret not in response.text


# --- Reads ------------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_work_reads_equal_the_mcp_structured_content() -> None:
    app = companion_app()
    user_id = owner(app)
    actor = owner_actor(user_id)
    work = seed_work(app, user_id)
    for index in range(3):
        create_task(app, user_id, title=f"Fler {index}", project_id=work.project.id)
    create_task(app, user_id, title="Utanför projektet")
    mcp = create_mcp_server(app.state.container, actor_provider=lambda: actor, enable_auth=False)
    async with Client(mcp) as mcp_client:
        hierarchy = await mcp_client.call_tool("get_work_hierarchy", {})
        hierarchy_cut = await mcp_client.call_tool("get_work_hierarchy", {"limit": 1})
        hierarchy_tasks = await mcp_client.call_tool("get_work_hierarchy", {"include_tasks": True})
        hierarchy_process = await mcp_client.call_tool(
            "get_work_hierarchy",
            {"include_tasks": True, "process_id": str(work.process.id)},
        )
        project = await mcp_client.call_tool("get_project", {"project_id": str(work.project.id)})
        domain = await mcp_client.call_tool("get_domain", {"domain_id": str(work.domain.id)})
        process = await mcp_client.call_tool("get_process", {"process_id": str(work.process.id)})
        first = await mcp_client.call_tool(
            "list_tasks", {"project_id": str(work.project.id), "limit": 2}
        )
        second = await mcp_client.call_tool(
            "list_tasks",
            {
                "project_id": str(work.project.id),
                "limit": 2,
                "cursor": first.structured_content["next_cursor"],
            },
        )
        default_page = await mcp_client.call_tool(
            "list_tasks", {"project_id": str(work.project.id)}
        )
    assert hierarchy_cut.structured_content["truncated"] is True
    assert hierarchy.structured_content["truncated"] is False
    assert "tasks" not in hierarchy.structured_content
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        headers = bearer(token)
        paths = read_paths(work)
        assert client.get(paths["hierarchy"], headers=headers).json() == (
            hierarchy.structured_content
        )
        assert client.get(f"{paths['hierarchy']}?limit=1", headers=headers).json() == (
            hierarchy_cut.structured_content
        )
        assert client.get(f"{paths['hierarchy']}?include_tasks=true", headers=headers).json() == (
            hierarchy_tasks.structured_content
        )
        assert client.get(
            paths["hierarchy"],
            params={"include_tasks": "true", "process_id": str(work.process.id)},
            headers=headers,
        ).json() == (hierarchy_process.structured_content)
        # `calculated_at` is the moment each read was made; everything else is equal.
        assert without_calculated_at(client.get(paths["project"], headers=headers).json()) == (
            without_calculated_at(project.structured_content)
        )
        assert client.get(paths["domain"], headers=headers).json() == domain.structured_content
        assert client.get(paths["process"], headers=headers).json() == (process.structured_content)
        page = client.get(f"{paths['project_tasks']}?limit=2", headers=headers)
        assert page.json() == first.structured_content
        follow = client.get(
            paths["project_tasks"],
            params={"limit": 2, "cursor": first.structured_content["next_cursor"]},
            headers=headers,
        )
        assert follow.json() == second.structured_content
        assert client.get(paths["project_tasks"], headers=headers).json() == (
            default_page.structured_content
        )
    assert project.structured_content["project"]["title"] == SECRET_NAMES["project"]
    assert len(default_page.structured_content["tasks"]) == 4
    assert len(first.structured_content["tasks"]) == 2


@pytest.mark.integration
@pytest.mark.parametrize("route", ["hierarchy", "project", "project_tasks", "domain", "process"])
def test_work_reads_need_a_companion_credential_with_the_read_capability(route: str) -> None:
    app = companion_app()
    user_id = owner(app)
    work = seed_work(app, user_id)
    path = read_paths(work)[route]
    pat = app.state.container.auth.create_personal_token(user_id, "mcp", TOKEN_SCOPES)
    with TestClient(app) as client:
        no_credential = client.get(path)
        assert_problem(no_credential, 401, "unauthorized")
        assert "Bearer" in no_credential.headers["www-authenticate"]
        for broken in ("rsc_" + "x" * 40, "x" * 300, pat):
            assert_problem(client.get(path, headers=bearer(broken)), 401, "unauthorized")
        # A malformed scheme is no credential either.
        assert client.get(path, headers={"Authorization": "Basic abc"}).status_code == 401
        for scopes in (PUSH, COMPLETE, PUSH | COMPLETE):
            token = paired_token(client, app, user_id, scopes=scopes)
            assert_problem(
                client.get(path, headers=bearer(token)), 403, "forbidden", "capability_missing"
            )
        reader = paired_token(client, app, user_id, scopes=READ)
        allowed = client.get(path, headers=bearer(reader))
        assert allowed.status_code == 200
        assert allowed.headers["cache-control"] == "no-store"
        # Reading is the only verb these paths take.
        assert client.post(path, headers=bearer(reader)).status_code == 405


@pytest.mark.integration
@pytest.mark.parametrize("route", ["project", "project_tasks", "domain", "process"])
def test_work_reads_of_another_owners_or_unknown_records_are_404_and_never_echoed(
    route: str,
) -> None:
    app = companion_app()
    user_id = owner(app)
    stranger = owner(app, "annan")
    mine = seed_work(app, user_id)
    foreign = seed_work(app, stranger, STRANGER_NAMES)
    create_task(app, stranger, title="Främmande i annans projekt", project_id=foreign.project.id)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        foreign_path = read_paths(foreign)[route]
        unknown_path = {
            "project": f"/companion/v1/projects/{uuid4()}",
            "project_tasks": f"/companion/v1/projects/{uuid4()}/tasks",
            "domain": f"/companion/v1/domains/{uuid4()}",
            "process": f"/companion/v1/processes/{uuid4()}",
        }[route]
        for path in (foreign_path, unknown_path):
            denied = client.get(path, headers=bearer(token))
            assert_problem(denied, 404, "not_found")
            assert "Främmande" not in denied.text
        # A project of mine with no tasks is an empty page, not a 404.
        assert client.get(read_paths(mine)[route], headers=bearer(token)).status_code == 200
        stranger_token = paired_token(client, app, stranger)
        assert client.get(foreign_path, headers=bearer(stranger_token)).status_code == 200
        # One owner's credential never opens the other's record, and reading changed nothing.
        assert client.get(read_paths(mine)[route], headers=bearer(stranger_token)).status_code == (
            404
        )


@pytest.mark.integration
def test_the_hierarchy_holds_only_the_owners_nodes() -> None:
    app = companion_app()
    user_id = owner(app)
    stranger = owner(app, "annan")
    mine = seed_work(app, user_id)
    seed_work(app, stranger, STRANGER_NAMES)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        response = client.get("/companion/v1/work/hierarchy", headers=bearer(token))
    assert response.status_code == 200
    ids = {node["id"] for node in response.json()["nodes"]}
    assert ids == {str(mine.domain.id), str(mine.process.id), str(mine.project.id)}
    assert response.json()["truncated"] is False
    assert all(name not in response.text for name in STRANGER_NAMES.values())


@pytest.mark.integration
def test_the_hierarchy_counts_tasks_and_narrows_to_a_process() -> None:
    app = companion_app()
    user_id = owner(app)
    work = seed_work(app, user_id)
    in_process = create_task(app, user_id, title="I processen", process_id=work.process.id)
    with TestClient(app) as client:
        headers = bearer(paired_token(client, app, user_id))
        plain = client.get("/companion/v1/work/hierarchy", headers=headers)
        everything = client.get("/companion/v1/work/hierarchy?include_tasks=true", headers=headers)
        narrowed = client.get(
            "/companion/v1/work/hierarchy",
            params={"include_tasks": "true", "process_id": str(work.process.id)},
            headers=headers,
        )
    assert "tasks" not in plain.json()
    assert {task["id"] for task in everything.json()["tasks"]} == {
        str(work.task.id),
        str(in_process.id),
    }
    assert [task["id"] for task in narrowed.json()["tasks"]] == [str(in_process.id)]
    assert narrowed.json()["tasks"][0]["parent_id"] == str(work.process.id)


@pytest.mark.integration
def test_the_hierarchy_process_filter_is_owner_scoped_and_needs_include_tasks() -> None:
    app = companion_app()
    user_id = owner(app)
    stranger = owner(app, "annan")
    mine = seed_work(app, user_id)
    foreign = seed_work(app, stranger, STRANGER_NAMES)
    create_task(app, stranger, title="Främmande i annans process", process_id=foreign.process.id)
    with TestClient(app) as client:
        headers = bearer(paired_token(client, app, user_id))
        for process_id in (foreign.process.id, uuid4()):
            denied = client.get(
                "/companion/v1/work/hierarchy",
                params={"include_tasks": "true", "process_id": str(process_id)},
                headers=headers,
            )
            assert_problem(denied, 404, "not_found")
            assert "Främmande" not in denied.text
        # Without include_tasks the filter means nothing and is refused, not ignored.
        refused = client.get(
            "/companion/v1/work/hierarchy",
            params={"process_id": str(mine.process.id)},
            headers=headers,
        )
        assert refused.status_code == 400
        assert refused.json()["code"] == "bad_request"
        assert_problem(
            client.get(
                "/companion/v1/work/hierarchy",
                params={"include_tasks": "true", "process_id": "not-a-uuid"},
                headers=headers,
            ),
            422,
            "validation_error",
        )


@pytest.mark.integration
def test_a_project_lists_its_tasks_page_by_page_with_a_cursor() -> None:
    app = companion_app()
    user_id = owner(app)
    work = seed_work(app, user_id)
    other = seed_work(app, user_id, STRANGER_NAMES)
    wanted = {str(work.task.id)}
    for index in range(4):
        wanted.add(
            str(create_task(app, user_id, title=f"Sida {index}", project_id=work.project.id).id)
        )
    path = f"/companion/v1/projects/{work.project.id}/tasks"
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        seen: list[str] = []
        cursor: str | None = None
        pages = 0
        while True:
            params: dict[str, Any] = {"limit": 2}
            if cursor:
                params["cursor"] = cursor
            response = client.get(path, params=params, headers=bearer(token))
            assert response.status_code == 200
            body = response.json()
            assert len(body["tasks"]) <= 2
            seen.extend(task["id"] for task in body["tasks"])
            pages += 1
            cursor = body["next_cursor"]
            if cursor is None:
                break
            assert pages < 10
        other_page = client.get(
            f"/companion/v1/projects/{other.project.id}/tasks", headers=bearer(token)
        )
    assert pages == 3
    assert len(seen) == len(set(seen)) == 5
    assert set(seen) == wanted
    assert [task["id"] for task in other_page.json()["tasks"]] == [str(other.task.id)]


@pytest.mark.integration
def test_a_task_lists_its_steps_page_by_page_with_a_cursor() -> None:
    app = companion_app()
    user_id = owner(app)
    work = seed_work(app, user_id)
    actor = owner_actor(user_id)
    wanted = [str(work.step.id)]
    for index in range(4):
        step = app.state.container.steps.create_step(
            actor, work.task.id, title=f"Steg {index}", idempotency_key=f"step-{uuid4()}"
        )
        wanted.append(str(step.id))
    path = f"/companion/v1/tasks/{work.task.id}/steps"
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        seen: list[str] = []
        cursor: str | None = None
        pages = 0
        while True:
            params: dict[str, Any] = {"limit": 2}
            if cursor:
                params["cursor"] = cursor
            response = client.get(path, params=params, headers=bearer(token))
            assert response.status_code == 200
            body = response.json()
            assert len(body["items"]) <= 2
            seen.extend(step["id"] for step in body["items"])
            pages += 1
            cursor = body["next_cursor"]
            if cursor is None:
                break
            assert pages < 10
        bad = client.get(path, params={"cursor": "not-a-cursor"}, headers=bearer(token))
    assert pages == 3
    assert seen == wanted
    assert bad.status_code == 400


@pytest.mark.integration
def test_a_task_with_more_than_100_steps_is_read_to_the_end_with_the_cursor() -> None:
    app = companion_app()
    user_id = owner(app)
    work = seed_work(app, user_id)
    actor = owner_actor(user_id)
    wanted = [str(work.step.id)]
    for index in range(124):
        step = app.state.container.steps.create_step(
            actor, work.task.id, title=f"Steg {index}", idempotency_key=f"step-{uuid4()}"
        )
        wanted.append(str(step.id))
    path = f"/companion/v1/tasks/{work.task.id}/steps"
    with TestClient(app) as client:
        headers = bearer(paired_token(client, app, user_id))
        first = client.get(path, headers=headers).json()
        seen = [step["id"] for step in first["items"]]
        cursor = first["next_cursor"]
        pages = 1
        while cursor is not None:
            body = client.get(path, params={"cursor": cursor}, headers=headers).json()
            seen.extend(step["id"] for step in body["items"])
            cursor = body["next_cursor"]
            pages += 1
            assert pages < 5
    assert len(first["items"]) == 100
    assert pages == 2
    assert seen == wanted


@pytest.mark.integration
def test_work_read_query_bounds_are_the_mcp_bounds() -> None:
    app = companion_app()
    user_id = owner(app)
    work = seed_work(app, user_id)
    tasks_path = read_paths(work)["project_tasks"]
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        headers = bearer(token)
        for query in ("limit=0", "limit=101", "limit=x", "cursor=" + "c" * (MAX_CURSOR_LENGTH + 1)):
            response = client.get(f"{tasks_path}?{query}", headers=headers)
            assert_problem(response, 422, "validation_error")
        for query in ("limit=0", "limit=101", "limit=x"):
            response = client.get(f"/companion/v1/work/hierarchy?{query}", headers=headers)
            assert_problem(response, 422, "validation_error")
        assert client.get(f"{tasks_path}?limit=100", headers=headers).status_code == 200
        assert (
            client.get("/companion/v1/work/hierarchy?limit=100", headers=headers).status_code == 200
        )
        assert client.get(f"{tasks_path}?limit=1", headers=headers).status_code == 200
        bad_cursor = client.get(f"{tasks_path}?cursor=nope", headers=headers)
        assert bad_cursor.status_code in {400, 422}
        assert "projektuppgift" not in bad_cursor.text
        # A well-formed cursor signed with another key (for instance from before a restart
        # with a per-process key) is a polite 400, never a 500.
        foreign = CursorCodec("another-instance-key-" + "k" * 16).encode(user_id, 1, "tasks")
        stale = client.get(f"{tasks_path}?cursor={foreign}", headers=headers)
        assert stale.status_code == 400
        assert stale.json()["code"] == "bad_request"
        # The route takes the Project from its path only: other list filters are ignored.
        extra = client.get(
            f"{tasks_path}?process_id={uuid4()}&status=completed&unsorted=true", headers=headers
        )
        assert extra.status_code == 200
        assert [task["id"] for task in extra.json()["tasks"]] == [str(work.task.id)]
        # An id that is not a UUID never reaches a use case.
        not_a_uuid = client.get("/companion/v1/projects/not-a-uuid", headers=headers)
        assert not_a_uuid.status_code in {404, 422}


# --- Step ticks -------------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize("action", ["complete", "reopen"])
def test_step_posts_are_refused_before_anything_changes(action: str) -> None:
    app = companion_app()
    user_id = owner(app)
    stranger = owner(app, "annan")
    done = action == "reopen"
    mine = make_step(app, user_id, done=done)
    foreign = make_step(app, stranger, done=done, title=STRANGER_NAMES["step"])
    before = step_state(app, user_id, mine.id)
    foreign_before = step_state(app, stranger, foreign.id)
    pat = app.state.container.auth.create_personal_token(user_id, "mcp", TOKEN_SCOPES)
    path = f"/companion/v1/steps/{mine.id}/{action}"
    body = {"version": before[1]}
    key = {"Idempotency-Key": f"refused-{action}-0001"}
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        reader = paired_token(client, app, user_id, scopes=READ)
        push_only = paired_token(client, app, user_id, scopes=PUSH)
        stranger_token = paired_token(client, app, stranger)

        assert_problem(client.post(path, headers=key, json=body), 401, "unauthorized")
        for broken in ("rsc_" + "x" * 40, "x" * 300, pat):
            refused = client.post(path, headers={**bearer(broken), **key}, json=body)
            assert_problem(refused, 401, "unauthorized")
        for weak in (reader, push_only):
            denied = client.post(path, headers={**bearer(weak), **key}, json=body)
            assert_problem(denied, 403, "forbidden", "capability_missing")

        # Another owner's Step is a missing one; so is an unknown id. Nothing is revealed.
        for step_id in (foreign.id, uuid4()):
            missing = client.post(
                f"/companion/v1/steps/{step_id}/{action}",
                headers={**bearer(token), **key},
                json={"version": foreign_before[1]},
            )
            assert_problem(missing, 404, "not_found")
        # ... and the stranger's own credential cannot reach mine.
        crossed = client.post(path, headers={**bearer(stranger_token), **key}, json=body)
        assert_problem(crossed, 404, "not_found")

        no_key = client.post(path, headers=bearer(token), json=body)
        assert_problem(no_key, 422, "validation_error")
        short_key = client.post(
            path, headers={**bearer(token), "Idempotency-Key": "short"}, json=body
        )
        assert_problem(short_key, 422, "validation_error")

        stale = client.post(path, headers={**bearer(token), **key}, json={"version": before[1] + 1})
        assert_problem(stale, 409, "conflict")
        zero = client.post(path, headers={**bearer(token), **key}, json={"version": 0})
        assert_problem(zero, 422, "validation_error")

        assert client.get(path, headers=bearer(token)).status_code == 405

    assert step_state(app, user_id, mine.id) == before
    assert step_state(app, stranger, foreign.id) == foreign_before


@pytest.mark.integration
@pytest.mark.parametrize("action", ["complete", "reopen"])
def test_a_stale_step_version_names_the_stale_version_reason(action: str) -> None:
    app = companion_app()
    user_id = owner(app)
    step = make_step(app, user_id, done=action == "reopen")
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        stale = client.post(
            f"/companion/v1/steps/{step.id}/{action}",
            headers={**bearer(token), "Idempotency-Key": f"stale-{action}-0001"},
            json={"version": step.version + 1},
        )
    assert_problem(stale, 409, "conflict", "stale_version")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_step_complete_is_idempotent_versioned_and_shares_the_mcp_use_case() -> None:
    app = companion_app()
    user_id = owner(app)
    actor = owner_actor(user_id)
    step = make_step(app, user_id)
    stale = make_step(app, user_id, title="Gammalt steg")
    path = f"/companion/v1/steps/{step.id}/complete"
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        headers = {**bearer(token), "Idempotency-Key": "step-complete-0001"}
        first = client.post(path, headers=headers, json={"version": step.version})
        replay = client.post(path, headers=headers, json={"version": step.version})
        other_body = client.post(path, headers=headers, json={"version": step.version + 1})
        conflict = client.post(
            f"/companion/v1/steps/{stale.id}/complete",
            headers={**bearer(token), "Idempotency-Key": "step-complete-0002"},
            json={"version": stale.version + 1},
        )
    assert first.status_code == 200
    assert first.headers["cache-control"] == "no-store"
    assert first.json()["step"]["status"] == "completed"
    assert first.json()["step"]["id"] == str(step.id)
    assert replay.status_code == 200 and replay.json() == first.json()
    assert_problem(other_body, 409, "conflict", "idempotency_key_reused")
    assert_problem(conflict, 409, "conflict")
    assert "Gammalt steg" not in conflict.text
    # One transition only: the replay and the refused reuse did not tick it again.
    assert step_state(app, user_id, step.id) == ("completed", step.version + 1)
    assert step_state(app, user_id, stale.id) == ("todo", stale.version)
    mcp = create_mcp_server(app.state.container, actor_provider=lambda: actor, enable_auth=False)
    async with Client(mcp) as mcp_client:
        same = await mcp_client.call_tool(
            "complete_task_step",
            {
                "step_id": str(step.id),
                "version": step.version,
                "idempotency_key": "step-complete-0001",
            },
        )
        fresh = make_step(app, user_id, title="Via MCP")
        via_mcp = await mcp_client.call_tool(
            "complete_task_step",
            {"step_id": str(fresh.id), "version": fresh.version, "idempotency_key": "mcp-0000001"},
        )
    # The MCP tool replays the companion call's durable result: one use case, one record.
    assert same.structured_content == first.json()
    assert step_state(app, user_id, step.id) == ("completed", step.version + 1)
    assert set(via_mcp.structured_content) == set(first.json()) == {"step"}
    assert set(via_mcp.structured_content["step"]) == set(first.json()["step"])


@pytest.mark.asyncio
@pytest.mark.integration
async def test_step_reopen_undoes_only_a_completion_like_update_task_step() -> None:
    app = companion_app()
    user_id = owner(app)
    actor = owner_actor(user_id)
    done = make_step(app, user_id, done=True)
    open_step = make_step(app, user_id, title="Fortfarande öppet")
    open_before = step_state(app, user_id, open_step.id)
    path = f"/companion/v1/steps/{done.id}/reopen"
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        headers = {**bearer(token), "Idempotency-Key": "step-reopen-0001"}
        reopened = client.post(path, headers=headers, json={"version": done.version})
        replay = client.post(path, headers=headers, json={"version": done.version})
        other_body = client.post(path, headers=headers, json={"version": done.version + 3})
        # The Step is open again: a second reopen with a new key is refused, whatever version.
        again = client.post(
            path,
            headers={**bearer(token), "Idempotency-Key": "step-reopen-0002"},
            json={"version": done.version + 1},
        )
        stale_open = client.post(
            path,
            headers={**bearer(token), "Idempotency-Key": "step-reopen-0003"},
            json={"version": done.version},
        )
        not_completed = client.post(
            f"/companion/v1/steps/{open_step.id}/reopen",
            headers={**bearer(token), "Idempotency-Key": "step-reopen-0004"},
            json={"version": open_step.version},
        )
        guessed = client.post(
            f"/companion/v1/steps/{open_step.id}/reopen",
            headers={**bearer(token), "Idempotency-Key": "step-reopen-0005"},
            json={"version": open_step.version + 1},
        )
    assert reopened.status_code == 200
    assert reopened.json()["step"]["status"] == "todo"
    assert reopened.json()["step"]["version"] == done.version + 1
    assert replay.status_code == 200 and replay.json() == reopened.json()
    assert_problem(other_body, 409, "conflict", "idempotency_key_reused")
    for refused in (again, stale_open, not_completed, guessed):
        assert_problem(refused, 409, "conflict", "not_completed")
    assert step_state(app, user_id, done.id) == ("todo", done.version + 1)
    assert step_state(app, user_id, open_step.id) == open_before
    mcp = create_mcp_server(app.state.container, actor_provider=lambda: actor, enable_auth=False)
    async with Client(mcp) as mcp_client:
        same = await mcp_client.call_tool(
            "update_task_step",
            {
                "step_id": str(done.id),
                "version": done.version,
                "idempotency_key": "step-reopen-0001",
                "changes": {"status": "todo"},
            },
        )
    # The same `update_task_step` use case and idempotency record as the MCP undo.
    assert same.structured_content == reopened.json()
    assert step_state(app, user_id, done.id) == ("todo", done.version + 1)


@pytest.mark.integration
def test_a_step_can_be_ticked_and_undone_again_and_each_change_is_one_version() -> None:
    app = companion_app()
    user_id = owner(app)
    step = make_step(app, user_id)
    base = f"/companion/v1/steps/{step.id}"
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        version = step.version
        for round_ in range(2):
            ticked = client.post(
                f"{base}/complete",
                headers={**bearer(token), "Idempotency-Key": f"round-{round_}-complete"},
                json={"version": version},
            )
            assert ticked.json()["step"]["version"] == version + 1
            undone = client.post(
                f"{base}/reopen",
                headers={**bearer(token), "Idempotency-Key": f"round-{round_}-reopen-"},
                json={"version": version + 1},
            )
            assert undone.json()["step"]["status"] == "todo"
            version += 2
    assert step_state(app, user_id, step.id) == ("todo", step.version + 4)


@pytest.mark.integration
def test_a_write_only_device_gets_a_step_receipt_and_a_reader_gets_the_step() -> None:
    app = companion_app()
    user_id = owner(app)
    first = make_step(app, user_id)
    second = make_step(app, user_id, title="Andra steget")
    with TestClient(app) as client:
        writer = paired_token(client, app, user_id, scopes=COMPLETE)
        full = paired_token(client, app, user_id)
        receipt = client.post(
            f"/companion/v1/steps/{first.id}/complete",
            headers={**bearer(writer), "Idempotency-Key": "step-receipt-complete1"},
            json={"version": first.version},
        )
        replay = client.post(
            f"/companion/v1/steps/{first.id}/complete",
            headers={**bearer(writer), "Idempotency-Key": "step-receipt-complete1"},
            json={"version": first.version},
        )
        reopen = client.post(
            f"/companion/v1/steps/{first.id}/reopen",
            headers={**bearer(writer), "Idempotency-Key": "step-receipt-reopen01"},
            json={"version": receipt.json()["version"]},
        )
        wrong = client.post(
            f"/companion/v1/steps/{first.id}/complete",
            headers={**bearer(writer), "Idempotency-Key": "step-receipt-complete2"},
            json={"version": 99},
        )
        wrong_reopen = client.post(
            f"/companion/v1/steps/{second.id}/reopen",
            headers={**bearer(writer), "Idempotency-Key": "step-receipt-reopen02"},
            json={"version": 99},
        )
        whole = client.post(
            f"/companion/v1/steps/{second.id}/complete",
            headers={**bearer(full), "Idempotency-Key": "step-receipt-complete3"},
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
        assert SECRET_NAMES["step"] not in response.text and "Andra" not in response.text
    for response in (wrong, wrong_reopen):
        assert response.status_code == 409
        assert "step" not in response.json()
    for receipt_like in (receipt, replay, reopen):
        assert set(receipt_like.json()) == {"ok", "id", "version", "status"}
    assert whole.status_code == 200
    assert whole.json()["step"]["title"] == "Andra steget"
    assert whole.json()["step"]["status"] == "completed"
    assert "ok" not in whole.json()


@pytest.mark.integration
@pytest.mark.parametrize("action", ["complete", "reopen"])
def test_step_post_bodies_are_capped_and_read_only_after_authentication(
    action: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sidekick.api.companion as companion

    app = companion_app()
    user_id = owner(app)
    step = make_step(app, user_id, done=action == "reopen")
    path = f"/companion/v1/steps/{step.id}/{action}"
    json_type = {"Content-Type": "application/json"}
    oversized = b'{"version": 1, "pad": "' + b"x" * 8000 + b'"}'
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        key = {"Idempotency-Key": f"step-cap-{action}-1"}
        too_big = client.post(
            path, headers={**bearer(token), **key, **json_type}, content=oversized
        )
        assert_problem(too_big, 413, "payload_too_large")

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
                assert_problem(refused, 401, "unauthorized")
        assert reads == []

        for content in (b"not json", b'{"version": "x"}', b'{"version": 1, "extra": 1}', b"{}"):
            bad = client.post(path, headers={**bearer(token), **key, **json_type}, content=content)
            assert_problem(bad, 422, "validation_error")
        wrong_type = client.post(
            path, headers={**bearer(token), **key, "Content-Type": "text/plain"}, content=b"{}"
        )
        assert_problem(wrong_type, 415, "unsupported_media_type")

        ok_body = client.post(
            path, headers={**bearer(token), **key, **json_type}, content=b'{"version": 1}'
        )
        assert ok_body.status_code in {200, 409}
        assert companion.MAX_TASK_BODY_BYTES in reads


# --- Logs -------------------------------------------------------------------------------------


@pytest.mark.integration
def test_no_log_record_carries_a_title_name_token_or_id_for_the_work_routes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = companion_app()
    user_id = owner(app)
    stranger = owner(app, "annan")
    work = seed_work(app, user_id)
    foreign = seed_work(app, stranger, STRANGER_NAMES)
    done = make_step(app, user_id, done=True)
    caplog.set_level(logging.DEBUG)
    watched = [logging.getLogger(name) for name in ("sidekick", "uvicorn", "fastapi", "fastmcp")]
    for logger in watched:
        logger.addHandler(caplog.handler)
    try:
        with TestClient(app) as client:
            token = paired_token(client, app, user_id)
            headers = bearer(token)
            for path in read_paths(work).values():
                client.get(path, headers=headers)
            client.get(read_paths(foreign)["project"], headers=headers)
            client.get(read_paths(foreign)["project_tasks"], headers=headers)
            client.get(f"{read_paths(work)['project_tasks']}?cursor=nope", headers=headers)
            client.get(f"{read_paths(work)['project_tasks']}?limit=0", headers=headers)
            client.get(read_paths(work)["domain"], headers=bearer(token + "x"))
            client.post(
                f"/companion/v1/steps/{work.step.id}/complete",
                headers={**headers, "Idempotency-Key": "log-step-0001"},
                json={"version": work.step.version + 5},
            )
            client.post(
                f"/companion/v1/steps/{work.step.id}/complete",
                headers={**headers, "Idempotency-Key": "log-step-0002"},
                json={"version": work.step.version},
            )
            client.post(
                f"/companion/v1/steps/{work.step.id}/reopen",
                headers={**headers, "Idempotency-Key": "log-step-0003"},
                json={"version": work.step.version},
            )
            client.post(
                f"/companion/v1/steps/{done.id}/reopen",
                headers={**headers, "Idempotency-Key": "log-step-0004"},
                json={"version": done.version},
            )
            client.post(
                f"/companion/v1/steps/{foreign.step.id}/complete",
                headers={**headers, "Idempotency-Key": "log-step-0005"},
                json={"version": foreign.step.version},
            )
    finally:
        for logger in watched:
            logger.removeHandler(caplog.handler)
    records = [record for record in caplog.records if record.name.startswith("sidekick")]
    assert any(record.getMessage() == "companion_request" for record in records)
    forbidden = [
        *SECRET_NAMES.values(),
        *STRANGER_NAMES.values(),
        token,
        "Hemlig",
        "Annans",
        "nope",
        *(
            str(item.id)
            for item in (
                work.domain,
                work.process,
                work.project,
                work.task,
                work.step,
                done,
                foreign.project,
                foreign.step,
            )
        ),
    ]
    server_records = [
        record for record in caplog.records if not record.name.startswith(("httpx", "httpcore"))
    ]
    for record in server_records:
        rendered = f"{record.getMessage()} {record.__dict__}"
        for item in forbidden:
            assert item not in rendered, (record.name, record.getMessage())
