"""Fifteen curated Journal MCP tools over the authoritative Journal use cases.

Four of them review an AI-derived draft: `get_journal_draft` reads it, and
`update_journal_draft`, `reject_journal_draft` and `finalize_journal_draft` are explicit owner
commands that call the same use cases as the REST routes.
"""

# En dashes are intentional human-facing tool copy preserved by contract snapshots.

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastmcp import FastMCP
from fastmcp.apps import AppConfig
from pydantic import BaseModel, Field

from sidekick.journal.application.review_input import RelationSelection, TaskProposalInput
from sidekick.journal.domain.analysis import (
    ContactSuggestion,
    CreateTaskProposal,
    ProjectSuggestion,
    TaskSuggestion,
    UpdateTaskProposal,
)
from sidekick.journal.domain.analysis import KeyPoint as AnalysisKeyPoint
from sidekick.journal.domain.analysis import KeyPointKind as AnalysisKeyPointKind
from sidekick.journal.domain.day_done import owner_today
from sidekick.journal.domain.entry import KeyPoint, KeyPointKind
from sidekick.journal.domain.finalize import FinalizeCommand
from sidekick.journal.domain.records import DaySummaryStatus, EntryRelations
from sidekick.journal.domain.review import (
    CandidateCatalog,
    DraftReview,
    FailureCategory,
    ProcessingStatus,
)
from sidekick.journal.domain.source import SourceType
from sidekick.journal.domain.summary import SummaryContent
from sidekick.mcp.annotations import DESTRUCTIVE, READ, WRITE
from sidekick.mcp.correlation import request_correlation_id_or_new
from sidekick.mcp.idempotency import IdempotencyKey
from sidekick.mcp.results import output_schema, result
from sidekick.mcp.sidekick_app import SIDEKICK_APP_URI
from sidekick.mcp.text import count_phrase, flat, rows_text, spoken_date, spoken_status
from sidekick.mcp.tool_context import ToolContext
from sidekick.shared.errors import ValidationError
from sidekick.shared.text_guard import NoImageData
from sidekick.shared.types import MAX_CURSOR_LENGTH
from sidekick.structured.base import Output
from sidekick.structured.journal import (
    JournalDayResult,
    JournalEntryPageResult,
    JournalEntryRecord,
    JournalEntryResult,
    JournalKeyPoint,
    JournalKeyPointInput,
    JournalSourceReadRecord,
    JournalSourceReadResult,
    JournalSourceRecord,
    JournalSummaryRecord,
    journal_day_structured,
    journal_entries_structured,
    journal_entry_structured,
    journal_source_structured,
    labeled_entry_record,
    source_read_record,
    source_record,
    summary_record,
    update_journal_entry_structured,
    write_journal_entry_structured,
)

JOURNAL_TOOL_NAMES = (
    "list_journal_entries",
    "get_journal_entry",
    "get_journal_day",
    "get_daily_journal_summary",
    "get_journal_source",
    "list_pending_journal",
    "create_journal_source",
    "create_manual_journal_entry",
    "write_journal_entry",
    "update_journal_entry",
    "set_daily_journal_summary",
    "get_journal_draft",
    "update_journal_draft",
    "reject_journal_draft",
    "finalize_journal_draft",
)
# The review tools are explicit owner commands; a contract test pins their names.
JOURNAL_REVIEW_TOOL_NAMES = (
    "get_journal_draft",
    "update_journal_draft",
    "reject_journal_draft",
    "finalize_journal_draft",
)
# `journal:read` on the draft tools is the reply rule of `sidekick.mcp.reply_scopes`: the answer
# carries the stored draft. The tools that write the owner's own text answer with that text and
# stay write-only on purpose (pinned by tests/mcp/test_journal_writes.py).
JOURNAL_TOOL_SCOPES = {
    "list_journal_entries": {"journal:read"},
    "get_journal_entry": {"journal:read"},
    "get_journal_day": {"journal:read"},
    "get_daily_journal_summary": {"journal:read"},
    "get_journal_source": {"journal:read"},
    "list_pending_journal": {"journal:read"},
    "create_journal_source": {"journal:write"},
    "create_manual_journal_entry": {
        "journal:write",
        "projects:read",
        "tasks:read",
        "contacts:read",
    },
    "write_journal_entry": {
        "journal:write",
        "projects:read",
        "tasks:read",
        "contacts:read",
    },
    # The entry's relations are read back after the write, so the actor needs journal:read too.
    "update_journal_entry": {"journal:read", "journal:write"},
    # put_manual_summary checks journal:write only; the day's entries are read inside the use case.
    "set_daily_journal_summary": {"journal:write"},
    # The Project, Task and Contact scopes only widen what include_content may show of the draft's
    # suggestions, Task proposals and candidate catalogue; journal:read alone still opens it.
    "get_journal_draft": {"journal:read", "projects:read", "tasks:read", "contacts:read"},
    "update_journal_draft": {"journal:read", "journal:write"},
    "reject_journal_draft": {"journal:read", "journal:write"},
    # The Project, Task and Contact scopes are required only when the selected relations or Task
    # proposals name such a record, and `tasks:write` only when a Task proposal is applied; the
    # use case checks them against the actual command.
    "finalize_journal_draft": {
        "journal:read",
        "journal:write",
        "projects:read",
        "tasks:read",
        "contacts:read",
        "tasks:write",
    },
}

