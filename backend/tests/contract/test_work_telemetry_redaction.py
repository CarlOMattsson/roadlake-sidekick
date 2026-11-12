"""Work content never crosses telemetry, audit, or safe-error boundaries."""

import pytest
from fastmcp import Client
from sqlalchemy import select

from sidekick.api.app import create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.persistence.models import AuditEventRow
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings
from tests.support.telemetry import CaptureTelemetry

SENTINEL = "WORK_PRIVATE_SENTINEL"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_work_interfaces_keep_content_out_of_telemetry_and_audit() -> None:
    telemetry = CaptureTelemetry()
    factory = database_factory()
    container = create_container(make_settings(), factory, telemetry)
    owner_id = container.auth.provision_user("work_redaction", "Work")
    actor = Actor(
        owner_id,
        frozenset({"projects:read", "projects:write", "tasks:read", "tasks:write"}),
    )
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    async with Client(server) as client:
        domain = await client.call_tool(
            "create_domain",
            {"name": SENTINEL, "description": SENTINEL, "idempotency_key": "redact-domain"},
        )
        assert domain.structured_content is not None
        domain_id = domain.structured_content["domain"]["id"]
        project = await client.call_tool(
            "create_project",
            {
                "domain_id": domain_id,
                "title": SENTINEL,
                "description": SENTINEL,
                "idempotency_key": "redact-project",
            },
        )
        assert project.structured_content is not None
        await client.call_tool("get_work_hierarchy", {"limit": 100})
        await client.call_tool("list_domains", {"limit": 10})
        await client.call_tool("list_projects", {"limit": 10})

    with factory() as session:
        audit = session.scalars(select(AuditEventRow)).all()
        assert audit

    serialized = str(telemetry.records) + str(audit)
    assert SENTINEL not in serialized
    assert "redact-project" not in serialized
    assert "redact-domain" not in serialized
    assert project.structured_content["project"]["title"] == SENTINEL
