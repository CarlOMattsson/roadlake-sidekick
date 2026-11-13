"""The Journal read tools: lists, one entry, one day, a summary, a source and pending items."""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastmcp import FastMCP
from fastmcp.apps import AppConfig
from fastmcp.tools import ToolResult
from pydantic import Field

from sidekick.journal.domain.day_done import owner_today
from sidekick.journal.domain.entry import JournalOrder
from sidekick.mcp.annotations import READ
from sidekick.mcp.journal_records import (
    JournalSummaryResult,
    PendingJournalPageResult,
    pending_record,
)
from sidekick.mcp.journal_text import (
    SPOKEN_TITLE_LIMIT,
    JournalToolContext,
    counted,
    done_row,
    entry_row,
    links_row,
    summary_phrase,
    tags_row,
)
from sidekick.mcp.results import output_schema, result
from sidekick.mcp.sidekick_app import SIDEKICK_APP_URI
from sidekick.mcp.text import flat, rows_text, spoken_status
from sidekick.shared.errors import ValidationError
from sidekick.shared.types import MAX_CURSOR_LENGTH
from sidekick.structured.journal import (
    JournalDayResult,
    JournalEntryPageResult,
    JournalEntryResult,
    JournalSourceReadResult,
    journal_day_structured,
    journal_entries_structured,
    journal_entry_structured,
    journal_source_structured,
    summary_record,
)
from sidekick.structured.tags import TagFilter, TagMatch


def _register_list_journal_entries(mcp: FastMCP, ctx: JournalToolContext) -> None:
    @mcp.tool(
        name="list_journal_entries",
        description=(
            "Use this for a bounded date-filtered list of at most 366 inclusive calendar "
            "days of the authenticated user's journal entries, oldest first (order=desc: "
            "newest first). For the latest entry of a day, make one call with limit=50 and "
            "take the last row; do not also call get_journal_entry unless the user asks to "
            "see it. Each entry carries its summary and key points unless include_content "
            "is false; tags lists only entries with them. "
            "Do not use it for another user or unbounded history."
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
        tags: TagFilter | None = None,
        tag_match: TagMatch = "any",
        order: JournalOrder = "asc",
        limit: Annotated[int, Field(ge=1, le=50)] = 10,
        cursor: Annotated[str | None, Field(max_length=MAX_CURSOR_LENGTH)] = None,
    ) -> ToolResult:
        structured = journal_entries_structured(
            ctx.container,
            ctx.actor_provider(),
            from_date=from_date,
            to_date=to_date,
            include_archived=include_archived,
            include_content=include_content,
            tags=tuple(tags or ()),
            tag_match=tag_match,
            order=order,
            limit=limit,
            cursor=cursor,
        )
        entries = structured.entries
        partial = structured.next_cursor is not None
        count = counted(len(entries), "journal entry", "journal entries", partial=partial)
        header = f"Found {count}"
        if include_content and entries:
            latest = flat(entries[0 if order == "desc" else -1].title, SPOKEN_TITLE_LIMIT)
            header += f', latest "{latest}"'
        return result(
            structured.model_dump(mode="json"),
            rows_text(
                f"{header}.",
                [entry_row(entry, include_content=include_content) for entry in entries],
            ),
        )


def _register_get_journal_entry(mcp: FastMCP, ctx: JournalToolContext) -> None:
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
    ) -> ToolResult:
        structured = journal_entry_structured(
            ctx.container, ctx.actor_provider(), entry_id, include_content=include_content
        )
        record = structured.entry
        title = flat(record.title, SPOKEN_TITLE_LIMIT)
        day = ctx.spoken_day(record.journal_date)
        return result(
            structured.model_dump(mode="json"),
            rows_text(
                f'The journal entry "{title}" from {day}.',
                [
                    f"Entry {record.id} v{record.version}.",
                    *links_row(record),
                    *tags_row(record),
                ],
            ),
        )


def _register_get_journal_day(mcp: FastMCP, ctx: JournalToolContext) -> None:
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
    ) -> ToolResult:
        structured = journal_day_structured(
            ctx.container,
            ctx.actor_provider(),
            journal_date,
            include_archived=include_archived,
            include_content=include_content,
            limit=limit,
            cursor=cursor,
        )
        count = counted(
            len(structured.entries),
            "entry",
            "entries",
            partial=structured.next_cursor is not None,
        )
        sentence = (
            f"{count} on {ctx.spoken_day(structured.journal_date)}, "
            f"{summary_phrase(structured.summary)}."
        )
        return result(
            structured.model_dump(mode="json"),
            rows_text(
                sentence,
                [
                    f"entry_fingerprint {structured.entry_fingerprint}; "
                    "the daily summary status is included.",
                    *done_row(structured.done),
                ],
            ),
        )


def _register_get_daily_journal_summary(mcp: FastMCP, ctx: JournalToolContext) -> None:
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
    def get_daily_journal_summary(journal_date: date) -> ToolResult:
        actor = ctx.actor_provider()
        status, summary = ctx.container.journal_day.get_summary(actor, journal_date)
        structured = JournalSummaryResult(
            summary=summary_record(journal_date, summary, status)
        ).model_dump(mode="json")
        return result(
            structured,
            f"Returned the daily summary for {journal_date.isoformat()}.",
        )


def _register_get_journal_source(mcp: FastMCP, ctx: JournalToolContext) -> None:
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
    ) -> ToolResult:
        structured = journal_source_structured(
            ctx.container, ctx.actor_provider(), source_id, include_content=include_content
        )
        record = structured.source
        kind = spoken_status(record.source_type)
        return result(
            structured.model_dump(mode="json"),
            rows_text(
                f"The source text from {ctx.spoken_day(record.journal_date)} ({kind}).",
                [f"Source {record.id}."],
            ),
        )


def _register_list_pending_journal(mcp: FastMCP, ctx: JournalToolContext) -> None:
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
    ) -> ToolResult:
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
            items=[pending_record(item) for item in items]
        ).model_dump(mode="json")
        return result(
            structured,
            f"Found {counted(len(items), 'journal item', 'journal items')} awaiting review.",
        )


def register_journal_read_tools(mcp: FastMCP, ctx: JournalToolContext) -> None:
    """Register the six Journal read tools, in the order the list shows them."""

    _register_list_journal_entries(mcp, ctx)
    _register_get_journal_entry(mcp, ctx)
    _register_get_journal_day(mcp, ctx)
    _register_get_daily_journal_summary(mcp, ctx)
    _register_get_journal_source(mcp, ctx)
    _register_list_pending_journal(mcp, ctx)
