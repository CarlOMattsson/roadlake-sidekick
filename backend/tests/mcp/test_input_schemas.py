"""The cached input-schema lookup replaces a per-call `tools/list`; the listing is unchanged."""

from __future__ import annotations

import gzip
import json
import logging
from collections.abc import Iterator, Sequence
from typing import Any

import httpx2
import pytest
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.auth import require_scopes
from fastmcp.server.transforms import Transform
from fastmcp.tools import Tool

from sidekick.api.app import create_app, create_container
from sidekick.mcp import input_schemas
from sidekick.mcp.input_schemas import INTERNAL_LISTING, install_input_schema_lookup
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.auth import TOKEN_SCOPES
from sidekick.shared.types import new_uuid7
from tests.db import database_factory
from tests.support.settings import make_settings


def _canonical(schema: Any) -> str:
    """Key order is not part of a schema's meaning, and the test client reorders keys."""
    return json.dumps(schema, sort_keys=True)


def _schema(server: FastMCP, name: str) -> Any:
    lookup = server._mcp_server.get_tool_input_schema  # pyright: ignore[reportPrivateUsage]
    assert lookup is not None
    return lookup(name)


async def _warm(server: FastMCP) -> None:
    """The first `tools/call` builds the cache. Any call will do, even a rejected one."""
    async with Client(server) as client:
        await client.call_tool("get_task", {"task_id": str(new_uuid7())}, raise_on_error=False)


async def _listed(server: FastMCP) -> dict[str, str]:
    async with Client(server) as client:
        tools = await client.list_tools()
    return {tool.name: _canonical(tool.input_schema) for tool in tools}


@pytest.fixture(name="records")
def _records() -> Iterator[list[logging.LogRecord]]:
    records: list[logging.LogRecord] = []

    class Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = Collector(level=logging.DEBUG)
    logger = logging.getLogger("sidekick.mcp")
    previous = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)


@pytest.mark.asyncio
async def test_lookup_is_off_until_the_first_call_and_then_matches_tools_list() -> None:
    server = create_mcp_server(create_container(make_settings()), enable_auth=False)
    assert server._mcp_server.get_tool_input_schema is None  # pyright: ignore[reportPrivateUsage]

    await _warm(server)
    listed = await _listed(server)

    assert len(listed) > 50
    for name, expected in listed.items():
        assert _canonical(_schema(server, name)) == expected, name
    assert _schema(server, "no_such_tool") is None


class _KeepFirstFive(Transform):
    """A transform added after the server is built that narrows the listing."""

    async def list_tools(self, tools: Sequence[Tool]) -> Sequence[Tool]:
        return list(tools)[:5]


@pytest.mark.asyncio
async def test_lookup_covers_only_the_tools_a_later_transform_leaves_listed() -> None:
    # A transform added after `create_mcp_server` that narrows the listing: a cache built at
    # construction would list all tools. Lazy building sees the narrowed listing.
    container = create_container(make_settings())
    server = create_mcp_server(container, enable_auth=False)
    server.add_transform(_KeepFirstFive())
    async with Client(server) as client:
        narrowed = {tool.name: _canonical(tool.input_schema) for tool in await client.list_tools()}
        first = next(iter(narrowed))
        await client.call_tool(first, {}, raise_on_error=False)

    assert len(narrowed) == 5
    for name, expected in narrowed.items():
        assert _canonical(_schema(server, name)) == expected, name
    assert _schema(server, "create_project") is None


@pytest.mark.asyncio
async def test_a_tool_with_component_auth_keeps_the_sdk_path() -> None:
    # The listing then depends on the caller, which a caller-blind lookup cannot honour.
    server = FastMCP("auth-probe")
    install_input_schema_lookup(server)

    @server.tool(auth=require_scopes("a"))
    def guarded() -> str:
        return "x"

    @server.tool
    def open_tool() -> str:
        return "x"

    async with Client(server) as client:
        await client.call_tool("open_tool", {}, raise_on_error=False)

    assert server._mcp_server.get_tool_input_schema is None  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize("package", ["fastmcp", "mcp"])
