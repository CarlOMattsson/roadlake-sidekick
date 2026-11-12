"""Ranked full-text and trigram lookups, one function per searchable kind.

Every query is owner-scoped, excludes trashed records and archived records, and returns only the
columns the search tool may expose. Journal hits carry ids, dates and the entry title (null for a
source without an entry), never entry summary, raw source text or excerpts. Search terms arrive
already sanitized (letters and digits, at least two characters); they are bound as parameters and
never concatenated into SQL.

Indexes: the 0.1.0 baseline defines `search_vector` (GIN) and the trigram indexes on titles/names.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    String,
    and_,
    case,
    cast,
    func,
    literal_column,
    null,
    or_,
    select,
    union_all,
)
from sqlalchemy.orm import Session, aliased

from sidekick.shared.persistence.models import (
    ContactAliasRow,
    ContactRow,
    JournalEntryRow,
    JournalSourceRow,
    ProjectRow,
    TaskRow,
)
from sidekick.shared.persistence.stores.task_parents import task_parents_live
from sidekick.store import SqlAlchemyStore

TITLE_LIMIT = 120
"""Titles and names are clipped to this length, the same bound as the list tools."""

CLOSEST_LIMIT = 3
"""A misheard-name suggestion lists at most this many Contacts."""

CLOSEST_MIN_TERM_LENGTH = 3
"""Shorter terms never reach the word-level trigram comparison (no false hit for 1-2 letters)."""

CLOSEST_SPELLING_MAX_TERM_LENGTH = 6
"""Terms up to this length may also match a whole name word by spelling, not only by trigrams."""

CLOSEST_SPELLING_SCORE = 0.5
"""Ranking score of a spelling match. A stronger trigram match still ranks above it."""


def _closest_threshold(term: str) -> float:
    """Minimum word similarity for a term. Short terms need a closer match than long ones."""

    return 0.5 if len(term) <= 4 else 0.4


def _spelling_max_edits(term: str) -> int:
    """Edits allowed for a spelling match: one for 3-4 letters, two for 5-6 letters."""

    return 1 if len(term) <= 4 else 2


def _spelling_pattern(term: str) -> str:
    """POSIX regex for the whole words within the allowed edit distance of a lower-case `term`.

    The pattern is built from the term only, which is letters and digits (`_query` guarantees
    that), and is matched against lower-cased text, so no user text becomes regex syntax. Each
    `.` stands for one substituted or inserted character. `\\y` anchors both ends of the word, so
    "anna" never matches inside "johanna".
    """

    variants: set[str] = set()

    def walk(index: int, left: int, pattern: str) -> None:
        if index == len(term):
            variants.add(pattern)
        else:
            walk(index + 1, left, pattern + term[index])
        if left == 0:
            return
        if index < len(term):
            walk(index + 1, left - 1, pattern + ".")
            walk(index + 1, left - 1, pattern)
        walk(index, left - 1, pattern + ".")

    walk(0, _spelling_max_edits(term), "")
    return "\\y(?:" + "|".join(sorted(variants)) + ")\\y"


_SIMPLE_CONFIG = literal_column("'simple'::regconfig", String())
_SWEDISH_CONFIG = literal_column("'swedish'::regconfig", String())
# Constant SQL literals that label the union branches; never built from user input.
_ENTRY = literal_column("'entry'::text", String())
_SOURCE = literal_column("'source'::text", String())
_SOURCE_TEXT = literal_column("'source_text'::text", String())


@dataclass(frozen=True, slots=True)
class TaskHit:
    id: UUID
    title: str
    status: str
    version: int


@dataclass(frozen=True, slots=True)
class ProjectHit:
    id: UUID
    title: str
    status: str
    version: int


@dataclass(frozen=True, slots=True)
class ContactHit:
    id: UUID
    display_name: str
    version: int


@dataclass(frozen=True, slots=True)
class JournalHit:
    """A journal match. `id_type` is `entry` or `source`; `matched_in` is `entry` or `source_text`.

    `title` is the entry title, clipped like other titles, and None for a source without an entry.
    The hit deliberately has no summary, raw text or excerpt field (D-058).
    """

    id: UUID
    id_type: Literal["entry", "source"]
    journal_date: date
    matched_in: Literal["entry", "source_text"]
    title: str | None


def _query(terms: Sequence[str]) -> tuple[ColumnElement[Any], str]:
    """Build the OR of simple and swedish prefix tsqueries, and the plain trigram string."""

    if not terms:
        raise ValueError("at least one search term is required")
    if not all(term.isalnum() for term in terms):
        raise ValueError("search terms must contain only letters and digits")
    prefixes = " & ".join(f"{term}:*" for term in terms)
    tsquery = func.to_tsquery(_SIMPLE_CONFIG, prefixes).op("||")(
        func.to_tsquery(_SWEDISH_CONFIG, prefixes)
    )
    return tsquery, " ".join(terms)


def _matches(
    vector: Any, title: Any, tsquery: ColumnElement[Any], query: str
) -> ColumnElement[bool]:
    """A row matches by full-text prefix or by trigram similarity of its title or name."""

    return or_(vector.op("@@")(tsquery), title.op("%")(query))


def _rank(vector: Any, title: Any, tsquery: ColumnElement[Any], query: str) -> ColumnElement[Any]:
    return func.coalesce(func.ts_rank(vector, tsquery), 0) + func.similarity(title, query)


def _clip(value: str) -> str:
    return value[:TITLE_LIMIT]


class SearchStore(SqlAlchemyStore):
    """Owner-filtered search reads. Callers pass the owner id from the authenticated actor."""

    @staticmethod
    def search_tasks(
        session: Session,
        owner_id: UUID,
        terms: Sequence[str],
        *,
        limit: int,
        offset: int = 0,
    ) -> list[TaskHit]:
        tsquery, query = _query(terms)
        score = _rank(TaskRow.search_vector, TaskRow.title, tsquery, query)
        rows = session.execute(
            select(TaskRow.id, TaskRow.title, TaskRow.status, TaskRow.version, score.label("score"))
            .where(
                TaskRow.owner_id == owner_id,
                TaskRow.trashed_at.is_(None),
                TaskRow.archived_at.is_(None),
                task_parents_live(),
                _matches(TaskRow.search_vector, TaskRow.title, tsquery, query),
            )
            .order_by(score.desc(), TaskRow.updated_at.desc(), TaskRow.id.asc())
            .offset(offset)
            .limit(limit)
        ).all()
        return [
            TaskHit(id=row.id, title=_clip(row.title), status=row.status, version=row.version)
            for row in rows
        ]

    @staticmethod
    def search_projects(
        session: Session,
        owner_id: UUID,
        terms: Sequence[str],
        *,
        limit: int,
        offset: int = 0,
    ) -> list[ProjectHit]:
        tsquery, query = _query(terms)
        score = _rank(ProjectRow.search_vector, ProjectRow.title, tsquery, query)
        rows = session.execute(
            select(
                ProjectRow.id,
                ProjectRow.title,
                ProjectRow.status,
                ProjectRow.version,
                score.label("score"),
            )
            .where(
                ProjectRow.owner_id == owner_id,
                ProjectRow.trashed_at.is_(None),
                ProjectRow.archived_at.is_(None),
                _matches(ProjectRow.search_vector, ProjectRow.title, tsquery, query),
            )
            .order_by(score.desc(), ProjectRow.updated_at.desc(), ProjectRow.id.asc())
            .offset(offset)
            .limit(limit)
        ).all()
        return [
            ProjectHit(id=row.id, title=_clip(row.title), status=row.status, version=row.version)
            for row in rows
        ]

    @staticmethod
    def search_contacts(
        session: Session,
        owner_id: UUID,
        terms: Sequence[str],
        *,
        limit: int,
        offset: int = 0,
    ) -> list[ContactHit]:
        """Match on display name, context note or any alias; alias text is never returned."""

        tsquery, query = _query(terms)
        alias = aliased(ContactAliasRow)
        alias_match = _matches(alias.search_vector, alias.display_value, tsquery, query)
        alias_scope = and_(
            alias.owner_id == owner_id,
            alias.contact_id == ContactRow.id,
            alias_match,
        )
        matched_alias = select(alias.id).where(alias_scope).exists()
        best_alias_score = (
            select(func.max(_rank(alias.search_vector, alias.display_value, tsquery, query)))
            .where(alias_scope)
            .scalar_subquery()
        )
        score = _rank(ContactRow.search_vector, ContactRow.display_name, tsquery, query) + (
            func.coalesce(best_alias_score, 0)
        )
        rows = session.execute(
            select(ContactRow.id, ContactRow.display_name, ContactRow.version, score.label("score"))
            .where(
                ContactRow.owner_id == owner_id,
                ContactRow.trashed_at.is_(None),
                ContactRow.archived.is_(False),
                ContactRow.archived_at.is_(None),
                or_(
                    _matches(ContactRow.search_vector, ContactRow.display_name, tsquery, query),
                    matched_alias,
                ),
            )
            .order_by(score.desc(), ContactRow.updated_at.desc(), ContactRow.id.asc())
            .offset(offset)
            .limit(limit)
        ).all()
        return [
            ContactHit(id=row.id, display_name=_clip(row.display_name), version=row.version)
            for row in rows
        ]

    @staticmethod
    def closest_contacts(
        session: Session,
        owner_id: UUID,
        terms: Sequence[str],
        *,
        limit: int = CLOSEST_LIMIT,
    ) -> list[ContactHit]:
        """Contacts whose name or alias is close to each term, for a misheard name ("Elijas").

        Compares every term with the words of the display name and of every alias. A term matches
        by `strict_word_similarity`, which compares whole words only (so "Anna" does not match the
        end of "Johanna"), or, for terms up to 6 characters, by spelling: a whole word within 1
        edit (3-4 letters) or 2 edits (5-6 letters), such as "Elijas" for "Elias" or "Peter" for
        "Petra". A first name alone is enough. Every term must match. Terms shorter than 3
        characters are ignored, so one or two letters never produce a false hit. Owner-scoped,
        active Contacts only; alias text is never returned.
        """

        usable = [term for term in terms if len(term) >= CLOSEST_MIN_TERM_LENGTH]
        if not usable:
            return []
        alias = aliased(ContactAliasRow)
        bests: list[ColumnElement[Any]] = []
        conditions: list[ColumnElement[bool]] = []
        for term in usable:
            alias_best = (
                select(func.max(func.strict_word_similarity(term, alias.display_value)))
                .where(alias.owner_id == owner_id, alias.contact_id == ContactRow.id)
                .scalar_subquery()
            )
            best = func.greatest(
                func.strict_word_similarity(term, ContactRow.display_name),
                func.coalesce(alias_best, 0),
            )
            threshold = best >= _closest_threshold(term)
            if len(term) > CLOSEST_SPELLING_MAX_TERM_LENGTH:
                conditions.append(threshold)
                bests.append(best)
                continue
            pattern = _spelling_pattern(term.lower())
            spelled_alias = (
                select(alias.id)
                .where(
                    alias.owner_id == owner_id,
                    alias.contact_id == ContactRow.id,
                    func.lower(alias.display_value).op("~")(pattern),
                )
                .exists()
            )
            spelled = or_(func.lower(ContactRow.display_name).op("~")(pattern), spelled_alias)
            conditions.append(or_(threshold, spelled))
            bests.append(func.greatest(best, case((spelled, CLOSEST_SPELLING_SCORE), else_=0.0)))
        total = sum(bests[1:], bests[0])
        rows = session.execute(
            select(ContactRow.id, ContactRow.display_name, ContactRow.version, total.label("score"))
            .where(
                ContactRow.owner_id == owner_id,
                ContactRow.trashed_at.is_(None),
                ContactRow.archived.is_(False),
                ContactRow.archived_at.is_(None),
                *conditions,
            )
            .order_by(total.desc(), ContactRow.updated_at.desc(), ContactRow.id.asc())
            .limit(limit)
        ).all()
        return [
            ContactHit(id=row.id, display_name=_clip(row.display_name), version=row.version)
            for row in rows
        ]

    @staticmethod
    def search_journal(
        session: Session,
        owner_id: UUID,
        terms: Sequence[str],
        *,
        limit: int,
        offset: int = 0,
    ) -> list[JournalHit]:
        """Entries matched by their own text or through their source, plus sources with no entry.

        A source that was replaced by a newer live source is excluded. A source whose entries are
        all trashed or archived is excluded too, because it has entries but none that is live.
        """

        tsquery, query = _query(terms)
        entry = JournalEntryRow
        source = JournalSourceRow
        replacement = aliased(JournalSourceRow)
        replaced = (
            select(replacement.id)
            .where(
                replacement.owner_id == owner_id,
                replacement.replaces_source_id == source.id,
                replacement.trashed_at.is_(None),
            )
            .exists()
        )
        live_source = and_(source.owner_id == owner_id, source.trashed_at.is_(None), ~replaced)
        entry_text_match = _matches(entry.search_vector, entry.title, tsquery, query)

        entry_hits = (
            select(
                entry.id.label("id"),
                _ENTRY.label("id_type"),
                entry.journal_date.label("journal_date"),
                case(
                    (entry_text_match, _ENTRY),
                    else_=_SOURCE_TEXT,
                ).label("matched_in"),
                entry.title.label("title"),
                (
                    func.coalesce(func.ts_rank(entry.search_vector, tsquery), 0)
                    + func.coalesce(func.ts_rank(source.search_vector, tsquery), 0)
                    + func.similarity(entry.title, query)
                ).label("score"),
                entry.updated_at.label("sort_at"),
            )
            .join(
                source,
                and_(source.id == entry.source_id, source.owner_id == entry.owner_id),
            )
            .where(
                entry.owner_id == owner_id,
                entry.trashed_at.is_(None),
                entry.archived_at.is_(None),
                live_source,
                or_(entry_text_match, source.search_vector.op("@@")(tsquery)),
            )
        )

        has_entry = (
            select(entry.id)
            .where(entry.owner_id == owner_id, entry.source_id == source.id)
            .exists()
        )
        source_hits = select(
            source.id.label("id"),
            _SOURCE.label("id_type"),
            source.journal_date.label("journal_date"),
            _SOURCE_TEXT.label("matched_in"),
            cast(null(), String).label("title"),
            func.coalesce(func.ts_rank(source.search_vector, tsquery), 0).label("score"),
            source.created_at.label("sort_at"),
        ).where(live_source, ~has_entry, source.search_vector.op("@@")(tsquery))

        hits = union_all(entry_hits, source_hits).subquery("journal_hits")
        rows = session.execute(
            select(hits.c.id, hits.c.id_type, hits.c.journal_date, hits.c.matched_in, hits.c.title)
            .order_by(hits.c.score.desc(), hits.c.sort_at.desc(), hits.c.id.asc())
            .offset(offset)
            .limit(limit)
        ).all()
        return [
            JournalHit(
                id=row.id,
                id_type=row.id_type,
                journal_date=row.journal_date,
                matched_in=row.matched_in,
                title=None if row.title is None else _clip(row.title),
            )
            for row in rows
        ]
