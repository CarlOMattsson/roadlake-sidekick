"""Journal list and day reads take a fixed number of statements, however many entries they hold.

The links and names of a page's entries are read in batches, and the day's fingerprint reads only
id, version and ordering fields, so the statement count depends on neither the number of entries
nor the number of links.
"""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from sidekick.api.app import create_container
from sidekick.composition import Container
from sidekick.journal.domain.entry import KeyPoint, KeyPointKind
from sidekick.journal.domain.source import SourceType
from sidekick.journal.domain.summary import entry_fingerprint
from sidekick.shared.types import Actor, new_uuid7
from sidekick.store import SqlAlchemyStore
from sidekick.structured.journal import journal_day_structured, journal_entries_structured
from tests.db import count_statements, database_factory
from tests.support.settings import make_settings

DAY = date(2026, 7, 21)
NOW = datetime(2026, 7, 21, 6, 0, tzinfo=UTC)
SCOPES = frozenset({"journal:read", "journal:write", "projects:read", "contacts:read"})


def _seed_links(factory: sessionmaker[Session], owner_id: UUID) -> tuple[UUID, UUID]:
    domain_id, project_id, contact_id = new_uuid7(), new_uuid7(), new_uuid7()
    with factory.begin() as session:
        session.execute(
            text(
                "INSERT INTO sidekick.domains "
                "(id, owner_id, name, status, created_at, updated_at, version) "
                "VALUES (:id, :owner, 'Batch Domain', 'active', :now, :now, 1)"
            ),
            {"id": domain_id, "owner": owner_id, "now": NOW},
        )
        session.execute(
            text(
                "INSERT INTO sidekick.projects "
                "(id, owner_id, domain_id, title, status, created_at, updated_at, version) "
                "VALUES (:id, :owner, :domain, 'Batch Project', 'active', :now, :now, 1)"
            ),
            {"id": project_id, "owner": owner_id, "domain": domain_id, "now": NOW},
        )
        session.execute(
            text(
                "INSERT INTO sidekick.contacts "
                "(id, owner_id, display_name, display_name_key, archived, "
                "created_at, updated_at, version) "
                "VALUES (:id, :owner, 'Batch Contact', 'batch contact', false, :now, :now, 1)"
            ),
            {"id": contact_id, "owner": owner_id, "now": NOW},
        )
    return project_id, contact_id


def _world(entry_count: int) -> tuple[Container, sessionmaker[Session], Actor, UUID, UUID]:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    owner_id = container.auth.provision_user(f"batch-owner-{entry_count}", "Batch Owner")
    actor = Actor(owner_id, SCOPES)
    project_id, contact_id = _seed_links(factory, owner_id)
    for number in range(entry_count):
        container.journal_capture.write_entry(
            actor,
            source_type=SourceType.TRANSCRIPT_TEXT,
            journal_date=DAY,
            occurred_at=NOW + timedelta(minutes=number),
            raw_text=f"Synthetic source text {number}",
            language="sv",
            title=f"Synthetic entry {number}",
            summary=None,
            key_points=(KeyPoint(KeyPointKind.FACT, "A synthetic fact."),),
            project_ids=(project_id,),
            contact_ids=(contact_id,),
            idempotency_key=f"batch-entry-{number}",
        )
    return container, factory, actor, project_id, contact_id


def _statement_counts(entry_count: int) -> dict[str, int]:
    container, factory, actor, project_id, contact_id = _world(entry_count)
    counts: dict[str, int] = {}

    with count_statements(factory) as statements:
        page = journal_entries_structured(
            container,
            actor,
            from_date=DAY,
            to_date=DAY,
            include_archived=False,
            include_content=True,
            limit=100,
            cursor=None,
        ).model_dump(mode="json")
    counts["list"] = len(statements)
    assert len(page["entries"]) == entry_count
    for record in page["entries"]:
        assert record["project_ids"] == [str(project_id)]
        assert record["contact_ids"] == [str(contact_id)]
        assert sorted(link["label"] for link in record["links"]) == [
            "Batch Contact",
            "Batch Project",
        ]

    with count_statements(factory) as statements:
        day = journal_day_structured(
            container,
            actor,
            DAY,
            include_archived=False,
            include_content=True,
            limit=100,
            cursor=None,
        ).model_dump(mode="json")
    counts["day"] = len(statements)
    assert len(day["entries"]) == entry_count
    assert day["entry_fingerprint"] == entry_fingerprint(
        container.journal_day.get_day(actor, journal_date=DAY).entries
    )
    return counts


@pytest.mark.integration
def test_list_and_day_reads_take_the_same_statements_for_two_and_ten_entries() -> None:
    small = _statement_counts(2)
    large = _statement_counts(10)

    assert small == large


@pytest.mark.integration
def test_the_day_fingerprint_reads_no_entry_text() -> None:
    container, factory, actor, _project_id, _contact_id = _world(3)
    assert isinstance(container.journal.store, SqlAlchemyStore)

    with count_statements(factory) as statements:
        heads = container.journal.store.transaction(
            lambda session: container.journal.store.list_active_journal_entry_heads(
                session, actor.user_id, DAY
            )
        )

    assert len(heads) == 3
    assert len(statements) == 1
    for column in ("title", "summary", "key_points", "raw_text"):
        assert column not in statements[0]
    day = container.journal_day.get_day(actor, journal_date=DAY)
    assert entry_fingerprint(heads) == day.entry_fingerprint
