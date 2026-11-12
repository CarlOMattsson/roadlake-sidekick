"""Derived memory and the Hindsight provider."""

from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator

from sidekick.shared.config.environment import EnvironmentSettings
from sidekick.shared.config.validation import secret_is_blank
from sidekick.shared.private_endpoint import validate_private_base_url


class MemorySettings(EnvironmentSettings):
    memory_enabled: bool = Field(
        default=False,
        description="Turns on derived memory; nothing is derived or sent to Hindsight while off.",
    )
    memory_provider: Literal["fake", "hindsight"] = Field(
        default="fake",
        description="Memory provider: in-process fake, or hindsight (needs URL, token, key).",
    )
    memory_ingest_enabled: bool = Field(
        default=True,
        description="Kill switch for sending: false stops every retain while recall keeps working.",
    )
    memory_orphan_sweep_enabled: bool = Field(
        default=False,
        description="Deletes Sidekick-format memory banks that no living user derives.",
    )
    memory_hindsight_base_url: str = Field(
        default="", description="Private base URL of the Hindsight server; required for hindsight."
    )
    memory_hindsight_api_token: SecretStr | None = Field(
        default=None, description="API token for Hindsight; required when memory uses hindsight."
    )
    memory_id_derivation_key: SecretStr | None = Field(
        default=None,
        description="Key from which per-user memory bank ids are derived; required for hindsight.",
    )
    memory_hindsight_max_response_bytes: int = Field(
        default=1_048_576,
        ge=1_024,
        le=16_777_216,
        description="Largest Hindsight response body read after decompression; larger is refused.",
    )
    memory_allow_loopback: bool = Field(
        default=False,
        description="Allows a loopback Hindsight address for a sandbox; refused in production.",
    )
    memory_quiet_seconds: int = Field(
        default=600,
        ge=600,
        le=86_400,
        description="Quiet period after a change before a record is sent to memory (minimum 600).",
    )
    memory_daily_retain_cap: int = Field(
        default=40,
        ge=0,
        le=1000,
        description="Most records sent to memory per owner and day by live changes.",
    )
    memory_backfill_daily_cap: int = Field(
        default=150,
        ge=0,
        le=5000,
        description="Most records sent to memory per owner and day by the backfill.",
    )
    memory_daily_char_cap: int = Field(
        default=400_000,
        ge=0,
        le=10_000_000,
        description="Characters sent to the memory provider per owner and day, live and backfill.",
    )

    @model_validator(mode="after")
    def validate_memory(self) -> Self:
        """Memory fails closed: a loopback, public or incoherent destination never starts."""

        if self.memory_allow_loopback and self.environment == "production":
            raise ValueError("SIDEKICK_MEMORY_ALLOW_LOOPBACK is not valid in production")
        if (
            self.memory_enabled
            and self.environment == "production"
            and self.memory_provider == "fake"
        ):
            # The fake provider keeps nothing durable; production memory must reach Hindsight.
            raise ValueError("SIDEKICK_MEMORY_PROVIDER=fake is not valid in production")
        if self.memory_hindsight_base_url.strip():
            # The same rule as the memory adapter, with the loopback exemption granted only by the
            # explicit flag, which production has already refused above.
            self.memory_hindsight_base_url = validate_private_base_url(
                self.memory_hindsight_base_url,
                label="Memory Hindsight",
                allow_loopback=self.memory_allow_loopback,
            )
        if self.memory_enabled and self.memory_provider == "hindsight":
            if not self.memory_hindsight_base_url.strip():
                raise ValueError(
                    "SIDEKICK_MEMORY_HINDSIGHT_BASE_URL is required when memory uses hindsight"
                )
            if secret_is_blank(self.memory_hindsight_api_token):
                raise ValueError(
                    "SIDEKICK_MEMORY_HINDSIGHT_API_TOKEN is required when memory uses hindsight"
                )
            if secret_is_blank(self.memory_id_derivation_key):
                raise ValueError(
                    "SIDEKICK_MEMORY_ID_DERIVATION_KEY is required when memory uses hindsight"
                )
        return self
