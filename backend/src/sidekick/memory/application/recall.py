"""Verified recall: provider facts released only when Postgres confirms their source.

Invariant (the memory design's verified-recall rule): no fact is returned unless
its document maps to a `memory_sources` row of this owner that is not excluded, its source record
still exists in Postgres and is not trashed, the fact is of an allowed type (not an observation),
the fact still stems from the current version of its source, the owner's memory settings switch
the kind on, and the actor holds the read scope of that kind. The provider is not trusted for any
of this. A journal entry counts as live only when its source is live and no live source replaces
it, the same rule that `queries.py` applies.

Source version. A document is replaced when its source changes, but only after a quiet period and a
retain round trip. Until then the provider still holds facts of the older version. A fact is
therefore released only while the source has not changed since the last successful retain: for a
`retained` row since the version it describes (`memory_sources.source_updated_at`), for any other
status (a pipeline-version bump, a retry, a parked row all reset a row to `pending` without the
content changing) since `retained_at`. A row that was never retained, a source changed after the
last retain and a removal marker are dropped as `stale_version`; a changed source returns once the
replacement is retained.

Statuses: `ok` (facts), `empty` (nothing verified), `unavailable` (provider down or refusing),
`disabled` (no settings row, or every domain switched off), `paused` (owner paused memory).

Privacy of logs. The query and fact text never reach a log record or the result of a failure.
Logs carry the owner id, the status, counts per drop reason and fixed provider failure categories.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from sidekick.memory.application.records import MemorySettingsRecord
from sidekick.memory.application.store import LiveSource, MemoryStore
from sidekick.memory.application.sync_rules import RETAINED
from sidekick.memory.domain import MemoryKind
from sidekick.memory.ports import (
    ALLOWED_FACT_TYPES,
    MemoryFact,
    MemoryProvider,
    MemoryProviderError,
)
from sidekick.shared.errors import InvalidInputError
from sidekick.shared.types import TxSession, paginate, validate_limit

LOGGER = logging.getLogger("sidekick.memory.recall")

RecallStatus = Literal["ok", "empty", "unavailable", "disabled", "paused"]

MIN_QUERY_LENGTH = 2
MAX_QUERY_LENGTH = 300
MIN_LIMIT = 1
MAX_LIMIT = 20
#: Token budget asked of the provider per recall. Facts beyond `limit` drop after verification.
RECALL_TOKEN_BUDGET = 2_048

#: Read scope per kind. Mirrors the search gate in `sidekick/search/domain.py` (`KIND_SCOPE`).
KIND_READ_SCOPE: dict[MemoryKind, str] = {
    MemoryKind.JOURNAL_ENTRY: "journal:read",
    MemoryKind.CONTACT: "contacts:read",
    MemoryKind.PROJECT: "projects:read",
    MemoryKind.TASK: "tasks:read",
}


@dataclass(frozen=True, slots=True)
class _MemoryRow:
    """What recall needs of a `memory_sources` row."""

    kind: MemoryKind
    source_id: UUID
    retained: bool
    source_updated_at: datetime
    retained_at: datetime | None
    removed_marker: bool


@dataclass(frozen=True, slots=True)
class RecalledFact:
    """A verified fact with the source it was derived from. Dates are the provider's ISO strings."""

    text: str
    source_kind: MemoryKind
    source_id: UUID
    archived: bool
    occurred_start: str | None
    occurred_end: str | None


@dataclass(frozen=True, slots=True)
class CitedSource:
    """Title and date of a record a fact cites. Read from Postgres, never from the provider."""

    title: str | None
    day: date | None


@dataclass(frozen=True, slots=True)
class RecallResult:
    status: RecallStatus
    facts: tuple[RecalledFact, ...] = ()
    truncated: bool = False


