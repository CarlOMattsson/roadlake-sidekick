"""Only allowlisted span names, attribute keys and server-owned component names are exported.

FastMCP names its spans and attributes after what the client sent, so a call to an unknown tool
whose name is an e-mail address must not reach an exporter. These tests drive a real FastMCP server
through its client with the exact request that exposed it, and also test the rules directly.
"""

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Link, SpanContext, TraceFlags, Tracer

import sidekick
from sidekick.mcp.server import _register_trusted_span_names  # pyright: ignore[reportPrivateUsage]
from sidekick.shared.observability import (
    SAFE_ATTRIBUTE_NAMES,
    SAFE_SPAN_ATTRIBUTES,
    SAFE_SPAN_NAMES,
    harden_tracer_provider,
)
from sidekick.shared.observability.span_allowlist import normalize_span_name

EMAIL = "anna.svensson@example.com"
FRAGMENTS = ("anna", "example.com", "svensson", "Johan", "tandrot")


@pytest.fixture
def exporter(monkeypatch: pytest.MonkeyPatch) -> Iterator[InMemorySpanExporter]:
    """A hardened provider with an exporting processor registered *before* hardening."""

    sink = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(sink))
    harden_tracer_provider(provider)

    def tracer_for(name: str, version: str | None = None) -> Tracer:
        return provider.get_tracer(name, version)

    monkeypatch.setattr("fastmcp.telemetry.otel_get_tracer", tracer_for)
    yield sink


def exported_text(sink: InMemorySpanExporter) -> str:
    parts: list[str] = []
    for span in sink.get_finished_spans():
        parts.append(span.name)
        parts.append(repr(dict(span.attributes or {})))
        parts.append(str(span.status.description))
        parts.extend(f"{event.name} {dict(event.attributes or {})}" for event in span.events)
        parts.extend(repr(dict(link.attributes or {})) for link in span.links)
    return "\n".join(parts)


def assert_no_personal_text(sink: InMemorySpanExporter) -> None:
    assert sink.get_finished_spans(), "the test must have produced spans"
    text = exported_text(sink)
    for fragment in FRAGMENTS:
        assert fragment not in text, text


def make_server() -> FastMCP:
    server = FastMCP("test-server")

    @server.tool
    def known_tool() -> str:
        return "ok"

    @server.resource("ui://sidekick/known.html")
    def known_resource() -> str:
        return "<html></html>"

    @server.prompt
    def known_prompt() -> str:
        return "hello"

    _register_trusted_span_names(server)
    return server


@pytest.mark.asyncio
async def test_unknown_tool_name_chosen_by_the_client_is_not_exported(
    exporter: InMemorySpanExporter,
) -> None:
    async with Client(make_server()) as client:
        with pytest.raises(ToolError):
            await client.call_tool(EMAIL, {})
    assert_no_personal_text(exporter)
    names = {span.name for span in exporter.get_finished_spans()}
    assert "tools/call tool:unknown" in names
    attributes = [dict(span.attributes or {}) for span in exporter.get_finished_spans()]
    called = next(item for item in attributes if "gen_ai.tool.name" in item)
    assert called["gen_ai.tool.name"] == "tool:unknown"
    assert called["fastmcp.component.key"] == "unknown"  # a bare key that is no registered name


@pytest.mark.asyncio
async def test_unknown_resource_and_prompt_names_are_not_exported(
    exporter: InMemorySpanExporter,
) -> None:
    async with Client(make_server()) as client:
        with pytest.raises(Exception, match=r".*"):
            await client.read_resource(f"mail://{EMAIL}/ringde-om-Johans-tandrot")
        with pytest.raises(Exception, match=r".*"):
            await client.get_prompt(f"{EMAIL}-Johan")
    assert_no_personal_text(exporter)
    attributes = [dict(span.attributes or {}) for span in exporter.get_finished_spans()]
    assert {item["mcp.resource.uri"] for item in attributes if "mcp.resource.uri" in item} == {
        "resource:unknown"
    }
    assert {item["gen_ai.prompt.name"] for item in attributes if "gen_ai.prompt.name" in item} == {
        "prompt:unknown"
    }
    names = {span.name for span in exporter.get_finished_spans()}
    assert "prompts/get prompt:unknown" in names


