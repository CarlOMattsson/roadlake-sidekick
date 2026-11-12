"""Rejected MCP tool arguments are named by field and type, never echoed back (D-058, redaction).

Two paths reject a call before the tool body runs: FastMCP's pydantic validation (prefix
"Invalid tool arguments:") and the MCP SDK's JSON Schema pre-check (prefix "Input validation
error:"). Each test pins the prefix, so an SDK change that bypasses the redaction fails here.
"""

import logging
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastmcp import Client
from mcp.types import TextContent

from sidekick.api.app import create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.auth import MCP_SCOPES
from sidekick.shared.types import Actor
from tests.support.settings import make_settings

ENTRY_SENTINEL = "sentinel-entry-id-4c1e"
TITLE_SENTINEL = "sentinel-journal-title-8d2b"
REF_SENTINEL = "sentinel-work-ref-6a9f"

PYDANTIC_PREFIX = "The request was missing or had a wrong value. Fields:"
SDK_PREFIX = "The request was missing or had a wrong value. Fields:"


class _Collector(logging.Handler):
    """Keeps every record that reaches it. FastMCP and Sidekick set `propagate = False` on their
    namespaces, so `caplog` alone would miss the records this test must see."""

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def rendered(self) -> str:
        formatter = logging.Formatter("%(levelname)s %(name)s %(message)s")
        parts = [formatter.format(record) for record in self.records]
        parts.extend(repr(record.__dict__) for record in self.records)
        return "\n".join(parts)


@pytest.fixture(name="all_logs")
def _all_logs() -> Iterator[_Collector]:
    collector = _Collector()
    loggers: list[logging.Logger] = [logging.getLogger()]
    loggers.extend(
        item
        for item in logging.root.manager.loggerDict.values()
        if isinstance(item, logging.Logger)
    )
    for logger in loggers:
        logger.addHandler(collector)
    try:
        yield collector
    finally:
        for logger in loggers:
            logger.removeHandler(collector)


def _server() -> Any:
    # Every scope, so a refusal can only come from input validation, not from the caller's scopes.
    actor = Actor(uuid4(), frozenset(MCP_SCOPES))
    return create_mcp_server(
        create_container(make_settings()), actor_provider=lambda: actor, enable_auth=False
    )


def _text(response: Any) -> str:
    return "\n".join(block.text for block in response.content if isinstance(block, TextContent))


def _assert_redacted(
    response: Any,
    sentinel: str,
    prefix: str,
    fields: tuple[str, ...],
    all_logs: _Collector,
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert response.is_error
    text = _text(response)
    assert text.startswith(prefix), text
    for field in fields:
        assert field in text, text

    assert sentinel not in str(response.content)
    assert sentinel not in str(response.structured_content)
    assert sentinel not in text
    assert sentinel not in all_logs.rendered()
    assert sentinel not in caplog.text


@pytest.mark.asyncio
async def test_journal_pydantic_error_names_the_field_and_hides_the_value(
    all_logs: _Collector, caplog: pytest.LogCaptureFixture
) -> None:
    server = _server()
    async with Client(server) as client:
        response = await client.call_tool(
            "update_journal_entry",
            {
                # Passes the JSON Schema (no format check) and fails pydantic's UUID parse.
                "entry_id": ENTRY_SENTINEL,
                "expected_version": 1,
                "title": "Ny titel",
                "summary": None,
                "key_points": [],
                "idempotency_key": "redaction-probe-001",
            },
            raise_on_error=False,
        )

    _assert_redacted(
        response, ENTRY_SENTINEL, PYDANTIC_PREFIX, ("entry_id: invalid UUID",), all_logs, caplog
    )


@pytest.mark.asyncio
async def test_journal_schema_error_names_the_field_and_hides_the_value(
    all_logs: _Collector, caplog: pytest.LogCaptureFixture
) -> None:
    server = _server()
    async with Client(server) as client:
        response = await client.call_tool(
            "update_journal_entry",
            {
                "entry_id": str(uuid4()),
                "expected_version": 1,
                # Wrong shape: rejected by the SDK's JSON Schema check before FastMCP runs.
                # title is optional (None allowed), so the schema names the failing anyOf.
                "title": [TITLE_SENTINEL],
                "summary": None,
                "key_points": [],
                "idempotency_key": "redaction-probe-002",
            },
            raise_on_error=False,
        )

    _assert_redacted(response, TITLE_SENTINEL, SDK_PREFIX, ("title: anyOf",), all_logs, caplog)


@pytest.mark.asyncio
async def test_work_argument_errors_name_fields_and_hide_rejected_values(
    all_logs: _Collector, caplog: pytest.LogCaptureFixture
) -> None:
    server = _server()
    async with Client(server) as client:
        response = await client.call_tool(
            "show_work_changes",
            {"refs": [{"kind": "task", "id": REF_SENTINEL}]},
            raise_on_error=False,
        )

    _assert_redacted(
        response, REF_SENTINEL, PYDANTIC_PREFIX, ("refs.0.id: invalid UUID",), all_logs, caplog
    )
