"""The per-owner Postgres advisory lock that keeps two memory workers out of one owner."""

from __future__ import annotations

import hashlib
import logging
from uuid import UUID

from sqlalchemy import Connection, Engine, func, select

from sidekick.memory.application.store import LockLost

# The lock belongs to the sync pass, so its records keep the pass's logger name.
LOGGER = logging.getLogger("sidekick.memory.sync")

_LOCK_LABEL = "sidekick:memory-sync:"


def _lock_key(owner_id: UUID) -> int:
    digest = hashlib.sha256(f"{_LOCK_LABEL}{owner_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


class OwnerLock:
    """A session-level advisory lock on a dedicated autocommit connection.

    The connection stays checked out for the whole pass, outside any transaction, so the lock
    survives the many short transactions of the pass and vanishes with the connection if the
    process dies.
    """

    def __init__(self, engine: Engine, owner_id: UUID) -> None:
        self._engine = engine
        self._key = _lock_key(owner_id)
        self._connection: Connection | None = None

    def acquire(self) -> bool:
        connection = self._engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        try:
            got = bool(connection.execute(select(func.pg_try_advisory_lock(self._key))).scalar())
        except BaseException:
            connection.close()
            raise
        if not got:
            connection.close()
            return False
        self._connection = connection
        return True

    def assert_alive(self) -> None:
        if self._connection is None:
            raise LockLost
        try:
            self._connection.execute(select(1)).close()
        except Exception as error:  # any failure means the lock cannot be shown to be alive
            raise LockLost from error

    def release(self) -> None:
        connection, self._connection = self._connection, None
        if connection is None:
            return
        unlocked = False
        try:
            unlocked = bool(connection.execute(select(func.pg_advisory_unlock(self._key))).scalar())
        except Exception:
            # Release is cleanup and must never raise: a dead connection (a driver, socket or
            # SQLAlchemy error alike) already dropped the lock on the server.
            LOGGER.warning("memory sync lock release failed")
        try:
            if not unlocked:
                # Never hand a connection that may still hold the session lock back to the pool:
                # closing the DBAPI connection drops every lock it holds.
                LOGGER.warning("memory sync lock was not released cleanly; connection discarded")
                connection.invalidate()
        except Exception:
            LOGGER.warning("memory sync lock connection could not be invalidated")
        finally:
            try:
                connection.close()
            except Exception:
                LOGGER.warning("memory sync lock connection could not be closed")
