"""Running an approved AI step on the server with the owner's own Anthropic key (opt-in)."""

from typing import Self

from pydantic import Field, SecretStr, model_validator

from sidekick.shared.config.ai_prices import require_prices_together
from sidekick.shared.config.base import SettingsGroup


class AiRunnerSettings(SettingsGroup):
    ai_runner_enabled: bool = Field(
        default=False,
        description="Lets the owner run an approved AI step on the server. Needs the `ai` "
        "Compose profile and the owner's own Anthropic API key.",
    )
    ai_model: str = Field(
        default="claude-opus-5-5",
        min_length=1,
        max_length=120,
        description="The Anthropic model that runs AI steps on the server.",
    )
    ai_anthropic_api_key: SecretStr | None = Field(
        default=None,
        repr=False,
        description="The owner's Anthropic API key. Only the AI worker may hold it; the API "
        "and the other workers refuse to start in production when they see it.",
    )
    ai_max_output_tokens: int = Field(
        default=16_000,
        ge=256,
        le=32_000,
        description="Most tokens one model call may produce.",
    )
    ai_server_starts_per_day: int = Field(
        default=50,
        ge=1,
        le=1_000,
        description="Most AI steps the owner may run on the server per day.",
    )
    ai_request_timeout_seconds: int = Field(
        default=300,
        ge=30,
        le=300,
        description=(
            "How long one model call may take; at most the five minutes the worker is given to "
            "finish a call when it is stopped."
        ),
    )
    ai_poll_seconds: int = Field(
        default=5, ge=1, le=60, description="How often the AI worker looks for a queued run."
    )
    ai_price_input_usd_per_mtok: float | None = Field(
        default=None,
        gt=0,
        description="Price of input tokens in US dollars per million tokens. Set all four "
        "prices only for a model that Sidekick has no built-in price for.",
    )
    ai_price_output_usd_per_mtok: float | None = Field(
        default=None, gt=0, description="Price of output tokens in US dollars per million tokens."
    )
    ai_price_cache_write_usd_per_mtok: float | None = Field(
        default=None, gt=0, description="Price of cache-write tokens, per million tokens."
    )
    ai_price_cache_read_usd_per_mtok: float | None = Field(
        default=None, gt=0, description="Price of cache-read tokens, per million tokens."
    )

    @model_validator(mode="after")
    def _prices_are_given_together(self) -> Self:
        require_prices_together(
            "SIDEKICK_AI_PRICE_",
            (
                self.ai_price_input_usd_per_mtok,
                self.ai_price_output_usd_per_mtok,
                self.ai_price_cache_write_usd_per_mtok,
                self.ai_price_cache_read_usd_per_mtok,
            ),
        )
        return self
