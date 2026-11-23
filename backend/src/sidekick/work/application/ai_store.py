"""What the AI Step use cases share: the store port, the limits and the views they return."""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sidekick.shared.config import Settings
from sidekick.shared.errors import ConflictError
from sidekick.shared.types import TxSession
from sidekick.tasks.domain import Task
from sidekick.work.application.steps_service import StepsStore
from sidekick.work.domain import Action, Step
from sidekick.work.domain.ai_cost import ModelPrice, price_for
from sidekick.work.domain.ai_plan import AiStepStatus, PlanState, RunHistory
from sidekick.work.domain.ai_runs import AiStepRun, CostSource, MoneyCaps, RunnerKind

MICROUSD_PER_USD = 1_000_000
MAX_STEPS_PER_TASK = 1000
LINK_NAMES_LIMIT = 25


class AiStepsStore(StepsStore, Protocol):
    """The Step and Action reads and writes plus the Task save and the run rows."""

    def save_task(
        self, session: TxSession, task: Task, expected_version: int | None = None
    ) -> None: ...
    def list_actions_for_steps(
        self,
        session: TxSession,
        owner_id: UUID,
        step_ids: tuple[UUID, ...],
        per_step_limit: int = 1000,
        include_archived: bool = False,
    ) -> dict[UUID, list[Action]]: ...
    def project_titles(
        self, session: TxSession, owner_id: UUID, project_ids: tuple[UUID, ...]
    ) -> dict[UUID, str]: ...
    def step_task_id(self, session: TxSession, owner_id: UUID, step_id: UUID) -> UUID: ...
    def get_ai_run(self, session: TxSession, owner_id: UUID, run_id: UUID) -> AiStepRun: ...
    def previous_ai_run(
        self,
        session: TxSession,
        owner_id: UUID,
        step_id: UUID,
        attempt: int,
        since: datetime | None = None,
    ) -> AiStepRun | None: ...
    def save_ai_run(
        self, session: TxSession, run: AiStepRun, expected_version: int | None = None
    ) -> None: ...
    def run_histories(
        self,
        session: TxSession,
        owner_id: UUID,
        step_ids: tuple[UUID, ...],
        since: datetime | None = None,
    ) -> dict[UUID, RunHistory]: ...
    def count_ai_runs_since(
        self, session: TxSession, owner_id: UUID, runner: RunnerKind, since: datetime
    ) -> int: ...
    def sum_ai_cost_since(
        self,
        session: TxSession,
        owner_id: UUID,
        since: datetime,
        sources: Collection[CostSource],
        task_id: UUID | None = None,
    ) -> int: ...
    def lock_owner_spend(self, session: TxSession, owner_id: UUID) -> None: ...
    def next_queued_server_run(self, session: TxSession, now: datetime) -> AiStepRun | None: ...
    def list_stalled_server_runs(
        self, session: TxSession, now: datetime, limit: int
    ) -> list[AiStepRun]: ...
    def list_tasks_with_approved_plans(
        self, session: TxSession, owner_id: UUID, limit: int, from_id: UUID | None = None
    ) -> list[Task]: ...
    def task_contact_names(
        self, session: TxSession, owner_id: UUID, task_id: UUID, limit: int
    ) -> list[str]: ...
    def task_reference_titles(
        self, session: TxSession, owner_id: UUID, task_id: UUID, limit: int
    ) -> list[str]: ...


