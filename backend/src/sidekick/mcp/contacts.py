"""The Contact and relationship tools."""

from __future__ import annotations

from fastmcp import FastMCP

from sidekick.mcp.contact_link_tools import register_contact_link_tools
from sidekick.mcp.contact_read_tools import register_contact_read_tools
from sidekick.mcp.contact_write_tools import register_contact_write_tools
from sidekick.mcp.tool_context import ToolContext


def register_contacts_tools(mcp: FastMCP, ctx: ToolContext) -> None:
    """Register all 13 curated Contact and relationship tools, in the order the list shows them."""

    register_contact_read_tools(mcp, ctx)
    register_contact_write_tools(mcp, ctx)
    register_contact_link_tools(mcp, ctx)
