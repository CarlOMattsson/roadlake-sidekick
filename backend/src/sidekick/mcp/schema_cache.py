"""Memoise FastMCP's parsing of tool functions across repeated server builds.

`create_mcp_server` registers about 94 tools. For each one FastMCP builds a pydantic
`TypeAdapter` and a JSON Schema in `ParsedFunction.from_function`. FastMCP caches the adapter on
the function object, but every Sidekick tool is a closure created afresh by each `register_*`
call, so that cache never hits and the parsing is repeated on every build (about 1 s of the
roughly 1.4 s that `create_app` takes). A process builds the server once in production, but
the test suite builds it hundreds of times.

The parse result (name, description, input schema, output schema, return type) is a pure function
of the function's code, defaults, annotations, name, docstring and module namespace. It does not
depend on the closure cells, which carry only the container and actor provider. This module
therefore keys a bounded cache on exactly those inputs and reuses the result for the next closure
that has the same code. The resolved `fn` is always the new closure, and the schemas are handed
out as private copies.

The cache works by replacing one classmethod inside FastMCP, which is an internal API. It is
therefore installed only when the installed FastMCP is the exact version this was reviewed
against and the replaced method still has the expected shape. On any deviation, and for any tool
whose inputs cannot be keyed safely, behaviour is exactly FastMCP's own: no cache.
`tests/mcp/test_schema_cache.py` proves the cached and uncached tool surface byte-identical.
Only the test suite installs it (`tests/conftest.py`); production builds the server once and
keeps FastMCP's own parsing.
"""

from __future__ import annotations

import inspect
import logging
import threading
import types
from collections import OrderedDict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import metadata
from typing import Any, Final, cast

from fastmcp.tools.function_parsing import ParsedFunction

from sidekick.shared.errors.core import InternalFaultError

LOGGER = logging.getLogger("sidekick.mcp.schema_cache")

#: The FastMCP release whose `ParsedFunction.from_function` this was reviewed against.
REVIEWED_FASTMCP_VERSION: Final = "4.1.6"
_EXPECTED_PARAMETERS: Final = (
    "cls",
    "fn",
    "validate",
    "wrap_non_object_output_schema",
)
_EXPECTED_FIELDS: Final = (
    "fn",
    "name",
    "description",
    "input_schema",
    "output_schema",
    "return_type",
)
_HARMLESS_ATTRIBUTES: Final = frozenset({"__wrapped__", "__fastmcp__"})
_MAX_ENTRIES: Final = 1024
_MAX_WRAPPER_DEPTH: Final = 8


class _Uncacheable(InternalFaultError):
    """The function has an input the key cannot represent safely; parse it uncached."""


@dataclass(frozen=True)
class _Entry:
    name: str
    description: str | None
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None
    return_type: Any
    #: Strong references to objects whose `id()` is part of the key, so ids are never reused.
    anchors: tuple[Any, ...]


_original: Any = None
_lock = threading.Lock()
_entries: OrderedDict[tuple[Any, ...], _Entry] = OrderedDict()
_enabled = True
_hits = 0
_misses = 0


def _copy_json(value: Any) -> Any:
    """Copy a JSON-shaped value; dicts and lists are rebuilt, anything else is shared."""

    if isinstance(value, dict):
        return {key: _copy_json(item) for key, item in cast(dict[Any, Any], value).items()}
    if isinstance(value, list):
        return [_copy_json(item) for item in cast(list[Any], value)]
    return value


def _freeze(value: Any) -> tuple[Any, Any]:
    """Key a value by type and equality; unhashable values cannot be keyed."""

    try:
        hash(value)
    except TypeError as error:
        raise _Uncacheable from error
    return (cast(Any, type(value)), value)


def _layer_key(fn: Callable[..., Any]) -> tuple[Any, ...]:
    if type(fn) is not types.FunctionType:
        raise _Uncacheable
    # An explicit `__signature__` or other attribute could change what FastMCP sees.
    # `__fastmcp__` is the registration metadata FastMCP attaches; parsing never reads it.
    if set(fn.__dict__) - _HARMLESS_ATTRIBUTES:
        raise _Uncacheable
    annotations = tuple((name, _freeze(item)) for name, item in fn.__annotations__.items())
    defaults = tuple(_freeze(item) for item in fn.__defaults__ or ())
    kwdefaults = tuple((name, _freeze(item)) for name, item in (fn.__kwdefaults__ or {}).items())
    return (
        fn.__code__,
        id(fn.__globals__),
        fn.__name__,
        fn.__doc__,
        defaults,
        kwdefaults,
        annotations,
    )


