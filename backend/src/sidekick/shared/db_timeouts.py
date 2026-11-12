"""Time budgets for database connections, statements and locks.

Kept free of other Sidekick imports so both the settings and the persistence layer can use it.
A value of 0 for a millisecond budget means "no limit" (PostgreSQL's own meaning).
"""

from dataclasses import dataclass, replace
from typing import Any

# SQLSTATE codes PostgreSQL raises when one of the budgets below is exhausted.
_TIMEOUT_SQLSTATES = {
    "57014": "statement_timeout",
    "55P03": "lock_timeout",
    "25P03": "idle_in_transaction_session_timeout",
}


@dataclass(frozen=True)
class DatabaseTimeouts:
    connect_seconds: int = 10
    statement_ms: int = 30_000
    lock_ms: int = 5_000
    idle_in_transaction_ms: int = 60_000

    def unbounded_statements(self) -> "DatabaseTimeouts":
        """For long maintenance work (backup, export, import): no statement or idle limit.

        The connect and lock budgets stay, so a stuck connection or a lock queue still fails
        instead of waiting forever. Migrations run through their own migrator connection and
        never pass through here.
        """

        return replace(self, statement_ms=0, idle_in_transaction_ms=0)

    def connect_args(self) -> dict[str, Any]:
        return {"connect_timeout": self.connect_seconds}

    def session_settings(self) -> tuple[tuple[str, str], ...]:
        """The server settings applied to every new connection, as (name, value) pairs."""

        return (
            ("statement_timeout", str(self.statement_ms)),
            ("lock_timeout", str(self.lock_ms)),
            ("idle_in_transaction_session_timeout", str(self.idle_in_transaction_ms)),
        )


def database_timeout_reason(error: BaseException) -> str | None:
    """The exhausted budget's name if `error` is a database timeout, else None.

    Workers use this to log a timeout as a retryable condition (the next cycle tries again)
    without ever logging the statement or its parameters.
    """

    current: BaseException | None = error
    for _ in range(4):
        if current is None:
            return None
        state = getattr(current, "sqlstate", None) or getattr(
            getattr(current, "orig", None), "sqlstate", None
        )
        if isinstance(state, str) and state in _TIMEOUT_SQLSTATES:
            return _TIMEOUT_SQLSTATES[state]
        current = current.__cause__ or current.__context__
    return None
