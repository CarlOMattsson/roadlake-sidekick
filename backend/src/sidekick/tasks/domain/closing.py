"""The port through which completing or reopening a Task carries its Steps and Actions along.

Task use cases depend on this protocol, not on the Work application layer; the composition root
injects the implementation, which runs in the command's own transaction.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sidekick.shared.types import TxSession

from .task import Task


@dataclass(frozen=True, slots=True)
class StepsMoved:
    """How many Steps and Actions a command closed, opened again or reset."""

    steps: int = 0
    actions: int = 0

    def __bool__(self) -> bool:
        return bool(self.steps or self.actions)


class TaskStepCloser(Protocol):
    def close(
        self,
        session: TxSession,
        /,
        *,
        actor_id: UUID,
        task: Task,
        now: datetime,
        correlation_id: str | None = None,
    ) -> StepsMoved:
        """Complete the open Steps of `task`, and their open Actions, as of `now`."""
        ...

    def reopen(
        self,
        session: TxSession,
        /,
        *,
        actor_id: UUID,
        task: Task,
        now: datetime,
        correlation_id: str | None = None,
    ) -> StepsMoved:
        """Open again what the completion of `task` (as it stood when completed) closed."""
        ...

    def reset(
        self,
        session: TxSession,
        /,
        *,
        actor_id: UUID,
        task: Task,
        now: datetime,
        correlation_id: str | None = None,
    ) -> StepsMoved:
        """Start the Steps and Actions of a repeating `task` over for its next run."""
        ...
