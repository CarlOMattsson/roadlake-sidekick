"""Database time budgets: an over-long statement or lock wait is cancelled, not left hanging."""

import time

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from sidekick.shared.db_timeouts import DatabaseTimeouts, database_timeout_reason
from sidekick.shared.persistence import create_session_factory
from tests.db import assert_safe_test_database, database_factory, require_test_database_url


def _factory(timeouts: DatabaseTimeouts) -> sessionmaker[Session]:
    url = require_test_database_url()
    assert_safe_test_database(url)
    return create_session_factory(url, timeouts=timeouts)


@pytest.mark.integration
def test_an_over_long_statement_is_cancelled_by_the_statement_budget() -> None:
    database_factory()
    factory = _factory(DatabaseTimeouts(statement_ms=300))
    started = time.monotonic()
    with pytest.raises(OperationalError) as raised, factory() as session:
        session.execute(text("SELECT pg_sleep(10)"))
    assert time.monotonic() - started < 5
    assert database_timeout_reason(raised.value) == "statement_timeout"


@pytest.mark.integration
def test_the_budgets_are_set_on_every_connection_and_unbounded_statements_lifts_two() -> None:
    database_factory()
    bounded = DatabaseTimeouts(statement_ms=1_234, lock_ms=567, idle_in_transaction_ms=8_910)
    with _factory(bounded)() as session:
        seen = {
            name: session.execute(text(f"SHOW {name}")).scalar_one()
            for name in ("statement_timeout", "lock_timeout", "idle_in_transaction_session_timeout")
        }
    assert seen == {
        "statement_timeout": "1234ms",
        "lock_timeout": "567ms",
        "idle_in_transaction_session_timeout": "8910ms",
    }
    with _factory(bounded.unbounded_statements())() as session:
        assert session.execute(text("SHOW statement_timeout")).scalar_one() == "0"
        assert session.execute(text("SHOW lock_timeout")).scalar_one() == "567ms"


@pytest.mark.integration
def test_a_lock_wait_ends_at_the_lock_budget() -> None:
    database_factory()
    factory = _factory(DatabaseTimeouts(lock_ms=300, statement_ms=10_000))
    with factory() as holder, factory() as waiter:
        holder.execute(text("SELECT pg_advisory_xact_lock(7342)"))
        with pytest.raises(OperationalError) as raised:
            waiter.execute(text("SELECT pg_advisory_xact_lock(7342)"))
        assert database_timeout_reason(raised.value) == "lock_timeout"


def test_a_non_timeout_error_is_not_reported_as_a_timeout() -> None:
    assert database_timeout_reason(ValueError("nope")) is None
