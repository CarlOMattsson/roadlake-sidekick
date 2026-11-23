"""Tell the audit trail whether an MCP tool call is the model's or the owner's app.

A tool hidden from the model (`visibility=["app"]`) is only called by the Sidekick app on the
owner's behalf, so its changes are the owner's. The app also calls the tools Claude uses; those
calls carry `APP_ORIGIN_META` in the request's `_meta`, which the app's bridge adds to every
`tools/call` and which the model cannot set (it only sends arguments). Any other call is a model
call, so its changes are Claude's. The mark is a label for the history, not a permission: every
call is authorized by its scopes as before. The middleware sets the source for the duration of the
call; the audit writer reads it (`sidekick.shared.change_source`). It reads the tool's listed
visibility and the request's origin mark, never its arguments.
"""

import logging
from collections.abc import Mapping
from typing import Final, cast

from fastmcp import FastMCP
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import ToolResult
from mcp.types import CallToolRequestParams

from sidekick.mcp.correlation import UNKNOWN_CORRELATION
from sidekick.mcp.results import error_result
from sidekick.shared.change_source import ChangeSource, change_source
from sidekick.shared.errors import PermissionDeniedError
from sidekick.shared.observability import safe_log_fields

LOGGER = logging.getLogger("sidekick.mcp.tool")

APP_ORIGIN_META = "com.roadlake.sidekick/origin"
"""The `_meta` key the Sidekick app puts on its `tools/call`; its value is `"app"`."""


REQUIRES_PERSON_META: Final = "anthropic/requiresUserInteraction"
"""The tool meta that marks a decision only the owner makes, confirmed by a person at every call."""


REQUIRES_APP_META: Final = "com.roadlake.sidekick/requiresApp"
"""The tool meta that marks a tool only the app may call, without a person confirming each call.

A tool that takes or returns the bytes of a photo carries it: it is hidden from the model, and the
server refuses a call that does not come from the app, so a model that names the tool is refused.
"""


def called_by_app(call_meta: Mapping[str, object] | None) -> bool:
    """Whether the request carries the app's origin mark, which the model cannot add."""

    return (call_meta or {}).get(APP_ORIGIN_META) == "app"


def source_of_tool(meta: Mapping[str, object] | None) -> ChangeSource:
    """`you` for a tool whose `_meta.ui.visibility` is exactly `["app"]`, else `claude`."""

    ui: object = (meta or {}).get("ui")
    visibility = cast("dict[str, object]", ui).get("visibility") if isinstance(ui, dict) else None
    return "you" if visibility == ["app"] else "claude"


def source_of_call(
    tool_meta: Mapping[str, object] | None, call_meta: Mapping[str, object] | None
) -> ChangeSource:
    """`you` for an app-only tool or a call the app marked as its own, else `claude`."""

    if called_by_app(call_meta):
        return "you"
    return source_of_tool(tool_meta)


class ToolChangeSource(Middleware):
    """Run each `tools/call` with the change source of the tool that was called."""

    def __init__(self, mcp: FastMCP) -> None:
        self._mcp = mcp

    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        tool = await self._mcp.get_tool(context.message.name)
        request = context.fastmcp_context.request_context if context.fastmcp_context else None
        source = source_of_call(
            tool.meta if tool is not None else None, request.meta if request else None
        )
        with change_source(source):
            return await call_next(context)


def is_owner_decision(tool_meta: Mapping[str, object] | None) -> bool:
    """Whether the tool is hidden from the model and always confirmed by a person (an approval)."""

    return (
        source_of_tool(tool_meta) == "you" and (tool_meta or {}).get(REQUIRES_PERSON_META) is True
    )


def requires_app(tool_meta: Mapping[str, object] | None) -> bool:
    """Whether the server refuses the tool unless the request comes from the app.

    That holds for an owner's decision and for every tool that carries `REQUIRES_APP_META`; each is
    hidden from the model as well.
    """

    return source_of_tool(tool_meta) == "you" and (
        (tool_meta or {}).get(REQUIRES_PERSON_META) is True
        or (tool_meta or {}).get(REQUIRES_APP_META) is True
    )


class OwnerDecisionsFromTheApp(Middleware):
    """Refuse a call by name to an app-only tool unless the request comes from the app.

    An approval, a spending decision or a photo is hidden from the model, but hiding is only a
    listing. The server also refuses the call unless it carries the app's origin mark, which the
    model cannot set, so a model that names the tool is refused before anything is read or written,
    and the audit trail never labels such a call as the owner's. The tools are those that
    `requires_app` names, by their metadata and never by a list of names. The refusal is the
    ordinary `forbidden` result with the reason `app_only`.
    """

    def __init__(self, mcp: FastMCP) -> None:
        self._mcp = mcp

    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        tool = await self._mcp.get_tool(context.message.name)
        if tool is None or not requires_app(tool.meta):
            return await call_next(context)
        request = context.fastmcp_context.request_context if context.fastmcp_context else None
        if called_by_app(request.meta if request else None):
            return await call_next(context)
        error = PermissionDeniedError("this is done in the app", reason="app_only")
        refusal = error_result(error)
        LOGGER.info(
            "mcp_tool_failed",
            extra=safe_log_fields(
                {
                    "correlation_id": (refusal.structured_content or {}).get(
                        "correlation_id", UNKNOWN_CORRELATION
                    ),
                    "mcp_tool_name": context.message.name,
                    "mcp_error_class": type(error).__name__,
                }
            ),
        )
        return refusal
