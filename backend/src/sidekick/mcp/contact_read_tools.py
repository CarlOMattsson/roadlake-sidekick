"""The Contact read tools: list, context around one Contact, and the Contacts of a Task."""

# En dashes are intentional human-facing tool copy preserved by contract snapshots.

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastmcp import FastMCP
from fastmcp.apps import AppConfig
from fastmcp.tools import ToolResult
from pydantic import Field

from sidekick.contacts.application.models import (
    LinkedJournalEntries,
    TaskContactMarks,
)
from sidekick.contacts.application.serialization import contact_public_data
from sidekick.contacts.domain.contact import Contact
from sidekick.mcp.annotations import READ
from sidekick.mcp.contact_records import (
    ContactContextResult,
    ContactPageResult,
    ContactRecord,
    Cursor,
    JournalEntryContextRecord,
    JournalEntryLinkRecord,
    ProjectContextPageRecord,
    ProjectSummaryRecord,
    TaskContextPageRecord,
    TaskSummaryRecord,
)
from sidekick.mcp.contact_text import (
    CLOSEST_HINT,
    NO_MATCH_HINT,
    contact_context_text,
    contact_row,
)
from sidekick.mcp.results import output_schema, result, spoken_names
from sidekick.mcp.sidekick_app import SIDEKICK_APP_URI
from sidekick.mcp.text import count_phrase, rows_text
from sidekick.mcp.tool_context import ToolContext
from sidekick.projects.domain import Project
from sidekick.shared.types import Page
from sidekick.structured.contacts import (
    ContactSummaryRecord,
    TaskContactPageRecord,
    task_contacts_structured,
)
from sidekick.structured.tags import TagFilter, TagMatch
from sidekick.tasks.domain import Task


def _summary_record(item: Contact, tags: Sequence[str] = ()) -> ContactSummaryRecord:
    return ContactSummaryRecord(
        id=item.id,
        display_name=item.display_name,
        archived=item.archived,
        updated_at=item.updated_at,
        version=item.version,
        relationship=item.relationship,
        organization=item.organization,
        role=item.role,
        tags=list(tags),
    )


def _page_records(ctx: ToolContext, items: Sequence[Contact]) -> list[ContactSummaryRecord]:
    """The Contacts of a page as summaries, each with its tags (one read for the page)."""

    tags = ctx.container.work_tags.slugs_for(ctx.actor_provider(), "contact", [i.id for i in items])
    return [_summary_record(item, tags.get(item.id, ())) for item in items]


def _closest_contacts(ctx: ToolContext, q: str) -> list[Contact]:
    """Contacts close to a misheard name, empty without contacts:read or any near match."""
    actor = ctx.actor_provider()
    return [
        ctx.container.contacts.get(actor, hit.id)
        for hit in ctx.container.search.closest_contacts(actor, q)
    ]


def _closest_reply(ctx: ToolContext, page: ContactPageResult, closest: list[Contact]) -> ToolResult:
    """A misheard name ("Elijas" for "Elias"): the same word-level search as `search`."""
    contacts = _page_records(ctx, closest)
    structured = page.model_copy(update={"contacts": contacts}).model_dump(mode="json")
    names = [item.display_name for item in closest]
    label = "Closest match" if len(names) == 1 else "Closest matches"
    header = f"{label}: {spoken_names(names, total=len(names))}?"
    text = rows_text(header, [contact_row(contact) for contact in contacts])
    return result(structured, f"{text}\n{CLOSEST_HINT}")


def _project_context_page(page: Page[Project]) -> ProjectContextPageRecord:
    return ProjectContextPageRecord(
        items=[
            ProjectSummaryRecord(
                id=p.id,
                title=p.title,
                status=p.status.value,
                updated_at=p.updated_at,
                version=p.version,
            )
            for p in page.items
        ],
        next_cursor=page.next_cursor,
    )


def _task_context_page(
    page: Page[Task], marks: Mapping[UUID, TaskContactMarks]
) -> TaskContextPageRecord:
    return TaskContextPageRecord(
        items=[
            TaskSummaryRecord(
                id=t.id,
                project_id=t.project_id,
                title=t.title,
                status=t.status.value,
                priority=t.priority.value,
                due_at=t.due_at,
                updated_at=t.updated_at,
                version=t.version,
                waiting_on_contact=marks[t.id]["waiting_on_contact"],
                waiting_since=marks[t.id]["waiting_since"],
                follow_up_at=marks[t.id]["follow_up_at"],
                follow_up_due=marks[t.id]["follow_up_due"],
            )
            for t in page.items
        ],
        next_cursor=page.next_cursor,
    )


def _journal_context(entries: LinkedJournalEntries) -> JournalEntryContextRecord:
    return JournalEntryContextRecord(
        items=[
            JournalEntryLinkRecord(id=entry.id, journal_date=entry.journal_date, title=entry.title)
            for entry in entries.items
        ],
        has_more=entries.has_more,
        readable=entries.readable,
    )


