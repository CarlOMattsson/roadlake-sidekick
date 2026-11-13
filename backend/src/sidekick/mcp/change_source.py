"""Tell the audit trail whether an MCP tool call is the model's or the owner's app.

A tool hidden from the model (`visibility=["app"]`) is only called by the Sidekick app on the
owner's behalf, so its changes are the owner's. Any other tool is a model tool, so its changes are
Claude's. The middleware sets the source for the duration of the call; the audit writer reads it
(`sidekick.shared.change_source`). It reads the tool's listed visibility and never its arguments.
"""

from collections.abc import Mapping
from typing import cast

from fastmcp import FastMCP
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import ToolResult
from mcp.types import CallToolRequestParams

from sidekick.shared.change_source import ChangeSource, change_source


def source_of_tool(meta: Mapping[str, object] | None) -> ChangeSource:
    """`you` for a tool whose `_meta.ui.visibility` is exactly `["app"]`, else `claude`."""

    ui: object = (meta or {}).get("ui")
    visibility = cast("dict[str, object]", ui).get("visibility") if isinstance(ui, dict) else None
    return "you" if visibility == ["app"] else "claude"


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
        with change_source(source_of_tool(tool.meta if tool is not None else None)):
            return await call_next(context)
