"""The limits on AI Steps: spending caps, attempts and how often Claude Code may start a step."""

from pydantic import Field

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
    ai_max_attempts_per_step: int = Field(
        default=3, ge=1, le=10, description="Most attempts one AI step may have."
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
