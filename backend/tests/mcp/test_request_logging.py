"""MCP request logs name the method, the tool and the outcome, and never carry a value (D-058).

The records are captured on the `sidekick.mcp.request` logger itself. `configure_observability`
sets `propagate = False` on `sidekick`, so a root-level `caplog` would miss them once an earlier
test has configured observability.
"""

import json
import logging
from collections.abc import Iterator
from typing import ClassVar

import httpx
import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import ToolResult
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import Receive, Scope, Send

from sidekick.mcp.request_log import (
    LOGGER,
    McpRequestLogging,
    McpTransportLogging,
    transport_reason,
)
from sidekick.mcp.results import error_result
from sidekick.mcp.validation_errors import install_validation_error_redaction
from sidekick.shared.errors import InvalidInputError
from sidekick.shared.observability import register_trusted_mcp_names, safe_mcp_method

VALUE_SENTINEL = "sentinel-request-value-5b8e"
COUNT_SENTINEL = "sentinel-request-count-2d7a"
BODY_SENTINEL = "sentinel-request-body-9c4f"
VERSION_SENTINEL = "sentinel-request-version-4e1a"


class _Collector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def rendered(self) -> str:
        parts = [record.getMessage() for record in self.records]
        parts.extend(repr(vars(record)) for record in self.records)
        return "\n".join(parts)

    def fields(self, method: str) -> dict[str, object]:
        """The one record for `method`. The client's `initialize` handshake logs too."""
        matches = [
            vars(record) for record in self.records if vars(record).get("mcp_method") == method
        ]
        assert len(matches) == 1, matches
        return matches[0]


@pytest.fixture(name="records")
def _records() -> Iterator[_Collector]:
    collector = _Collector()
    previous = LOGGER.level
    LOGGER.addHandler(collector)
    LOGGER.setLevel(logging.INFO)
    try:
        yield collector
    finally:
        LOGGER.removeHandler(collector)
        LOGGER.setLevel(previous)


def _server(*, schema_checked: bool = False) -> FastMCP:
    mcp = FastMCP("request-log-probe")
    mcp.add_middleware(McpRequestLogging())
    if schema_checked:
        install_validation_error_redaction(mcp)

    @mcp.tool()
    def echo(value: str) -> str:
        return "ok"

    @mcp.tool()
    def sidekick_failure(value: str) -> ToolResult:
        return error_result(InvalidInputError(value))

    @mcp.tool()
    def raises(value: str) -> str:
        raise ToolError(f"tool failed {value}")

    @mcp.tool()
    def counted(count: int) -> str:
        return "ok"

    # The registry the span allowlist uses; `create_mcp_server` fills it for the real server.
    register_trusted_mcp_names(tools=["echo", "sidekick_failure", "raises", "counted"])
    return mcp


@pytest.mark.asyncio
async def test_a_successful_tool_call_logs_its_name_and_no_argument_value(
    records: _Collector,
) -> None:
    async with Client(_server()) as client:
        response = await client.call_tool_mcp("echo", {"value": VALUE_SENTINEL})

    assert not response.isError
    fields = records.fields("tools/call")
    assert fields["mcp_method"] == "tools/call"
    assert fields["mcp_tool_name"] == "echo"
    assert fields["outcome"] == "success"
    assert "mcp_error_class" not in fields
    # Timing is a plain number of milliseconds, next to the tool name and nothing else.
    assert isinstance(fields["duration_ms"], float) and fields["duration_ms"] >= 0
    assert VALUE_SENTINEL not in records.rendered()


@pytest.mark.asyncio
async def test_a_sidekick_error_result_logs_its_closed_code_and_no_argument_value(
    records: _Collector,
) -> None:
    async with Client(_server()) as client:
        response = await client.call_tool_mcp("sidekick_failure", {"value": VALUE_SENTINEL})

    assert response.isError
    fields = records.fields("tools/call")
    assert fields["mcp_tool_name"] == "sidekick_failure"
    assert fields["outcome"] == "error"
    assert fields["mcp_error_class"] == "ToolError"
    assert fields["mcp_error_code"] == "validation_error"
    assert VALUE_SENTINEL not in records.rendered()


