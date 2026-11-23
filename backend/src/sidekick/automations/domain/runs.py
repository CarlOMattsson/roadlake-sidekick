"""A run of an automation: one attempt at one occurrence, and the rules for starting it.

An occurrence is a scheduled day in the owner's zone (`d:2026-11-22`) or one request to run now
(`m:<id>`). Starting an occurrence twice gives the same run; a run that failed, was cancelled or
lapsed may be tried again, up to three attempts. A run is held by a lease that every call of its
runner renews, so a runner that went away does not block the occurrence for good.

The text of a run is written by an AI and is untrusted: `summary` is shown escaped and labelled.
Nothing here knows storage or transport.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta, tzinfo
from enum import StrEnum
from typing import Any
from uuid import UUID

from sidekick.automations.domain.spec import Cadence
from sidekick.automations.domain.text import normalise_line
from sidekick.shared.errors import ConflictError, ValidationError
from sidekick.work.domain.ai_runs import AiUsage, CostSource

MAX_ATTEMPTS_PER_OCCURRENCE = 3
MAX_SUGGESTIONS_PER_CALL = 25
RUN_LEASE = timedelta(minutes=30)
"""How long a runner may be silent before another start takes the occurrence over."""
CHECK_RETRY_WAIT_SECONDS = 60.0
"""The longest a worker waits before asking a busy checker again."""
CHECK_LEASE_MARGIN = timedelta(seconds=120)
DEFAULT_CHECK_RELEASE_AFTER = timedelta(hours=1)
"""How long a run may wait for its check, untaken, before its cards are shown as not checked."""


def check_lease(request_timeout_seconds: float) -> timedelta:
    """How long a worker may be silent while it checks a run before another takes it over.

    The lease is renewed when a call is reserved, so it must outlast one whole call and the wait
    before the next: the provider's timeout, the longest retry wait and a margin. A shorter lease
    lets a second worker take the run while the first still has a call in flight.
    """

    return (
        timedelta(seconds=request_timeout_seconds + CHECK_RETRY_WAIT_SECONDS) + CHECK_LEASE_MARGIN
    )


DEFAULT_CHECK_LEASE = check_lease(300)
MAX_CHECKER_MODEL_CHARS = 120
MAX_SUMMARY_CHARS = 300
SUGGESTION_LIFETIME = timedelta(days=14)
"""A pending suggestion that nobody decided expires after this."""


class RunRunner(StrEnum):
    CLAUDE = "claude"
    CLAUDE_CODE = "claude_code"
    SERVER = "server"


class CredentialKind(StrEnum):
    TOKEN = "token"  # noqa: S105  # a credential kind, not a credential
    OAUTH = "oauth"
    WORKER = "worker"


class RunState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CHECKING = "checking"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    LAPSED = "lapsed"


ACTIVE_STATES = frozenset({RunState.QUEUED, RunState.RUNNING, RunState.CHECKING})


class RunOutcome(StrEnum):
    OK = "ok"
    NOTHING_FOUND = "nothing_found"
    FAILED = "failed"
    BUDGET = "budget"
    INVALID_OUTPUT = "invalid_output"
    PROVIDER = "provider"
    REFUSED = "refused"


REPORTABLE_OUTCOMES = (RunOutcome.OK, RunOutcome.NOTHING_FOUND, RunOutcome.FAILED)
"""What a runner may say about its own run; the others are what the server finds out."""


class OccurrenceKind(StrEnum):
    SCHEDULED = "scheduled"
    MANUAL = "manual"


class NothingDueReason(StrEnum):
    NO_CADENCE = "no_cadence"
    NOT_DUE = "not_due"
    ALREADY_DONE = "already_done"
    CHECKING = "checking"


@dataclass(frozen=True, slots=True)
class AutomationRun:
    id: UUID
    owner_id: UUID
    automation_id: UUID
    occurrence_key: str
    attempt: int
    runner: RunRunner
    state: RunState
    spec_digest: str
    credential_kind: CredentialKind
    created_at: datetime
    updated_at: datetime
    stage: str | None = None
    session_digest: str | None = None
    """Keyed hash of the MCP session that claimed the run; `None` when the transport has none."""
    worker_id: str | None = None
    lease_until: datetime | None = None
    queued_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    datapoint_count: int = 0
    suggestion_count: int = 0
    rejected_count: int = 0
    flagged_count: int = 0
    auto_applied_count: int = 0
    summary: str | None = None
    """Written by the AI and untrusted."""
    outcome: RunOutcome | None = None
    checker_model: str | None = None
    usage: AiUsage = field(default_factory=AiUsage)
    version: int = 1

    def __post_init__(self) -> None:
        if self.attempt < 1 or self.version < 1:
            raise ValidationError("run attempt and version must be positive")

    @classmethod
    def claim(
        cls,
        *,
        run_id: UUID,
        owner_id: UUID,
        automation_id: UUID,
        occurrence_key: str,
        attempt: int,
        runner: RunRunner,
        spec_digest: str,
        session_digest: str | None,
        credential_kind: CredentialKind,
        now: datetime,
    ) -> "AutomationRun":
        """A run that a client runner has just taken: running, with its lease."""

        return cls(
            id=run_id,
            owner_id=owner_id,
            automation_id=automation_id,
            occurrence_key=occurrence_key,
            attempt=attempt,
            runner=runner,
            state=RunState.RUNNING,
            spec_digest=spec_digest,
            credential_kind=credential_kind,
            session_digest=session_digest,
            lease_until=now + RUN_LEASE,
            queued_at=now,
            started_at=now,
            created_at=now,
            updated_at=now,
        )

    @property
    def open(self) -> bool:
        return self.state is RunState.RUNNING

    def holds_lease(self, now: datetime) -> bool:
        return self.open and self.lease_until is not None and self.lease_until > now

    def _next(self, now: datetime, **changes: Any) -> "AutomationRun":
        return replace(self, version=self.version + 1, updated_at=now, **changes)

    def ended(self, state: RunState, now: datetime) -> "AutomationRun":
        """A run that did not finish well: cancelled, or lapsed after its lease ran out."""

        if self.state not in ACTIVE_STATES:
            raise ConflictError("the run is not active", reason="run_not_open")
        return self._next(now, state=state, lease_until=None, finished_at=now)

    def recorded(
        self,
        *,
        datapoints: int,
        suggestions: int,
        rejected: int,
        flagged: int,
        now: datetime,
    ) -> "AutomationRun":
        """What one call of the runner added. Only a running run takes results; each call renews
        the lease."""

        if not self.open:
            raise ConflictError("the run is not open", reason="run_not_open")
        return self._next(
            now,
            lease_until=now + RUN_LEASE,
            datapoint_count=self.datapoint_count + datapoints,
            suggestion_count=self.suggestion_count + suggestions,
            rejected_count=self.rejected_count + rejected,
            flagged_count=self.flagged_count + flagged,
        )

    def finished(
        self,
        *,
        outcome: RunOutcome,
        summary: str | None,
        usage: AiUsage,
        checker_enabled: bool,
        now: datetime,
    ) -> "AutomationRun":
        """The runner's last word. A failure ends the run; otherwise it is done, or waits for the
        independent check when one is configured and there is something to check."""

        if not self.open:
            raise ConflictError("the run is not open", reason="run_not_open")
        if outcome not in REPORTABLE_OUTCOMES:
            raise ValidationError("a runner cannot report that outcome")
        checking = (
            outcome is not RunOutcome.FAILED and checker_enabled and self.suggestion_count > 0
        )
        state = (
            RunState.FAILED
            if outcome is RunOutcome.FAILED
            else RunState.CHECKING
            if checking
            else RunState.DONE
        )
        return self._next(
            now,
            state=state,
            outcome=outcome,
            summary=clean_summary(summary),
            usage=usage,
            lease_until=None,
            finished_at=None if checking else now,
        )

    # --- the independent check ------------------------------------------------------------------

    def _require_checking(self) -> None:
        if self.state is not RunState.CHECKING:
            raise ConflictError("the run is not being checked", reason="run_not_open")

    def claim_check(
        self, worker_id: str, checker_model: str, *, lease: timedelta, now: datetime
    ) -> "AutomationRun":
        """A worker takes a run that waits for its check and whose last worker has gone silent."""

        self._require_checking()
        if self.lease_until is not None and self.lease_until > now:
            raise ConflictError("another worker is checking the run", reason="run_not_open")
        return self._next(
            now,
            worker_id=worker_id,
            stage="check",
            lease_until=now + lease,
            checker_model=checker_model[:MAX_CHECKER_MODEL_CHARS],
        )

    def holds_check(self, worker_id: str, now: datetime) -> bool:
        """This worker still holds the run's check: it took it and its lease has not run out."""

        return (
            self.state is RunState.CHECKING
            and self.worker_id == worker_id
            and self.lease_until is not None
            and self.lease_until > now
        )

    def holds_lapsed_check_reservation(self, now: datetime) -> bool:
        """The worker went silent with a model call reserved, which may have been billed."""

        return (
            self.state is RunState.CHECKING
            and self.usage.reserved_microusd > 0
            and self.lease_until is not None
            and self.lease_until <= now
        )

    def abandon_check_reservation(self, *, now: datetime) -> "AutomationRun":
        """Book a reservation whose call never reported back as its cost, and free the run."""

        if not self.holds_lapsed_check_reservation(now):
            raise ConflictError("the run has no lapsed reservation", reason="run_not_open")
        usage = replace(
            self.usage,
            reserved_microusd=0,
            cost_microusd=self.usage.cost_microusd + self.usage.reserved_microusd,
        )
        return self._next(now, usage=usage, worker_id=None, lease_until=None)

    def reserve_check(
        self,
        microusd: int,
        source: CostSource,
        *,
        worker_id: str,
        lease: timedelta,
        now: datetime,
    ) -> "AutomationRun":
        """Set aside the most the next call of the check can cost; one call at a time holds it."""

        if not self.holds_check(worker_id, now) or self.usage.reserved_microusd:
            raise ConflictError("the run is not held for a check call", reason="run_not_open")
        base = usage_for_check(self.usage, source)
        return self._next(
            now,
            lease_until=now + lease,
            usage=replace(base, reserved_microusd=microusd),
        )

    def settle_check(self, call: AiUsage, *, worker_id: str, now: datetime) -> "AutomationRun":
        """Book what a call cost, whoever holds the run: a call that ended after the lease ran out
        is still billed. The reservation is replaced only when `worker_id` is the worker that holds
        it; when another worker took the run over, its reservation stays and the cost is added."""

        self._require_checking()
        base = usage_for_check(self.usage, call.cost_source)
        counted = replace(call, cost_source=base.cost_source, model=None)
        booked = base.plus(counted)
        if self.worker_id != worker_id:
            booked = replace(booked, reserved_microusd=base.reserved_microusd)
        return self._next(now, usage=booked)

    def releasable(self, now: datetime, *, checker_enabled: bool, release_after: timedelta) -> bool:
        """The run waits for a check that nobody is doing: no worker holds it, and the check is
        off or the run has waited longer than `release_after` since it last changed."""

        if self.state is not RunState.CHECKING:
            return False
        if self.lease_until is not None and self.lease_until > now:
            return False
        return not checker_enabled or now - self.updated_at >= release_after

    def release_unchecked(self, *, now: datetime) -> "AutomationRun":
        """End the wait for a check that did not happen. A reservation whose worker went silent
        is booked as cost first. The caller shows the run's waiting cards as not checked."""

        run = self
        if self.holds_lapsed_check_reservation(now):
            run = self.abandon_check_reservation(now=now)
        return run.checked(now=now)

    def checked(self, *, now: datetime) -> "AutomationRun":
        """Every card of the run has its check, or was shown as not checked: the run is done."""

        self._require_checking()
        if self.usage.reserved_microusd:
            raise ConflictError("a check call is still reserved", reason="run_not_open")
        return self._next(
            now, state=RunState.DONE, stage=None, worker_id=None, lease_until=None, finished_at=now
        )

    def with_auto_applied(self, count: int, *, now: datetime) -> "AutomationRun":
        """The run with `count` more suggestions applied by the opt-in policy. Only a finished
        run takes it: the policy runs after the check, never while a run is open."""

        if self.state is not RunState.DONE:
            raise ConflictError("the run is not done", reason="run_not_open")
        if count < 0:
            raise ValidationError("the count of automatic applies cannot be negative")
        return self._next(now, auto_applied_count=self.auto_applied_count + count)


