"""The MCP `search` tool over the shared SearchService (Tasks, Projects, Contacts, Journal).

Journal hits carry ids, the journal date, where the match was found and the entry title. No
Journal summary, raw text or excerpt appears in either text block or in structuredContent
(D-058: logs, audit and telemetry never carry user content; the owner reads journal text in the
Journal room).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.tools import ToolResult
from pydantic import Field

from sidekick.mcp.annotations import READ
from sidekick.mcp.contact_text import CLOSEST_HINT
from sidekick.mcp.correlation import request_correlation_id_or_new
from sidekick.mcp.results import output_schema, result, spoken_names
from sidekick.mcp.text import flat, rows_text
from sidekick.mcp.tool_context import ToolContext
from sidekick.search.domain import Kind
from sidekick.search.schemas import ContactHitRecord, ContactSearchPage, SearchResult
from sidekick.shared.types import MAX_CURSOR_LENGTH, Actor

TITLE_LIMIT = 120


def _names(search_result: SearchResult) -> list[str]:
    """Titles of the Task, Project and journal entry hits and names of the Contact hits, in the
    order of the counts. A journal source without an entry has no title and is not named."""
    names: list[str] = []
    if search_result.tasks is not None:
        names.extend(hit.title for hit in search_result.tasks.hits)
    if search_result.projects is not None:
        names.extend(hit.title for hit in search_result.projects.hits)
    if search_result.contacts is not None:
        names.extend(hit.display_name for hit in search_result.contacts.hits)
    if search_result.journal is not None:
        names.extend(hit.title for hit in search_result.journal.hits if hit.title)
    return names


def _journal_count(search_result: SearchResult) -> int:
    return 0 if search_result.journal is None else len(search_result.journal.hits)


def _names_count(search_result: SearchResult) -> int:
    """How many named hits (Tasks, Projects, Contacts and journal entries) the result holds."""
    return len(_names(search_result))


def _kind_counts(search_result: SearchResult) -> list[tuple[int, str, str]]:
    """Hit counts per kind with their singular and plural noun, in the order they are named."""
    journal = [] if search_result.journal is None else search_result.journal.hits
    entries = sum(1 for hit in journal if hit.id_type == "entry")
    return [
        (0 if search_result.tasks is None else len(search_result.tasks.hits), "task", "tasks"),
        (
            0 if search_result.projects is None else len(search_result.projects.hits),
            "project",
            "projects",
        ),
        (
            0 if search_result.contacts is None else len(search_result.contacts.hits),
            "contact",
            "contacts",
        ),
        (entries, "journal entry", "journal entries"),
        (len(journal) - entries, "journal note", "journal notes"),
    ]


def _summary(search_result: SearchResult) -> str:
    """Line 1: the hits in words. One named hit reads "Found the journal entry "Flytten"."; more
    give counts per kind and up to three names. Journal text is never included (D-058: logs and
    telemetry never carry user content)."""
    counts = [(count, one, many) for count, one, many in _kind_counts(search_result) if count]
    if not counts:
        return "No matches."
    names = _names(search_result)
    if len(counts) == 1 and counts[0][0] == 1 and len(names) == 1:
        _, one, _ = counts[0]
        name = flat(names[0], limit=TITLE_LIMIT)
        shown = f'"{name}"' if one.startswith("journal") else name
        return f"Found the {one} {shown}."
    parts = [f"{count} {one if count == 1 else many}" for count, one, many in counts]
    joined = f"{', '.join(parts[:-1])} and {parts[-1]}" if len(parts) > 1 else parts[0]
    head = f"Found {joined}"
    spoken = spoken_names(names, total=len(names))
    return f"{head}: {spoken}." if spoken else f"{head}."


def _closest_header(names: list[str]) -> str:
    """The spoken first line for a misheard-name suggestion: "Closest match: Elias Svensson?"."""
    label = "Closest match" if len(names) == 1 else "Closest matches"
    return f"{label}: {spoken_names(names, total=len(names))}?"


def _structured(search_result: SearchResult) -> dict[str, Any]:
    """Structured content without absent kinds or cursors. A journal hit keeps `title`, null for a
    source without an entry: `exclude_none` would drop it, and the output schema requires it."""
    structured = search_result.model_dump(mode="json", exclude_none=True)
    journal = structured.get("journal")
    if journal is not None:
        for hit in journal["hits"]:
            hit.setdefault("title", None)
    return structured


def _rows(search_result: SearchResult) -> list[str]:
    """Ids with titles or names and the version for Tasks, Projects and Contacts, so Claude can
    update a hit without a get call first. Journal rows are never listed."""
    rows: list[str] = []
    if search_result.tasks is not None:
        rows.extend(
            f"- task {hit.id} | {flat(hit.title, limit=TITLE_LIMIT)} | {hit.status} "
            f"| v{hit.version}"
            for hit in search_result.tasks.hits
        )
    if search_result.projects is not None:
        rows.extend(
            f"- project {hit.id} | {flat(hit.title, limit=TITLE_LIMIT)} | {hit.status} "
            f"| v{hit.version}"
            for hit in search_result.projects.hits
        )
    if search_result.contacts is not None:
        rows.extend(
            f"- contact {hit.id} | {flat(hit.display_name, limit=TITLE_LIMIT)} | v{hit.version}"
            for hit in search_result.contacts.hits
        )
    return rows


def register_search_tools(mcp: FastMCP, ctx: ToolContext) -> None:
    """Register the `search` tool over the shared search use case."""

    service = ctx.container.search

    def _closest(actor: Actor, query: str, found: SearchResult) -> list[ContactHitRecord] | None:
        """Misheard-name suggestions, only when nothing matched and Contacts were searched."""
        if found.contacts is None or _names_count(found) or _journal_count(found):
            return None
        hits = service.closest_contacts(actor, query)
        return hits or None

    @mcp.tool(
        name="search",
        description=(
            "Use this to find records by words when no id is known: searches the user's Tasks, "
            "Projects, Contacts and Journal (kinds narrows it). Prefix and misspelling tolerant, "
            "best match first. Returns ids and titles, never Journal text; read an entry with "
            "get_journal_entry. A kind the user lacks access to is an error. Archived and "
            "trashed records are excluded. For an exact email or phone use list_contacts."
        ),
        output_schema=output_schema(SearchResult),
        annotations=READ,
    )
    @ctx.instrument("search")
    def search(
        query: Annotated[str, Field(min_length=2, max_length=100)],
        kinds: Annotated[list[Kind], Field(min_length=1, max_length=4)] | None = None,
        limit: Annotated[int, Field(ge=1, le=25)] = 10,
        cursor: Annotated[str | None, Field(max_length=MAX_CURSOR_LENGTH)] = None,
    ) -> ToolResult:
        search_result = service.search(
            ctx.actor_provider(),
            query,
            kinds,
            limit=limit,
            cursor=cursor,
            correlation_id=request_correlation_id_or_new(),
        )
        closest = _closest(ctx.actor_provider(), query, search_result) if cursor is None else None
        if closest is not None:
            search_result = search_result.model_copy(
                update={"contacts": ContactSearchPage(hits=closest, next_cursor=None)}
            )
            rows = [
                f"- contact {hit.id} | {flat(hit.display_name, limit=TITLE_LIMIT)} | v{hit.version}"
                for hit in closest
            ]
            header = _closest_header([hit.display_name for hit in closest])
            return result(_structured(search_result), f"{rows_text(header, rows)}\n{CLOSEST_HINT}")
        structured = _structured(search_result)
        return result(structured, rows_text(_summary(search_result), _rows(search_result)))
