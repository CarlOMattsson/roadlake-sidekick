"""MCP tool-argument validation errors name the fields that failed, never the rejected values.

Two paths reject a call before the tool body runs, and both can quote the rejected input:

1. FastMCP's pydantic argument validation raises an error whose text repeats each `input_value`.
   `RedactedToolArgumentErrors` turns it into a ToolError with `field: error type` pairs.
2. The JSON Schema check of the arguments against the tool's listed input schema. MCP SDK 1.x
   ran it in its low-level `tools/call` handler when `strict_input_validation=True`; SDK 2.x and
   FastMCP 4 dropped it (FastMCP's flag now means strict pydantic instead). `SchemaCheckedArguments`
   runs the same check as middleware, before FastMCP's pydantic validation, and answers with
   `path: validator` rows. Manual-schema tools such as the agent read wrappers take `**arguments`,
   so this check is the only one their input gets before the gateway.

Both keep the field name so the model can correct the call. Neither includes a value.

A third check, `NulFreeArguments`, answers a NUL character anywhere in the arguments as a
`validation_error`: PostgreSQL cannot store one and would otherwise fail the call as internal.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from functools import lru_cache
from typing import Any, cast

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError, ValidationError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import ToolResult
from jsonschema import ValidationError as SchemaValidationError
from jsonschema.protocols import Validator
from jsonschema.validators import validator_for
from mcp.types import CallToolRequestParams
from pydantic import ValidationError as PydanticValidationError

from sidekick.mcp.request_log import SchemaRejection
from sidekick.mcp.results import error_result
from sidekick.shared.errors import ValidationError as SidekickValidationError
from sidekick.shared.text_guard import contains_nul

_MAX_REPORTED = 10
# One validator per listed tool schema is enough; the bound keeps the cache small if schemas change.
_VALIDATOR_CACHE_SIZE = 64
_NO_FIELD = "arguments"
_UNKNOWN_TYPE = "invalid value"
# The model-facing message: a plain sentence first, then the field rows (names only, no values).
_ARGUMENTS_SENTENCE = "The request was missing or had a wrong value."
_ARGUMENTS_PREFIX = f"{_ARGUMENTS_SENTENCE} Fields:"
_PYDANTIC_PREFIX = _ARGUMENTS_PREFIX
_PYDANTIC_FALLBACK = _ARGUMENTS_SENTENCE
_SDK_MESSAGE_PREFIX = _ARGUMENTS_PREFIX
_SDK_FALLBACK = _ARGUMENTS_SENTENCE

# Pydantic error type -> fixed description. Anything not listed falls back to `_UNKNOWN_TYPE`,
# so no message text from pydantic (which can quote the input) is ever used.
_TYPE_LABELS: dict[str, str] = {
    "missing": "required field missing",
    "extra_forbidden": "unexpected field",
    "uuid_parsing": "invalid UUID",
    "string_type": "expected string",
    "string_too_short": "too short",
    "string_too_long": "too long",
    "int_type": "expected integer",
    "int_parsing": "expected integer",
    "int_from_float": "expected integer",
    "float_type": "expected number",
    "float_parsing": "expected number",
    "bool_type": "expected boolean",
    "bool_parsing": "expected boolean",
    "list_type": "expected list",
    "dict_type": "expected object",
    "model_type": "expected object",
    "model_attributes_type": "expected object",
    "json_invalid": "invalid JSON",
    "date_type": "expected date",
    "date_parsing": "invalid date",
    "date_from_datetime_parsing": "invalid date",
    "datetime_type": "expected date and time",
    "datetime_parsing": "invalid date and time",
    "literal_error": "not an allowed value",
    "greater_than": "out of range",
    "greater_than_equal": "out of range",
    "less_than": "out of range",
    "less_than_equal": "out of range",
    "too_short": "too few items",
    "too_long": "too many items",
}


def _join_rows(prefix: str, rows: list[str], fallback: str) -> str:
    """Join at most `_MAX_REPORTED` rows after `prefix`; an empty list gives `fallback`."""

    if not rows:
        return fallback
    message = f"{prefix} " + "; ".join(rows[:_MAX_REPORTED])
    hidden = len(rows) - _MAX_REPORTED
    if hidden > 0:
        message += f"; and {hidden} more"
    return message


def _field_path(parts: Iterable[Any]) -> str:
    return ".".join(str(part) for part in parts) or _NO_FIELD


def _describe(error: BaseException | None) -> str:
    """Return `field: error type` pairs for a pydantic argument error, without any input value."""

    if not isinstance(error, PydanticValidationError):
        return _PYDANTIC_FALLBACK
    # Only `loc` and `type` are read. `msg`, `input` and `ctx` can quote the rejected value.
    details = error.errors(include_url=False, include_input=False, include_context=False)
    rows = [
        f"{_field_path(item['loc'])}: {_TYPE_LABELS.get(item['type'], _UNKNOWN_TYPE)}"
        for item in details
    ]
    return _join_rows(_PYDANTIC_PREFIX, rows, _PYDANTIC_FALLBACK)


def _schema_rows(error: SchemaValidationError) -> list[str]:
    """Return `path: validator` rows for one JSON Schema error. Never reads its message."""

    path: list[Any] = list(error.absolute_path)
    # jsonschema's stubs are looser than their runtime values; `str()` keeps the comparison typed.
    keyword = str(error.validator)
    if keyword == "required":
        # Names the missing properties from the schema's own `required` list. The values the
        # caller sent are only checked for key presence, never reported.
        instance: object = error.instance
        present: set[object] = set()
        if isinstance(instance, dict):
            present = set(cast("dict[object, object]", instance))
        required: object = error.validator_value
        names: list[object] = []
        if isinstance(required, list):
            names = list(cast("list[object]", required))
        return [
            f"{_field_path([*path, name])}: required"
            for name in names
            if isinstance(name, str) and name not in present
        ]
    return [f"{_field_path(path)}: {keyword}"]


@lru_cache(maxsize=_VALIDATOR_CACHE_SIZE)
def _validator_for_schema_json(schema_json: str) -> Validator:
    # Built from a copy loaded from the key, so later changes to the caller's dict do not reach it.
    schema: dict[str, Any] = json.loads(schema_json)
    return validator_for(schema)(schema)


def _validator_for(schema: dict[str, Any]) -> Validator:
    """Return the validator for a listed schema, reusing it for every call with an equal schema.

    The key keeps key order (no `sort_keys`), because jsonschema reports errors in schema order and
    the message text depends on that order. `lru_cache` is thread-safe for concurrent lookups.
    """

    return _validator_for_schema_json(json.dumps(schema))


def _schema_message(schema: dict[str, Any], arguments: dict[str, Any]) -> str | None:
    """Check the arguments against the tool's listed schema; describe every failure, or None."""

    # A failure with no describable row still counts as a failure, so the fallback is returned.
    errors = list(_validator_for(schema).iter_errors(arguments))
    if not errors:
        return None
    rows: list[str] = []
    for error in errors:
        rows.extend(_schema_rows(error))
    return _join_rows(_SDK_MESSAGE_PREFIX, rows, _SDK_FALLBACK)