def usage_for_check(usage: AiUsage, source: CostSource) -> AiUsage:
    """The run's usage, ready to take the cost of a check booked under `source`.

    A client's own estimate never counts toward a cap, so a check that does cost something cannot
    be added to it: the estimate gives way to the check's usage. A run that already carries a cost
    the caps count keeps its source; any other takes the check's."""

    if usage.cost_source is CostSource.CLIENT_ESTIMATE:
        return AiUsage(model=usage.model, cost_source=source)
    if usage.cost_source in (CostSource.PROVIDER, CostSource.PRICE_TABLE):
        return usage
    return replace(usage, cost_source=source)


def clean_summary(value: str | None) -> str | None:
    """The summary as stored: one line, at most 300 characters, never empty."""

    if value is None:
        return None
    summary = normalise_line(value)[:MAX_SUMMARY_CHARS].rstrip()
    return summary or None


# --- occurrences --------------------------------------------------------------------------------


def scheduled_key(day: date) -> str:
    return f"d:{day.isoformat()}"


def manual_key(unique: str) -> str:
    return f"m:{unique}"


def scheduled_day(key: str) -> date | None:
    """The day of a scheduled occurrence key, or `None` for any other key."""

    if not key.startswith("d:"):
        return None
    try:
        return date.fromisoformat(key[2:])
    except ValueError:
        return None


