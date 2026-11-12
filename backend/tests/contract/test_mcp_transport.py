"""The public MCP transport is a streamable-HTTP mount, separate from the REST routers."""

import re
from pathlib import Path

import pytest

from sidekick.mcp import MCP_MOUNT_PATH

ROOT = Path(__file__).parents[3]


@pytest.mark.policy
def test_mcp_is_mounted_as_streamable_http_at_mcp() -> None:
    source = (ROOT / "backend/src/sidekick/api/app.py").read_text(encoding="utf-8")
    public_call = re.search(r"mcp_app = mcp\.http_app\((?P<args>[^)]*)\)", source)
    assert public_call is not None
    args = public_call["args"]
    assert 'path="/"' in args
    assert 'transport="streamable-http"' in args
    assert "stateless_http=True" in args
    assert "app.mount(MCP_MOUNT_PATH, McpTransportLogging(mcp_app))" in source
    assert MCP_MOUNT_PATH == "/mcp"
    # There is no REST chat router; MCP is the only chat surface.
    assert "chat.router" not in source
