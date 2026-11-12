"""Given/When/Then examples for the AI-independent manual Journal path."""

from __future__ import annotations

import copy
import inspect
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from sidekick.journal.application.service import JournalService
from sidekick.journal.domain.day_done import DayDone
from sidekick.journal.domain.entry import (
    EntryHead,
    KeyPoint,
    KeyPointKind,
    entry_order_key,
    entry_page_key,
)
from sidekick.journal.domain.source import SourceType
from sidekick.projects.domain import Project, ProjectStatus
from sidekick.shared.errors import NotFoundError, ValidationError
from sidekick.shared.types import Actor
from sidekick.tasks.domain import Priority, Task, TaskStatus
from tests.support.fakes import (
    JOURNAL_CONTACT_ID,
    JOURNAL_PROJECT_ID,
    JOURNAL_REPLACEMENT_TEXT,
    JOURNAL_SOURCE_TEXT,
    JOURNAL_TASK_ID,
    ContactBuilder,
    InMemoryStore,
    JournalProviderSpy,
    make_cursor_codec,
)

OWNER_ID = UUID("018af000-0000-7000-8000-000000000001")
# Every Project belongs to one owner-consistent Domain.
JOURNAL_DOMAIN_ID = UUID("01910000-0000-7000-8000-000000000010")
JOURNAL_DATE = date(2026, 7, 21)
CREATED_ON_JULY_24 = datetime(2026, 7, 24, 10, tzinfo=UTC)


class MutableClock:
    def __init__(self, value: datetime = CREATED_ON_JULY_24) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


class ManualJournalStore(InMemoryStore):
    """Journal-focused fake with rollback semantics for application BDD tests."""

    def __init__(self) -> None:
        super().__init__()
        self.journal_sources: dict[UUID, Any] = {}
        self.journal_entries: dict[UUID, Any] = {}
        self.journal_entry_projects: set[tuple[UUID, UUID]] = set()
        self.journal_entry_tasks: set[tuple[UUID, UUID]] = set()
        self.journal_entry_contacts: set[tuple[UUID, UUID]] = set()
        self.processing_runs: list[Any] = []

    def transaction(self, operation: Any) -> Any:
        state = copy.deepcopy(
            (
                self.journal_sources,
                self.journal_entries,
                self.journal_entry_projects,
                self.journal_entry_tasks,
                self.journal_entry_contacts,
                self.operations,
                self.audit_events,
                self.tasks,
            )
        )
        try:
            return operation(self)
        except Exception:
            (
                self.journal_sources,
                self.journal_entries,
                self.journal_entry_projects,
                self.journal_entry_tasks,
                self.journal_entry_contacts,
                self.operations,
                self.audit_events,
                self.tasks,
            ) = state
            raise

    def read_day_done(self, session: Any, actor: Any, journal_date: Any, zone: Any) -> DayDone:
        del session, actor, journal_date, zone
        return DayDone()

    def save_journal_source(self, session: Any, source: Any) -> None:
        del session
        if source.id in self.journal_sources:
            raise ValidationError("journal source already exists")
        if source.replaces_source_id is not None:
            replaced = self.journal_sources.get(source.replaces_source_id)
            if replaced is None or replaced.owner_id != source.owner_id:
                raise NotFoundError("journal source not found")
        self.journal_sources[source.id] = source

    def get_journal_source(self, session: Any, owner_id: UUID, source_id: UUID) -> Any:
        del session
        source = self.journal_sources.get(source_id)
        if source is None or source.owner_id != owner_id:
            raise NotFoundError("journal source not found")
        return source

    def journal_source_has_live_replacement(
        self, session: Any, owner_id: UUID, source_id: UUID
    ) -> bool:
        del session
        return any(
            source.owner_id == owner_id and source.replaces_source_id == source_id
            for source in self.journal_sources.values()
        )

    def save_journal_entry(self, session: Any, entry: Any) -> None:
        del session
        if any(
            existing.owner_id == entry.owner_id and existing.source_id == entry.source_id
            for existing in self.journal_entries.values()
        ):
            raise ValidationError("journal source already has an entry")
        self.journal_entries[entry.id] = entry

    def add_journal_entry_relations(
        self,
        session: Any,
        *,
        owner_id: UUID,
        entry_id: UUID,
        project_ids: tuple[UUID, ...],
        task_ids: tuple[UUID, ...],
        contact_ids: tuple[UUID, ...],
    ) -> None:
        del session, owner_id
        self.journal_entry_projects.update((entry_id, target_id) for target_id in project_ids)
        self.journal_entry_tasks.update((entry_id, target_id) for target_id in task_ids)
        self.journal_entry_contacts.update((entry_id, target_id) for target_id in contact_ids)

    def list_journal_entries(
        self,
        session: Any,
        owner_id: UUID,
        *,
        start_date: date,
        end_date: date,
        include_archived: bool = False,
        limit: int = 100,
        after: tuple[Any, ...] | None = None,
    ) -> list[Any]:
        del session
        entries = [
            entry
            for entry in self.journal_entries.values()
            if entry.owner_id == owner_id
            and start_date <= entry.journal_date <= end_date
            and (include_archived or entry.archived_at is None)
        ]
        ordered = sorted(entries, key=entry_page_key)
        if after is not None:
            ordered = [entry for entry in ordered if entry_page_key(entry) > after]
        return ordered[:limit]

    def list_active_journal_entry_heads(
        self, session: Any, owner_id: UUID, journal_date: date
    ) -> list[EntryHead]:
        # Same contract as SqlAlchemyStore: all non-archived entries of the day, unpaged, in
        # occurrence order. Domain entries carry no trash flag in this fake.
        del session
        entries = [
            entry
            for entry in self.journal_entries.values()
            if entry.owner_id == owner_id
            and entry.journal_date == journal_date
            and entry.archived_at is None
        ]
        return [
            EntryHead(
                entry.id,
                entry.version,
                entry.occurred_at,
                entry.source_recorded_at,
                entry.created_at,
            )
            for entry in sorted(entries, key=entry_order_key)
        ]

    def get_journal_entry(self, session: Any, owner_id: UUID, entry_id: UUID) -> Any:
        del session
        entry = self.journal_entries.get(entry_id)
        if entry is None or entry.owner_id != owner_id:
            raise NotFoundError("journal entry not found")
        return entry


