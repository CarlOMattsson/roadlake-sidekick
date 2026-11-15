"""The port a Task command records its user-visible activity through.

Task use cases depend on this protocol, not on the activity application layer; the
composition root injects the activity ledger, which satisfies it.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sidekick.shared.types import TxSession

from .task import Task


class TaskActivityRecorder(Protocol):
    """Records one Task command in the activity history, inside the command's transaction."""

    def record_task(
        self,
        session: TxSession,
        /,
        *,
        task: Task,
        operation: str,
        actor_id: UUID,
        actor_type: str,
        occurred_at: datetime,
        before: Task | None = None,
        correlation_id: str | None = None,
        changed_fields: frozenset[str] | None = None,
    ) -> UUID: ...

    def record_unchanged_review(
        self,
        session: TxSession,
        /,
        *,
        tasks: Sequence[Task],
        actor_id: UUID,
        actor_type: str,
        occurred_at: datetime,
        correlation_id: str | None = None,
    ) -> UUID:
        """One entry for every Task a review kept unchanged, instead of one per Task."""
        ...
