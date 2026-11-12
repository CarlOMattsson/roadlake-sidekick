"""The tool-parsing cache must not change anything Claude sees, and must fail safe."""

import json
from collections.abc import Callable
from functools import wraps
from typing import Annotated, Any

import pytest
from fastmcp.tools.function_parsing import ParsedFunction
from pydantic import Field

from sidekick.api.app import create_container
from sidekick.mcp import schema_cache
from sidekick.mcp.schema_cache import (
    clear_schema_cache,
    install_schema_cache,
    schema_cache_disabled,
    schema_cache_stats,
)
from sidekick.mcp.server import create_mcp_server
from tests.support.settings import make_settings

Count = Annotated[int, Field(ge=1)]


async def _tool_surface() -> dict[str, str]:
    """Serialise every tool as Claude receives it: name, description, schemas, annotations, meta."""

    server = create_mcp_server(create_container(make_settings()), enable_auth=False)
    surface: dict[str, str] = {}
    for tool in await server.list_tools():
        wire = tool.to_mcp_tool().model_dump(mode="json", by_alias=True)
        surface[tool.name] = json.dumps(wire, ensure_ascii=False)
    return surface


@pytest.mark.asyncio
async def test_cached_builds_are_byte_identical_to_an_uncached_reference() -> None:
    install_schema_cache()
    with schema_cache_disabled():
        reference = await _tool_surface()

    clear_schema_cache()
    first = await _tool_surface()
    _, misses_after_first, _ = schema_cache_stats()
    second = await _tool_surface()
    hits, misses, entries = schema_cache_stats()

    assert len(reference) > 50
    assert first == reference
    assert second == reference
    # The second build parsed nothing new: every tool came from the cache.
    assert misses == misses_after_first
    assert hits >= len(reference)
    assert entries == misses


@pytest.mark.asyncio
async def test_a_tool_schema_is_a_private_copy_per_build() -> None:
    install_schema_cache()
    clear_schema_cache()
    container = create_container(make_settings())
    first = await create_mcp_server(container, enable_auth=False).list_tools()
    pristine = json.dumps([tool.parameters for tool in first], sort_keys=True)
    for tool in first:
        tool.parameters["properties"]["poisoned"] = {"type": "string"}
        if tool.output_schema is not None:
            tool.output_schema["poisoned"] = True

    second = await create_mcp_server(container, enable_auth=False).list_tools()

    assert json.dumps([tool.parameters for tool in second], sort_keys=True) == pristine
    assert all("poisoned" not in (tool.output_schema or {}) for tool in second), (
        "output schema leaked between builds"
    )


def _parse(make_fn: Callable[[str], Callable[..., Any]], marker: str) -> ParsedFunction:
    return ParsedFunction.from_function(make_fn(marker))


def test_closures_share_a_parse_only_when_every_input_matches() -> None:
    install_schema_cache()
    clear_schema_cache()

    def make(label: str) -> Callable[..., Any]:
        def tool(count: Count = 3) -> Any:
            """Return a number."""
            return label, count

        return tool

    one = _parse(make, "one")
    two = _parse(make, "two")

    assert two.fn is not one.fn
    assert two.input_schema == one.input_schema
    assert two.input_schema is not one.input_schema
    assert schema_cache_stats()[:2] == (1, 1)


def test_default_values_are_part_of_the_key() -> None:
    install_schema_cache()
    clear_schema_cache()

    def make(default: int) -> Callable[..., Any]:
        def tool(count: int = default) -> Any:
            """Return a number."""
            return count

        return tool

    three = ParsedFunction.from_function(make(3))
    four = ParsedFunction.from_function(make(4))

    assert three.input_schema["properties"]["count"]["default"] == 3
    assert four.input_schema["properties"]["count"]["default"] == 4
    assert schema_cache_stats()[:2] == (0, 2)


def test_functions_with_an_explicit_signature_are_never_cached() -> None:
    install_schema_cache()
    clear_schema_cache()

    def make(default: int) -> Callable[..., Any]:
        @wraps(lambda: None)
        def tool(**kwargs: Any) -> Any:
            """Return a number."""
            return kwargs

        import inspect

        tool.__signature__ = inspect.Signature(  # pyright: ignore[reportFunctionMemberAccess]
            [inspect.Parameter("count", inspect.Parameter.KEYWORD_ONLY, default=default)]
        )
        tool.__name__ = "tool"
        return tool

    # A `__signature__` could change what FastMCP sees, so each parse must run FastMCP's own code.
    first = ParsedFunction.from_function(make(1), validate=False)
    second = ParsedFunction.from_function(make(2), validate=False)

    assert first.input_schema["properties"]["count"]["default"] == 1
    assert second.input_schema["properties"]["count"]["default"] == 2
    assert schema_cache_stats() == (0, 0, 0)


def test_disabled_cache_parses_with_fastmcp_directly() -> None:
    install_schema_cache()
    clear_schema_cache()

    def tool(count: int = 1) -> Any:
        """Return a number."""
        return count

    with schema_cache_disabled():
        ParsedFunction.from_function(tool)
        ParsedFunction.from_function(tool)

    assert schema_cache_stats() == (0, 0, 0)


def test_an_unreviewed_fastmcp_version_is_not_patched(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(schema_cache.metadata, "version", lambda _name: "99.0.0")

    reason = schema_cache._reviewed_shape()  # pyright: ignore[reportPrivateUsage]

    assert reason is not None and "99.0.0" in reason


def test_the_installed_fastmcp_is_the_reviewed_one() -> None:
    assert schema_cache._reviewed_shape() is None  # pyright: ignore[reportPrivateUsage]
    assert install_schema_cache() is True
