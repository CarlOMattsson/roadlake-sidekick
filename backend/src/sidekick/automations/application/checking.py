"""The independent check of an automation run: the AI worker's second job.

A run that ended with proposals waits in the state `checking`; that row is the queue. A worker
takes the run that has waited longest, asks the checker about its cards (one call each for a
decision model, up to 25 at once for a chat model) and writes what comes back: one row in
`automation_checks` per card, the card's verdict and confidence, and the cost on the run. When
every card has its check, or was shown as "Not checked", the run is done and the cards that
qualify for the high-confidence group become eligible.

Money is as for AI steps. Before every call, in one transaction that holds the owner's spend lock,
the worker reserves the most the call can cost and refuses it if that would pass the run's
budget, the share of the month that automations may spend or the month's cap that every kind of
AI spending shares. After the call the reservation becomes the cost the provider reported. A
worker that dies during a call leaves its reservation, which the next worker books as cost. The
lease that holds a run outlasts one whole call (`runs.check_lease`), and a call that ends after
another worker took the run over is booked without touching that worker's reservation.

A check that fails, or is refused for money, never blocks the owner: its cards are shown as not
checked and nothing is ever approved on the strength of a missing answer. What the checker sees
and what it may answer are fixed in `automations.domain.checking`. Text of a proposal is untrusted:
it is never written to a log, a metric or an audit event; those hold ids and closed codes.
"""

import logging
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, tzinfo
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from sidekick.automations.application.check_release import CHECKED, close_checked_run
from sidekick.automations.application.runs import AutomationRunLimits
from sidekick.automations.application.suggestions import AutoApplyOutcome
from sidekick.automations.domain.automation import Automation, SuggestionCheck
from sidekick.automations.domain.checking import (
    CheckAnswer,
    CheckCap,
    CheckContext,
    CheckerCall,
    CheckItem,
    breached_check_cap,
    check_item,
)
from sidekick.automations.domain.datapoints import Datapoint
from sidekick.automations.domain.runs import (
    CHECK_RETRY_WAIT_SECONDS,
    AutomationRun,
    RunState,
    usage_for_check,
)
from sidekick.automations.domain.suggestion import Suggestion, SuggestionState
from sidekick.shared.observability import TelemetryPort, log_failure, safe_log_fields
from sidekick.shared.owner_day import month_start
from sidekick.shared.types import AuditingStore, Clock, TransactionalStore, TxSession, new_uuid7
from sidekick.work.domain.ai_model_port import (
    ModelRejected,
    ModelTransient,
    ModelUncertain,
    RejectionKind,
)
from sidekick.work.domain.ai_runs import AiUsage, CostSource, MoneyCaps

LOGGER = logging.getLogger("sidekick.automations.checks")

MAX_TRANSIENT_RETRIES = 2
ERROR = "error"
"""The verdict a check row carries when no usable answer came back."""


class CheckerPort(Protocol):
    """The model that checks, as this use case calls it (`automations.infrastructure.checkers`)."""

    kind: str
    model: str
    max_batch: int
    cost_source: CostSource

    def reserve_microusd(self, context: CheckContext, items: Sequence[CheckItem]) -> int: ...

    def check(self, context: CheckContext, items: Sequence[CheckItem]) -> CheckerCall: ...


class AutoApplier(Protocol):
    """The opt-in policy that applies what the check cleared (`SuggestionService`)."""

    def auto_apply_run(
        self,
        owner_id: UUID,
        run_id: UUID,
        *,
        checker_configured: bool,
        correlation_id: str | None = None,
    ) -> AutoApplyOutcome: ...


