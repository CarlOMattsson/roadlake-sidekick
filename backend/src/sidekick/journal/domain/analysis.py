"""Closed strict models for untrusted Journal analysis payloads."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from .source import require_aware

NonBlank200 = Annotated[str, StringConstraints(min_length=1, max_length=200)]
NonBlank1000 = Annotated[str, StringConstraints(min_length=1, max_length=1_000)]
NonBlank2000 = Annotated[str, StringConstraints(min_length=1, max_length=2_000)]
OptionalText10000 = Annotated[str, StringConstraints(max_length=10_000)] | None
OverviewText = Annotated[str, StringConstraints(min_length=1, max_length=20_000)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class KeyPointKind(StrEnum):
    FACT = "fact"
    REFLECTION = "reflection"
    DECISION = "decision"
    COMMITMENT = "commitment"
    QUESTION = "question"


class TaskPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class TaskStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"


class Perspective(StrEnum):
    FACT = "fact"
    INTERPRETATION = "interpretation"
    PLAN = "plan"


class ContradictionStatus(StrEnum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    POSSIBLY_SUPERSEDED = "possibly_superseded"


class DraftState(StrEnum):
    PENDING_REVIEW = "pending_review"
    FINALIZED = "finalized"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


PENDING_REVIEW = DraftState.PENDING_REVIEW


def _unique_uuids(values: list[UUID]) -> list[UUID]:
    if len(values) != len(set(values)):
        raise ValueError("identifiers must be unique")
    return values


EntryIdList = Annotated[
    list[UUID],
    Field(max_length=10, json_schema_extra={"uniqueItems": True}),
    AfterValidator(_unique_uuids),
]
ContradictionEntryIdList = Annotated[
    list[UUID],
    Field(min_length=2, max_length=10, json_schema_extra={"uniqueItems": True}),
    AfterValidator(_unique_uuids),
]
ContactIdList = Annotated[
    list[UUID],
    Field(max_length=25, json_schema_extra={"uniqueItems": True}),
    AfterValidator(_unique_uuids),
]


class KeyPoint(StrictModel):
    kind: KeyPointKind
    text: NonBlank2000


class ProjectSuggestion(StrictModel):
    project_id: UUID
    rationale: NonBlank1000


class TaskSuggestion(StrictModel):
    task_id: UUID
    rationale: NonBlank1000


class ContactSuggestion(StrictModel):
    contact_id: UUID
    rationale: NonBlank1000


class CreateTaskProposal(StrictModel):
    proposal_id: UUID
    type: Literal["create_task"]
    title: NonBlank200
    description: OptionalText10000
    project_id: UUID | None
    priority: TaskPriority
    due_at: datetime | None
    contact_ids: ContactIdList

    @field_validator("due_at")
    @classmethod
    def due_at_must_be_aware(cls, value: datetime | None) -> datetime | None:
        require_aware(value, "due_at")
        return value


def _update_task_json_schema(schema: dict[str, Any]) -> None:
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        raise TypeError("UpdateTaskProposal schema properties are missing")
    properties["title"] = {"type": "string", "minLength": 1, "maxLength": 200}
    properties["status"] = {
        "type": "string",
        "enum": ["todo", "in_progress", "blocked", "completed"],
    }
    properties["priority"] = {
        "type": "string",
        "enum": ["low", "normal", "high", "urgent"],
    }
    mutable_fields = ("project_id", "title", "description", "status", "priority", "due_at")
    common_required = ["proposal_id", "type", "task_id", "expected_task_version"]
    title = schema.get("title", "UpdateTaskProposal")
    description = (
        "Each closed branch requires one mutable field so generated clients preserve "
        "omission versus explicit null without widening the proposal to unknown."
    )
    schema.clear()
    schema.update(
        {
            "title": title,
            "description": description,
            "anyOf": [
                {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": properties,
                    "required": [*common_required, field_name],
                }
                for field_name in mutable_fields
            ],
        }
    )


class UpdateTaskProposal(StrictModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        json_schema_extra=_update_task_json_schema,
    )

    proposal_id: UUID
    type: Literal["update_task"]
    task_id: UUID
    expected_task_version: Annotated[int, Field(ge=1)]
    project_id: UUID | None = None
    title: NonBlank200 | None = None
    description: OptionalText10000 = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    due_at: datetime | None = None

    @model_validator(mode="after")
    def require_explicit_update(self) -> "UpdateTaskProposal":
        mutable_fields = {
            "project_id",
            "title",
            "description",
            "status",
            "priority",
            "due_at",
        }
        supplied_fields = self.model_fields_set & mutable_fields
        if not supplied_fields:
            raise ValueError("at least one mutable Task field must be supplied")
        for field_name in ("title", "status", "priority"):
            if field_name in supplied_fields and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        require_aware(self.due_at, "due_at")
        return self


type TaskProposal = Annotated[
    CreateTaskProposal | UpdateTaskProposal,
    Field(discriminator="type"),
]


class SummaryTheme(StrictModel):
    title: NonBlank200
    summary: NonBlank2000
    perspective: Perspective
    entry_ids: EntryIdList


class SummaryStatement(StrictModel):
    text: NonBlank2000
    perspective: Perspective
    entry_ids: EntryIdList


class SummaryContradiction(StrictModel):
    description: NonBlank2000
    status: ContradictionStatus
    resolution: Annotated[str, StringConstraints(max_length=2_000)] | None
    entry_ids: ContradictionEntryIdList


class DailySummaryAnalysis(StrictModel):
    kind: Literal["daily_summary"]
    overview: OverviewText
    overview_entry_ids: EntryIdList
    themes: Annotated[list[SummaryTheme], Field(max_length=50)]
    important_events: Annotated[list[SummaryStatement], Field(max_length=50)]
    decisions: Annotated[list[SummaryStatement], Field(max_length=50)]
    commitments: Annotated[list[SummaryStatement], Field(max_length=50)]
    open_questions: Annotated[list[SummaryStatement], Field(max_length=50)]
    unresolved_items: Annotated[list[SummaryStatement], Field(max_length=50)]
    contradictions: Annotated[list[SummaryContradiction], Field(max_length=25)]
