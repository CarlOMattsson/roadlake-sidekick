"""Shared test helpers moved out of `tests/api/test_companion_work.py`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI

from tests.support.companion import (
    create_task,
    owner_actor,
)

SECRET_NAMES = {
    "domain": "Hemlig domän Alfa",
    "process": "Hemlig process Beta",
    "project": "Hemligt projekt Gamma",
    "task": "Hemlig projektuppgift Delta",
    "step": "Hemligt steg Epsilon",
}


@dataclass(frozen=True)
class Work:
    domain: Any
    process: Any
    project: Any
    task: Any
    step: Any


def seed_work(app: FastAPI, user_id: UUID, names: dict[str, str] = SECRET_NAMES) -> Work:
    """A Domain with a Process and a Project, one Task in the Project, and one Step on the Task."""

    container = app.state.container
    actor = owner_actor(user_id)
    domain = container.contexts.create_domain(
        actor, name=names["domain"], description=None, idempotency_key=f"domain-{uuid4()}"
    )
    process = container.contexts.create_process(
        actor,
        domain_id=domain.id,
        name=names["process"],
        description=None,
        idempotency_key=f"process-{uuid4()}",
    )
    project = container.projects.create(
        actor, title=names["project"], domain_id=domain.id, idempotency_key=f"project-{uuid4()}"
    )
    task = create_task(app, user_id, title=names["task"], project_id=project.id)
    step = container.steps.create_step(
        actor, task.id, title=names["step"], idempotency_key=f"step-{uuid4()}"
    )
    return Work(domain, process, project, task, step)