@pytest.mark.asyncio
async def test_registered_names_are_kept_and_session_and_user_attributes_are_dropped(
    exporter: InMemorySpanExporter,
) -> None:
    async with Client(make_server()) as client:
        await client.call_tool("known_tool", {})
        await client.read_resource("ui://sidekick/known.html")
        await client.get_prompt("known_prompt")
    finished = exporter.get_finished_spans()
    names = {span.name for span in finished}
    assert "tools/call known_tool" in names
    assert "prompts/get known_prompt" in names
    attributes = [dict(span.attributes or {}) for span in finished]
    assert {item["gen_ai.tool.name"] for item in attributes if "gen_ai.tool.name" in item} == {
        "known_tool"
    }
    assert {item["mcp.resource.uri"] for item in attributes if "mcp.resource.uri" in item} == {
        "ui://sidekick/known.html"
    }
    keys = {item["fastmcp.component.key"] for item in attributes if "fastmcp.component.key" in item}
    assert "tool:known_tool" in keys
    for item in attributes:
        assert not {"enduser.id", "enduser.scope", "mcp.session.id"} & item.keys()


def test_attribute_keys_and_event_and_link_attributes_follow_the_allowlist(
    exporter: InMemorySpanExporter,
) -> None:
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    harden_tracer_provider(provider)
    tracer = provider.get_tracer("t")
    context = SpanContext(1, 1, False, TraceFlags(1))
    with tracer.start_as_current_span(
        f"GET /{EMAIL}",
        attributes={
            "http.url": f"https://x/{EMAIL}",
            "enduser.id": EMAIL,
            "outcome": "success",
            "mcp.tool.name": "known_tool",
            "mcp.method.name": f"made/up {EMAIL}",
        },
        links=[Link(context, {"x": EMAIL})],
    ) as span:
        span.add_event(f"saw {EMAIL}", {"detail": EMAIL, "outcome": "success"})
    (done,) = exporter.get_finished_spans()
    assert done.name == "span:unknown"
    assert dict(done.attributes or {}) == {
        "outcome": "success",
        "mcp.tool.name": "known_tool",
        "mcp.method.name": "unknown",
    }
    (event,) = done.events
    assert event.name == "event"
    assert dict(event.attributes or {}) == {"outcome": "success"}
    assert [dict(link.attributes or {}) for link in done.links] == [{}]
    assert_no_personal_text(exporter)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("mcp.tool", "mcp.tool"),
        ("tools/list", "tools/list"),
        ("tools/call", "tools/call"),
        (f"tools/call {EMAIL}", "tools/call tool:unknown"),
        (f"resources/read mail://{EMAIL}", "resources/read resource:unknown"),
        (f"prompts/get {EMAIL}", "prompts/get prompt:unknown"),
        (f"delegate {EMAIL}", "delegate unknown"),
        (f"POST /{EMAIL}", "span:unknown"),
        (EMAIL, "span:unknown"),
        ("", "span:unknown"),
    ],
)
def test_span_names_are_fixed_or_registered_or_unknown(name: str, expected: str) -> None:
    assert normalize_span_name(name) == expected


@pytest.mark.policy
def test_every_span_name_sidekick_creates_is_on_the_allowlist() -> None:
    source = Path(sidekick.__file__).parent
    # Telemetry port spans only; `re.Match.span("group")` is unrelated to tracing.
    pattern = re.compile(r"telemetry\.span\(\s*\"([^\"]+)\"")
    found = {
        match
        for path in source.rglob("*.py")
        for match in pattern.findall(path.read_text(encoding="utf-8"))
    }
    assert {"mcp.tool", "db.transaction"} <= found, "the scan must find Sidekick's span calls"
    assert found <= SAFE_SPAN_NAMES


def test_port_attributes_are_a_subset_of_the_span_allowlist() -> None:
    assert SAFE_ATTRIBUTE_NAMES <= SAFE_SPAN_ATTRIBUTES
    forbidden = {"enduser.id", "enduser.scope", "mcp.session.id", "http.url", "url.full"}
    assert not forbidden & SAFE_SPAN_ATTRIBUTES