def _actor() -> Actor:
    return Actor(
        OWNER_ID,
        frozenset(
            {
                "journal:read",
                "journal:write",
                "projects:read",
                "tasks:read",
                "contacts:read",
            }
        ),
    )


def _journal_service(store: ManualJournalStore, clock: MutableClock) -> JournalService:
    return JournalService(store, clock, make_cursor_codec())


def _capture_source(
    service: Any,
    *,
    source_type: SourceType = SourceType.MANUAL_TEXT,
    raw_text: str = JOURNAL_SOURCE_TEXT,
    occurred_at: datetime | None = datetime(2026, 7, 21, 9, tzinfo=UTC),
    source_recorded_at: datetime | None = datetime(2026, 7, 21, 9, 5, tzinfo=UTC),
    replaces_source_id: UUID | None = None,
    key: str = "journal-source-001",
) -> Any:
    return service.create_source(
        _actor(),
        source_type=source_type,
        journal_date=JOURNAL_DATE,
        occurred_at=occurred_at,
        source_recorded_at=source_recorded_at,
        raw_text=raw_text,
        language="sv",
        replaces_source_id=replaces_source_id,
        idempotency_key=key,
    )


def _finalize_manual(
    service: Any,
    source_id: UUID,
    *,
    title: str = "Planering och uppföljning",
    project_ids: tuple[UUID, ...] = (),
    task_ids: tuple[UUID, ...] = (),
    contact_ids: tuple[UUID, ...] = (),
    key: str = "journal-entry-001",
) -> Any:
    return service.create_manual_entry(
        _actor(),
        source_id=source_id,
        title=title,
        summary="Ett beslut fattades och en uppföljning planerades.",
        key_points=(KeyPoint(KeyPointKind.DECISION, "Följ upp på måndag."),),
        project_ids=project_ids,
        task_ids=task_ids,
        contact_ids=contact_ids,
        idempotency_key=key,
    )


