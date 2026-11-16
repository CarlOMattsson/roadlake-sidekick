"""The AI worker's use case: take a queued run, call the model once and record what came back.

Money is the hard part. Before every model call, in one transaction that holds the owner's spend
lock, the runner recomputes the plan's digest, reserves the most the call can cost and refuses the
call if that would pass the step's budget, the task's cap or the month's cap. After the call the
reservation is replaced by the cost the provider's token counts give. Every decision reads every
other worker's outstanding reservations, so the caps hold however many workers run. A worker that
dies during a call leaves its reservation, which is booked as cost when the lease runs out: Sidekick
never counts less than was spent.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import tzinfo
from functools import partial
from uuid import UUID

from sidekick.shared.errors import NotFoundError, ValidationError
from sidekick.shared.observability import TelemetryPort, safe_log_fields
from sidekick.shared.types import Clock, TxSession
from sidekick.tasks.domain import TaskStatus
from sidekick.work.application.ai_plans import load_plan_view
from sidekick.work.application.ai_run_support import (
    WORKER_SCOPES,
    breached_cap,
    flag_attention,
    record_run_event,
    render_run_brief,
    require_spec,
)
from sidekick.work.application.ai_store import (
    AiLimits,
    AiPlanView,
    AiStepsStore,
    ServerRunnerConfig,
)
from sidekick.work.domain.ai_cost import ModelPrice, call_cost, call_reserve
from sidekick.work.domain.ai_model_port import (
    CallUsage,
    ModelPort,
    ModelRejected,
    ModelRequest,
    ModelResponse,
    ModelTransient,
    ModelUncertain,
    RejectionKind,
    StopReason,
)
from sidekick.work.domain.ai_outcome import parse_outcome
from sidekick.work.domain.ai_plan import PlanState
from sidekick.work.domain.ai_runs import (
    AiRunState,
    AiStepRun,
    AiUsage,
    CostSource,
    FailureCategory,
)
from sidekick.work.domain.ai_server_brief import MAX_BRIEF_BYTES, build_request
from sidekick.work.domain.ai_spec import AiStepSpecV1
from sidekick.work.domain.run_ports import RunActivityRecorder

LOGGER = logging.getLogger("sidekick.work.ai_runner")

MAX_TRANSIENT_RETRIES = 2
MAX_RETRY_WAIT_SECONDS = 60.0
RECOVERY_BATCH = 100
CLAIM_ATTEMPTS = 10
ACTOR = "worker"

_Conclusion = Callable[[AiStepRun], AiStepRun]
"""What becomes of a run once a call is settled: the run to save."""


@dataclass(frozen=True, slots=True)
class _Claim:
    run: AiStepRun
    spec: AiStepSpecV1
    request: ModelRequest
    action_ids: frozenset[UUID]


class AiRunnerService:
    def __init__(
        self,
        store: AiStepsStore,
        clock: Clock,
        limits: AiLimits,
        config: ServerRunnerConfig,
        model: ModelPort,
        *,
        owner_timezone: tzinfo,
        telemetry: TelemetryPort,
        activity: RunActivityRecorder | None = None,
        sleep: Callable[[float], None] = time.sleep,
        stopping: Callable[[], bool] = lambda: False,
    ) -> None:
        self.store = store
        self.clock = clock
        self.limits = limits
        self.config = config
        self.model = model
        self.owner_timezone = owner_timezone
        self.telemetry = telemetry
        self.activity = activity
        self.sleep = sleep
        self.stopping = stopping
        self.credentials_rejected = False
        """Set once the provider refused the key: no further run is taken until a restart."""

    # Recovery

    def recover_stalled(self) -> int:
        """Lapse queued runs nobody took and settle runs whose server went silent."""

        now = self.clock.now()
        stalled = self.store.transaction(
            lambda session: self.store.list_stalled_server_runs(session, now, RECOVERY_BATCH)
        )
        recovered = 0
        for candidate in stalled:
            if self.store.transaction(lambda session, run=candidate: self._recover(session, run)):
                recovered += 1
        return recovered

    def _recover(self, session: TxSession, candidate: AiStepRun) -> bool:
        try:
            self.store.lock_step_order(session, candidate.owner_id, candidate.task_id)
        except NotFoundError:
            return False
        run = self.store.get_ai_run(session, candidate.owner_id, candidate.id)
        now = self.clock.now()
        if run.holds_lapsed_reservation(now):
            self._save(session, run.abandon(now=now), run.version, "ai.run_abandoned", "abandoned")
            self.telemetry.count("sidekick.ai_runner_recoveries", {"kind": "abandoned"})
            return True
        if run.state is AiRunState.QUEUED and run.is_stale(now):
            self._save(session, run.cancel(now=now), run.version, "ai.run_cancelled", "lapsed")
            self.telemetry.count("sidekick.ai_runner_recoveries", {"kind": "lapsed"})
            return True
        return False

    # Taking a run

    def run_next(self, worker_id: str) -> bool:
        """Take the oldest queued run and carry it out. False when there was nothing to take."""

        if self.credentials_rejected:
            return False
        price = self.config.require_price()
        for _ in range(CLAIM_ATTEMPTS):
            found, claim = self.store.transaction(lambda session: self._claim(session, worker_id))
            if not found:
                return False
            if claim is not None:
                self._carry_out(claim, worker_id, price)
                return True
        return False

    def _claim(self, session: TxSession, worker_id: str) -> tuple[bool, _Claim | None]:
        """(whether a queued run existed, the claim when it was taken and may be run)."""

        now = self.clock.now()
        candidate = self.store.next_queued_server_run(session, now)
        if candidate is None:
            return False, None
        owner_id = candidate.owner_id
        try:
            self.store.lock_step_order(session, owner_id, candidate.task_id)
        except NotFoundError:
            return True, None
        run = self.store.get_ai_run(session, owner_id, candidate.id)
        if run.state is not AiRunState.QUEUED or run.is_stale(now):
            return True, None  # another worker took it, or it lapsed
        view = self._plan_view(session, run)
        if view is None or not _plan_is_current(view, run):
            self._save(session, run.cancel(now=now), run.version, "ai.run_cancelled", "cancelled")
            return True, None
        step = self.store.get_step(session, owner_id, run.step_id)
        spec = require_spec(step)
        claimed = run.claim(
            worker_id,
            provider=self.config.provider,
            model=self.config.model,
            cost_source=CostSource.PRICE_TABLE,
            now=now,
        )
        brief = render_run_brief(
            self.store,
            session,
            run=claimed,
            task=view.task,
            step=step,
            spec=spec,
            scopes=WORKER_SCOPES,
            runner=run.runner,
        )
        if len(brief.encode()) > MAX_BRIEF_BYTES:
            failed = claimed.report_failure(FailureCategory.OTHER, claimed.usage, now=now)
            self._save(session, failed, run.version, "ai.run_reported", "failed")
            return True, None
        self._save(session, claimed, run.version, "ai.run_started", "started")
        actions = self.store.list_actions(session, owner_id, step.id, 1000)
        return True, _Claim(
            claimed,
            spec,
            build_request(brief, spec, self.config.max_output_tokens),
            frozenset(action.id for action in actions),
        )

    # Carrying a run out

    def _carry_out(self, claim: _Claim, worker_id: str, price: ModelPrice) -> None:
        run_id = claim.run.id
        for attempt in range(MAX_TRANSIENT_RETRIES + 1):
            reserved = self.store.transaction(
                lambda session: self._reserve(session, claim, worker_id, price)
            )
            if reserved is None:
                return
            try:
                with self.telemetry.span("ai.model_call", {"ai.model": self.config.model}):
                    response = self.model.complete(claim.request)
            except ModelTransient as error:
                self._count_call("transient", run_id)
                last = attempt == MAX_TRANSIENT_RETRIES
                if self._settle(
                    claim, AiUsage(), _failed(FailureCategory.PROVIDER) if last else _keep
                ):
                    return
                if self.stopping():
                    self._settle(claim, AiUsage(), _cancelled)
                    return
                self.sleep(min(error.retry_after, MAX_RETRY_WAIT_SECONDS))
                continue
            except ModelUncertain:
                self._count_call("uncertain", run_id)
                # The call may have been billed: the reservation is booked as its cost.
                billed = AiUsage(cost_microusd=reserved.usage.reserved_microusd)
                self._settle(claim, billed, _failed(FailureCategory.PROVIDER))
                return
            except ModelRejected as error:
                self._count_call(error.kind.value, run_id)
                if error.kind is RejectionKind.AUTH:
                    self.credentials_rejected = True
                    LOGGER.error(
                        "ai_runner_credentials_rejected",
                        extra=safe_log_fields({"ai_call_outcome": "auth"}),
                    )
                self._settle(claim, AiUsage(), _failed(FailureCategory.PROVIDER))
                return
            self._count_call(_outcome_name(response), run_id)
            self._settle(
                claim,
                self._usage_of(response, price),
                partial(self._conclude, response=response, claim=claim),
            )
            return

    def _count_call(self, outcome: str, run_id: UUID) -> None:
        self.telemetry.count("sidekick.ai_model_calls", {"outcome": outcome})
        LOGGER.info(
            "ai_model_call",
            extra=safe_log_fields({"ai_call_outcome": outcome, "ai_run_id": str(run_id)}),
        )

    def _usage_of(self, response: ModelResponse, price: ModelPrice) -> AiUsage:
        call: CallUsage = response.usage
        return AiUsage(
            input_tokens=call.input_tokens,
            output_tokens=call.output_tokens,
            cache_read_tokens=call.cache_read_tokens,
            cache_write_tokens=call.cache_write_tokens,
            cost_microusd=call_cost(call, price),
        )

    def _conclude(self, settled: AiStepRun, *, response: ModelResponse, claim: _Claim) -> AiStepRun:
        """The run after an answer: reported for review, or failed with the reason."""

        now = self.clock.now()
        if response.stop_reason is StopReason.REFUSAL:
            return settled.report_failure(FailureCategory.REFUSED, settled.usage, now=now)
        if response.stop_reason is StopReason.MAX_TOKENS:
            return settled.report_failure(FailureCategory.BUDGET, settled.usage, now=now)
        if response.stop_reason is not StopReason.END_TURN or response.output_json is None:
            return settled.report_failure(FailureCategory.INVALID_OUTPUT, settled.usage, now=now)
        try:
            outcome = parse_outcome(response.output_json, claim.spec, claim.action_ids)
        except ValidationError:
            return settled.report_failure(FailureCategory.INVALID_OUTPUT, settled.usage, now=now)
        if outcome.result is not None:
            return settled.report_result(outcome.result, settled.usage, now=now)
        if outcome.question is not None:
            return settled.report_question(outcome.question, settled.usage, now=now)
        return settled.report_failure(
            outcome.failure or FailureCategory.OTHER, settled.usage, now=now
        )

    # The two transactions around a call

    def _reserve(
        self, session: TxSession, claim: _Claim, worker_id: str, price: ModelPrice
    ) -> AiStepRun | None:
        """Reserve the call's upper cost, or end the run when it may not go on. None: no call."""

        owner_id = claim.run.owner_id
        try:
            self.store.lock_step_order(session, owner_id, claim.run.task_id)
            run = self.store.get_ai_run(session, owner_id, claim.run.id)
        except NotFoundError:
            return None  # the Task or Step was erased permanently
        now = self.clock.now()
        if run.state is not AiRunState.RUNNING or run.worker_id != worker_id or run.is_stale(now):
            return None  # cancelled by the owner, or taken over after the lease ran out
        view = self._plan_view(session, run)
        if view is None or not _plan_is_current(view, run):
            self._save(session, run.cancel(now=now), run.version, "ai.run_cancelled", "cancelled")
            return None
        self.store.lock_owner_spend(session, owner_id)
        reserve = call_reserve(claim.request.size_bytes(), claim.request.max_tokens, price)
        cap = breached_cap(
            self.store,
            session,
            run=run,
            task=view.task,
            spec=claim.spec,
            limits=self.limits,
            reserve_microusd=reserve,
            now=now,
            zone=self.owner_timezone,
        )
        if cap is not None:
            self.telemetry.count("sidekick.ai_cap_refusals", {"cap": cap})
            failed = run.report_failure(FailureCategory.BUDGET, run.usage, now=now)
            self._save(session, failed, run.version, "ai.run_reported", "failed")
            return None
        reserved = run.reserve(reserve, now=now)
        self.store.save_ai_run(session, reserved, expected_version=run.version)
        return reserved

    def _settle(self, claim: _Claim, call: AiUsage, conclude: _Conclusion) -> bool:
        """Book what the call cost and move the run on. True when the run is no longer running.

        A run the owner cancelled, or whose plan changed during the call, keeps its cost and
        loses the answer.
        """

        call = AiUsage(
            input_tokens=call.input_tokens,
            output_tokens=call.output_tokens,
            cache_read_tokens=call.cache_read_tokens,
            cache_write_tokens=call.cache_write_tokens,
            cost_microusd=call.cost_microusd,
            cost_source=CostSource.PRICE_TABLE,
            model=self.config.model,
        )

        def transaction(session: TxSession) -> bool:
            owner_id = claim.run.owner_id
            self.store.lock_step_order(session, owner_id, claim.run.task_id)
            run = self.store.get_ai_run(session, owner_id, claim.run.id)
            now = self.clock.now()
            settled = run.settle(call, now=now)
            if settled.state is not AiRunState.RUNNING:
                self.store.save_ai_run(session, settled, expected_version=run.version)
                return True
            view = self._plan_view(session, run)
            moved = (
                conclude(settled)
                if view is not None and _plan_is_current(view, run)
                else settled.cancel(now=now)
            )
            if moved.state is AiRunState.RUNNING:
                self.store.save_ai_run(session, moved, expected_version=run.version)
                return False
            self._save(session, moved, run.version, _event_of(moved), moved.state.value)
            if moved.state in (AiRunState.TO_REVIEW, AiRunState.NEEDS_INPUT):
                flag_attention(self.store, session, moved, now)
            return True

        try:
            return self.store.transaction(transaction)
        except NotFoundError:
            # The Task or Step was erased permanently during the call. The run went with it and
            # its cost is already kept for the caps, so there is nothing left to settle.
            LOGGER.info(
                "ai_run_erased_during_call",
                extra=safe_log_fields({"ai_run_id": str(claim.run.id)}),
            )
            return True

    # Shared

    def _plan_view(self, session: TxSession, run: AiStepRun) -> AiPlanView | None:
        """The run's plan as it stands now; none when the Task is gone or in the trash."""

        try:
            task = self.store.get_task(session, run.owner_id, run.task_id)
        except NotFoundError:
            return None
        if task.status is TaskStatus.COMPLETED:
            return None
        return load_plan_view(self.store, session, task, limits=self.limits, now=self.clock.now())

    def _save(
        self,
        session: TxSession,
        run: AiStepRun,
        expected_version: int,
        event: str,
        outcome: str,
    ) -> None:
        self.store.save_ai_run(session, run, expected_version=expected_version)
        record_run_event(
            self.store,
            self.activity,
            session,
            run,
            event,
            actor_type=ACTOR,
            now=self.clock.now(),
        )
        self.telemetry.count(
            "sidekick.ai_runs", {"ai.runner": run.runner.value, "outcome": outcome}
        )


def _plan_is_current(view: AiPlanView, run: AiStepRun) -> bool:
    """The plan is still the approved one the run was queued under and its step is still open."""

    if view.state is not PlanState.APPROVED or view.digest != run.plan_digest:
        return False
    item = next((item for item in view.steps if item.step.id == run.step_id), None)
    return item is not None and item.step.status is not TaskStatus.COMPLETED


def _outcome_name(response: ModelResponse) -> str:
    return {
        StopReason.END_TURN: "ok",
        StopReason.MAX_TOKENS: "max_tokens",
        StopReason.REFUSAL: "refusal",
        StopReason.OTHER: "other",
    }[response.stop_reason]


def _event_of(run: AiStepRun) -> str:
    return "ai.run_cancelled" if run.state is AiRunState.CANCELLED else "ai.run_reported"


def _keep(settled: AiStepRun) -> AiStepRun:
    return settled


def _cancelled(settled: AiStepRun) -> AiStepRun:
    return settled.cancel(now=settled.updated_at)


def _failed(category: FailureCategory) -> _Conclusion:
    def conclude(settled: AiStepRun) -> AiStepRun:
        return settled.report_failure(category, settled.usage, now=settled.updated_at)

    return conclude
