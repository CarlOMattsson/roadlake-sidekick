"""Port for the derived memory provider. Application code depends on this, not on Hindsight.

Every failure that crosses this boundary is a `MemoryProviderError` carrying a fixed category.
Messages, document text, facts and provider bodies never travel with it, so they cannot leak
into logs or responses.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol
from uuid import UUID

from sidekick.shared.errors.core import InternalFaultError

MemoryFailureCategory = Literal[
    "unavailable",
    "timeout",
    "unauthorized",
    "rate_limited",
    "rejected",
    "invalid_response",
    "operation_failed",
    "operation_lost",
]
OperationState = Literal["pending", "retained", "failed"]
#: What curating one provider fact came to: `applied` (the fact is now in the requested state, an
#: unchanged one included) or `gone` (the provider no longer has that fact, for example because its
#: document was replaced since).
FactCurationOutcome = Literal["applied", "gone"]
#: Which adapter serves the port. For status displays only; application code must not branch on it.
MemoryProviderName = Literal["fake", "hindsight"]

#: Upper bound per retain request. The sync pass sends at most this many pending documents.
MAX_RETAIN_BATCH = 20
#: Opaque ids are server-derived and used in URL paths, so only this alphabet is accepted.
OPAQUE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
#: The exact shape of a bank id Sidekick derives (`v1_` plus an HMAC-SHA256 hex digest). A bank id
#: that does not match is never treated as ours and never deleted.
BANK_ID_PATTERN = re.compile(r"^v1_[0-9a-f]{64}$")


#: Fact types Sidekick may release. Hindsight's derived `observation` type merges several documents
#: into one fact, so it has no single source version and is never allowed. Any other type, a
#: type this list does not name included, is refused rather than guessed at.
ALLOWED_FACT_TYPES: frozenset[str] = frozenset({"world", "experience"})


class MemoryProviderError(InternalFaultError):
    """Content-free provider failure. `category` is the only detail that may be logged or stored."""

    def __init__(self, category: MemoryFailureCategory) -> None:
        super().__init__(category)
        self.category: MemoryFailureCategory = category


@dataclass(frozen=True, slots=True)
class RetainItem:
    """One canonical document. `document_id` is the opaque `doc_key` from `memory_sources`."""

    document_id: str
    content: str
    #: Event time as ISO-8601, or the literal "unset" (for example for contacts).
    timestamp: str
    entities: tuple[str, ...]
    tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OperationResult:
    state: OperationState
    failure_category: MemoryFailureCategory | None = None


@dataclass(frozen=True, slots=True)
class MemoryFact:
    """A recalled fact and the document it was derived from. Callers check the source row."""

    id: str
    #: Left out of `repr`, so a fact in a log line or a traceback never prints its text.
    text: str = field(repr=False)
    document_id: str
    occurred_start: str | None
    occurred_end: str | None
    #: The provider's fact type. None when the provider does not say (observations are then off by
    #: configuration); a value outside `ALLOWED_FACT_TYPES` is refused by the adapter and by recall.
    fact_type: str | None = None


@dataclass(frozen=True, slots=True)
class DocumentFact:
    """One valid fact of a document, as the provider lists it."""

    id: str
    #: Left out of `repr`, so a fact in a log line or a traceback never prints its text.
    text: str = field(repr=False)


def validate_opaque_id(value: str) -> None:
    if not OPAQUE_ID_PATTERN.fullmatch(value):
        raise ValueError("memory opaque id is invalid")


def validate_bank_id(value: str) -> None:
    if not BANK_ID_PATTERN.fullmatch(value):
        raise ValueError("memory bank id is invalid")


def validate_retain_items(items: Sequence[RetainItem]) -> None:
    """Shared by every provider so the fake rejects exactly what the real adapter rejects."""

    if not 1 <= len(items) <= MAX_RETAIN_BATCH:
        raise ValueError("memory retain batch size is out of bounds")
    seen: set[str] = set()
    for item in items:
        validate_opaque_id(item.document_id)
        if not item.content.strip():
            raise ValueError("memory document cannot be empty")
        if not item.timestamp.strip():
            raise ValueError("memory document timestamp is invalid")
        if item.document_id in seen:
            raise ValueError("memory retain batch repeats a document")
        seen.add(item.document_id)


class MemoryProvider(Protocol):
    @property
    def provider_name(self) -> MemoryProviderName:
        """The adapter's name, for status displays only. Pure; no network."""
        ...

    def retain_batch(self, *, owner_id: UUID, items: Sequence[RetainItem]) -> str:
        """Submit documents with replace semantics. Returns the provider operation id."""
        ...

    def operation_status(self, *, owner_id: UUID, operation_id: str) -> OperationResult: ...

    def delete_document(self, *, owner_id: UUID, document_id: str) -> None:
        """Delete a document and its facts. A document that is already gone is not an error."""
        ...

    def recall(self, *, owner_id: UUID, query: str, max_tokens: int) -> tuple[MemoryFact, ...]: ...

    def bank_id_for(self, owner_id: UUID) -> str:
        """The bank id this provider derives for an owner. Pure; no network."""
        ...

    def list_banks(self) -> tuple[str, ...]:
        """Every bank id the provider holds, whatever its shape. Callers filter by the pattern."""
        ...

    def delete_bank(self, *, bank_id: str) -> None:
        """Delete a whole bank. Only ids matching `BANK_ID_PATTERN` are accepted. A bank that is
        already gone is not an error."""
        ...

    def document_count(self, *, owner_id: UUID) -> int:
        """Number of documents in the owner's bank. Raises `MemoryProviderError` when the provider
        cannot give a definite answer (a 404 included), so a caller never reads an error as 0."""
        ...

    def health(self) -> bool: ...


class FactCuration(Protocol):
    """Hiding single facts at the provider, for the statements the owner asked to forget.

    Only the reconcile pass calls these. An invalidated fact is left out of recall and listings at
    the provider and can be restored, so nothing is lost by hiding it. A call never carries the
    text of a fact.
    """

    def invalidate_fact(self, *, owner_id: UUID, fact_id: str) -> FactCurationOutcome:
        """Hide one fact. Hiding a fact that is already hidden is not an error."""
        ...

    def restore_fact(self, *, owner_id: UUID, fact_id: str) -> FactCurationOutcome:
        """Show a hidden fact again. Restoring a fact that is not hidden is not an error."""
        ...

    def list_document_facts(self, *, owner_id: UUID, document_id: str) -> tuple[DocumentFact, ...]:
        """The valid facts of one document, hidden ones left out. A document the provider does not
        have lists no facts."""
        ...
