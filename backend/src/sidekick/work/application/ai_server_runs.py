"""Running an approved AI step on the server: queueing it and cancelling a run.

The owner presses "Run" and the step becomes a queued run row; the AI worker takes it from there
(`ai_runner`). Everything that can be refused for the owner's own benefit is refused here, before
any model call: a plan that changed, a step that is not next, a cap that is already reached.
"""

from datetime import datetime, tzinfo
from uuid import UUID

from sidekick.shared.errors import ConflictError, ValidationError
from sidekick.shared.observability import TelemetryPort
from sidekick.shared.owner_day import day_start
from sidekick.shared.replay import id_replay_record, id_result
from sidekick.shared.types import Actor, Clock, TxSession, new_uuid7
from sidekick.tasks.domain import Task
from sidekick.work.application.ai_plans import load_plan_view
from sidekick.work.application.ai_run_support import (
    WORKER_SCOPES,
    breached_cap,
    record_run_event,
    render_run_brief,
    replayed_run,
    require_approved,
    require_spec,
    server_blocker,
    with_server_info,
)
from sidekick.work.application.ai_store import (
    AiLimits,
    AiPlanView,
    AiStepsStore,
    ServerRunnerConfig,
)
from sidekick.work.domain import Step
from sidekick.work.domain.ai_cost import ModelPrice, call_reserve
from sidekick.work.domain.ai_plan import STARTABLE, AiStepStatus
from sidekick.work.domain.ai_runs import AiStepRun, RunnerKind
from sidekick.work.domain.ai_server_brief import MAX_BRIEF_BYTES, build_request
from sidekick.work.domain.ai_spec import AiStepSpecV1
from sidekick.work.domain.run_ports import RunActivityRecorder