@pytest.mark.asyncio
async def test_an_error_reply_carries_the_id_of_the_request_log_line(
    records: _Collector, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Request:
        scope: ClassVar[dict[str, str]] = {"sidekick.correlation_id": "corr-from-the-middleware"}

    monkeypatch.setattr("sidekick.mcp.correlation.get_http_request", lambda: _Request())
    async with Client(_server()) as client:
        response = await client.call_tool_mcp("sidekick_failure", {"value": VALUE_SENTINEL})

    assert response.isError
    assert response.structuredContent is not None
    assert response.structuredContent["correlation_id"] == "corr-from-the-middleware"
    assert records.fields("tools/call")["correlation_id"] == "corr-from-the-middleware"


@pytest.mark.asyncio
async def test_an_error_reply_outside_a_request_gets_a_fresh_id(records: _Collector) -> None:
    first = error_result(InvalidInputError("a")).structured_content
    second = error_result(InvalidInputError("b")).structured_content

    assert first is not None and second is not None
    assert first["correlation_id"] != second["correlation_id"]


@pytest.mark.asyncio
async def test_a_raised_tool_error_logs_its_class_name(records: _Collector) -> None:
    async with Client(_server()) as client:
        response = await client.call_tool_mcp("raises", {"value": VALUE_SENTINEL})

    assert response.isError
    fields = records.fields("tools/call")
    assert fields["mcp_tool_name"] == "raises"
    assert fields["outcome"] == "error"
    assert fields["mcp_error_class"] == "ToolError"
    assert VALUE_SENTINEL not in records.rendered()


@pytest.mark.parametrize(
    "name", ["ring_anna_svensson", "ECHO", "echo ", "anna.svensson@example.com"]
)
@pytest.mark.asyncio
async def test_an_unregistered_tool_name_is_logged_as_unknown(
    name: str, records: _Collector
) -> None:
    # Only names the server registers are logged; whatever else a client sends is a fixed marker.
    async with Client(_server()) as client:
        response = await client.call_tool_mcp(name, {"value": VALUE_SENTINEL})

    assert response.isError
    fields = records.fields("tools/call")
    assert fields["mcp_tool_name"] == "unknown"
    assert fields["outcome"] == "error"
    assert name not in records.rendered()
    assert VALUE_SENTINEL not in records.rendered()


@pytest.mark.asyncio
async def test_a_protocol_request_logs_its_method_and_no_tool_name(records: _Collector) -> None:
    async with Client(_server()) as client:
        await client.list_tools()

    fields = records.fields("tools/list")
    assert fields["mcp_method"] == "tools/list"
    assert fields["outcome"] == "success"
    assert "mcp_tool_name" not in fields


@pytest.mark.asyncio
async def test_a_schema_rejection_logs_its_tool_name_and_no_value(records: _Collector) -> None:
    # `install_validation_error_redaction` checks the arguments against the listed JSON Schema in
    # middleware; `McpRequestLogging` records that rejection with the closed `json_schema` code.
    async with Client(_server(schema_checked=True)) as client:
        response = await client.call_tool_mcp("counted", {"count": COUNT_SENTINEL})

    assert response.isError
    fields = records.fields("tools/call")
    assert fields["mcp_tool_name"] == "counted"
    assert fields["outcome"] == "error"
    assert fields["mcp_error_code"] == "json_schema"
    assert COUNT_SENTINEL not in records.rendered()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("tools/call", "tools/call"),
        ("resources/read", "resources/read"),
        ("notifications/initialized", "notifications/initialized"),
        ("ring_anna_svensson", "other"),
        ("tools/call;drop", "other"),
        ("Tools Call with spaces", "other"),
        ("a" * 65, "other"),
        ("", "other"),
        (None, "other"),
    ],
)
def test_only_protocol_methods_are_logged_by_name(raw: str | None, expected: str) -> None:
    assert safe_mcp_method(raw) == expected


def _rpc_error(code: int, message: str) -> bytes:
    return json.dumps(
        {"jsonrpc": "2.0", "id": "server-error", "error": {"code": code, "message": message}}
    ).encode()


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (_rpc_error(-32600, "Bad Request: Missing session ID"), "missing_session_id"),
        (
            _rpc_error(-32600, "Bad Request: Unsupported protocol version: 1999-01-01."),
            "unsupported_protocol_version",
        ),
        (_rpc_error(-32700, "Parse error: Expecting value: line 1 column 1"), "parse_error"),
        (_rpc_error(-32602, "Validation error: 1 validation error"), "invalid_params"),
        (b"Invalid Content-Type header", "invalid_content_type"),
        (b"something the server never writes", "unclassified"),
        (b"[1, 2]", "unclassified"),
        (b"", "unclassified"),
    ],
)
def test_a_transport_400_body_maps_to_a_fixed_reason_code(body: bytes, expected: str) -> None:
    assert transport_reason(body) == expected


