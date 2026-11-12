"""Journal telemetry, audit, provider, and MCP narration redaction contract."""

from typing import Any

import pytest
from fastmcp import Client
from sqlalchemy import select

from sidekick.api.app import create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.observability import safe_log_fields, safe_telemetry_attributes
from sidekick.shared.persistence.models import AuditEventRow
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.fakes import (
    JOURNAL_REDACTION_SENTINEL_ONE,
    JOURNAL_REDACTION_SENTINEL_TWO,
)
from tests.support.settings import make_settings
from tests.support.telemetry import CaptureTelemetry


def _sensitive_matrix() -> dict[str, Any]:
    return {
        "raw_text": JOURNAL_REDACTION_SENTINEL_ONE,
        "source_content": JOURNAL_REDACTION_SENTINEL_ONE,
        "summary_content": JOURNAL_REDACTION_SENTINEL_TWO,
        "prompt": JOURNAL_REDACTION_SENTINEL_TWO,
        "model_output": JOURNAL_REDACTION_SENTINEL_ONE,
        "candidate_label": JOURNAL_REDACTION_SENTINEL_TWO,
        "candidate_context": JOURNAL_REDACTION_SENTINEL_ONE,
        "entry_title": JOURNAL_REDACTION_SENTINEL_TWO,
        "email": "private-journal@example.invalid",
        "phone": "+46123456789",
        "authorization": "Bearer journal-secret-token",
        "cookie": "session=journal-secret-cookie",
        "query": JOURNAL_REDACTION_SENTINEL_ONE,
        "sql_parameters": JOURNAL_REDACTION_SENTINEL_TWO,
        "safe_operation": "journal.source_created",
        "outcome": "success",
    }


@pytest.mark.integration
def test_journal_telemetry_allowlist_drops_content_credentials_and_provider_data() -> None:
    values = _sensitive_matrix()
    telemetry = safe_telemetry_attributes(values)
    logs = safe_log_fields(values)

    assert telemetry == {"outcome": "success"}
    assert logs == {"outcome": "success"}
    serialized = str((telemetry, logs))
    assert JOURNAL_REDACTION_SENTINEL_ONE not in serialized
    assert JOURNAL_REDACTION_SENTINEL_TWO not in serialized
    assert "journal-secret-token" not in serialized
    assert "journal-secret-cookie" not in serialized


@pytest.mark.asyncio
@pytest.mark.integration
async def test_mcp_sql_audit_and_problem_surfaces_redact_journal_sentinels() -> None:
    telemetry = CaptureTelemetry()
    factory = database_factory()
    container = create_container(make_settings(), factory, telemetry)
    owner_id = container.auth.provision_user("journal-telemetry-owner", "Owner")
    source_text = f"{JOURNAL_REDACTION_SENTINEL_ONE} source text"
    entry_title = f"{JOURNAL_REDACTION_SENTINEL_TWO} title"
    actor = Actor(owner_id, frozenset({"journal:read", "journal:write"}))
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        written = await client.call_tool(
            "write_journal_entry",
            {
                "journal_date": "2026-07-21",
                "title": entry_title,
                "source_text": source_text,
                "summary": JOURNAL_REDACTION_SENTINEL_ONE,
                "key_points": [{"kind": "decision", "text": JOURNAL_REDACTION_SENTINEL_TWO}],
                "idempotency_key": "journal-telemetry-entry",
            },
        )
        assert written.structured_content is not None
        entry_id = written.structured_content["entry"]["id"]

        # A rejected call names the field and never echoes the rejected content.
        failed = await client.call_tool(
            "write_journal_entry",
            {"journal_date": "2026-07-21", "source_text": source_text},
            raise_on_error=False,
        )
        assert failed.is_error
        assert source_text not in str(failed.content)

        # D-060: the model may read all journal content, and
        # include_content now defaults to True, so the text block carries it.
        opted_in = await client.call_tool(
            "get_journal_entry", {"entry_id": entry_id, "include_content": True}
        )
        opted_in_narration = str(opted_in.content)
        assert JOURNAL_REDACTION_SENTINEL_ONE in opted_in_narration
        assert JOURNAL_REDACTION_SENTINEL_TWO in opted_in_narration

        # An explicit opt-out still leaves the summary out; the title stays visible (D-060).
        opted_out = await client.call_tool(
            "get_journal_entry", {"entry_id": entry_id, "include_content": False}
        )
        assert JOURNAL_REDACTION_SENTINEL_ONE not in str(opted_out.content)

    with factory() as session:
        events = list(
            session.scalars(select(AuditEventRow).where(AuditEventRow.actor_id == owner_id))
        )
    audit_metadata = str(
        [
            {
                "event": event.event,
                "outcome": event.outcome,
                "reason": event.reason,
                "correlation_id": event.correlation_id,
                "target_type": event.target_type,
                "target_id": event.target_id,
            }
            for event in events
        ]
    )
    serialized = str(telemetry.records) + audit_metadata
    assert JOURNAL_REDACTION_SENTINEL_ONE not in serialized
    assert JOURNAL_REDACTION_SENTINEL_TWO not in serialized
    assert "private-journal@example.invalid" not in serialized
    assert "journal-secret-token" not in serialized
    assert "journal-secret-cookie" not in serialized