def _register_list_contacts(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="list_contacts",
        description=(
            "Use this to resolve a person the user mentions (name, alias, email or phone) to a "
            "Contact id. It returns a bounded set of the authenticated user's Contacts matching "
            "preferred name, alias, or exact email/phone. If exactly one active Contact matches, "
            "use its id. If several match, ask the user which one, briefly naming the candidates. "
            'If no match, try search with kinds=["contacts"] before creating; create the Contact '
            "only when the user is describing a new person. "
            "Duplicate candidates are returned separately. tags lists only Contacts with them."
        ),
        output_schema=output_schema(ContactPageResult),
        annotations=READ,
    )
    @ctx.instrument("list_contacts")
    def list_contacts(
        q: Annotated[str | None, Field(min_length=1, max_length=200)] = None,
        include_archived: bool = False,
        tags: TagFilter | None = None,
        tag_match: TagMatch = "any",
        limit: Annotated[int, Field(ge=1, le=100)] = 25,
        cursor: Cursor = None,
    ) -> ToolResult:
        page = ctx.container.contacts.list(
            ctx.actor_provider(),
            q=q,
            include_archived=include_archived,
            tags=tuple(tags or ()),
            tag_match=tag_match,
            limit=limit,
            cursor=cursor,
        )
        page_result = ContactPageResult(
            contacts=_page_records(ctx, page.items),
            next_cursor=page.next_cursor,
            q=q,
            include_archived=include_archived,
            tags=list(tags or ()),
            tag_match=tag_match,
        )
        closest = _closest_contacts(ctx, q) if not page.items and q and cursor is None else []
        if closest:
            return _closest_reply(ctx, page_result, closest)
        if page.items:
            names = spoken_names([item.display_name for item in page.items], total=len(page.items))
            header = f"{count_phrase(len(page.items), 'contact', 'contacts')}: {names}."
        else:
            header = "No contacts found."
        text = rows_text(header, [contact_row(contact) for contact in page_result.contacts])
        if not page.items:
            text = f"{text}\n{NO_MATCH_HINT}"
        return result(page_result.model_dump(mode="json"), text)


def _register_get_contact_context(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="get_contact_context",
        description=(
            "Use this after the Contact id is known, for example from list_contacts or "
            "create_contact, to retrieve that owned active Contact, bounded current "
            "Project/Task context and up to 10 newest linked Journal entries (id, date and "
            "title only; read a Journal entry for its content), or to answer who a Contact is. "
            "Do not use it to retrieve archived/future-domain data or read another user's context. "
            "When the app card opens, reply in one or two sentences and do not repeat its contents "
            "as a list or table."
        ),
        output_schema=output_schema(ContactContextResult),
        annotations=READ,
        app=AppConfig(resource_uri=SIDEKICK_APP_URI),
    )
    @ctx.instrument("get_contact_context")
    def get_contact_context(
        contact_id: UUID,
        project_limit: Annotated[int, Field(ge=1, le=25)] = 10,
        project_cursor: Cursor = None,
        task_limit: Annotated[int, Field(ge=1, le=25)] = 10,
        task_cursor: Cursor = None,
        include_completed: bool = False,
    ) -> ToolResult:
        container = ctx.container
        res = container.contact_relations.get_contact_context(
            ctx.actor_provider(),
            contact_id,
            project_limit=project_limit,
            project_cursor=project_cursor,
            task_limit=task_limit,
            task_cursor=task_cursor,
            include_completed=include_completed,
        )
        contact_tags = container.work_tags.for_record(ctx.actor_provider(), "contact", contact_id)
        context = ContactContextResult(
            contact=ContactRecord.model_validate(
                {**contact_public_data(res.contact), "tags": [tag.slug for tag in contact_tags]}
            ),
            projects=_project_context_page(res.projects),
            tasks=_task_context_page(res.tasks, res.task_marks),
            journal_entries=_journal_context(res.journal_entries),
        )
        return result(
            context.model_dump(mode="json"),
            contact_context_text(
                context, now=datetime.now(UTC), zone=container.settings.owner_zone
            ),
        )


def _register_list_task_contacts(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="list_task_contacts",
        description=(
            "Use this after a Task UUID is known to list the owned Contacts linked to that Task "
            "as a bounded, paginated page of Contact summaries. Do not use it to read another "
            "user's Task."
        ),
        output_schema=output_schema(TaskContactPageRecord),
        annotations=READ,
    )
    @ctx.instrument("list_task_contacts")
    def list_task_contacts(
        task_id: UUID,
        limit: Annotated[int, Field(ge=1, le=50)] = 20,
        cursor: Cursor = None,
    ) -> ToolResult:
        structured = task_contacts_structured(
            ctx.container, ctx.actor_provider(), task_id, limit=limit, cursor=cursor
        )
        return result(
            structured.model_dump(mode="json"),
            rows_text(
                f"Found {len(structured.items)} linked Contacts.",
                [contact_row(contact) for contact in structured.items],
            ),
        )


def register_contact_read_tools(mcp: FastMCP, ctx: ToolContext) -> None:
    """Register list_contacts, get_contact_context and list_task_contacts."""

    _register_list_contacts(mcp, ctx)
    _register_get_contact_context(mcp, ctx)
    _register_list_task_contacts(mcp, ctx)
