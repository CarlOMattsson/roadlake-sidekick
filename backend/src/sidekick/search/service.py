"""Search use case shared by every transport. MCP is its only transport so far; no HTTP
route calls it yet.

Scopes are checked per kind before any query runs. Logs, spans and metrics carry the operation
name, the kinds, hit counts and query length only: never the query text, its terms, a cursor or
any hit text.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from typing import Final, Protocol
from uuid import UUID

from sidekick.contacts.domain.contact import Contact
from sidekick.search.domain import KIND_SCOPE, Kind, SearchQuery, parse_query, resolve_kinds
from sidekick.search.persistence import (
    CLOSEST_LIMIT,
    TITLE_LIMIT,
    ContactHit,
    JournalHit,
    ProjectHit,
    TaskHit,
)
from sidekick.search.schemas import (
    ContactHitRecord,
    ContactSearchPage,
    JournalHitRecord,
    JournalSearchPage,
    ProjectHitRecord,
    ProjectSearchPage,
    SearchResult,
    TaskHitRecord,
    TaskSearchPage,
)
from sidekick.shared.errors import ValidationError
from sidekick.shared.observability import TelemetryPort
from sidekick.shared.types import (
    MAX_CURSOR_LENGTH,
    Actor,
    CursorCodec,
    TransactionalStore,
    TxSession,
)

LOGGER = logging.getLogger("sidekick.search")

MIN_QUERY_LENGTH: Final = 2
MAX_QUERY_LENGTH: Final = 100
MIN_LIMIT: Final = 1
MAX_LIMIT: Final = 25


def _query_key(kind: Kind, query: SearchQuery) -> str:
    # CursorCodec hashes this key, so the terms never appear in the cursor token itself.
    return f"search:v1:kind={kind.value}:terms={' '.join(query.terms)}"


def _hit_counts(result: SearchResult) -> dict[str, int]:
    counts: dict[str, int] = {}
    if result.tasks is not None:
        counts[Kind.TASK.value] = len(result.tasks.hits)
    if result.projects is not None:
        counts[Kind.PROJECT.value] = len(result.projects.hits)
    if result.contacts is not None:
        counts[Kind.CONTACT.value] = len(result.contacts.hits)
    if result.journal is not None:
        counts[Kind.JOURNAL.value] = len(result.journal.hits)
    return counts


class SearchReader(TransactionalStore, Protocol):
    """The owner-filtered reads search needs; each returns at most `limit` hits."""

    def search_tasks(
        self, session: TxSession, owner_id: UUID, terms: Sequence[str], *, limit: int, offset: int
    ) -> list[TaskHit]: ...
    def search_projects(
        self, session: TxSession, owner_id: UUID, terms: Sequence[str], *, limit: int, offset: int
    ) -> list[ProjectHit]: ...
    def search_contacts(
        self, session: TxSession, owner_id: UUID, terms: Sequence[str], *, limit: int, offset: int
    ) -> list[ContactHit]: ...
    def search_journal(
        self, session: TxSession, owner_id: UUID, terms: Sequence[str], *, limit: int, offset: int
    ) -> list[JournalHit]: ...
    def closest_contacts(
        self, session: TxSession, owner_id: UUID, terms: Sequence[str], *, limit: int
    ) -> list[ContactHit]: ...
    def phonetic_contacts(
        self, session: TxSession, owner_id: UUID, query: str, *, limit: int
    ) -> list[Contact]: ...


class SearchService:
    def __init__(
        self, store: SearchReader, cursor_codec: CursorCodec, telemetry: TelemetryPort
    ) -> None:
        self.store = store
        self.cursor_codec = cursor_codec
        self.telemetry = telemetry

    def search(
        self,
        actor: Actor,
        query: str,
        kinds: Sequence[str] | None = None,
        limit: int = 10,
        cursor: str | None = None,
        correlation_id: str | None = None,
    ) -> SearchResult:
        attributes = {"search.operation": "search"}
        started = time.perf_counter()
        try:
            with self.telemetry.span("search.operation", attributes):
                result, parsed = self._search(actor, query, kinds, limit, cursor)
        except Exception:
            self.telemetry.count("sidekick.search.operations", {**attributes, "outcome": "failure"})
            raise
        self.telemetry.count("sidekick.search.operations", {**attributes, "outcome": "success"})
        LOGGER.info(
            "search_completed",
            extra={
                "correlation_id": correlation_id,
                "operation": "search",
                "outcome": "success",
                "kinds": [kind.value for kind in result.searched],
                "hit_counts": _hit_counts(result),
                "query_length": parsed.length,
                "term_count": parsed.term_count,
                "duration_ms": round((time.perf_counter() - started) * 1000),
            },
        )
        return result

    def closest_contacts(
        self, actor: Actor, query: str, limit: int = CLOSEST_LIMIT
    ) -> list[ContactHitRecord]:
        """Contacts whose name or alias is close to a misheard `query` ("Elijas" for "Elias").

        Used only after the normal search found nothing. A query with no term of 3 or more
        characters, or one that cannot be parsed, returns an empty list rather than an error.
        """
        actor.require(KIND_SCOPE[Kind.CONTACT])
        try:
            parsed = parse_query(query[:MAX_QUERY_LENGTH])
        except ValueError:
            return []
        rows = self.store.transaction(
            lambda session: self.store.closest_contacts(
                session, actor.user_id, parsed.terms, limit=min(limit, CLOSEST_LIMIT)
            )
        )
        LOGGER.info(
            "search_closest_contacts",
            extra={"operation": "closest_contacts", "hit_counts": {"contact": len(rows)}},
        )
        return [
            ContactHitRecord(id=row.id, display_name=row.display_name, version=row.version)
            for row in rows
        ]

    def _search(
        self,
        actor: Actor,
        query: str,
        kinds: Sequence[str] | None,
        limit: int,
        cursor: str | None,
    ) -> tuple[SearchResult, SearchQuery]:
        selected = resolve_kinds(kinds, actor.scopes)
        for kind in selected:
            actor.require(KIND_SCOPE[kind])
        if not MIN_LIMIT <= limit <= MAX_LIMIT:
            raise ValidationError("limit must be between 1 and 25")
        if not MIN_QUERY_LENGTH <= len(query) <= MAX_QUERY_LENGTH:
            raise ValidationError("search query must be 2-100 characters")
        try:
            parsed = parse_query(query)
        except ValueError as error:
            raise ValidationError(
                "search query needs at least one term of 2 or more letters or digits"
            ) from error

        offset = 0
        if cursor is not None:
            if len(selected) != 1:
                raise ValidationError("a cursor needs exactly one search kind")
            if len(cursor) > MAX_CURSOR_LENGTH:
                raise ValidationError("invalid pagination cursor")
            offset = self._decode_cursor(actor.user_id, cursor, _query_key(selected[0], parsed))

        result = self.store.transaction(
            lambda session: self._read(session, actor.user_id, parsed, selected, limit, offset)
        )
        return result, parsed

    def _decode_cursor(self, actor_id: UUID, cursor: str, query_key: str) -> int:
        try:
            return self.cursor_codec.decode(actor_id, cursor, query_key)
        except ValueError as error:
            raise ValidationError("invalid pagination cursor") from error

    def _read(
        self,
        session: TxSession,
        actor_id: UUID,
        query: SearchQuery,
        kinds: tuple[Kind, ...],
        limit: int,
        offset: int,
    ) -> SearchResult:
        tasks = self._tasks(session, actor_id, query, limit, offset) if Kind.TASK in kinds else None
        projects = (
            self._projects(session, actor_id, query, limit, offset)
            if Kind.PROJECT in kinds
            else None
        )
        contacts = (
            self._contacts(session, actor_id, query, limit, offset)
            if Kind.CONTACT in kinds
            else None
        )
        journal = (
            self._journal(session, actor_id, query, limit, offset)
            if Kind.JOURNAL in kinds
            else None
        )
        return SearchResult(
            searched=list(kinds),
            tasks=tasks,
            projects=projects,
            contacts=contacts,
            journal=journal,
        )

    def _tasks(
        self, session: TxSession, actor_id: UUID, query: SearchQuery, limit: int, offset: int
    ) -> TaskSearchPage:
        rows = self.store.search_tasks(
            session, actor_id, query.terms, limit=limit + 1, offset=offset
        )
        return TaskSearchPage(
            hits=[
                TaskHitRecord(id=row.id, title=row.title, status=row.status, version=row.version)
                for row in rows[:limit]
            ],
            next_cursor=self._next_cursor(actor_id, Kind.TASK, query, limit, offset, len(rows)),
        )

    def _projects(
        self, session: TxSession, actor_id: UUID, query: SearchQuery, limit: int, offset: int
    ) -> ProjectSearchPage:
        rows = self.store.search_projects(
            session, actor_id, query.terms, limit=limit + 1, offset=offset
        )
        return ProjectSearchPage(
            hits=[
                ProjectHitRecord(id=row.id, title=row.title, status=row.status, version=row.version)
                for row in rows[:limit]
            ],
            next_cursor=self._next_cursor(actor_id, Kind.PROJECT, query, limit, offset, len(rows)),
        )

    def _contacts(
        self, session: TxSession, actor_id: UUID, query: SearchQuery, limit: int, offset: int
    ) -> ContactSearchPage:
        rows = self.store.search_contacts(
            session, actor_id, query.terms, limit=limit + 1, offset=offset
        )
        if not rows and offset == 0:
            # A misheard name finds nothing by text or typo tolerance: one bounded phonetic page
            # (Swedish key, see sidekick.contacts.domain.phonetic), without a cursor.
            phonetic = self.store.phonetic_contacts(
                session, actor_id, " ".join(query.terms), limit=limit
            )
            return ContactSearchPage(
                hits=[
                    ContactHitRecord(
                        id=contact.id,
                        display_name=contact.display_name[:TITLE_LIMIT],
                        version=contact.version,
                    )
                    for contact in phonetic
                ],
                next_cursor=None,
            )
        return ContactSearchPage(
            hits=[
                ContactHitRecord(id=row.id, display_name=row.display_name, version=row.version)
                for row in rows[:limit]
            ],
            next_cursor=self._next_cursor(actor_id, Kind.CONTACT, query, limit, offset, len(rows)),
        )

    def _journal(
        self, session: TxSession, actor_id: UUID, query: SearchQuery, limit: int, offset: int
    ) -> JournalSearchPage:
        rows = self.store.search_journal(
            session, actor_id, query.terms, limit=limit + 1, offset=offset
        )
        return JournalSearchPage(
            hits=[
                JournalHitRecord(
                    id=row.id,
                    id_type=row.id_type,
                    journal_date=row.journal_date,
                    matched_in=row.matched_in,
                    title=row.title,
                )
                for row in rows[:limit]
            ],
            next_cursor=self._next_cursor(actor_id, Kind.JOURNAL, query, limit, offset, len(rows)),
        )

    def _next_cursor(
        self,
        actor_id: UUID,
        kind: Kind,
        query: SearchQuery,
        limit: int,
        offset: int,
        fetched: int,
    ) -> str | None:
        if fetched <= limit:
            return None
        return self.cursor_codec.encode(actor_id, offset + limit, _query_key(kind, query))
