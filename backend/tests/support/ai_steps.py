"""Helpers the AI Step service tests share: plans, owners, keys and admin reads."""

import itertools
import os
from uuid import UUID

from sqlalchemy import text

from sidekick.api.app import Container, create_container
from sidekick.shared.types import Actor
from sidekick.tasks.domain import Task
from sidekick.work.application.ai_plans import PlanItem
from sidekick.work.application.ai_store import AiPlanView
from sidekick.work.domain.ai_spec import AiStepSpecV1, Performer
from tests.db import _cleanup_factory_for, database_factory
from tests.support.settings import make_settings

SCOPES = frozenset({"tasks:read", "tasks:write", "ai:run"})
GOAL = "Find the opening hours of the pharmacy"

_keys = itertools.count(1)


def key() -> str:
    """A fresh idempotency key."""

    return f"ai-steps-key-{next(_keys)}"


def spec(**changes: object) -> AiStepSpecV1:
    return AiStepSpecV1(goal=GOAL, **changes)  # type: ignore[arg-type]


def ai_item(title: str, ai_spec: AiStepSpecV1 | None = None) -> PlanItem:
    return PlanItem(performer=Performer.AI, title=title, ai_spec=ai_spec or spec())


def container_with(**settings: object) -> Container:
    base = make_settings()
    return create_container(
        base.model_copy(update=settings) if settings else base, database_factory()
    )


def owner_actor(container: Container, login: str = "ai-owner") -> Actor:
    return Actor(container.auth.provision_user(login, "Owner"), SCOPES)


def new_task(container: Container, actor: Actor, title: str = "Pharmacy errand") -> Task:
    return container.tasks.create(actor, title=title, idempotency_key=key())


def plan(
    container: Container,
    actor: Actor,
    items: list[PlanItem],
    *,
    task: Task | None = None,
    correlation_id: str | None = None,
) -> AiPlanView:
    task = task or new_task(container, actor)
    return container.ai_plans.set_plan(
        actor,
        task.id,
        task_version=task.version,
        items=items,
        idempotency_key=key(),
        correlation_id=correlation_id,
    )


def approve(
    container: Container, actor: Actor, view: AiPlanView, correlation_id: str | None = None
) -> AiPlanView:
    return container.ai_plans.approve_plan(
        actor,
        view.task.id,
        digest=view.digest,
        decision="approve",
        idempotency_key=key(),
        correlation_id=correlation_id,
    )


def approved_plan(
    container: Container, actor: Actor, items: list[PlanItem] | None = None
) -> AiPlanView:
    return approve(container, actor, plan(container, actor, items or [ai_item("Look it up")]))


def step_ids(view: AiPlanView) -> list[UUID]:
    return [item.step.id for item in view.steps]


def titles(view: AiPlanView) -> list[str]:
    return [item.step.title for item in view.steps]


def admin_rows(sql: str, **params: object) -> list[tuple[object, ...]]:
    """Rows read as the schema owner, which sees the audit trail the app role cannot change."""

    admin = _cleanup_factory_for(os.environ["SIDEKICK_TEST_ADMIN_DATABASE_URL"])
    with admin() as session:
        return [tuple(row) for row in session.execute(text(sql), params).all()]
