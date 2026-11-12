"""The reviewed Journal draft effect package: command, result and the stale-proposal conflict."""

from dataclasses import dataclass
from uuid import UUID

from sidekick.shared.errors import ConflictError

from .analysis import KeyPoint, TaskProposal
from .entry import JournalEntry


@dataclass(frozen=True, slots=True)
class FinalizeCommand:
    draft_id: UUID
    expected_version: int
    title: str
    summary: str | None
    key_points: tuple[KeyPoint, ...]
    relation_selection: dict[str, tuple[tuple[UUID, str], ...]]
    task_proposals: tuple[TaskProposal, ...]


@dataclass(frozen=True, slots=True)
class FinalizeResult:
    entry: JournalEntry
    project_ids: tuple[UUID, ...]
    task_ids: tuple[UUID, ...]
    contact_ids: tuple[UUID, ...]
    created_task_ids: tuple[UUID, ...]
    updated_task_ids: tuple[UUID, ...]


class FinalizeProposalConflict(ConflictError):
    """A safe conflict identifying only the selected proposal."""

    def __init__(self, proposal_id: UUID, message: str = "selected Task proposal is stale") -> None:
        super().__init__(message)
        self.proposal_id = proposal_id
