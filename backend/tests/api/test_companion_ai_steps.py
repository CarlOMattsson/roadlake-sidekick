"""`/companion/v1/tasks/{id}/steps` tells an AI Step from an owner Step and says where it stands.

The phone only reads: `performer` and `ai_status` are fields of the Step list, which needs no new
capability, and nothing on the route starts, approves or reviews a run.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sidekick.shared.types import Actor
from sidekick.work.domain.ai_runs import AiRunResult, AiUsage
from sidekick.work.domain.ai_spec import ResultFormat
from tests.support.ai_steps import ai_item, approve, key, new_task, plan
from tests.support.companion import bearer, companion_app, owner, owner_actor, paired_token


def listed_steps(app: FastAPI, user_id: UUID, task_id: UUID) -> list[dict[str, Any]]:
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        response = client.get(f"/companion/v1/tasks/{task_id}/steps", headers=bearer(token))
    assert response.status_code == 200
    return response.json()["items"]


def started_with_result(app: FastAPI, actor: Actor, step_id: UUID) -> None:
    """Start the step and report a result, which leaves it waiting for the owner's review."""

    runs = app.state.container.ai_runs
    started = runs.start_step(actor, step_id, idempotency_key=key())
    runs.report(
        actor,
        started.run.id,
        run_version=started.run.version,
        outcome="result",
        idempotency_key=key(),
        usage=AiUsage(),
        result=AiRunResult(format=ResultFormat.TEXT, text="Open nine to six.", summary="Found"),
    )


@pytest.mark.integration
def test_a_task_without_ai_steps_lists_owner_steps_with_no_ai_status() -> None:
    app = companion_app()
    user_id = owner(app)
    actor = owner_actor(user_id)
    task = new_task(app.state.container, actor)
    app.state.container.steps.create_step(actor, task.id, title="Buy stamps", idempotency_key=key())

    items = listed_steps(app, user_id, task.id)

    assert [(item["performer"], item["ai_status"]) for item in items] == [("owner", None)]


@pytest.mark.integration
def test_ai_steps_list_their_performer_and_where_each_stands() -> None:
    app = companion_app()
    user_id = owner(app)
    actor = owner_actor(user_id)
    container = app.state.container
    task = new_task(container, actor)
    owner_step = container.steps.create_step(
        actor, task.id, title="Post the letter", idempotency_key=key()
    )
    view = plan(container, actor, [ai_item("Look it up"), ai_item("Draft the note")], task=task)
    view = approve(container, actor, view)
    started_with_result(app, actor, view.steps[0].step.id)

    items = listed_steps(app, user_id, task.id)

    by_title = {item["title"]: (item["performer"], item["ai_status"]) for item in items}
    assert by_title == {
        "Look it up": ("ai", "to_review"),
        "Draft the note": ("ai", "waiting"),
        owner_step.title: ("owner", None),
    }
