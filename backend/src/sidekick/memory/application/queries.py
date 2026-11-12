"""Derived-memory candidate and tombstone queries. Read-only, owner-scoped, keyset-paged.

`MemoryStore.candidate_page` and `MemoryStore.tombstone_page` read one owner's rows of one memory
kind, one page at a time, and map them into the pure inputs of `sidekick.memory.domain`; the SQL is
in `sidekick.memory.infrastructure.candidates`. Nothing there writes, calls a provider or decides
the sync state; the pass in `application/sync.py` does that. This module holds the page types and
the page-size bounds, and documents the rules.

Rules applied in SQL:
- A trashed record is hidden: it is not a candidate. A journal entry is also hidden when its source
  is trashed or is replaced by a live source, the same live-source rule that search uses.
- A trashed record is NOT a tombstone: its document stays in the bank and is only
  hidden at recall time, so a restore costs nothing. A record that is permanently gone, replaced by
  a live source, excluded or switched off is a tombstone.
- An archived record stays a candidate. `MemoryCandidate.archived` marks it for recall.
- A kind whose `memory_settings` flag is off has no candidates. Every memory row of that kind is
  a tombstone.
- A `memory_sources` row with `excluded = true` is not a candidate and is a tombstone.
- Trashed contacts and trashed projects are left out of linked names.

Journal candidates come from `journal_entries` only. Drafts live in `journal_drafts` and are never
read here. Candidate pages return every live record of an enabled kind, including records that the
domain rule rejects, with `is_candidate` False. The pass then deletes the document of a record that
no longer qualifies. Pages are keyset on the id and capped at `MAX_PAGE_SIZE`.

Owner time zone: `completed_on` is the owner's calendar day of the completion instant, counted in
the zone from `SIDEKICK_OWNER_TIMEZONE` (`Settings.owner_zone`), the same zone Work uses for
"today".
The caller passes it to `candidate_page`.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sidekick.memory.domain import MemoryKind, MemoryRecord

DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 200


@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    """One live record of an enabled kind. `record` is the input `canonical_document` reads."""

    kind: MemoryKind
    source_id: UUID
    source_updated_at: datetime
    archived: bool
    is_candidate: bool
    record: MemoryRecord


@dataclass(frozen=True, slots=True)
class MemoryTombstone:
    """A memory row whose record is gone, hidden, excluded or switched off. Its document must go."""

    memory_source_id: UUID
    kind: MemoryKind
    source_id: UUID
    doc_key: str
