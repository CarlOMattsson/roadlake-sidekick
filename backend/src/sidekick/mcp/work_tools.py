"""The Work tools: Projects, Domains, Processes, Steps, Actions, views and Tasks."""

from __future__ import annotations

from fastmcp import FastMCP

from sidekick.mcp.project_tools import register_project_tools
from sidekick.mcp.step_tools import register_step_tools
from sidekick.mcp.task_tools import register_task_tools
from sidekick.mcp.tool_context import ToolContext
from sidekick.mcp.work_view_tools import register_work_view_tools


def register_work_tools(mcp: FastMCP, ctx: ToolContext) -> None:
    """Register every Work tool, in the order the tool list shows them."""

    register_project_tools(mcp, ctx)
    register_step_tools(mcp, ctx)
    register_work_view_tools(mcp, ctx)
    register_task_tools(mcp, ctx)
