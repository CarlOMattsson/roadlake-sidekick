"""`list_assistant_activity` is a read-only owner tool.

It reads the Activity Center for the owner's control view. No automation-settings tool exists on
the MCP surface (that read needs a session-only scope).
"""

import pytest

from sidekick.api.app import create_container
from sidekick.mcp.server import create_mcp_server
from tests.support.settings import make_settings

TOOL = "list_assistant_activity"
REGISTRY_TOOLS = {
    "list_automations",
    "get_automation",
    "save_automation",
    "approve_automation",
    "start_automation_run",
    "record_automation_results",
    "get_automation_report",
    "mark_automation_report_seen",
    "export_automation_report_html",
}


@pytest.mark.asyncio
async def test_it_is_the_only_owner_control_tool_and_it_is_read_only() -> None:
    server = create_mcp_server(create_container(make_settings()), enable_auth=False)
    tools = {tool.name: tool for tool in await server.list_tools()}

    assert tools[TOOL].annotations is not None
    assert tools[TOOL].annotations.readOnlyHint is True
    assert tools[TOOL].annotations.destructiveHint is False
    # No policy or pause tool, and the only automation tools are the registry's four, the
    # runner's two and the report's three (ADR-013): none of them pauses or settles anything, a
    # run only records proposals for the owner to decide, and the report only reads and marks.
    controls = {
        name
        for name in tools
        if any(word in name for word in ("automation", "policy", "pause", "activity"))
    }
    assert controls == {TOOL, *REGISTRY_TOOLS}