@pytest.mark.asyncio
async def test_a_transport_400_logs_its_reason_code_and_never_the_body(
    records: _Collector,
) -> None:
    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)
        await request.body()
        response = JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": "server-error",
                "error": {"code": -32700, "message": f"Parse error: {BODY_SENTINEL}"},
            },
            status_code=400,
        )
        await response(scope, receive, send)

    async def with_correlation(scope: Scope, receive: Receive, send: Send) -> None:
        scope["sidekick.correlation_id"] = "corr-request-log-1"
        await McpTransportLogging(inner)(scope, receive, send)

    transport = httpx.ASGITransport(app=with_correlation)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/", content=BODY_SENTINEL.encode())

    assert response.status_code == 400
    assert len(records.records) == 1
    fields = vars(records.records[0])
    assert fields["mcp_error_code"] == "parse_error"
    assert fields["http_status"] == 400
    assert fields["http_method"] == "POST"
    assert fields["correlation_id"] == "corr-request-log-1"
    assert BODY_SENTINEL not in records.rendered()


async def _post_to_transport_400(
    records: _Collector, message: str, headers: dict[str, str] | None = None
) -> dict[str, object]:
    """Send one request through `McpTransportLogging` to an inner app that answers 400."""

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(
            {"jsonrpc": "2.0", "id": "server-error", "error": {"code": -32600, "message": message}},
            status_code=400,
        )
        await response(scope, receive, send)

    transport = httpx.ASGITransport(app=McpTransportLogging(inner))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/", content=b"{}", headers=headers or {})

    assert response.status_code == 400
    assert len(records.records) == 1
    return vars(records.records[0])


@pytest.mark.asyncio
async def test_an_unsupported_protocol_version_logs_the_date_the_client_sent(
    records: _Collector,
) -> None:
    fields = await _post_to_transport_400(
        records,
        "Bad Request: Unsupported protocol version: 2026-07-28. Supported versions: 2025-11-25",
        headers={"mcp-protocol-version": "2026-07-28"},
    )

    assert fields["mcp_error_code"] == "unsupported_protocol_version"
    assert fields["mcp_protocol_version"] == "2026-07-28"


@pytest.mark.asyncio
async def test_an_unsupported_protocol_version_logs_invalid_for_a_value_that_is_not_a_date(
    records: _Collector,
) -> None:
    fields = await _post_to_transport_400(
        records,
        "Bad Request: Unsupported protocol version: x. Supported versions: 2025-11-25",
        headers={"mcp-protocol-version": f"2026-07-28-{VERSION_SENTINEL}"},
    )

    assert fields["mcp_error_code"] == "unsupported_protocol_version"
    assert fields["mcp_protocol_version"] == "invalid"
    assert VERSION_SENTINEL not in records.rendered()


@pytest.mark.asyncio
async def test_an_unsupported_protocol_version_without_the_header_logs_invalid(
    records: _Collector,
) -> None:
    fields = await _post_to_transport_400(
        records, "Bad Request: Unsupported protocol version: 1999-01-01. Supported versions: x"
    )

    assert fields["mcp_protocol_version"] == "invalid"


@pytest.mark.asyncio
async def test_other_transport_rejections_do_not_log_a_protocol_version(
    records: _Collector,
) -> None:
    fields = await _post_to_transport_400(
        records,
        "Bad Request: Missing session ID",
        headers={"mcp-protocol-version": "2025-11-25"},
    )

    assert fields["mcp_error_code"] == "missing_session_id"
    assert "mcp_protocol_version" not in fields


@pytest.mark.asyncio
async def test_a_successful_transport_response_logs_nothing(records: _Collector) -> None:
    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        await Response("ok", status_code=200)(scope, receive, send)

    transport = httpx.ASGITransport(app=McpTransportLogging(inner))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/", content=b"{}")

    assert response.status_code == 200
    assert records.records == []
