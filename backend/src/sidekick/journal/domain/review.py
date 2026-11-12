"""Journal draft review records: the closed candidate catalog, processing runs and the draft."""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from .analysis import (
    ContactSuggestion,
    CreateTaskProposal,
    DraftState,
    KeyPoint,
    ProjectSuggestion,
    StrictModel,
    TaskSuggestion,
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


@dataclass(frozen=True, slots=True)
class SuggestionLink:
    """One model-suggested link; the rationale is model text and follows `include_content`."""

    id: UUID
    rationale: str | None


@dataclass(frozen=True, slots=True)
class ScopedDraft:
    """A draft as one caller may read it: what the caller's scopes and `include_content` leave.

    `draft` is the whole record (identity, source, run and version are not scope-limited); the
    other fields replace the draft's own, limited ones. `task_proposal_count` is the draft's real
    count even when some proposals are withheld.
    """

    draft: DraftReview
    summary: str | None
    key_points: tuple[KeyPoint, ...]
    project_suggestions: tuple[SuggestionLink, ...]
    task_suggestions: tuple[SuggestionLink, ...]
    contact_suggestions: tuple[SuggestionLink, ...]
    task_proposals: tuple[CreateTaskProposal | UpdateTaskProposal, ...]
    task_proposal_count: int
    catalog: CandidateCatalog


def _proposal_visible(
    proposal: CreateTaskProposal | UpdateTaskProposal, scopes: frozenset[str]
) -> bool:
    """A Task proposal names Tasks, Projects or Contacts, so it needs those read scopes."""

    needed: set[str] = set()
    if isinstance(proposal, UpdateTaskProposal):
        needed.add("tasks:read")
        if "project_id" in proposal.model_fields_set and proposal.project_id is not None:
            needed.add("projects:read")
    else:
        if proposal.project_id is not None:
            needed.add("projects:read")
        if proposal.contact_ids:
            needed.add("contacts:read")
    return needed <= scopes


def _suggestion_links(
    items: tuple[dict[str, Any], ...],
    model: type[BaseModel],
    id_field: str,
    *,
    scope: str,
    scopes: frozenset[str],
    include_content: bool,
) -> tuple[SuggestionLink, ...]:
    if scope not in scopes:
        return ()
    links: list[SuggestionLink] = []
    for item in items:
        # The stored items hold JSON values (identifiers as text), which the strict models only
        # accept in JSON mode; `strict=False` reads them the same way.
        fields = model.model_validate(item, strict=False).model_dump()
        links.append(
            SuggestionLink(fields[id_field], fields["rationale"] if include_content else None)
        )
    return tuple(links)


def scope_draft(
    draft: DraftReview, scopes: frozenset[str], *, include_content: bool
) -> ScopedDraft:
    """Limit a draft to what the caller may read.

    The title, state, run and version are always shown. Owner text (summary, key points,
    rationales, Task proposals, candidate labels) is left out when `include_content` is false.
    The catalogue, suggestions and Task proposals describe Projects, Tasks and Contacts, which
    `journal:read` alone does not cover, so each also needs the matching read scope.
    """

    def suggestions(
        items: tuple[dict[str, Any], ...], model: type[BaseModel], id_field: str, scope: str
    ) -> tuple[SuggestionLink, ...]:
        return _suggestion_links(
            items,
            model,
            id_field,
            scope=scope,
            scopes=scopes,
            include_content=include_content,
        )

    if include_content:
        catalog = CandidateCatalog(
            projects=draft.catalog.projects if "projects:read" in scopes else [],
            tasks=draft.catalog.tasks if "tasks:read" in scopes else [],
            contacts=draft.catalog.contacts if "contacts:read" in scopes else [],
        )
        proposals = tuple(p for p in draft.task_proposals if _proposal_visible(p, scopes))
    else:
        catalog = CandidateCatalog(projects=[], tasks=[], contacts=[])
        proposals = ()
    return ScopedDraft(
        draft=draft,
        summary=draft.summary if include_content else None,
        key_points=draft.key_points if include_content else (),
        project_suggestions=suggestions(
            draft.project_suggestions, ProjectSuggestion, "project_id", "projects:read"
        ),
        task_suggestions=suggestions(
            draft.task_suggestions, TaskSuggestion, "task_id", "tasks:read"
        ),
        contact_suggestions=suggestions(
            draft.contact_suggestions, ContactSuggestion, "contact_id", "contacts:read"
        ),
        task_proposals=proposals,
        task_proposal_count=len(draft.task_proposals),
        catalog=catalog,
    )
