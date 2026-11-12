"""Write tools refuse image data in free-text fields; plain text in the same fields is saved.

The host model reads a photo or screenshot itself and sends only text. A data URL or a long base64
block in a text field would store image bytes as record text, so the call is refused during
argument validation, before any service runs. The error names the field, never the value.
"""

from typing import Any
from uuid import uuid4

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from sidekick.api.app import create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.auth import MCP_SCOPES
from sidekick.shared.text_guard import IMAGE_DATA_REFUSED, MIN_BASE64_BLOCK, reject_image_data
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings

DATA_URL = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYAAAAAYAAjCB"
)
BASE64_BLOCK = "QUJDRA==" * 40  # 320 characters, no spaces
WORK_SCOPES = frozenset(
    {
        "contacts:read",
        "contacts:write",
        "journal:read",
        "journal:write",
        "projects:read",
        "projects:write",
        "tasks:read",
        "tasks:write",
    }
)


@pytest.mark.parametrize(
    "value",
    [
        DATA_URL,
        "DATA:IMAGE/JPEG;base64,/9j/4AAQSkZJRg==",
        BASE64_BLOCK,
        f"Kvitto nedan {BASE64_BLOCK}",
        "QUJDRA==" * (MIN_BASE64_BLOCK // 8),
        "Ab" * (MIN_BASE64_BLOCK // 2),
    ],
)
def test_image_data_and_base64_blocks_are_refused(value: str) -> None:
    with pytest.raises(ValueError, match="image data") as refused:
        reject_image_data(value)
    assert value not in str(refused.value)


def test_plain_text_and_short_runs_pass_unchanged() -> None:
    offer = "Offert på fredag. Ritningen skickas i morgon: https://example.com/offert?id=7"
    assert reject_image_data(None) is None
    assert reject_image_data(offer) == offer
    just_below = "A" * (MIN_BASE64_BLOCK - 1)
    assert reject_image_data(just_below) == just_below
    assert reject_image_data(f"x {just_below} y") == f"x {just_below} y"


def test_refusal_names_the_rule() -> None:
    assert IMAGE_DATA_REFUSED.startswith("text field must not contain image data")


# Each call is valid except for the one free-text field holding image data. Refusal happens during
# argument validation, so these need no database: a missing database would surface as a different
# error, which the message check below catches.
REFUSED_CALLS: list[tuple[str, dict[str, Any], str]] = [
    (
        "create_task",
        {"title": DATA_URL, "idempotency_key": "img-task-title-0001"},
        "title",
    ),
    (
        "create_task",
        {
            "title": "Flytta bilen",
            "idempotency_key": "img-task-desc-0001",
            "description": BASE64_BLOCK,
        },
        "description",
    ),
    (
        "create_task",
        {"title": "Flytta bilen", "idempotency_key": "img-task-tag-0001", "tags": [DATA_URL]},
        "tags",
    ),
    (
        "update_task",
        {
            "task_id": str(uuid4()),
            "version": 1,
            "idempotency_key": "img-task-update-0001",
            "changes": {"description": DATA_URL},
        },
        "changes.description",
    ),
    (
        "create_contact",
        {
            "display_name": "Sara",
            "idempotency_key": "img-contact-create-0001",
            "context_note": DATA_URL,
        },
        "context_note",
    ),
    (
        "update_contact",
        {
            "contact_id": str(uuid4()),
            "expected_version": 1,
            "idempotency_key": "img-contact-update-0001",
            "changes": {"context_note": BASE64_BLOCK},
        },
        "changes.context_note",
    ),
    (
        "write_journal_entry",
        {
            "journal_date": "2026-10-29",
            "title": "Foto från mötet",
            "source_text": BASE64_BLOCK,
            "idempotency_key": "img-journal-source-0001",
        },
        "source_text",
    ),
    (
        "write_journal_entry",
        {
            "journal_date": "2026-10-29",
            "title": "Foto från mötet",
            "source_text": "Mötet med Sara gick bra.",
            "key_points": [{"kind": "decision", "text": DATA_URL}],
            "idempotency_key": "img-journal-point-0001",
        },
        "key_points",
    ),
    (
        "create_manual_journal_entry",
        {
            "source_id": str(uuid4()),
            "title": "Foto från mötet",
            "summary": DATA_URL,
            "key_points": [],
            "project_ids": [],
            "task_ids": [],
            "contact_ids": [],
            "idempotency_key": "img-manual-summary-0001",
        },
        "summary",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool", "arguments", "field"), REFUSED_CALLS)
async def test_write_tools_refuse_image_data_in_text_fields(
    tool: str, arguments: dict[str, Any], field: str
) -> None:
    # Input is refused before the reply-scope rule looks at who is calling; the caller still has
    # every scope, so the refusal below can only come from the text guard.
    actor = Actor(uuid4(), frozenset(MCP_SCOPES))
    server = create_mcp_server(
        create_container(make_settings()), actor_provider=lambda: actor, enable_auth=False
    )

    async with Client(server) as client:
        with pytest.raises(ToolError) as refused:
            await client.call_tool(tool, arguments)

    message = str(refused.value)
    assert "invalid value" in message
    assert field in message
    assert "base64" not in message
    assert "data:image" not in message.lower()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_plain_text_in_the_same_fields_is_saved() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    actor = Actor(owner, WORK_SCOPES)
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        task = await client.call_tool(
            "create_task",
            {
                "title": "Skicka ritningen i morgon",
                "idempotency_key": "img-plain-task-0001",
                "description": "Offert på fredag. Dotter börjar skolan i januari.",
                "tags": ["offert"],
            },
        )
        assert task.structured_content is not None
        assert task.structured_content["task"]["title"] == "Skicka ritningen i morgon"

        contact = await client.call_tool(
            "create_contact",
            {
                "display_name": "Sara",
                "idempotency_key": "img-plain-contact-0001",
                "context_note": "Byggbolaget. Vill ha offerten på fredag.",
            },
        )
        assert contact.structured_content is not None
        assert contact.structured_content["contact"]["display_name"] == "Sara"


@pytest.mark.asyncio
async def test_server_instructions_state_the_voice_and_photo_rules() -> None:
    server = create_mcp_server(create_container(make_settings()), enable_auth=False)
    instructions = server.instructions or ""
    for phrase in (
        "Voice debrief",
        "max 5 calls",
        "base64",
        "create_contact",
        "one or two sentences",
        "Always a card: add_shopping_items",
        "list_shopping_lists, then get_shopping_list",
        "create_task with due_at; say Sidekick sends no notification",
    ):
        assert phrase in instructions
