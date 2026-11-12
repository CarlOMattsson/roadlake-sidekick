"""Query parsing and kind/scope resolution for search, without transport or database.

Search covers Tasks, Projects, Contacts and Journal. A kind is searched only when the actor
holds that kind's read scope. Query text is reduced to plain letter and digit terms before
it reaches any SQL, so no tsquery operator can pass through.
"""

import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from sidekick.shared.errors import PermissionDeniedError, ValidationError

MAX_TERMS: Final = 8
MIN_TERM_LENGTH: Final = 2
MAX_KINDS: Final = 4


class Kind(StrEnum):
    TASK = "task"
    PROJECT = "project"
    CONTACT = "contact"
    JOURNAL = "journal"


KIND_SCOPE: Final[dict[Kind, str]] = {
    Kind.TASK: "tasks:read",
    Kind.PROJECT: "projects:read",
    Kind.CONTACT: "contacts:read",
    Kind.JOURNAL: "journal:read",
}


@dataclass(frozen=True, slots=True)
class SearchQuery:
    """A sanitized query: at most MAX_TERMS terms, each of at least MIN_TERM_LENGTH characters.

    `length` is the NFC-normalized length of the raw input and is meant for telemetry only.
    """

    terms: tuple[str, ...]
    length: int

    @property
    def term_count(self) -> int:
        return len(self.terms)


def _is_term_character(char: str) -> bool:
    category = unicodedata.category(char)
    return category[0] == "L" or category == "Nd"


def parse_query(raw: str) -> SearchQuery:
    """Normalize and sanitize a raw query. Raises ValueError when no usable term remains."""
    normalized = unicodedata.normalize("NFC", raw).strip()
    terms: list[str] = []
    for token in normalized.split():
        term = "".join(char for char in token if _is_term_character(char))
        if len(term) < MIN_TERM_LENGTH:
            continue
        terms.append(term)
        if len(terms) == MAX_TERMS:
            break
    if not terms:
        raise ValueError("search query is too short")
    return SearchQuery(terms=tuple(terms), length=len(normalized))


def resolve_kinds(requested: Sequence[str] | None, scopes: Iterable[str]) -> tuple[Kind, ...]:
    """Return the kinds to search, in canonical order when none were requested.

    With `requested` omitted, only kinds the actor holds scope for are returned, and no scope
    at all raises PermissionDeniedError. An explicitly requested kind without scope rejects the
    whole call, so nothing is searched partially. Error messages never name the scope or the
    input.
    """
    granted = frozenset(scopes)
    if requested is None:
        allowed = tuple(kind for kind in Kind if KIND_SCOPE[kind] in granted)
        if not allowed:
            raise PermissionDeniedError("forbidden")
        return allowed

    if not requested or len(requested) > MAX_KINDS or len(set(requested)) != len(requested):
        raise ValidationError("kinds must be 1-4 unique search kinds")
    kinds: list[Kind] = []
    for raw in requested:
        try:
            kinds.append(Kind(raw))
        except ValueError as error:
            raise ValidationError("unknown search kind") from error
    for kind in kinds:
        if KIND_SCOPE[kind] not in granted:
            raise PermissionDeniedError("forbidden")
    return tuple(kinds)
