"""One attempt at an AI Step: its states, what it reports and what it costs.

A run is created when a step is started, ends in a result, a question or a failure that the
owner then reviews, and never completes a step by itself: only the owner's acceptance does.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from sidekick.shared.errors import ConflictError, ValidationError
from sidekick.work.domain.ai_spec import MAX_RESULT_CHARS, ResultFormat, clean_text

MAX_SUMMARY_CHARS = 500
MAX_DIALOG_CHARS = 1_000
CLAUDE_CODE_LEASE = timedelta(minutes=30)
"""How long a started run may stay silent before another attempt may replace it."""
SERVER_QUEUE_TTL = timedelta(minutes=30)
"""How long a run may wait for the server to take it before it lapses without using an attempt."""
SERVER_LEASE = timedelta(minutes=15)
"""How long a run the server took may stay silent; each model call renews it."""


class RunnerKind(StrEnum):
    CLAUDE_CODE = "claude_code"
    SERVER = "server"


class AiRunState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    TO_REVIEW = "to_review"
    NEEDS_INPUT = "needs_input"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    REDO = "redo"
    """The owner asked for another attempt, with a comment for it."""
    ANSWERED = "answered"
    """The owner answered the run's question; another attempt carries the answer."""


ACTIVE_STATES = frozenset({AiRunState.QUEUED, AiRunState.RUNNING})
AWAITING_OWNER = frozenset({AiRunState.TO_REVIEW, AiRunState.NEEDS_INPUT})


class CostSource(StrEnum):
    PROVIDER = "provider"
    PRICE_TABLE = "price_table"
    CLIENT_ESTIMATE = "client_estimate"
    NONE = "none"


class FailureCategory(StrEnum):
    BLOCKED = "blocked"
    UNCLEAR_GOAL = "unclear_goal"
    TOOL_ERROR = "tool_error"
    BUDGET = "budget"
    OTHER = "other"
    PROVIDER = "provider"
    """The model provider could not be reached or refused the call."""
    REFUSED = "refused"
    """The model declined to answer."""
    INVALID_OUTPUT = "invalid_output"
    """The answer did not follow the schema or the step's limits."""


@dataclass(frozen=True, slots=True)
class ChecklistItem:
    """Whether the AI finished one of the step's Actions."""

    action_id: UUID
    done: bool


@dataclass(frozen=True, slots=True)
class AiRunResult:
    format: ResultFormat
    text: str
    summary: str
    checklist: tuple[ChecklistItem, ...] = ()

    def __post_init__(self) -> None:
        text = clean_text(self.text, multiline=True).strip()
        summary = " ".join(clean_text(self.summary).split())
        if not text or len(text) > MAX_RESULT_CHARS:
            raise ValidationError(f"a result has 1-{MAX_RESULT_CHARS} characters")
        if not summary or len(summary) > MAX_SUMMARY_CHARS:
            raise ValidationError(f"a result summary has 1-{MAX_SUMMARY_CHARS} characters")
        object.__setattr__(self, "text", text)
        object.__setattr__(self, "summary", summary)


@dataclass(frozen=True, slots=True)
class AiUsage:
    """What a run used. A client reports an estimate; a server runner reports its own count."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reserved_microusd: int = 0
    cost_microusd: int = 0
    cost_source: CostSource = CostSource.NONE
    model: str | None = None

    def __post_init__(self) -> None:
        counts = (
            self.input_tokens,
            self.output_tokens,
            self.cache_read_tokens,
            self.cache_write_tokens,
            self.reserved_microusd,
            self.cost_microusd,
        )
        if any(count < 0 for count in counts):
            raise ValidationError("usage counts cannot be negative")

    def plus(self, call: "AiUsage") -> "AiUsage":
        """This usage with one more call's tokens and cost added; the reservation is cleared."""

        return AiUsage(
            input_tokens=self.input_tokens + call.input_tokens,
            output_tokens=self.output_tokens + call.output_tokens,
            cache_read_tokens=self.cache_read_tokens + call.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + call.cache_write_tokens,
            reserved_microusd=0,
            cost_microusd=self.cost_microusd + call.cost_microusd,
            cost_source=call.cost_source,
            model=call.model or self.model,
        )


def dialog_text(value: str, label: str) -> str:
    cleaned = clean_text(value, multiline=True).strip()
    if not cleaned or len(cleaned) > MAX_DIALOG_CHARS:
        raise ValidationError(f"{label} has 1-{MAX_DIALOG_CHARS} characters")
    return cleaned