# Rejecting discards an AI draft for good, and finalizing consumes it, creates the entry and may
# overwrite fields of existing Tasks. Both are terminal, so a host may ask before running them.


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


def _pending_record(item: Any) -> PendingJournalItemRecord:
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


def _proposal_visible(proposal: CreateTaskProposal | UpdateTaskProposal, scopes: Any) -> bool:
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


def _draft_record(
    draft: DraftReview, *, include_content: bool, scopes: frozenset[str]
) -> JournalDraftRecord:
    """Map a draft; owner text and candidate labels are left out only when include_content is false.

    Content is further limited by the caller's scopes: the catalogue, suggestions and Task
    proposals describe Projects, Tasks and Contacts, which `journal:read` alone does not cover.
    """

    def suggestions(
        items: tuple[dict[str, Any], ...], model: Any, id_field: str, scope: str
    ) -> list[Any]:
        if scope not in scopes:
            return []
        parsed = [model.model_validate_json(json.dumps(item)) for item in items]
        return [
            JournalDraftSuggestion(
                id=getattr(item, id_field),
                rationale=item.rationale if include_content else None,
            )
            for item in parsed
        ]

    return JournalDraftRecord(
        id=draft.id,
        source_id=draft.source.id,
        journal_date=draft.source.journal_date,
        state=draft.state.value,
        title=draft.title,
        summary=draft.summary if include_content else None,
        key_points=[
            JournalKeyPoint(kind=KeyPointKind(point.kind.value), text=point.text)
            for point in draft.key_points
        ]
        if include_content
        else [],
        suggestions=JournalDraftSuggestions(
            projects=suggestions(
                draft.project_suggestions, ProjectSuggestion, "project_id", "projects:read"
            ),
            tasks=suggestions(draft.task_suggestions, TaskSuggestion, "task_id", "tasks:read"),
            contacts=suggestions(
                draft.contact_suggestions, ContactSuggestion, "contact_id", "contacts:read"
            ),
        ),
        # The count is the draft's real count even when some proposals are withheld by scope.
        task_proposals=[
            proposal for proposal in draft.task_proposals if _proposal_visible(proposal, scopes)
        ]
        if include_content
        else [],
        task_proposal_count=len(draft.task_proposals),
        catalog=CandidateCatalog(
            projects=draft.catalog.projects if "projects:read" in scopes else [],
            tasks=draft.catalog.tasks if "tasks:read" in scopes else [],
            contacts=draft.catalog.contacts if "contacts:read" in scopes else [],
        )
        if include_content
        else CandidateCatalog(projects=[], tasks=[], contacts=[]),
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


def _draft_status(draft: DraftReview) -> JournalDraftStatusResult:
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


def _analysis_key_points(points: list[JournalKeyPointInput]) -> tuple[AnalysisKeyPoint, ...]:
    return tuple(
        AnalysisKeyPoint(kind=AnalysisKeyPointKind(point.kind.value), text=point.text)
        for point in points
    )


def _draft_dump(record: BaseModel) -> dict[str, Any]:
    """Serialize a draft read keeping which Task-proposal fields the model actually set.

    An update proposal distinguishes an omitted field from an explicit null, and the review
    writes the proposal back unchanged, so unset fields must stay absent from the output.
    """

    return record.model_dump(mode="json", exclude_unset=True)


# Block 2 of every Journal tool result is the full structuredContent (D-060):
# Claude may read all Journal information in tool results, titles, summaries, key points, raw
# text, drafts and rationales alike. Logs, audit, SQL telemetry and error surfaces never carry
# journal text; see tests/contract/test_journal_telemetry_redaction.py.


def _appended_line(points: int, with_text: bool, where: str) -> str:
    """Line 1 of an add: "Added 2 points to today's journal." with no id and no version."""

    parts: list[str] = []
    if points:
        parts.append(count_phrase(points, "point", "points"))
    if with_text:
        parts.append("your words")
    return f"Added {' and '.join(parts)} to {where}."


_LINK_NAMES_SHOWN = 6


def _links_row(record: dict[str, Any]) -> list[str]:
    """One plain row naming what the entry is linked to, so Claude can say it aloud."""

    names = [flat(link["label"], 60) for link in record["links"] if link["label"]]
    if not names:
        return []
    shown = names[:_LINK_NAMES_SHOWN]
    text = ", ".join(shown[:-1]) + (" and " if len(shown) > 1 else "") + shown[-1]
    if len(names) > len(shown):
        text += f" and {len(names) - len(shown)} more"
    return [f"Linked to {text}."]


def _relation_change_phrase(added: int, removed: int) -> str:
    """Words for a change of links, like Added 2 links and removed 1 link; empty for none."""

    parts: list[str] = []
    if added:
        parts.append(f"added {count_phrase(added, 'link', 'links')}")
    if removed:
        parts.append(f"removed {count_phrase(removed, 'link', 'links')}")
    return f"{' and '.join(parts).capitalize()}." if parts else ""


def _entry_row(entry: dict[str, Any], *, include_content: bool) -> str:
    """One row: id, date, status and version; the title unless include_content is false."""

    status = "archived" if entry["archived"] else "active"
    row = f"- {entry['id']} | {entry['journal_date']} | {status} | v{entry['version']}"
    if include_content:
        row += f" | {flat(entry['title'])}"
    return row


_SPOKEN_TITLE_LIMIT = 80
_DRAFT_STATE_WORDS = {
    "pending_review": "waiting for review",
    "finalized": "finalized",
    "rejected": "rejected",
    "superseded": "superseded",
}


def _count(count: int, one: str, many: str, *, partial: bool = False) -> str:
    """`N` with its noun; `at least N` when the page is only part of the result."""

    prefix = "at least " if partial else ""
    return f"{prefix}{count_phrase(count, one, many)}"


def _done_row(done: dict[str, Any]) -> list[str]:
    """One counts-only line about what was done that day; nothing when nothing was."""

    counts = done["counts"]
    if not any(counts.values()):
        return []
    return [
        f"Done that day (owner's zone): {counts['tasks']} tasks, {counts['steps']} steps, "
        f"{counts['purchases']} purchases"
        + ("; lists are cut at 50." if done["truncated"] else ".")
    ]


def _summary_phrase(summary: dict[str, Any]) -> str:
    """The daily summary's state for line 1 of get_journal_day."""

    if not summary["exists"]:
        return "without a daily summary"
    if summary["status"] is None:
        return "with a daily summary"
    return f"with a {summary['status']} daily summary"


# Parameter types shared by several tools; the JSON schema each produces is pinned by the contract.
_Version = Annotated[int, Field(ge=1)]
_Title = Annotated[str, Field(min_length=1, max_length=200)]
_KeyPointInputs = Annotated[list[JournalKeyPointInput], Field(max_length=50)]
_TaskProposals = Annotated[list[TaskProposalInput], Field(max_length=20)]
_RelationIds = Annotated[list[UUID], Field(max_length=25, json_schema_extra={"uniqueItems": True})]


@dataclass(frozen=True, slots=True)
class _JournalToolContext(ToolContext):
    """The shared tool context plus the journal's speakable day helpers."""

    def _today(self) -> date:
        return owner_today(self.container.journal.clock.now(), self.container.settings.owner_zone)

    def spoken_day(self, day: date | str) -> str:
        """A journal day for line 1, such as "21 July"; the ISO date stays on later lines."""

        value = day if isinstance(day, date) else date.fromisoformat(day)
        return spoken_date(value, self._today())

    def journal_phrase(self, day: date | str) -> str:
        """ "today's journal" for today, otherwise "the journal from 21 July"."""

        value = day if isinstance(day, date) else date.fromisoformat(day)
        if value == self._today():
            return "today's journal"
        return f"the journal from {self.spoken_day(value)}"


def _relation_selection(items: Any) -> tuple[tuple[UUID, str], ...]:
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
    )


