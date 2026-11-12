"""`set_license_key` (D-081): the owner enters the instance's license key over MCP.

Owner only (the installation's only active user, holding the `license:write` scope), checked
offline, and the key is never echoed, logged or put in an error.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest
from fastmcp import Client
from sqlalchemy.orm import Session, sessionmaker

from sidekick.api.app import Container, create_container
from sidekick.mcp.rooms import TOOL_ROOM
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.auth import MCP_SCOPES
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.license_support import (
    LICENSEE,
    OWNER_PUBLIC,
    STRANGER_PRIVATE,
    assert_logs_hold_none_of,
    signature_of,
    signed_key,
    watched,
)
from tests.support.settings import make_settings

WRITER = frozenset({"license:write"})


def _container(factory: sessionmaker[Session]) -> Container:
    settings = make_settings().model_copy(update={"license_public_key": OWNER_PUBLIC})
    return create_container(settings, factory)


async def _call(container: Container, actor: Actor, key: str) -> Any:
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    async with Client(server) as client:
        return await client.call_tool("set_license_key", {"key": key}, raise_on_error=False)


def _everything(call: Any) -> str:
    """All that the model and the host would see of the answer."""
    parts = [json.dumps(call.structured_content)]
    parts += [getattr(item, "text", "") for item in call.content]
    return " ".join(parts)


def test_the_tool_belongs_to_the_work_room() -> None:
    assert TOOL_ROOM["set_license_key"] == "work"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_owner_sets_a_valid_key_and_gets_the_display_state_only() -> None:
    container = _container(database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    key = signed_key(expires=date(2027, 11, 9), kind="org", licensee="Förening X")
    call = await _call(container, Actor(owner, WRITER), key)
    assert not call.is_error
    assert call.structured_content == {
        "state": "licensed",
        "licensee": "Förening X",
        "kind": "org",
        "expires": "2027-11-09",
        "accepted": True,
    }
    assert "Förening X" in _everything(call)
    assert key not in _everything(call) and signature_of(key) not in _everything(call)
    assert container.license.view().state == "licensed"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_key_that_is_not_accepted_changes_nothing_and_says_so() -> None:
    container = _container(database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    forged = signed_key(key=STRANGER_PRIVATE)
    call = await _call(container, Actor(owner, WRITER), forged)
    assert not call.is_error
    assert call.structured_content == {"state": "unlicensed", "accepted": False}
    assert forged not in _everything(call)
    assert container.license.view().state == "unlicensed"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_token_that_only_changes_tasks_cannot_set_the_key() -> None:
    container = _container(database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    others = frozenset(scope for scope in MCP_SCOPES if scope != "license:write")
    call = await _call(container, Actor(owner, others), signed_key())
    assert call.is_error and call.structured_content["code"] == "forbidden"
    assert container.license.view().state == "unlicensed"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_read_only_token_cannot_set_the_key() -> None:
    container = _container(database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    call = await _call(container, Actor(owner, frozenset({"tasks:read"})), signed_key())
    assert call.is_error and call.structured_content["code"] == "forbidden"
    assert container.license.view().state == "unlicensed"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_nobody_but_the_only_owner_can_set_the_key() -> None:
    container = _container(database_factory())
    first = container.auth.provision_user("owner", "Owner")
    second = container.auth.provision_user("second", "Second")
    for user in (first, second):
        call = await _call(container, Actor(user, WRITER), signed_key())
        assert call.is_error and call.structured_content["code"] == "forbidden"
    assert container.license.view().state == "unlicensed"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_key_and_its_signature_never_reach_a_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    container = _container(database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    good, forged = signed_key(), signed_key(key=STRANGER_PRIVATE, licensee="Bedragare Hemlig")
    refused = signed_key(licensee="Annan Hemlig")
    with watched(caplog):
        await _call(container, Actor(owner, WRITER), good)
        await _call(container, Actor(owner, WRITER), forged)
        await _call(container, Actor(owner, WRITER), "x" * 6000)
        await _call(container, Actor(owner, frozenset({"tasks:read"})), refused)
    assert_logs_hold_none_of(
        caplog,
        good,
        forged,
        refused,
        signature_of(good),
        signature_of(forged),
        signature_of(refused),
        LICENSEE,
        "Bedragare",
        "x" * 100,
    )
