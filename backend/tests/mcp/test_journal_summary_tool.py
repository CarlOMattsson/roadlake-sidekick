"""The model-visible daily summary write, and the entry fingerprint that guards it."""

from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastmcp import Client

from sidekick.api.app import Container, create_container
from sidekick.journal.domain.entry import KeyPoint, KeyPointKind
from sidekick.journal.domain.source import SourceType
from sidekick.journal.domain.summary import entry_fingerprint
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings

JOURNAL_DATE = date(2026, 7, 21)
JOURNAL_DATE_TEXT = "2026-07-21"
ZERO_FINGERPRINT = "0" * 64


def make_state() -> tuple[Container, Actor, Any]:
    container = create_container(make_settings(), database_factory())
    user_id = container.auth.provision_user("mcp-summary-owner", "MCP Summary Owner")
    actor = Actor(
        user_id,
        frozenset(
            {"journal:read", "journal:write", "projects:read", "tasks:read", "contacts:read"}
        ),
    )
    source = container.journal_capture.create_source(
        actor,
        source_type=SourceType.MANUAL_TEXT,
        journal_date=JOURNAL_DATE,
        occurred_at=datetime(2026, 7, 21, 9, 0, tzinfo=UTC),
        source_recorded_at=datetime(2026, 7, 24, 8, 0, tzinfo=UTC),
        raw_text="Källtext för sammanfattningstestet.",
        language="sv",
        replaces_source_id=None,
        idempotency_key="mcp-summary-source",
    )
    entry = container.journal_capture.create_manual_entry(
        actor,
        source_id=source.id,
        title="Sammanfattningsbar post",
        summary="Ett manuellt beslut.",
        key_points=(KeyPoint(KeyPointKind.DECISION, "Följ upp beslutet."),),
        idempotency_key="mcp-summary-entry",
    )
    return container, actor, entry


def _structured(outcome: Any) -> dict[str, Any]:
    assert outcome.structured_content is not None
    structured: dict[str, Any] = outcome.structured_content
    return structured


@pytest.mark.asyncio
@pytest.mark.integration
async def test_set_daily_summary_writes_once_and_get_journal_day_exposes_the_fingerprint() -> None:
    container, actor, entry = make_state()
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    fingerprint = entry_fingerprint([entry])

    async with Client(server) as client:
        before = await client.call_tool("get_journal_day", {"journal_date": JOURNAL_DATE_TEXT})
        day = _structured(before)
        assert day["entry_fingerprint"] == fingerprint
        assert fingerprint in before.content[0].text
        assert before.content[0].text.startswith("1 entry on 21 July, without a daily summary.\n")
        assert day["summary"]["exists"] is False

        args = {
            "journal_date": JOURNAL_DATE_TEXT,
            "summary_text": "Dagens översikt.",
            "expected_entry_fingerprint": day["entry_fingerprint"],
            "expected_summary_version": None,
            "idempotency_key": "mcp-summary-write-1",
        }
        first = await client.call_tool("set_daily_journal_summary", args)
        replay = await client.call_tool("set_daily_journal_summary", args)
        assert _structured(first) == _structured(replay)
        # Line 1 names the day without the version; the version sits on line 2.
        assert first.content[0].text == (
            "Saved the daily summary for 21 July.\nSummary 2026-07-21 v1."
        )

        summary = _structured(first)["summary"]
        assert summary["exists"] is True
        assert summary["origin"] == "manual"
        assert summary["status"] == "current"
        assert summary["version"] == 1
        assert summary["content"]["overview"] == "Dagens översikt."
        assert summary["source_fingerprint"] == fingerprint
        assert summary["entry_ids"] == [str(entry.id)]
        assert summary["changed_entry_count"] == 0

        after = _structured(
            await client.call_tool("get_journal_day", {"journal_date": JOURNAL_DATE_TEXT})
        )
        assert after["entry_fingerprint"] == fingerprint
        assert after["summary"]["version"] == 1
        assert after["summary"]["content"]["overview"] == "Dagens översikt."