def _update_entry_text(
    ctx: _JournalToolContext,
    structured: dict[str, Any],
    before: EntryRelations | None,
    *,
    appended_points: int,
    appended_text: bool,
    edited_fields: bool,
) -> str:
    """The speakable text of an entry update: what changed, the entry, and the link changes."""

    updated = structured["entry"]
    if appended_points or appended_text:
        first_line = _appended_line(
            appended_points, appended_text, ctx.journal_phrase(updated["journal_date"])
        )
    elif not edited_fields:
        day = ctx.spoken_day(updated["journal_date"])
        first_line = f"Changed the links of the journal entry from {day}."
    else:
        first_line = f"Updated the journal entry from {ctx.spoken_day(updated['journal_date'])}."
    rows = [f"Entry {updated['id']} v{updated['version']}."]
    if before is not None:
        was = {str(i) for i in (*before.project_ids, *before.contact_ids)}
        now = {link["id"] for link in updated["links"]}
        changed = _relation_change_phrase(len(now - was), len(was - now))
        rows.append(changed or "No link changed.")
    rows.extend(_links_row(updated))
    return rows_text(first_line, rows)


def _empty_summary_content(overview: str) -> SummaryContent:
    """Only the overview is model text; the structured sections stay empty."""

    return SummaryContent(
        overview=overview,
        overview_entry_ids=[],
        themes=[],
        important_events=[],
        decisions=[],
        commitments=[],
        open_questions=[],
        unresolved_items=[],
        contradictions=[],
    )


