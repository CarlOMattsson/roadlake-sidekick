"""Deterministic in-process memory provider for tests and local development.

One non-empty line of a document becomes one fact, so tests can predict counts exactly. Replace
semantics match the real provider: a second retain of the same document replaces its facts.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sidekick.memory.ports import (
    MemoryFact,
    MemoryProviderError,
    OperationResult,
    RetainItem,
    validate_bank_id,
    validate_opaque_id,
    validate_retain_items,
)

MAX_RECALL_TOKENS = 2_048
UNSET_TIMESTAMP = "unset"


@dataclass(slots=True)
class FakeRetainCall:
    owner_id: UUID
    items: tuple[RetainItem, ...]
    operation_id: str


class FakeMemoryProvider:
    """Keeps facts per owner and document in memory. `available=False` simulates an outage."""

    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self._facts: dict[tuple[UUID, str], tuple[MemoryFact, ...]] = {}
        self._operations: dict[str, OperationResult] = {}
        self.retain_calls: list[FakeRetainCall] = []
        self.delete_calls: list[tuple[UUID, str]] = []
        #: Banks that exist, by id. Retaining creates one and `delete_bank` removes it. Tests may
        #: add ids directly to model banks that belong to somebody else.
        self.banks: set[str] = set()
        self.deleted_banks: list[str] = []

    @property
    def provider_name(self) -> Literal["fake"]:
        return "fake"

    def retain_batch(self, *, owner_id: UUID, items: Sequence[RetainItem]) -> str:
        validate_retain_items(items)
        self._require_available()
        self.banks.add(self.bank_id_for(owner_id))
        for item in items:
            self._facts[(owner_id, item.document_id)] = _facts_for(item)
        operation_id = f"fake-op-{len(self._operations) + 1:06d}"
        self._operations[operation_id] = OperationResult(state="retained")
        self.retain_calls.append(
            FakeRetainCall(owner_id=owner_id, items=tuple(items), operation_id=operation_id)
        )
        return operation_id

    def operation_status(self, *, owner_id: UUID, operation_id: str) -> OperationResult:
        validate_opaque_id(operation_id)
        self._require_available()
        return self._operations.get(
            operation_id, OperationResult(state="failed", failure_category="operation_lost")
        )

    def delete_document(self, *, owner_id: UUID, document_id: str) -> None:
        validate_opaque_id(document_id)
        self._require_available()
        self.delete_calls.append((owner_id, document_id))
        self._facts.pop((owner_id, document_id), None)

    def recall(self, *, owner_id: UUID, query: str, max_tokens: int) -> tuple[MemoryFact, ...]:
        if not 1 <= max_tokens <= MAX_RECALL_TOKENS:
            raise ValueError("memory recall token budget is out of bounds")
        self._require_available()
        terms = {term.casefold() for term in query.split() if term.strip()}
        if not terms:
            return ()
        selected: list[MemoryFact] = []
        budget = max_tokens * 4
        for (fact_owner, _document_id), facts in self._facts.items():
            if fact_owner != owner_id:
                continue
            for fact in facts:
                if not any(term in fact.text.casefold() for term in terms):
                    continue
                budget -= max(1, (len(fact.text) + 3) // 4)
                if budget < 0:
                    return tuple(selected)
                selected.append(fact)
        return tuple(selected)

    def bank_id_for(self, owner_id: UUID) -> str:
        return "v1_" + hashlib.sha256(f"fake-bank:{owner_id}".encode()).hexdigest()

    def list_banks(self) -> tuple[str, ...]:
        self._require_available()
        return tuple(sorted(self.banks))

    def delete_bank(self, *, bank_id: str) -> None:
        validate_bank_id(bank_id)
        self._require_available()
        self.deleted_banks.append(bank_id)
        self.banks.discard(bank_id)
        for key in [key for key in self._facts if self.bank_id_for(key[0]) == bank_id]:
            del self._facts[key]

    def document_count(self, *, owner_id: UUID) -> int:
        self._require_available()
        if self.bank_id_for(owner_id) not in self.banks:
            return 0
        return sum(1 for (fact_owner, _doc) in self._facts if fact_owner == owner_id)

    def health(self) -> bool:
        return self.available

    def _require_available(self) -> None:
        if not self.available:
            raise MemoryProviderError("unavailable")


def _facts_for(item: RetainItem) -> tuple[MemoryFact, ...]:
    occurred = None if item.timestamp == UNSET_TIMESTAMP else item.timestamp
    lines = [line.strip() for line in item.content.splitlines() if line.strip()]
    return tuple(
        MemoryFact(
            id=f"{item.document_id}#{index}",
            text=line,
            document_id=item.document_id,
            occurred_start=occurred,
            occurred_end=occurred,
            fact_type="world",
        )
        for index, line in enumerate(lines, start=1)
    )