def _seed_relation_targets(store: ManualJournalStore, now: datetime) -> dict[str, UUID]:
    inactive_project_id = UUID("01910000-0000-7000-8000-000000000021")
    inactive_task_id = UUID("01910000-0000-7000-8000-000000000022")
    inactive_contact_id = UUID("01910000-0000-7000-8000-000000000023")
    store.projects[JOURNAL_PROJECT_ID] = Project(
        id=JOURNAL_PROJECT_ID,
        owner_id=OWNER_ID,
        domain_id=JOURNAL_DOMAIN_ID,
        title="Planering",
        description=None,
        status=ProjectStatus.ACTIVE,
        start_date=None,
        target_date=None,
        created_at=now,
        updated_at=now,
    )
    store.projects[inactive_project_id] = Project(
        id=inactive_project_id,
        owner_id=OWNER_ID,
        domain_id=JOURNAL_DOMAIN_ID,
        title="Avslutat projekt",
        description=None,
        status=ProjectStatus.COMPLETED,
        start_date=None,
        target_date=None,
        created_at=now,
        updated_at=now,
    )
    store.tasks[JOURNAL_TASK_ID] = Task(
        id=JOURNAL_TASK_ID,
        owner_id=OWNER_ID,
        project_id=None,
        title="Följ upp beslut",
        description=None,
        status=TaskStatus.TODO,
        priority=Priority.NORMAL,
        due_at=None,
        completed_at=None,
        created_at=now,
        updated_at=now,
    )
    store.tasks[inactive_task_id] = Task(
        id=inactive_task_id,
        owner_id=OWNER_ID,
        project_id=None,
        title="Redan klar",
        description=None,
        status=TaskStatus.COMPLETED,
        priority=Priority.NORMAL,
        due_at=None,
        completed_at=now,
        created_at=now,
        updated_at=now,
    )
    store.contacts[JOURNAL_CONTACT_ID] = ContactBuilder().with_id(JOURNAL_CONTACT_ID).build_fake()
    store.contacts[inactive_contact_id] = (
        ContactBuilder().with_id(inactive_contact_id).archived().build_fake()
    )
    return {
        "project": inactive_project_id,
        "task": inactive_task_id,
        "contact": inactive_contact_id,
    }


@pytest.mark.parametrize("source_type", [SourceType.MANUAL_TEXT, SourceType.TRANSCRIPT_TEXT])
def test_capture_preserves_supported_source_text_and_metadata(source_type: SourceType) -> None:
    store = ManualJournalStore()
    service = _journal_service(store, MutableClock())

    source = _capture_source(service, source_type=source_type)

    assert source.owner_id == OWNER_ID
    assert source.source_type is source_type
    assert source.journal_date == JOURNAL_DATE
    assert source.raw_text == JOURNAL_SOURCE_TEXT
    assert source.created_at == CREATED_ON_JULY_24
    assert store.journal_sources[source.id] == source


def test_replacement_is_distinct_and_does_not_repoint_existing_entry() -> None:
    store = ManualJournalStore()
    clock = MutableClock()
    service = _journal_service(store, clock)
    original = _capture_source(service)
    entry = _finalize_manual(service, original.id)
    original_snapshot = copy.deepcopy(original)
    entry_snapshot = copy.deepcopy(entry)
    clock.value += timedelta(days=1)

    replacement = _capture_source(
        service,
        raw_text=JOURNAL_REPLACEMENT_TEXT,
        replaces_source_id=original.id,
        key="journal-source-replacement",
    )

    assert replacement.id != original.id
    assert replacement.replaces_source_id == original.id
    assert replacement.raw_text == JOURNAL_REPLACEMENT_TEXT
    assert store.journal_sources[original.id] == original_snapshot
    assert store.journal_entries[entry.id] == entry_snapshot
    assert entry.source_id == original.id


def test_backdated_entry_uses_historical_day_and_later_creation_time() -> None:
    store = ManualJournalStore()
    service = _journal_service(store, MutableClock())
    source = _capture_source(service)

    entry = _finalize_manual(service, source.id)
    day = service.get_day(_actor(), journal_date=JOURNAL_DATE)

    assert source.journal_date == JOURNAL_DATE
    assert source.created_at.date() == date(2026, 7, 24)
    assert entry.journal_date == JOURNAL_DATE
    assert entry.created_at.date() == date(2026, 7, 24)
    assert [item.id for item in day.entries] == [entry.id]


def test_multiple_same_day_entries_remain_separate_and_deterministically_ordered() -> None:
    store = ManualJournalStore()
    clock = MutableClock()
    service = _journal_service(store, clock)
    source_one = _capture_source(
        service,
        occurred_at=datetime(2026, 7, 21, 11, tzinfo=UTC),
        source_recorded_at=None,
        key="source-occurrence",
    )
    source_two = _capture_source(
        service,
        occurred_at=None,
        source_recorded_at=datetime(2026, 7, 21, 10, tzinfo=UTC),
        key="source-recorded",
    )
    source_three = _capture_source(
        service,
        occurred_at=None,
        source_recorded_at=None,
        key="source-created",
    )
    entries = [
        _finalize_manual(service, source_three.id, title="Tre", key="entry-three"),
        _finalize_manual(service, source_one.id, title="Ett", key="entry-one"),
        _finalize_manual(service, source_two.id, title="Två", key="entry-two"),
    ]

    listed = list(
        service.list_entries(_actor(), start_date=JOURNAL_DATE, end_date=JOURNAL_DATE).items
    )
    day_entries = list(service.get_day(_actor(), journal_date=JOURNAL_DATE).entries)
    expected_ids = [entry.id for entry in sorted(entries, key=entry_order_key)]

    assert len(listed) == 3
    assert len({entry.id for entry in listed}) == 3
    assert [entry.id for entry in listed] == expected_ids
    assert [entry.id for entry in day_entries] == expected_ids


