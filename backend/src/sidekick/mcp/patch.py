"""Typed helpers that turn a partial-update model into the arguments of a use case.

A `*Changes` model records which fields the caller sent (`model_fields_set`); a null counts as not
sent, and a field is emptied only when the tool's `clear` list names it (`PartialChanges.resolved`).
The use cases take `UNSET` for a field that was not sent, so an omitted field stays.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel

from sidekick.shared.types import UNSET, UnsetType
from sidekick.structured.base import PartialChanges, WithIgnoredNulls

# The sentence every update tool's description ends with.
CLEAR_SENTENCE = "Null in changes means not sent; to empty a field, list it in clear."


def sent[T](changes: BaseModel, name: str, value: T) -> T | UnsetType:
    """`value` when the field was sent or cleared (it is then None), else `UNSET`."""

    return value if name in changes.model_fields_set else UNSET


def present[T](value: T | None) -> T | UnsetType:
    """`value`, or `UNSET` for a field that cannot be cleared.

    A null on such a field was read as not sent (`PartialChanges.fixed_fields`).
    """

    return UNSET if value is None else value


def updated[T: WithIgnoredNulls](
    output_type: type[T], output: BaseModel, changes: PartialChanges
) -> T:
    """`output` as the reply of an update: the same fields plus the nulls that changed nothing."""

    return output_type.model_validate({**dict(output), "ignored_nulls": changes.ignored_nulls})


def ignored_nulls_note(ignored: Sequence[str]) -> str:
    """A sentence for the reply text when nulls were read as not sent; empty when none were."""

    if not ignored:
        return ""
    return (
        f" Ignored null for {', '.join(ignored)}: null clears nothing. "
        "To empty a field, name it in clear."
    )
