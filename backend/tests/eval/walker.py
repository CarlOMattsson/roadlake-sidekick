"""A scripted owner walking through the review queue over MCP, counting what it costs.

The walker talks to the real MCP server in process (no HTTP), the way Claude does: it reads a page
of `get_review_queue`, decides each row by its bucket and saves the decisions with `review_tasks`.
Every tool call is counted; the reads also record how many characters of text Claude would get.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from fastmcp import Client
from mcp.types import TextContent

from sidekick.mcp.server import create_mcp_server
from sidekick.tasks.application.review import MAX_REVIEW_PAGE
from tests.eval.scenario import Scenario

# What the owner says about each bucket, in the words of `review_tasks`.
DECISION_BY_BUCKET: dict[str, dict[str, str]] = {
    "likely_done": {"decision": "done"},
    "long_overdue": {"decision": "move", "when": "next_week"},
    "follow_up_due": {"decision": "waiting", "follow_up": "tomorrow"},
    "overdue": {"decision": "move", "when": "tomorrow"},
    "other": {"decision": "keep"},
}
# How many decisions the guide lets pass before they are saved.
CHECKPOINT = 5

Row = dict[str, Any]


def connect(scenario: Scenario) -> Client[Any]:
    """A client of the whole server, as the owner; each one is a new conversation."""

    server = create_mcp_server(
        scenario.container, actor_provider=lambda: scenario.actor, enable_auth=False
    )
    return Client(server)


def decision_for(row: Row) -> dict[str, Any]:
    return {
        "task_id": row["id"],
        "expected_version": row["version"],
        **DECISION_BY_BUCKET[row["bucket"]],
    }


def _text(result: Any) -> str:
    block = result.content[0]
    assert isinstance(block, TextContent)
    return block.text


@dataclass
class Walker:
    client: Client[Any]
    reads: list[int] = field(default_factory=list)
    """Characters of text in each counted read."""
    saves: list[int] = field(default_factory=list)
    """Decisions in each counted save that went through."""
    saved_ids: list[str] = field(default_factory=list)
    calls: int = 0

    async def read(self, **arguments: Any) -> dict[str, Any]:
        """One counted `get_review_queue`; the structured page."""

        result = await self.client.call_tool("get_review_queue", arguments)
        self.calls += 1
        self.reads.append(len(_text(result)))
        return dict(result.structured_content or {})

    async def save(self, rows: list[Row]) -> Any:
        """One counted `review_tasks` with the scripted decision of each row; the raw result."""

        result = await self.client.call_tool(
            "review_tasks",
            {
                "items": [decision_for(row) for row in rows],
                "idempotency_key": f"eval-{uuid4().hex}",
            },
            raise_on_error=False,
        )
        self.calls += 1
        if not result.is_error:
            self.saves.append(len(rows))
            self.saved_ids.extend(row["id"] for row in rows)
        return result

    async def order(self) -> list[Row]:
        """The whole queue as it stands, page by page. Not counted: it is how the test knows."""

        rows: list[Row] = []
        cursor: str | None = None
        while True:
            arguments: dict[str, Any] = {"scope": "all", "limit": MAX_REVIEW_PAGE}
            if cursor is not None:
                arguments["cursor"] = cursor
            page = (await self.client.call_tool("get_review_queue", arguments)).structured_content
            assert page is not None
            rows.extend(page["tasks"])
            cursor = page["next_cursor"]
            if cursor is None:
                return rows

    async def walk(self, *, stop_after: int | None = None) -> int:
        """Read, decide and save until the queue is empty or `stop_after` decisions are saved.

        Saved Tasks leave the queue, so every read starts at its head. Decisions are saved every
        `CHECKPOINT`, which is how often the guide asks Claude to save.
        """

        decided = 0
        while True:
            page = await self.read(scope="all", limit=MAX_REVIEW_PAGE)
            rows: list[Row] = page["tasks"]
            for start in range(0, len(rows), CHECKPOINT):
                chunk = rows[start : start + CHECKPOINT]
                if stop_after is not None:
                    chunk = chunk[: stop_after - decided]
                if not chunk:
                    return decided
                result = await self.save(chunk)
                assert not result.is_error, result.structured_content
                decided += len(chunk)
            if page["next_cursor"] is None or (stop_after is not None and decided >= stop_after):
                return decided
