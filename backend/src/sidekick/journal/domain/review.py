"""Journal draft review records: the closed candidate catalog, processing runs and the draft."""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from .analysis import (
    CreateTaskProposal,
    DraftState,
    KeyPoint,
    StrictModel,
    UpdateTaskProposal,
)
from .source import JournalSource

MAX_PROJECT_CANDIDATES = 50
MAX_TASK_CANDIDATES = 100
MAX_CONTACT_CANDIDATES = 50


class ProjectCandidate(StrictModel):
    id: UUID
    kind: Literal["project"] = "project"
    label: str = Field(min_length=1, max_length=200)
    status: Literal["active", "paused"]
    version: int | None = Field(default=None, ge=1)
    context: str | None = Field(default=None, max_length=240)


class TaskCandidate(StrictModel):
    id: UUID
    kind: Literal["task"] = "task"
    label: str = Field(min_length=1, max_length=200)
    status: Literal["todo", "in_progress", "blocked"]
    version: int = Field(ge=1)
    context: str | None = Field(default=None, max_length=240)


class ContactCandidate(StrictModel):
    id: UUID
    kind: Literal["contact"] = "contact"
    label: str = Field(min_length=1, max_length=200)
    status: Literal["active"] = "active"
    version: int | None = Field(default=None, ge=1)
    context: str | None = Field(default=None, max_length=240)


class CandidateCatalog(StrictModel):
    projects: list[ProjectCandidate] = Field(max_length=MAX_PROJECT_CANDIDATES)
    tasks: list[TaskCandidate] = Field(max_length=MAX_TASK_CANDIDATES)
    contacts: list[ContactCandidate] = Field(max_length=MAX_CONTACT_CANDIDATES)


class FailureCategory(StrEnum):
    PROVIDER_CONFIGURATION = "provider_configuration"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    MODEL_UNAVAILABLE = "model_unavailable"
    INVALID_PROVIDER_RESPONSE = "invalid_provider_response"
    INVALID_MODEL_OUTPUT = "invalid_model_output"


class ProcessingStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ProcessingRun:
    id: UUID
    owner_id: UUID
    source_id: UUID | None
    operation: Literal["entry_draft", "daily_summary"]
    journal_date: date
    status: ProcessingStatus
    provider: str
    model_id: str
    prompt_version: str
    schema_version: str
    input_fingerprint: str
    candidate_catalog: CandidateCatalog
    provider_response_id: str | None
    failure_category: FailureCategory | None
    input_tokens: int | None
    output_tokens: int | None
    started_at: datetime | None
    finished_at: datetime | None
    lease_expires_at: datetime | None
    attempt_count: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DraftReview:
    id: UUID
    owner_id: UUID
    source: JournalSource
    state: DraftState
    title: str
    summary: str | None
    key_points: tuple[KeyPoint, ...]
    project_suggestions: tuple[dict[str, Any], ...]
    task_suggestions: tuple[dict[str, Any], ...]
    contact_suggestions: tuple[dict[str, Any], ...]
    task_proposals: tuple[CreateTaskProposal | UpdateTaskProposal, ...]
    catalog: CandidateCatalog
    run: ProcessingRun
    version: int
