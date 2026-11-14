"""A write tool that answers with a record also needs the scope to read that record.

A write use case checks only its write scope (`tasks:write`), but its reply carries the record as
stored: the description of a Task that `complete_task` just completed, the title of a Step, the
fields of a Contact. Without this rule a token that may write but not read could read through the
reply. Every tool that is not read-only is therefore listed here exactly once:

- `WRITE_REPLY_READ_SCOPES` names the read scope its reply needs. The call is refused up front, so
  an idempotent replay, a stale version and a first write all answer `forbidden`, and no row,
  audit event or idempotency key is committed.
- `RECEIPT_ONLY_WRITES` answers with identifiers and flags only (or checks the read scope itself),
  so it needs nothing more.

Tools that write the owner's own journal text answer with that text and stay write-only (D-076: the
journal is written by hand, no AI).
A contract test requires every write tool to be in exactly one of the two, so a new tool cannot be
added without choosing. The companion adapter applies the same rule with `CompanionOperation.also`
and a receipt for a device that may not read (`sidekick.api.companion_tasks`).
"""

import logging
from collections.abc import Callable, Mapping
from typing import Final

from fastmcp import FastMCP
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import ToolResult
from mcp.types import CallToolRequestParams

from sidekick.mcp.correlation import UNKNOWN_CORRELATION
from sidekick.mcp.results import error_result
from sidekick.shared.errors import AuthenticationRequiredError, PermissionDeniedError
from sidekick.shared.observability import safe_log_fields
from sidekick.shared.types import Actor

LOGGER = logging.getLogger("sidekick.mcp.tool")

_TASK_READ: Final = "tasks:read"
_STEP_AND_ACTION_TOOLS: Final = (
    "create_task_step",
    "update_task_step",
    "complete_task_step",
    "archive_task_step",
    "restore_task_step",
    "reorder_task_steps",
    "create_step_action",
    "update_step_action",
    "complete_step_action",
    "archive_step_action",
    "restore_step_action",
    "reorder_step_actions",
)

WRITE_REPLY_READ_SCOPES: Final[Mapping[str, str]] = {
    # Work: Tasks, Steps and Actions are read with `tasks:read`.
    **dict.fromkeys(
        (
            "create_task",
            "create_tasks",
            "update_task",
            "complete_task",
            "reschedule_tasks",  # the spoken line names the moved Tasks by title
            "link_external_reference_to_task",
            *_STEP_AND_ACTION_TOOLS,
        ),
        _TASK_READ,
    ),
    # Work: Projects, Domains, Processes and saved views are read with `projects:read`.
    **dict.fromkeys(
        (
            "create_project",
            "update_project",
            "create_domain",
            "update_domain",
            "create_process",
            "update_process",
            "create_saved_work_view",
            "update_saved_work_view",
            "archive_saved_work_view",
            "restore_saved_work_view",
        ),
        "projects:read",
    ),
    **dict.fromkeys(
        (
            "create_contact",
            "update_contact",
            "archive_contact",
            "restore_contact",
            "add_contact_alias",
            "remove_contact_alias",
        ),
        "contacts:read",
    ),
    **dict.fromkeys(
        (
            "create_shopping_list",
            "update_shopping_list",
            "add_shopping_items",
            "update_shopping_item",
            "set_shopping_item_purchased",
            "set_shopping_items_purchased",
        ),
        "shopping:read",
    ),
    **dict.fromkeys(
        (
            "update_journal_entry",
            "update_journal_draft",
            "reject_journal_draft",
            "finalize_journal_draft",
        ),
        "journal:read",
    ),
}

RECEIPT_ONLY_WRITES: Final[frozenset[str]] = frozenset(
    {
        # Identifiers and flags only; the linking use cases also require both sides' read scope.
        "link_contact_to_project",
        "unlink_contact_from_project",
        "link_contact_to_task",
        "unlink_contact_from_task",
        "unlink_external_reference_from_task",
        "reorder_work_board_column",  # task ids and versions
        "exclude_from_memory",
        # The trash tools leave out the label unless the caller holds the kind's read scope
        # (`sidekick.mcp.lifecycle._record`): a receipt of id, version and time.
        "move_to_trash",
        "restore_from_trash",
        # Memory settings carry per-domain scope checks of their own
        # (`sidekick.memory.application.settings`).
        "set_memory_settings",
        # The installation licence key; reaches no record.
        "set_license_key",
        # The journal tools that write the user's own text answer with that text and stay
        # write-only on purpose (the journal is written by hand, not by the assistant; pinned
        # by tests/mcp/test_journal_writes.py).
        "create_journal_source",
        "create_manual_journal_entry",
        "write_journal_entry",
        "set_daily_journal_summary",
    }
)


def missing_reply_scope(tool_name: str, actor: Actor) -> str | None:
    """The read scope a write tool's reply needs and the actor lacks, else None."""

    scope = WRITE_REPLY_READ_SCOPES.get(tool_name)
    return scope if scope is not None and scope not in actor.scopes else None


class WriteReplyScopes(Middleware):
    """Refuse a write tool whose reply needs a read scope the caller does not hold.

    Runs before the tool, so nothing is written, replayed or compared by version for a caller that
    could not be shown the answer. The refusal is the ordinary `forbidden` result with a
    correlation id, logged by class name only. It fails closed: a tool that is not read-only and
    is in neither `WRITE_REPLY_READ_SCOPES` nor `RECEIPT_ONLY_WRITES` is refused too, so a write
    tool added without being classified never answers with a record.
    """

    def __init__(self, mcp: FastMCP, actor_provider: Callable[[], Actor]) -> None:
        self._mcp = mcp
        self._actor_provider = actor_provider

    async def _is_unclassified_write(self, name: str) -> bool:
        if name in WRITE_REPLY_READ_SCOPES or name in RECEIPT_ONLY_WRITES:
            return False
        tool = await self._mcp.get_tool(name)
        if tool is None:  # not a tool of this server; the call fails as unknown further on
            return False
        return getattr(tool.annotations, "readOnlyHint", None) is not True

    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        name = context.message.name
        unclassified = await self._is_unclassified_write(name)
        if name not in WRITE_REPLY_READ_SCOPES and not unclassified:
            return await call_next(context)
        try:
            if unclassified:
                raise PermissionDeniedError("write tool without a reply-scope rule")
            if missing_reply_scope(name, self._actor_provider()) is not None:
                raise PermissionDeniedError("missing required scope")
        except (AuthenticationRequiredError, PermissionDeniedError) as error:
            refusal = error_result(error)
            LOGGER.info(
                "mcp_tool_failed",
                extra=safe_log_fields(
                    {
                        "correlation_id": (refusal.structured_content or {}).get(
                            "correlation_id", UNKNOWN_CORRELATION
                        ),
                        "mcp_tool_name": name,
                        "mcp_error_class": type(error).__name__,
                    }
                ),
            )
            return refusal
        return await call_next(context)
