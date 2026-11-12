"""`python -m sidekick.mcp.stdio`: the curated server over stdio, for Claude Desktop.

The module is spawned as a real child process and spoken to with FastMCP's stdio client. A child
ends when the client closes its stdin; nothing here signals a process by pid.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from uuid import uuid4

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from fastmcp.exceptions import ToolError
from mcp.shared.exceptions import MCPError
from sqlalchemy.engine import make_url

from sidekick.api.app import create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.mcp.sidekick_app import SIDEKICK_APP_URI
from tests.db import DATABASE_URL, database_factory
from tests.support.mcp_stdio import (
    ALL_ROOMS,
    OWNER_VARIABLE,
    _environment,
    _run,
)
from tests.support.settings import make_settings


def _transport(environment: Mapping[str, str], cwd: Path) -> StdioTransport:
    return StdioTransport(
        sys.executable, ["-m", "sidekick.mcp.stdio"], env=dict(environment), cwd=str(cwd)
    )


async def _http_tool_names(rooms: str) -> frozenset[str]:
    """What the HTTP surface lists for the same rooms, built in this process."""

    settings = make_settings().model_copy(update={"enabled_rooms": rooms})
    server = create_mcp_server(create_container(settings), enable_auth=False)
    return frozenset(tool.name for tool in await server.list_tools())


def test_a_missing_owner_stops_the_process_with_a_clear_message(tmp_path: Path) -> None:
    result = _run(_environment(None), tmp_path)

    assert result.returncode != 0
    assert f"{OWNER_VARIABLE} is not set" in result.stderr
    assert result.stdout == ""


def test_an_owner_that_is_not_a_uuid_stops_the_process_without_echoing_it(tmp_path: Path) -> None:
    result = _run(_environment("not-a-uuid-secret-looking-value"), tmp_path)

    assert result.returncode != 0
    assert f"{OWNER_VARIABLE} must be a user UUID" in result.stderr
    assert "not-a-uuid-secret-looking-value" not in result.stderr
    assert result.stdout == ""


def test_an_env_file_that_does_not_exist_stops_the_process(tmp_path: Path) -> None:
    result = _run(_environment(None), tmp_path, "--env-file", str(tmp_path / "missing.env"))

    assert result.returncode != 0
    assert "--env-file" in result.stderr
    assert result.stdout == ""


def test_the_env_file_alone_configures_the_process(tmp_path: Path) -> None:
    """Every setting comes from the file (the cwd has no .env): the owner check passes and the
    database that refuses the login is what stops it.

    The target is the suite's own test database with a wrong password, never an unreachable
    address: `_run` validates the file's URL like any test URL, so nothing outside the test pool
    (and no port the guard does not allow) can be dialed from a child process.
    """

    environment = {
        key: value for key, value in _environment(None).items() if not key.startswith("SIDEKICK_")
    }
    settings = _environment(uuid4())
    settings["SIDEKICK_DATABASE_URL"] = (
        make_url(DATABASE_URL).set(password="wrong-password").render_as_string(hide_password=False)
    )
    env_file = tmp_path / "sidekick.env"
    env_file.write_text(
        "".join(f"{k}={v}\n" for k, v in settings.items() if k.startswith("SIDEKICK_")),
        encoding="utf-8",
    )

    result = _run(environment, tmp_path, "--env-file", str(env_file))

    assert result.returncode != 0
    assert "database could not be reached" in result.stderr
    assert result.stdout == ""


def test_logging_writes_nothing_to_stdout(tmp_path: Path) -> None:
    """stdout is the protocol: Sidekick's logger, a library logger and the root use stderr."""

    program = (
        "import logging\n"
        "from sidekick.shared.observability import configure_observability\n"
        "configure_observability('test')\n"
        "logging.getLogger('sidekick.mcp.stdio').info('sidekick-record')\n"
        "logging.getLogger('fastmcp.test').warning('library-record')\n"
        "logging.getLogger().error('root-record')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        env=_environment(None),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert "sidekick-record" in result.stderr
    # Library and root records are written to stderr too, as a fixed label and never their text.
    assert "WARNING fastmcp.test third_party_log" in result.stderr
    assert "ERROR root third_party_log" in result.stderr
    assert "library-record" not in result.stderr
    assert "root-record" not in result.stderr


@pytest.mark.integration
def test_an_owner_who_is_not_a_user_stops_the_process(tmp_path: Path) -> None:
    database_factory()

    result = _run(_environment(uuid4()), tmp_path)

    assert result.returncode != 0
    assert f"{OWNER_VARIABLE} does not name an active Sidekick user" in result.stderr
    assert result.stdout == ""


@pytest.mark.integration
@pytest.mark.parametrize("rooms", [ALL_ROOMS, "work", "work,shopping"])
@pytest.mark.asyncio
async def test_the_stdio_tools_are_the_http_tools_for_the_same_rooms(
    tmp_path: Path, rooms: str
) -> None:
    factory = database_factory()
    owner_id = create_container(make_settings(), factory).auth.provision_user("owner", "Owner")

    # "legacy" is the `initialize` handshake that Claude Desktop sends.
    async with Client(_transport(_environment(owner_id, rooms), tmp_path), mode="legacy") as client:
        assert client.initialize_result is not None
        assert client.initialize_result.serverInfo.name == make_settings().mcp_server_name
        tools = await client.list_tools()

    names = frozenset(tool.name for tool in tools)
    assert names == await _http_tool_names(rooms)
    assert len(names) > 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_the_app_resources_are_served_and_a_tool_acts_as_the_owner(tmp_path: Path) -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    owner_id = container.auth.provision_user("owner", "Owner")

    async with Client(_transport(_environment(owner_id), tmp_path)) as client:
        uris = {str(resource.uri) for resource in await client.list_resources()}
        html = (await client.read_resource(SIDEKICK_APP_URI))[0]
        listed = await client.call_tool("list_projects", {})

    assert SIDEKICK_APP_URI in uris
    assert html.mimeType == "text/html;profile=mcp-app"
    assert listed.is_error is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_room_that_is_off_has_no_tools_and_cannot_be_called(tmp_path: Path) -> None:
    factory = database_factory()
    owner_id = create_container(make_settings(), factory).auth.provision_user("owner", "Owner")

    async with Client(_transport(_environment(owner_id, "work"), tmp_path)) as client:
        with pytest.raises(ToolError):
            await client.call_tool("list_shopping_lists", {})


@pytest.mark.integration
@pytest.mark.asyncio
async def test_disabling_the_owner_stops_a_session_that_is_already_running(
    tmp_path: Path,
) -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    owner_id = container.auth.provision_user("owner", "Owner")

    async with Client(_transport(_environment(owner_id), tmp_path)) as client:
        assert (await client.call_tool("list_projects", {})).is_error is False
        assert container.auth.disable_user(owner_id)

        with pytest.raises(MCPError, match="owner is not active"):
            await client.call_tool("list_projects", {})
