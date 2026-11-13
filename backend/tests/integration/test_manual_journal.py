"""PostgreSQL/application contract tests for the manual Journal transaction."""

from __future__ import annotations

import inspect
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine, create_engine, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from sidekick.journal.domain.entry import KeyPoint, KeyPointKind, entry_order_key, entry_page_key
from sidekick.journal.domain.source import SourceType
from sidekick.shared.errors import ConflictError, NotFoundError, ValidationError
from sidekick.shared.persistence import create_session_factory
from sidekick.shared.persistence.models import (
    AuditEventRow,
    DailyJournalSummaryRow,
    IdempotencyRow,
    JournalEntryContactRow,
    JournalEntryProjectRow,
    JournalEntryRow,
    JournalEntryTaskRow,
    JournalSourceRow,
    TaskRow,
)
from sidekick.shared.types import Actor, new_uuid7
from sidekick.store import SqlAlchemyStore
from tests.db import require_test_database_url
from tests.support.fakes import (
    JOURNAL_REDACTION_SENTINEL_ONE,
    JOURNAL_SOURCE_TEXT,
    JournalProviderSpy,
    make_cursor_codec,
)
from tests.support.journal_services import ManualJournal

JOURNAL_DATE = date(2026, 7, 21)
CREATED_AT = datetime(2026, 7, 24, 10, tzinfo=UTC)
OWNER_SCOPES = frozenset(
    {"journal:read", "journal:write", "projects:read", "tasks:read", "contacts:read"}
)


@dataclass(frozen=True, slots=True)
class DatabaseHarness:
    factory: sessionmaker[Session]
    app_engine: Engine
    owner_engine: Engine


@dataclass(slots=True)
class FixedClock:
    value: datetime = CREATED_AT

    def now(self) -> datetime:
        return self.value


def _cleanup(harness: DatabaseHarness) -> None:
    """Clean Journal state without widening the shared cleanup."""

    with harness.owner_engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE sidekick_owner"))
        connection.execute(text("TRUNCATE sidekick.journal_sources CASCADE"))
        connection.execute(text("DELETE FROM sidekick.audit_events WHERE event LIKE 'journal.%'"))
        connection.execute(
            text("DELETE FROM sidekick.idempotency_operations WHERE operation LIKE '%journal%'")
        )
        connection.execute(
            text("DELETE FROM sidekick.users WHERE username LIKE 'manual_journal_%'")
        )


@pytest.fixture(scope="module")
def database_harness() -> DatabaseHarness:
    app_url = require_test_database_url()
    owner_url = require_test_database_url("SIDEKICK_TEST_MIGRATION_DATABASE_URL")
    harness = DatabaseHarness(
        factory=create_session_factory(app_url),
        app_engine=create_engine(app_url),
        owner_engine=create_engine(owner_url),
    )
    with harness.app_engine.connect() as connection:
        assert connection.scalar(text("SELECT to_regclass('sidekick.journal_sources')")) is not None
    _cleanup(harness)
    yield harness
    _cleanup(harness)
    harness.app_engine.dispose()
    harness.owner_engine.dispose()


@pytest.fixture
def db(database_harness: DatabaseHarness) -> DatabaseHarness:
    _cleanup(database_harness)
    yield database_harness
    _cleanup(database_harness)


@pytest.fixture
def journal_service(db: DatabaseHarness) -> ManualJournal:
    return ManualJournal.build(SqlAlchemyStore(db.factory), FixedClock(), make_cursor_codec())


def _actor(owner_id: UUID) -> Actor:
    return Actor(owner_id, OWNER_SCOPES)


def _seed_user(harness: DatabaseHarness, owner_id: UUID) -> None:
    with harness.factory.begin() as session:
        session.execute(
            text(
                "INSERT INTO sidekick.users "
                "(id, username, display_name, active, created_at) "
                "VALUES (:id, :username, 'Manual journal Owner', true, :created_at)"
            ),
            {
                "id": owner_id,
                "username": f"manual_journal_{owner_id.hex}",
                "created_at": CREATED_AT,
            },
        )


