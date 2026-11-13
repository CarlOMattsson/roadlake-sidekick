"""Small structured MCP result models and compatible text content."""

import copy
import functools
import json
from collections.abc import Mapping, Sequence
from typing import cast
from uuid import uuid4

import pydantic_core
from fastmcp.tools import ToolResult
from mcp.types import TextContent
from pydantic import BaseModel
from pydantic.json_schema import JsonSchemaMode

from sidekick.mcp.correlation import request_correlation_id
from sidekick.mcp.text import flat
from sidekick.shared.errors.core import CLIENT_INPUT_ERRORS, SidekickError, SidekickErrorReason

# One fixed English sentence per closed SidekickError reason, appended to the error text.
REASON_ADVICE: dict[SidekickErrorReason, str] = {
    "stale_version": "Re-read the record and retry with its current version.",
    "not_before_after_due": (
        "Set the earliest start no later than the due date, or change the due date as well."
    ),
    "not_completed": "Only a completed task can be reopened.",
    "nul_character": "Remove the NUL (\\u0000) character from the text and retry.",
}

# A stale version on a named record: the spoken first line names it and says what to do.
_STALE_SUBJECT_TEXT: dict[str, str] = {
    "shopping_item": "{name} changed (bought in the app?). Re-read the list and retry.",
    "task": "{name} changed. Re-read the task and retry.",
}
_SUBJECT_CHARS = 60

_ERROR_MESSAGES = {
    "unauthorized": "Authentication required.",
    "forbidden": "You do not have access to that.",
    "validation_error": "Request validation failed.",
    "not_found": "I could not find that. Check the name or search again.",
    "conflict": "That changed in the meantime.",
    "idempotency_conflict": "That request key was already used with different data.",
    "unavailable": "Service unavailable.",
    "internal_error": "Request failed.",
}

_SPOKEN_NAME_LIMIT = 3
_SPOKEN_NAME_CHARS = 60


def spoken_names(names: Sequence[str], total: int) -> str:
    """Up to three names for the summary line: "A, B and C", or "A, B and 2 more" when more exist.

    `total` is how many items the names stand for; items beyond the names are counted as more.
    Each name is flattened and cut, so it stays on the one summary line. Returns "" for no names.
    """

    shown = [flat(name, limit=_SPOKEN_NAME_CHARS) for name in names[:_SPOKEN_NAME_LIMIT]]
    if not shown:
        return ""
    more = total - len(shown)
    if more > 0:
        return f"{', '.join(shown)} and {more} more"
    if len(shown) == 1:
        return shown[0]
    return f"{', '.join(shown[:-1])} and {shown[-1]}"


# Block 2 (the compact JSON) is left out above this size, so a very large result does not
# double the text the model is given. structuredContent is unchanged either way.
_TEXT_JSON_LIMIT = 30_000
_LARGE_RESULT_NOTE = (
    "Full data is in structuredContent; narrow the request (filters, limit) to get it as text."
)


@functools.cache
def _cached_output_schema(model: type[BaseModel], mode: JsonSchemaMode) -> dict[str, object]:
    return model.model_json_schema(mode=mode)


def output_schema(
    model: type[BaseModel], *, mode: JsonSchemaMode = "validation"
) -> dict[str, object]:
    """Return a private copy of the memoised JSON Schema for a tool's output model.

    The copy keeps callers from mutating the cached schema shared by later tool builds.
    """

    return copy.deepcopy(_cached_output_schema(model, mode))


def _without_empty(value: object) -> object:
    """Return a copy of a JSON-compatible value without keys whose value is None or ``[]``.

    The rule applies recursively to dicts and to dicts inside lists. Other values, including
    ``0``, ``""``, ``False`` and ``{}``, are kept, so id, version and status stay when they have
    values.
    """

    if isinstance(value, dict):
        mapping = cast(dict[str, object], value)
        return {
            key: _without_empty(item)
            for key, item in mapping.items()
            if item is not None and item != []
        }
    if isinstance(value, list):
        return [_without_empty(item) for item in cast(list[object], value)]
    return value


def result(
    structured_content: Mapping[str, object],
    text: str,
    *,
    text_json: Mapping[str, object] | None = None,
) -> ToolResult:
    """Return structured content plus two text blocks for model clients.

    Model clients such as claude.ai only see text blocks. Block 1 is the summary line and
    block 2 is the compact JSON of the result, so the model sees the ids. ``text_json`` replaces
    ``structured_content`` in block 2 for tools whose content must stay out of the text (for
    example Journal text); ``structured_content`` itself is unchanged. The JSON is serialized the
    way FastMCP serializes structured content (pydantic ``to_jsonable_python``), then keys whose
    value is None or an empty list are left out of block 2 (see ``_without_empty``), before
    compact encoding.
    """

    payload = structured_content if text_json is None else text_json
    serialized = json.dumps(
        _without_empty(pydantic_core.to_jsonable_python(payload)),
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
        sort_keys=False,
    )
    if len(serialized) > _TEXT_JSON_LIMIT:
        return ToolResult(
            structured_content=structured_content,
            content=[TextContent(type="text", text=f"{text}\n{_LARGE_RESULT_NOTE}")],
        )
    return ToolResult(
        structured_content=structured_content,
        content=[
            TextContent(type="text", text=text),
            TextContent(type="text", text=serialized),
        ],
    )


def card_result(structured_content: Mapping[str, object], text: str) -> ToolResult:
    """Return structured content for an app card with one short text block for the model.

    The card renders `structured_content`, which is unchanged. The model gets only `text`, a
    one-line summary built with `card_text`, so it does not copy the list back into the chat.
    No JSON block is added, because that block would repeat the whole result.
    """

    return ToolResult(
        structured_content=structured_content,
        content=[TextContent(type="text", text=text)],
    )


def error_result(error: Exception) -> ToolResult:
    """Return a bounded MCP error without exposing exception details."""

    if isinstance(error, CLIENT_INPUT_ERRORS):
        code = "validation_error"
    else:
        code = getattr(error, "code", "internal_error")
        if code not in _ERROR_MESSAGES:
            code = "internal_error"
    message = _ERROR_MESSAGES[code]
    # A SidekickError reason is a closed value with fixed advice, never the exception's text.
    reason: SidekickErrorReason | None = error.reason if isinstance(error, SidekickError) else None
    if reason is not None:
        message = f"{message} {REASON_ADVICE[reason]}"
        if (
            isinstance(error, SidekickError)
            and reason == "stale_version"
            and error.subject
            and error.subject_kind in _STALE_SUBJECT_TEXT
        ):
            name = flat(error.subject, limit=_SUBJECT_CHARS)
            message = _STALE_SUBJECT_TEXT[error.subject_kind].format(name=name)
    structured_content = {
        "code": code,
        "message": message,
        # The id of the request being answered, so the reply matches its log lines. Outside a
        # request (a unit test, a worker) there is none and a fresh one is issued.
        "correlation_id": request_correlation_id() or uuid4().hex,
    }
    if reason is not None:
        structured_content["reason"] = reason
    return ToolResult(
        structured_content=structured_content,
        content=[TextContent(type="text", text=message)],
        is_error=True,
    )