def scheduled_run_is_due(
    cadence: Cadence | None, *, last_day: date | None, today: date, zone: tzinfo
) -> NothingDueReason | None:
    """Why no scheduled run is due today, or `None` when one is.

    Without a cadence the automation runs only when the owner asks. The first scheduled run is
    due as soon as it is asked for (the routine's own schedule says when); each later one is due
    on the day the cadence names after the previous scheduled day. Several missed days make one
    run, today's, never a catch-up of each.
    """

    if cadence is None:
        return NothingDueReason.NO_CADENCE
    if cadence.until is not None and today > cadence.until:
        return NothingDueReason.NOT_DUE
    if last_day is None:
        return None
    hour, minute = (int(part) for part in cadence.local_time.split(":"))
    anchor = datetime.combine(last_day, time(hour, minute), tzinfo=zone)
    following = cadence.rule().next_due_at(anchor, zone)
    if following is None or following.astimezone(zone).date() > today:
        return NothingDueReason.NOT_DUE
    return None


class StartAction(StrEnum):
    RETURN_EXISTING = "return_existing"
    NEW_ATTEMPT = "new_attempt"
    NOTHING_DUE = "nothing_due"


@dataclass(frozen=True, slots=True)
class StartPlan:
    action: StartAction
    run: AutomationRun | None = None
    """The run to return, or the one to end before the new attempt."""
    attempt: int = 1
    reason: NothingDueReason | None = None
    end_as: RunState | None = None
    """How `run` ends before a new attempt: lapsed when its lease ran out, else cancelled."""


