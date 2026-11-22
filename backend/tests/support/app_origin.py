"""The request mark the Sidekick app puts on its calls, for tests that act as the app.

An owner's decision, such as approving a plan or an automation, is refused unless the request
carries this mark, so a test that makes such a call by name sends it the way the app does.
"""

from sidekick.mcp.change_source import APP_ORIGIN_META

APP_ORIGIN: dict[str, str] = {APP_ORIGIN_META: "app"}

OWNER_DECISIONS = frozenset({"approve_ai_plan", "run_ai_plan", "approve_automation"})


def origin_for(tool: str) -> dict[str, str] | None:
    """The app's mark for an owner's decision, nothing for any other tool."""

    return APP_ORIGIN if tool in OWNER_DECISIONS else None
