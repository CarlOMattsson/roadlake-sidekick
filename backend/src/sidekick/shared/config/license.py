"""The licence key the instance verifies."""

from pydantic import Field

from sidekick.shared.config.base import SettingsGroup


class LicenseSettings(SettingsGroup):
    license_public_key: str | None = Field(
        default=None,
        description="Licensor's base64 Ed25519 public key; unset uses the built-in constant.",
    )
