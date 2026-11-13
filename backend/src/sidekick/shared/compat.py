"""The one place Sidekick reaches into private parts of third-party libraries.

Every access to an underscore name of a library (an attribute, a private class, a private
module) is a contract nobody promised us, so a library upgrade has to re-check it by hand. They
are collected here, one function per access, each with the reason and the library version it was
reviewed on. After an upgrade of `fastmcp`, `mcp`, `opentelemetry-sdk`, `sqlalchemy` or Python,
this file is the checklist; `tests/policy/test_private_library_access.py` fails when such an access
shows up anywhere else.

Two modules keep private access of their own because it is part of their reviewed design and
each carries its own startup probe: `shared/observability/span_allowlist.py` and `setup.py`
rewrite the private fields of `ReadableSpan` (probed by `sdk_internals.span_rewrite_problem`), and
`mcp/oauth.py` overrides `FileTreeStore._setup_collection` (probed by `_require_file_tree_hooks`).

Nothing here raises on its own at import time: callers decide what a missing internal means
(refuse to start, log and skip, or fail closed).
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from opentelemetry.sdk.trace import TracerProvider
    from sqlalchemy.orm import Mapper

# --- fastmcp 4.1.6 / mcp 2.3.0 ---------------------------------------------------------------


def low_level_server(server: FastMCP) -> Any | None:
    """The MCP SDK server that FastMCP wraps (`FastMCP._mcp_server`), or None if it is gone.

    Why: the SDK reads `get_tool_input_schema` from it on every tool call and FastMCP does not
    set it. fastmcp 4.1.6, mcp 2.3.0.
    """

    return getattr(server, "_mcp_server", None)


def set_tool_input_schema_lookup(
    server: FastMCP, lookup: Callable[[str], Mapping[str, object] | None]
) -> None:
    """Install the SDK's per-call input-schema lookup on `server`.

    Why: avoids running a full `tools/list` for every `tools/call`. fastmcp 4.1.6, mcp 2.3.0.
    """

    server._mcp_server.get_tool_input_schema = lookup  # pyright: ignore[reportPrivateUsage]


def local_provider_components(server: FastMCP) -> dict[str, object] | None:
    """The component store of the server's local provider (`_components`), or None if not a dict.

    Why: the public listings are coroutines and the span allowlist is filled while the server is
    built. fastmcp 4.1.6.
    """

    store = getattr(getattr(server, "local_provider", None), "_components", None)
    return cast("dict[str, object]", store) if isinstance(store, dict) else None


# --- opentelemetry-sdk 1.45.2 ----------------------------------------------------------------


def active_span_processor(provider: TracerProvider) -> Any:
    """The processor chain the provider hands to its tracers (`_active_span_processor`), or None.

    Why: it is the only object that sees every ended span whatever processors were added, so the
    span redaction is installed in front of it. opentelemetry-sdk 1.45.2.
    """

    return getattr(provider, "_active_span_processor", None)


def replace_active_span_processor(provider: TracerProvider, chain: Any) -> None:
    """Give the provider a fresh processor chain (used when span export must stop).

    Why: tracers obtained later and processors added later must not reach the old chain.
    opentelemetry-sdk 1.45.2.
    """

    provider._active_span_processor = chain  # pyright: ignore[reportPrivateUsage]


# --- sqlalchemy (pinned in pyproject.toml) ---------------------------------------------------


def set_mapper_sort_key(mapper: Mapper[Any], key: str) -> None:
    """Set the key the unit of work orders mappers by (`Mapper._sort_key`).

    Why: makes mappers without a `relationship()` flush in foreign-key order.
    `tests/integration/test_flush_order.py` fails if SQLAlchemy stops honouring it.
    """

    cast("Any", mapper)._sort_key = key


# --- argparse (Python 3.13) ------------------------------------------------------------------


def parser_actions(parser: argparse.ArgumentParser) -> list[argparse.Action]:
    """Every action of a parser (`ArgumentParser._actions`). Why: the CLI reference is generated."""

    return list(parser._actions)


def parser_exclusive_groups(parser: argparse.ArgumentParser) -> list[list[argparse.Action]]:
    """The actions of each mutually exclusive group (`_mutually_exclusive_groups`)."""

    return [list(group._group_actions) for group in parser._mutually_exclusive_groups]


def is_subparsers_action(action: argparse.Action) -> bool:
    """Whether the action is the one `add_subparsers` creates (`argparse._SubParsersAction`)."""

    return isinstance(action, argparse._SubParsersAction)  # pyright: ignore[reportPrivateUsage]


def is_help_action(action: argparse.Action) -> bool:
    """Whether the action is the automatic `-h` one (`argparse._HelpAction`)."""

    return isinstance(action, argparse._HelpAction)  # pyright: ignore[reportPrivateUsage]


def is_append_action(action: argparse.Action) -> bool:
    """Whether the action is `action="append"` (`argparse._AppendAction`)."""

    return isinstance(action, argparse._AppendAction)  # pyright: ignore[reportPrivateUsage]


def subparser_choice_actions(subparsers: Any) -> list[Any]:
    """The pseudo-actions holding each sub-command's help (`_SubParsersAction._choices_actions`)."""

    return list(subparsers._choices_actions)
