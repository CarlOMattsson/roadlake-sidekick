"""The base class of every settings group: the one place the loading rules are declared."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class SettingsGroup(BaseSettings):
    """Common base of the groups that `Settings` combines.

    The groups only exist to keep the file small enough to review; they are never read on their
    own. Declaring the configuration here gives every group, and so `Settings`, the same flat
    `SIDEKICK_<NAME>` variables.
    """

    # `hide_input_in_errors`: a validation error must never quote the offending input, which for a
    # misconfigured secret is the secret.
    model_config = SettingsConfigDict(
        env_prefix="SIDEKICK_", env_file=".env", extra="forbid", hide_input_in_errors=True
    )