def _seed_relation_targets(
    harness: DatabaseHarness,
    owner_id: UUID,
    *,
    active: bool = True,
) -> tuple[UUID, UUID, UUID]:
    domain_id = new_uuid7()
    project_id, task_id, contact_id = new_uuid7(), new_uuid7(), new_uuid7()
    archived_at = None if active else CREATED_AT
    with harness.factory.begin() as session:
        # Every Project needs an owner-consistent Domain ancestry.
        session.execute(
            text(
                "INSERT INTO sidekick.domains "
                "(id, owner_id, name, status, created_at, updated_at, version) "
                "VALUES (:id, :owner, 'Manual journal Domain', 'active', :now, :now, 1)"
            ),
            {"id": domain_id, "owner": owner_id, "now": CREATED_AT},
        )
        session.execute(
            text(
                "INSERT INTO sidekick.projects "
                "(id, owner_id, domain_id, title, status, created_at, updated_at, archived_at, "
                "version) "
                "VALUES (:id, :owner, :domain, 'Manual Project', :status, :now, :now, :archived, 1)"
            ),
            {
                "id": project_id,
                "owner": owner_id,
                "domain": domain_id,
                "status": "active" if active else "completed",
                "now": CREATED_AT,
                "archived": archived_at,
            },
        )
        session.execute(
            text(
                "INSERT INTO sidekick.tasks "
                "(id, owner_id, title, status, priority, created_at, updated_at, "
                "archived_at, version) VALUES (:id, :owner, 'Manual journal Task', :status, "
                "'normal', :now, :now, :archived, 1)"
            ),
            {
                "id": task_id,
                "owner": owner_id,
                "status": "todo" if active else "completed",
                "now": CREATED_AT,
                "archived": archived_at,
            },
        )
        session.execute(
            text(
                "INSERT INTO sidekick.contacts "
                "(id, owner_id, display_name, display_name_key, archived, archived_at, "
                "created_at, updated_at, version) VALUES (:id, :owner, 'Manual journal Contact', "
                "'manual journal contact', :archived, :archived_at, :now, :now, 1)"
            ),
            {
                "id": contact_id,
                "owner": owner_id,
                "archived": not active,
                "archived_at": archived_at,
                "now": CREATED_AT,
            },
        )
    return project_id, task_id, contact_id


def _seed_current_summary(harness: DatabaseHarness, owner_id: UUID) -> UUID:
    summary_id = new_uuid7()
    with harness.factory.begin() as session:
        session.add(
            DailyJournalSummaryRow(
                id=summary_id,
                owner_id=owner_id,
                journal_date=JOURNAL_DATE,
                origin="manual",
                status="current",
                overview="Syntetisk dagssammanfattning.",
                content={"overview": "Syntetisk dagssammanfattning."},
                source_fingerprint="b" * 64,
                processing_run_id=None,
                accepted_proposal_id=None,
                version=1,
                generated_at=CREATED_AT,
                updated_at=CREATED_AT,
                manual_edited_at=CREATED_AT,
            )
        )
    return summary_id


def _create_source(
    service: Any,
    actor: Actor,
    *,
    raw_text: str = JOURNAL_SOURCE_TEXT,
    occurred_at: datetime | None = datetime(2026, 7, 21, 9, tzinfo=UTC),
    source_recorded_at: datetime | None = datetime(2026, 7, 21, 9, 5, tzinfo=UTC),
    key: str = "manual-journal-source-key",
    journal_date: date = JOURNAL_DATE,
) -> Any:
    return service.capture.create_source(
        actor,
        source_type=SourceType.MANUAL_TEXT,
        journal_date=journal_date,
        occurred_at=occurred_at,
        source_recorded_at=source_recorded_at,
        raw_text=raw_text,
        language="sv",
        replaces_source_id=None,
        idempotency_key=key,
    )


def _create_manual_entry(
    service: Any,
    actor: Actor,
    source_id: UUID,
    *,
    title: str = "Planering och uppföljning",
    project_ids: tuple[UUID, ...] = (),
    task_ids: tuple[UUID, ...] = (),
    contact_ids: tuple[UUID, ...] = (),
    key: str = "manual-journal-manual-entry-key",
) -> Any:
    return service.capture.create_manual_entry(
        actor,
        source_id=source_id,
        title=title,
        summary="Ett beslut fattades och en uppföljning planerades.",
        key_points=(KeyPoint(KeyPointKind.DECISION, "Följ upp på måndag."),),
        project_ids=project_ids,
        task_ids=task_ids,
        contact_ids=contact_ids,
        idempotency_key=key,
        correlation_id="manual-journal-correlation",
    )


