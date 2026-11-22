"""The model that checks what an automation proposes: Anthropic, OpenRouter or a local server."""

from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator

from sidekick.shared.config.ai_prices import require_prices_together
from sidekick.shared.config.environment import EnvironmentSettings
from sidekick.shared.private_endpoint import validate_model_base_url


class AiCheckSettings(EnvironmentSettings):
    ai_check_provider: Literal["off", "anthropic", "openai_compat"] = Field(
        default="off",
        description="The model that checks proposals: off, anthropic (the AI worker's Anthropic "
        "key), or openai_compat (OpenRouter with your own key, or a local OpenAI-compatible "
        "server such as Ollama or LM Studio).",
    )
    ai_check_model: str = Field(
        default="",
        max_length=120,
        description="The model the check runs on; required unless the check is off.",
    )
    ai_check_base_url: str = Field(
        default="",
        description="Base URL of the OpenAI-compatible server: https://openrouter.ai, or a "
        "private address (for example `http://ollama.internal:11434`); required for openai_compat.",
    )
    ai_check_api_key: SecretStr | None = Field(
        default=None,
        repr=False,
        description="Key for an OpenAI-compatible server (required for OpenRouter, optional for a "
        "local one). Only the AI worker may hold it; the API and the other workers refuse to "
        "start in production when they see it.",
    )
    ai_check_allow_loopback: bool = Field(
        default=False,
        description="Allows a loopback address for a local model server on a development "
        "machine; refused in production.",
    )
    ai_check_max_response_bytes: int = Field(
        default=1_048_576,
        ge=4_096,
        le=16_777_216,
        description="Largest model response body read after decompression; larger is refused.",
    )
    ai_check_price_input_usd_per_mtok: float | None = Field(
        default=None,
        gt=0,
        description="Price of the check model's input tokens in US dollars per million tokens. "
        "Needed for OpenRouter and for a model Sidekick has no built-in price for; set all four "
        "prices or none. A private server with no price is counted as free.",
    )
    ai_check_price_output_usd_per_mtok: float | None = Field(
        default=None, gt=0, description="Price of the check model's output tokens, per million."
    )
    ai_check_price_cache_write_usd_per_mtok: float | None = Field(
        default=None,
        gt=0,
        description="Price of the check model's cache-write tokens.",
    )
    ai_check_price_cache_read_usd_per_mtok: float | None = Field(
        default=None, gt=0, description="Price of the check model's cache-read tokens."
    )

    @model_validator(mode="after")
    def validate_ai_check(self) -> Self:
        """The check fails closed: a public, loopback or incoherent destination never starts."""

        if self.ai_check_allow_loopback and self.environment == "production":
            raise ValueError("SIDEKICK_AI_CHECK_ALLOW_LOOPBACK is not valid in production")
        require_prices_together(
            "SIDEKICK_AI_CHECK_PRICE_",
            (
                self.ai_check_price_input_usd_per_mtok,
                self.ai_check_price_output_usd_per_mtok,
                self.ai_check_price_cache_write_usd_per_mtok,
                self.ai_check_price_cache_read_usd_per_mtok,
            ),
        )
        if self.ai_check_base_url.strip():
            self.ai_check_base_url = validate_model_base_url(
                self.ai_check_base_url,
                label="AI check model",
                allow_loopback=self.ai_check_allow_loopback,
            )
        if self.ai_check_provider == "off":
            return self
        if not self.ai_check_model.strip():
            raise ValueError("SIDEKICK_AI_CHECK_MODEL is required when the AI check is on")
        if self.ai_check_provider == "openai_compat" and not self.ai_check_base_url:
            raise ValueError(
                "SIDEKICK_AI_CHECK_BASE_URL is required when the AI check uses openai_compat"
            )
        return self
