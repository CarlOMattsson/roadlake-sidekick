"""Typed helpers that turn a partial-update model into the arguments of a use case.

A `*Changes` model records which fields the caller sent (`model_fields_set`). The use cases take
`UNSET` for a field that was not sent, so an omitted field stays and an explicit null still applies.
"""

from __future__ import annotations

from pydantic import BaseModel

from sidekick.shared.types import UNSET, UnsetType


def sent[T](changes: BaseModel, name: str, value: T) -> T | UnsetType:
    """`value` when the caller sent the field (an explicit null included), else `UNSET`."""

    return value if name in changes.model_fields_set else UNSET


def present[T](value: T | None) -> T | UnsetType:
    """`value`, or `UNSET` for a field that cannot be cleared.

    The change models reject an explicit null on such a field, so null means it was not sent.
    """

    return UNSET if value is None else value