def _register_list_journal_entries(mcp: FastMCP, ctx: _JournalToolContext) -> None:
    @mcp.tool(
        name="list_journal_entries",
        description=(
            "Use this for a bounded date-filtered list of at most 366 inclusive calendar "
            "days of the authenticated user's journal entries, oldest first. For the latest "
            "entry of a day, make one call with limit=50 and take the last row; do not also call "
            "get_journal_entry unless the user asks to see it. Each entry carries its summary "
            "and key points unless include_content is false; do not use it for another user "
            "or unbounded history."
        ),
        output_schema=output_schema(JournalEntryPageResult),
        annotations=READ,
    )
    @ctx.instrument("list_journal_entries")
    def list_journal_entries(
        from_date: date | None = None,
        to_date: date | None = None,
        include_archived: bool = False,
        include_content: bool = True,
        limit: Annotated[int, Field(ge=1, le=50)] = 10,
        cursor: Annotated[str | None, Field(max_length=MAX_CURSOR_LENGTH)] = None,
    ) -> Any:
        structured = journal_entries_structured(
            ctx.container,
            ctx.actor_provider(),
            from_date=from_date,
            to_date=to_date,
            include_archived=include_archived,
            include_content=include_content,
            limit=limit,
            cursor=cursor,
        )
        entries = structured["entries"]
        partial = structured["next_cursor"] is not None
        count = _count(len(entries), "journal entry", "journal entries", partial=partial)
        header = f"Found {count}"
        if include_content and entries:
            latest = flat(entries[-1]["title"], _SPOKEN_TITLE_LIMIT)
            header += f', latest "{latest}"'
        return result(
            structured,
            rows_text(
                f"{header}.",
                [_entry_row(entry, include_content=include_content) for entry in entries],
            ),
        )


def _register_get_journal_entry(mcp: FastMCP, ctx: _JournalToolContext) -> None:
    @mcp.tool(
        name="get_journal_entry",
        description=(
            "Use this for one known owned entry UUID, usually from a list result, when the "
            "user asks to see that entry. One call per request; do not re-read the same entry. "
            "The summary and key points are included unless include_content is false; "
            "inaccessible IDs disclose no existence detail."
        ),
        output_schema=output_schema(JournalEntryResult),
        annotations=READ,
        app=AppConfig(resource_uri=SIDEKICK_APP_URI),
    )
    @ctx.instrument("get_journal_entry")
    def get_journal_entry(
        entry_id: UUID,
        include_content: bool = True,
    ) -> Any:
        structured = journal_entry_structured(
            ctx.container, ctx.actor_provider(), entry_id, include_content=include_content
        )
        record = structured["entry"]
        title = flat(record["title"], _SPOKEN_TITLE_LIMIT)
        day = ctx.spoken_day(record["journal_date"])
        return result(
            structured,
            rows_text(
                f'The journal entry "{title}" from {day}.',
                [f"Entry {record['id']} v{record['version']}.", *_links_row(record)],
            ),
        )


