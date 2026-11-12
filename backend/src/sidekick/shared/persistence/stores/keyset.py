"""Keyset ("seek") paging: continue a list strictly after the last row the client has seen."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import String, func, literal, tuple_
from sqlalchemy.sql import ColumnElement

from sidekick.shared.types import SORT_KEY_CHARS, KeyValue


def text_key(column: Any) -> ColumnElement[str]:
    """A text sort key cut to `SORT_KEY_CHARS` characters, so a cursor carrying it stays small.

    Order by this expression, then by the id: the order is still total, and ties beyond the cut
    fall to the id. Use it for both the ORDER BY and `rows_after`.
    """

    return func.left(column, SORT_KEY_CHARS, type_=String)


def rows_after(
    columns: Sequence[Any], position: tuple[KeyValue, ...], *, descending: bool
) -> ColumnElement[bool]:
    """The rows that sort strictly after `position` when ordered by `columns`.

    The columns are the list's whole sort key and end in a unique id, so the order is total and
    a row can neither be repeated nor skipped by rows added or removed meanwhile. Every column
    sorts the same way (all ascending, or all descending) and none is nullable.
    """

    row = tuple_(*columns)
    marker = tuple_(
        *(literal(value, column.type) for column, value in zip(columns, position, strict=True))
    )
    return row < marker if descending else row > marker
