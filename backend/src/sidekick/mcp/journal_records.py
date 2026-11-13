"""Result models and record mappers of the Journal tools."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from sidekick.journal.application.review_input import TaskProposalInput
from sidekick.journal.domain.analysis import (
    CreateTaskProposal,
    UpdateTaskProposal,
)
from sidekick.journal.domain.records import PendingJournalItem
from sidekick.journal.domain.review import (
    CandidateCatalog,
    DraftReview,
    FailureCategory,
    ProcessingStatus,
    ScopedDraft,
    SuggestionLink,
)
from sidekick.journal.domain.source import SourceType
from sidekick.structured.base import Output
from sidekick.structured.journal import (
    JournalEntryRecord,
    JournalKeyPoint,
    JournalKeyPointInput,
    JournalSourceReadRecord,
    JournalSourceRecord,
    JournalSummaryRecord,
)


class JournalSourceResult(Output):
    source: JournalSourceRecord


class PendingJournalItemRecord(Output):
    source_id: UUID
    journal_date: date
    source_type: SourceType
    source_created_at: datetime
    character_count: Annotated[int, Field(ge=1, le=100_000)]
    state: Literal["source_saved", "draft_pending_review"]
    draft_id: UUID | None
    draft_title: Annotated[str, Field(min_length=1, max_length=200)] | None


class PendingJournalPageResult(Output):
    items: Annotated[list[PendingJournalItemRecord], Field(max_length=100)]


class JournalSummaryResult(Output):
    summary: JournalSummaryRecord


class JournalDraftSuggestion(Output):
    """One model-suggested link; the rationale is model text and follows `include_content`."""

    id: UUID
    rationale: Annotated[str, Field(min_length=1, max_length=1_000)] | None


class JournalDraftSuggestions(Output):
    projects: Annotated[list[JournalDraftSuggestion], Field(max_length=25)]
    tasks: Annotated[list[JournalDraftSuggestion], Field(max_length=25)]
    contacts: Annotated[list[JournalDraftSuggestion], Field(max_length=25)]


class JournalDraftRunRecord(Output):
    """Which model produced the draft; never the prompt, the response or any credential."""

    status: ProcessingStatus
    provider: Annotated[str, Field(min_length=1, max_length=64)]
    model_id: Annotated[str, Field(min_length=1, max_length=200)]
    prompt_version: Annotated[str, Field(min_length=1, max_length=64)]
    schema_version: Annotated[str, Field(min_length=1, max_length=64)]
    failure_category: FailureCategory | None


class JournalDraftRecord(Output):
    """An AI-derived draft awaiting the owner's review. It carries no source text."""

    id: UUID
    source_id: UUID
    journal_date: date
    state: Literal["pending_review", "finalized", "rejected", "superseded"]
    title: Annotated[str, Field(min_length=1, max_length=200)]
    summary: Annotated[str, Field(max_length=10_000)] | None
    key_points: Annotated[list[JournalKeyPoint], Field(max_length=50)]
    suggestions: JournalDraftSuggestions
    task_proposals: Annotated[list[CreateTaskProposal | UpdateTaskProposal], Field(max_length=20)]
    task_proposal_count: Annotated[int, Field(ge=0, le=20)]
    catalog: CandidateCatalog
    run: JournalDraftRunRecord
    version: Annotated[int, Field(ge=1)]


class JournalDraftStatusRecord(Output):
    """The outcome of an edit or rejection: identity, state and the version to use next.

    It echoes no draft text; read the draft with `get_journal_draft` to see its content.
    """

    id: UUID
    source_id: UUID
    state: Literal["pending_review", "finalized", "rejected", "superseded"]
    title: Annotated[str, Field(min_length=1, max_length=200)]
    task_proposal_count: Annotated[int, Field(ge=0, le=20)]
    version: Annotated[int, Field(ge=1)]


class JournalDraftStatusResult(Output):
    draft: JournalDraftStatusRecord


class JournalDraftReadResult(Output):
    """The draft and its source; `raw_text` is present unless include_content is false."""

    draft: JournalDraftRecord
    source: JournalSourceReadRecord


class JournalFinalizeResult(Output):
    entry: JournalEntryRecord
    created_task_ids: Annotated[list[UUID], Field(max_length=20)]
    updated_task_ids: Annotated[list[UUID], Field(max_length=20)]


def pending_record(item: PendingJournalItem) -> PendingJournalItemRecord:
    return PendingJournalItemRecord(
        source_id=item.source_id,
        journal_date=item.journal_date,
        source_type=item.source_type,
        source_created_at=item.source_created_at,
        character_count=item.character_count,
        state="draft_pending_review" if item.draft_id is not None else "source_saved",
        draft_id=item.draft_id,
        draft_title=item.draft_title,
    )


def _suggestions(links: tuple[SuggestionLink, ...]) -> list[JournalDraftSuggestion]:
    return [JournalDraftSuggestion(id=link.id, rationale=link.rationale) for link in links]


def draft_record(scoped: ScopedDraft) -> JournalDraftRecord:
    """Map a draft the use case has already limited to the caller's scopes."""

    draft = scoped.draft
    return JournalDraftRecord(
        id=draft.id,
        source_id=draft.source.id,
        journal_date=draft.source.journal_date,
        state=draft.state.value,
        title=draft.title,
        summary=scoped.summary,
        key_points=[
            JournalKeyPoint(kind=point.kind, text=point.text) for point in scoped.key_points
        ],
        suggestions=JournalDraftSuggestions(
            projects=_suggestions(scoped.project_suggestions),
            tasks=_suggestions(scoped.task_suggestions),
            contacts=_suggestions(scoped.contact_suggestions),
        ),
        task_proposals=list(scoped.task_proposals),
        task_proposal_count=scoped.task_proposal_count,
        catalog=scoped.catalog,
        run=JournalDraftRunRecord(
            status=draft.run.status,
            provider=draft.run.provider,
            model_id=draft.run.model_id,
            prompt_version=draft.run.prompt_version,
            schema_version=draft.run.schema_version,
            failure_category=draft.run.failure_category,
        ),
        version=draft.version,
    )


def draft_status(draft: DraftReview) -> JournalDraftStatusResult:
    return JournalDraftStatusResult(
        draft=JournalDraftStatusRecord(
            id=draft.id,
            source_id=draft.source.id,
            state=draft.state.value,
            title=draft.title,
            task_proposal_count=len(draft.task_proposals),
            version=draft.version,
        )
    )


def draft_dump(record: BaseModel) -> dict[str, Any]:
    """Serialize a draft read keeping which Task-proposal fields the model actually set.

    An update proposal distinguishes an omitted field from an explicit null, and the review
    writes the proposal back unchanged, so unset fields must stay absent from the output.
    """

    return record.model_dump(mode="json", exclude_unset=True)


# Parameter types shared by several tools; the JSON schema each produces is pinned by the contract.
VersionParam = Annotated[int, Field(ge=1)]
TitleParam = Annotated[str, Field(min_length=1, max_length=200)]
KeyPointInputs = Annotated[list[JournalKeyPointInput], Field(max_length=50)]
TaskProposals = Annotated[list[TaskProposalInput], Field(max_length=20)]
RelationIds = Annotated[list[UUID], Field(max_length=25, json_schema_extra={"uniqueItems": True})]