def _register_get_journal_day(mcp: FastMCP, ctx: _JournalToolContext) -> None:
    @mcp.tool(
        name="get_journal_day",
        description=(
            "Use this for bounded entries and summary status on one explicit date. Entry "
            "content is included unless include_content is false, and no AI generation occurs. "
            "`done` lists what was completed or bought that day, also on an empty day. "
            "Its entry_fingerprint is the value set_daily_journal_summary requires. "
            "When the app card opens, reply in one "
            "or two sentences and do not repeat its contents as a list or table. Edits made in the "
            "card are invisible to you until you re-read, so re-read before describing the current "
            "state."
        ),
        output_schema=output_schema(JournalDayResult),
        annotations=READ,
        app=AppConfig(resource_uri=SIDEKICK_APP_URI),
    )
    @ctx.instrument("get_journal_day")
    def get_journal_day(
        journal_date: date,
        include_archived: bool = False,
        include_content: bool = True,
        limit: Annotated[int, Field(ge=1, le=50)] = 10,
        cursor: Annotated[str | None, Field(max_length=MAX_CURSOR_LENGTH)] = None,
    ) -> Any:
        structured = journal_day_structured(
            ctx.container,
            ctx.actor_provider(),
            journal_date,
            include_archived=include_archived,
            include_content=include_content,
            limit=limit,
            cursor=cursor,
        )
        count = _count(
            len(structured["entries"]),
            "entry",
            "entries",
            partial=structured["next_cursor"] is not None,
        )
        sentence = (
            f"{count} on {ctx.spoken_day(structured['journal_date'])}, "
            f"{_summary_phrase(structured['summary'])}."
        )
        return result(
            structured,
            rows_text(
                sentence,
                [
                    f"entry_fingerprint {structured['entry_fingerprint']}; "
                    "the daily summary status is included.",
                    *_done_row(structured["done"]),
                ],
            ),
        )


def _register_get_daily_journal_summary(mcp: FastMCP, ctx: _JournalToolContext) -> None:
    @mcp.tool(
        name="get_daily_journal_summary",
        description=(
            "Use this to read the owned summary content, entry provenance, and current, "
            "stale, or failed status for one explicit date. It never generates or updates "
            "a summary."
        ),
        output_schema=output_schema(JournalSummaryResult),
        annotations=READ,
        app=AppConfig(visibility=["app"]),
    )
    @ctx.instrument("get_daily_journal_summary")
    def get_daily_journal_summary(journal_date: date) -> Any:
        actor = ctx.actor_provider()
        status, summary = ctx.container.journal.get_summary(actor, journal_date)
        structured = JournalSummaryResult(
            summary=summary_record(journal_date, summary, status)
        ).model_dump(mode="json")
        return result(
            structured,
            f"Returned the daily summary for {journal_date.isoformat()}.",
        )


def _register_get_journal_source(mcp: FastMCP, ctx: _JournalToolContext) -> None:
    @mcp.tool(
        name="get_journal_source",
        description=(
            "Use this for one known owned source UUID to read its immutable provenance: type, "
            "dates, language, replacement link, and fingerprint. The raw text is included unless "
            "include_content is false; inaccessible IDs disclose nothing."
        ),
        output_schema=output_schema(JournalSourceReadResult),
        annotations=READ,
    )
    @ctx.instrument("get_journal_source")
    def get_journal_source(
        source_id: UUID,
        include_content: bool = True,
    ) -> Any:
        structured = journal_source_structured(
            ctx.container, ctx.actor_provider(), source_id, include_content=include_content
        )
        record = structured["source"]
        kind = spoken_status(record["source_type"])
        return result(
            structured,
            rows_text(
                f"The source text from {ctx.spoken_day(record['journal_date'])} ({kind}).",
                [f"Source {record['id']}."],
            ),
        )


def _register_list_pending_journal(mcp: FastMCP, ctx: _JournalToolContext) -> None:
    @mcp.tool(
        name="list_pending_journal",
        description=(
            "Use this for a bounded list of preserved sources on one explicit date range that "
            "still await manual or AI-assisted review, with draft state and no source text. "
            "Supply both dates or neither, which means today; at most 100 items are returned."
        ),
        output_schema=output_schema(PendingJournalPageResult),
        annotations=READ,
        app=AppConfig(resource_uri=SIDEKICK_APP_URI),
    )
    @ctx.instrument("list_pending_journal")
    def list_pending_journal(
        from_date: date | None = None,
        to_date: date | None = None,
        limit: Annotated[int, Field(ge=1, le=100)] = 100,
    ) -> Any:
        container = ctx.container
        actor = ctx.actor_provider()
        if from_date is None and to_date is None:
            current_date = owner_today(container.journal.clock.now(), container.settings.owner_zone)
            from_date = to_date = current_date
        elif from_date is None or to_date is None:
            raise ValidationError("from_date and to_date must be supplied together")
        items = container.journal.list_pending_items(
            actor,
            start_date=from_date,
            end_date=to_date,
            limit=limit,
        )
        structured = PendingJournalPageResult(
            items=[_pending_record(item) for item in items]
        ).model_dump(mode="json")
        return result(
            structured,
            f"Found {_count(len(items), 'journal item', 'journal items')} awaiting review.",
        )