class SchemaCheckedArguments(Middleware):
    """Reject a `tools/call` whose arguments do not match the tool's listed input schema."""

    def __init__(self, mcp: FastMCP) -> None:
        self._mcp = mcp

    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        params = context.message
        tool = await self._mcp.get_tool(params.name)
        if tool is not None:
            arguments: dict[str, Any] = params.arguments or {}
            message = _schema_message(tool.parameters, arguments)
            if message is not None:
                raise SchemaRejection(message)
        return await call_next(context)


class NulFreeArguments(Middleware):
    """Answer a `tools/call` with a NUL character in any argument as a client error.

    One check over the whole argument tree, so every text field of every tool (nested ones and
    keys included) is covered, and the rejected text is never echoed.
    """

    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        if contains_nul(context.message.arguments):
            return error_result(
                SidekickValidationError("NUL character in arguments", reason="nul_character")
            )
        return await call_next(context)


class RedactedToolArgumentErrors(Middleware):
    """Replace FastMCP's pydantic argument-validation error with a ToolError that omits values."""

    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        try:
            return await call_next(context)
        except ValidationError as error:
            # FastMCP keeps the pydantic error as the cause; its own str() repeats the input.
            message = _describe(error.__cause__)
        except PydanticValidationError as error:
            message = _describe(error)
        # Raised outside the except block, so the original error is not chained onto the response.
        raise ToolError(message)


def install_validation_error_redaction(mcp: FastMCP) -> None:
    """Check arguments against the listed schema and redact validation text on one server.

    Call once, right after the server is constructed and before tools are added. The schema check
    is added before FastMCP's pydantic validation, as the SDK's check did. The NUL check goes
    first of all: it needs no schema and refuses the call whatever else is wrong with it.
    """

    mcp.add_middleware(NulFreeArguments())
    mcp.add_middleware(SchemaCheckedArguments(mcp))
    mcp.add_middleware(RedactedToolArgumentErrors())
