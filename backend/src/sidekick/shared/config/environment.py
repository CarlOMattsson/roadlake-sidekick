"""Deployment mode: the root of every settings group that depends on it."""

import os
from typing import Any, Literal, Self, cast

from pydantic import Field, model_validator

from sidekick.shared.config.base import SettingsGroup

# Settings renamed before the first release. The old name is not accepted any more; startup stops
# and names the new one, so an env file written before the rename fails loudly, not silently.
RENAMED_SETTINGS = {"SESSION_SECRET": "CURSOR_SIGNING_SECRET"}


def _renamed_hint(prefix: str, names: list[str]) -> str:
    """One sentence naming the current name of each renamed setting in `names` (names only)."""

    return "; ".join(
        f"{name} was renamed to {prefix}{RENAMED_SETTINGS[name.removeprefix(prefix)]}"
        for name in names
        if name.removeprefix(prefix) in RENAMED_SETTINGS
    )


def _reject_renamed_keys(prefix: str, data: object) -> None:
    """Raise when a dotenv entry still uses a renamed setting name."""

    if isinstance(data, dict):
        # A dotenv entry arrives with its prefix, a field name without it.
        keys = [str(key).upper().removeprefix(prefix) for key in cast(dict[str, Any], data)]
        renamed = [f"{prefix}{key}" for key in keys if key in RENAMED_SETTINGS]
        if renamed:
            raise ValueError(_renamed_hint(prefix, renamed))


class EnvironmentSettings(SettingsGroup):
    """The deployment mode, and the one check that every prefixed variable is declared.

    `repr=False` on the secrets in the groups keeps them out of `repr(settings)` and logs.
    `Settings` inherits the groups, so every field keeps its flat `SIDEKICK_<NAME>` environment
    variable and its `settings.<name>` access.
    """

    environment: Literal["development", "test", "production"] = Field(
        default="development",
        description="Deployment mode; production refuses to start with placeholder secrets.",
    )

    @model_validator(mode="before")
    @classmethod
    def reject_renamed_dotenv_names(cls, data: object) -> object:
        """Stop on a renamed setting in a dotenv file (the process environment is checked below)."""

        _reject_renamed_keys(cls.model_config.get("env_prefix") or "", data)
        return data

    @model_validator(mode="after")
    def reject_undeclared_environment(self) -> Self:
        prefix = self.model_config.get("env_prefix") or ""
        declared = {f"{prefix}{name}".upper() for name in type(self).model_fields}
        # Test-database variables deliberately sit outside Settings: they choose a
        # destructive-test target, not an application configuration value. Every other
        # prefixed process variable must name a declared setting so a typo cannot silently
        # leave a production route on its default.
        undeclared = sorted(
            name
            for name in os.environ
            if name.startswith(prefix)
            and name not in declared
            and not name.startswith(f"{prefix}TEST_")
        )
        if undeclared:
            hint = _renamed_hint(prefix, undeclared)
            raise ValueError(
                "undeclared SIDEKICK_ setting environment variables: "
                + ", ".join(undeclared)
                + (f" ({hint})" if hint else "")
            )
        return self
