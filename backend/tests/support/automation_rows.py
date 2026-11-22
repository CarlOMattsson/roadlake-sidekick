"""Insert helpers for the automation tables: one valid row each, changed by keyword overrides.

A test names only the columns it cares about; every other column holds a value that satisfies the
table's constraints. The statements run on the connection they are given, so a test chooses the
role (the application role or the owner side).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import Connection

DIGEST = "d" * 64


@dataclass(frozen=True)
class Sql:
    """A SQL expression to put into an INSERT as written, such as `now()`."""

    expression: str


_CASTS = {
    "cadence": "jsonb",
    "fields": "jsonb",
    "payload": "jsonb",
    "proposed_payload": "jsonb",
    "datapoint_ids": "uuid[]",
    "sources": "character varying[]",
    "allowed_effects": "character varying[]",
    "auto_effects": "character varying[]",
    "screening_flags": "character varying[]",
    "reason_codes": "character varying[]",
}
_JSON_COLUMNS = frozenset({"cadence", "fields", "payload", "proposed_payload"})


def insert_owner(connection: Connection, owner_id: str) -> None:
    connection.execute(
        text(
            "INSERT INTO sidekick.users (id, username, display_name, created_at) "
            "VALUES (:id, :username, 'Owner', now())"
        ),
        {"id": owner_id, "username": f"owner-{owner_id[-12:]}"},
    )


def insert_automation(connection: Connection, owner_id: str, **overrides: Any) -> str:
    """An automation with only the required columns; the rest takes the column defaults."""

    values: dict[str, Any] = {
        "id": str(uuid4()),
        "owner_id": owner_id,
        "title": "Morning mail",
        "purpose": "Find people and commitments in the morning mail",
        "instruction": "Read the mail and note who writes.",
        "runner": "claude",
        "cadence": {"unit": "day", "local_time": "07:00"},
        "spec_digest": DIGEST,
        "version": 1,
        "created_at": Sql("now()"),
        "updated_at": Sql("now()"),
        **overrides,
    }
    _insert(connection, "automations", values)
    return str(values["id"])


def insert_run(connection: Connection, owner_id: str, automation_id: str, **overrides: Any) -> str:
    values: dict[str, Any] = {
        "id": str(uuid4()),
        "owner_id": owner_id,
        "automation_id": automation_id,
        "occurrence_key": "d:2026-11-22",
        "attempt": 1,
        "runner": "claude",
        "state": "running",
        "spec_digest": DIGEST,
        "credential_kind": "token",
        "version": 1,
        "created_at": Sql("now()"),
        "updated_at": Sql("now()"),
        **overrides,
    }
    _insert(connection, "automation_runs", values)
    return str(values["id"])


def insert_datapoint(
    connection: Connection, owner_id: str, automation_id: str, run_id: str, **overrides: Any
) -> str:
    values: dict[str, Any] = {
        "id": str(uuid4()),
        "owner_id": owner_id,
        "automation_id": automation_id,
        "run_id": run_id,
        "kind": "person",
        "fields": {"name": "Anna Svensson"},
        "source_kind": "mail",
        "source_fingerprint": DIGEST,
        "created_at": Sql("now()"),
        "purge_after": Sql("now() + interval '30 days'"),
        **overrides,
    }
    _insert(connection, "automation_datapoints", values)
    return str(values["id"])


def insert_suggestion(
    connection: Connection, owner_id: str, automation_id: str, run_id: str, **overrides: Any
) -> str:
    values: dict[str, Any] = {
        "id": str(uuid4()),
        "owner_id": owner_id,
        "automation_id": automation_id,
        "run_id": run_id,
        "effect": "create_task",
        "effect_version": 1,
        "payload": {"title": "Call Anna"},
        "proposed_payload": {"title": "Call Anna"},
        "dedupe_fingerprint": uuid4().hex + uuid4().hex,
        "state": "pending",
        "expires_at": Sql("now() + interval '14 days'"),
        "version": 1,
        "created_at": Sql("now()"),
        "updated_at": Sql("now()"),
        **overrides,
    }
    _insert(connection, "automation_suggestions", values)
    return str(values["id"])


def insert_check(
    connection: Connection, owner_id: str, suggestion_id: str, run_id: str, **overrides: Any
) -> str:
    values: dict[str, Any] = {
        "id": str(uuid4()),
        "owner_id": owner_id,
        "suggestion_id": suggestion_id,
        "run_id": run_id,
        "attempt": 1,
        "checker": "openai_compat",
        "model": "checker-model",
        "verdict": "ok",
        "confidence": 97,
        "checked_at": Sql("now()"),
        **overrides,
    }
    _insert(connection, "automation_checks", values)
    return str(values["id"])


def _insert(connection: Connection, table: str, values: dict[str, Any]) -> None:
    """Insert one row into `sidekick.<table>`.

    A `Sql` value is put into the statement as written, the other values are bound parameters;
    JSON values are serialised and array values are cast to their column type.
    """

    placeholders = []
    params: dict[str, Any] = {}
    for column, value in values.items():
        if isinstance(value, Sql):
            placeholders.append(value.expression)
            continue
        placeholders.append(
            f"CAST(:{column} AS {_CASTS[column]})" if column in _CASTS else f":{column}"
        )
        params[column] = (
            json.dumps(value) if column in _JSON_COLUMNS and value is not None else value
        )
    columns = ", ".join(values)
    statement = f"INSERT INTO sidekick.{table} ({columns}) VALUES ({', '.join(placeholders)})"  # noqa: S608
    connection.execute(text(statement), params)
