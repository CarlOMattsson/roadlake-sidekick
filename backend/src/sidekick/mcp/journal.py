"""Fifteen curated Journal MCP tools over the authoritative Journal use cases.

Four of them review an AI-derived draft: `get_journal_draft` reads it, and
`update_journal_draft`, `reject_journal_draft` and `finalize_journal_draft` are explicit owner
commands that call the same use cases as the REST routes.
"""

from __future__ import annotations

from fastmcp import FastMCP

from sidekick.mcp.journal_draft_tools import register_journal_draft_tools
from sidekick.mcp.journal_read_tools import register_journal_read_tools
from sidekick.mcp.journal_text import JournalToolContext
from sidekick.mcp.journal_write_tools import register_journal_write_tools
from sidekick.mcp.tool_context import ToolContext

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


def register_journal_tools(mcp: FastMCP, ctx: ToolContext) -> None:
    """Register the fifteen bounded Journal tools; none of them starts AI processing."""

    journal_ctx = JournalToolContext(ctx.container, ctx.actor_provider, ctx.instrument)
    register_journal_read_tools(mcp, journal_ctx)
    register_journal_write_tools(mcp, journal_ctx)
    register_journal_draft_tools(mcp, journal_ctx)
