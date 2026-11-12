"""Framework-independent daily Journal summary rules."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from sidekick.shared.errors import InvalidInputError

from .analysis import (
    DailySummaryAnalysis,
    EntryIdList,
    StrictModel,
    SummaryContradiction,
    SummaryStatement,
    SummaryTheme,
)
from .entry import EntryHead, JournalEntry, entry_order_key


class SummaryOrigin(StrEnum):
    MANUAL = "manual"
    AI_ASSISTED = "ai_assisted"


class SummaryState(StrEnum):
    CURRENT = "current"
    STALE = "stale"
    MISSING = "missing"
    FAILED = "failed"


class SummaryContent(StrictModel):
    """Closed structured content shared by manual and AI-assisted summaries."""

    overview: str = Field(min_length=1, max_length=20_000)
    overview_entry_ids: EntryIdList
    themes: list[SummaryTheme] = Field(max_length=50)
    important_events: list[SummaryStatement] = Field(max_length=50)
    decisions: list[SummaryStatement] = Field(max_length=50)
    commitments: list[SummaryStatement] = Field(max_length=50)
    open_questions: list[SummaryStatement] = Field(max_length=50)
    unresolved_items: list[SummaryStatement] = Field(max_length=50)
    contradictions: list[SummaryContradiction] = Field(max_length=25)

    @classmethod
    def from_analysis(cls, analysis: DailySummaryAnalysis) -> SummaryContent:
        return cls.model_validate(analysis.model_dump(exclude={"kind"}))


@dataclass(frozen=True, slots=True)
class DailySummary:
    id: UUID
    owner_id: UUID
    journal_date: date
    origin: SummaryOrigin
    state: SummaryState
    content: SummaryContent
    entry_ids: tuple[UUID, ...]
    source_fingerprint: str
    version: int
    changed_entry_count: int


@dataclass(frozen=True, slots=True)
class SummaryProposal:
    id: UUID
    owner_id: UUID
    journal_date: date
    state: str
    entry_fingerprint: str
    content: SummaryContent
    version: int

    def accept(self) -> SummaryProposal:
        if self.state != "pending_review":
            raise InvalidInputError("summary proposal is no longer pending review")
        return replace(self, state="accepted", version=self.version + 1)

    def reject(self) -> SummaryProposal:
        if self.state != "pending_review":
            raise InvalidInputError("summary proposal is no longer pending review")
        return replace(self, state="rejected", version=self.version + 1)


def active_entries(
    entries: Iterable[JournalEntry | EntryHead],
) -> tuple[JournalEntry | EntryHead, ...]:
    """Return active entries in the authoritative deterministic timeline order."""

    return tuple(
        sorted((entry for entry in entries if entry.archived_at is None), key=entry_order_key)
    )


def entry_fingerprint(entries: Iterable[JournalEntry | EntryHead]) -> str:
    """Fingerprint the ordered active entry ID/version map, not mutable content."""

    values = [{"id": str(entry.id), "version": entry.version} for entry in active_entries(entries)]
    encoded = json.dumps(values, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def changed_entry_count(
    stored_version_by_entry_id: Mapping[UUID, int],
    current_version_by_entry_id: Mapping[UUID, int],
) -> int:
    """Count each added, removed, or version-changed entry exactly once."""

    ids = set(stored_version_by_entry_id) | set(current_version_by_entry_id)
    return sum(
        stored_version_by_entry_id.get(entry_id) != current_version_by_entry_id.get(entry_id)
        for entry_id in ids
    )


def validate_content_references(content: SummaryContent, entry_ids: set[UUID]) -> None:
    """Require every structured reference to point to an active source entry."""

    references: list[UUID] = list(content.overview_entry_ids)
    for section in (
        content.themes,
        content.important_events,
        content.decisions,
        content.commitments,
        content.open_questions,
        content.unresolved_items,
        content.contradictions,
    ):
        references.extend(entry_id for item in section for entry_id in item.entry_ids)
    if any(entry_id not in entry_ids for entry_id in references):
        raise InvalidInputError("summary references an entry outside the active day")
