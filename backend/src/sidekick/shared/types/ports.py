"""The persistence operations every context's store Protocol shares.

Each application service declares the narrow store Protocol it needs. Three members are the same
in all of them: opening a transaction, running an idempotent write and appending an audit event.
They are declared once here; a context Protocol inherits the ones it uses and adds only what is
specific to its context. A policy test fails if a context Protocol re-declares them.
"""

from collections.abc import Callable
from typing import Any, Protocol, TypeVar
from uuid import UUID

from .tx import TxSession

T = TypeVar("T")


class TransactionalStore(Protocol):
    def transaction(self, operation: Callable[[TxSession], T]) -> T: ...


class IdempotentStore(Protocol):
    def idempotent(
        self,
        session: TxSession,
        *,
        actor_id: UUID,
        operation: str,
        key: str,
        payload: dict[str, Any],
        execute: Callable[[], dict[str, Any]],
        replay: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> dict[str, Any]: ...


class AuditingStore(Protocol):
    def append_audit(
        self,
        session: TxSession,
        *,
        actor_id: UUID | None,
        event: str,
        outcome: str,
        target_type: str | None = None,
        target_id: UUID | None = None,
        related_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> None: ...
