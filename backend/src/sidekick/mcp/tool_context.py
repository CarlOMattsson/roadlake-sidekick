"""What every curated MCP tool registrar needs: the container, the caller and the span wrapper."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, ParamSpec, Protocol, TypeVar

from sidekick.shared.types import Actor

if TYPE_CHECKING:
    from sidekick.composition import Container

P = ParamSpec("P")
R = TypeVar("R")


class Instrument(Protocol):
    """Wraps a tool in its telemetry span: `@ctx.instrument("tool_name")` keeps the signature."""

    def __call__(self, tool_name: str, /) -> Callable[[Callable[P, R]], Callable[P, R]]: ...


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Passed to each module-level `_register_<tool>(mcp, ctx)` function of a tool module."""

    container: Container
    actor_provider: Callable[[], Actor]
    instrument: Instrument
