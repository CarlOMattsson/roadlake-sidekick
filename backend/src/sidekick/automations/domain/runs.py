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
from sidekick.work.domain.ai_runs import AiUsage

MAX_ATTEMPTS_PER_OCCURRENCE = 3
MAX_SUGGESTIONS_PER_CALL = 25
RUN_LEASE = timedelta(minutes=30)
"""How long a runner may be silent before another start takes the occurrence over."""
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
