"""The application database: URL and per-connection time budgets."""

from typing import Self

from pydantic import Field, model_validator

from sidekick.shared.config.environment import EnvironmentSettings
from sidekick.shared.db_timeouts import DatabaseTimeouts


class DatabaseSettings(EnvironmentSettings):
    database_url: str = Field(
        default="postgresql+psycopg://sidekick_app:sidekick_app@localhost:5432/sidekick",
        repr=False,
        description="SQLAlchemy URL of the application database; mandatory in production.",
    )
    db_connect_timeout_seconds: int = Field(
        default=10,
        ge=1,
        le=120,
        description="Seconds an application database connection may take to open.",
    )
    db_statement_timeout_ms: int = Field(
        default=30_000,
        ge=0,
        le=3_600_000,
        description="Milliseconds a statement may run (0 = no limit); migrations are not bound.",
    )
    db_lock_timeout_ms: int = Field(
        default=5_000,
        ge=0,
        le=600_000,
        description="Milliseconds a statement may wait for a lock (0 = no limit).",
    )
    db_idle_in_transaction_timeout_ms: int = Field(
        default=60_000,
        ge=0,
        le=3_600_000,
        description="Milliseconds a session may sit idle inside a transaction (0 = no limit).",
    )

    @model_validator(mode="after")
    def reject_implicit_production_database(self) -> Self:
        if self.environment == "production" and "database_url" not in self.model_fields_set:
            # The development default carries a well-known password and a local host; a production
            # process that lost its variable must stop, not quietly aim at it.
            raise ValueError("SIDEKICK_DATABASE_URL must be set explicitly in production")
        return self

    @property
    def database_timeouts(self) -> DatabaseTimeouts:
        return DatabaseTimeouts(
            connect_seconds=self.db_connect_timeout_seconds,
            statement_ms=self.db_statement_timeout_ms,
            lock_ms=self.db_lock_timeout_ms,
            idle_in_transaction_ms=self.db_idle_in_transaction_timeout_ms,
        )