@pytest.mark.asyncio
@pytest.mark.integration
async def test_set_daily_summary_refuses_stale_fingerprint_and_version_with_stale_version() -> None:
    container, actor, entry = make_state()
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    fingerprint = entry_fingerprint([entry])
    base: dict[str, Any] = {
        "journal_date": JOURNAL_DATE_TEXT,
        "summary_text": "Första översikten.",
        "expected_entry_fingerprint": fingerprint,
        "expected_summary_version": None,
        "idempotency_key": "mcp-summary-base-1",
    }

    async with Client(server) as client:
        wrong = await client.call_tool(
            "set_daily_journal_summary",
            {
                **base,
                "expected_entry_fingerprint": ZERO_FINGERPRINT,
                "idempotency_key": "mcp-wrong",
            },
            raise_on_error=False,
        )
        assert wrong.is_error is True
        assert _structured(wrong)["code"] == "conflict"
        assert _structured(wrong)["reason"] == "stale_version"

        await client.call_tool("set_daily_journal_summary", base)

        # A summary already exists, so writing again without its current version is stale.
        no_version = await client.call_tool(
            "set_daily_journal_summary",
            {**base, "summary_text": "Ny översikt.", "idempotency_key": "mcp-no-version"},
            raise_on_error=False,
        )
        assert no_version.is_error is True
        assert _structured(no_version)["reason"] == "stale_version"

        # An entry edit moves the fingerprint on, so the value captured before it is refused.
        await client.call_tool(
            "update_journal_entry",
            {
                "entry_id": str(entry.id),
                "expected_version": 1,
                "title": "Ändrad titel",
                "summary": "Ändrad sammanfattning.",
                "key_points": [],
                "idempotency_key": "mcp-summary-entry-edit",
            },
        )
        after_edit = await client.call_tool(
            "set_daily_journal_summary",
            {**base, "expected_summary_version": 1, "idempotency_key": "mcp-after-edit"},
            raise_on_error=False,
        )
        assert after_edit.is_error is True
        assert _structured(after_edit)["reason"] == "stale_version"

        fresh = _structured(
            await client.call_tool("get_journal_day", {"journal_date": JOURNAL_DATE_TEXT})
        )
        assert fresh["entry_fingerprint"] != fingerprint
        assert fresh["summary"]["status"] == "stale"

        refreshed = await client.call_tool(
            "set_daily_journal_summary",
            {
                "journal_date": JOURNAL_DATE_TEXT,
                "summary_text": "Uppdaterad översikt.",
                "expected_entry_fingerprint": fresh["entry_fingerprint"],
                "expected_summary_version": fresh["summary"]["version"],
                "idempotency_key": "mcp-refreshed",
            },
        )
        assert _structured(refreshed)["summary"]["version"] == fresh["summary"]["version"] + 1

    assert container.journal_day.get_summary(actor, JOURNAL_DATE)[1] is not None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_set_daily_summary_needs_journal_write_and_writes_nothing_without_it() -> None:
    container, actor, _entry = make_state()
    reader = Actor(actor.user_id, frozenset({"journal:read"}))
    server = create_mcp_server(container, actor_provider=lambda: reader, enable_auth=False)

    async with Client(server) as client:
        refused = await client.call_tool(
            "set_daily_journal_summary",
            {
                "journal_date": JOURNAL_DATE_TEXT,
                "summary_text": "Ska inte sparas.",
                "expected_entry_fingerprint": entry_fingerprint([_entry]),
                "expected_summary_version": None,
                "idempotency_key": "mcp-read-only",
            },
            raise_on_error=False,
        )

    assert refused.is_error is True
    assert _structured(refused)["code"] == "forbidden"
    assert container.journal_day.get_summary(actor, JOURNAL_DATE)[1] is None
