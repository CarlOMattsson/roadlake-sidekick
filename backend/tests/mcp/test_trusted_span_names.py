"""The span allowlist is filled from FastMCP's component store; a changed store stops startup."""

import pytest
from fastmcp import FastMCP

from sidekick.api.app import create_container
from sidekick.mcp.server import (
    _local_components,  # pyright: ignore[reportPrivateUsage]
    create_mcp_server,
)
from tests.support.settings import make_settings


@pytest.mark.asyncio
async def test_the_component_store_holds_every_tool_the_public_listing_shows() -> None:
    server = create_mcp_server(create_container(make_settings()), enable_auth=False)

    listed = {tool.name for tool in await server.list_tools()}

    assert len(listed) > 50
    # The private store and the public listing must agree, so a renamed store is not silent.
    stored = {getattr(item, "name", None) for item in _local_components(server)}
    assert listed <= stored


def test_a_component_store_that_changed_shape_raises_instead_of_leaving_the_allowlist_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = FastMCP("store-probe")
    monkeypatch.setattr(server.local_provider, "_components", [])

    with pytest.raises(RuntimeError, match="component store"):
        _local_components(server)


def test_a_server_without_a_local_provider_raises() -> None:
    class Changed:
        pass

    with pytest.raises(RuntimeError, match="component store"):
        _local_components(Changed())  # pyright: ignore[reportArgumentType]