def _insert_source_sql(connection: Any, source_id: UUID, owner_id: UUID) -> None:
    connection.execute(
        text(
            "INSERT INTO sidekick.journal_sources "
            "(id, owner_id, source_type, journal_date, raw_text, content_fingerprint, created_at) "
            "VALUES (:id, :owner, 'manual_text', :journal_date, 'Syntetisk manuell källa', "
            ":fingerprint, :created_at)"
        ),
        {
            "id": source_id,
            "owner": owner_id,
            "journal_date": JOURNAL_DATE,
            "fingerprint": "a" * 64,
            "created_at": CREATED_AT,
        },
    )


def _insert_entry_sql(connection: Any, entry_id: UUID, owner_id: UUID, source_id: UUID) -> None:
    connection.execute(
        text(
            "INSERT INTO sidekick.journal_entries "
            "(id, owner_id, source_id, journal_date, title, key_points, version, "
            "created_at, updated_at) VALUES (:id, :owner, :source, :journal_date, "
            "'Manual journal entry', '[]'::jsonb, 1, :created_at, :created_at)"
        ),
        {
            "id": entry_id,
            "owner": owner_id,
            "source": source_id,
            "journal_date": JOURNAL_DATE,
            "created_at": CREATED_AT,
        },
    )


def _insert_finalized_draft_sql(connection: Any, owner_id: UUID, source_id: UUID) -> UUID:
    run_id, draft_id = new_uuid7(), new_uuid7()
    connection.execute(
        text(
            "INSERT INTO sidekick.journal_processing_runs "
            "(id, owner_id, source_id, operation, journal_date, status, provider, model_id, "
            "prompt_version, schema_version, input_fingerprint, candidate_catalog, "
            "attempt_count, created_at) VALUES (:run, :owner, :source, 'entry_draft', "
            ":journal_date, 'succeeded', 'fake', 'fake-model', 'v1', 'v1', :fingerprint, "
            "'{}'::jsonb, 1, :created_at)"
        ),
        {
            "run": run_id,
            "owner": owner_id,
            "source": source_id,
            "journal_date": JOURNAL_DATE,
            "fingerprint": "c" * 64,
            "created_at": CREATED_AT,
        },
    )
    connection.execute(
        text(
            "INSERT INTO sidekick.journal_drafts "
            "(id, owner_id, source_id, processing_run_id, catalog_run_id, state, title, "
            "key_points, relation_suggestions, task_proposals, version, created_at, updated_at, "
            "lifecycle_at) VALUES (:draft, :owner, :source, :run, :run, 'finalized', "
            "'Manual journal draft', '[]'::jsonb, '{}'::jsonb, '[]'::jsonb, 1, :created_at, "
            ":created_at, :created_at)"
        ),
        {
            "draft": draft_id,
            "owner": owner_id,
            "source": source_id,
            "run": run_id,
            "created_at": CREATED_AT,
        },
    )
    return draft_id


@pytest.mark.integration
@pytest.mark.parametrize("first_path", ["manual_then_draft", "draft_then_manual"])
def test_database_allows_only_one_entry_for_manual_and_draft_finalize_orders(
    db: DatabaseHarness, first_path: str
) -> None:
    owner_id, source_id = new_uuid7(), new_uuid7()
    _seed_user(db, owner_id)
    with db.app_engine.begin() as connection:
        _insert_source_sql(connection, source_id, owner_id)
        if first_path == "draft_then_manual":
            _insert_finalized_draft_sql(connection, owner_id, source_id)
        _insert_entry_sql(connection, new_uuid7(), owner_id, source_id)
        if first_path == "manual_then_draft":
            _insert_finalized_draft_sql(connection, owner_id, source_id)
        with pytest.raises(IntegrityError), connection.begin_nested():
            _insert_entry_sql(connection, new_uuid7(), owner_id, source_id)
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM sidekick.journal_entries "
                    "WHERE owner_id = :owner AND source_id = :source"
                ),
                {"owner": owner_id, "source": source_id},
            )
            == 1
        )