class AiServerRunService:
    def __init__(
        self,
        store: AiStepsStore,
        clock: Clock,
        limits: AiLimits,
        config: ServerRunnerConfig,
        *,
        owner_timezone: tzinfo,
        telemetry: TelemetryPort,
        activity: RunActivityRecorder | None = None,
    ) -> None:
        self.store = store
        self.clock = clock
        self.limits = limits
        self.config = config
        self.owner_timezone = owner_timezone
        self.telemetry = telemetry
        self.activity = activity

    def queue_plan_step(
        self,
        actor: Actor,
        task_id: UUID,
        *,
        digest: str,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> AiPlanView:
        """Queue the next step of the Task's approved plan for the server to run.

        `digest` is the plan the owner is looking at; a plan that changed since is not run. The
        right to do this is the right to change the Task, not the right to run steps: the owner
        presses the button, and a connector's own `ai:run` right is for Claude Code.
        """

        actor.require("tasks:write")

        def operation(session: TxSession) -> dict[str, str]:
            return id_result(self._queue(session, actor, task_id, digest, correlation_id).id)

        def replayed(session: TxSession) -> AiPlanView:
            self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="run_ai_plan",
                key=idempotency_key,
                payload={"task_id": str(task_id), "digest": digest},
                execute=lambda: operation(session),
                replay=id_replay_record,
            )
            task = self.store.get_task(session, actor.user_id, task_id)
            now = self.clock.now()
            view = load_plan_view(self.store, session, task, limits=self.limits, now=now)
            return with_server_info(
                view,
                self.store,
                session,
                config=self.config,
                limits=self.limits,
                now=now,
                zone=self.owner_timezone,
            )

        return self.store.transaction(replayed)

    def _queue(
        self,
        session: TxSession,
        actor: Actor,
        task_id: UUID,
        digest: str,
        correlation_id: str | None,
    ) -> AiStepRun:
        owner_id = actor.user_id
        self.store.lock_step_order(session, owner_id, task_id)
        task = self.store.get_task(session, owner_id, task_id)
        # After the Task is found, so another owner's Task is "not found" whatever the setting.
        price = self.config.require_price()
        now = self.clock.now()
        view = load_plan_view(self.store, session, task, limits=self.limits, now=now)
        if view.digest != digest:
            raise ConflictError("the plan changed since you looked at it", reason="plan_changed")
        require_approved(view)
        item = next((item for item in view.steps if item.status in STARTABLE), None)
        if item is None:
            exhausted = any(item.status is AiStepStatus.EXHAUSTED for item in view.steps)
            raise ConflictError(
                "no step of the plan can run now",
                reason="ai_limit_reached" if exhausted else "step_not_ready",
            )
        spec = require_spec(item.step)
        if (blocker := server_blocker(spec)) is not None:
            raise blocker
        latest = item.history.latest
        if latest is not None and latest.holds_lapsed_reservation(now):
            self.store.save_ai_run(
                session, latest.abandon(now=now), expected_version=latest.version
            )
        elif latest is not None and latest.is_stale(now):
            self.store.save_ai_run(session, latest.cancel(now=now), expected_version=latest.version)
        if self._starts_today(session, owner_id, now) >= self.limits.server_starts_per_day:
            raise ConflictError(
                "the daily limit of AI starts is reached", reason="ai_limit_reached"
            )
        run = AiStepRun.queue(
            run_id=new_uuid7(),
            owner_id=owner_id,
            task_id=task.id,
            step_id=item.step.id,
            attempt=item.history.last_attempt + 1,
            plan_digest=view.digest,
            now=now,
        )
        self._require_room_for_a_call(session, run, task, item.step, spec, price, now)
        self.store.save_ai_run(session, run)
        record_run_event(
            self.store,
            self.activity,
            session,
            run,
            "ai.run_queued",
            actor_type="user",
            now=now,
            correlation_id=correlation_id,
        )
        self.telemetry.count("sidekick.ai_runs", {"ai.runner": "server", "outcome": "queued"})
        return run

    def _starts_today(self, session: TxSession, owner_id: UUID, now: datetime) -> int:
        since = day_start(now, self.owner_timezone)
        return self.store.count_ai_runs_since(session, owner_id, RunnerKind.SERVER, since)

    def _require_room_for_a_call(
        self,
        session: TxSession,
        run: AiStepRun,
        task: Task,
        step: Step,
        spec: AiStepSpecV1,
        price: ModelPrice,
        now: datetime,
    ) -> None:
        """Refuse, at no cost, a run whose first model call could not be reserved."""

        brief = render_run_brief(
            self.store,
            session,
            run=run,
            task=task,
            step=step,
            spec=spec,
            scopes=WORKER_SCOPES,
            runner=RunnerKind.SERVER,
        )
        if len(brief.encode()) > MAX_BRIEF_BYTES:
            raise ValidationError("the step's material is too large to send to the model")
        request = build_request(brief, spec, self.config.max_output_tokens)
        reserve = call_reserve(request.size_bytes(), request.max_tokens, price)
        cap = breached_cap(
            self.store,
            session,
            run=run,
            task=task,
            spec=spec,
            limits=self.limits,
            reserve_microusd=reserve,
            now=now,
            zone=self.owner_timezone,
        )
        if cap is not None:
            self.telemetry.count("sidekick.ai_cap_refusals", {"cap": cap})
            raise ConflictError("a spending cap would be passed", reason="ai_budget_reached")

    def cancel_run(
        self,
        actor: Actor,
        run_id: UUID,
        *,
        run_version: int,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> AiStepRun:
        """Stop a queued or running run. A model call already under way is still billed."""

        actor.require("tasks:write")

        def operation(session: TxSession) -> dict[str, str]:
            owner_id = actor.user_id
            task_id = self.store.get_ai_run(session, owner_id, run_id).task_id
            self.store.lock_step_order(session, owner_id, task_id)
            run = self.store.get_ai_run(session, owner_id, run_id)
            if run.version != run_version:
                raise ConflictError("stale run version", reason="stale_version")
            now = self.clock.now()
            cancelled = run.cancel(now=now)
            self.store.save_ai_run(session, cancelled, expected_version=run_version)
            record_run_event(
                self.store,
                self.activity,
                session,
                cancelled,
                "ai.run_cancelled",
                actor_type="user",
                now=now,
                correlation_id=correlation_id,
            )
            self.telemetry.count(
                "sidekick.ai_runs", {"ai.runner": run.runner.value, "outcome": "cancelled"}
            )
            return id_result(cancelled.id)

        return replayed_run(
            self.store,
            actor,
            "cancel_ai_step_run",
            idempotency_key,
            {"run_id": str(run_id), "run_version": run_version},
            operation,
        )