def test_an_unreviewed_version_installs_nothing_and_warns_once(
    package: str, monkeypatch: pytest.MonkeyPatch, records: list[logging.LogRecord]
) -> None:
    real = input_schemas.metadata.version

    def version(name: str) -> str:
        return "0.0.0" if name == package else real(name)

    monkeypatch.setattr(input_schemas.metadata, "version", version)
    monkeypatch.setattr(input_schemas, "_warned", False)
    server = FastMCP("version-probe")
    middleware_before = len(server.middleware)

    assert install_input_schema_lookup(server) is False
    assert install_input_schema_lookup(server) is False

    assert len(server.middleware) == middleware_before
    warnings = [r for r in records if r.getMessage().startswith("mcp_input_schema_lookup_not_")]
    assert len(warnings) == 1
    assert f"{package} 0.0.0" in warnings[0].getMessage()


def test_a_server_without_the_sdk_hook_installs_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(input_schemas, "_warned", True)
    server = FastMCP("hook-probe")
    monkeypatch.setattr(server, "_mcp_server", object())
    assert install_input_schema_lookup(server) is False


class _ListSpy:
    """Counts every `FastMCP.list_tools` run: the SDK's per-call listing and any internal one."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.count = 0
        original = FastMCP.list_tools
        spy = self

        async def counting(server: FastMCP, *, run_middleware: bool = True) -> Sequence[Tool]:
            spy.count += 1
            return await original(server, run_middleware=run_middleware)

        monkeypatch.setattr(FastMCP, "list_tools", counting)


def _wire_tool_schemas(captured: list[bytes]) -> dict[str, str]:
    """The `inputSchema` of each tool in a captured `tools/list` response, in wire key order."""
    raw = b"".join(captured)
    text = (gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw).decode()
    payloads = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")] or [
        text
    ]
    body = json.loads(payloads[-1])
    result = body.get("result", body)
    return {tool["name"]: json.dumps(tool["inputSchema"]) for tool in result["tools"]}


def _client_for(app: Any, token: str) -> Client[Any]:
    def client_factory(**kwargs: Any) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver", **kwargs
        )

    return Client(
        StreamableHttpTransport(
            "http://testserver/mcp/",
            headers={"Authorization": f"Bearer {token}"},
            httpx_client_factory=client_factory,
        ),
        mode="auto",
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_tools_call_with_arguments_runs_no_listing_once_the_cache_is_built(
    monkeypatch: pytest.MonkeyPatch, records: list[logging.LogRecord]
) -> None:
    app = create_app(make_settings(), database_factory())
    user_id = app.state.container.auth.provision_user("owner", "Owner")
    token = app.state.container.auth.create_personal_token(
        user_id, "schema lookup test", TOKEN_SCOPES
    )
    spy = _ListSpy(monkeypatch)

    async with app.router.lifespan_context(app), _client_for(app, token) as client:
        first = await client.call_tool("list_projects", {"limit": 5})
        built = spy.count
        spy.count = 0
        for limit in (5, 10, 20):
            result = await client.call_tool("list_projects", {"limit": limit})
            assert result.structured_content == {"projects": [], "next_cursor": None}
        assert first.structured_content == {"projects": [], "next_cursor": None}
        # The first call pays for the listings (its own, the SDK's, the cache build), once ever.
        assert built >= 1
        assert spy.count == 0

    request_logs = [vars(r) for r in records if r.name == "sidekick.mcp.request"]
    assert len([r for r in request_logs if r.get("mcp_method") == "tools/call"]) == 4


@pytest.mark.asyncio
async def test_the_internal_listing_is_not_logged_as_a_client_request(
    records: list[logging.LogRecord],
) -> None:
    server = create_mcp_server(create_container(make_settings()), enable_auth=False)

    def listings() -> int:
        return len(
            [r for r in records if vars(r).get("mcp_method") == "tools/list"],
        )

    token = INTERNAL_LISTING.set(True)
    try:
        await server.list_tools()
    finally:
        INTERNAL_LISTING.reset(token)
    assert listings() == 0

    await server.list_tools()
    assert listings() == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_cached_schemas_are_byte_identical_to_the_tools_list_the_server_sends() -> None:
    app = create_app(make_settings(), database_factory())
    user_id = app.state.container.auth.provision_user("owner", "Owner")
    token = app.state.container.auth.create_personal_token(
        user_id, "schema wire test", TOKEN_SCOPES
    )
    captured: list[bytes] = []

    async def observed(scope: Any, receive: Any, send: Any) -> None:
        listing = (
            scope["type"] == "http" and dict(scope["headers"]).get(b"mcp-method") == b"tools/list"
        )

        async def capture(message: Any) -> None:
            if listing and message["type"] == "http.response.body":
                captured.append(bytes(message.get("body", b"")))
            await send(message)

        await app(scope, receive, capture)

    reference = create_mcp_server(app.state.container, enable_auth=False)
    async with app.router.lifespan_context(app), _client_for(observed, token) as client:
        await client.list_tools()
    await _warm(reference)

    wire = _wire_tool_schemas(captured)
    assert len(wire) > 50
    for name, on_the_wire in wire.items():
        assert json.dumps(_schema(reference, name)) == on_the_wire, name


@pytest.mark.asyncio
async def test_a_listing_middleware_that_may_depend_on_the_caller_keeps_the_sdk_path() -> None:
    from fastmcp.server.middleware.tool_injection import ToolInjectionMiddleware

    server = FastMCP("injected")

    @server.tool
    def open_tool() -> str:
        return "ok"

    server.add_middleware(ToolInjectionMiddleware(tools=[]))
    assert install_input_schema_lookup(server)
    async with Client(server) as client:
        await client.call_tool("open_tool", {})
    assert server._mcp_server.get_tool_input_schema is None  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_a_cancelled_build_is_retried_on_the_next_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    server = FastMCP("retry")

    @server.tool
    def open_tool(value: str) -> str:
        return value

    assert install_input_schema_lookup(server)
    lookup = next(
        m
        for m in server.middleware
        if isinstance(m, input_schemas._InputSchemaLookup)  # pyright: ignore[reportPrivateUsage]
    )
    real_build = lookup._build  # pyright: ignore[reportPrivateUsage]
    calls = 0

    async def cancelled_once() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise asyncio.CancelledError
        await real_build()

    async def call_next(_context: Any) -> str:
        return "done"

    monkeypatch.setattr(lookup, "_build", cancelled_once)
    with pytest.raises(asyncio.CancelledError):
        await lookup.on_call_tool(None, call_next)  # type: ignore[arg-type]
    assert server._mcp_server.get_tool_input_schema is None  # pyright: ignore[reportPrivateUsage]
    assert await lookup.on_call_tool(None, call_next) == "done"  # type: ignore[arg-type]
    assert calls == 2
    assert server._mcp_server.get_tool_input_schema is not None  # pyright: ignore[reportPrivateUsage]


def test_the_installed_libraries_have_the_internals_the_lookup_needs() -> None:
    assert input_schemas._unreviewed_reason() is None  # pyright: ignore[reportPrivateUsage]
    assert install_input_schema_lookup(FastMCP("shape-probe")) is True


def test_a_server_whose_hook_is_already_set_installs_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(input_schemas, "_warned", True)
    server = FastMCP("hook-set-probe")

    def lookup(name: str) -> None:
        del name

    server._mcp_server.get_tool_input_schema = lookup  # pyright: ignore[reportPrivateUsage]
    assert install_input_schema_lookup(server) is False


def test_an_sdk_server_without_the_constructor_parameter_installs_nothing(
    monkeypatch: pytest.MonkeyPatch, records: list[logging.LogRecord]
) -> None:
    class Changed:
        get_tool_input_schema = None

        def __init__(self) -> None:
            pass

    monkeypatch.setattr(input_schemas, "_warned", False)
    server = FastMCP("signature-probe")
    monkeypatch.setattr(server, "_mcp_server", Changed())

    assert install_input_schema_lookup(server) is False
    assert any("no longer takes get_tool_input_schema" in r.getMessage() for r in records)


def test_a_missing_build_helper_installs_nothing_and_warns(
    monkeypatch: pytest.MonkeyPatch, records: list[logging.LogRecord]
) -> None:
    import fastmcp.utilities.versions as versions

    monkeypatch.delattr(versions, "dedupe_with_versions")
    monkeypatch.setattr(input_schemas, "_warned", False)

    assert install_input_schema_lookup(FastMCP("helper-probe")) is False
    assert any("a helper the lookup needs is missing" in r.getMessage() for r in records)


@pytest.mark.policy
def test_sidekick_never_uses_per_session_component_visibility() -> None:
    """The cached lookup assumes one caller-independent catalog per server."""

    from pathlib import Path

    import sidekick

    root = Path(sidekick.__file__).parent
    offenders = [
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if any(
            needle in path.read_text(encoding="utf-8")
            for needle in ("enable_components(", "disable_components(", "reset_visibility(")
        )
    ]
    assert offenders == []