@pytest.mark.integration
def test_database_rejects_an_equal_second_insert_for_the_same_owner_source(
    db: DatabaseHarness,
) -> None:
    owner_id, source_id, entry_id = new_uuid7(), new_uuid7(), new_uuid7()
    _seed_user(db, owner_id)
    with db.app_engine.begin() as connection:
        _insert_source_sql(connection, source_id, owner_id)
        _insert_entry_sql(connection, entry_id, owner_id, source_id)
        with pytest.raises(IntegrityError), connection.begin_nested():
            _insert_entry_sql(connection, entry_id, owner_id, source_id)
        assert (
            connection.scalar(
                text("SELECT count(*) FROM sidekick.journal_entries WHERE source_id = :source"),
                {"source": source_id},
            )
            == 1
        )


@pytest.mark.integration
def test_database_concurrent_manual_and_draft_race_has_one_authoritative_entry(
    db: DatabaseHarness,
) -> None:
    owner_id, source_id = new_uuid7(), new_uuid7()
    _seed_user(db, owner_id)
    with db.app_engine.begin() as connection:
        _insert_source_sql(connection, source_id, owner_id)
        _insert_finalized_draft_sql(connection, owner_id, source_id)

    def finalize(entry_id: UUID) -> bool:
        try:
            with db.app_engine.begin() as connection:
                _insert_entry_sql(connection, entry_id, owner_id, source_id)
            return True
        except IntegrityError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(finalize, (new_uuid7(), new_uuid7())))

    assert sorted(results) == [False, True]
    with db.app_engine.connect() as connection:
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM sidekick.journal_entries "
                    "WHERE owner_id = :owner AND source_id = :source"
                ),
                {"owner": owner_id, "source": source_id},
            )
            == 1
        )


@pytest.mark.integration
def test_source_commit_and_owner_filtering_are_actor_derived(
    db: DatabaseHarness, journal_service: Any
) -> None:
    owner_id, other_id = new_uuid7(), new_uuid7()
    _seed_user(db, owner_id)
    _seed_user(db, other_id)
    owner, other = _actor(owner_id), _actor(other_id)

    source = _create_source(journal_service, owner)

    with db.factory() as session:
        committed = session.get(JournalSourceRow, source.id)
        assert committed is not None
        assert committed.owner_id == owner.user_id
        assert committed.raw_text == JOURNAL_SOURCE_TEXT
    assert journal_service.capture.get_source(owner, source.id).id == source.id
    with pytest.raises(NotFoundError):
        journal_service.capture.get_source(other, source.id)


@pytest.mark.integration
def test_manual_entry_commits_links_stale_audit_and_idempotency_atomically(
    db: DatabaseHarness,
    journal_service: Any,
    journal_provider_spy: JournalProviderSpy,
) -> None:
    owner_id = new_uuid7()
    _seed_user(db, owner_id)
    project_id, task_id, contact_id = _seed_relation_targets(db, owner_id)
    summary_id = _seed_current_summary(db, owner_id)
    actor = _actor(owner_id)
    source = _create_source(journal_service, actor)
    with db.factory() as session:
        task_before = session.get(TaskRow, task_id)
        assert task_before is not None
        task_snapshot = (
            task_before.project_id,
            task_before.title,
            task_before.status,
            task_before.priority,
            task_before.version,
            task_before.updated_at,
        )

    entry = _create_manual_entry(
        journal_service,
        actor,
        source.id,
        project_ids=(project_id,),
        task_ids=(task_id,),
        contact_ids=(contact_id,),
    )
    replay = _create_manual_entry(
        journal_service,
        actor,
        source.id,
        project_ids=(project_id,),
        task_ids=(task_id,),
        contact_ids=(contact_id,),
    )

    assert replay.id == entry.id
    with db.factory() as session:
        assert session.scalar(select(func.count()).select_from(JournalEntryRow)) == 1
        assert session.scalar(select(func.count()).select_from(JournalEntryProjectRow)) == 1
        assert session.scalar(select(func.count()).select_from(JournalEntryTaskRow)) == 1
        assert session.scalar(select(func.count()).select_from(JournalEntryContactRow)) == 1
        summary = session.get(DailyJournalSummaryRow, summary_id)
        task_after = session.get(TaskRow, task_id)
        assert summary is not None and summary.status == "stale"
        assert task_after is not None
        assert (
            task_after.project_id,
            task_after.title,
            task_after.status,
            task_after.priority,
            task_after.version,
            task_after.updated_at,
        ) == task_snapshot
        operations = list(
            session.scalars(
                select(IdempotencyRow).where(
                    IdempotencyRow.actor_id == owner_id,
                    IdempotencyRow.idempotency_key == "manual-journal-manual-entry-key",
                )
            )
        )
        assert len(operations) == 1
        audits = list(
            session.scalars(
                select(AuditEventRow).where(
                    AuditEventRow.actor_id == owner_id,
                    AuditEventRow.target_id == entry.id,
                )
            )
        )
        assert len(audits) == 1
        audit = audits[0]
        assert audit.event.startswith("journal.")
        assert audit.outcome == "success"
        audit_metadata = "|".join(
            str(value)
            for value in (
                audit.event,
                audit.outcome,
                audit.reason,
                audit.correlation_id,
                audit.target_type,
                audit.target_id,
            )
        )
        for prohibited in (
            JOURNAL_SOURCE_TEXT,
            "Planering och uppföljning",
            "Ett beslut fattades",
            JOURNAL_REDACTION_SENTINEL_ONE,
        ):
            assert prohibited not in audit_metadata
    assert journal_provider_spy.calls == []
    required_provider_parameters = {
        name
        for part in journal_service.services()
        for name, parameter in inspect.signature(type(part).__init__).parameters.items()
        if name != "self" and "provider" in name and parameter.default is inspect.Parameter.empty
    }
    assert required_provider_parameters == set()