@dataclass(frozen=True, slots=True)
class AiStepRun:
    id: UUID
    owner_id: UUID
    task_id: UUID
    step_id: UUID
    attempt: int
    runner: RunnerKind
    state: AiRunState
    plan_digest: str
    created_at: datetime
    updated_at: datetime
    version: int = 1
    provider: str | None = None
    worker_id: str | None = None
    lease_until: datetime | None = None
    queued_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    reviewed_at: datetime | None = None
    result: AiRunResult | None = None
    question: str | None = None
    answer: str | None = None
    feedback: str | None = None
    usage: AiUsage = AiUsage()
    error_category: FailureCategory | None = None

    def __post_init__(self) -> None:
        if self.attempt < 1 or self.version < 1:
            raise ValidationError("run attempt and version must be positive")

    @classmethod
    def start(
        cls,
        *,
        run_id: UUID,
        owner_id: UUID,
        task_id: UUID,
        step_id: UUID,
        attempt: int,
        runner: RunnerKind,
        plan_digest: str,
        now: datetime,
        lease: timedelta = CLAUDE_CODE_LEASE,
    ) -> "AiStepRun":
        return cls(
            id=run_id,
            owner_id=owner_id,
            task_id=task_id,
            step_id=step_id,
            attempt=attempt,
            runner=runner,
            state=AiRunState.RUNNING,
            plan_digest=plan_digest,
            created_at=now,
            updated_at=now,
            queued_at=now,
            started_at=now,
            lease_until=now + lease,
        )

    @classmethod
    def queue(
        cls,
        *,
        run_id: UUID,
        owner_id: UUID,
        task_id: UUID,
        step_id: UUID,
        attempt: int,
        plan_digest: str,
        now: datetime,
    ) -> "AiStepRun":
        """A run for the server to take. It is not an attempt until the server starts it."""

        return cls(
            id=run_id,
            owner_id=owner_id,
            task_id=task_id,
            step_id=step_id,
            attempt=attempt,
            runner=RunnerKind.SERVER,
            state=AiRunState.QUEUED,
            plan_digest=plan_digest,
            created_at=now,
            updated_at=now,
            queued_at=now,
            lease_until=now + SERVER_QUEUE_TTL,
        )

    @property
    def active(self) -> bool:
        return self.state in ACTIVE_STATES

    def is_stale(self, now: datetime) -> bool:
        """An active run whose lease ran out: its runner went silent and another may replace it."""

        return self.active and self.lease_until is not None and self.lease_until <= now

    def _move(self, state: AiRunState, now: datetime, **changes: Any) -> "AiStepRun":
        return replace(self, state=state, updated_at=now, version=self.version + 1, **changes)

    def _require(self, *states: AiRunState) -> None:
        if self.state not in states:
            raise ConflictError("the run is not in a state this applies to", reason="run_not_open")

    def claim(
        self, worker_id: str, *, provider: str, model: str, cost_source: CostSource, now: datetime
    ) -> "AiStepRun":
        """The server takes a queued run that has not lapsed."""

        self._require(AiRunState.QUEUED)
        if self.lease_until is None or self.lease_until <= now:
            raise ConflictError("the run waited too long", reason="run_not_open")
        return self._move(
            AiRunState.RUNNING,
            now,
            worker_id=worker_id,
            provider=provider,
            started_at=now,
            lease_until=now + SERVER_LEASE,
            usage=replace(self.usage, model=model, cost_source=cost_source),
        )

    def reserve(self, microusd: int, *, now: datetime) -> "AiStepRun":
        """Set aside the most the next model call can cost; one call at a time holds it."""

        self._require(AiRunState.RUNNING)
        if self.usage.reserved_microusd:
            raise ConflictError("a model call is already reserved", reason="run_not_open")
        return self._move(
            self.state,
            now,
            lease_until=now + SERVER_LEASE,
            usage=replace(self.usage, reserved_microusd=microusd),
        )

    def settle(self, call: AiUsage, *, now: datetime) -> "AiStepRun":
        """Replace the reservation by what the call cost. Allowed in any state: a call that
        ended after the owner cancelled the run is still billed."""

        return replace(
            self,
            updated_at=now,
            version=self.version + 1,
            usage=self.usage.plus(call),
        )

    def holds_lapsed_reservation(self, now: datetime) -> bool:
        """Whether the server went silent with a model call reserved: a running run whose lease
        ran out, or a cancelled one whose reserved call never reported back."""

        lapsed = self.lease_until is not None and self.lease_until <= now
        if self.state is AiRunState.RUNNING:
            return lapsed
        return self.state is AiRunState.CANCELLED and lapsed and self.usage.reserved_microusd > 0

    def abandon(self, *, now: datetime) -> "AiStepRun":
        """End a run whose server went silent. A reserved call may have been billed, so the
        reservation is booked as cost."""

        if not self.holds_lapsed_reservation(now):
            raise ConflictError("the run is not stalled", reason="run_not_open")
        usage = replace(
            self.usage,
            reserved_microusd=0,
            cost_microusd=self.usage.cost_microusd + self.usage.reserved_microusd,
        )
        return self._move(
            AiRunState.CANCELLED,
            now,
            finished_at=self.finished_at or now,
            lease_until=None,
            usage=usage,
        )

    def report_result(self, result: AiRunResult, usage: AiUsage, *, now: datetime) -> "AiStepRun":
        self._require(AiRunState.RUNNING)
        return self._move(
            AiRunState.TO_REVIEW, now, result=result, usage=usage, finished_at=now, lease_until=None
        )

    def report_question(self, question: str, usage: AiUsage, *, now: datetime) -> "AiStepRun":
        self._require(AiRunState.RUNNING)
        return self._move(
            AiRunState.NEEDS_INPUT,
            now,
            question=dialog_text(question, "a question"),
            usage=usage,
            finished_at=now,
            lease_until=None,
        )

    def report_failure(
        self, category: FailureCategory, usage: AiUsage, *, now: datetime
    ) -> "AiStepRun":
        self._require(AiRunState.RUNNING)
        return self._move(
            AiRunState.FAILED,
            now,
            error_category=category,
            usage=usage,
            finished_at=now,
            lease_until=None,
        )

    def cancel(self, *, now: datetime) -> "AiStepRun":
        self._require(AiRunState.QUEUED, AiRunState.RUNNING)
        # A model call still reserved keeps the lease, so a server that dies before it reports
        # back has the reservation booked as cost when the lease runs out.
        lease = self.lease_until if self.usage.reserved_microusd else None
        return self._move(AiRunState.CANCELLED, now, finished_at=now, lease_until=lease)

    def accept(self, *, now: datetime) -> "AiStepRun":
        self._require(AiRunState.TO_REVIEW)
        return self._move(AiRunState.ACCEPTED, now, reviewed_at=now)

    def request_redo(self, comment: str | None, *, now: datetime) -> "AiStepRun":
        self._require(AiRunState.TO_REVIEW)
        feedback = dialog_text(comment, "a comment") if comment else None
        return self._move(AiRunState.REDO, now, reviewed_at=now, feedback=feedback)

    def reject(self, comment: str | None, *, now: datetime) -> "AiStepRun":
        self._require(AiRunState.TO_REVIEW, AiRunState.NEEDS_INPUT, AiRunState.FAILED)
        feedback = dialog_text(comment, "a comment") if comment else None
        return self._move(AiRunState.REJECTED, now, reviewed_at=now, feedback=feedback)

    def answer_question(self, answer: str, *, now: datetime) -> "AiStepRun":
        self._require(AiRunState.NEEDS_INPUT)
        return self._move(
            AiRunState.ANSWERED, now, reviewed_at=now, answer=dialog_text(answer, "an answer")
        )


