"""Sidekick's MCP server over stdio, for a client that starts it as a local process.

Claude Desktop launches this module from ``claude_desktop_config.json`` (``command`` + ``args``)
and speaks MCP over its stdin and stdout::

    python -m sidekick.mcp.stdio [--env-file PATH]

It builds the same curated server as the public HTTP endpoint (``create_mcp_server``): the same
tools, the same ``ui://`` app resources, the same use cases, the same sanitised errors, and the
rooms of ``SIDEKICK_ENABLED_ROOMS``. Only the transport and the identity differ.

Trust model: nothing on the wire proves who is calling, because the process is started by the
local operating-system user. The caller is therefore the owner named in
``SIDEKICK_MCP_STDIO_OWNER_ID`` (a Sidekick user UUID), holding every scope the MCP surface can ever
carry (``MCP_SCOPES``) minus the scopes of rooms that are switched off. Whoever can start this
process already holds the database credentials it reads from its environment, so it is trusted
exactly that far and no further. The process refuses to start when the owner is not set, is not a
user, or has been disabled, and it checks the owner again on every request, so disabling the
account stops a session that is already running.

stdout belongs to the protocol. Sidekick's logs go to stderr (``configure_observability``), the
startup banner is off, and nothing is printed to stdout while the server is built. Settings come
from the process environment and ``.env``, which is looked up relative to the working directory:
a desktop client rarely starts a process in the repository, so pass ``--env-file`` or put the
variables in the client's ``env`` block.
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from uuid import UUID

from anyio import to_thread
from fastmcp import FastMCP
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from mcp.shared.exceptions import MCPError
from mcp.types import Request
from pydantic import ValidationError

from sidekick.composition import Container, create_container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.auth import MCP_SCOPES
from sidekick.shared.config import Settings
from sidekick.shared.errors.core import InternalFaultError
from sidekick.shared.observability import safe_log_fields
from sidekick.shared.types import Actor

LOGGER = logging.getLogger("sidekick.mcp.stdio")

OWNER_VARIABLE = "SIDEKICK_MCP_STDIO_OWNER_ID"
# A JSON-RPC server error: the request was understood and refused because the owner is not active.
_OWNER_INACTIVE_CODE = -32001

_REFUSED_OWNER_MISSING = "owner_missing"
_REFUSED_OWNER_UNKNOWN = "owner_unknown"
_REFUSED_UNAVAILABLE = "database_unavailable"
_REFUSED_CONFIGURATION = "configuration_invalid"


class StdioStartupError(InternalFaultError):
    """The process must not start. The message is safe to print: it never carries a value."""

    def __init__(self, startup_reason: str, message: str) -> None:
        super().__init__(message)
        self.startup_reason = startup_reason


class OwnerStillActive(Middleware):
    """Refuse every request once the owner's account is gone or disabled."""

    def __init__(self, container: Container, owner_id: UUID) -> None:
        self._container = container
        self._owner_id = owner_id

    async def on_request(
        self,
        context: MiddlewareContext[Request[Any, Any]],
        call_next: CallNext[Request[Any, Any], Any],
    ) -> Any:
        try:
            active = await to_thread.run_sync(self._container.auth.is_user_active, self._owner_id)
        except Exception:
            self._container.telemetry.count("sidekick.mcp.stdio", {"outcome": "unavailable"})
            raise MCPError(-32603, "Sidekick is unavailable") from None
        if not active:
            self._container.telemetry.count("sidekick.mcp.stdio", {"outcome": "owner_inactive"})
            raise MCPError(_OWNER_INACTIVE_CODE, "The Sidekick owner is not active")
        return await call_next(context)


def load_settings(env_file: Path | None) -> Settings:
    """The usual Settings; with ``env_file`` that file replaces ``.env`` and must exist."""

    if env_file is None:
        return Settings()  # type: ignore[call-arg]
    if not env_file.is_file():
        raise StdioStartupError(_REFUSED_CONFIGURATION, f"--env-file {env_file} is not a file")
    return Settings(_env_file=env_file)  # type: ignore[call-arg]


def resolve_owner(settings: Settings) -> UUID:
    """The configured owner, or a refusal. Settings has already checked that it is a UUID."""

    if not settings.mcp_stdio_owner_id:
        raise StdioStartupError(
            _REFUSED_OWNER_MISSING,
            f"{OWNER_VARIABLE} is not set; set it to the Sidekick user UUID this process acts as",
        )
    return UUID(settings.mcp_stdio_owner_id)


def build_stdio_server(container: Container, owner_id: UUID) -> FastMCP:
    """The curated server bound to the owner; an owner who is not an active user is refused."""

    try:
        active = container.auth.is_user_active(owner_id)
    except Exception:
        raise StdioStartupError(
            _REFUSED_UNAVAILABLE, "the Sidekick database could not be reached"
        ) from None
    if not active:
        raise StdioStartupError(
            _REFUSED_OWNER_UNKNOWN, f"{OWNER_VARIABLE} does not name an active Sidekick user"
        )
    # `create_mcp_server` takes the scopes of switched-off rooms off this actor.
    actor = Actor(owner_id, frozenset(MCP_SCOPES))
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)
    server.add_middleware(OwnerStillActive(container, owner_id))
    return server


def _refuse(error: StdioStartupError) -> int:
    LOGGER.error(
        "mcp_stdio_refused",
        extra=safe_log_fields({"outcome": "refused", "mcp_auth_mode": "stdio"})
        | {"mcp_auth_reason": error.startup_reason},
    )
    print(f"sidekick-mcp-stdio: {error}", file=sys.stderr)
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m sidekick.mcp.stdio", description="Sidekick's MCP server over stdio."
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        help="read settings from this file instead of ./.env (a relative .env follows the cwd)",
    )
    args = parser.parse_args(argv)
    # Anything a library prints while the server is built goes to stderr, never into the protocol.
    with contextlib.redirect_stdout(sys.stderr):
        try:
            settings = load_settings(args.env_file)
            owner_id = resolve_owner(settings)
            container = create_container(settings)
            server = build_stdio_server(container, owner_id)
        except ValidationError as error:
            details = "; ".join(
                f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
                for item in error.errors()
            )
            return _refuse(
                StdioStartupError(_REFUSED_CONFIGURATION, f"invalid configuration: {details}")
            )
        except StdioStartupError as error:
            return _refuse(error)
    LOGGER.info(
        "mcp_stdio_started", extra=safe_log_fields({"outcome": "ready", "mcp_auth_mode": "stdio"})
    )
    server.run("stdio", show_banner=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
