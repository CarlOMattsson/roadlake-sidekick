"""Explicit SQLAlchemy engine and session creation; never migrates on startup."""

from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from sidekick.shared.db_timeouts import DatabaseTimeouts

from .runtime_role import require_unprivileged_runtime_role


def create_session_factory(
    database_url: str,
    *,
    require_unprivileged_role: bool = False,
    timeouts: DatabaseTimeouts | None = None,
) -> sessionmaker[Session]:
    """Build the session factory; in production the role must not be able to change the schema.

    Every connection carries explicit connect, statement, lock and idle-in-transaction budgets
    (`DatabaseTimeouts`), so a stuck query or lock queue ends in an error rather than a hang.
    """

    budgets = timeouts or DatabaseTimeouts()
    engine = create_engine(
        database_url,
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args=budgets.connect_args(),
    )

    @event.listens_for(engine, "connect")
    def _apply_budgets(dbapi_connection: Any, _record: Any) -> None:
        # Session-level settings, committed so a later rollback cannot undo them. Applied here
        # rather than through the libpq `options` parameter, which test guards refuse.
        cursor = dbapi_connection.cursor()
        try:
            for name, value in budgets.session_settings():
                cursor.execute("SELECT set_config(%s, %s, false)", (name, value))
        finally:
            cursor.close()
        dbapi_connection.commit()

    factory = sessionmaker(engine, expire_on_commit=False)
    if require_unprivileged_role:
        try:
            require_unprivileged_runtime_role(factory)
        except Exception:
            engine.dispose()
            raise
    return factory
