"""Replay projections for idempotent writes: what a retry may keep of a first result.

`StoreBase.idempotent` stores whatever projection an operation passes as `replay`, after checking
that it holds identifiers only. A retry then returns that record, and the application layer
re-reads the rest by id, so no title, note or name is kept in the idempotency table.
"""

from collections.abc import Iterable, Mapping
from typing import Any, TypedDict
from uuid import UUID


class IdRecord(TypedDict):
    """A replay record that names one record: its id as text."""

    id: str


def id_replay_record(result: dict[str, Any]) -> dict[str, Any]:
    """Projection of one serialized record: its id alone, no titles, notes or names."""

    return {"id": result["id"]}


def items_replay_record(result: dict[str, Any], key: str = "items") -> dict[str, Any]:
    """Projection of an ordered list of records (`{key: [...]}`): their ids, in order."""

    return {key: [{"id": item["id"]} for item in result[key]]}


def id_result(record_id: UUID) -> dict[str, str]:
    """What a write hands `StoreBase.idempotent` when a retry re-reads the record by id."""

    return {"id": str(record_id)}


def ids_result(record_ids: Iterable[UUID], key: str = "items") -> dict[str, list[dict[str, str]]]:
    """The same for a write of an ordered list of records (`{key: [{"id": ...}]}`)."""

    return {key: [id_result(record_id) for record_id in record_ids]}


def record_id(record: Mapping[str, object]) -> UUID:
    """The id a replay record holds."""

    return UUID(str(record["id"]))
