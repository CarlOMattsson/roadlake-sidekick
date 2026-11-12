"""One MCP server per container, with the acting Actor switched between a test's cases.

Building `create_mcp_server` registers the whole tool surface (about 2 s), so a test that
needs several scope variants builds the server once and calls `ActorSwitch.use(actor)` before
each case instead. Cases run one after another, so the switch is never read by two calls at once.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastmcp import Client, FastMCP

from sidekick.api.app import Container
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.types import Actor


class ActorSwitch:
    """The Actor an MCP server acts as. Pass the instance itself as `actor_provider`."""

    def __init__(self, actor: Actor) -> None:
        self._actor = actor

    def __call__(self) -> Actor:
        return self._actor

    def use(self, actor: Actor) -> None:
        self._actor = actor


@dataclass(frozen=True, slots=True)
class SwitchableServer:
    switch: ActorSwitch
    server: FastMCP

    @classmethod
    def build(cls, container: Container, actor: Actor) -> SwitchableServer:
        switch = ActorSwitch(actor)
        server = create_mcp_server(container, actor_provider=switch, enable_auth=False)
        return cls(switch, server)

    def client(self, actor: Actor) -> Client:
        """Client whose calls act as `actor`. Enter it before any other client is in use."""
        self.switch.use(actor)
        return Client(self.server)