def _cache_key(
    fn: Callable[..., Any],
    validate: bool,
    wrap_non_object_output_schema: bool,
) -> tuple[tuple[Any, ...], tuple[Any, ...]]:
    """Return the key and the anchors of a plain function, following `functools.wraps` layers."""

    layers: list[tuple[Any, ...]] = []
    anchors: list[Any] = []
    current: Any = fn
    for _ in range(_MAX_WRAPPER_DEPTH):
        layers.append(_layer_key(current))
        anchors.append(current.__globals__)
        wrapped = current.__dict__.get("__wrapped__")
        if wrapped is None:
            key = (
                tuple(layers),
                validate,
                wrap_non_object_output_schema,
            )
            return key, tuple(anchors)
        current = wrapped
    raise _Uncacheable


def _from_function(
    cls: type[ParsedFunction],
    fn: Callable[..., Any],
    validate: bool = True,
    wrap_non_object_output_schema: bool = True,
) -> ParsedFunction:
    global _hits, _misses
    if not _enabled:
        return _original(cls, fn, validate, wrap_non_object_output_schema)
    try:
        key, anchors = _cache_key(fn, validate, wrap_non_object_output_schema)
    except _Uncacheable:
        return _original(cls, fn, validate, wrap_non_object_output_schema)
    with _lock:
        entry = _entries.get(key)
        if entry is not None:
            _entries.move_to_end(key)
            _hits += 1
    if entry is not None:
        return cls(
            fn=fn,
            name=entry.name,
            description=entry.description,
            input_schema=_copy_json(entry.input_schema),
            output_schema=_copy_json(entry.output_schema),
            return_type=entry.return_type,
        )
    parsed: ParsedFunction = _original(cls, fn, validate, wrap_non_object_output_schema)
    # FastMCP rewrote the function (Context injection): the result is not a pure function of the
    # key's inputs, so do not reuse it.
    if parsed.fn is not fn:
        return parsed
    with _lock:
        _misses += 1
        _entries[key] = _Entry(
            name=parsed.name,
            description=parsed.description,
            input_schema=_copy_json(parsed.input_schema),
            output_schema=_copy_json(parsed.output_schema),
            return_type=parsed.return_type,
            anchors=anchors,
        )
        while len(_entries) > _MAX_ENTRIES:
            _entries.popitem(last=False)
    return parsed


def _reviewed_shape() -> str | None:
    """Return why the installed FastMCP is not the reviewed one, or None when it is."""

    installed = metadata.version("fastmcp")
    if installed != REVIEWED_FASTMCP_VERSION:
        return f"fastmcp {installed} is not the reviewed {REVIEWED_FASTMCP_VERSION}"
    method = ParsedFunction.__dict__.get("from_function")
    if not isinstance(method, classmethod):
        return "ParsedFunction.from_function is not a classmethod"
    parameters = tuple(inspect.signature(cast(Any, method).__func__).parameters)
    if parameters != _EXPECTED_PARAMETERS:
        return "ParsedFunction.from_function has an unexpected signature"
    fields = tuple(inspect.signature(ParsedFunction).parameters)
    if fields != _EXPECTED_FIELDS:
        return "ParsedFunction has unexpected fields"
    return None


def install_schema_cache() -> bool:
    """Install the cache once; return whether it is active. Safe to call repeatedly."""

    global _original
    if _original is not None:
        return True
    reason = _reviewed_shape()
    if reason is not None:
        LOGGER.warning("MCP schema cache not installed: %s", reason)
        return False
    method = ParsedFunction.__dict__["from_function"]
    _original = method.__func__
    ParsedFunction.from_function = classmethod(_from_function)  # pyright: ignore[reportAttributeAccessIssue]
    return True


def clear_schema_cache() -> None:
    global _hits, _misses
    with _lock:
        _entries.clear()
        _hits = 0
        _misses = 0


def schema_cache_stats() -> tuple[int, int, int]:
    """Return (hits, misses, entries), for tests."""

    with _lock:
        return _hits, _misses, len(_entries)


@contextmanager
def schema_cache_disabled() -> Iterator[None]:
    """Parse every tool with FastMCP's own code, for reference builds in tests."""

    global _enabled
    previous = _enabled
    _enabled = False
    try:
        yield
    finally:
        _enabled = previous
