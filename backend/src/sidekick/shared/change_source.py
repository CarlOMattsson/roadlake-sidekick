"""Who is making the change in progress: the owner in the app, or the model through a tool.

The transport sets the source once per request or tool call (the HTTP middleware says `you`, the
MCP middleware says `you` for an app-only tool and `claude` for a model tool), and the audit writer
reads it when it appends an event. Use cases never pass it around. Outside a request, for example in
a background job, no source is set and the event records none (stored as NULL, read as unknown).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Literal

ChangeSource = Literal["you", "claude"]

_SOURCE: ContextVar[ChangeSource | None] = ContextVar("sidekick_change_source", default=None)


def current_change_source() -> ChangeSource | None:
    """The source of the change being made now, or None when no transport has set one."""

    return _SOURCE.get()


@contextmanager
def change_source(source: ChangeSource) -> Iterator[None]:
    """Mark every audit event appended inside the block (and its worker threads) with `source`."""

    token = _SOURCE.set(source)
    try:
        yield
    finally:
        _SOURCE.reset(token)
