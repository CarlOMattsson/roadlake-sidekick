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

from collections.abc import Mapping
from typing import cast

from fastmcp import FastMCP
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import ToolResult
from mcp.types import CallToolRequestParams

from sidekick.shared.change_source import ChangeSource, change_source

APP_ORIGIN_META = "com.roadlake.sidekick/origin"
"""The `_meta` key the Sidekick app puts on its `tools/call`; its value is `"app"`."""


def source_of_tool(meta: Mapping[str, object] | None) -> ChangeSource:
    """`you` for a tool whose `_meta.ui.visibility` is exactly `["app"]`, else `claude`."""

    ui: object = (meta or {}).get("ui")
    visibility = cast("dict[str, object]", ui).get("visibility") if isinstance(ui, dict) else None
    return "you" if visibility == ["app"] else "claude"


def source_of_call(
    tool_meta: Mapping[str, object] | None, call_meta: Mapping[str, object] | None
) -> ChangeSource:
    """`you` for an app-only tool or a call the app marked as its own, else `claude`."""

    if (call_meta or {}).get(APP_ORIGIN_META) == "app":
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
