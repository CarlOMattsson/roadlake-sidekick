"""update_journal_entry as an addition: append_key_points and append_text (UX point 14, case 9)."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

import pytest
from fastmcp import Client
from sqlalchemy import text

from sidekick.api.app import Container, create_container
from sidekick.journal.domain.entry import KeyPoint, KeyPointKind
from sidekick.journal.domain.source import SourceType
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.errors.core import ConflictError
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.journal_drafts import seed_entry_draft
from tests.support.mcp_journal_review import call, finalize_args, read_draft
from tests.support.settings import make_settings


def make_container() -> tuple[Any, Actor]:
    container = create_container(make_settings(), database_factory(), None)
    user_id = container.auth.provision_user("mcp-append-owner", "MCP Append Owner")
    actor = Actor(
        user_id,
        frozenset(
            {"journal:read", "journal:write", "projects:read", "tasks:read", "contacts:read"}
        ),
    )
    return container, actor


def _point(text_value: str, kind: str = "fact") -> dict[str, str]:
    return {"kind": kind, "text": text_value}


async def _create_entry(
    client: Client, suffix: str, journal_date: str = "2026-07-21"
) -> dict[str, Any]:
    source = await client.call_tool(
        "create_journal_source",
        {
            "source_type": "manual_text",
            "journal_date": journal_date,
            "raw_text": "Jag sov länge.",
            "idempotency_key": f"{suffix}-source",
        },
    )
    entry = await client.call_tool(
        "create_manual_journal_entry",
        {
            "source_id": source.structured_content["source"]["id"],
            "title": "Lördag",
            "summary": "En lugn dag.",
            "key_points": [_point("Sov länge"), _point("Promenad med Lisa")],
            "project_ids": [],
            "task_ids": [],
            "contact_ids": [],
            "idempotency_key": f"{suffix}-entry",
        },
    )
    return entry.structured_content["entry"]


def _line_one(response: Any) -> str:
    return response.content[0].text.split("\n", 1)[0]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_append_key_points_adds_after_the_existing_ones_and_keeps_the_rest() -> None:
    container, actor = make_container()
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        entry = await _create_entry(client, "append-points")
        args = {
            "entry_id": entry["id"],
            "expected_version": 1,
            "append_key_points": [_point("Middag hos mamma"), _point("Tog bussen hem")],
            "idempotency_key": "append-points-1",
        }
        appended = await client.call_tool("update_journal_entry", args, raise_on_error=False)
        assert not appended.is_error, appended.structured_content
        record = appended.structured_content["entry"]
        assert record["version"] == 2
        assert record["title"] == "Lördag"
        assert record["summary"] == "En lugn dag."
        assert [point["text"] for point in record["key_points"]] == [
            "Sov länge",
            "Promenad med Lisa",
            "Middag hos mamma",
            "Tog bussen hem",
        ]
        # No text, so no new source: the entry keeps its own.
        assert record["source_id"] == entry["source_id"]
        # Line 1 is speakable; the id and version are on line 2.
        assert appended.content[0].text == (
            f"Added 2 points to the journal from 21 July.\nEntry {entry['id']} v2."
        )

        replay = await client.call_tool("update_journal_entry", args)
        assert replay.structured_content == appended.structured_content


@pytest.mark.asyncio
@pytest.mark.integration
async def test_append_line_one_says_todays_journal_for_the_current_day() -> None:
    container, actor = make_container()
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    today = datetime.now(container.settings.owner_zone).date().isoformat()

    async with Client(server) as client:
        entry = await _create_entry(client, "append-today", today)
        appended = await client.call_tool(
            "update_journal_entry",
            {
                "entry_id": entry["id"],
                "expected_version": 1,
                "append_key_points": [_point("Ett"), _point("Två")],
                "idempotency_key": "append-today-1",
            },
        )
        assert _line_one(appended) == "Added 2 points to today's journal."
        single = await client.call_tool(
            "update_journal_entry",
            {
                "entry_id": entry["id"],
                "expected_version": 2,
                "append_key_points": [_point("Tre")],
                "idempotency_key": "append-today-2",
            },
        )
        assert _line_one(single) == "Added 1 point to today's journal."


@pytest.mark.asyncio
@pytest.mark.integration
async def test_append_text_saves_her_words_as_a_new_source_replacing_the_old_one() -> None:
    container, actor = make_container()
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        entry = await _create_entry(client, "append-text")
        old_source_id = entry["source_id"]
        args = {
            "entry_id": entry["id"],
            "expected_version": 1,
            "append_text": "Vi åt middag hos mamma.",
            "append_key_points": [_point("Middag hos mamma")],
            "idempotency_key": "append-text-1",
        }
        appended = await client.call_tool("update_journal_entry", args, raise_on_error=False)
        assert not appended.is_error, appended.structured_content
        record = appended.structured_content["entry"]
        assert record["version"] == 2
        assert record["source_id"] != old_source_id
        assert _line_one(appended) == "Added 1 point and your words to the journal from 21 July."

        new_source = await client.call_tool(
            "get_journal_source", {"source_id": record["source_id"]}
        )
        source = new_source.structured_content["source"]
        assert source["replaces_source_id"] == old_source_id
        assert source["raw_text"] == "Jag sov länge.\n\nVi åt middag hos mamma."
        assert source["journal_date"] == "2026-07-21"
        old_source = await client.call_tool("get_journal_source", {"source_id": old_source_id})
        assert old_source.structured_content["source"]["raw_text"] == "Jag sov länge."

        # A retry returns the same entry and does not create a second source.
        replay = await client.call_tool("update_journal_entry", args)
        assert replay.structured_content == appended.structured_content
        fetched = await client.call_tool("get_journal_entry", {"entry_id": entry["id"]})
        assert fetched.structured_content["entry"]["source_id"] == record["source_id"]

    with container.session_factory() as session:
        count = session.execute(text("SELECT count(*) FROM sidekick.journal_sources")).scalar_one()
        assert count == 2


@pytest.mark.asyncio
@pytest.mark.integration
async def test_append_text_alone_changes_only_the_source_and_version() -> None:
    container, actor = make_container()
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        entry = await _create_entry(client, "append-only-text")
        appended = await client.call_tool(
            "update_journal_entry",
            {
                "entry_id": entry["id"],
                "expected_version": 1,
                "append_text": "Och sedan åt vi glass.",
                "idempotency_key": "append-only-text-1",
            },
        )
        record = appended.structured_content["entry"]
        assert record["version"] == 2
        assert record["key_points"] == entry["key_points"]
        assert record["summary"] == entry["summary"]
        assert record["source_id"] != entry["source_id"]
        assert _line_one(appended) == "Added your words to the journal from 21 July."


@pytest.mark.asyncio
@pytest.mark.integration
async def test_append_can_also_rewrite_the_summary_and_title() -> None:
    container, actor = make_container()
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        entry = await _create_entry(client, "append-summary")
        appended = await client.call_tool(
            "update_journal_entry",
            {
                "entry_id": entry["id"],
                "expected_version": 1,
                "append_key_points": [_point("Middag hos mamma")],
                "summary": "En lugn dag som slutade hos mamma.",
                "title": "Lördag hos mamma",
                "idempotency_key": "append-summary-1",
            },
        )
        record = appended.structured_content["entry"]
        assert record["summary"] == "En lugn dag som slutade hos mamma."
        assert record["title"] == "Lördag hos mamma"
        assert len(record["key_points"]) == 3


@pytest.mark.asyncio
@pytest.mark.integration
async def test_append_conflicts_on_a_stale_version_and_writes_nothing() -> None:
    container, actor = make_container()
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        entry = await _create_entry(client, "append-stale")
        first = await client.call_tool(
            "update_journal_entry",
            {
                "entry_id": entry["id"],
                "expected_version": 1,
                "append_key_points": [_point("Ett")],
                "idempotency_key": "append-stale-1",
            },
        )
        assert first.structured_content["entry"]["version"] == 2

        stale = await client.call_tool(
            "update_journal_entry",
            {
                "entry_id": entry["id"],
                "expected_version": 1,
                "append_text": "Det här ska inte sparas.",
                "idempotency_key": "append-stale-2",
            },
            raise_on_error=False,
        )
        assert stale.is_error and stale.structured_content["code"] == "conflict"
        current = await client.call_tool("get_journal_entry", {"entry_id": entry["id"]})
        assert current.structured_content["entry"]["version"] == 2
        assert current.structured_content["entry"]["source_id"] == entry["source_id"]

        changed = await client.call_tool(
            "update_journal_entry",
            {
                "entry_id": entry["id"],
                "expected_version": 1,
                "append_key_points": [_point("Annat")],
                "idempotency_key": "append-stale-1",
            },
            raise_on_error=False,
        )
        assert changed.is_error

    with container.session_factory() as session:
        count = session.execute(text("SELECT count(*) FROM sidekick.journal_sources")).scalar_one()
        assert count == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_append_refuses_an_archived_entry_and_too_many_points() -> None:
    container, actor = make_container()
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        entry = await _create_entry(client, "append-limits")
        too_many = await client.call_tool(
            "update_journal_entry",
            {
                "entry_id": entry["id"],
                "expected_version": 1,
                "append_key_points": [_point(f"Punkt {number}") for number in range(49)],
                "idempotency_key": "append-limits-1",
            },
            raise_on_error=False,
        )
        assert too_many.is_error and too_many.structured_content["code"] == "validation_error"

        container.journal.archive_entry(
            actor,
            entry_id=UUID(entry["id"]),
            expected_version=1,
            idempotency_key="append-limits-archive",
        )
        archived = await client.call_tool(
            "update_journal_entry",
            {
                "entry_id": entry["id"],
                "expected_version": 2,
                "append_key_points": [_point("Sent")],
                "idempotency_key": "append-limits-2",
            },
            raise_on_error=False,
        )
        assert archived.is_error and archived.structured_content["code"] == "conflict"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_replacing_still_works_and_needs_title_and_key_points() -> None:
    container, actor = make_container()
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        entry = await _create_entry(client, "replace-compat")
        replaced = await client.call_tool(
            "update_journal_entry",
            {
                "entry_id": entry["id"],
                "expected_version": 1,
                "title": "Ny titel",
                "summary": None,
                "key_points": [_point("Bara en punkt")],
                "idempotency_key": "replace-compat-1",
            },
        )
        record = replaced.structured_content["entry"]
        assert record["summary"] is None
        assert [point["text"] for point in record["key_points"]] == ["Bara en punkt"]
        assert record["source_id"] == entry["source_id"]
        assert _line_one(replaced) == "Updated the journal entry from 21 July."

        missing = await client.call_tool(
            "update_journal_entry",
            {
                "entry_id": entry["id"],
                "expected_version": 2,
                "title": "Bara titel",
                "idempotency_key": "replace-compat-2",
            },
            raise_on_error=False,
        )
        assert missing.is_error and missing.structured_content["code"] == "validation_error"

        mixed = await client.call_tool(
            "update_journal_entry",
            {
                "entry_id": entry["id"],
                "expected_version": 2,
                "key_points": [_point("A")],
                "append_key_points": [_point("B")],
                "idempotency_key": "replace-compat-3",
            },
            raise_on_error=False,
        )
        assert mixed.is_error and mixed.structured_content["code"] == "validation_error"


async def _pending(client: Client, day: str = "2026-07-21") -> list[dict[str, Any]]:
    listed = await client.call_tool("list_pending_journal", {"from_date": day, "to_date": day})
    return listed.structured_content["items"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_replaced_source_is_not_listed_as_pending_after_one_or_two_appends() -> None:
    container, actor = make_container()
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        entry = await _create_entry(client, "append-pending")
        assert await _pending(client) == []

        for version, key in ((1, "append-pending-1"), (2, "append-pending-2")):
            appended = await client.call_tool(
                "update_journal_entry",
                {
                    "entry_id": entry["id"],
                    "expected_version": version,
                    "append_text": f"Mer text {version}.",
                    "idempotency_key": key,
                },
            )
            assert not appended.is_error, appended.structured_content
            assert await _pending(client) == []

    with container.session_factory() as session:
        count = session.execute(text("SELECT count(*) FROM sidekick.journal_sources")).scalar_one()
        assert count == 3


async def _review_harness(
    username: str, *, with_entry: bool
) -> tuple[Container, Actor, UUID, UUID, UUID | None]:
    """A source with a pending AI draft, and optionally a manual entry on that same source."""

    container = create_container(make_settings(), database_factory())
    user_id = container.auth.provision_user(username, "Append Review Owner")
    actor = Actor(
        user_id,
        frozenset(
            {
                "journal:read",
                "journal:write",
                "projects:read",
                "tasks:read",
                "tasks:write",
                "contacts:read",
            }
        ),
    )
    source = container.journal.create_source(
        actor,
        source_type=SourceType.MANUAL_TEXT,
        journal_date=date(2026, 7, 21),
        occurred_at=None,
        source_recorded_at=None,
        raw_text="Jag sov länge.",
        language="sv",
        replaces_source_id=None,
        idempotency_key=f"{username}-source",
    )
    draft_id = seed_entry_draft(container, actor, source.id, source.journal_date)
    entry_id: UUID | None = None
    if with_entry:
        entry_id = container.journal.create_manual_entry(
            actor,
            source_id=source.id,
            title="Lördag",
            summary=None,
            key_points=(KeyPoint(KeyPointKind.FACT, "Sov länge"),),
            idempotency_key=f"{username}-entry",
        ).id
    return container, actor, source.id, draft_id, entry_id


def _count_entries(container: Container, owner_id: UUID) -> int:
    with container.session_factory() as session:
        return session.execute(
            text("SELECT count(*) FROM sidekick.journal_entries WHERE owner_id = :owner"),
            {"owner": owner_id},
        ).scalar_one()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_append_text_supersedes_a_pending_draft_on_the_old_source() -> None:
    container, actor, source_id, draft_id, entry_id = await _review_harness(
        "append-supersede", with_entry=True
    )
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        before = await read_draft(client, draft_id)
        assert before["draft"]["state"] == "pending_review"
        appended = await client.call_tool(
            "update_journal_entry",
            {
                "entry_id": str(entry_id),
                "expected_version": 1,
                "append_text": "Och sedan åt vi glass.",
                "idempotency_key": "append-supersede-1",
            },
        )
        assert not appended.is_error, appended.structured_content
        assert appended.structured_content["entry"]["source_id"] != str(source_id)

        after = await read_draft(client, draft_id, content=False)
        assert after["draft"]["state"] == "superseded"
        assert after["draft"]["version"] == before["draft"]["version"] + 1

        # The old draft can no longer become a second entry.
        finalized = await call(
            client, "finalize_journal_draft", finalize_args(before, "append-supersede-final")
        )
        assert finalized.is_error and finalized.structured_content["code"] == "conflict"
        assert await _pending(client) == []

    assert _count_entries(container, actor.user_id) == 1
    with container.session_factory() as session:
        events = session.execute(
            text(
                "SELECT event, target_type, reason FROM sidekick.audit_events "
                "WHERE actor_id = :owner AND target_id = :draft"
            ),
            {"owner": actor.user_id, "draft": draft_id},
        ).all()
    assert ("journal.draft_superseded", "journal_draft", None) in [tuple(e) for e in events]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_key_point_append_leaves_a_pending_draft_alone() -> None:
    container, actor, _source_id, draft_id, entry_id = await _review_harness(
        "append-no-supersede", with_entry=True
    )
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        appended = await client.call_tool(
            "update_journal_entry",
            {
                "entry_id": str(entry_id),
                "expected_version": 1,
                "append_key_points": [_point("Glass")],
                "idempotency_key": "append-no-supersede-1",
            },
        )
        assert not appended.is_error, appended.structured_content
        draft = await read_draft(client, draft_id, content=False)
        assert draft["draft"]["state"] == "pending_review"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_replaced_source_refuses_finalize_and_a_manual_entry() -> None:
    # The defensive layer: a live replacement exists but the draft was left pending.
    container, actor, source_id, draft_id, _ = await _review_harness(
        "append-guard", with_entry=False
    )
    replacement = container.journal.create_source(
        actor,
        source_type=SourceType.MANUAL_TEXT,
        journal_date=date(2026, 7, 21),
        occurred_at=None,
        source_recorded_at=None,
        raw_text="Jag sov länge. Och åt glass.",
        language="sv",
        replaces_source_id=source_id,
        idempotency_key="append-guard-replacement",
    )
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        owned = await read_draft(client, draft_id)
        assert owned["draft"]["state"] == "pending_review"
        refused = await call(
            client, "finalize_journal_draft", finalize_args(owned, "append-guard-final")
        )
        assert refused.is_error and refused.structured_content["code"] == "conflict"
        # Still pending, so only the replacement guard can have refused it.
        again = await read_draft(client, draft_id, content=False)
        assert again["draft"]["state"] == "pending_review"

    assert _count_entries(container, actor.user_id) == 0
    with pytest.raises(ConflictError, match="journal source was replaced"):
        container.journal.create_manual_entry(
            actor,
            source_id=source_id,
            title="Dubbel",
            summary=None,
            key_points=(),
            idempotency_key="append-guard-manual-old",
        )
    assert _count_entries(container, actor.user_id) == 0
    created = container.journal.create_manual_entry(
        actor,
        source_id=replacement.id,
        title="På ersättaren",
        summary=None,
        key_points=(),
        idempotency_key="append-guard-manual-new",
    )
    assert created.source_id == replacement.id
