"""Performance contract for bounded search over 10,000 owner Contacts.

Two layers, so that a loaded CI runner cannot fail the main suite:

* the deterministic guard (always runs): a search over 10,000 Contacts is one bounded read, counted
  in SQL statements and returned rows, not in seconds;
* the wall-clock p95 (marker `performance`, run on its own and serially by CI): a generous bound
  that only catches a lost index or a scan per row, never ordinary runner noise.
"""

import time
from typing import Any

import pytest
from sqlalchemy import text

from sidekick.api.app import create_app
from sidekick.shared.types import Actor
from tests.db import count_statements, database_factory
from tests.support.settings import make_settings

SEARCH = "person9999@example.com"
# One search is the Contact page plus its owner-scoped checks; it must not depend on the table size.
MAX_STATEMENTS_PER_SEARCH = 3
# A lost index on 10,000 rows is a sequential scan, still far below this; the bound is deliberately
# an order of magnitude above a healthy run so only a structural regression can reach it.
P95_BOUND_SECONDS = 2.0


def _seeded_app() -> tuple[Any, Actor]:
    factory = database_factory()
    app = create_app(make_settings(), factory)
    owner_id = app.state.container.auth.provision_user("perf-owner", "Owner")
    with factory.begin() as session:
        session.execute(
            text("""
            INSERT INTO sidekick.contacts
              (id, owner_id, display_name, display_name_key, email, email_key,
               created_at, updated_at, archived, archived_at, version)
            SELECT gen_random_uuid(), :owner, 'Contact ' || n, 'contact ' || n,
                   'person' || n || '@example.com', 'person' || n || '@example.com',
                   now(), now(), false, NULL, 1
            FROM generate_series(1, 10000) AS n
        """),
            {"owner": owner_id},
        )
    return app, Actor(owner_id, frozenset({"contacts:read"}))


@pytest.mark.integration
def test_a_contact_search_over_10000_rows_is_one_bounded_read() -> None:
    app, actor = _seeded_app()
    factory = app.state.container.session_factory

    for _ in range(3):
        with count_statements(factory) as statements:
            page = app.state.container.contacts.list(actor, q=SEARCH, limit=25)
        assert len(page.items) == 1 and page.next_cursor is None
        assert len(statements) <= MAX_STATEMENTS_PER_SEARCH, statements

    unfiltered = app.state.container.contacts.list(actor, limit=25)
    assert len(unfiltered.items) == 25 and unfiltered.next_cursor is not None


@pytest.mark.integration
@pytest.mark.performance
def test_performance_p95_bounds() -> None:
    app, actor = _seeded_app()
    durations = []
    for _ in range(20):
        started = time.perf_counter()
        page = app.state.container.contacts.list(actor, q=SEARCH, limit=25)
        durations.append(time.perf_counter() - started)
        assert len(page.items) == 1 and page.next_cursor is None
    p95 = sorted(durations)[int(len(durations) * 0.95) - 1]
    assert p95 < P95_BOUND_SECONDS
