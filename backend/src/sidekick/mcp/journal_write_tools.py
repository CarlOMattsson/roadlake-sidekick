"""The Journal write tools: sources, entries and the daily summary."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any
from uuid import UUID

from fastmcp import FastMCP
from fastmcp.apps import AppConfig
from pydantic import Field

from sidekick.journal.domain.entry import KeyPoint
from sidekick.journal.domain.records import DaySummaryStatus, EntryRelations
from sidekick.journal.domain.source import SourceType
from sidekick.mcp.annotations import WRITE
from sidekick.mcp.correlation import request_correlation_id_or_new
from sidekick.mcp.idempotency import IdempotencyKey
from sidekick.mcp.journal_records import (
    JournalSourceResult,
    JournalSummaryResult,
    KeyPointInputs,
    RelationIds,
    TitleParam,
    VersionParam,
)
from sidekick.mcp.journal_text import (
    JournalToolContext,
    empty_summary_content,
    links_row,
    update_entry_text,
)
from sidekick.mcp.results import output_schema, result
from sidekick.mcp.sidekick_app import SIDEKICK_APP_URI
from sidekick.mcp.text import rows_text
from sidekick.shared.text_guard import NoImageData
from sidekick.structured.journal import (
    JournalEntryResult,
    JournalKeyPointInput,
    labeled_entry_record,
    source_record,
    summary_record,
    update_journal_entry_structured,
    write_journal_entry_structured,
)


def _register_create_journal_source(mcp: FastMCP, ctx: JournalToolContext) -> None:
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
        source = ctx.container.journal_capture.create_source(
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


def _register_create_manual_journal_entry(mcp: FastMCP, ctx: JournalToolContext) -> None:
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
        key_points: KeyPointInputs,
        project_ids: RelationIds,
        task_ids: RelationIds,
        contact_ids: RelationIds,
        idempotency_key: IdempotencyKey,
    ) -> Any:
        container = ctx.container
        actor = ctx.actor_provider()
        entry = container.journal_capture.create_manual_entry(
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
                [f"Entry {created['id']} v{created['version']}.", *links_row(created)],
            ),
        )


def _register_write_journal_entry(mcp: FastMCP, ctx: JournalToolContext) -> None:
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
        key_points: KeyPointInputs | None = None,
        project_ids: RelationIds | None = None,
        task_ids: RelationIds | None = None,
        contact_ids: RelationIds | None = None,
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
                [f"Entry {record['id']} v{record['version']}.", *links_row(record)],
            ),
        )


def _register_update_journal_entry(mcp: FastMCP, ctx: JournalToolContext) -> None:
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
        expected_version: VersionParam,
        idempotency_key: IdempotencyKey,
        title: TitleParam | None = None,
        summary: Annotated[str, Field(max_length=10_000)] | None = None,
        key_points: KeyPointInputs | None = None,
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
        add_contact_ids: RelationIds | None = None,
        remove_contact_ids: RelationIds | None = None,
        add_project_ids: RelationIds | None = None,
        remove_project_ids: RelationIds | None = None,
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
        text = update_entry_text(
            ctx,
            structured,
            before,
            appended_points=len(append_key_points or []),
            appended_text=append_text is not None,
            edited_fields=not (title is None and key_points is None and summary is None),
        )
        return result(structured, text)


def _register_set_daily_journal_summary(mcp: FastMCP, ctx: JournalToolContext) -> None:
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
        expected_summary_version: VersionParam | None = None,
    ) -> Any:
        summary = ctx.container.journal_day.put_manual_summary(
            ctx.actor_provider(),
            journal_date=journal_date,
            expected_entry_fingerprint=expected_entry_fingerprint,
            expected_summary_version=expected_summary_version,
            content=empty_summary_content(summary_text),
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


def register_journal_write_tools(mcp: FastMCP, ctx: JournalToolContext) -> None:
    """Register the five Journal write tools, in the order the list shows them."""

    _register_create_journal_source(mcp, ctx)
    _register_create_manual_journal_entry(mcp, ctx)
    _register_write_journal_entry(mcp, ctx)
    _register_update_journal_entry(mcp, ctx)
    _register_set_daily_journal_summary(mcp, ctx)