@pytest.mark.integration
def test_changed_payload_reusing_manual_idempotency_key_conflicts_without_second_entry(
    db: DatabaseHarness, journal_service: Any
) -> None:
    owner_id = new_uuid7()
    _seed_user(db, owner_id)
    actor = _actor(owner_id)
    source = _create_source(journal_service, actor)
    entry = _create_manual_entry(journal_service, actor, source.id)

    with pytest.raises(ConflictError):
        _create_manual_entry(
            journal_service,
            actor,
            source.id,
            title="Ändrad titel under samma nyckel",
        )

    with db.factory() as session:
        rows = list(session.scalars(select(JournalEntryRow)))
        assert [row.id for row in rows] == [entry.id]
        assert rows[0].title == "Planering och uppföljning"


@pytest.mark.integration
@pytest.mark.parametrize("relation_kind", ["project", "task", "contact"])
def test_failed_relation_validation_rolls_back_entry_links_stale_audit_and_replay(
    db: DatabaseHarness, journal_service: Any, relation_kind: str
) -> None:
    owner_id, other_id = new_uuid7(), new_uuid7()
    _seed_user(db, owner_id)
    _seed_user(db, other_id)
    inaccessible_targets = _seed_relation_targets(db, other_id)
    summary_id = _seed_current_summary(db, owner_id)
    actor = _actor(owner_id)
    source = _create_source(journal_service, actor)
    target_by_kind = dict(zip(("project", "task", "contact"), inaccessible_targets, strict=True))
    selected: dict[str, tuple[UUID, ...]] = {
        "project_ids": (),
        "task_ids": (),
        "contact_ids": (),
    }
    selected[f"{relation_kind}_ids"] = (target_by_kind[relation_kind],)
    with db.factory() as session:
        baseline_audits = session.scalar(select(func.count()).select_from(AuditEventRow))
        baseline_operations = session.scalar(select(func.count()).select_from(IdempotencyRow))

    with pytest.raises((NotFoundError, ValidationError, ConflictError)):
        _create_manual_entry(
            journal_service,
            actor,
            source.id,
            key=f"manual-journal-rollback-{relation_kind}",
            **selected,
        )

    with db.factory() as session:
        assert session.scalar(select(func.count()).select_from(JournalEntryRow)) == 0
        assert session.scalar(select(func.count()).select_from(JournalEntryProjectRow)) == 0
        assert session.scalar(select(func.count()).select_from(JournalEntryTaskRow)) == 0
        assert session.scalar(select(func.count()).select_from(JournalEntryContactRow)) == 0
        summary = session.get(DailyJournalSummaryRow, summary_id)
        assert summary is not None and summary.status == "current"
        assert session.scalar(select(func.count()).select_from(AuditEventRow)) == baseline_audits
        assert (
            session.scalar(select(func.count()).select_from(IdempotencyRow)) == baseline_operations
        )