def plan_start(attempts: Sequence[AutomationRun], *, spec_digest: str, now: datetime) -> StartPlan:
    """What starting an occurrence does, given the attempts it already has (oldest first).

    The same occurrence started twice returns the open run; a finished one has nothing due; a run
    that ended badly, or whose lease ran out, or that followed an older spec, is replaced by the
    next attempt, unless the three attempts are used.
    """

    if not attempts:
        return StartPlan(StartAction.NEW_ATTEMPT)
    latest = attempts[-1]
    if latest.state is RunState.DONE:
        return StartPlan(StartAction.NOTHING_DUE, latest, reason=NothingDueReason.ALREADY_DONE)
    if latest.state is RunState.CHECKING:
        return StartPlan(StartAction.NOTHING_DUE, latest, reason=NothingDueReason.CHECKING)
    next_attempt = latest.attempt + 1
    if latest.state in ACTIVE_STATES:
        if latest.spec_digest == spec_digest and (
            latest.holds_lease(now) or latest.state is RunState.QUEUED
        ):
            return StartPlan(StartAction.RETURN_EXISTING, latest)
        lapsed = latest.spec_digest == spec_digest
        end_as = RunState.LAPSED if lapsed else RunState.CANCELLED
        return _retry(latest, next_attempt, end_as)
    return _retry(None, next_attempt, None)


def _retry(ending: AutomationRun | None, attempt: int, end_as: RunState | None) -> StartPlan:
    if attempt > MAX_ATTEMPTS_PER_OCCURRENCE:
        raise ConflictError("every attempt at the occurrence is used", reason="ai_limit_reached")
    return StartPlan(StartAction.NEW_ATTEMPT, ending, attempt=attempt, end_as=end_as)