@dataclass(frozen=True, slots=True)
class MoneyCaps:
    """The spending limits for AI runs, in millionths of a US dollar.

    A cost reported by a client (`client_estimate`) is an estimate on a plan that is not billed
    per call, so it never counts. A run on a local model (`none`) costs nothing; the owner may
    keep such runs out of the caps altogether.
    """

    task_microusd: int
    month_microusd: int
    local_models_exempt: bool = False

    def counts(self, source: CostSource) -> bool:
        """Whether a cost of this source counts toward the caps."""

        if source is CostSource.CLIENT_ESTIMATE:
            return False
        return not (source is CostSource.NONE and self.local_models_exempt)

    def breached_cap(
        self,
        *,
        source: CostSource,
        reserve_microusd: int,
        spent_on_task_microusd: int,
        spent_in_month_microusd: int,
        task_cap_microusd: int | None = None,
        spent_on_run_microusd: int = 0,
        run_budget_microusd: int | None = None,
    ) -> Literal["step", "task", "month"] | None:
        """The cap that reserving `reserve_microusd` more would pass, if any: the step's budget
        for this attempt, the task's cap or the month's. A source that does not count passes
        none."""

        if not self.counts(source):
            return None
        task_cap = self.task_microusd if task_cap_microusd is None else task_cap_microusd
        if (
            run_budget_microusd is not None
            and spent_on_run_microusd + reserve_microusd > run_budget_microusd
        ):
            return "step"
        if spent_on_task_microusd + reserve_microusd > task_cap:
            return "task"
        if spent_in_month_microusd + reserve_microusd > self.month_microusd:
            return "month"
        return None