@pytest.mark.integration
def test_owned_lists_and_day_views_share_deterministic_fallback_order(
    db: DatabaseHarness, journal_service: Any
) -> None:
    owner_id, other_id = new_uuid7(), new_uuid7()
    _seed_user(db, owner_id)
    _seed_user(db, other_id)
    actor, other = _actor(owner_id), _actor(other_id)
    source_specs = (
        (datetime(2026, 7, 21, 11, tzinfo=UTC), None, "occurrence"),
        (None, datetime(2026, 7, 21, 10, tzinfo=UTC), "recorded"),
        (None, None, "created-a"),
        (None, None, "created-b"),
    )
    entries = []
    for occurred_at, recorded_at, suffix in reversed(source_specs):
        source = _create_source(
            journal_service,
            actor,
            raw_text=f"Syntetisk ordningskälla {suffix}",
            occurred_at=occurred_at,
            source_recorded_at=recorded_at,
            key=f"manual-journal-source-{suffix}",
        )
        entries.append(
            _create_manual_entry(
                journal_service,
                actor,
                source.id,
                title=f"Post {suffix}",
                key=f"manual-journal-entry-{suffix}",
            )
        )
    other_source = _create_source(
        journal_service,
        other,
        raw_text="Annan ägares syntetiska källa",
        key="manual-journal-other-source",
    )
    _create_manual_entry(
        journal_service,
        other,
        other_source.id,
        title="Annan ägares post",
        key="manual-journal-other-entry",
    )

    expected_ids = [entry.id for entry in sorted(entries, key=entry_order_key)]
    listed = list(
        journal_service.entries.list_entries(
            actor,
            start_date=JOURNAL_DATE,
            end_date=JOURNAL_DATE,
        ).items
    )
    day = journal_service.day.get_day(actor, journal_date=JOURNAL_DATE)

    assert [entry.id for entry in listed] == expected_ids
    assert [entry.id for entry in day.entries] == expected_ids
    assert other_source.id not in {entry.source_id for entry in listed}


@pytest.mark.integration
def test_descending_list_reverses_timed_entries_keeps_untimed_last_and_pages_both_ways(
    db: DatabaseHarness, journal_service: Any
) -> None:
    owner_id, other_id = new_uuid7(), new_uuid7()
    _seed_user(db, owner_id)
    _seed_user(db, other_id)
    actor, other = _actor(owner_id), _actor(other_id)
    # Timed, recorded-only and untimed entries, so every part of the sort key takes part.
    specs = (
        (datetime(2026, 7, 21, 9, tzinfo=UTC), None, "nine"),
        (datetime(2026, 7, 21, 11, tzinfo=UTC), None, "eleven"),
        (None, datetime(2026, 7, 21, 10, tzinfo=UTC), "recorded"),
        (None, None, "untimed-a"),
        (None, None, "untimed-b"),
    )
    for service_actor, prefix in ((actor, "own"), (other, "other")):
        for occurred_at, recorded_at, suffix in specs:
            source = _create_source(
                journal_service,
                service_actor,
                raw_text=f"Syntetisk källa {prefix} {suffix}",
                occurred_at=occurred_at,
                source_recorded_at=recorded_at,
                key=f"order-source-{prefix}-{suffix}",
            )
            _create_manual_entry(
                journal_service,
                service_actor,
                source.id,
                title=f"Post {prefix} {suffix}",
                key=f"order-entry-{prefix}-{suffix}",
            )

    def read(order: str, limit: int, cursor: str | None = None) -> Any:
        return journal_service.entries.list_entries(
            actor,
            start_date=JOURNAL_DATE,
            end_date=JOURNAL_DATE,
            order=order,
            limit=limit,
            cursor=cursor,
        )

    def paged(order: str) -> list[UUID]:
        seen: list[UUID] = []
        cursor = None
        while True:
            page = read(order, 2, cursor)
            seen.extend(entry.id for entry in page.items)
            cursor = page.next_cursor
            if cursor is None:
                return seen

    ascending = [entry.id for entry in read("asc", 100).items]
    assert len(ascending) == len(specs), "only the owner's entries are listed"
    untimed = 2
    timed, undated = ascending[:-untimed], ascending[-untimed:]
    # Entries without a time are last in both orders; the timed ones reverse.
    descending = timed[::-1] + undated[::-1]
    assert [entry.id for entry in read("desc", 100).items] == descending
    assert paged("asc") == ascending
    assert paged("desc") == descending, "the cursor follows the descending order"
    assert [entry.title for entry in read("asc", 100).items][-untimed:] == [
        "Post own untimed-a",
        "Post own untimed-b",
    ]

    asc_cursor = read("asc", 2).next_cursor
    desc_cursor = read("desc", 2).next_cursor
    with pytest.raises(ValidationError):
        read("desc", 2, asc_cursor)
    with pytest.raises(ValidationError):
        read("asc", 2, desc_cursor)


