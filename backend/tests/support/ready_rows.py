"""Insert helpers for the ready conversation tables: one valid row each, changed by overrides.

The statements run on the connection they are given, so a test chooses the role.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy.engine import Connection

from tests.support.automation_rows import Sql, insert_row

DAILY_AT_18 = {
    "frequency": "daily",
    "interval": 1,
    "weekdays": [],
    "day_of_month": None,
    "last_weekday": False,
    "until": None,
    "local_time": "18:00",
}


def insert_conversation(connection: Connection, owner_id: str, **overrides: Any) -> str:
    values: dict[str, Any] = {
        "id": str(uuid4()),
        "owner_id": owner_id,
        "title": "Evening review",
        "kind": "evening_review",
        "cadence": DAILY_AT_18,
        "version": 1,
        "created_at": Sql("now()"),
        "updated_at": Sql("now()"),
        **overrides,
    }
    insert_row(connection, "ready_conversations", values)
    return str(values["id"])


def insert_day(
    connection: Connection, owner_id: str, conversation_id: str, day: str, **overrides: Any
) -> None:
    values: dict[str, Any] = {
        "conversation_id": conversation_id,
        "day": day,
        "owner_id": owner_id,
        "state": "skipped",
        "changed_at": Sql("now()"),
        "version": 1,
        **overrides,
    }
    insert_row(connection, "ready_conversation_days", values)
