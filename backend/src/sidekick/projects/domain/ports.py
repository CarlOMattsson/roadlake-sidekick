"""The read other contexts' stores borrow from Projects."""

from typing import Protocol
from uuid import UUID

from sidekick.projects.domain.project import Project
from sidekick.shared.types import TxSession


class ProjectReader(Protocol):
    def get_project(
        self,
        session: TxSession,
        owner_id: UUID,
        project_id: UUID,
        include_archived: bool = False,
    ) -> Project: ...