@pytest.mark.integration
def test_list_orders_by_journal_date_first_in_both_directions_and_refuses_old_cursors(
    db: DatabaseHarness, journal_service: Any
) -> None:
    owner_id = new_uuid7()
    _seed_user(db, owner_id)
    actor = _actor(owner_id)
    monday, tuesday, wednesday = date(2026, 7, 20), date(2026, 7, 21), date(2026, 7, 22)

    def at(day: date, hour: int) -> datetime:
        return datetime(day.year, day.month, day.day, hour, tzinfo=UTC)

    # Tuesday's untimed entry is written before Wednesday's timed ones, so only the day keeps it
    # ahead of them; the late entry for Monday carries a time on Tuesday and stays on Monday.
    specs = (
        (tuesday, at(tuesday, 15), None, "tue-15"),
        (monday, at(monday, 9), None, "mon-09"),
        (tuesday, None, None, "tue-untimed"),
        (wednesday, at(wednesday, 8), None, "wed-08"),
        (monday, None, None, "mon-untimed"),
        (monday, at(tuesday, 7), None, "mon-late"),
        (tuesday, None, at(tuesday, 10), "tue-recorded"),
        (wednesday, None, None, "wed-untimed"),
    )
    titles: dict[UUID, str] = {}
    for day, occurred_at, recorded_at, suffix in specs:
        source = _create_source(
            journal_service,
            actor,
            raw_text=f"Syntetisk dagordningskälla {suffix}",
            occurred_at=occurred_at,
            source_recorded_at=recorded_at,
            key=f"day-order-source-{suffix}",
            journal_date=day,
        )
        entry = _create_manual_entry(
            journal_service, actor, source.id, title=suffix, key=f"day-order-entry-{suffix}"
        )
        titles[entry.id] = suffix

    def read(order: str, limit: int, cursor: str | None = None) -> Any:
        return journal_service.entries.list_entries(
            actor,
            start_date=monday,
            end_date=wednesday,
            order=order,
            limit=limit,
            cursor=cursor,
        )

    def paged(order: str, limit: int) -> list[str]:
        seen: list[str] = []
        cursor = None
        while True:
            page = read(order, limit, cursor)
            seen.extend(titles[entry.id] for entry in page.items)
            cursor = page.next_cursor
            if cursor is None:
                return seen

    ascending = [
        "mon-09",
        "mon-late",
        "mon-untimed",
        "tue-recorded",
        "tue-15",
        "tue-untimed",
        "wed-08",
        "wed-untimed",
    ]
    descending = [
        "wed-08",
        "wed-untimed",
        "tue-15",
        "tue-recorded",
        "tue-untimed",
        "mon-late",
        "mon-09",
        "mon-untimed",
    ]
    # `mon-late` occurred on Tuesday morning but belongs to Monday, so it follows Monday's 09:00
    # entry by its time and ahead of Monday's untimed one.
    assert [titles[entry.id] for entry in read("asc", 100).items] == ascending
    assert [titles[entry.id] for entry in read("desc", 100).items] == descending
    for limit in (1, 2, 3):
        assert paged("asc", limit) == ascending
        assert paged("desc", limit) == descending

    # A cursor from before the date-first key (the old query key) is refused, not misread.
    old_key = "journal:entries:v1:from=2026-07-20:to=2026-07-22:archived=false"
    codec = journal_service.entries.cursor_codec
    old_cursor = codec.encode_keyset(
        owner_id, (at(tuesday, 15), 0, at(tuesday, 15), new_uuid7()), old_key
    )
    with pytest.raises(ValidationError):
        read("asc", 2, old_cursor)


