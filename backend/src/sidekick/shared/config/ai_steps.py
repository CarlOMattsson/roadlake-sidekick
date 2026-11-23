"""The limits on AI Steps: spending caps, attempts and how often Claude Code may start a step."""

from typing import Self

from pydantic import Field, model_validator

from sidekick.shared.config.base import SettingsGroup


class AiStepSettings(SettingsGroup):
    ai_default_task_cap_usd: float = Field(
        default=2.0,
        gt=0,
        le=1_000,
        description="Spending cap per task, in US dollars, for AI steps the owner approves "
        "without naming one.",
    )
    ai_monthly_cap_usd: float = Field(
        default=50.0,
        gt=0,
        le=100_000,
        description="Spending cap per calendar month, in US dollars, for AI steps that bill "
        "per call.",
    )
    ai_automation_monthly_cap_usd: float = Field(
        default=15.0,
        gt=0,
        le=100_000,
        description="Part of the monthly cap, in US dollars, that automations may spend; no "
        "automation may budget one run above it. When left unset it is 15 or the monthly cap, "
        "whichever is lower. A value above the monthly cap is refused.",
    )
    ai_automation_runs_per_day: int = Field(
        default=20,
        ge=1,
        le=1_000,
        description="Most automation runs that may be started per day, all automations together.",
    )
    ai_max_attempts_per_step: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Most attempts one AI step may have in a cycle of its task; a repeating task "
        "gets them back each time it is completed.",
    )
    ai_claude_code_starts_per_day: int = Field(
        default=50,
        ge=1,
        le=1_000,
        description="Most AI steps the owner's Claude Code may start per day.",
    )
    ai_local_models_exempt_from_cap: bool = Field(
        default=False,
        description="Keeps runs on a local model, which cost nothing, out of the spending caps.",
    )

    @model_validator(mode="after")
    def _automation_cap_is_inside_the_monthly_cap(self) -> Self:
        if "ai_automation_monthly_cap_usd" not in self.model_fields_set:
            self.ai_automation_monthly_cap_usd = min(
                self.ai_automation_monthly_cap_usd, self.ai_monthly_cap_usd
            )
        if self.ai_automation_monthly_cap_usd > self.ai_monthly_cap_usd:
            raise ValueError(
                "SIDEKICK_AI_AUTOMATION_MONTHLY_CAP_USD cannot be above SIDEKICK_AI_MONTHLY_CAP_USD"
            )
        return self
