"""Shared test helpers moved out of `tests/unit/test_backup.py`."""

from datetime import UTC, datetime
from typing import Any

CREATED_AT = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


class EmptyBackupSession:
    def scalars(self, _query: object) -> Any:
        return self

    def all(self) -> list[object]:
        return []


class EmptyBackupStore:
    def snapshot_transaction(self, operation: Any) -> Any:
        return operation(EmptyBackupSession())


class FixedClock:
    def now(self) -> datetime:
        return CREATED_AT
