"""Project domain entity and invariants."""

from dataclasses import dataclass, replace
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from sidekick.shared.errors import ValidationError
from sidekick.shared.types import UNSET, UnsetType
from sidekick.work.domain.planning import MAX_DEFINITION_OF_DONE_LENGTH


class ProjectStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class Project:
    id: UUID
    owner_id: UUID
    title: str
    description: str | None
    status: ProjectStatus
    start_date: date | None
    target_date: date | None
    created_at: datetime
    updated_at: datetime
    domain_id: UUID
    version: int = 1
    archived_at: datetime | None = None
    definition_of_done: str | None = None
    """What finishing this project means. Prose, never a machine condition."""

    def __post_init__(self) -> None:
        title = self.title.strip()
        if not title or len(title) > 200:
            raise ValidationError("project title must contain 1-200 characters")
        if self.description is not None and len(self.description) > 10_000:
            raise ValidationError("project description is too long")
        if self.start_date and self.target_date and self.target_date < self.start_date:
            raise ValidationError("target date cannot precede start date")
        if (
            self.definition_of_done is not None
            and len(self.definition_of_done) > MAX_DEFINITION_OF_DONE_LENGTH
        ):
            raise ValidationError("project definition of done is too long")
        if self.version < 1:
            raise ValidationError("project version must be positive")
        object.__setattr__(self, "title", title)

    def update(
        self,
        *,
        now: datetime,
        title: str | UnsetType = UNSET,
        description: str | UnsetType | None = UNSET,
        status: ProjectStatus | UnsetType = UNSET,
        start_date: date | UnsetType | None = UNSET,
        target_date: date | UnsetType | None = UNSET,
        domain_id: UUID | UnsetType = UNSET,
        definition_of_done: str | UnsetType | None = UNSET,
    ) -> "Project":
        """Apply the mutable Project fields, including its planning metadata.

        `start_date` is the project's earliest start: the project-level counterpart
        of a Task's `not_before`. It is never derived from the dates of its Tasks.
        """

        changes = {
            key: value
            for key, value in {
                "title": title,
                "description": description,
                "status": status,
                "start_date": start_date,
                "target_date": target_date,
                "domain_id": domain_id,
                "definition_of_done": definition_of_done,
            }.items()
            if value is not UNSET
        }
        if not changes:
            raise ValidationError("at least one project change is required")
        if "domain_id" in changes and not isinstance(changes["domain_id"], UUID):
            raise ValidationError("project domain is required")
        next_start = self.start_date if start_date is UNSET else start_date
        next_target = self.target_date if target_date is UNSET else target_date
        if next_start and next_target and next_target < next_start:
            raise ValidationError("target date cannot precede start date")
        return replace(self, **changes, updated_at=now, version=self.version + 1)

    def archive(self, *, now: datetime) -> "Project":
        if self.archived_at is not None:
            return self
        return replace(self, archived_at=now, updated_at=now, version=self.version + 1)

    def complete(self, *, now: datetime) -> "Project":
        """Record that this finite project outcome has been achieved."""
        if self.status is ProjectStatus.COMPLETED:
            return self
        return replace(
            self,
            status=ProjectStatus.COMPLETED,
            updated_at=now,
            version=self.version + 1,
        )

    def restore(self, *, now: datetime) -> "Project":
        if self.archived_at is None:
            return self
        return replace(self, archived_at=None, updated_at=now, version=self.version + 1)
