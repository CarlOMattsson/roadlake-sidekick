"""MCP App resources declare the host contract on the wire, not only on the Python object."""

from pathlib import Path

import pytest
from fastmcp import Client
from mcp.shared.exceptions import MCPError

from sidekick.api.app import create_container
from sidekick.mcp import app_meta
from sidekick.mcp.server import create_mcp_server
from sidekick.mcp.sidekick_app import SIDEKICK_APP_URI
from sidekick.shared.types import Actor, new_uuid7
from tests.support.settings import make_settings

ALL_APP_URIS = (SIDEKICK_APP_URI,)
UNIFIED_HTML = "<!doctype html><html><head></head><body>UNIFIED</body></html>"
# Every read scope that opens the app on its own.
APP_READ_SCOPES = (
    "tasks:read",
    "projects:read",
    "contacts:read",
    "journal:read",
    "shopping:read",
)


@pytest.mark.asyncio
@pytest.mark.parametrize("uri", ALL_APP_URIS)
async def test_app_resource_meta_has_no_border_and_an_empty_csp(uri: str) -> None:
    reader = Actor(new_uuid7(), frozenset({"tasks:read", "journal:read", "shopping:read"}))
    server = create_mcp_server(
        create_container(make_settings()), actor_provider=lambda: reader, enable_auth=False
    )
    async with Client(server) as client:
        resource = (await client.read_resource(uri))[0]
    assert resource.mimeType == "text/html;profile=mcp-app"
    assert resource.meta is not None
    ui = resource.meta["ui"]
    assert ui["prefersBorder"] is False
    # An empty CSP object means no connect, resource, frame or base-uri domains are allowed.
    assert ui["csp"] == {}
    assert "domain" not in ui
    assert "permissions" not in ui


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "expected"),
    [({}, "sv"), ({"mcp_app_locale": "en"}, "en")],
)
async def test_every_app_resource_carries_the_sidekick_app_locale(
    overrides: dict[str, str], expected: str
) -> None:
    settings = make_settings().model_copy(update=overrides)
    reader = Actor(new_uuid7(), frozenset({"tasks:read", "journal:read", "shopping:read"}))
    server = create_mcp_server(
        create_container(settings), actor_provider=lambda: reader, enable_auth=False
    )
    async with Client(server) as client:
        for uri in ALL_APP_URIS:
            html = (await client.read_resource(uri))[0].text
            assert f'<meta name="sidekick-app-locale" content="{expected}">' in html


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "expected"),
    [({}, "sv"), ({"mcp_app_locale": "en"}, "en")],
)
async def test_every_app_resource_serves_the_unified_app(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, overrides: dict[str, str], expected: str
) -> None:
    (tmp_path / app_meta.UNIFIED_APP_FILE).write_text(UNIFIED_HTML, encoding="utf-8")
    monkeypatch.setattr("sidekick.mcp.app_meta.APPS_DIR", tmp_path)
    settings = make_settings().model_copy(update=overrides)
    reader = Actor(new_uuid7(), frozenset({"tasks:read", "journal:read", "shopping:read"}))
    server = create_mcp_server(
        create_container(settings), actor_provider=lambda: reader, enable_auth=False
    )
    async with Client(server) as client:
        for uri in ALL_APP_URIS:
            html = (await client.read_resource(uri))[0].text
            assert "UNIFIED" in html, uri
            assert f'<meta name="sidekick-app-locale" content="{expected}">' in html, uri


@pytest.mark.asyncio
async def test_the_unified_app_opens_with_any_one_read_scope_and_refuses_the_rest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / app_meta.UNIFIED_APP_FILE).write_text(UNIFIED_HTML, encoding="utf-8")
    monkeypatch.setattr("sidekick.mcp.app_meta.APPS_DIR", tmp_path)
    container = create_container(make_settings())

    # There is no per-app resource: the one app opens with any one read scope, and the tools
    # that fill it check their own scopes.
    for scope in APP_READ_SCOPES:
        reader = Actor(new_uuid7(), frozenset({scope}))
        server = create_mcp_server(
            container, actor_provider=lambda reader=reader: reader, enable_auth=False
        )
        async with Client(server) as client:
            html = (await client.read_resource(SIDEKICK_APP_URI))[0].text
        assert "UNIFIED" in html, scope

    # No read scope, or only write scopes, is refused.
    for scopes in (frozenset[str](), frozenset({"tasks:write", "journal:write"})):
        stranger = Actor(new_uuid7(), scopes)
        server = create_mcp_server(
            container, actor_provider=lambda stranger=stranger: stranger, enable_auth=False
        )
        async with Client(server) as client:
            with pytest.raises(MCPError, match="Error reading resource"):
                await client.read_resource(SIDEKICK_APP_URI)


@pytest.mark.asyncio
async def test_every_app_tool_names_the_one_sidekick_app_resource() -> None:
    server = create_mcp_server(create_container(make_settings()), enable_auth=False)
    named = {
        (tool.meta or {}).get("ui", {}).get("resourceUri") for tool in await server.list_tools()
    }
    # The host caches one app HTML for every app tool, so no tool names a per-app resource.
    assert named - {None} == {SIDEKICK_APP_URI}


@pytest.mark.asyncio
async def test_sidekick_app_resource_opens_with_one_read_scope_and_refuses_a_stranger() -> None:
    container = create_container(make_settings())
    reader = Actor(new_uuid7(), frozenset({"shopping:read"}))
    server = create_mcp_server(container, actor_provider=lambda: reader, enable_auth=False)
    async with Client(server) as client:
        resource = await client.read_resource(SIDEKICK_APP_URI)
    assert resource[0].mimeType == "text/html;profile=mcp-app"
    assert "<html" in resource[0].text

    stranger = Actor(new_uuid7(), frozenset())
    server = create_mcp_server(container, actor_provider=lambda: stranger, enable_auth=False)
    async with Client(server) as client:
        with pytest.raises(MCPError, match="Error reading resource"):
            await client.read_resource(SIDEKICK_APP_URI)
