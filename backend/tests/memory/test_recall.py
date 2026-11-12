"""PostgreSQL integration tests for verified recall.

The fake provider supplies facts; Postgres decides which of them may leave. Rows are written with
the ORM so that lifecycle state (trash, exclusion, switched-off domains, missing rows) is explicit.
One fake fact per non-empty line, so counts are exact.
"""

import logging
from collections.abc import Iterator
from datetime import UTC, date, datetime
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from sidekick.memory.adapters.fake import FakeMemoryProvider
from sidekick.memory.application.recall import RecallResult, recall_verified
from sidekick.memory.domain import MemoryKind
from sidekick.memory.infrastructure.store import SqlAlchemyMemoryStore
from sidekick.memory.ports import MemoryFact, RetainItem
from sidekick.shared.errors import InvalidInputError
from sidekick.shared.persistence.models import (
    ContactRow,
    JournalEntryRow,
    JournalSourceRow,
    MemorySettingsRow,
    MemorySourceRow,
    TaskRow,
    UserRow,
)
from sidekick.shared.types import new_uuid7
from tests.db import database_factory

NOW = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
JOURNAL_DATE = date(2026, 10, 20)
ALL_SCOPES = frozenset({"journal:read", "contacts:read", "projects:read", "tasks:read"})


class _LeakingFakeProvider(FakeMemoryProvider):
    """The fake, plus facts a defective provider might return for another owner's document."""

    def __init__(self, leaked: tuple[MemoryFact, ...]) -> None:
        super().__init__()
        self._leaked = leaked

    def recall(self, *, owner_id: UUID, query: str, max_tokens: int) -> tuple[MemoryFact, ...]:
        own = super().recall(owner_id=owner_id, query=query, max_tokens=max_tokens)
        return (*own, *self._leaked)