@pytest.mark.integration
@pytest.mark.parametrize("surface", ["list", "day"])
def test_paging_survives_entries_removed_and_added_between_pages(
    db: DatabaseHarness, journal_service: Any, surface: str
) -> None:
    owner_id = new_uuid7()
    _seed_user(db, owner_id)
    actor = _actor(owner_id)

    def make(suffix: str, occurred_at: datetime | None) -> Any:
        source = _create_source(
            journal_service,
            actor,
            raw_text=f"Syntetisk sidkälla {suffix}",
            occurred_at=occurred_at,
            source_recorded_at=None,
            key=f"paging-source-{suffix}",
        )
        return _create_manual_entry(
            journal_service, actor, source.id, title=f"Post {suffix}", key=f"paging-entry-{suffix}"
        )

    def page(cursor: str | None) -> tuple[list[UUID], str | None]:
        if surface == "list":
            result = journal_service.entries.list_entries(
                actor, start_date=JOURNAL_DATE, end_date=JOURNAL_DATE, limit=2, cursor=cursor
            )
            return [entry.id for entry in result.items], result.next_cursor
        day = journal_service.day.get_day(
            actor, journal_date=JOURNAL_DATE, limit=2, cursor=cursor, include_done=False
        )
        return [entry.id for entry in day.entries], day.next_cursor

    def at(hour: int, minute: int = 0) -> datetime:
        return datetime(2026, 7, 21, hour, minute, tzinfo=UTC)

    # Three untimed entries sort after every timed one; the page border falls among them.
    initial = [make(str(hour), at(hour)) for hour in (2, 3, 4, 5)]
    initial += [make(f"untimed-{index}", None) for index in range(3)]

    first, cursor = page(None)
    assert cursor is not None
    assert len(first) == 2

    # Before the cursor: one served entry leaves, one new one arrives. After it: one arrives.
    served_first = next(entry for entry in initial if entry.id == first[0])
    journal_service.entries.archive_entry(
        actor,
        entry_id=served_first.id,
        expected_version=served_first.version,
        idempotency_key="paging-archive",
    )
    make("before", at(1))
    late = make("late", at(4, 30))

    seen = list(first)
    while cursor is not None:
        ids, cursor = page(cursor)
        assert ids
        seen.extend(ids)

    assert len(seen) == len(set(seen)), "no entry is served twice"
    remaining = [entry for entry in initial if entry.id != served_first.id] + [late]
    expected_after_cursor = [
        entry.id for entry in sorted(remaining, key=entry_page_key) if entry.id not in first
    ]
    assert seen[2:] == expected_after_cursor, "no entry after the cursor is skipped"


@pytest.mark.integration
def test_concurrent_equal_manual_retries_return_one_durable_package(
    db: DatabaseHarness, journal_service: Any
) -> None:
    owner_id = new_uuid7()
    _seed_user(db, owner_id)
    actor = _actor(owner_id)
    project_id, task_id, contact_id = _seed_relation_targets(db, owner_id)
    source = _create_source(journal_service, actor)

    def finalize(_: int) -> UUID:
        return _create_manual_entry(
            journal_service,
            actor,
            source.id,
            project_ids=(project_id,),
            task_ids=(task_id,),
            contact_ids=(contact_id,),
            key="manual-journal-concurrent-equal",
        ).id

    with ThreadPoolExecutor(max_workers=2) as pool:
        result_ids = list(pool.map(finalize, range(2)))

    assert len(set(result_ids)) == 1
    with db.factory() as session:
        assert session.scalar(select(func.count()).select_from(JournalEntryRow)) == 1
        assert session.scalar(select(func.count()).select_from(JournalEntryProjectRow)) == 1
        assert session.scalar(select(func.count()).select_from(JournalEntryTaskRow)) == 1
        assert session.scalar(select(func.count()).select_from(JournalEntryContactRow)) == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(IdempotencyRow)
                .where(IdempotencyRow.idempotency_key == "manual-journal-concurrent-equal")
            )
            == 1
        )
