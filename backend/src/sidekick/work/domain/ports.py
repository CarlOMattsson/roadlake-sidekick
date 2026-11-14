"""The Work reads and writes other contexts' stores borrow, as small ports."""

from typing import Protocol
from uuid import UUID

from sidekick.shared.types import TxSession
from sidekick.work.domain.context import Domain, Process
from sidekick.work.domain.steps import Step


class StructureReader(Protocol):
    """The Domain and Process a Task or Project points at."""

    def get_domain(self, session: TxSession, owner_id: UUID, domain_id: UUID) -> Domain: ...
    def get_process(self, session: TxSession, owner_id: UUID, process_id: UUID) -> Process: ...


class TaskStepStore(Protocol):
    """The Steps of a Task, which its use cases read and write with the Task."""

    def save_step(self, session: TxSession, step: Step) -> None: ...
    def list_steps(
        self,
        session: TxSession,
        owner_id: UUID,
        task_id: UUID,
        limit: int,
        offset: int = 0,
        include_archived: bool = False,
    ) -> list[Step]: ...
    def list_live_steps_by_ids(
        self, session: TxSession, owner_id: UUID, step_ids: tuple[UUID, ...]
    ) -> dict[UUID, Step]: ...
