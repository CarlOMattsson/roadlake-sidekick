"""The listed-schema check reuses one validator per schema and keeps its messages unchanged."""
# pyright: reportPrivateUsage=false

import copy
from typing import Any

from sidekick.mcp.validation_errors import (
    _VALIDATOR_CACHE_SIZE,
    _schema_message,
    _validator_for,
    _validator_for_schema_json,
)

FALLBACK = "The request was missing or had a wrong value."

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "maxLength": 5},
        "n": {"type": "integer"},
        "due": {"type": "string"},
    },
    "required": ["title", "due"],
    "additionalProperties": False,
}
# Same content, other key order: jsonschema reports errors in schema order, so the message follows.
SAME_KEYS_OTHER_ORDER: dict[str, Any] = {
    "type": "object",
    "properties": {
        "n": {"type": "integer"},
        "title": {"type": "string", "maxLength": 5},
        "due": {"type": "string"},
    },
    "required": ["title", "due"],
    "additionalProperties": False,
}


def test_equal_schemas_share_one_validator() -> None:
    first = _validator_for(SCHEMA)

    assert _validator_for(copy.deepcopy(SCHEMA)) is first
    assert _validator_for(SCHEMA) is first
    assert _validator_for(SAME_KEYS_OTHER_ORDER) is not first
    assert _validator_for_schema_json.cache_info().maxsize == _VALIDATOR_CACHE_SIZE


def test_valid_arguments_give_no_message() -> None:
    assert _schema_message(SCHEMA, {"title": "ok", "due": "x"}) is None


def test_invalid_arguments_name_the_fields_and_never_the_values() -> None:
    message = _schema_message(
        SCHEMA, {"title": 123456789, "due": "SECRET-VALUE", "n": "SECRET2", "extra": "SECRET3"}
    )

    assert (
        message == f"{FALLBACK} Fields: title: expected string; n: expected integer; "
        "arguments: unexpected field"
    )
    assert message is not None
    assert "SECRET" not in message
    assert "123456789" not in message


def test_missing_required_fields_are_named_without_values() -> None:
    assert _schema_message(SCHEMA, {"title": "ok"}) == f"{FALLBACK} Fields: due: required"


def test_error_order_follows_the_schema_key_order() -> None:
    message = _schema_message(SAME_KEYS_OTHER_ORDER, {"title": 999999, "n": "x"})

    assert (
        message == f"{FALLBACK} Fields: n: expected integer; title: expected string; due: required"
    )
    assert _schema_message(SCHEMA, {"title": 999999, "n": "x"}) == (
        f"{FALLBACK} Fields: title: expected string; n: expected integer; due: required"
    )


def test_a_failure_without_a_describable_row_still_rejects() -> None:
    # A non-string name in `required` yields no row, but the arguments are still invalid.
    assert _schema_message({"type": "object", "required": [1]}, {}) == FALLBACK


UNION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "cursor": {"anyOf": [{"type": "string", "maxLength": 3}, {"type": "null"}]},
        "due": {"anyOf": [{"type": "string"}, {"type": "integer"}, {"type": "null"}]},
        "nested": {
            "type": "object",
            "properties": {"title": {"type": "string", "minLength": 1}},
        },
    },
}


def test_a_union_names_the_types_it_takes_when_no_alternative_fits_the_type() -> None:
    message = _schema_message(UNION_SCHEMA, {"cursor": 5, "due": ["SECRET"]})

    assert message == (
        f"{FALLBACK} Fields: cursor: expected string or null; "
        "due: expected string or integer or null"
    )
    assert message is not None
    assert "SECRET" not in message


def test_a_union_names_what_the_matching_alternative_objected_to() -> None:
    assert _schema_message(UNION_SCHEMA, {"cursor": "SECRET-LONG"}) == (
        f"{FALLBACK} Fields: cursor: too long"
    )


def test_a_nested_failure_names_the_whole_path_and_the_reason() -> None:
    assert _schema_message(UNION_SCHEMA, {"nested": {"title": ""}}) == (
        f"{FALLBACK} Fields: nested.title: too short"
    )
