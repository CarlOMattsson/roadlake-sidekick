"""Configuration for the manual local seeder.

Seed configuration is deliberately kept out of the application's own `.env`.
`sidekick.shared.config.Settings` forbids unknown keys, which means an extra
`SIDEKICK_SEED_*` line in `.env` would stop FastAPI from starting at all. The seeder
therefore reads its own `.env.seed` file (see `.env.seed.example`). The names are not
usable as process environment variables: `Settings` rejects any undeclared `SIDEKICK_`
variable, and the seeder loads it first.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SeedSettings(BaseSettings):
    """Local seed identity, resolved from `.env.seed`, environment, or defaults."""

    model_config = SettingsConfigDict(
        env_prefix="SIDEKICK_SEED_",
        env_file=".env.seed",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    login: str = Field(default="local-user", min_length=1, max_length=200)
    display_name: str = Field(default="Local User", min_length=1, max_length=200)


def get_seed_settings() -> SeedSettings:
    return SeedSettings()
