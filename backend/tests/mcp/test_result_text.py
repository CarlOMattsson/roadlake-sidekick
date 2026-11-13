"""Model-facing MCP text carries the structured result JSON (ids included).

claude.ai passes only the text blocks of a tool result to the model. Block 1 is the summary line
and block 2 is the compact JSON of the result, so the model can see ids. Journal tools put their
full structured result in block 2, owner text included (D-060).
"""

import copy
import json
import re
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import NAMESPACE_OID, UUID, uuid5
from zoneinfo import ZoneInfo

import pytest
from fastmcp import Client

from sidekick.api.app import create_container
from sidekick.mcp.results import _LARGE_RESULT_NOTE, _TEXT_JSON_LIMIT, card_result, result
from sidekick.mcp.server import create_mcp_server
from sidekick.mcp.text import (
    AGENDA_NOTE,
    AGENDA_ROW_LIMIT,
    BOARD_ROW_LIMIT,
    CARD_NOTE,
    EMPTY_WORK_NOTE,
    card_row,
    card_rows,
    card_text,
    count_phrase,
    spoken_date,
    spoken_status,
)
from sidekick.mcp.work_text import (
    HierarchyRow,
    TextRow,
    agenda_card_text,
    agenda_sentence,
    board_card_text,
    board_sentence,
    hierarchy_card_text,
    hierarchy_indents,
    list_text,
    waiting_agenda_text,
    work_item_sentence,
)
from sidekick.shared.types import Actor
from sidekick.structured.work_records import WorkItemRecord
from tests.db import database_factory
from tests.support.settings import make_settings

JOURNAL_SENTINEL = "JOURNAL-TEXT-SENTINEL-7f3a9c"


def _summary_and_json(tool_result: Any) -> tuple[str, dict[str, Any]]:
    assert len(tool_result.content) == 2, "expected a summary block and a JSON block"
    summary = tool_result.content[0].text
    decoded = json.loads(tool_result.content[1].text)
    assert isinstance(decoded, dict)
    return summary, decoded


def _block_two_text(tool_result: Any) -> str:
    text: str = tool_result.content[1].text
    return text


def _card_text(tool_result: Any) -> str:
    """The text of an app card result: one block, with no JSON block."""
    assert len(tool_result.content) == 1, "expected one text block for the card"
    text: str = tool_result.content[0].text
    return text


def _without_empty(value: Any) -> Any:
    """Expected block 2 for a structured result: keys with None or [] values are left out."""

    if isinstance(value, dict):
        return {
            key: _without_empty(item)
            for key, item in value.items()
            if item is not None and item != []
        }
    if isinstance(value, list):
        return [_without_empty(item) for item in value]
    return value


def test_result_text_is_summary_block_followed_by_compact_json() -> None:
    contact_id = UUID("0f8fad5b-d9cb-469f-a165-70867728950e")
    tool_result = result(
        {
            "id": contact_id,
            "created_at": datetime(2026, 10, 25, 12, 0, tzinfo=UTC),
            "amount": Decimal("1.50"),
            "display_name": "Åsa",
        },
        "Created the Contact.",
    )

    assert len(tool_result.content) == 2
    assert tool_result.content[0].text == "Created the Contact."
    json_block = tool_result.content[1].text
    assert "\n" not in json_block
    assert ": " not in json_block
    decoded = json.loads(json_block)
    assert decoded["id"] == str(contact_id)
    assert decoded["amount"] == "1.50"
    assert decoded["display_name"] == "Åsa"
    assert "Åsa" in json_block


def test_result_text_json_can_replace_the_text_block_without_touching_structured_content() -> None:
    structured = {"entry": {"id": "entry-1", "title": "Private title"}}
    tool_result = result(structured, "Returned.", text_json={"entry": {"id": "entry-1"}})

    assert tool_result.structured_content == structured
    assert json.loads(tool_result.content[1].text) == {"entry": {"id": "entry-1"}}


def test_result_text_json_is_pruned_the_same_way_as_structured_content() -> None:
    structured = {"entry": {"id": "entry-1", "title": "Private title", "key_points": []}}
    text_json = {"entry": {"id": "entry-1", "summary": None, "project_ids": [], "version": 2}}
    tool_result = result(structured, "Returned.", text_json=text_json)

    assert tool_result.structured_content == structured
    assert json.loads(_block_two_text(tool_result)) == {"entry": {"id": "entry-1", "version": 2}}


def test_result_text_leaves_out_null_and_empty_fields_and_keeps_structured_content() -> None:
    task = {
        "id": "task-1",
        "version": 3,
        "status": "open",
        "title": "Write brief",
        "due_at": None,
        "labels": [],
        "project_id": None,
        "steps": [],
        "notes": "",
    }
    structured = {
        "task": task,
        "tasks": [{**task, "id": f"task-{number}"} for number in range(25)],
        "cursor": None,
    }
    # Size of the same result serialized without the pruning rule.
    unpruned_size = len(json.dumps(structured, ensure_ascii=False, separators=(",", ":")))
    original = copy.deepcopy(structured)

    tool_result = result(structured, "Found 25 tasks.")

    assert tool_result.structured_content == original
    summary, decoded = _summary_and_json(tool_result)
    assert summary == "Found 25 tasks."
    assert len(_block_two_text(tool_result)) < unpruned_size
    assert decoded == _without_empty(original)
    # Null and empty fields are gone from block 2; id, version, status and non-empty values stay.
    expected_task = {
        "id": "task-1",
        "version": 3,
        "status": "open",
        "title": "Write brief",
        "notes": "",
    }
    assert decoded["task"] == expected_task
    assert "cursor" not in decoded
    assert len(decoded["tasks"]) == 25
    assert decoded["tasks"][24] == {**expected_task, "id": "task-24"}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_domains_text_contains_domain_ids() -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    user_id = container.auth.provision_user("owner", "Owner")
    actor = Actor(user_id, frozenset({"projects:read", "projects:write"}))
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        created = await client.call_tool(
            "create_domain", {"name": "Operations", "idempotency_key": "mcp-text-domain-001"}
        )
        domain_id = created.structured_content["domain"]["id"]
        listed = await client.call_tool("list_domains", {"limit": 10})

    summary, decoded = _summary_and_json(listed)
    lines = summary.splitlines()
    assert lines[0] == "Found 1 domain: Operations."
    assert lines[1].startswith(f"- {domain_id} | Operations | v1 |")
    assert decoded == _without_empty(listed.structured_content)
    assert [domain["id"] for domain in decoded["domains"]] == [domain_id]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_empty_domain_list_names_the_first_step() -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    user_id = container.auth.provision_user("owner", "Owner")
    actor = Actor(user_id, frozenset({"projects:read", "projects:write"}))
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        listed = await client.call_tool("list_domains", {"limit": 10})

    summary, _decoded = _summary_and_json(listed)
    assert summary == f"Found 0 domains.\n{EMPTY_WORK_NOTE}"


