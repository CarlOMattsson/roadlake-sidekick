"""Shared test helpers moved out of `tests/mcp/test_journal_review.py`."""

from typing import Any
from uuid import UUID

from fastmcp import Client


async def call(client: Client, tool: str, arguments: dict[str, Any]) -> Any:
    return await client.call_tool(tool, arguments, raise_on_error=False)


async def read_draft(client: Client, draft_id: UUID, *, content: bool = True) -> dict[str, Any]:
    response = await call(
        client, "get_journal_draft", {"draft_id": str(draft_id), "include_content": content}
    )
    assert not response.is_error, response.structured_content
    return response.structured_content


def update_args(draft: dict[str, Any], key: str, **overrides: Any) -> dict[str, Any]:
    body = draft["draft"]
    arguments: dict[str, Any] = {
        "draft_id": body["id"],
        "expected_version": body["version"],
        "title": "Granskad titel",
        "summary": "Granskad sammanfattning.",
        "key_points": [{"kind": "decision", "text": "Ett granskat beslut."}],
        "task_proposals": body["task_proposals"],
        "idempotency_key": key,
    }
    arguments.update(overrides)
    return arguments


def finalize_args(draft: dict[str, Any], key: str, **overrides: Any) -> dict[str, Any]:
    arguments = update_args(draft, key)
    arguments["relation_selection"] = {"project_ids": [], "task_ids": [], "contact_ids": []}
    arguments.update(overrides)
    return arguments
