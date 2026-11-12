"""The public MCP server name is configurable; the default stays the product name."""

import pytest

from sidekick.shared.config import Settings


def test_the_default_mcp_server_name_is_the_product_name() -> None:
    assert Settings().mcp_server_name == "Sidekick"


def test_the_mcp_server_name_is_read_from_its_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIDEKICK_MCP_SERVER_NAME", "Sidekick test")
    assert Settings().mcp_server_name == "Sidekick test"
