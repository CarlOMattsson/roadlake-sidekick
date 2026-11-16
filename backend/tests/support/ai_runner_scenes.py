"""The scenes the AI runner integration tests share: a queued run, a played script, a wait."""

import dataclasses
import itertools
import os
import threading
import time
from collections.abc import Callable, Collection, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text

from sidekick.api.app import Container
from sidekick.shared.types import Actor, TxSession
from sidekick.work.application.ai_plans import PlanItem
from sidekick.work.application.ai_runner import AiRunnerService
from sidekick.work.application.ai_store import AiPlanView, AiStepsStore, ServerRunnerConfig
from sidekick.work.domain.ai_cost import call_reserve
from sidekick.work.domain.ai_model_port import (
    ModelRequest,
)
from sidekick.work.domain.ai_runs import (
    AiStepRun,
    CostSource,
)
from tests.db import _cleanup_factory_for  # pyright: ignore[reportPrivateUsage]
from tests.support.ai_runner import (
    FakeModel,
    answer,
    make_runner,
    runner_container,
)
from tests.support.ai_runner import Step as ScriptStep
from tests.support.ai_steps import (
    approved_plan,
    key,
    owner_actor,
)
from tests.support.mcp_logging import (
    _all_logs,  # noqa: F401  # pyright: ignore[reportPrivateUsage, reportUnusedImport]
)

_logins = itertools.count(1)

SETTLED_COST = 8_000  # 1 000 in at 4 USD and 200 out at 20 USD per MTok: the default answer


def new_owner(container: Container) -> Actor:
    return owner_actor(container, f"runner-owner-{next(_logins)}")


def queue(container: Container, actor: Actor, view: AiPlanView) -> AiPlanView:
    return container.ai_server_runs.queue_plan_step(
        actor, view.task.id, digest=view.digest, idempotency_key=key()
    )


@dataclass(frozen=True)
class Scene:
    """One queued run of the first startable step of an approved plan."""

    container: Container
    actor: Actor
    task_id: UUID
    step_id: UUID
    run_id: UUID

    def run(self) -> AiStepRun:
        return self.container.ai_runs.get_run(self.actor, self.run_id)

    def attention(self) -> bool:
        return self.container.steps.get_step(self.actor, self.step_id).attention_requested

    def view(self) -> AiPlanView:
        return self.container.ai_plans.get_plan(self.actor, self.task_id)

    def queue_again(self) -> "Scene":
        queued = queue(self.container, self.actor, self.view())
        latest = next(item for item in queued.steps if item.step.id == self.step_id).history.latest
        assert latest is not None
        return dataclasses.replace(self, run_id=latest.id)


def queued_scene(
    container: Container,
    actor: Actor | None = None,
    items: list[PlanItem] | None = None,
    *,
    view: AiPlanView | None = None,
) -> Scene:
    """Approve a plan (unless `view` already is one) and queue its next step for the server."""

    actor = actor or new_owner(container)
    approved = view or approved_plan(container, actor, items)
    queued = queue(container, actor, approved)
    item = next(item for item in queued.steps if item.history.latest is not None)
    assert item.history.latest is not None
    return Scene(container, actor, approved.task.id, item.step.id, item.history.latest.id)


@dataclass(frozen=True)
class Played:
    scene: Scene
    model: FakeModel
    runner: AiRunnerService

    @property
    def run(self) -> AiStepRun:
        return self.scene.run()


def play(
    script: Sequence[ScriptStep],
    *,
    items: list[PlanItem] | None = None,
    sleeps: list[float] | None = None,
    **settings: object,
) -> Played:
    """Queue one step, let a worker take it once against a model that plays `script`."""

    container = runner_container(**settings)
    scene = queued_scene(container, items=items)
    model = FakeModel(list(script))
    runner = make_runner(container, model, sleeps=sleeps)
    runner.run_next("w1")
    return Played(scene, model, runner)


def reserve_of(container: Container, request: ModelRequest) -> int:
    """What the runner sets aside for `request`."""

    price = ServerRunnerConfig.from_settings(container.settings).require_price()
    return call_reserve(request.size_bytes(), request.max_tokens, price)


def probe_request(items: list[PlanItem] | None = None) -> tuple[Container, ModelRequest]:
    """The request a run of a plan of this shape sends, found by running one for another owner.

    The brief holds the same number of bytes for any plan whose titles and spec have the same
    lengths, so the reservation of a real run can be worked out before the run exists.
    """

    played = play([answer()], items=items)
    return played.scene.container, played.model.requests[0]


def expire_lease(run_id: UUID) -> None:
    """Make the run's lease run out, as if its worker had been silent for a long time."""

    admin = _cleanup_factory_for(os.environ["SIDEKICK_TEST_ADMIN_DATABASE_URL"])
    with admin.begin() as session:
        session.execute(
            text(
                "UPDATE sidekick.ai_step_runs SET lease_until = now() - interval '1 minute' "
                "WHERE id = :id"
            ),
            {"id": run_id},
        )


class _SlowSums:
    """A store that reads the spending sums slowly, so two workers deciding at once overlap.

    The decision to reserve is a read of what is spent followed by a write of the reservation;
    pausing between them makes a missing lock show up every time instead of once in a while.
    """

    def __init__(self, store: AiStepsStore, seconds: float) -> None:
        self._store = store
        self._seconds = seconds

    def __getattr__(self, name: str) -> object:
        return getattr(self._store, name)

    def sum_ai_cost_since(
        self,
        session: TxSession,
        owner_id: UUID,
        since: datetime,
        sources: Collection[CostSource],
        task_id: UUID | None = None,
    ) -> int:
        spent = self._store.sum_ai_cost_since(session, owner_id, since, sources, task_id)
        time.sleep(self._seconds)
        return spent


def run_together(
    container: Container, model: FakeModel, workers: Sequence[str], *, read_delay: float = 0.0
) -> list[bool]:
    """One `run_next` per worker, all released at the same moment on separate threads."""

    barrier = threading.Barrier(len(workers))

    def work(worker: str) -> bool:
        runner = make_runner(container, model)
        if read_delay:
            runner.store = cast("AiStepsStore", _SlowSums(runner.store, read_delay))
        barrier.wait(timeout=10)
        return runner.run_next(worker)

    with ThreadPoolExecutor(len(workers)) as pool:
        futures = [pool.submit(work, worker) for worker in workers]
        return [future.result(timeout=60) for future in futures]


def wait_until(condition: Callable[[], bool], seconds: float = 10.0) -> None:
    """Poll `condition` until it holds; a timeout is not an error, the caller's asserts decide."""

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and not condition():
        time.sleep(0.02)
