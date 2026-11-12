"""Deployment mode: the root of every settings group that depends on it."""

import os
from typing import Literal, Self

from pydantic import Field, model_validator

from sidekick.shared.config.base import SettingsGroup
from sidekick.shared.config.secret_files import secret_file_variable_names


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

    @model_validator(mode="after")
    def reject_undeclared_environment(self) -> Self:
        prefix = self.model_config.get("env_prefix") or ""
        declared = {f"{prefix}{name}".upper() for name in type(self).model_fields}
        declared |= secret_file_variable_names(type(self))
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
            raise ValueError(
                "undeclared SIDEKICK_ setting environment variables: " + ", ".join(undeclared)
            )
        return self