class _Collect(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def recall_log() -> Iterator[_Collect]:
    """Capture the recall logger directly. Another test's logging setup (the `sidekick` logger has
    propagate=False after app setup, plus levels and `disabled`) must not hide the records."""

    handler = _Collect()
    logger = logging.getLogger("sidekick.memory.recall")
    saved = (logger.level, logger.disabled, logger.propagate)
    logger.setLevel(logging.INFO)
    logger.disabled = False
    logger.addHandler(handler)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(saved[0])
        logger.disabled = saved[1]
        logger.propagate = saved[2]


def _owner(factory: sessionmaker[Session]) -> UUID:
    owner_id = new_uuid7()
    with factory.begin() as session:
        session.add(
            UserRow(
                id=owner_id,
                username=f"recall-{owner_id.hex}",
                display_name="Minne",
                active=True,
                created_at=NOW,
            )
        )
    return owner_id


def _settings(
    factory: sessionmaker[Session],
    owner_id: UUID,
    *,
    journal: bool = False,
    contacts: bool = False,
    projects: bool = False,
    tasks: bool = False,
    paused: bool = False,
) -> None:
    with factory.begin() as session:
        session.add(
            MemorySettingsRow(
                owner_id=owner_id,
                journal=journal,
                contacts=contacts,
                projects=projects,
                tasks=tasks,
                paused=paused,
                version=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )


def _contact(
    factory: sessionmaker[Session], owner_id: UUID, name: str, *, trashed: bool = False
) -> UUID:
    contact_id = new_uuid7()
    with factory.begin() as session:
        session.add(
            ContactRow(
                id=contact_id,
                owner_id=owner_id,
                display_name=name,
                display_name_key=name.casefold(),
                context_note=None,
                relationship=None,
                organization=None,
                created_at=NOW,
                updated_at=NOW,
                archived=False,
                archived_at=None,
                version=1,
                trashed_at=NOW if trashed else None,
            )
        )
    return contact_id


def _task(factory: sessionmaker[Session], owner_id: UUID, title: str) -> UUID:
    task_id = new_uuid7()
    with factory.begin() as session:
        session.add(
            TaskRow(
                id=task_id,
                owner_id=owner_id,
                project_id=None,
                title=title,
                description=None,
                status="todo",
                priority="normal",
                completed_at=None,
                created_at=NOW,
                updated_at=NOW,
                version=1,
                attention_requested=False,
                waiting_on_contact_id=None,
                waiting_since=None,
                recurrence=None,
                trashed_at=None,
            )
        )
    return task_id


def _journal(factory: sessionmaker[Session], owner_id: UUID, title: str) -> UUID:
    source_id = new_uuid7()
    entry_id = new_uuid7()
    raw_text = f"Råtext för {title}"
    with factory.begin() as session:
        session.add(
            JournalSourceRow(
                id=source_id,
                owner_id=owner_id,
                source_type="manual_text",
                journal_date=JOURNAL_DATE,
                raw_text=raw_text,
                content_fingerprint=sha256(raw_text.encode()).hexdigest(),
                replaces_source_id=None,
                created_at=NOW,
                trashed_at=None,
            )
        )
        session.flush()
        session.add(
            JournalEntryRow(
                id=entry_id,
                owner_id=owner_id,
                source_id=source_id,
                journal_date=JOURNAL_DATE,
                title=title,
                summary=None,
                key_points=[],
                version=1,
                created_at=NOW,
                updated_at=NOW,
                archived_at=None,
                trashed_at=None,
            )
        )
    return entry_id


def _memory_row(
    factory: sessionmaker[Session],
    owner_id: UUID,
    kind: MemoryKind,
    source_id: UUID,
    *,
    excluded: bool = False,
) -> str:
    """A `memory_sources` row and the opaque document id the provider knows it by."""

    row_id = new_uuid7()
    doc_key = f"d1_{row_id.hex}"
    with factory.begin() as session:
        session.add(
            MemorySourceRow(
                id=row_id,
                owner_id=owner_id,
                source_kind=kind.value,
                source_id=source_id,
                doc_key=doc_key,
                fingerprint=sha256(str(source_id).encode()).hexdigest(),
                pipeline_version=1,
                status="retained",
                attempts=1,
                next_attempt_at=None,
                operation_id="fake-op-000001",
                source_updated_at=NOW,
                retained_at=NOW,
                failure_category=None,
                excluded=excluded,
            )
        )
    return doc_key


def _retain(
    provider: FakeMemoryProvider,
    owner_id: UUID,
    doc_key: str,
    text: str,
    *,
    timestamp: str = "unset",
) -> None:
    provider.retain_batch(
        owner_id=owner_id,
        items=[
            RetainItem(
                document_id=doc_key,
                content=text,
                timestamp=timestamp,
                entities=(),
                tags=(),
            )
        ],
    )


def _recall(
    factory: sessionmaker[Session],
    provider: FakeMemoryProvider,
    owner_id: UUID,
    *,
    query: str = "Sara",
    limit: int = 8,
    scopes: frozenset[str] = ALL_SCOPES,
) -> RecallResult:
    with factory() as session:
        return recall_verified(
            SqlAlchemyMemoryStore(factory),
            session,
            provider,
            owner_id=owner_id,
            query=query,
            limit=limit,
            scopes=scopes,
            correlation_id="recall-test",
        )


@pytest.mark.integration
def test_verified_facts_carry_source_kind_id_and_dates() -> None:
    factory = database_factory()
    owner = _owner(factory)
    _settings(factory, owner, journal=True, contacts=True)
    entry = _journal(factory, owner, "Dagbok")
    contact = _contact(factory, owner, "Sara")
    provider = FakeMemoryProvider()
    _retain(
        provider,
        owner,
        _memory_row(factory, owner, MemoryKind.JOURNAL_ENTRY, entry),
        "Sara bytte jobb till Volvo",
        timestamp="2026-10-12",
    )
    _retain(
        provider, owner, _memory_row(factory, owner, MemoryKind.CONTACT, contact), "Sara är kollega"
    )

    result = _recall(factory, provider, owner)

    assert result.status == "ok"
    assert result.truncated is False
    assert {(fact.source_kind, fact.source_id) for fact in result.facts} == {
        (MemoryKind.JOURNAL_ENTRY, entry),
        (MemoryKind.CONTACT, contact),
    }
    journal_fact = next(f for f in result.facts if f.source_kind is MemoryKind.JOURNAL_ENTRY)
    assert journal_fact.occurred_start == "2026-10-12"
    assert journal_fact.occurred_end == "2026-10-12"
    assert journal_fact.archived is False
    contact_fact = next(f for f in result.facts if f.source_kind is MemoryKind.CONTACT)
    assert contact_fact.occurred_start is None


@pytest.mark.integration
def test_trashed_source_is_dropped() -> None:
    factory = database_factory()
    owner = _owner(factory)
    _settings(factory, owner, contacts=True, tasks=True)
    live = _contact(factory, owner, "Sara")
    trashed_contact = _contact(factory, owner, "Sara gammal", trashed=True)
    provider = FakeMemoryProvider()
    _retain(provider, owner, _memory_row(factory, owner, MemoryKind.CONTACT, live), "Sara live")
    _retain(
        provider,
        owner,
        _memory_row(factory, owner, MemoryKind.CONTACT, trashed_contact),
        "Sara i papperskorgen",
    )

    result = _recall(factory, provider, owner)

    assert result.status == "ok"
    assert [fact.source_id for fact in result.facts] == [live]
    assert "Sara i papperskorgen" not in {fact.text for fact in result.facts}


@pytest.mark.integration
def test_foreign_owner_document_is_dropped() -> None:
    factory = database_factory()
    owner = _owner(factory)
    other = _owner(factory)
    _settings(factory, owner, contacts=True)
    _settings(factory, other, contacts=True)
    own_contact = _contact(factory, owner, "Sara")
    own_doc = _memory_row(factory, owner, MemoryKind.CONTACT, own_contact)
    foreign_contact = _contact(factory, other, "Sara")
    foreign_doc = _memory_row(factory, other, MemoryKind.CONTACT, foreign_contact)
    leaked = MemoryFact(
        id=f"{foreign_doc}#1",
        text="Sara hemlig fakta",
        document_id=foreign_doc,
        occurred_start=None,
        occurred_end=None,
    )
    provider = _LeakingFakeProvider((leaked,))
    _retain(provider, owner, own_doc, "Sara är kollega")
    _retain(provider, other, foreign_doc, "Sara hemlig fakta")

    result = _recall(factory, provider, owner)

    assert [fact.source_id for fact in result.facts] == [own_contact]
    assert all("hemlig" not in fact.text for fact in result.facts)


@pytest.mark.integration
def test_fact_without_memory_row_is_dropped() -> None:
    factory = database_factory()
    owner = _owner(factory)
    _settings(factory, owner, contacts=True)
    contact = _contact(factory, owner, "Sara")
    provider = FakeMemoryProvider()
    _retain(
        provider, owner, _memory_row(factory, owner, MemoryKind.CONTACT, contact), "Sara är kollega"
    )
    _retain(provider, owner, f"d1_{uuid4().hex}", "Sara utan rad i memory_sources")

    result = _recall(factory, provider, owner)

    assert result.status == "ok"
    assert [fact.source_id for fact in result.facts] == [contact]
    assert "Sara utan rad i memory_sources" not in {fact.text for fact in result.facts}


@pytest.mark.integration
def test_memory_row_whose_source_record_is_gone_is_dropped() -> None:
    factory = database_factory()
    owner = _owner(factory)
    _settings(factory, owner, contacts=True)
    gone_doc = _memory_row(factory, owner, MemoryKind.CONTACT, new_uuid7())
    provider = FakeMemoryProvider()
    _retain(provider, owner, gone_doc, "Sara finns inte längre")

    result = _recall(factory, provider, owner)

    assert result == RecallResult(status="empty")


@pytest.mark.integration
def test_fact_of_kind_without_read_scope_is_dropped() -> None:
    factory = database_factory()
    owner = _owner(factory)
    _settings(factory, owner, contacts=True, tasks=True)
    contact = _contact(factory, owner, "Sara")
    task = _task(factory, owner, "Ring Sara")
    provider = FakeMemoryProvider()
    _retain(provider, owner, _memory_row(factory, owner, MemoryKind.CONTACT, contact), "Sara ok")
    _retain(provider, owner, _memory_row(factory, owner, MemoryKind.TASK, task), "Sara uppgift")

    result = _recall(factory, provider, owner, scopes=frozenset({"contacts:read"}))

    assert result.status == "ok"
    assert {fact.source_kind for fact in result.facts} == {MemoryKind.CONTACT}
    assert _recall(factory, provider, owner, scopes=frozenset()).status == "empty"


@pytest.mark.integration
def test_unavailable_provider_gives_status_unavailable_without_raising() -> None:
    factory = database_factory()
    owner = _owner(factory)
    _settings(factory, owner, contacts=True)
    provider = FakeMemoryProvider(available=False)

    result = _recall(factory, provider, owner)

    assert result == RecallResult(status="unavailable")


class _RaisingProvider(FakeMemoryProvider):
    """A provider that fails with an exception outside the MemoryProviderError contract."""

    def recall(self, *, owner_id: UUID, query: str, max_tokens: int) -> tuple[MemoryFact, ...]:
        raise RuntimeError("Sara hemlig fråga i felmeddelandet")


@pytest.mark.integration
def test_any_provider_exception_gives_unavailable_and_logs_only_its_type(
    recall_log: _Collect,
) -> None:
    factory = database_factory()
    owner = _owner(factory)
    _settings(factory, owner, contacts=True)

    result = _recall(factory, _RaisingProvider(), owner)

    assert result == RecallResult(status="unavailable")
    logged = " ".join(f"{record.getMessage()} {record.__dict__!r}" for record in recall_log.records)
    assert "memory_recall_unavailable" in logged
    assert "RuntimeError" in logged
    assert "hemlig" not in logged
    assert "Sara" not in logged


@pytest.mark.integration
def test_no_database_transaction_is_open_during_the_provider_call() -> None:
    factory = database_factory()
    owner = _owner(factory)
    _settings(factory, owner, contacts=True)
    contact = _contact(factory, owner, "Sara")
    doc = _memory_row(factory, owner, MemoryKind.CONTACT, contact)
    provider = FakeMemoryProvider()
    _retain(provider, owner, doc, "Sara är kollega")
    open_during_call: list[bool] = []

    class _TransactionProbe(FakeMemoryProvider):
        def recall(self, *, owner_id: UUID, query: str, max_tokens: int) -> tuple[MemoryFact, ...]:
            open_during_call.append(session.in_transaction())
            return provider.recall(owner_id=owner_id, query=query, max_tokens=max_tokens)

    with factory() as session:
        result = recall_verified(
            SqlAlchemyMemoryStore(factory),
            session,
            _TransactionProbe(),
            owner_id=owner,
            query="Sara",
            limit=8,
            scopes=ALL_SCOPES,
            correlation_id="recall-test",
        )

    assert open_during_call == [False]
    assert [fact.source_id for fact in result.facts] == [contact]


@pytest.mark.integration
def test_missing_settings_all_domains_off_and_paused_never_reach_the_provider() -> None:
    factory = database_factory()
    no_settings = _owner(factory)
    all_off = _owner(factory)
    _settings(factory, all_off)
    paused = _owner(factory)
    _settings(factory, paused, contacts=True, paused=True)
    # An unavailable provider proves that none of these statuses calls it.
    provider = FakeMemoryProvider(available=False)

    assert _recall(factory, provider, no_settings).status == "disabled"
    assert _recall(factory, provider, all_off).status == "disabled"
    assert _recall(factory, provider, paused).status == "paused"


@pytest.mark.integration
def test_excluded_row_and_switched_off_domain_are_dropped() -> None:
    factory = database_factory()
    owner = _owner(factory)
    _settings(factory, owner, contacts=True)
    kept = _contact(factory, owner, "Sara")
    excluded = _contact(factory, owner, "Sara undantagen")
    task = _task(factory, owner, "Sara uppgift")
    provider = FakeMemoryProvider()
    _retain(provider, owner, _memory_row(factory, owner, MemoryKind.CONTACT, kept), "Sara ok")
    _retain(
        provider,
        owner,
        _memory_row(factory, owner, MemoryKind.CONTACT, excluded, excluded=True),
        "Sara undantagen",
    )
    _retain(provider, owner, _memory_row(factory, owner, MemoryKind.TASK, task), "Sara uppgift")

    result = _recall(factory, provider, owner)

    assert [fact.source_id for fact in result.facts] == [kept]


@pytest.mark.integration
def test_limit_truncates_verified_facts_and_marks_truncation() -> None:
    factory = database_factory()
    owner = _owner(factory)
    _settings(factory, owner, contacts=True)
    provider = FakeMemoryProvider()
    for index in range(3):
        contact = _contact(factory, owner, f"Sara {index}")
        _retain(
            provider,
            owner,
            _memory_row(factory, owner, MemoryKind.CONTACT, contact),
            f"Sara nummer {index}",
        )

    result = _recall(factory, provider, owner, limit=2)

    assert result.status == "ok"
    assert len(result.facts) == 2
    assert result.truncated is True


@pytest.mark.integration
def test_out_of_bounds_query_or_limit_is_refused() -> None:
    factory = database_factory()
    owner = _owner(factory)
    _settings(factory, owner, contacts=True)
    provider = FakeMemoryProvider()

    with pytest.raises(InvalidInputError):
        _recall(factory, provider, owner, limit=0)
    with pytest.raises(InvalidInputError):
        _recall(factory, provider, owner, limit=21)
    with pytest.raises(InvalidInputError):
        _recall(factory, provider, owner, query="x")


@pytest.mark.integration
def test_logs_carry_counts_never_query_or_fact_text(recall_log: _Collect) -> None:
    factory = database_factory()
    owner = _owner(factory)
    _settings(factory, owner, contacts=True)
    contact = _contact(factory, owner, "Sara")
    provider = FakeMemoryProvider()
    _retain(
        provider,
        owner,
        _memory_row(factory, owner, MemoryKind.CONTACT, contact),
        "Hemlig dagboksrad om Sara",
    )
    _retain(provider, owner, f"d1_{uuid4().hex}", "Hemlig rad utan rad")

    result = _recall(factory, provider, owner, query="Sara")

    assert result.status == "ok"
    logged = " ".join(f"{record.getMessage()} {record.__dict__!r}" for record in recall_log.records)
    assert "memory_recall" in logged
    assert "Hemlig" not in logged
    assert "Sara" not in logged


class _ChangingPolicyProvider(FakeMemoryProvider):
    """A slow provider: while `recall` runs, the owner changes the memory settings.

    The change is committed from another session inside the call, which is what a concurrent
    request from the owner would do. The facts are those the provider held before the change.
    """

    def __init__(
        self,
        inner: FakeMemoryProvider,
        factory: sessionmaker[Session],
        owner_id: UUID,
        **settings_change: bool,
    ) -> None:
        super().__init__()
        self._inner = inner
        self._factory = factory
        self._owner_id = owner_id
        self._change = settings_change

    def recall(self, *, owner_id: UUID, query: str, max_tokens: int) -> tuple[MemoryFact, ...]:
        facts = self._inner.recall(owner_id=owner_id, query=query, max_tokens=max_tokens)
        with self._factory.begin() as other:
            other.execute(
                update(MemorySettingsRow)
                .where(MemorySettingsRow.owner_id == self._owner_id)
                .values(**self._change)
            )
        return facts


def _owner_with_one_fact_per_kind(
    factory: sessionmaker[Session], provider: FakeMemoryProvider
) -> tuple[UUID, UUID, UUID]:
    owner = _owner(factory)
    _settings(factory, owner, contacts=True, tasks=True)
    contact = _contact(factory, owner, "Sara")
    task = _task(factory, owner, "Sara uppgift")
    _retain(provider, owner, _memory_row(factory, owner, MemoryKind.CONTACT, contact), "Sara ok")
    _retain(provider, owner, _memory_row(factory, owner, MemoryKind.TASK, task), "Sara uppgift ok")
    return owner, contact, task


@pytest.mark.integration
def test_memory_paused_during_the_provider_call_returns_no_facts() -> None:
    factory = database_factory()
    probe = FakeMemoryProvider()
    owner, _contact_id, _task_id = _owner_with_one_fact_per_kind(factory, probe)
    provider = _ChangingPolicyProvider(probe, factory, owner, paused=True)

    result = _recall(factory, provider, owner)

    assert (result.status, result.facts) == ("paused", ())


@pytest.mark.integration
def test_memory_switched_off_during_the_provider_call_returns_no_facts() -> None:
    factory = database_factory()
    probe = FakeMemoryProvider()
    owner, _contact_id, _task_id = _owner_with_one_fact_per_kind(factory, probe)
    provider = _ChangingPolicyProvider(probe, factory, owner, contacts=False, tasks=False)

    result = _recall(factory, provider, owner)

    assert (result.status, result.facts) == ("disabled", ())


@pytest.mark.integration
def test_a_kind_narrowed_during_the_provider_call_is_filtered_from_the_facts() -> None:
    factory = database_factory()
    probe = FakeMemoryProvider()
    owner, contact, _task_id = _owner_with_one_fact_per_kind(factory, probe)
    provider = _ChangingPolicyProvider(probe, factory, owner, tasks=False)

    result = _recall(factory, provider, owner)

    assert result.status == "ok"
    assert [(fact.source_kind, fact.source_id) for fact in result.facts] == [
        (MemoryKind.CONTACT, contact)
    ]


LATER = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


def _change_contact(factory: sessionmaker[Session], contact_id: UUID) -> None:
    with factory.begin() as session:
        session.execute(
            update(ContactRow).where(ContactRow.id == contact_id).values(updated_at=LATER)
        )


def _catch_up_row(factory: sessionmaker[Session], doc_key: str) -> None:
    """What the sync does once the replacement document is retained."""

    with factory.begin() as session:
        session.execute(
            update(MemorySourceRow)
            .where(MemorySourceRow.doc_key == doc_key)
            .values(source_updated_at=LATER, status="retained", retained_at=LATER)
        )


@pytest.mark.integration
def test_fact_from_an_older_source_version_is_dropped_until_the_replacement_is_retained(
    recall_log: _Collect,
) -> None:
    factory = database_factory()
    owner = _owner(factory)
    _settings(factory, owner, contacts=True)
    changed = _contact(factory, owner, "Sara")
    unchanged = _contact(factory, owner, "Sara också")
    provider = FakeMemoryProvider()
    changed_doc = _memory_row(factory, owner, MemoryKind.CONTACT, changed)
    _retain(provider, owner, changed_doc, "Sara jobbar på Volvo")
    _retain(
        provider,
        owner,
        _memory_row(factory, owner, MemoryKind.CONTACT, unchanged),
        "Sara är kollega",
    )
    _change_contact(factory, changed)

    stale = _recall(factory, provider, owner)

    assert [fact.source_id for fact in stale.facts] == [unchanged]
    logged = " ".join(repr(record.__dict__) for record in recall_log.records)
    assert "'dropped_stale_version': 1" in logged
    assert "Volvo" not in logged

    _retain(provider, owner, changed_doc, "Sara jobbar på Saab")
    _catch_up_row(factory, changed_doc)

    fresh = _recall(factory, provider, owner)

    assert {fact.text for fact in fresh.facts} == {"Sara jobbar på Saab", "Sara är kollega"}


def _requeue(factory: sessionmaker[Session], doc_key: str, status: str, **values: object) -> None:
    """Put a retained row in another state, as a pipeline bump, a retry or a failure would."""

    with factory.begin() as session:
        session.execute(
            update(MemorySourceRow)
            .where(MemorySourceRow.doc_key == doc_key)
            .values(
                status=status,
                operation_id="fake-op-000002" if status == "submitted" else None,
                failure_category=values.pop("failure_category", None),
                **values,
            )
        )


def _one_contact_fact(factory: sessionmaker[Session]) -> tuple[UUID, UUID, str, FakeMemoryProvider]:
    owner = _owner(factory)
    _settings(factory, owner, contacts=True)
    contact = _contact(factory, owner, "Sara")
    provider = FakeMemoryProvider()
    doc_key = _memory_row(factory, owner, MemoryKind.CONTACT, contact)
    _retain(provider, owner, doc_key, "Sara gammal version")
    return owner, contact, doc_key, provider


@pytest.mark.integration
@pytest.mark.parametrize("status", ["pending", "submitted", "failed", "parked"])
def test_fact_of_a_requeued_row_is_still_released_while_the_source_is_unchanged(
    status: str,
) -> None:
    """A pipeline-version bump, a retry or a parked row keeps the last retained document current."""

    factory = database_factory()
    owner, contact, doc_key, provider = _one_contact_fact(factory)
    _requeue(
        factory,
        doc_key,
        status,
        pipeline_version=2,
        failure_category="rejected" if status in ("failed", "parked") else None,
    )

    result = _recall(factory, provider, owner)

    assert [fact.source_id for fact in result.facts] == [contact]


@pytest.mark.integration
@pytest.mark.parametrize("status", ["pending", "submitted", "failed", "parked"])
def test_fact_of_a_requeued_row_is_dropped_once_the_source_changed_after_the_retain(
    status: str,
) -> None:
    factory = database_factory()
    owner, contact, doc_key, provider = _one_contact_fact(factory)
    _requeue(
        factory,
        doc_key,
        status,
        source_updated_at=LATER,
        failure_category="rejected" if status in ("failed", "parked") else None,
    )
    _change_contact(factory, contact)

    assert _recall(factory, provider, owner) == RecallResult(status="empty")


@pytest.mark.integration
def test_fact_of_a_row_that_never_had_a_retain_is_dropped() -> None:
    factory = database_factory()
    owner, _contact_id, doc_key, provider = _one_contact_fact(factory)
    _requeue(factory, doc_key, "pending", retained_at=None)

    assert _recall(factory, provider, owner) == RecallResult(status="empty")


@pytest.mark.integration
def test_fact_of_a_removal_marker_is_dropped_although_its_source_is_live() -> None:
    factory = database_factory()
    owner, _contact_id, doc_key, provider = _one_contact_fact(factory)
    _requeue(factory, doc_key, "parked", failure_category="removed")

    assert _recall(factory, provider, owner) == RecallResult(status="empty")


@pytest.mark.integration
def test_excluded_source_is_never_recalled_even_when_the_document_lingers() -> None:
    factory = database_factory()
    owner = _owner(factory)
    _settings(factory, owner, contacts=True)
    contact = _contact(factory, owner, "Sara")
    provider = FakeMemoryProvider()
    _retain(
        provider,
        owner,
        _memory_row(factory, owner, MemoryKind.CONTACT, contact, excluded=True),
        "Sara utesluten",
    )

    assert _recall(factory, provider, owner) == RecallResult(status="empty")


class _TypedFakeProvider(FakeMemoryProvider):
    """The fake, but every fact carries the given provider fact type."""

    def __init__(self, fact_type: str | None) -> None:
        super().__init__()
        self._fact_type = fact_type

    def recall(self, *, owner_id: UUID, query: str, max_tokens: int) -> tuple[MemoryFact, ...]:
        return tuple(
            MemoryFact(
                id=fact.id,
                text=fact.text,
                document_id=fact.document_id,
                occurred_start=fact.occurred_start,
                occurred_end=fact.occurred_end,
                fact_type=self._fact_type,
            )
            for fact in super().recall(owner_id=owner_id, query=query, max_tokens=max_tokens)
        )


@pytest.mark.integration
@pytest.mark.parametrize(
    ("fact_type", "released"),
    [
        ("world", True),
        ("experience", True),
        (None, True),
        ("observation", False),
        ("opinion", False),
        ("", False),
    ],
)
def test_only_allowed_fact_types_are_released(fact_type: str | None, released: bool) -> None:
    factory = database_factory()
    owner = _owner(factory)
    _settings(factory, owner, contacts=True)
    contact = _contact(factory, owner, "Sara")
    provider = _TypedFakeProvider(fact_type)
    _retain(
        provider, owner, _memory_row(factory, owner, MemoryKind.CONTACT, contact), "Sara är kollega"
    )

    result = _recall(factory, provider, owner)

    assert (result.status == "ok") is released
    assert len(result.facts) == (1 if released else 0)
