"""The Journal draft review tools: read, edit, reject and finalize an AI-derived draft."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated
from uuid import UUID

from fastmcp import FastMCP
from fastmcp.apps import AppConfig
from fastmcp.tools import ToolResult
from pydantic import Field

from sidekick.journal.application.review_input import (
    RelationSelection,
    RelationSelectionItem,
    TaskProposalInput,
)
from sidekick.journal.domain.analysis import KeyPoint as AnalysisKeyPoint
from sidekick.journal.domain.finalize import FinalizeCommand
from sidekick.journal.domain.records import EntryRelations
from sidekick.mcp.annotations import DESTRUCTIVE, READ, WRITE
from sidekick.mcp.correlation import request_correlation_id_or_new
from sidekick.mcp.idempotency import IdempotencyKey
from sidekick.mcp.journal_records import (
    JournalDraftReadResult,
    JournalDraftStatusResult,
    JournalFinalizeResult,
    KeyPointInputs,
    TaskProposals,
    TitleParam,
    VersionParam,
    draft_dump,
    draft_record,
    draft_status,
)
from sidekick.mcp.journal_text import DRAFT_STATE_WORDS, SPOKEN_TITLE_LIMIT, JournalToolContext
from sidekick.mcp.results import output_schema, result
from sidekick.mcp.sidekick_app import SIDEKICK_APP_URI
from sidekick.mcp.text import flat, rows_text
from sidekick.structured.journal import (
    JournalKeyPointInput,
    labeled_entry_record,
    source_read_record,
)
from sidekick.structured.tags import TagsInput
from sidekick.work.domain.planning import normalize_tag_selection


def _analysis_key_points(points: list[JournalKeyPointInput]) -> tuple[AnalysisKeyPoint, ...]:
    return tuple(AnalysisKeyPoint(kind=point.kind, text=point.text) for point in points)


def _relation_selection(items: Sequence[RelationSelectionItem]) -> tuple[tuple[UUID, str], ...]:
    """The reviewed relation ids with their origin, in the shape the finalize use case takes."""

    return tuple((item.id, item.origin.value) for item in items)


def _finalize_command(
    *,
    draft_id: UUID,
    expected_version: int,
    title: str,
    summary: str | None,
    key_points: list[JournalKeyPointInput],
    relation_selection: RelationSelection,
    task_proposals: list[TaskProposalInput],
    tags: Sequence[str] | None = None,
) -> FinalizeCommand:
    return FinalizeCommand(
        draft_id=draft_id,
        expected_version=expected_version,
        title=title,
        summary=summary,
        key_points=_analysis_key_points(key_points),
        relation_selection={
            "projects": _relation_selection(relation_selection.project_ids),
            "tasks": _relation_selection(relation_selection.task_ids),
            "contacts": _relation_selection(relation_selection.contact_ids),
        },
        task_proposals=tuple(proposal.to_domain() for proposal in task_proposals),
        tags=tuple(tags or ()),
    )


def _register_get_journal_draft(mcp: FastMCP, ctx: JournalToolContext) -> None:
    @mcp.tool(
        name="get_journal_draft",
        description=(
            "Use this only when the user wants to review one known owned AI-derived journal "
            "draft UUID. The title, state and version are always returned; the summary, key "
            "points, rationales, Task proposals, candidate labels and source text unless "
            "include_content is false, and Project, Task and Contact details only with the "
            "matching read scope. Inaccessible IDs disclose nothing."
        ),
        output_schema=output_schema(JournalDraftReadResult),
        annotations=READ,
        app=AppConfig(resource_uri=SIDEKICK_APP_URI),
    )
    @ctx.instrument("get_journal_draft")
    def get_journal_draft(
        draft_id: UUID,
        include_content: bool = True,
    ) -> ToolResult:
        actor = ctx.actor_provider()
        scoped = ctx.container.journal_analysis.read_draft(
            actor, draft_id, include_content=include_content
        )
        read = JournalDraftReadResult(
            draft=draft_record(scoped),
            source=source_read_record(scoped.draft.source, include_content=include_content),
        )
        record = read.draft
        title = flat(record.title, SPOKEN_TITLE_LIMIT)
        day = ctx.spoken_day(read.source.journal_date)
        state = DRAFT_STATE_WORDS[record.state]
        return result(
            draft_dump(read),
            rows_text(
                f'The journal draft "{title}" from {day}, {state}.',
                [f"Draft {record.id} v{record.version}."],
            ),
        )


def _register_update_journal_draft(mcp: FastMCP, ctx: JournalToolContext) -> None:
    @mcp.tool(
        name="update_journal_draft",
        description=(
            "Use this only when the user asks to edit one pending journal draft. It replaces "
            "the draft's title, summary, key points and Task proposals using the draft's current "
            "version, creates no entry and changes no Task, and returns only the draft's state and "
            "next version. A stale version or a draft that is no longer pending conflicts."
        ),
        output_schema=output_schema(JournalDraftStatusResult),
        # Not destructive: it edits a disposable proposal that is still pending, creates no
        # entry and changes no Task; only reject and finalize are terminal.
        annotations=WRITE,
        app=AppConfig(visibility=["app"]),
    )
    @ctx.instrument("update_journal_draft")
    def update_journal_draft(
        draft_id: UUID,
        expected_version: VersionParam,
        title: TitleParam,
        summary: Annotated[str, Field(max_length=10_000)] | None,
        key_points: KeyPointInputs,
        task_proposals: TaskProposals,
        idempotency_key: IdempotencyKey,
    ) -> ToolResult:
        # Relation selection is only validated, never stored, on a draft; it is chosen at finalize.
        draft = ctx.container.journal_analysis.update_draft(
            ctx.actor_provider(),
            draft_id=draft_id,
            expected_version=expected_version,
            title=title,
            summary=summary,
            key_points=_analysis_key_points(key_points),
            relation_selection={"projects": (), "tasks": (), "contacts": ()},
            task_proposals=tuple(proposal.to_domain() for proposal in task_proposals),
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        structured = draft_status(draft).model_dump(mode="json")
        return result(structured, "Updated the journal draft.")


# Rejecting discards an AI draft for good, and finalizing consumes it, creates the entry and may
# overwrite fields of existing Tasks. Both are terminal, so a host may ask before running them.


def _register_reject_journal_draft(mcp: FastMCP, ctx: JournalToolContext) -> None:
    @mcp.tool(
        name="reject_journal_draft",
        description=(
            "Use this only when the user explicitly asks to reject one pending journal draft. "
            "Rejecting is terminal: the draft cannot be edited or finalized afterwards, and "
            "its source stays preserved. A stale version or a draft that is no longer pending "
            "conflicts."
        ),
        output_schema=output_schema(JournalDraftStatusResult),
        annotations=DESTRUCTIVE,
        app=AppConfig(visibility=["app"]),
    )
    @ctx.instrument("reject_journal_draft")
    def reject_journal_draft(
        draft_id: UUID,
        expected_version: VersionParam,
        idempotency_key: IdempotencyKey,
    ) -> ToolResult:
        draft = ctx.container.journal_analysis.reject_draft(
            ctx.actor_provider(),
            draft_id=draft_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        structured = draft_status(draft).model_dump(mode="json")
        return result(structured, "Rejected the journal draft.")


def _register_finalize_journal_draft(mcp: FastMCP, ctx: JournalToolContext) -> None:
    @mcp.tool(
        name="finalize_journal_draft",
        description=(
            "Use this only when the user explicitly approves one pending journal draft as "
            "reviewed. It creates the journal entry from the supplied fields, selected "
            "relations and optional tags, and applies only the Task proposals the user kept, "
            "which may create Tasks or change existing ones. It is terminal and invokes no AI. "
            "A stale version or a draft that is no longer pending conflicts."
        ),
        output_schema=output_schema(JournalFinalizeResult),
        annotations=DESTRUCTIVE,
        app=AppConfig(visibility=["app"]),
    )
    @ctx.instrument("finalize_journal_draft")
    def finalize_journal_draft(
        draft_id: UUID,
        expected_version: VersionParam,
        title: TitleParam,
        summary: Annotated[str, Field(max_length=10_000)] | None,
        key_points: KeyPointInputs,
        relation_selection: RelationSelection,
        task_proposals: TaskProposals,
        idempotency_key: IdempotencyKey,
        tags: TagsInput | None = None,
    ) -> ToolResult:
        container = ctx.container
        actor = ctx.actor_provider()
        outcome = container.journal_finalize.finalize(
            actor,
            command=_finalize_command(
                draft_id=draft_id,
                expected_version=expected_version,
                title=title,
                summary=summary,
                key_points=key_points,
                relation_selection=relation_selection,
                task_proposals=task_proposals,
                tags=tags,
            ),
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        relations = EntryRelations(
            project_ids=outcome.project_ids,
            task_ids=outcome.task_ids,
            contact_ids=outcome.contact_ids,
        )
        structured = JournalFinalizeResult(
            entry=labeled_entry_record(
                container,
                actor,
                outcome.entry,
                relations,
                # A write-only caller may not read the entry back: these are the tags just written.
                normalize_tag_selection(list(tags or ())),
                include_content=True,
            ),
            created_task_ids=list(outcome.created_task_ids),
            updated_task_ids=list(outcome.updated_task_ids),
        ).model_dump(mode="json")
        return result(structured, "Finalized the journal draft into a journal entry.")


def register_journal_draft_tools(mcp: FastMCP, ctx: JournalToolContext) -> None:
    """Register the four Journal draft review tools, in the order the list shows them."""

    _register_get_journal_draft(mcp, ctx)
    _register_update_journal_draft(mcp, ctx)
    _register_reject_journal_draft(mcp, ctx)
    _register_finalize_journal_draft(mcp, ctx)