def test_source_has_no_edit_archive_restore_or_delete_lifecycle() -> None:
    store = ManualJournalStore()
    service = _journal_service(store, MutableClock())
    source = _capture_source(service)

    assert service.get_source(_actor(), source.id) == source
    forbidden = {
        "update_source",
        "edit_source",
        "archive_source",
        "restore_source",
        "delete_source",
    }
    assert forbidden.isdisjoint(name for name, _ in inspect.getmembers(service, callable))
    assert not hasattr(source, "archived_at")


def test_manual_finalize_selects_only_active_typed_relations_atomically() -> None:
    store = ManualJournalStore()
    clock = MutableClock()
    inactive_ids = _seed_relation_targets(store, clock.now())
    service = _journal_service(store, clock)
    source = _capture_source(service)

    entry = _finalize_manual(
        service,
        source.id,
        project_ids=(JOURNAL_PROJECT_ID,),
        task_ids=(JOURNAL_TASK_ID,),
        contact_ids=(JOURNAL_CONTACT_ID,),
    )

    assert store.journal_entry_projects == {(entry.id, JOURNAL_PROJECT_ID)}
    assert store.journal_entry_tasks == {(entry.id, JOURNAL_TASK_ID)}
    assert store.journal_entry_contacts == {(entry.id, JOURNAL_CONTACT_ID)}

    for relation_kind, inactive_id in inactive_ids.items():
        invalid_source = _capture_source(
            service,
            key=f"source-inactive-{relation_kind}",
            raw_text=f"Syntetisk källa för inaktiv {relation_kind}.",
        )
        selected = {
            "project_ids": (),
            "task_ids": (),
            "contact_ids": (),
        }
        selected[f"{relation_kind}_ids"] = (inactive_id,)
        before = copy.deepcopy(store.journal_entries)
        with pytest.raises((NotFoundError, ValidationError, ValueError)):
            _finalize_manual(
                service,
                invalid_source.id,
                key=f"entry-inactive-{relation_kind}",
                **selected,
            )
        assert store.journal_entries == before


def test_manual_path_has_zero_task_provider_or_health_dependencies(
    journal_provider_spy: JournalProviderSpy,
) -> None:
    store = ManualJournalStore()
    now = CREATED_ON_JULY_24
    _seed_relation_targets(store, now)
    tasks_before = copy.deepcopy(store.tasks)

    # Construction and use intentionally provide no analysis provider or credentials.
    service = _journal_service(store, MutableClock(now))
    source = _capture_source(service)
    _finalize_manual(service, source.id, task_ids=(JOURNAL_TASK_ID,))
    day = service.get_day(_actor(), journal_date=JOURNAL_DATE)

    assert day.entries
    assert store.tasks == tasks_before
    assert store.processing_runs == []
    assert journal_provider_spy.calls == []
    constructor = inspect.signature(type(service).__init__)
    required_provider_parameters = {
        name
        for name, parameter in constructor.parameters.items()
        if "provider" in name and parameter.default is inspect.Parameter.empty and name != "self"
    }
    assert required_provider_parameters == set()


@pytest.mark.parametrize(
    ("overrides", "key"),
    [
        ({"raw_text": "x" * 100_001}, "oversized-source"),
        ({"occurred_at": datetime(2026, 7, 21, 9)}, "naive-occurrence"),
        ({"source_recorded_at": datetime(2026, 7, 21, 9)}, "naive-recorded"),
    ],
)
def test_invalid_source_is_rejected_atomically(overrides: dict[str, Any], key: str) -> None:
    store = ManualJournalStore()
    service = _journal_service(store, MutableClock())
    before = SimpleNamespace(
        sources=copy.deepcopy(store.journal_sources),
        operations=copy.deepcopy(store.operations),
        audits=copy.deepcopy(store.audit_events),
    )

    with pytest.raises((ValidationError, ValueError)):
        _capture_source(service, key=key, **overrides)

    assert store.journal_sources == before.sources
    assert store.operations == before.operations
    assert store.audit_events == before.audits
