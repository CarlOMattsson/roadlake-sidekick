"""Property 2: manual Journal paths stay independent from AI and Tasks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from hypothesis import given
from hypothesis import strategies as st

from sidekick.journal.domain.day_done import DayDone
from sidekick.journal.domain.entry import EntryHead, JournalEntry, KeyPoint, KeyPointKind
from sidekick.journal.domain.source import JournalSource, SourceType
from sidekick.journal.domain.summary import (
    DailySummary,
    SummaryContent,
    SummaryOrigin,
    SummaryState,
    entry_fingerprint,
)
from sidekick.shared.types import Actor
from tests.support.fakes import make_cursor_codec
from tests.support.journal_services import ManualJournal

OWNER = UUID("018af000-0000-7000-8000-000000000001")
SOURCE_ID = UUID("01910000-0000-7000-8000-000000000001")
ENTRY_ID = UUID("01910000-0000-7000-8000-000000000003")


@dataclass(frozen=True, slots=True)
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


class ManualOnlyStore:
    """Small transport-neutral store double with an explicit no-run ledger."""

    def __init__(self) -> None:
        self.source: JournalSource | None = None
        self.entry: JournalEntry | None = None
        self.summary: DailySummary | None = None
        self.operations: dict[tuple[UUID, str, str], dict[str, Any]] = {}
        self.processing_runs: list[object] = []
        self.task_state = {"title": "Oförändrad uppgift", "version": 4}
        self.stale_marks = 0
        self.provider_calls = 0

    def transaction(self, operation: Any) -> Any:
        return operation(self)

    def read_day_done(self, session: Any, actor: Any, journal_date: Any, zone: Any) -> DayDone:
        del session, actor, journal_date, zone
        return DayDone()

    def idempotent(
        self,
        session: Any,
        *,
        actor_id: UUID,
        operation: str,
        key: str,
        payload: dict[str, Any],
        execute: Any,
    ) -> dict[str, Any]:
        del session, payload
        identity = (actor_id, operation, key)
        if identity not in self.operations:
            self.operations[identity] = execute()
        return self.operations[identity]

    def append_audit(self, session: Any, **kwargs: Any) -> None:
        del session, kwargs

    def save_journal_source(self, session: Any, source: JournalSource) -> None:
        del session
        self.source = source

    def get_journal_source(self, session: Any, owner_id: UUID, source_id: UUID) -> JournalSource:
        del session
        assert self.source is not None
        assert self.source.owner_id == owner_id and self.source.id == source_id
        return self.source

    def save_journal_entry(self, session: Any, entry: JournalEntry) -> None:
        del session
        self.entry = entry

    def get_journal_entry(self, session: Any, owner_id: UUID, entry_id: UUID) -> JournalEntry:
        del session
        assert self.entry is not None
        assert self.entry.owner_id == owner_id and self.entry.id == entry_id
        return self.entry

    def journal_source_has_live_replacement(
        self, session: Any, owner_id: UUID, source_id: UUID
    ) -> bool:
        del session, owner_id, source_id
        return False

    def add_journal_entry_relations(self, session: Any, **kwargs: Any) -> None:
        del session, kwargs

    def update_journal_entry(
        self,
        session: Any,
        *,
        owner_id: UUID,
        entry: JournalEntry,
        expected_version: int,
    ) -> JournalEntry:
        del session
        assert self.entry is not None
        assert self.entry.owner_id == owner_id and self.entry.version == expected_version
        self.entry = entry
        return entry

    def mark_daily_journal_summary_stale(
        self, session: Any, owner_id: UUID, journal_date: date
    ) -> None:
        del session, owner_id, journal_date
        self.stale_marks += 1

    def list_active_journal_entry_heads(
        self, session: Any, owner_id: UUID, journal_date: date
    ) -> list[EntryHead]:
        del session
        if (
            self.entry
            and self.entry.owner_id == owner_id
            and self.entry.journal_date == journal_date
        ):
            entry = self.entry
            return [
                EntryHead(
                    entry.id,
                    entry.version,
                    entry.occurred_at,
                    entry.source_recorded_at,
                    entry.created_at,
                )
            ]
        return []

    def get_daily_summary(
        self, session: Any, owner_id: UUID, summary_or_date: UUID | date
    ) -> DailySummary | None:
        del session, owner_id, summary_or_date
        return self.summary

    def upsert_manual_daily_summary(
        self,
        session: Any,
        *,
        owner_id: UUID,
        journal_date: date,
        content: SummaryContent,
        expected_entry_fingerprint: str,
        expected_summary_version: int | None,
        now: datetime,
        correlation_id: str | None = None,
    ) -> DailySummary:
        del session, expected_summary_version, correlation_id
        entries = self.list_active_journal_entry_heads(None, owner_id, journal_date)
        assert entry_fingerprint(entries) == expected_entry_fingerprint
        self.summary = DailySummary(
            id=UUID("01910000-0000-7000-8000-000000000005"),
            owner_id=owner_id,
            journal_date=journal_date,
            origin=SummaryOrigin.MANUAL,
            state=SummaryState.CURRENT,
            content=content,
            entry_ids=tuple(entry.id for entry in entries),
            source_fingerprint=expected_entry_fingerprint,
            version=(self.summary.version + 1 if self.summary else 1),
            changed_entry_count=0,
        )
        del now
        return self.summary


class NeverCalledProvider:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"manual path accessed provider member {name}")


def actor() -> Actor:
    return Actor(
        user_id=OWNER,
        scopes=frozenset({"journal:read", "journal:write"}),
    )


def make_service(store: ManualOnlyStore) -> ManualJournal:
    return ManualJournal.build(
        store,
        FixedClock(datetime(2026, 7, 24, 8, 0, tzinfo=UTC)),
        make_cursor_codec(),
    )


def content(overview: str) -> SummaryContent:
    return SummaryContent(
        overview=overview,
        overview_entry_ids=[ENTRY_ID],
        themes=[],
        important_events=[],
        decisions=[],
        commitments=[],
        open_questions=[],
        unresolved_items=[],
        contradictions=[],
    )


@given(st.sampled_from(("Första manuella sammanfattningen.", "Ett beslut följdes upp.")))
def test_manual_source_and_entry_never_create_runs_or_change_task_state(overview: str) -> None:
    store = ManualOnlyStore()
    service = make_service(store)
    before_task = dict(store.task_state)

    source = service.capture.create_source(
        actor(),
        source_type=SourceType.MANUAL_TEXT,
        journal_date=date(2026, 7, 21),
        occurred_at=datetime(2026, 7, 21, 9, 0, tzinfo=UTC),
        source_recorded_at=datetime(2026, 7, 24, 8, 0, tzinfo=UTC),
        raw_text="En syntetisk manuell källa.",
        language="sv",
        replaces_source_id=None,
        idempotency_key="manual-source-property",
    )
    entry = service.capture.create_manual_entry(
        actor(),
        source_id=source.id,
        title="Manuell post",
        summary="Ett manuellt beslut.",
        key_points=(KeyPoint(KeyPointKind.DECISION, "Följ upp beslutet."),),
        idempotency_key="manual-entry-property",
    )
    summary = service.day.put_manual_summary(
        actor(),
        journal_date=entry.journal_date,
        expected_entry_fingerprint=entry_fingerprint([entry]),
        expected_summary_version=None,
        content=content(overview),
        idempotency_key="manual-summary-property",
    )

    assert summary.origin is SummaryOrigin.MANUAL
    assert store.processing_runs == []
    assert store.task_state == before_task
    assert store.provider_calls == 0
    assert store.stale_marks == 1
    assert isinstance(NeverCalledProvider(), NeverCalledProvider)