def _register_create_journal_source(mcp: FastMCP, ctx: _JournalToolContext) -> None:
    @mcp.tool(
        name="create_journal_source",
        description=(
            "Use this only when the user asks to preserve manual or transcript text for an "
            "explicit date. It creates an immutable source or replacement and invokes no AI."
        ),
        output_schema=output_schema(JournalSourceResult),
        annotations=WRITE,
        app=AppConfig(visibility=["app"]),
    )
    @ctx.instrument("create_journal_source")
    def create_journal_source(
        source_type: SourceType,
        journal_date: date,
        raw_text: Annotated[str, Field(min_length=1, max_length=100_000)],
        idempotency_key: IdempotencyKey,
        occurred_at: datetime | None = None,
        source_recorded_at: datetime | None = None,
        language: Annotated[str | None, Field(min_length=2, max_length=35)] = None,
        replaces_source_id: UUID | None = None,
    ) -> Any:
        source = ctx.container.journal.create_source(
            ctx.actor_provider(),
            source_type=source_type,
            journal_date=journal_date,
            occurred_at=occurred_at,
            source_recorded_at=source_recorded_at,
            raw_text=raw_text,
            language=language,
            replaces_source_id=replaces_source_id,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        structured = JournalSourceResult(source=source_record(source)).model_dump(mode="json")
        return result(
            structured,
            rows_text(
                f"Created the journal source for {structured['source']['journal_date']}.",
                [f"Source {structured['source']['id']}."],
            ),
        )


def _register_create_manual_journal_entry(mcp: FastMCP, ctx: _JournalToolContext) -> None:
    @mcp.tool(
        name="create_manual_journal_entry",
        description=(
            "Use this to finalize one committed owned source with user-authored fields and "
            "selected active relations. A source can create at most one entry; an existing "
            "entry conflicts. It invokes no AI and cannot create or update Tasks."
        ),
        output_schema=output_schema(JournalEntryResult),
        annotations=WRITE,
        app=AppConfig(resource_uri=SIDEKICK_APP_URI, visibility=["app"]),
    )
    @ctx.instrument("create_manual_journal_entry")
    def create_manual_journal_entry(
        source_id: UUID,
        title: Annotated[str, Field(min_length=1, max_length=200), NoImageData],
        summary: Annotated[str, Field(max_length=10_000), NoImageData] | None,
        key_points: _KeyPointInputs,
        project_ids: _RelationIds,
        task_ids: _RelationIds,
        contact_ids: _RelationIds,
        idempotency_key: IdempotencyKey,
    ) -> Any:
        container = ctx.container
        actor = ctx.actor_provider()
        entry = container.journal.create_manual_entry(
            actor,
            source_id=source_id,
            title=title,
            summary=summary,
            key_points=tuple(KeyPoint(point.kind, point.text) for point in key_points),
            project_ids=tuple(project_ids),
            task_ids=tuple(task_ids),
            contact_ids=tuple(contact_ids),
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        relations = EntryRelations(
            project_ids=tuple(project_ids),
            task_ids=tuple(task_ids),
            contact_ids=tuple(contact_ids),
        )
        structured = JournalEntryResult(
            entry=labeled_entry_record(container, actor, entry, relations, include_content=True)
        ).model_dump(mode="json")
        created = structured["entry"]
        return result(
            structured,
            rows_text(
                f"Created a manual entry from {ctx.spoken_day(created['journal_date'])}.",
                [f"Entry {created['id']} v{created['version']}.", *_links_row(created)],
            ),
        )


def _register_write_journal_entry(mcp: FastMCP, ctx: _JournalToolContext) -> None:
    @mcp.tool(
        name="write_journal_entry",
        description=(
            'Use this when the user asks to write or save a journal entry (e.g. "skriv dagbok"). '
            "It saves the user's own words as an immutable source and creates the entry in one "
            "step: supply the date, title, summary, key points and, only when named, related "
            "project, task or contact ids. Do not look up or create a source first, or call "
            "get_journal_entry afterwards. Retrying with the same idempotency_key returns the same "
            "entry. When the app card opens, reply in one or two sentences without repeating it. "
            "It invokes no AI and cannot create or update Tasks."
        ),
        output_schema=output_schema(JournalEntryResult),
        annotations=WRITE,
        app=AppConfig(resource_uri=SIDEKICK_APP_URI),
    )
    @ctx.instrument("write_journal_entry")
    def write_journal_entry(
        journal_date: date,
        title: Annotated[str, Field(min_length=1, max_length=200), NoImageData],
        source_text: Annotated[str, Field(min_length=1, max_length=100_000), NoImageData],
        idempotency_key: IdempotencyKey,
        summary: Annotated[str, Field(max_length=10_000), NoImageData] | None = None,
        key_points: _KeyPointInputs | None = None,
        project_ids: _RelationIds | None = None,
        task_ids: _RelationIds | None = None,
        contact_ids: _RelationIds | None = None,
        occurred_at: datetime | None = None,
        language: Annotated[str | None, Field(min_length=2, max_length=35)] = None,
    ) -> Any:
        structured = write_journal_entry_structured(
            ctx.container,
            ctx.actor_provider(),
            journal_date=journal_date,
            title=title,
            source_text=source_text,
            idempotency_key=idempotency_key,
            summary=summary,
            key_points=key_points,
            project_ids=project_ids,
            task_ids=task_ids,
            contact_ids=contact_ids,
            occurred_at=occurred_at,
            language=language,
            correlation_id=request_correlation_id_or_new(),
        )
        record = structured["entry"]
        return result(
            structured,
            rows_text(
                f"Saved the journal entry from {ctx.spoken_day(record['journal_date'])}.",
                [f"Entry {record['id']} v{record['version']}.", *_links_row(record)],
            ),
        )


def _register_update_journal_entry(mcp: FastMCP, ctx: _JournalToolContext) -> None:
    @mcp.tool(
        name="update_journal_entry",
        description=(
            "Use this to add to, correct or relink an existing journal entry (e.g. 'lägg till i "
            "dagens dagbok'); read it first and send its current version. To add, send "
            "append_key_points and/or append_text (her own words, a new source). To correct, send "
            "title and key_points, which replace title, summary and key points. To fix its links, "
            "send add_/remove_contact_ids or add_/remove_project_ids, alone or with the above. A "
            "stale version or an archived entry conflicts. When the card opens, reply in one or "
            "two sentences."
        ),
        output_schema=output_schema(JournalEntryResult),
        # Not destructive: the edit is versioned, an appended text keeps the earlier source, and
        # a removed link can be added again.
        annotations=WRITE,
        app=AppConfig(resource_uri=SIDEKICK_APP_URI),
    )
    @ctx.instrument("update_journal_entry")
    def update_journal_entry(
        entry_id: UUID,
        expected_version: _Version,
        idempotency_key: IdempotencyKey,
        title: _Title | None = None,
        summary: Annotated[str, Field(max_length=10_000)] | None = None,
        key_points: _KeyPointInputs | None = None,
        append_key_points: Annotated[
            list[JournalKeyPointInput],
            Field(max_length=50, description="Points added after the existing ones."),
        ]
        | None = None,
        append_text: Annotated[
            str,
            Field(
                min_length=1,
                max_length=100_000,
                description="Her own words to add; kept as a new source.",
            ),
            NoImageData,
        ]
        | None = None,
        add_contact_ids: _RelationIds | None = None,
        remove_contact_ids: _RelationIds | None = None,
        add_project_ids: _RelationIds | None = None,
        remove_project_ids: _RelationIds | None = None,
    ) -> Any:
        structured, before = update_journal_entry_structured(
            ctx.container,
            ctx.actor_provider(),
            entry_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            title=title,
            summary=summary,
            key_points=key_points,
            append_key_points=append_key_points,
            append_text=append_text,
            add_contact_ids=add_contact_ids,
            remove_contact_ids=remove_contact_ids,
            add_project_ids=add_project_ids,
            remove_project_ids=remove_project_ids,
            correlation_id=request_correlation_id_or_new(),
        )
        text = _update_entry_text(
            ctx,
            structured,
            before,
            appended_points=len(append_key_points or []),
            appended_text=append_text is not None,
            edited_fields=not (title is None and key_points is None and summary is None),
        )
        return result(structured, text)


def _register_set_daily_journal_summary(mcp: FastMCP, ctx: _JournalToolContext) -> None:
    @mcp.tool(
        name="set_daily_journal_summary",
        description=(
            "Use this when the user asks you to write or replace the daily journal summary for "
            "one explicit date. Send summary_text as its overview, expected_entry_fingerprint from "
            "get_journal_day's entry_fingerprint, and expected_summary_version from its "
            "summary.version, or null when no summary exists. Retrying with the same "
            "idempotency_key returns the same result. A changed entry set or stale summary version "
            "fails with reason stale_version; re-read get_journal_day and retry. It invokes no AI "
            "and changes no entry."
        ),
        output_schema=output_schema(JournalSummaryResult),
        annotations=WRITE,
    )
    @ctx.instrument("set_daily_journal_summary")
    def set_daily_journal_summary(
        journal_date: date,
        summary_text: Annotated[str, Field(min_length=1, max_length=20_000)],
        expected_entry_fingerprint: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")],
        idempotency_key: IdempotencyKey,
        expected_summary_version: _Version | None = None,
    ) -> Any:
        summary = ctx.container.journal.put_manual_summary(
            ctx.actor_provider(),
            journal_date=journal_date,
            expected_entry_fingerprint=expected_entry_fingerprint,
            expected_summary_version=expected_summary_version,
            content=_empty_summary_content(summary_text),
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        # Written just now, so no entry has changed since: the changed-entry count is zero.
        structured = JournalSummaryResult(
            summary=summary_record(journal_date, summary, DaySummaryStatus())
        ).model_dump(mode="json")
        return result(
            structured,
            rows_text(
                f"Saved the daily summary for {ctx.spoken_day(journal_date)}.",
                [f"Summary {journal_date.isoformat()} v{structured['summary']['version']}."],
            ),
        )


def _register_get_journal_draft(mcp: FastMCP, ctx: _JournalToolContext) -> None:
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
    ) -> Any:
        actor = ctx.actor_provider()
        draft = ctx.container.journal_analysis.get_draft(actor, draft_id)
        structured = _draft_dump(
            JournalDraftReadResult(
                draft=_draft_record(draft, include_content=include_content, scopes=actor.scopes),
                source=source_read_record(draft.source, include_content=include_content),
            )
        )
        record = structured["draft"]
        title = flat(record["title"], _SPOKEN_TITLE_LIMIT)
        day = ctx.spoken_day(structured["source"]["journal_date"])
        state = _DRAFT_STATE_WORDS[record["state"]]
        return result(
            structured,
            rows_text(
                f'The journal draft "{title}" from {day}, {state}.',
                [f"Draft {record['id']} v{record['version']}."],
            ),
        )


def _register_update_journal_draft(mcp: FastMCP, ctx: _JournalToolContext) -> None:
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
        expected_version: _Version,
        title: _Title,
        summary: Annotated[str, Field(max_length=10_000)] | None,
        key_points: _KeyPointInputs,
        task_proposals: _TaskProposals,
        idempotency_key: IdempotencyKey,
    ) -> Any:
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
        structured = _draft_status(draft).model_dump(mode="json")
        return result(structured, "Updated the journal draft.")


def _register_reject_journal_draft(mcp: FastMCP, ctx: _JournalToolContext) -> None:
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
        expected_version: _Version,
        idempotency_key: IdempotencyKey,
    ) -> Any:
        draft = ctx.container.journal_analysis.reject_draft(
            ctx.actor_provider(),
            draft_id=draft_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        structured = _draft_status(draft).model_dump(mode="json")
        return result(structured, "Rejected the journal draft.")


def _register_finalize_journal_draft(mcp: FastMCP, ctx: _JournalToolContext) -> None:
    @mcp.tool(
        name="finalize_journal_draft",
        description=(
            "Use this only when the user explicitly approves one pending journal draft as "
            "reviewed. It creates the journal entry from the supplied fields and selected "
            "relations, and applies only the Task proposals the user kept, which may create "
            "Tasks or change existing ones. It is terminal and invokes no AI. A stale version "
            "or a draft that is no longer pending conflicts."
        ),
        output_schema=output_schema(JournalFinalizeResult),
        annotations=DESTRUCTIVE,
        app=AppConfig(visibility=["app"]),
    )
    @ctx.instrument("finalize_journal_draft")
    def finalize_journal_draft(
        draft_id: UUID,
        expected_version: _Version,
        title: _Title,
        summary: Annotated[str, Field(max_length=10_000)] | None,
        key_points: _KeyPointInputs,
        relation_selection: RelationSelection,
        task_proposals: _TaskProposals,
        idempotency_key: IdempotencyKey,
    ) -> Any:
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
                container, actor, outcome.entry, relations, include_content=True
            ),
            created_task_ids=list(outcome.created_task_ids),
            updated_task_ids=list(outcome.updated_task_ids),
        ).model_dump(mode="json")
        return result(structured, "Finalized the journal draft into a journal entry.")


_REGISTRARS = (
    _register_list_journal_entries,
    _register_get_journal_entry,
    _register_get_journal_day,
    _register_get_daily_journal_summary,
    _register_get_journal_source,
    _register_list_pending_journal,
    _register_create_journal_source,
    _register_create_manual_journal_entry,
    _register_write_journal_entry,
    _register_update_journal_entry,
    _register_set_daily_journal_summary,
    _register_get_journal_draft,
    _register_update_journal_draft,
    _register_reject_journal_draft,
    _register_finalize_journal_draft,
)


def register_journal_tools(mcp: FastMCP, ctx: ToolContext) -> None:
    """Register the fifteen bounded Journal tools; none of them starts AI processing."""

    journal_ctx = _JournalToolContext(ctx.container, ctx.actor_provider, ctx.instrument)
    for register in _REGISTRARS:
        register(mcp, journal_ctx)