def source_details(
    store: MemoryStore, session: TxSession, owner_id: UUID, facts: Sequence[RecalledFact]
) -> dict[tuple[MemoryKind, UUID], CitedSource]:
    """Title and date per cited record. One batched query per kind, never one per fact."""

    ids_by_kind: dict[MemoryKind, set[UUID]] = {}
    for fact in facts:
        ids_by_kind.setdefault(fact.source_kind, set()).add(fact.source_id)
    details: dict[tuple[MemoryKind, UUID], CitedSource] = {}
    for kind, ids in ids_by_kind.items():
        for cited in store.cited_records(session, owner_id, kind, sorted(ids)):
            details[(kind, cited.record_id)] = CitedSource(title=cited.title, day=cited.day)
    return details


def recall_verified(
    store: MemoryStore,
    session: TxSession,
    provider: MemoryProvider,
    *,
    owner_id: UUID,
    query: str,
    limit: int,
    scopes: Iterable[str],
    correlation_id: str | None = None,
) -> RecallResult:
    """Recall facts for one owner and return only those verified against Postgres.

    Raises InvalidInputError for an out-of-bounds query or limit. Provider failures never raise: any
    exception from the provider returns status `unavailable`. Read-only. It ends its read
    transaction before the provider call, so no database transaction is open during network I/O;
    the verification after the call runs in a fresh transaction. The caller's session may be reused.
    """

    validate_limit(
        limit,
        minimum=MIN_LIMIT,
        maximum=MAX_LIMIT,
        message=f"recall limit must be between {MIN_LIMIT} and {MAX_LIMIT}",
    )
    text = query.strip()
    if not MIN_QUERY_LENGTH <= len(text) <= MAX_QUERY_LENGTH:
        raise InvalidInputError("recall query length is out of bounds")

    # The policy is read into plain values; the read transaction ends before any network call.
    blocked, switched_on = _read_policy(store, session, owner_id)
    if blocked is not None:
        return _finish(owner_id, correlation_id, RecallResult(status=blocked))

    granted = frozenset(scopes)
    if not _readable(switched_on, granted):
        return _finish(owner_id, correlation_id, RecallResult(status="empty"))

    try:
        provider_facts = provider.recall(
            owner_id=owner_id, query=text, max_tokens=RECALL_TOKEN_BUDGET
        )
    except Exception as error:
        # Never log the message: it may echo the query or fact text. The fixed category of a
        # MemoryProviderError is safe to log; any other exception only by its type name.
        LOGGER.warning(
            "memory_recall_unavailable",
            extra={
                "correlation_id": correlation_id,
                "error_type": type(error).__name__,
                "category": error.category if isinstance(error, MemoryProviderError) else None,
            },
        )
        return RecallResult(status="unavailable")

    # The call may have been slow. The owner can have paused or switched memory off, narrowed the
    # kinds or deleted a source meanwhile, so the policy is read again and decides what may leave;
    # the memory rows and live sources below are likewise read after the call.
    blocked, switched_on = _read_policy(store, session, owner_id)
    if blocked is not None:
        _log_counts(
            owner_id, correlation_id, RecallResult(status=blocked), len(provider_facts), Counter()
        )
        return RecallResult(status=blocked)
    readable = _readable(switched_on, granted)
    rows = _memory_rows(store, session, owner_id, {fact.document_id for fact in provider_facts})
    wanted: dict[MemoryKind, set[UUID]] = {}
    for memory_row in rows.values():
        if memory_row.kind in readable:
            wanted.setdefault(memory_row.kind, set()).add(memory_row.source_id)
    live: dict[MemoryKind, dict[UUID, LiveSource]] = {
        kind: store.live_sources(session, owner_id, kind, ids) for kind, ids in wanted.items()
    }

    dropped: Counter[str] = Counter()
    verified: list[RecalledFact] = []
    for fact in provider_facts:
        if fact.fact_type is not None and fact.fact_type not in ALLOWED_FACT_TYPES:
            dropped["fact_type"] += 1
            continue
        row = rows.get(fact.document_id)
        if row is None:
            dropped["unverified"] += 1
            continue
        kind, source_id = row.kind, row.source_id
        if kind not in readable:
            dropped["not_readable"] += 1
            continue
        source = live[kind].get(source_id)
        if source is None:
            dropped["source_not_live"] += 1
            continue
        if not _current(row, source):
            dropped["stale_version"] += 1
            continue
        verified.append(_recalled(fact, kind, source_id, source.archived))

    served, more = paginate(verified, limit, lambda _: True)
    result = RecallResult(
        status="ok" if served else "empty",
        facts=tuple(served),
        truncated=bool(more),
    )
    _log_counts(owner_id, correlation_id, result, len(provider_facts), dropped)
    return result


