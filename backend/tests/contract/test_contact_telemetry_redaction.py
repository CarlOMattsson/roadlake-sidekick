"""Telemetry and audit exclude seeded Contact content."""

import pytest
from fastmcp import Client
from sqlalchemy import select

from sidekick.api.app import create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.persistence.models import AuditEventRow
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.fakes import (
    SENSITIVE_ALIAS,
    SENSITIVE_EMAIL,
    SENSITIVE_NAME,
    SENSITIVE_NOTE,
    SENSITIVE_PHONE,
)
from tests.support.settings import make_settings
from tests.support.telemetry import CaptureTelemetry


@pytest.mark.asyncio
@pytest.mark.integration
async def test_telemetry_redaction_guarantees() -> None:
    telemetry = CaptureTelemetry()
    factory = database_factory()
    container = create_container(make_settings(), factory, telemetry)
    owner_id = container.auth.provision_user("telemetry-owner", "Owner")
    actor = Actor(owner_id, frozenset({"contacts:read", "contacts:write"}))
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    async with Client(server) as client:
        created = await client.call_tool(
            "create_contact",
            {
                "display_name": SENSITIVE_NAME,
                "aliases": [SENSITIVE_ALIAS],
                "email": SENSITIVE_EMAIL,
                "phone": SENSITIVE_PHONE,
                "context_note": SENSITIVE_NOTE,
                "idempotency_key": "telemetry-contact",
            },
        )
        assert not created.is_error
        await client.call_tool("list_contacts", {"q": SENSITIVE_NAME})
    with factory() as session:
        audit = session.scalars(select(AuditEventRow)).all()
    serialized = str(telemetry.records) + str(audit)
    for value in (
        SENSITIVE_NAME,
        SENSITIVE_ALIAS,
        SENSITIVE_EMAIL,
        SENSITIVE_PHONE,
        SENSITIVE_NOTE,
        "telemetry-contact",
    ):
        assert value not in serialized
