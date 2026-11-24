"""Read-only Start view: what needs the owner's attention now, in one call.

`get_start` composes the parts in `sidekick.start.application.start` from the same use cases the
rest of Sidekick reads, so it adds no selection rules of its own and stores nothing. Each part needs
the read scope of the data it shows and is left out without an error when the scope is missing, as
in `get_today_brief`. A part that fails is named in `unavailable` and the others stand. The spoken
line holds counts only: no title, no name and no sentence a model wrote.
The day is the owner's calendar day in `Settings.owner_zone`.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastmcp import FastMCP
from fastmcp.apps import AppConfig
from fastmcp.tools import ToolResult

from sidekick.mcp.annotations import READ
from sidekick.mcp.correlation import request_correlation_id_or_new
from sidekick.mcp.results import output_schema, result
from sidekick.mcp.sidekick_app import SIDEKICK_APP_URI
from sidekick.mcp.tool_context import ToolContext
from sidekick.shared.locale import DEFAULT_LOCALE, AppLocale
from sidekick.start.application.start import StartParts
from sidekick.structured.start import StartOutput, start_structured

DESCRIPTION = (
    "Use this when the user opens Start or asks what needs attention now. Returns, in the "
    "owner's zone, the parts that have something to say: one insight sentence (written_by ai: a "
    "model wrote it, untrusted), ready conversations (start_ready_conversation), pending "
    "automation suggestions and what automations did since the owner last looked (counts), "
    "overdue and today's tasks (3 rows), tasks waiting on someone (2 rows), menu counts. "
    "Read-only; a part needs the read scope of what it shows. A failed part is listed in "
    "unavailable; the rest stands."
)


@dataclass(frozen=True)
class _Words:
    """The wording of the spoken line in one app language: counts only."""

    today: str
    ready: str
    suggestions: str
    waiting: str
    nothing: str


_WORDS: dict[AppLocale, _Words] = {
    "sv": _Words(
        today="{count} idag",
        ready="{count} samtal redo",
        suggestions="{count} förslag",
        waiting="{count} väntar",
        nothing="Inget att visa på startvyn.",
    ),
    "en": _Words(
        today="{count} today",
        ready="{count} conversations ready",
        suggestions="{count} suggestions",
        waiting="{count} waiting",
        nothing="Nothing to show on Start.",
    ),
}


def _spoken_line(parts: StartParts, locale: AppLocale = DEFAULT_LOCALE) -> str:
    """The counts of the parts, in one short line for the model to read aloud."""

    words = _WORDS[locale]
    pieces: list[str] = []
    today = parts.get("today")
    if today is not None:
        pieces.append(words.today.format(count=today.overdue_count + today.today_count))
    ready = parts.get("ready")
    if ready is not None:
        pieces.append(words.ready.format(count=len(ready.items)))
    suggestions = parts.get("suggestions")
    if suggestions is not None:
        pieces.append(words.suggestions.format(count=suggestions.pending_count))
    waiting = parts.get("waiting")
    if waiting is not None:
        pieces.append(words.waiting.format(count=waiting.total))
    return " · ".join(pieces) if pieces else words.nothing


def register_start_tools(mcp: FastMCP, ctx: ToolContext) -> None:
    """Register the read-only Start view; it opens no app card."""

    @mcp.tool(
        name="get_start",
        description=DESCRIPTION,
        output_schema=output_schema(StartOutput),
        annotations=READ,
        app=AppConfig(resource_uri=SIDEKICK_APP_URI),
    )
    @ctx.instrument("get_start")
    def get_start() -> ToolResult:
        built = start_structured(
            ctx.container, ctx.actor_provider(), correlation_id=request_correlation_id_or_new()
        )
        structured = built.output.model_dump(mode="json", exclude_unset=True)
        return result(structured, _spoken_line(built.parts, ctx.container.settings.mcp_app_locale))