class CheckStore(TransactionalStore, AuditingStore, Protocol):
    def next_checking_run(self, session: TxSession, now: datetime) -> AutomationRun | None: ...
    def get_automation(
        self, session: TxSession, owner_id: UUID, automation_id: UUID, *, lock: bool = False
    ) -> Automation: ...
    def get_run(
        self, session: TxSession, owner_id: UUID, run_id: UUID, *, lock: bool = False
    ) -> AutomationRun: ...
    def save_run(
        self, session: TxSession, run: AutomationRun, expected_version: int | None = None
    ) -> None: ...
    def list_suggestions(
        self,
        session: TxSession,
        owner_id: UUID,
        *,
        states: Collection[SuggestionState] | None = None,
        automation_id: UUID | None = None,
        run_id: UUID | None = None,
        limit: int = ...,
    ) -> list[Suggestion]: ...
    def get_suggestion(
        self, session: TxSession, owner_id: UUID, suggestion_id: UUID, *, lock: bool = False
    ) -> Suggestion: ...
    def save_suggestion(
        self,
        session: TxSession,
        suggestion: Suggestion,
        now: datetime,
        expected_version: int | None = None,
    ) -> None: ...
    def append_check(self, session: TxSession, check: SuggestionCheck) -> None: ...
    def list_checks(
        self, session: TxSession, owner_id: UUID, suggestion_id: UUID
    ) -> list[SuggestionCheck]: ...
    def list_run_datapoints(
        self, session: TxSession, owner_id: UUID, run_id: UUID
    ) -> list[Datapoint]: ...
    def lock_owner_spend(self, session: TxSession, owner_id: UUID) -> None: ...
    def sum_automation_cost_since(
        self, session: TxSession, owner_id: UUID, since: datetime, sources: Collection[CostSource]
    ) -> int: ...
    def sum_ai_cost_since(
        self,
        session: TxSession,
        owner_id: UUID,
        since: datetime,
        sources: Collection[CostSource],
        task_id: UUID | None = None,
    ) -> int: ...


@dataclass(frozen=True, slots=True)
class _Claim:
    run: AutomationRun
    context: CheckContext
    run_budget_microusd: int
    items: tuple[CheckItem, ...]


class _Reservation(StrEnum):
    HELD = "held"
    LOST = "lost"