def _read_policy(
    store: MemoryStore, session: TxSession, owner_id: UUID
) -> tuple[RecallStatus | None, frozenset[MemoryKind]]:
    """The owner's current policy: a blocking status (or None) and the kinds switched on.

    Always reads the database, never the session's identity map, and ends the read transaction.
    """

    settings = store.settings(session, owner_id, fresh=True)
    if settings is None:
        blocked: RecallStatus | None = "disabled"
        switched_on: frozenset[MemoryKind] = frozenset()
    else:
        switched_on = _switched_on(settings)
        blocked = "paused" if settings.paused else None if switched_on else "disabled"
    session.rollback()
    return blocked, switched_on


def _readable(switched_on: frozenset[MemoryKind], granted: frozenset[str]) -> frozenset[MemoryKind]:
    return frozenset(kind for kind in switched_on if KIND_READ_SCOPE[kind] in granted)


def _switched_on(settings: MemorySettingsRecord) -> frozenset[MemoryKind]:
    flags = {
        MemoryKind.JOURNAL_ENTRY: settings.journal,
        MemoryKind.CONTACT: settings.contacts,
        MemoryKind.PROJECT: settings.projects,
        MemoryKind.TASK: settings.tasks,
    }
    return frozenset(kind for kind, on in flags.items() if on)


def _memory_rows(
    store: MemoryStore, session: TxSession, owner_id: UUID, doc_keys: set[str]
) -> dict[str, _MemoryRow]:
    """Owner's non-excluded memory rows for these documents. Other owners' rows never match."""

    if not doc_keys:
        return {}
    return {
        ref.doc_key: _MemoryRow(
            MemoryKind(ref.source_kind),
            ref.source_id,
            ref.status == RETAINED,
            ref.source_updated_at,
            ref.retained_at,
            ref.removed_marker,
        )
        for ref in store.sources_for_documents(session, owner_id, doc_keys)
    }


def _current(row: _MemoryRow, source: LiveSource) -> bool:
    """True when the provider's document still describes the live source.

    A `retained` row says so itself. Any other row (re-queued for a new pipeline version, waiting
    for a retry or parked) still has the last retained document in the bank, which is current
    until the source changes after that retain.
    """

    if row.removed_marker:
        return False
    if row.retained:
        return source.updated_at <= row.source_updated_at
    return row.retained_at is not None and source.updated_at <= row.retained_at


def _recalled(fact: MemoryFact, kind: MemoryKind, source_id: UUID, archived: bool) -> RecalledFact:
    return RecalledFact(
        text=fact.text,
        source_kind=kind,
        source_id=source_id,
        archived=archived,
        occurred_start=fact.occurred_start,
        occurred_end=fact.occurred_end,
    )


def _finish(owner_id: UUID, correlation_id: str | None, result: RecallResult) -> RecallResult:
    LOGGER.info(
        "memory_recall",
        extra={
            "correlation_id": correlation_id,
            "outcome": result.status,
            "returned": len(result.facts),
        },
    )
    return result


def _log_counts(
    owner_id: UUID,
    correlation_id: str | None,
    result: RecallResult,
    provider_count: int,
    dropped: Counter[str],
) -> None:
    LOGGER.info(
        "memory_recall",
        extra={
            "correlation_id": correlation_id,
            "outcome": result.status,
            "provider_facts": provider_count,
            "returned": len(result.facts),
            "truncated": result.truncated,
            "dropped_unverified": dropped["unverified"],
            "dropped_not_readable": dropped["not_readable"],
            "dropped_source_not_live": dropped["source_not_live"],
            "dropped_stale_version": dropped["stale_version"],
            "dropped_fact_type": dropped["fact_type"],
        },
    )
