"""The ports process-run materialization writes a Task and its activity through.

Process runs create a Task and record an activity entry in their own transaction. They depend
on these protocols, not on the Task or automation application layers; the composition root
injects the Task service and the automation activity ledger, which satisfy them.
"""

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from sidekick.shared.types import Actor, TxSession


class RunTaskCreator(Protocol):
    """Creates one Task inside the caller's open transaction and returns its serialized result."""

    def create_in_session(
        self,
        session: TxSession,
        actor: Actor,
        payload: dict[str, Any],
        correlation_id: str | None,
        /,
        *,
        actor_type: str,
    ) -> dict[str, Any]: ...


class RunActivityRecorder(Protocol):
    """Appends one activity event and its read projection inside the caller's transaction."""

    def append(
        self,
        session: TxSession,
        /,
        *,
        owner_id: UUID,
        aggregate_type: str,
        aggregate_id: UUID,
        aggregate_version: int,
        event_type: str,
        actor_type: str,
        actor_id: UUID | None,
        operation: str,
        category: str,
        summary: str,
        after_values: dict[str, Any] | None = None,
        evidence: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        occurred_at: datetime,
    ) -> UUID: ...
