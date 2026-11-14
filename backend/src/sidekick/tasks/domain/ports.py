"""The read other contexts' stores borrow from Tasks."""

from typing import Protocol
from uuid import UUID

from sidekick.shared.types import TxSession
from sidekick.tasks.domain.task import Task


class TaskReader(Protocol):
    def get_task(
        self,
        session: TxSession,
        owner_id: UUID,
        task_id: UUID,
        include_archived: bool = False,
        for_update: bool = False,
        include_hidden: bool = False,
    ) -> Task: ...
