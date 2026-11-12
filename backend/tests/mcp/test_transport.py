"""Streamable HTTP transport, bearer auth, and mounted lifespan smoke tests."""

from typing import Any

import httpx
import httpx2
import pytest
from fastapi import FastAPI
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from starlette.types import Receive, Scope, Send

from sidekick.api.app import create_app
from sidekick.shared.auth import TOKEN_SCOPES
from tests.contract_counts import curated_tool_count
from tests.db import database_factory
from tests.support.settings import make_settings


@pytest.mark.asyncio
@pytest.mark.integration
async def test_remote_streamable_http_discovers_tools_with_personal_token() -> None:
    factory = database_factory()
    app = create_app(make_settings(), factory)
    user_id = app.state.container.auth.provision_user("owner", "Owner")
    token = app.state.container.auth.create_personal_token(user_id, "transport test", TOKEN_SCOPES)

    def client_factory(**kwargs: Any) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="http://testserver",
            **kwargs,
        )

    transport = StreamableHttpTransport(
        "http://testserver/mcp/",
        headers={"Authorization": f"Bearer {token}"},
        httpx_client_factory=client_factory,
    )
    async with app.router.lifespan_context(app), Client(transport) as client:
        tools = await client.list_tools()
        projects = await client.call_tool("list_projects", {"limit": 5})
        journal = await client.call_tool(
            "list_journal_entries",
            {"from_date": "2026-07-21", "to_date": "2026-07-21"},
        )
    assert len(tools) == curated_tool_count()
    assert projects.structured_content == {"projects": [], "next_cursor": None}
    assert journal.structured_content is not None
    assert journal.structured_content["entries"] == []
    assert journal.structured_content["next_cursor"] is None
    assert journal.structured_content["owner_timezone"] == "Europe/Stockholm"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_remote_streamable_http_rejects_missing_bearer() -> None:
    factory = database_factory()
    app = create_app(make_settings(), factory)

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        response = await client.post(
            "/mcp/",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
    assert response.status_code == 401


MODERN_PROTOCOL_VERSION = "2026-07-28"
# Older clients still negotiate one of these with an `initialize` handshake.
HANDSHAKE_PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")


def _owner_token(app: FastAPI) -> str:
    user_id = app.state.container.auth.provision_user("owner", "Owner")
    return app.state.container.auth.create_personal_token(user_id, "protocol test", TOKEN_SCOPES)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_remote_streamable_http_serves_protocol_2026_07_28_without_a_handshake() -> None:
    # The Claude app asks for 2026-07-28 first. A 400 here costs it a retry at an older version,
    # one extra round trip per connection over the tunnel.
    app = create_app(make_settings(), database_factory())
    token = _owner_token(app)
    versions: list[str] = []
    methods: list[str] = []

    async def observed(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = dict(scope["headers"])
            versions.append(headers.get(b"mcp-protocol-version", b"").decode())
            methods.append(headers.get(b"mcp-method", b"").decode())
        await app(scope, receive, send)

    def client_factory(**kwargs: Any) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=observed),
            base_url="http://testserver",
            **kwargs,
        )

    transport = StreamableHttpTransport(
        "http://testserver/mcp/",
        headers={"Authorization": f"Bearer {token}"},
        httpx_client_factory=client_factory,
    )
    async with app.router.lifespan_context(app), Client(transport, mode="auto") as client:
        tools = await client.list_tools()
        projects = await client.call_tool("list_projects", {"limit": 5})

    assert len(tools) == curated_tool_count()
    assert projects.structured_content == {"projects": [], "next_cursor": None}
    assert set(versions) == {MODERN_PROTOCOL_VERSION}
    assert "initialize" not in methods


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("version", HANDSHAKE_PROTOCOL_VERSIONS)
async def test_remote_streamable_http_still_accepts_handshake_protocol_versions(
    version: str,
) -> None:
    app = create_app(make_settings(), database_factory())
    token = _owner_token(app)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": version,
    }
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": version,
            "capabilities": {},
            "clientInfo": {"name": "protocol-test", "version": "1"},
        },
    }

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        response = await client.post("/mcp/", json=initialize, headers=headers)

    assert response.status_code == 200
    assert f'"protocolVersion":"{version}"' in response.text
