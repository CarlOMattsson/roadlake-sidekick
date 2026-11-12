"""Row to domain mappers for journal sources, entries, runs, summaries and drafts."""

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from sidekick.journal.domain.analysis import (
    CreateTaskProposal,
    DraftState,
    UpdateTaskProposal,
)
from sidekick.journal.domain.analysis import (
    KeyPoint as AnalysisKeyPoint,
)
from sidekick.journal.domain.entry import JournalEntry, KeyPoint, KeyPointKind
from sidekick.journal.domain.review import (
    CandidateCatalog,
    DraftReview,
    FailureCategory,
    ProcessingRun,
    ProcessingStatus,
)
from sidekick.journal.domain.source import JournalSource, SourceType
from sidekick.journal.domain.summary import (
    DailySummary,
    SummaryContent,
    SummaryOrigin,
    SummaryState,
)
from sidekick.shared.errors import (
    NotFoundError,
)
from sidekick.shared.persistence.models import (
    DailyJournalSummaryEntryRow,
    DailyJournalSummaryRow,
    JournalDraftRow,
    JournalEntryRow,
    JournalProcessingRunRow,
    JournalSourceRow,
)


def journal_source_from_row(row: JournalSourceRow) -> JournalSource:
    return JournalSource(
        id=row.id,
        owner_id=row.owner_id,
        source_type=SourceType(row.source_type),
        journal_date=row.journal_date,
        occurred_at=row.occurred_at,
        source_recorded_at=row.source_recorded_at,
        raw_text=row.raw_text,
        language=row.language,
        replaces_source_id=row.replaces_source_id,
        created_at=row.created_at,
    )


def journal_entry_from_row(row: JournalEntryRow) -> JournalEntry:
    return JournalEntry(
        id=row.id,
        owner_id=row.owner_id,
        source_id=row.source_id,
        journal_date=row.journal_date,
        occurred_at=row.occurred_at,
        source_recorded_at=row.source.source_recorded_at,
        title=row.title,
        summary=row.summary,
        key_points=tuple(
            KeyPoint(kind=KeyPointKind(point["kind"]), text=point["text"])
            for point in row.key_points
        ),
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
        archived_at=row.archived_at,
    )


def processing_run_from_row(row: JournalProcessingRunRow) -> ProcessingRun:
    return ProcessingRun(
        id=row.id,
        owner_id=row.owner_id,
        source_id=row.source_id,
        operation=("entry_draft" if row.operation == "entry_draft" else "daily_summary"),
        journal_date=row.journal_date,
        status=ProcessingStatus(row.status),
        provider=row.provider,
        model_id=row.model_id,
        prompt_version=row.prompt_version,
        schema_version=row.schema_version,
        input_fingerprint=row.input_fingerprint,
        candidate_catalog=CandidateCatalog.model_validate_json(json.dumps(row.candidate_catalog)),
        provider_response_id=row.provider_response_id,
        failure_category=(FailureCategory(row.failure_category) if row.failure_category else None),
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        started_at=row.started_at,
        finished_at=row.finished_at,
        lease_expires_at=row.lease_expires_at,
        attempt_count=row.attempt_count,
        created_at=row.created_at,
    )


def daily_summary_from_row(session: Session, row: DailyJournalSummaryRow) -> DailySummary:
    provenance = list(
        session.scalars(
            select(DailyJournalSummaryEntryRow)
            .where(
                DailyJournalSummaryEntryRow.owner_id == row.owner_id,
                DailyJournalSummaryEntryRow.summary_id == row.id,
            )
            .order_by(DailyJournalSummaryEntryRow.ordinal.asc())
        )
    )
    return DailySummary(
        id=row.id,
        owner_id=row.owner_id,
        journal_date=row.journal_date,
        origin=SummaryOrigin(row.origin),
        state=SummaryState(row.status),
        content=SummaryContent.model_validate_json(json.dumps(row.content)),
        entry_ids=tuple(item.entry_id for item in provenance),
        source_fingerprint=row.source_fingerprint,
        version=row.version,
        changed_entry_count=0,
    )


def draft_review_from_row(session: Session, row: JournalDraftRow) -> DraftReview:
    if "source" not in row.__dict__:
        session.refresh(row, attribute_names=["source"])
    run = session.scalar(
        select(JournalProcessingRunRow).where(
            JournalProcessingRunRow.id == row.catalog_run_id,
            JournalProcessingRunRow.owner_id == row.owner_id,
        )
    )
    if run is None:
        raise NotFoundError("journal processing run not found")
    suggestions = row.relation_suggestions
    task_proposals: list[CreateTaskProposal | UpdateTaskProposal] = []
    for proposal in row.task_proposals:
        if proposal.get("type") == "create_task":
            task_proposals.append(CreateTaskProposal.model_validate_json(json.dumps(proposal)))
        else:
            task_proposals.append(UpdateTaskProposal.model_validate_json(json.dumps(proposal)))
    return DraftReview(
        id=row.id,
        owner_id=row.owner_id,
        source=journal_source_from_row(row.source),
        state=DraftState(row.state),
        title=row.title,
        summary=row.summary,
        key_points=tuple(
            AnalysisKeyPoint.model_validate_json(json.dumps(point)) for point in row.key_points
        ),
        project_suggestions=tuple(suggestions.get("projects", [])),
        task_suggestions=tuple(suggestions.get("tasks", [])),
        contact_suggestions=tuple(suggestions.get("contacts", [])),
        task_proposals=tuple(task_proposals),
        catalog=CandidateCatalog.model_validate_json(json.dumps(run.candidate_catalog)),
        run=processing_run_from_row(run),
        version=row.version,
    )