@dataclass(frozen=True, slots=True)
class AiLimits:
    """The limits on AI Steps, in the units the domain uses (millionths of a dollar)."""

    default_task_cap_microusd: int
    monthly_cap_microusd: int
    max_attempts_per_step: int
    claude_code_starts_per_day: int
    server_starts_per_day: int
    local_models_exempt: bool

    @classmethod
    def from_settings(cls, settings: Settings) -> "AiLimits":
        return cls(
            default_task_cap_microusd=round(settings.ai_default_task_cap_usd * MICROUSD_PER_USD),
            monthly_cap_microusd=round(settings.ai_monthly_cap_usd * MICROUSD_PER_USD),
            max_attempts_per_step=settings.ai_max_attempts_per_step,
            claude_code_starts_per_day=settings.ai_claude_code_starts_per_day,
            server_starts_per_day=settings.ai_server_starts_per_day,
            local_models_exempt=settings.ai_local_models_exempt_from_cap,
        )

    def money_caps(self) -> MoneyCaps:
        return MoneyCaps(
            task_microusd=self.default_task_cap_microusd,
            month_microusd=self.monthly_cap_microusd,
            local_models_exempt=self.local_models_exempt,
        )

    def task_cap(self, task: Task) -> int:
        """The cap that applies to the Task: the owner's own at approval, else the default."""

        return task.ai_task_cap_microusd or self.default_task_cap_microusd


@dataclass(frozen=True, slots=True)
class ServerRunnerConfig:
    """Whether and how this server runs AI steps itself."""

    enabled: bool
    model: str
    price: ModelPrice | None
    max_output_tokens: int
    provider: str = "anthropic"

    @classmethod
    def from_settings(cls, settings: Settings) -> "ServerRunnerConfig":
        return cls(
            enabled=settings.ai_runner_enabled,
            model=settings.ai_model,
            price=price_for(
                settings.ai_model,
                input=settings.ai_price_input_usd_per_mtok,
                output=settings.ai_price_output_usd_per_mtok,
                cache_write=settings.ai_price_cache_write_usd_per_mtok,
                cache_read=settings.ai_price_cache_read_usd_per_mtok,
            ),
            max_output_tokens=settings.ai_max_output_tokens,
        )

    @property
    def available(self) -> bool:
        """A run can be queued: the owner turned it on and the model's cost can be counted."""

        return self.enabled and self.price is not None

    def require_price(self) -> ModelPrice:
        """The model's price, or the refusal that running AI steps on the server is off."""

        if not self.enabled or self.price is None:
            raise ConflictError("running AI steps on the server is off", reason="ai_runner_off")
        return self.price


@dataclass(frozen=True, slots=True)
class AiPlanStepView:
    """One step of a plan: the step, its active Actions and, for an AI step, where it stands."""

    step: Step
    actions: Sequence[Action]
    status: AiStepStatus | None
    history: RunHistory
    server_startable: bool = False
    """The server could run this step now: it is next, the runner is on and the step suits it."""


@dataclass(frozen=True, slots=True)
class ServerRunInfo:
    """What the owner needs to decide on running a step on the server: whether it can, and what
    the Task (in its current cycle) and the month have cost against their caps."""

    available: bool
    task_spent_microusd: int
    month_spent_microusd: int
    month_cap_microusd: int


@dataclass(frozen=True, slots=True)
class AiPlanView:
    task: Task
    state: PlanState
    digest: str
    task_cap_microusd: int
    steps: Sequence[AiPlanStepView]
    server: ServerRunInfo | None = None


@dataclass(frozen=True, slots=True)
class AiStepEntry:
    """An AI step of an approved plan, for the list a runner reads."""

    task: Task
    step: Step
    status: AiStepStatus
    history: RunHistory
    startable: bool


@dataclass(frozen=True, slots=True)
class AiStepPage:
    items: Sequence[AiStepEntry]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class StartedAiStep:
    run: AiStepRun
    step: Step
    brief: str
    budget_microusd: int
    max_turns: int


@dataclass(frozen=True, slots=True)
class AiUsageSummary:
    """What AI runs cost this calendar month and how many Claude Code starts today used.

    `spent_microusd` is what counts toward the monthly cap; `client_estimate_microusd` is what
    Claude Code reported for runs that are not billed per call, which never counts.
    """

    month_starts_at: datetime
    spent_microusd: int
    client_estimate_microusd: int
    monthly_cap_microusd: int
    starts_today: int
    starts_per_day_cap: int
