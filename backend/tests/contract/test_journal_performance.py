"""Local Journal performance contracts for bounded reads and fingerprints.

Two layers, so that a loaded CI runner cannot fail the main suite:

* the deterministic guard (always runs): each bounded read over 10,000 Journal entries takes a fixed
  small number of SQL statements and returns at most its page, counted rather than timed;
* the wall-clock p95 (marker `performance`, run on its own and serially by CI): a generous bound
  that only catches a lost index or a read per row, never ordinary runner noise.
"""

from collections.abc import Callable
from datetime import date
from time import perf_counter
from typing import Any

import pytest
from sqlalchemy import create_engine, text

from sidekick.api.app import create_app
from sidekick.journal.domain.summary import entry_fingerprint
from sidekick.shared.types import Actor
from tests.db import count_statements, database_factory, require_test_database_url
from tests.support.settings import make_settings

JOURNAL_START = date(2025, 1, 1)
JOURNAL_END = date(2025, 12, 31)
# Statements one bounded read may take, whatever the table size; measured at 1 to 4.
MAX_STATEMENTS_PER_READ = 5
# A healthy run is a few milliseconds; the bound is far above it so only a structural regression
# (a lost index, a read per row) can reach it on a shared runner.
P95_BOUND_MILLISECONDS = 2000


def _p95_milliseconds(durations: list[float]) -> float:
    return sorted(durations)[(len(durations) * 95 // 100) - 1] * 1000


def _seeded_journal() -> tuple[Any, Any, Actor, Any]:
    """An owner with 10,000 Journal entries over a year, planner statistics in place."""

    factory = database_factory()
    app = create_app(make_settings(), factory)
    owner_id = app.state.container.auth.provision_user(
        "journal-performance-owner", "Journal Performance"
    )
    with factory.begin() as session:
        session.execute(
            text(
                """
                INSERT INTO sidekick.journal_sources
                  (id, owner_id, source_type, journal_date, occurred_at,
                   source_recorded_at, raw_text, content_fingerprint, language,
                   replaces_source_id, created_at)
                SELECT gen_random_uuid(), :owner, 'manual_text',
                       DATE '2025-01-01' + ((n - 1) % 365),
                       TIMESTAMPTZ '2025-01-01 08:00:00+00' + (n || ' minutes')::interval,
                       TIMESTAMPTZ '2025-01-01 08:00:00+00' + (n || ' minutes')::interval,
                       'synthetic journal source', repeat('a', 64), 'sv', NULL,
                       TIMESTAMPTZ '2025-01-01 08:00:00+00' + (n || ' minutes')::interval
                FROM generate_series(1, 10000) AS n
                """
            ),
            {"owner": owner_id},
        )
        session.execute(
            text(
                """
                INSERT INTO sidekick.journal_entries
                  (id, owner_id, source_id, journal_date, occurred_at, title,
                   summary, key_points, version, created_at, updated_at, archived_at)
                SELECT gen_random_uuid(), s.owner_id, s.id, s.journal_date,
                       s.occurred_at, 'Synthetic journal entry', NULL, '[]'::jsonb,
                       1, s.created_at, s.created_at, NULL
                FROM sidekick.journal_sources AS s
                WHERE s.owner_id = :owner
                """
            ),
            {"owner": owner_id},
        )
        detail_id = session.execute(
            text(
                """
                SELECT id
                FROM sidekick.journal_entries
                WHERE owner_id = :owner
                ORDER BY journal_date, occurred_at, id
                LIMIT 1
                """
            ),
            {"owner": owner_id},
        ).scalar_one()

    # Ten thousand rows arriving in one statement leave the planner without
    # statistics, which a real deployment never does: autovacuum has analysed the
    # tables long before anyone reads them. Without this the measurement depends on
    # a plan no production query would get.
    admin = create_engine(require_test_database_url("SIDEKICK_TEST_ADMIN_DATABASE_URL"))
    try:
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(text("ANALYZE sidekick.journal_sources"))
            connection.execute(text("ANALYZE sidekick.journal_entries"))
    finally:
        admin.dispose()

    actor = Actor(owner_id, frozenset({"journal:read"}))
    return factory, app.state.container, actor, detail_id


def _reads(container: Any, actor: Actor, detail_id: Any) -> dict[str, Callable[[], None]]:
    def list_entries() -> None:
        page = container.journal.list_entries(
            actor, start_date=JOURNAL_START, end_date=JOURNAL_END, limit=100
        )
        assert 0 < len(page.items) <= 100

    def get_day() -> None:
        day = container.journal_day.get_day(actor, journal_date=JOURNAL_START, limit=100)
        assert 0 < len(day.entries) <= 100

    def get_entry() -> None:
        assert container.journal.get_entry(actor, detail_id).title == "Synthetic journal entry"

    return {"365-day list": list_entries, "day": get_day, "detail": get_entry}


@pytest.mark.integration
def test_bounded_journal_reads_take_a_fixed_number_of_statements() -> None:
    factory, container, actor, detail_id = _seeded_journal()

    for label, read in _reads(container, actor, detail_id).items():
        with count_statements(factory) as statements:
            read()
        assert 0 < len(statements) <= MAX_STATEMENTS_PER_READ, (label, statements)

    page = container.journal.list_entries(
        actor, start_date=JOURNAL_START, end_date=JOURNAL_END, limit=100
    )
    fingerprint = entry_fingerprint(page.items)
    assert len(fingerprint) == 64
    # The fingerprint is computed from the bounded page in memory, not by a further read.
    with count_statements(factory) as statements:
        entry_fingerprint(page.items)
    assert statements == []


@pytest.mark.integration
@pytest.mark.performance
def test_bounded_journal_reads_and_fingerprint_p95_stay_below_the_generous_bound() -> None:
    _factory, container, actor, detail_id = _seeded_journal()
    reads = _reads(container, actor, detail_id)
    page = container.journal.list_entries(
        actor, start_date=JOURNAL_START, end_date=JOURNAL_END, limit=100
    )
    durations: dict[str, list[float]] = {label: [] for label in (*reads, "bounded fingerprint")}

    for _iteration in range(20):
        for label, read in reads.items():
            started = perf_counter()
            read()
            durations[label].append(perf_counter() - started)
        started = perf_counter()
        fingerprint = entry_fingerprint(page.items)
        durations["bounded fingerprint"].append(perf_counter() - started)
        assert len(fingerprint) == 64

    measurements = {label: _p95_milliseconds(values) for label, values in durations.items()}
    assert all(duration < P95_BOUND_MILLISECONDS for duration in measurements.values()), (
        f"Journal local p95 measurements exceeded {P95_BOUND_MILLISECONDS} ms: {measurements}"
    )