class AutomationCheckService:
    def __init__(
        self,
        store: CheckStore,
        clock: Clock,
        limits: AutomationRunLimits,
        checker: CheckerPort,
        *,
        owner_timezone: tzinfo,
        telemetry: TelemetryPort,
        sleep: Callable[[float], None] = time.sleep,
        stopping: Callable[[], bool] = lambda: False,
        auto_applier: AutoApplier | None = None,
    ) -> None:
        self.store = store
        self.clock = clock
        self.limits = limits
        self.checker = checker
        self.owner_timezone = owner_timezone
        self.telemetry = telemetry
        self.sleep = sleep
        self.stopping = stopping
        self.auto_applier = auto_applier
        self.credentials_rejected = False
        """Set once the provider refused the key: no run is taken until a restart."""
        self.progress: Callable[[], None] = lambda: None
        """Called before each call to the checker: the worker's proof that it is not stuck."""
        self._caps = MoneyCaps(
            task_microusd=limits.automation_monthly_cap_microusd,
            month_microusd=limits.monthly_cap_microusd,
            local_models_exempt=limits.local_models_exempt,
        )

    # --- taking a run -------------------------------------------------------------------------

    def run_next(self, worker_id: str) -> bool:
        """Take the run that has waited longest for its check and carry it out. False when none
        waits, or when the provider has refused the key."""

        if self.credentials_rejected:
            return False
        claim = self.store.transaction(lambda session: self._claim(session, worker_id))
        if claim is None:
            return False
        self._carry_out(claim, worker_id)
        return True

    def _claim(self, session: TxSession, worker_id: str) -> _Claim | None:
        now = self.clock.now()
        run = self.store.next_checking_run(session, now)
        if run is None:
            return None
        stored_version = run.version
        if run.holds_lapsed_check_reservation(now):
            # The worker that reserved a call went silent: the call may have been billed.
            run = run.abandon_check_reservation(now=now)
        claimed = run.claim_check(
            worker_id, self.checker.model, lease=self.limits.check_lease, now=now
        )
        owner_id = claimed.owner_id
        automation = self.store.get_automation(session, owner_id, claimed.automation_id)
        waiting = self.store.list_suggestions(
            session, owner_id, run_id=claimed.id, states=[SuggestionState.CHECKING]
        )
        points = {
            point.id: point
            for point in self.store.list_run_datapoints(session, owner_id, claimed.id)
        }
        self.store.save_run(session, claimed, expected_version=stored_version)
        spec = automation.spec
        return _Claim(
            run=claimed,
            context=CheckContext(
                title=automation.title,
                purpose=spec.purpose,
                sources=tuple(item.value for item in spec.sources),
                allowed_effects=tuple(item.value for item in spec.allowed_effects),
            ),
            run_budget_microusd=spec.run_budget_microusd,
            items=tuple(check_item(card, points) for card in waiting),
        )

    # --- carrying a run out -------------------------------------------------------------------

    def _carry_out(self, claim: _Claim, worker_id: str) -> None:
        size = max(self.checker.max_batch, 1)
        items = claim.items
        for start in range(0, len(items), size):
            if self.stopping():
                return  # the lease runs out and the next worker checks what is left
            self.progress()
            batch = items[start : start + size]
            outcome = self._check_batch(claim, batch, worker_id)
            if isinstance(outcome, CheckCap):
                self._count_cap(outcome)
                self._fail_rest(claim, items[start:])
                break
            if outcome is _Reservation.LOST:
                return
        if self.store.transaction(lambda session: self._finish(session, claim, worker_id)):
            self._auto_apply(claim.run)

    def _check_batch(
        self, claim: _Claim, batch: Sequence[CheckItem], worker_id: str
    ) -> CheckCap | _Reservation | None:
        """Check one batch. None: it is settled and the run goes on. A cap: stop and show the rest
        as not checked. Lost: this worker no longer holds the run (or the key was refused)."""

        reserve = self.checker.reserve_microusd(claim.context, batch)
        for attempt in range(MAX_TRANSIENT_RETRIES + 1):
            held = self.store.transaction(
                lambda session: self._reserve(session, claim, worker_id, reserve)
            )
            if held is not _Reservation.HELD:
                return held
            try:
                with self.telemetry.span("ai.model_call", {"ai.model": self.checker.model}):
                    result = self.checker.check(claim.context, batch)
            except ModelTransient as error:
                self._count_call("transient")
                last = attempt == MAX_TRANSIENT_RETRIES
                self._settle(claim, batch, worker_id, AiUsage(), None, fail=last)
                if last:
                    return None
                if self.stopping():
                    return _Reservation.LOST
                self.sleep(min(error.retry_after, CHECK_RETRY_WAIT_SECONDS))
                continue
            except ModelUncertain:
                self._count_call("uncertain")
                # The call may have been billed: the reservation is booked as its cost.
                billed = AiUsage(cost_microusd=reserve, cost_source=self.checker.cost_source)
                self._settle(claim, batch, worker_id, billed, None, fail=True)
                return None
            except ModelRejected as error:
                self._count_call(error.kind.value)
                if error.kind is RejectionKind.AUTH:
                    self.credentials_rejected = True
                    LOGGER.error(
                        "automation_check_credentials_rejected",
                        extra=safe_log_fields({"ai_call_outcome": "auth"}),
                    )
                    self._settle(claim, batch, worker_id, AiUsage(), None, fail=False)
                    return _Reservation.LOST
                self._settle(claim, batch, worker_id, AiUsage(), None, fail=True)
                return None
            self._count_call("ok" if result.answers is not None else "unusable")
            self._settle(claim, batch, worker_id, result.usage, result.answers, fail=True)
            return None
        return None

    def _reserve(
        self, session: TxSession, claim: _Claim, worker_id: str, reserve: int
    ) -> CheckCap | _Reservation:
        """Reserve the call's upper cost, or say which limit it would pass."""

        owner_id = claim.run.owner_id
        now = self.clock.now()
        self.store.lock_owner_spend(session, owner_id)
        run = self.store.get_run(session, owner_id, claim.run.id, lock=True)
        if not run.holds_check(worker_id, now):
            return _Reservation.LOST
        source = self.checker.cost_source
        since = month_start(now, self.owner_timezone)
        counted = self.limits.counted_sources()
        breached = breached_check_cap(
            self._caps,
            source=source,
            reserve_microusd=reserve,
            spent_on_run_microusd=usage_for_check(run.usage, source).cost_microusd,
            run_budget_microusd=claim.run_budget_microusd,
            spent_by_automations_microusd=self.store.sum_automation_cost_since(
                session, owner_id, since, counted
            ),
            automation_cap_microusd=self.limits.automation_monthly_cap_microusd,
            spent_in_month_microusd=self.store.sum_ai_cost_since(session, owner_id, since, counted),
        )
        if breached is not None:
            return breached
        self.store.save_run(
            session,
            run.reserve_check(
                reserve, source, worker_id=worker_id, lease=self.limits.check_lease, now=now
            ),
            expected_version=run.version,
        )
        return _Reservation.HELD

    def _settle(
        self,
        claim: _Claim,
        batch: Sequence[CheckItem],
        worker_id: str,
        usage: AiUsage,
        answers: Mapping[UUID, CheckAnswer] | None,
        *,
        fail: bool,
    ) -> None:
        """Book what the call cost and write the cards' checks. A card without an answer is shown
        as not checked when `fail`; otherwise it is left for the next worker."""

        given = answers or {}

        def transaction(session: TxSession) -> None:
            now = self.clock.now()
            run = self.store.get_run(session, claim.run.owner_id, claim.run.id, lock=True)
            self.store.save_run(
                session,
                run.settle_check(usage, worker_id=worker_id, now=now),
                expected_version=run.version,
            )
            for item in batch:
                answer = given.get(item.suggestion_id)
                if answer is not None or fail:
                    self._write_check(session, claim.run, item.suggestion_id, answer, now)

        self.store.transaction(transaction)

    def _fail_rest(self, claim: _Claim, items: Sequence[CheckItem]) -> None:
        """Show these cards as not checked, without a call."""

        def transaction(session: TxSession) -> None:
            now = self.clock.now()
            for item in items:
                self._write_check(session, claim.run, item.suggestion_id, None, now)

        self.store.transaction(transaction)

    def _write_check(
        self,
        session: TxSession,
        run: AutomationRun,
        suggestion_id: UUID,
        answer: CheckAnswer | None,
        now: datetime,
    ) -> None:
        """One check row and the card's move: checked with the answer, or failed without one."""

        owner_id = run.owner_id
        card = self.store.get_suggestion(session, owner_id, suggestion_id, lock=True)
        if card.state is not SuggestionState.CHECKING:
            return  # another worker got there first
        attempt = len(self.store.list_checks(session, owner_id, suggestion_id)) + 1
        if answer is None:
            moved = card.fail_check(expected_version=card.version)
            verdict, confidence, codes = ERROR, None, ()
        else:
            moved = card.record_check(
                answer.verdict, answer.confidence, expected_version=card.version
            )
            verdict, confidence = answer.verdict.value, answer.confidence
            codes = tuple(code.value for code in answer.reason_codes)
        self.store.append_check(
            session,
            SuggestionCheck(
                id=new_uuid7(),
                owner_id=owner_id,
                suggestion_id=suggestion_id,
                run_id=run.id,
                attempt=attempt,
                checker=self.checker.kind,
                model=self.checker.model,
                verdict=verdict,
                confidence=confidence,
                reason_codes=codes,
                checked_at=now,
            ),
        )
        self.store.save_suggestion(session, moved, now, expected_version=card.version)
        self.telemetry.count(
            "sidekick.automations.checks", {"kind": self.checker.kind, "outcome": verdict}
        )

    def _finish(self, session: TxSession, claim: _Claim, worker_id: str) -> bool:
        """Every card has its check: the run is done and the group is turned on. False when the
        run was not closed here."""

        owner_id = claim.run.owner_id
        now = self.clock.now()
        run = self.store.get_run(session, owner_id, claim.run.id, lock=True)
        if run.state is not RunState.CHECKING or run.worker_id != worker_id:
            return False  # another worker took the run over
        if self.store.list_suggestions(
            session, owner_id, run_id=run.id, states=[SuggestionState.CHECKING]
        ):
            return False  # a card is still waiting: the lease runs out and the run is taken again
        close_checked_run(
            self.store,
            session,
            run,
            run.checked(now=now),
            now=now,
            event=CHECKED,
            outcome="done",
        )
        return True

    def _auto_apply(self, run: AutomationRun) -> None:
        """Let the owner's opt-in policy apply what the check cleared. A step of its own, after the
        run is closed: a failure here leaves the cards pending, for the owner to decide."""

        if self.auto_applier is None:
            return
        try:
            outcome = self.auto_applier.auto_apply_run(
                run.owner_id,
                run.id,
                checker_configured=self.limits.checker_enabled,
                correlation_id=str(new_uuid7()),
            )
        except Exception as error:
            log_failure(LOGGER, "automation_auto_apply_failed", error)
            return
        if outcome.applied:
            LOGGER.info(
                "automation_auto_applied",
                extra=safe_log_fields(
                    {"automation_run_id": str(run.id), "outcome": "auto_applied"}
                ),
            )

    # --- shared -------------------------------------------------------------------------------

    def _count_call(self, outcome: str) -> None:
        self.telemetry.count("sidekick.automations.check_calls", {"outcome": outcome})
        LOGGER.info("automation_check_call", extra=safe_log_fields({"ai_call_outcome": outcome}))

    def _count_cap(self, cap: CheckCap) -> None:
        self.telemetry.count("sidekick.ai_cap_refusals", {"cap": cap.value})
        LOGGER.info("automation_check_refused", extra=safe_log_fields({"outcome": cap.value}))
