"""What every curated MCP tool registrar needs: the container, the caller and the span wrapper."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sidekick.shared.types import Actor

if TYPE_CHECKING:
    from sidekick.composition import Container

Instrument = Callable[[str], Callable[[Callable[..., Any]], Callable[..., Any]]]


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Passed to each module-level `_register_<tool>(mcp, ctx)` function of a tool module."""

    container: Container
    actor_provider: Callable[[], Actor]
    instrument: Instrument
