"""The four Journal draft-review tools are explicit owner commands.

`finalize_journal_draft` and `reject_journal_draft` turn an AI-derived draft into a committed
entry (and possibly Task changes) or discard it; this file pins the exact set of review tools.
"""

from sidekick.mcp.journal import JOURNAL_REVIEW_TOOL_NAMES

REVIEW_TOOLS = (
    "get_journal_draft",
    "update_journal_draft",
    "reject_journal_draft",
    "finalize_journal_draft",
)


def test_the_review_tool_names_are_exactly_the_four_pinned_here() -> None:
    assert JOURNAL_REVIEW_TOOL_NAMES == REVIEW_TOOLS
