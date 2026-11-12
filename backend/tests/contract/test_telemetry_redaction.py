"""Personal content and credentials are excluded by allowlist."""

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client

from sidekick.api.app import create_app
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.observability import safe_log_fields
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings
from tests.support.telemetry import (
    CaptureTelemetry,
)


def test_log_allowlist_drops_content_and_credentials() -> None:
    sensitive = {
        "correlation_id": "safe-id",
        "http_method": "POST",
        "http_status": 201,
        "project_title": "Secret project",
        "task_text": "Private task",
        "authorization": "Bearer secret-token",
        "cookie": "session=secret",
        "sql_parameters": "private-value",
        "prompt": "private prompt",
    }
    safe = safe_log_fields(sensitive)
    assert safe == {"correlation_id": "safe-id", "http_method": "POST", "http_status": 201}
    serialized = str(safe)
    assert "Secret" not in serialized
    assert "Private" not in serialized
    assert "Bearer" not in serialized


@pytest.mark.asyncio
@pytest.mark.integration
async def test_http_mcp_and_sql_use_the_same_content_free_telemetry_port() -> None:
    telemetry = CaptureTelemetry()
    factory = database_factory()
    app = create_app(make_settings(), factory, telemetry)
    user_id = app.state.container.auth.provision_user("owner", "Owner")
    with TestClient(app) as http:
        assert http.get("/health/live").status_code == 200
    actor = Actor(user_id, frozenset({"shopping:read", "shopping:write"}))
    mcp = create_mcp_server(app.state.container, actor_provider=lambda: actor, enable_auth=False)
    async with Client(mcp) as client:
        await client.call_tool(
            "create_shopping_list",
            {"name": "Never capture this title", "idempotency_key": "telemetry-project"},
        )
        await client.call_tool("list_shopping_lists", {"limit": 5})
    names = {name for name, _attributes in telemetry.records}
    assert {"http.request", "db.transaction", "mcp.tool"} <= names
    serialized = str(telemetry.records)
    assert "Never capture this title" not in serialized
    assert "correct horse" not in serialized
    assert "telemetry-project" not in serialized
