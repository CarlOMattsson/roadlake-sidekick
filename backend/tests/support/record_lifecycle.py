"""Shared test helpers moved out of `tests/unit/test_record_lifecycle.py`."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sidekick.lifecycle import RecordKind, TrashItem, TrashPosition
from sidekick.shared.errors import ConflictError
from sidekick.shared.types import new_uuid7

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return NOW


class FakeLifecycleStore:
    def __init__(self) -> None:
        self.items = [
            TrashItem(RecordKind.TASK, new_uuid7(), "Prepare pitch", None, 3),
        ]
        self.idempotency: dict[tuple[UUID, str, str], tuple[str, dict[str, Any]]] = {}
        self.audit: list[tuple[str, str]] = []
        self.removed: list[UUID] = []
        self.owner_ids: list[UUID] = []

    def list_trash_owner_ids(self, _session: Any) -> list[UUID]:
        return self.owner_ids

    def transaction(self, operation: Callable[[Any], Any]) -> Any:
        return operation(object())

    def list_trash(
        self,
        _session: Any,
        _owner_id: UUID,
        *,
        kinds: frozenset[RecordKind],
        limit: int,
        after: TrashPosition | None = None,
    ) -> list[TrashItem]:
        # Mirrors the SQL adapter: filter by kind first, order by the total key, keyset, limit.
        visible = [
            item
            for item in self.items
            if item.trashed_at is not None
            and item.kind in kinds
            and (after is None or TrashPosition.of(item).sort_key() < after.sort_key())
        ]
        visible.sort(key=lambda item: TrashPosition.of(item).sort_key(), reverse=True)
        return visible[:limit]

    def set_trashed(
        self,
        _session: Any,
        _owner_id: UUID,
        kind: RecordKind,
        record_id: UUID,
        *,
        version: int,
        trashed: bool,
        now: datetime,
    ) -> TrashItem:
        current = next(item for item in self.items if item.kind is kind and item.id == record_id)
        if current.version != version:
            raise ConflictError("stale version")
        if current.trashed_at is not None and trashed:
            raise ConflictError("already trashed")
        if current.trashed_at is None and not trashed:
            raise ConflictError("not trashed")
        updated = TrashItem(kind, record_id, current.label, now if trashed else None, version + 1)
        self.items[self.items.index(current)] = updated
        return updated

    def permanently_remove(
        self, _session: Any, _owner_id: UUID, kind: RecordKind, record_id: UUID, *, version: int
    ) -> None:
        current = next(item for item in self.items if item.kind is kind and item.id == record_id)
        if current.version != version or current.trashed_at is None:
            raise ConflictError("cannot remove")
        self.items.remove(current)
        self.removed.append(record_id)

    def idempotent(
        self,
        _session: Any,
        *,
        actor_id: UUID,
        operation: str,
        key: str,
        payload: dict[str, Any],
        execute: Callable[[], dict[str, Any]],
        replay: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        fingerprint = json.dumps(payload, sort_keys=True, default=str)
        existing = self.idempotency.get((actor_id, operation, key))
        if existing:
            if existing[0] != fingerprint:
                raise ConflictError("idempotency key was reused")
            return existing[1]
        result = execute()
        record = replay(result) if replay else result
        self.idempotency[(actor_id, operation, key)] = (fingerprint, record)
        return record

    def get_trash_item(
        self, _session: Any, _owner_id: UUID, kind: RecordKind, record_id: UUID
    ) -> TrashItem:
        return next(item for item in self.items if item.kind is kind and item.id == record_id)

    def append_audit(self, _session: Any, *, event: str, outcome: str, **_: Any) -> None:
        self.audit.append((event, outcome))
