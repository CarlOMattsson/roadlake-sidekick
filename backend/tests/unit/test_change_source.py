"""The change source: set by the transport, read by the audit writer, never by a use case."""

import asyncio
from typing import Any

import pytest
from starlette.types import Receive, Scope, Send

from sidekick.api.change_source import OwnerAppChangeSource
from sidekick.mcp.change_source import source_of_tool
from sidekick.shared.change_source import change_source, current_change_source


def test_no_source_is_set_outside_a_request() -> None:
    assert current_change_source() is None


def test_the_source_holds_inside_the_block_and_is_restored_after_an_error() -> None:
    with change_source("claude"):
        assert current_change_source() == "claude"
        with change_source("you"):
            assert current_change_source() == "you"
        assert current_change_source() == "claude"
    with pytest.raises(RuntimeError), change_source("you"):
        raise RuntimeError("boom")
    assert current_change_source() is None


@pytest.mark.parametrize(
    ("meta", "expected"),
    [
        ({"ui": {"visibility": ["app"]}}, "you"),
        ({"ui": {"resourceUri": "ui://x"}}, "claude"),
        ({"ui": {"visibility": ["model", "app"]}}, "claude"),
        ({"ui": "not a mapping"}, "claude"),
        ({}, "claude"),
        (None, "claude"),
    ],
)
def test_only_an_app_only_tool_is_the_owners(meta: dict[str, Any] | None, expected: str) -> None:
    assert source_of_tool(meta) == expected


def test_an_http_request_is_the_owners_and_a_non_http_scope_is_left_alone() -> None:
    seen: list[str | None] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(current_change_source())

    async def never(*_: Any) -> Any:
        raise AssertionError("not used")

    wrapped = OwnerAppChangeSource(app)
    asyncio.run(wrapped({"type": "http"}, never, never))
    asyncio.run(wrapped({"type": "lifespan"}, never, never))
    assert seen == ["you", None]
    assert current_change_source() is None
