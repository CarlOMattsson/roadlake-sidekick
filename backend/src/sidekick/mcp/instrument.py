"""The telemetry wrapper every MCP tool runs inside."""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import wraps
from typing import TYPE_CHECKING, ParamSpec, TypeVar, cast

from sidekick.mcp.correlation import UNKNOWN_CORRELATION
from sidekick.mcp.results import error_result
from sidekick.shared.observability import safe_log_fields

if TYPE_CHECKING:
    from sidekick.composition import Container

LOGGER = logging.getLogger("sidekick.mcp.tool")

P = ParamSpec("P")
R = TypeVar("R")


def instrument_mcp(
    container: Container, tool_name: str
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Wrap a tool at the adapter boundary without exposing arguments to telemetry."""

    def decorator(operation: Callable[P, R]) -> Callable[P, R]:
        @wraps(operation)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            attributes = {"mcp.tool.name": tool_name}
            try:
                with container.telemetry.span("mcp.tool", attributes):
                    result_value = operation(*args, **kwargs)
            except Exception as error:
                container.telemetry.count(
                    "sidekick.mcp.tool.calls", {**attributes, "outcome": "failure"}
                )
                result = error_result(error)
                structured = result.structured_content or {}
                # The same id as the reply and the request line; the class name only, never text.
                LOGGER.info(
                    "mcp_tool_failed",
                    extra=safe_log_fields(
                        {
                            "correlation_id": structured.get("correlation_id", UNKNOWN_CORRELATION),
                            "mcp_tool_name": tool_name,
                            "mcp_error_class": type(error).__name__,
                        }
                    ),
                )
                return cast(R, result)
            container.telemetry.count(
                "sidekick.mcp.tool.calls", {**attributes, "outcome": "success"}
            )
            return result_value

        return wrapped

    return decorator
