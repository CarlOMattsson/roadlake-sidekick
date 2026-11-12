"""Secrets that sign cursors and hash tokens."""

import secrets
from typing import Self

from pydantic import Field, model_validator

from sidekick.shared.config.environment import EnvironmentSettings
from sidekick.shared.config.validation import is_unusable_secret

# Pagination-cursor key for a process that has no configured cursor signing secret (development and
# test only; production refuses to start without one). Random per process, so no constant
# signing key ever sits in the source. Cursors issued before a restart simply stop validating.
_PROCESS_CURSOR_KEY = secrets.token_urlsafe(32)


class SigningSettings(EnvironmentSettings):
    cursor_signing_secret: str = Field(
        default="development-session-secret-change-me-do-not-use-in-production",
        min_length=32,
        repr=False,
        description="Secret that signs pagination cursors; must be configured in production.",
    )
    token_pepper: str = Field(
        default="development-token-pepper-change-me-do-not-use-in-production",
        min_length=32,
        repr=False,
        description="Pepper mixed into access-token hashes; must be configured in production.",
    )

    @model_validator(mode="after")
    def reject_unsafe_production_secrets(self) -> Self:
        if self.environment == "production" and is_unusable_secret(self.cursor_signing_secret):
            raise ValueError("production cursor signing secret must be configured")
        if self.environment == "production" and is_unusable_secret(self.token_pepper):
            raise ValueError("production token pepper must be configured")
        return self

    @property
    def cursor_signing_key(self) -> str:
        """Key that signs pagination cursors: the configured secret, never a constant.

        A placeholder secret only survives validation outside production; there the key is
        random per process rather than the guessable placeholder text.
        """

        if is_unusable_secret(self.cursor_signing_secret):
            return _PROCESS_CURSOR_KEY
        return self.cursor_signing_secret
