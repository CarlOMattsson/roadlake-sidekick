"""The version the MCP server announces in its handshake is the release version.

Nothing here needs a database: the server is built and a client only performs the handshake.
"""

from __future__ import annotations

import pytest
from fastmcp import Client

import sidekick
from sidekick.api.app import create_container
from sidekick.mcp.server import create_mcp_server
from tests.support.settings import make_settings


@pytest.mark.asyncio
async def test_the_server_info_version_is_the_package_version() -> None:
    server = create_mcp_server(create_container(make_settings()), enable_auth=False)
    async with Client(server) as client:
        info = client.server_info
    assert info is not None
    assert info.version == sidekick.__version__
