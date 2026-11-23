"""The model that checks what an automation proposes: Anthropic, OpenRouter or a local server."""

from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator

from sidekick.shared.config.ai_prices import require_prices_together
from sidekick.shared.config.environment import EnvironmentSettings
from sidekick.shared.private_endpoint import is_hosted_model_url, validate_model_base_url


class AiCheckSettings(EnvironmentSettings):
    ai_check_provider: Literal["off", "anthropic", "openai_compat"] = Field(
        default="off",
        description="The model that checks proposals: off, anthropic (the AI worker's Anthropic "
        "key), or openai_compat (OpenRouter with your own key, or a local OpenAI-compatible "
        "server such as Ollama or LM Studio).",
    )
    ai_check_mode: Literal["chat", "decisions"] = Field(
        default="chat",
        description="How the check model is asked: chat (a structured JSON answer, for Anthropic "
        "or a chat model) or decisions (typed yes/no questions answered with probabilities, "
        "for a decision model such as typesafe/jev-1.14 through OpenRouter).",
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
    ai_check_uncertain_threshold: float = Field(
        default=0.10,
        gt=0,
        lt=1,
        description="Decisions mode: a proposal whose highest risk probability is at or above "
        "this is called uncertain and leaves the high-confidence group.",
    )
    ai_check_suspicious_threshold: float = Field(
        default=0.30,
        gt=0,
        lt=1,
        description="Decisions mode: a proposal whose highest risk probability is at or above "
        "this is called suspicious; it needs a second tap and no model may decide it.",
    )
    ai_check_release_after_minutes: int = Field(
        default=60,
        ge=5,
        le=1_440,
        description="A run that has waited this long for its check without any worker taking it "
        "is ended and its proposals are shown as not checked, so that they can be decided.",
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
        if self.ai_check_uncertain_threshold > self.ai_check_suspicious_threshold:
            raise ValueError(
                "SIDEKICK_AI_CHECK_UNCERTAIN_THRESHOLD cannot be above "
                "SIDEKICK_AI_CHECK_SUSPICIOUS_THRESHOLD"
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

    @model_validator(mode="after")
    def validate_ai_check_mode(self) -> Self:
        """Decisions mode exists on the hosted origin only, with the owner's own key."""

        if self.ai_check_provider == "off" or self.ai_check_mode == "chat":
            return self
        if self.ai_check_provider != "openai_compat":
            raise ValueError("SIDEKICK_AI_CHECK_MODE=decisions needs the openai_compat provider")
        if not is_hosted_model_url(self.ai_check_base_url):
            raise ValueError(
                "SIDEKICK_AI_CHECK_MODE=decisions is answered by the hosted origin only"
            )
        return self