_LIST_UUID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_LIST_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _assert_first_line_names(first_line: str, lead: str, names: set[str]) -> None:
    """Line 1 has no id or ISO date and names up to three of `names`, counting the rest."""

    assert _LIST_UUID.search(first_line) is None
    assert _LIST_ISO_DATE.search(first_line) is None
    prefix = f"{lead}: "
    assert first_line.startswith(prefix)
    assert first_line.endswith(".")
    body = first_line[len(prefix) : -1]
    more = len(names) - 3
    if more > 0:
        tail = f" and {more} more"
        assert body.endswith(tail)
        body = body[: -len(tail)]
        shown = body.split(", ")
    else:
        shown = body.replace(" and ", ", ").split(", ")
    assert len(shown) == min(len(names), 3)
    assert len(set(shown)) == len(shown)
    assert set(shown) <= names


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_domains_first_line_names_three_domains_and_counts_the_rest() -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    user_id = container.auth.provision_user("owner", "Owner")
    actor = Actor(user_id, frozenset({"projects:read", "projects:write"}))
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        for index, name in enumerate(["Hem", "Jobb", "Hälsa", "Ekonomi"]):
            await client.call_tool(
                "create_domain",
                {"name": name, "idempotency_key": f"mcp-list-domain-{index:03d}"},
            )
        listed = await client.call_tool("list_domains", {"limit": 10})

    summary, _decoded = _summary_and_json(listed)
    names = {domain["name"] for domain in listed.structured_content["domains"]}
    assert names == {"Hem", "Jobb", "Hälsa", "Ekonomi"}
    _assert_first_line_names(summary.splitlines()[0], "Found 4 domains", names)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_processes_first_line_names_the_processes() -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    user_id = container.auth.provision_user("owner", "Owner")
    actor = Actor(user_id, frozenset({"projects:read", "projects:write"}))
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        domain = await client.call_tool(
            "create_domain", {"name": "Hem", "idempotency_key": "mcp-list-process-domain"}
        )
        domain_id = domain.structured_content["domain"]["id"]
        for index, name in enumerate(["Löpning", "Bokföring"]):
            await client.call_tool(
                "create_process",
                {
                    "domain_id": domain_id,
                    "name": name,
                    "idempotency_key": f"mcp-list-process-{index:03d}",
                },
            )
        listed = await client.call_tool("list_processes", {"limit": 10})

    summary, _decoded = _summary_and_json(listed)
    names = {process["name"] for process in listed.structured_content["processes"]}
    assert names == {"Löpning", "Bokföring"}
    _assert_first_line_names(summary.splitlines()[0], "Found 2 processes", names)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_task_steps_first_line_names_three_steps_and_counts_the_rest() -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    user_id = container.auth.provision_user("owner", "Owner")
    actor = Actor(
        user_id,
        frozenset({"projects:read", "projects:write", "tasks:read", "tasks:write"}),
    )
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        task = await client.call_tool(
            "create_task", {"title": "Write brief", "idempotency_key": "mcp-list-steps-task"}
        )
        task_id = task.structured_content["task"]["id"]
        for index, title in enumerate(["Ring Anna", "Boka tid", "Skicka papper", "Packa"]):
            await client.call_tool(
                "create_task_step",
                {
                    "task_id": task_id,
                    "title": title,
                    "idempotency_key": f"mcp-list-step-{index:03d}",
                },
            )
        listed = await client.call_tool("list_task_steps", {"task_id": task_id, "limit": 10})

    summary, _decoded = _summary_and_json(listed)
    names = {item["title"] for item in listed.structured_content["items"]}
    assert names == {"Ring Anna", "Boka tid", "Skicka papper", "Packa"}
    _assert_first_line_names(summary.splitlines()[0], "Found 4 steps", names)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_step_actions_first_line_names_the_actions() -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    user_id = container.auth.provision_user("owner", "Owner")
    actor = Actor(
        user_id,
        frozenset({"projects:read", "projects:write", "tasks:read", "tasks:write"}),
    )
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        task = await client.call_tool(
            "create_task", {"title": "Write brief", "idempotency_key": "mcp-list-actions-task"}
        )
        task_id = task.structured_content["task"]["id"]
        step = await client.call_tool(
            "create_task_step",
            {"task_id": task_id, "title": "Draft", "idempotency_key": "mcp-list-actions-step"},
        )
        step_id = step.structured_content["step"]["id"]
        for index, title in enumerate(["Öppna mallen", "Skriv ett stycke"]):
            await client.call_tool(
                "create_step_action",
                {
                    "step_id": step_id,
                    "title": title,
                    "idempotency_key": f"mcp-list-action-{index:03d}",
                },
            )
        listed = await client.call_tool("list_step_actions", {"step_id": step_id, "limit": 10})

    summary, _decoded = _summary_and_json(listed)
    names = {item["title"] for item in listed.structured_content["items"]}
    assert names == {"Öppna mallen", "Skriv ett stycke"}
    _assert_first_line_names(summary.splitlines()[0], "Found 2 actions", names)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_tags_first_line_names_three_tags_and_counts_the_rest() -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    user_id = container.auth.provision_user("owner", "Owner")
    actor = Actor(
        user_id,
        frozenset({"projects:read", "projects:write", "tasks:read", "tasks:write"}),
    )
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        await client.call_tool(
            "create_task",
            {
                "title": "Monthly bookkeeping",
                "idempotency_key": "mcp-list-tags-task",
                "tags": ["Ekonomi", "Telefon", "Hem", "Bil"],
            },
        )
        listed = await client.call_tool("list_tags", {"limit": 50})

    summary, _decoded = _summary_and_json(listed)
    names = {tag["label"] for tag in listed.structured_content["tags"]}
    assert len(names) == 4
    _assert_first_line_names(summary.splitlines()[0], "Found 4 tags", names)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_contact_text_contains_contact_id() -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    user_id = container.auth.provision_user("owner", "Owner")
    actor = Actor(user_id, frozenset({"contacts:read", "contacts:write"}))
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    result_created = await server.call_tool(
        "create_contact",
        {"display_name": "Rasmus", "idempotency_key": "mcp-text-contact-001"},
    )

    summary, decoded = _summary_and_json(result_created)
    assert decoded == _without_empty(result_created.structured_content)
    contact_id = decoded["contact"]["id"]
    assert isinstance(contact_id, str)
    assert UUID(contact_id)
    # Block 1 alone carries the id and version the model needs for the next call.
    assert summary == f"Created contact Rasmus.\nContact {contact_id} v1."


