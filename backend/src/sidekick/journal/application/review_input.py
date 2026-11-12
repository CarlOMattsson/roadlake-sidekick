"""Closed, non-strict input models shared by the HTTP and MCP Journal draft review commands.

The domain's Task proposals are `strict=True` because they validate untrusted model output;
a JSON request body would be refused by them, so both transports accept these equivalent
shapes and convert them explicitly. They live here, in neither transport, so FastAPI and
FastMCP parse a review decision identically.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sidekick.journal.domain.analysis import (
    CreateTaskProposal,
    TaskPriority,
    TaskStatus,
    UpdateTaskProposal,
)
from sidekick.journal.domain.source import require_aware


class ReviewInputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RelationOrigin(StrEnum):
    MODEL_SUGGESTED = "model_suggested"
    USER_SELECTED = "user_selected"


class RelationSelectionItem(ReviewInputModel):
    id: UUID
    origin: RelationOrigin


RelationItems = Annotated[list[RelationSelectionItem], Field(max_length=25)]


class RelationSelection(ReviewInputModel):
    project_ids: RelationItems
    task_ids: RelationItems
    contact_ids: RelationItems

    @field_validator("project_ids", "task_ids", "contact_ids")
    @classmethod
    def relation_ids_must_be_unique(
        cls, values: list[RelationSelectionItem]
    ) -> list[RelationSelectionItem]:
        ids = [item.id for item in values]
        if len(ids) != len(set(ids)):
            raise ValueError("relation identifiers must be unique")
        return values


class CreateTaskProposalInput(ReviewInputModel):
    """The HTTP shape of a create-Task proposal decision.

    `sidekick.journal.domain.analysis.CreateTaskProposal` is `strict=True` on purpose: it
    validates untrusted AI model output, where a wrong type must never be silently coerced.
    FastAPI parses a JSON request body into a plain Python dict before that model ever sees
    it, so strict mode then refuses to coerce a JSON string into `UUID` or an enum — the
    exact values every JSON body contains. Reusing the domain's strict model here as the
    request schema meant finalize could never succeed over real HTTP with a task proposal
    attached; only calling the application service directly with real Python objects, as
    every existing test did, worked. This class is the same non-strict shape and converts
    to the strict one explicitly.
    """

    proposal_id: UUID
    type: Literal["create_task"]
    title: Annotated[str, Field(min_length=1, max_length=200)]
    description: Annotated[str, Field(max_length=10_000)] | None
    project_id: UUID | None
    priority: TaskPriority
    due_at: datetime | None
    contact_ids: Annotated[list[UUID], Field(max_length=25)]

    @field_validator("due_at")
    @classmethod
    def due_at_must_be_aware(cls, value: datetime | None) -> datetime | None:
        require_aware(value, "due_at")
        return value

    @field_validator("contact_ids")
    @classmethod
    def contact_ids_must_be_unique(cls, values: list[UUID]) -> list[UUID]:
        if len(values) != len(set(values)):
            raise ValueError("contact_ids must be unique")
        return values

    def to_domain(self) -> CreateTaskProposal:
        return CreateTaskProposal(
            proposal_id=self.proposal_id,
            type=self.type,
            title=self.title,
            description=self.description,
            project_id=self.project_id,
            priority=self.priority,
            due_at=self.due_at,
            contact_ids=self.contact_ids,
        )


class UpdateTaskProposalInput(ReviewInputModel):
    """The HTTP shape of an update-Task proposal decision. See `CreateTaskProposalInput`."""

    proposal_id: UUID
    type: Literal["update_task"]
    task_id: UUID
    expected_task_version: Annotated[int, Field(ge=1)]
    project_id: UUID | None = None
    title: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    description: Annotated[str, Field(max_length=10_000)] | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    due_at: datetime | None = None

    @field_validator("due_at")
    @classmethod
    def due_at_must_be_aware(cls, value: datetime | None) -> datetime | None:
        require_aware(value, "due_at")
        return value

    @model_validator(mode="after")
    def require_explicit_update(self) -> UpdateTaskProposalInput:
        mutable_fields = {"project_id", "title", "description", "status", "priority", "due_at"}
        supplied_fields = self.model_fields_set & mutable_fields
        if not supplied_fields:
            raise ValueError("at least one mutable Task field must be supplied")
        for field_name in ("title", "status", "priority"):
            if field_name in supplied_fields and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self

    def to_domain(self) -> UpdateTaskProposal:
        fields: dict[str, object] = {
            "proposal_id": self.proposal_id,
            "type": self.type,
            "task_id": self.task_id,
            "expected_task_version": self.expected_task_version,
        }
        for name in ("project_id", "title", "description", "status", "priority", "due_at"):
            if name in self.model_fields_set:
                fields[name] = getattr(self, name)
        return UpdateTaskProposal.model_validate(fields)


TaskProposalInput = Annotated[
    CreateTaskProposalInput | UpdateTaskProposalInput,
    Field(discriminator="type"),
]
