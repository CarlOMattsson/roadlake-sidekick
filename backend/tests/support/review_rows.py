"""Insert helpers for the repetition tables: one valid row each, changed by keyword overrides.

A card names a library fact, which has no table yet, so a card made here needs no other row. The
statements run on the connection they are given, so a test chooses the role.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy.engine import Connection

from tests.support.automation_rows import Sql, insert_row


def insert_card(connection: Connection, owner_id: str, **overrides: Any) -> str:
    values: dict[str, Any] = {
        "id": str(uuid4()),
        "owner_id": owner_id,
        "source_kind": "library_fact",
        "library_fact_id": str(uuid4()),
        "scheduler_version": "fsrs-6.3.3/r0.90/s10m/v1",
        "version": 1,
        "created_at": Sql("now()"),
        "updated_at": Sql("now()"),
        **overrides,
    }
    insert_row(connection, "review_cards", values)
    return str(values["id"])


def insert_log(connection: Connection, owner_id: str, card_id: str, **overrides: Any) -> str:
    values: dict[str, Any] = {
        "id": str(uuid4()),
        "owner_id": owner_id,
        "card_id": card_id,
        "rating": 3,
        "reviewed_at": Sql("now()"),
        "received_at": Sql("now()"),
        "client_review_id": str(uuid4()),
        "channel": "app",
        **overrides,
    }
    insert_row(connection, "review_log", values)
    return str(values["id"])


def insert_settings(connection: Connection, owner_id: str, **overrides: Any) -> None:
    values: dict[str, Any] = {
        "owner_id": owner_id,
        "version": 1,
        "created_at": Sql("now()"),
        "updated_at": Sql("now()"),
        **overrides,
    }
    insert_row(connection, "review_settings", values)
