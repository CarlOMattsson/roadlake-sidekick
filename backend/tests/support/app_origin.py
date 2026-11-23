"""The request mark the Sidekick app puts on its calls, for tests that act as the app.

An owner's decision, such as approving a plan or an automation, is refused unless the request
carries this mark, so a test that makes such a call by name sends it the way the app does.
"""

from sidekick.mcp.change_source import APP_ORIGIN_META
from sidekick.mcp.journal_photo_tools import JOURNAL_PHOTO_TOOL_NAMES

APP_ORIGIN: dict[str, str] = {APP_ORIGIN_META: "app"}

OWNER_DECISIONS = frozenset({"approve_ai_plan", "run_ai_plan", "approve_automation"})

AUTOMATION_REPORT_APP_TOOLS = frozenset(
    {"mark_automation_report_seen", "export_automation_report_html"}
)

# Every tool the server refuses unless the request comes from the app: the decisions above, the
# Journal photo tools, which take or return the bytes of a photo, and the two report tools that move
# the owner's mark or hand a page to the app's download, and the owner's approval of a whole group
# of suggestions.
APP_ONLY_CALLS = (
    OWNER_DECISIONS
    | frozenset(JOURNAL_PHOTO_TOOL_NAMES)
    | AUTOMATION_REPORT_APP_TOOLS
    | frozenset({"approve_suggestion_group"})
)


def origin_for(tool: str) -> dict[str, str] | None:
    """The app's mark for a tool only the app may call, nothing for any other tool."""

    return APP_ORIGIN if tool in APP_ONLY_CALLS else None
