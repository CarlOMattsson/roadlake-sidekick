"""Full-text and trigram search behaviour on the search columns and indexes of the schema head."""

import pytest
from sqlalchemy import create_engine, text

from tests.db import database_factory, require_test_database_url

OWNER_ID = "018af000-0000-7000-8000-000000000a01"
SOURCE_ID = "018af000-0000-7000-8000-000000000a02"
CONTACT_ID = "018af000-0000-7000-8000-000000000a03"


def _insert_journal_text_about_a_match_clock() -> None:
    engine = create_engine(require_test_database_url())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO sidekick.users "
                "(id, username, display_name, created_at) "
                "VALUES (:id, 'search-owner', 'Search Owner', now())"
            ),
            {"id": OWNER_ID},
        )
        conn.execute(
            text(
                "INSERT INTO sidekick.journal_sources "
                "(id, owner_id, source_type, journal_date, raw_text, content_fingerprint, "
                "created_at) VALUES (:id, :owner, 'manual_text', DATE '2026-10-25', "
                "'matchklockan ska gå baklänges', repeat('b', 64), now())"
            ),
            {"id": SOURCE_ID, "owner": OWNER_ID},
        )
    engine.dispose()


@pytest.mark.integration
def test_prefix_query_finds_swedish_compound_in_journal_text() -> None:
    """The query layer uses prefix terms for Swedish compounds, not stemming alone.

    The Swedish stemmer keeps the definite compound 'matchklockan' whole, so the
    stemmed query 'matchklock' does not match it. The prefix term 'matchklock:*'
    does. Search queries therefore combine prefix terms with trigram similarity
    (a deliberate design choice, not a weakening of the requirement).
    """

    database_factory()
    _insert_journal_text_about_a_match_clock()
    engine = create_engine(require_test_database_url())
    with engine.connect() as conn:
        found = conn.scalars(
            text(
                "SELECT id FROM sidekick.journal_sources "
                "WHERE search_vector @@ to_tsquery('swedish', 'matchklock:*')"
            )
        ).all()
    engine.dispose()
    assert [str(identifier) for identifier in found] == [SOURCE_ID]


@pytest.mark.integration
def test_websearch_swedish_does_not_match_definite_compound_by_design() -> None:
    """Documents the known limit of websearch_to_tsquery for Swedish compounds.

    `websearch_to_tsquery('swedish', 'matchklocka')` does NOT find
    "matchklockan ska gå baklänges". This is intentional: the query layer uses prefix terms plus
    trigram matching instead (see test_prefix_query_finds_swedish_compound_in_journal_text).
    If this test starts failing, the Swedish dictionary or the search query design has
    changed and the design decision must be revisited.
    """

    database_factory()
    _insert_journal_text_about_a_match_clock()
    engine = create_engine(require_test_database_url())
    with engine.connect() as conn:
        found = conn.scalars(
            text(
                "SELECT id FROM sidekick.journal_sources "
                "WHERE search_vector @@ websearch_to_tsquery('swedish', 'matchklocka')"
            )
        ).all()
    engine.dispose()
    assert found == []


@pytest.mark.integration
def test_trigram_similarity_finds_contact_name_with_a_typo() -> None:
    database_factory()
    engine = create_engine(require_test_database_url())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO sidekick.users "
                "(id, username, display_name, created_at) "
                "VALUES (:id, 'search-owner', 'Search Owner', now())"
            ),
            {"id": OWNER_ID},
        )
        conn.execute(
            text(
                "INSERT INTO sidekick.contacts "
                "(id, owner_id, display_name, display_name_key, created_at, updated_at, "
                "archived, version) VALUES (:id, :owner, 'Klas Ekdahl', 'klas ekdahl', "
                "now(), now(), false, 1)"
            ),
            {"id": CONTACT_ID, "owner": OWNER_ID},
        )
    with engine.connect() as conn:
        found = conn.scalars(
            text(
                "SELECT display_name FROM sidekick.contacts "
                "WHERE similarity(display_name, 'Ekdah') > 0.3"
            )
        ).all()
    engine.dispose()
    assert found == ["Klas Ekdahl"]
