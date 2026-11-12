"""Replay projections for idempotent writes: what a retry may keep of a first result.

`StoreBase.idempotent` stores whatever projection an operation passes as `replay`, after checking
that it holds identifiers only. A retry then returns that record, and the application layer
re-reads the rest by id, so no title, note or name is kept in the idempotency table.
"""

from typing import Any


def id_replay_record(result: dict[str, Any]) -> dict[str, Any]:
    """Projection of one serialized record: its id alone, no titles, notes or names."""

    return {"id": result["id"]}


def items_replay_record(result: dict[str, Any], key: str = "items") -> dict[str, Any]:
    """Projection of an ordered list of records (`{key: [...]}`): their ids, in order."""

    return {key: [{"id": item["id"]} for item in result[key]]}
