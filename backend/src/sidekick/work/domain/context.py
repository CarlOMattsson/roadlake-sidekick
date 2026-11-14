"""Domain and Process entities.

Process and Project are deliberately peer contexts. A Process may recur or remain
ongoing, while a Project represents a finite outcome; neither entity owns the other.

Both carry a declared rhythm rather than a deadline: a Domain declares how often it
should be reviewed, a Process how often it should run. Neither timestamp is written
automatically; `review_due` is derived from stored values and the clock.
"""

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sidekick.shared.cadence import Cadence
from sidekick.shared.errors import ValidationError
from sidekick.shared.types import UNSET, UnsetType
from sidekick.work.domain.planning import is_review_due


class DomainStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


DOMAIN_ACCENTS: tuple[str, ...] = (
    "slate",
    "blue",
    "teal",
    "green",
    "amber",
    "orange",
    "rose",
    "violet",
)
"""The colour palette a Domain may carry; NULL means no colour was chosen."""


class ProcessStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


@dataclass(frozen=True, slots=True)
class Domain:
    id: UUID
    owner_id: UUID
    name: str
    description: str | None
    status: DomainStatus
    created_at: datetime
    updated_at: datetime
    version: int = 1
    review_cadence: Cadence | None = None
    last_reviewed_at: datetime | None = None
    accent: str | None = None

    def __post_init__(self) -> None:
        name = self.name.strip()
        if not name or len(name) > 200:
            raise ValidationError("domain name must contain 1-200 characters")
        if self.description is not None and len(self.description) > 10_000:
            raise ValidationError("domain description is too long")
        if self.version < 1:
            raise ValidationError("domain version must be positive")
        if self.accent is not None and self.accent not in DOMAIN_ACCENTS:
            raise ValidationError("domain accent must be one of the known palette names")
        object.__setattr__(self, "name", name)

    def review_due(self, *, now: datetime) -> bool:
        """Whether the declared review interval has elapsed. Pure derivation."""

        return is_review_due(
            review_cadence=self.review_cadence,
            last_reviewed_at=self.last_reviewed_at,
            archived=self.status is DomainStatus.ARCHIVED,
            now=now,
        )

    def update(
        self,
        *,
        now: datetime,
        name: str | UnsetType = UNSET,
        description: str | UnsetType | None = UNSET,
        status: DomainStatus | UnsetType = UNSET,
        review_cadence: Cadence | UnsetType | None = UNSET,
        last_reviewed_at: datetime | UnsetType | None = UNSET,
        accent: str | UnsetType | None = UNSET,
    ) -> "Domain":
        changes = {
            key: value
            for key, value in {
                "name": name,
                "description": description,
                "status": status,
                "review_cadence": review_cadence,
                "last_reviewed_at": last_reviewed_at,
                "accent": accent,
            }.items()
            if value is not UNSET
        }
        if not changes:
            raise ValidationError("at least one domain change is required")
        return replace(self, **changes, updated_at=now, version=self.version + 1)


@dataclass(frozen=True, slots=True)
class Process:
    id: UUID
    owner_id: UUID
    domain_id: UUID
    name: str
    description: str | None
    status: ProcessStatus
    created_at: datetime
    updated_at: datetime
    version: int = 1
    cadence: Cadence | None = None
    next_expected_run_at: datetime | None = None
    """Server-owned next run marker; it is advanced only when a run is materialized."""

    def __post_init__(self) -> None:
        name = self.name.strip()
        if not name or len(name) > 200:
            raise ValidationError("process name must contain 1-200 characters")
        if self.description is not None and len(self.description) > 10_000:
            raise ValidationError("process description is too long")
        if self.version < 1:
            raise ValidationError("process version must be positive")
        object.__setattr__(self, "name", name)

    def update(
        self,
        *,
        now: datetime,
        name: str | UnsetType = UNSET,
        description: str | UnsetType | None = UNSET,
        status: ProcessStatus | UnsetType = UNSET,
        domain_id: UUID | UnsetType = UNSET,
        cadence: Cadence | UnsetType | None = UNSET,
        next_expected_run_at: datetime | UnsetType | None = UNSET,
    ) -> "Process":
        changes = {
            key: value
            for key, value in {
                "name": name,
                "description": description,
                "status": status,
                "domain_id": domain_id,
                "cadence": cadence,
                "next_expected_run_at": next_expected_run_at,
            }.items()
            if value is not UNSET
        }
        if not changes:
            raise ValidationError("at least one process change is required")
        return replace(self, **changes, updated_at=now, version=self.version + 1)