@pytest.mark.asyncio
@pytest.mark.integration
async def test_add_shopping_items_text_maps_client_ref_to_item_id() -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    user_id = container.auth.provision_user("owner", "Owner")
    actor = Actor(user_id, frozenset({"shopping:read", "shopping:write"}))
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    created_list = await server.call_tool(
        "create_shopping_list",
        {"name": "Veckohandel", "idempotency_key": "mcp-text-list-001"},
    )
    list_id = created_list.structured_content["shopping_list"]["id"]
    added = await server.call_tool(
        "add_shopping_items",
        {
            "list_id": list_id,
            "items": [{"client_ref": "milk-1", "name": "Mjölk"}],
            "idempotency_key": "mcp-text-batch-001",
        },
    )

    summary, decoded = _summary_and_json(added)
    item_id = decoded["items"][0]["item"]["id"]
    assert summary == (
        f"Added Mjölk to Veckohandel.\nShopping batch committed.\n- milk-1 → {item_id} v1"
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_journal_text_block_carries_the_full_result_including_owner_text() -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    user_id = container.auth.provision_user("owner", "Owner")
    actor = Actor(
        user_id,
        frozenset(
            {"journal:read", "journal:write", "projects:read", "tasks:read", "contacts:read"}
        ),
    )
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        source = await client.call_tool(
            "create_journal_source",
            {
                "source_type": "manual_text",
                "journal_date": "2026-07-21",
                "raw_text": f"Källtext {JOURNAL_SENTINEL}",
                "idempotency_key": "mcp-text-source-001",
            },
        )
        source_id = source.structured_content["source"]["id"]
        entry = await client.call_tool(
            "create_manual_journal_entry",
            {
                "source_id": source_id,
                "title": f"Titel {JOURNAL_SENTINEL}",
                "summary": f"Sammanfattning {JOURNAL_SENTINEL}",
                "key_points": [{"kind": "decision", "text": f"Punkt {JOURNAL_SENTINEL}"}],
                "project_ids": [],
                "task_ids": [],
                "contact_ids": [],
                "idempotency_key": "mcp-text-entry-001",
            },
        )
        entry_id = entry.structured_content["entry"]["id"]
        read = await client.call_tool("get_journal_entry", {"entry_id": entry_id})
        listed = await client.call_tool(
            "list_journal_entries",
            {"from_date": "2026-07-21", "to_date": "2026-07-21"},
        )
        opted_in = await client.call_tool(
            "get_journal_entry", {"entry_id": entry_id, "include_content": True}
        )
        opted_out = await client.call_tool(
            "get_journal_entry", {"entry_id": entry_id, "include_content": False}
        )

    # The source record carries no raw text, so its text blocks never hold the source text.
    assert len(source.content) == 2
    for block in source.content:
        assert JOURNAL_SENTINEL not in block.text

    # Block 2 is the full structured result (D-060): the host model reads owner text by default.
    for tool_result in (entry, read, listed, opted_in):
        assert len(tool_result.content) == 2
        assert JOURNAL_SENTINEL in tool_result.content[1].text

    read_summary, read_json = _summary_and_json(read)
    # Block 1 opens with a sentence naming the date; the id and version are on line 2.
    assert read_summary == (
        f'The journal entry "Titel {JOURNAL_SENTINEL}" from 21 July.\nEntry {entry_id} v1.'
    )
    assert read_json["entry"]["id"] == entry_id
    assert read_json["entry"]["title"] == f"Titel {JOURNAL_SENTINEL}"
    assert read_json["entry"]["summary"] == f"Sammanfattning {JOURNAL_SENTINEL}"
    assert read_json["entry"]["key_points"][0]["text"] == f"Punkt {JOURNAL_SENTINEL}"

    listed_summary, listed_json = _summary_and_json(listed)
    assert [item["id"] for item in listed_json["entries"]] == [entry_id]
    assert listed_json["entries"][0]["summary"] == f"Sammanfattning {JOURNAL_SENTINEL}"
    # Block 1 carries the entry id and the title as a row.
    assert entry_id in listed_summary
    assert f"Titel {JOURNAL_SENTINEL}" in listed_summary

    # include_content=False still leaves the summary and key points out of the result.
    assert opted_out.structured_content["entry"]["summary"] is None
    assert f"Sammanfattning {JOURNAL_SENTINEL}" not in opted_out.content[1].text
    assert f"Punkt {JOURNAL_SENTINEL}" not in opted_out.content[1].text

    # The text block carries the whole structured result, as it does by default.
    assert JOURNAL_SENTINEL in str(opted_in.structured_content)
    _, opted_in_json = _summary_and_json(opted_in)
    assert opted_in_json == _without_empty(opted_in.structured_content)
    assert JOURNAL_SENTINEL in opted_in.content[1].text


JOURNAL_UUID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_journal_first_text_line_is_a_sentence_without_ids() -> None:
    # Voice mode reads block 1 only: the first line is a sentence, and the ids sit on line 2.
    factory = database_factory()
    container = create_container(make_settings(), factory)
    user_id = container.auth.provision_user("voice-owner", "Voice Owner")
    actor = Actor(
        user_id,
        frozenset(
            {"journal:read", "journal:write", "projects:read", "tasks:read", "contacts:read"}
        ),
    )
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        source = await client.call_tool(
            "create_journal_source",
            {
                "source_type": "manual_text",
                "journal_date": "2026-07-21",
                "raw_text": "Rösttext för ett kort dagboksunderlag.",
                "idempotency_key": "mcp-voice-source-001",
            },
        )
        source_id = source.structured_content["source"]["id"]
        created = await client.call_tool(
            "create_manual_journal_entry",
            {
                "source_id": source_id,
                "title": "Röst ett",
                "summary": None,
                "key_points": [],
                "project_ids": [],
                "task_ids": [],
                "contact_ids": [],
                "idempotency_key": "mcp-voice-entry-001",
            },
        )
        entry_id = created.structured_content["entry"]["id"]
        updated = await client.call_tool(
            "update_journal_entry",
            {
                "entry_id": entry_id,
                "expected_version": 1,
                "title": "Röst två",
                "summary": "Kort sammanfattning.",
                "key_points": [],
                "idempotency_key": "mcp-voice-update-001",
            },
        )
        read = await client.call_tool("get_journal_entry", {"entry_id": entry_id})
        day = await client.call_tool("get_journal_day", {"journal_date": "2026-07-21"})
        daily = await client.call_tool("get_daily_journal_summary", {"journal_date": "2026-07-21"})
        read_source = await client.call_tool("get_journal_source", {"source_id": source_id})
        written = await client.call_tool(
            "write_journal_entry",
            {
                "journal_date": "2026-07-22",
                "title": "Röst tre",
                "source_text": "Jag tog en promenad i solen.",
                "idempotency_key": "mcp-voice-write-001",
            },
        )

    changed = {
        "create_journal_source": source,
        "create_manual_journal_entry": created,
        "update_journal_entry": updated,
        "get_journal_entry": read,
        "get_journal_day": day,
        "get_daily_journal_summary": daily,
        "get_journal_source": read_source,
        "write_journal_entry": written,
    }
    for name, tool_result in changed.items():
        first_line = tool_result.content[0].text.split("\n", 1)[0]
        assert JOURNAL_UUID.search(first_line) is None, name

    # The ids and versions the model needs for its next call stay in block 1, on line 2.
    assert created.content[0].text.splitlines() == [
        "Created a manual entry from 21 July.",
        f"Entry {entry_id} v1.",
    ]
    assert updated.content[0].text.splitlines() == [
        "Updated the journal entry from 21 July.",
        f"Entry {entry_id} v{updated.structured_content['entry']['version']}.",
    ]
    read_version = read.structured_content["entry"]["version"]
    assert read.content[0].text.splitlines()[1] == f"Entry {entry_id} v{read_version}."
    assert read_version == updated.structured_content["entry"]["version"]
    assert written.content[0].text.splitlines()[1].startswith("Entry ")
    assert entry_id in read.content[1].text


def test_block_two_is_kept_at_the_text_json_limit_and_left_out_just_above_it() -> None:
    # '{"blob":""}' is 11 characters, so the compact JSON of each payload is exactly the size
    # named in the test.
    wrapper_length = len('{"blob":""}')
    at_limit = {"blob": "x" * (_TEXT_JSON_LIMIT - wrapper_length)}
    over_limit = {"blob": "x" * (_TEXT_JSON_LIMIT - wrapper_length + 1)}

    kept = result(at_limit, "Summary.")
    assert len(kept.content) == 2
    assert kept.content[0].text == "Summary."
    assert len(kept.content[1].text) == _TEXT_JSON_LIMIT
    assert kept.structured_content == at_limit

    left_out = result(over_limit, "Summary.")
    assert len(left_out.content) == 1
    assert left_out.content[0].text == f"Summary.\n{_LARGE_RESULT_NOTE}"
    assert left_out.structured_content == over_limit


def test_list_text_puts_id_version_status_and_due_on_each_row_and_caps_at_fifty() -> None:
    items = [
        TextRow(
            UUID(int=number),
            f"Item\n{number}  x",
            version=2,
            status="active",
            due_at=datetime(2026, 10, 25, 12, tzinfo=UTC),
        )
        for number in range(53)
    ]

    lines = list_text("Found 53 things.", items).splitlines()

    assert lines[0] == "Found 53 things."
    assert lines[1] == f"- {UUID(int=0)} | Item 0 x | v2 | active | due 2026-10-25T12:00:00Z"
    assert len(lines) == 1 + 50 + 1
    assert lines[-1] == "… 3 till (använd cursor)"


def test_hierarchy_text_indents_children_two_spaces_per_level() -> None:
    domain, project, orphan = UUID(int=1), UUID(int=2), UUID(int=3)
    rows = [
        HierarchyRow(domain, None, "Ops", "domain", status="a", version=1),
        HierarchyRow(project, domain, "Launch", "project", status="a", version=1),
        HierarchyRow(orphan, UUID(int=9), "Orphan", "project", status="a", version=1),
    ]

    lines = hierarchy_card_text(rows, hierarchy_indents(rows)).splitlines()

    assert lines[0] == f"- {domain} v1 | Ops | domain | a"
    assert lines[1] == f"  - {project} v1 | Launch | project | a"
    assert lines[2] == f"- {orphan} v1 | Orphan | project | a"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_work_hierarchy_text_names_domain_and_project_ids() -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    user_id = container.auth.provision_user("owner", "Owner")
    actor = Actor(user_id, frozenset({"projects:read", "projects:write"}))
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        domain = await client.call_tool(
            "create_domain", {"name": "Operations", "idempotency_key": "mcp-text-hier-domain"}
        )
        domain_id = domain.structured_content["domain"]["id"]
        project = await client.call_tool(
            "create_project",
            {
                "domain_id": domain_id,
                "title": "Launch",
                "idempotency_key": "mcp-text-hier-project",
            },
        )
        project_id = project.structured_content["project"]["id"]
        hierarchy = await client.call_tool("get_work_hierarchy", {"limit": 100})

    summary = _card_text(hierarchy)
    lines = summary.splitlines()
    assert lines[0] == "Found 1 domain and 1 project: Operations and Launch."
    assert f"\n- {domain_id} v1 | Operations | domain | " in summary
    assert f"\n  - {project_id} v1 | Launch | project | " in summary
    assert lines[-1] == CARD_NOTE
    structured: dict[str, Any] = hierarchy.structured_content or {}
    assert [node["id"] for node in structured["nodes"]] == [domain_id, project_id]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_project_text_names_project_id_version_and_domain() -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    user_id = container.auth.provision_user("owner", "Owner")
    actor = Actor(user_id, frozenset({"projects:read", "projects:write"}))
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        domain = await client.call_tool(
            "create_domain", {"name": "Operations", "idempotency_key": "mcp-text-proj-domain"}
        )
        domain_id = domain.structured_content["domain"]["id"]
        created = await client.call_tool(
            "create_project",
            {
                "domain_id": domain_id,
                "title": "Launch",
                "idempotency_key": "mcp-text-proj-001",
            },
        )

    project_id = created.structured_content["project"]["id"]
    summary, decoded = _summary_and_json(created)
    assert summary == f"Created project Launch.\n{project_id} v1: Launch in domain {domain_id}"
    assert decoded == _without_empty(created.structured_content)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_task_step_text_names_step_id_version_and_task() -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    user_id = container.auth.provision_user("owner", "Owner")
    actor = Actor(
        user_id,
        frozenset({"projects:read", "projects:write", "tasks:read", "tasks:write"}),
    )
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        task = await client.call_tool(
            "create_task", {"title": "Write brief", "idempotency_key": "mcp-text-task-001"}
        )
        task_id = task.structured_content["task"]["id"]
        step = await client.call_tool(
            "create_task_step",
            {
                "task_id": task_id,
                "title": "Draft outline",
                "idempotency_key": "mcp-text-step-001",
            },
        )

    step_id = step.structured_content["step"]["id"]
    summary, decoded = _summary_and_json(step)
    assert summary == f"Created step Draft outline.\n{step_id} v1: Draft outline in task {task_id}"
    assert decoded == _without_empty(step.structured_content)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_voice_first_line_is_a_sentence_without_ids_for_board_agenda_and_tasks() -> None:
    # Voice mode reads block 1 only: line 1 is a sentence without ids, and the ids sit on line 2.
    uuid_pattern = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
    factory = database_factory()
    container = create_container(make_settings(), factory)
    user_id = container.auth.provision_user("voice-owner", "Voice Owner")
    actor = Actor(
        user_id,
        frozenset({"projects:read", "projects:write", "tasks:read", "tasks:write"}),
    )
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        created = await client.call_tool(
            "create_task",
            {
                "title": "Ring Rasmus",
                "idempotency_key": "mcp-voice-task-001",
                "due_at": "2026-10-01T09:00:00+00:00",
            },
        )
        task = created.structured_content["task"]
        board = await client.call_tool("get_work_board", {"limit": 100})
        agenda = await client.call_tool("get_work_agenda", {"limit": 100})
        completed = await client.call_tool(
            "complete_task",
            {
                "task_id": task["id"],
                "version": task["version"],
                "idempotency_key": "mcp-voice-task-002",
            },
        )

    board_text, agenda_text = board.content[0].text, agenda.content[0].text
    created_text, completed_text = created.content[0].text, completed.content[0].text
    assert board_text.splitlines()[0] == "The Work board has 1 task: 1 to do."
    assert agenda_text.splitlines()[0] == "1 agenda item: 1 overdue, 0 due today."
    assert created_text.splitlines()[0] == "Created task Ring Rasmus."
    assert completed_text.splitlines()[0] == "Completed task Ring Rasmus."
    for text in (board_text, agenda_text, created_text, completed_text):
        assert not uuid_pattern.search(text.splitlines()[0]), text
    # The ids are still there for the next call: the Task on the board and agenda, and line 2.
    assert task["id"] in board_text and task["id"] in agenda_text
    assert created_text.splitlines()[1] == f"{task['id']} v1: Ring Rasmus"
    assert completed_text.splitlines()[1].startswith(f"{task['id']} v")


def test_card_text_is_one_line_with_at_most_five_ids_and_the_card_note() -> None:
    examples = [(f"id-{number}", f"Title {number}\nsecond line") for number in range(7)]

    text = card_text("Work board card shown: 7 records.", examples, tail="More: next_cursor abc.")

    assert "\n" not in text
    assert text.startswith(
        "Work board card shown: 7 records. Examples: id-0 Title 0 second line; id-1 "
    )
    assert "id-4 Title 4 second line." in text
    assert "id-5" not in text
    assert text.endswith(f"More: next_cursor abc. {CARD_NOTE}")


def test_card_text_cuts_long_titles_to_eighty_characters() -> None:
    text = card_text("Head.", [("id-1", "x" * 200)])

    assert "x" * 79 + "…" in text
    assert "x" * 80 not in text


def test_card_row_flattens_and_cuts_its_title_and_leaves_out_missing_details() -> None:
    row = card_row("id-1", "Line one\nline | two " + "x" * 100, "due 2026-10-25", None)

    assert row.startswith("- id-1 | Line one line / two xxx")
    title = row.split(" | ")[1]
    assert title.endswith("…")
    assert len(title) == 80
    assert row.endswith(" | due 2026-10-25")
    assert row.count(" | ") == 2
    assert "\n" not in row


def test_card_rows_keeps_the_head_and_at_most_the_limit_then_counts_the_rest() -> None:
    rows = [f"- id-{number}" for number in range(5)]

    assert card_rows("todo 5:", rows, limit=3) == [
        "todo 5:",
        "- id-0",
        "- id-1",
        "- id-2",
        "… 2 more",
    ]
    assert card_rows("todo 5:", rows, limit=5) == ["todo 5:", *rows]


_AGENDA_NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
_Group = Literal["overdue", "today", "upcoming", "scheduled_later"]


def _id(label: str) -> UUID:
    """A fixed id per label, so an expected row can name the record it expects."""

    return uuid5(NAMESPACE_OID, label)


def _at(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def _record(
    label: str,
    *,
    kind: str = "task",
    title: str | None = None,
    version: int = 1,
    group: _Group | None = None,
    due_at: str | None = None,
    project_title: str | None = None,
    waiting_since: str | None = None,
    name: str | None = None,
    estimated_minutes: int | None = None,
) -> WorkItemRecord:
    return WorkItemRecord(
        kind=kind,
        id=_id(label),
        parent_id=None,
        title=title or f"Title {label}",
        status="todo",
        version=version,
        agenda_group=group,
        due_at=_at(due_at),
        project_title=project_title,
        waiting_since=_at(waiting_since),
        waiting_on_contact_name=name,
        estimated_minutes=estimated_minutes,
    )


def _agenda_item(
    label: str,
    group: _Group,
    *,
    title: str | None = None,
    due_at: str | None = "2026-10-25T09:00:00+00:00",
    project_title: str | None = None,
) -> WorkItemRecord:
    return _record(
        label, title=title, version=3, group=group, due_at=due_at, project_title=project_title
    )


def test_agenda_card_text_lists_overdue_and_today_rows_and_counts_the_other_groups() -> None:
    long_title = "Långt " + "y" * 100
    items = [
        _agenda_item("up-1", "upcoming", due_at="2026-12-02T09:00:00+00:00"),
        _agenda_item(
            "ov-1", "overdue", due_at="2026-10-20T09:00:00+00:00", project_title="Bokslut"
        ),
        _agenda_item("td-1", "today", due_at="2026-10-27T18:00:00+00:00"),
        _agenda_item("ov-2", "overdue", title=long_title, due_at="2026-10-21T09:00:00+00:00"),
        _agenda_item("sc-1", "scheduled_later", due_at="2026-12-01T09:00:00+00:00"),
    ]

    text = agenda_card_text(items, "cursor-2", now=_AGENDA_NOW)

    assert text.splitlines() == [
        "Work agenda card shown: 5 items (overdue 2, today 1, upcoming 1, scheduled_later 1).",
        f"- {_id('ov-1')} v3 | Title ov-1 | due 2026-10-20T09:00:00Z | project Bokslut",
        f"- {_id('ov-2')} v3 | " + long_title[:79] + "… | due 2026-10-21T09:00:00Z",
        f"- {_id('td-1')} v3 | Title td-1 | due 2026-10-27T18:00:00Z",
        "More: next_cursor cursor-2.",
        f"{CARD_NOTE} {AGENDA_NOTE}",
    ]


def test_agenda_card_text_counts_an_undated_upcoming_record_without_parsing_it() -> None:
    items = [
        _agenda_item("up-1", "upcoming", due_at=None),
        _agenda_item("td-1", "today", due_at="2026-10-27T18:00:00+00:00"),
    ]

    lines = agenda_card_text(items, None, now=_AGENDA_NOW).splitlines()

    assert "upcoming 1" in lines[0]
    assert not any("up-1" in line for line in lines)


def test_agenda_card_text_caps_the_overdue_and_today_rows_at_the_row_limit() -> None:
    overdue = [_agenda_item(f"ov-{number}", "overdue") for number in range(AGENDA_ROW_LIMIT + 1)]

    lines = agenda_card_text(overdue, None, now=_AGENDA_NOW).splitlines()

    total = AGENDA_ROW_LIMIT + 1
    assert lines[0] == (
        f"Work agenda card shown: {total} items (overdue {total}, today 0, upcoming 0, "
        "scheduled_later 0)."
    )
    assert len([line for line in lines if line.startswith("- ")]) == AGENDA_ROW_LIMIT
    assert lines[-2] == "… 1 more"
    assert lines[-1] == f"{CARD_NOTE} {AGENDA_NOTE}"


def test_agenda_card_text_lists_upcoming_rows_due_within_seven_days_only() -> None:
    items = [
        _agenda_item("up-far", "upcoming", due_at="2026-11-17T09:00:00+00:00"),
        _agenda_item("up-near", "upcoming", due_at="2026-10-30T09:00:00+00:00"),
        _agenda_item("ov-1", "overdue", due_at="2026-10-20T09:00:00+00:00"),
    ]

    lines = agenda_card_text(items, None, now=_AGENDA_NOW).splitlines()

    assert lines == [
        "Work agenda card shown: 3 items (overdue 1, today 0, upcoming 2, scheduled_later 0).",
        f"- {_id('ov-1')} v3 | Title ov-1 | due 2026-10-20T09:00:00Z",
        f"- {_id('up-near')} v3 | Title up-near | due 2026-10-30T09:00:00Z",
        f"{CARD_NOTE} {AGENDA_NOTE}",
    ]


def test_agenda_card_text_keeps_overdue_and_today_ahead_of_upcoming_at_the_row_limit() -> None:
    items = [_agenda_item(f"ov-{number}", "overdue") for number in range(AGENDA_ROW_LIMIT)]
    items.append(_agenda_item("up-near", "upcoming", due_at="2026-10-30T09:00:00+00:00"))

    lines = agenda_card_text(items, None, now=_AGENDA_NOW).splitlines()

    assert len([line for line in lines if line.startswith("- ")]) == AGENDA_ROW_LIMIT
    assert not any("up-near" in line for line in lines)
    assert lines[-2] == "… 1 more"


_WAITING_ZONE = ZoneInfo("Europe/Stockholm")


def _waiting_item(
    label: str, since: str | None, version: int = 1, name: str | None = None
) -> WorkItemRecord:
    return _record(label, version=version, waiting_since=since, name=name)


def test_waiting_agenda_text_lists_the_longest_wait_first_and_marks_seven_days_or_more() -> None:
    # Stockholm is still on summer time on 20 Oct, so w-edge's 23:30 UTC is 21 Oct there: six days.
    items = [
        _waiting_item("w-new", "2026-10-26T09:00:00+00:00"),
        _waiting_item("w-edge", "2026-10-20T23:30:00+00:00"),
        _waiting_item("w-old", "2026-10-10T09:00:00+00:00", version=3, name="Anna Berg"),
        _waiting_item("w-mid", "2026-10-20T09:00:00+00:00"),
    ]

    text = waiting_agenda_text(items, "cursor-2", now=_AGENDA_NOW, zone=_WAITING_ZONE)

    assert text.splitlines() == [
        "You are waiting on 4 things on this page (more follow), longest on Anna Berg for 17 days: "
        "Title w-old.",
        "Waiting, longest first:",
        f"- {_id('w-old')} v3 | Title w-old | Anna Berg | waited 17 days | remind",
        f"- {_id('w-mid')} v1 | Title w-mid | waited 7 days | remind",
        f"- {_id('w-edge')} v1 | Title w-edge | waited 6 days",
        f"- {_id('w-new')} v1 | Title w-new | waited 1 day",
        "More: next_cursor cursor-2.",
        CARD_NOTE,
    ]


def test_waiting_agenda_text_line_one_reads_who_how_long_and_what_for_one_wait() -> None:
    items = [_waiting_item("w-1", "2026-10-19T09:00:00+00:00", name="Anna Berg")]

    lines = waiting_agenda_text(items, None, now=_AGENDA_NOW, zone=_WAITING_ZONE).splitlines()

    assert lines[0] == "You are waiting on Anna Berg for 8 days: Title w-1."


def test_waiting_agenda_text_line_one_without_a_contact_or_a_date_or_any_wait() -> None:
    nameless = [_waiting_item("w-1", "2026-10-27T09:00:00+00:00")]
    undated = [_waiting_item("w-2", None, name="Bo")]

    first = waiting_agenda_text(nameless, None, now=_AGENDA_NOW, zone=_WAITING_ZONE)
    second = waiting_agenda_text(undated, None, now=_AGENDA_NOW, zone=_WAITING_ZONE)
    empty = waiting_agenda_text([], None, now=_AGENDA_NOW, zone=_WAITING_ZONE)

    assert first.splitlines()[0] == "You are waiting since today: Title w-1."
    assert second.splitlines()[0] == "You are waiting on Bo: Title w-2."
    assert empty.splitlines()[0] == "You are not waiting on anyone."


def test_waiting_agenda_text_keeps_line_one_free_of_ids_and_puts_undated_rows_last() -> None:
    items = [
        _waiting_item("w-undated", None),
        _waiting_item("w-dated", "2026-10-27T09:00:00+00:00"),
    ]

    lines = waiting_agenda_text(items, None, now=_AGENDA_NOW, zone=_WAITING_ZONE).splitlines()

    assert lines[0] == "You are waiting on 2 things, longest since today: Title w-dated."
    assert str(_id("w-dated")) not in lines[0]
    assert lines[2] == f"- {_id('w-dated')} v1 | Title w-dated | waited 0 days"
    assert lines[3] == f"- {_id('w-undated')} v1 | Title w-undated"
    assert not any(line.startswith("More:") for line in lines)
    assert lines[-1] == CARD_NOTE


def test_board_card_text_names_at_most_eight_ids_per_column_and_counts_the_rest() -> None:
    columns = {
        "todo": [_record(f"td-{number}", version=2, title=f"Todo {number}") for number in range(9)],
        "blocked": [_record("bl-1", version=5, title="Blocked")],
    }

    lines = board_card_text(columns, None, filtered=False).splitlines()

    assert lines[0] == "Work board card shown: 10 tasks (todo 9, blocked 1)."
    assert lines[1] == "todo 9:"
    assert lines[2] == f"- {_id('td-0')} v2 | Todo 0"
    last = BOARD_ROW_LIMIT - 1
    assert lines[1 + BOARD_ROW_LIMIT] == f"- {_id(f'td-{last}')} v2 | Todo {last}"
    assert lines[2 + BOARD_ROW_LIMIT] == "… 1 more"
    assert lines[3 + BOARD_ROW_LIMIT] == "blocked 1:"
    assert lines[4 + BOARD_ROW_LIMIT] == f"- {_id('bl-1')} v5 | Blocked"
    assert lines[-1] == CARD_NOTE


def test_board_card_text_counts_only_tasks_and_lists_projects_and_domains_apart() -> None:
    columns = {
        "todo": [_record("t-1", title="Ring")],
        "active": [
            _record("p-1", kind="project", version=4, title="Kök"),
            _record("d-1", kind="domain", version=2, title="Hem"),
        ],
    }

    lines = board_card_text(columns, None, filtered=False).splitlines()

    assert lines == [
        "Work board card shown: 1 task (todo 1), also 1 project, 1 domain.",
        "todo 1:",
        f"- {_id('t-1')} v1 | Ring",
        "not tasks 2:",
        f"- {_id('p-1')} v4 | Kök | project",
        f"- {_id('d-1')} v2 | Hem | domain",
        CARD_NOTE,
    ]
    assert board_sentence(columns, None) == (
        "The Work board has 1 task: 1 to do. Also listed: 1 project, 1 domain."
    )


def test_card_result_keeps_structured_content_and_sends_only_the_short_text() -> None:
    structured = {
        "items": [{"id": "task-1", "title": "Write brief", "description": "Private body"}],
        "next_cursor": None,
    }

    tool_result = card_result(structured, "Work agenda card shown: 1 item.")

    assert tool_result.structured_content == structured
    assert [block.text for block in tool_result.content] == ["Work agenda card shown: 1 item."]
    assert "Private body" not in str(tool_result.content)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_shopping_list_card_text_names_the_list_and_item_ids() -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    user_id = container.auth.provision_user("owner", "Owner")
    actor = Actor(user_id, frozenset({"shopping:read", "shopping:write"}))
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    created_list = await server.call_tool(
        "create_shopping_list",
        {"name": "Veckohandel", "idempotency_key": "mcp-card-list-001"},
    )
    list_id = created_list.structured_content["shopping_list"]["id"]
    await server.call_tool(
        "add_shopping_items",
        {
            "list_id": list_id,
            "items": [
                {"client_ref": "milk-1", "name": "Mjölk"},
                {"client_ref": "bread-1", "name": "Bröd"},
            ],
            "idempotency_key": "mcp-card-batch-001",
        },
    )
    shown = await server.call_tool("get_shopping_list", {"list_id": list_id})

    assert len(shown.content) == 1
    summary = shown.content[0].text
    item_ids = [item["id"] for item in shown.structured_content["items"]]
    assert len(item_ids) == 2
    assert summary.startswith(
        "Shopping list Veckohandel has 2 items to buy and 0 already bought.\n"
        f"List {list_id} v1, card shown.\n"
    )
    assert all(item_id in summary for item_id in item_ids)
    assert "More:" not in summary
    assert summary.endswith(CARD_NOTE)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_shopping_list_card_text_lists_wanted_rows_and_counts_purchased() -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    user_id = container.auth.provision_user("owner", "Owner")
    actor = Actor(user_id, frozenset({"shopping:read", "shopping:write"}))
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    created_list = await server.call_tool(
        "create_shopping_list",
        {"name": "Veckohandel", "idempotency_key": "mcp-card-rows-list-001"},
    )
    list_id = created_list.structured_content["shopping_list"]["id"]
    added = await server.call_tool(
        "add_shopping_items",
        {
            "list_id": list_id,
            "items": [
                {"client_ref": f"item-{number}", "name": f"Vara {number}"} for number in range(1, 9)
            ],
            "idempotency_key": "mcp-card-rows-batch-001",
        },
    )
    added_items = {
        entry["client_ref"]: entry["item"] for entry in added.structured_content["items"]
    }
    purchased_item = added_items["item-1"]
    await server.call_tool(
        "set_shopping_item_purchased",
        {
            "item_id": purchased_item["id"],
            "purchased": True,
            "version": purchased_item["version"],
            "idempotency_key": "mcp-card-rows-purchase-001",
        },
    )
    shown = await server.call_tool("get_shopping_list", {"list_id": list_id})

    summary = shown.content[0].text
    lines = summary.splitlines()
    assert len(shown.content) == 1
    assert lines[0] == "Shopping list Veckohandel has 7 items to buy and 1 already bought."
    assert lines[1] == f"List {list_id} v1, card shown."
    assert sum(1 for line in lines if line.startswith("- ")) == 7
    # Wanted item 8 has one row with its id and version, so the model can mark it purchased.
    item_8 = added_items["item-8"]
    assert f"- {item_8['id']} | Vara 8 | v{item_8['version']}" in lines
    # The purchased item gets no row; only the count line names the purchased items.
    assert purchased_item["id"] not in summary
    assert "Purchased: 1 (not listed)." in lines
    assert lines[-1] == CARD_NOTE


SHOPPING_UUID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_shopping_first_text_line_is_a_sentence_without_ids() -> None:
    # Voice mode reads block 1 only: the first line is a sentence, and the ids sit on line 2.
    factory = database_factory()
    container = create_container(make_settings(), factory)
    user_id = container.auth.provision_user("voice-owner", "Voice Owner")
    actor = Actor(user_id, frozenset({"shopping:read", "shopping:write"}))
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        created = await client.call_tool(
            "create_shopping_list",
            {"name": "Veckohandel", "idempotency_key": "mcp-voice-shop-list-001"},
        )
        list_id = created.structured_content["shopping_list"]["id"]
        listed = await client.call_tool("list_shopping_lists", {})
        added = await client.call_tool(
            "add_shopping_items",
            {
                "list_id": list_id,
                "items": [{"client_ref": "milk-1", "name": "Mjölk"}],
                "idempotency_key": "mcp-voice-shop-batch-001",
            },
        )
        item_id = added.structured_content["items"][0]["item"]["id"]
        shown = await client.call_tool("get_shopping_list", {"list_id": list_id})
        renamed = await client.call_tool(
            "update_shopping_list",
            {
                "list_id": list_id,
                "name": "Veckohandel 2",
                "archived": False,
                "version": 1,
                "idempotency_key": "mcp-voice-shop-list-update-001",
            },
        )
        item_changed = await client.call_tool(
            "update_shopping_item",
            {
                "item_id": item_id,
                "item": {"name": "Mjölk 2"},
                "version": 1,
                "idempotency_key": "mcp-voice-shop-item-update-001",
            },
        )
        purchased = await client.call_tool(
            "set_shopping_item_purchased",
            {
                "item_id": item_id,
                "purchased": True,
                "version": 2,
                "idempotency_key": "mcp-voice-shop-purchase-001",
            },
        )

    changed = {
        "create_shopping_list": created,
        "list_shopping_lists": listed,
        "add_shopping_items": added,
        "get_shopping_list": shown,
        "update_shopping_list": renamed,
        "update_shopping_item": item_changed,
        "set_shopping_item_purchased": purchased,
    }
    for name, tool_result in changed.items():
        first_line = tool_result.content[0].text.split("\n", 1)[0]
        assert SHOPPING_UUID.search(first_line) is None, name

    assert created.content[0].text == f"Created shopping list Veckohandel.\nList {list_id} v1."
    assert listed.content[0].text.splitlines()[0] == "You have 1 shopping list: Veckohandel."
    assert added.content[0].text.splitlines()[0] == "Added Mjölk to Veckohandel."
    assert shown.content[0].text.splitlines()[0] == (
        "Shopping list Veckohandel has 1 item to buy and 0 already bought."
    )
    assert renamed.content[0].text.splitlines()[0] == "Updated shopping list Veckohandel 2."
    assert renamed.content[0].text.splitlines()[1] == f"List {list_id} v2."
    assert item_changed.content[0].text.splitlines()[0] == "Updated shopping item Mjölk 2."
    assert purchased.content[0].text.splitlines()[0] == "Marked Mjölk 2 as bought."
    # The ids and versions the model needs for its next call stay in block 1, on line 2 or later.
    assert purchased.content[0].text.splitlines()[1] == f"Item {item_id} v3."
    assert item_id in shown.content[0].text


def test_count_phrase_uses_the_singular_only_for_exactly_one() -> None:
    assert count_phrase(0, "task", "tasks") == "0 tasks"
    assert count_phrase(1, "task", "tasks") == "1 task"
    assert count_phrase(2, "task", "tasks") == "2 tasks"


def test_spoken_status_and_date_read_as_words() -> None:
    today = date(2026, 10, 30)
    assert spoken_status("todo") == "to do"
    assert spoken_status("in_progress") == "in progress"
    assert spoken_status("completed") == "completed"
    assert spoken_date(date(2026, 11, 2), today) == "2 November"
    assert spoken_date(date(2027, 1, 5), today) == "5 January 2027"


def test_agenda_sentence_counts_only_this_page_when_more_pages_follow() -> None:
    items = [_agenda_item("a", "overdue"), _agenda_item("b", "today")]
    assert agenda_sentence(items, None) == "2 agenda items: 1 overdue, 1 due today."
    assert agenda_sentence(items[:1], None) == "1 agenda item: 1 overdue, 0 due today."
    assert agenda_sentence(items, "cursor-2") == (
        "2 agenda items on this page (more follow): 1 overdue, 1 due today."
    )


def test_board_sentence_counts_tasks_per_status_in_words() -> None:
    columns = {
        "todo": [_record("a"), _record("b")],
        "in_progress": [_record("c")],
    }
    assert board_sentence(columns, None) == ("The Work board has 3 tasks: 2 to do, 1 in progress.")
    assert board_sentence({}, None) == "The Work board has no records."
    assert board_sentence({"todo": [_record("a")]}, "cursor-2") == (
        "The Work board has 1 task on this page (more follow): 1 to do."
    )
    only_project = {"active": [_record("p", kind="project")]}
    assert board_sentence(only_project, None) == (
        "The Work board has 0 tasks. Also listed: 1 project."
    )


def test_work_item_sentence_names_status_and_date_without_ids() -> None:
    today = date(2026, 10, 30)
    assert work_item_sentence(
        "Task", "Köp färg", "in_progress", date(2026, 11, 2), label="due date", today=today
    ) == ("Task Köp färg: in progress, due date 2 November.")
    assert work_item_sentence(
        "Project", "Köket", "active", None, label="target date", today=today
    ) == ("Project Köket: active, no target date.")
