"""Cards of the suggestion inbox for the companion tests, written straight to the tables.

The owner of a companion app has one approved-looking automation with a run, and cards the run
proposed. A checked card is written as the independent checker will write it, so it is in the
high-confidence group the phone can approve as a whole.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import FastAPI
from sqlalchemy import text

from tests.support.automation_rows import (
    DIGEST,
    Sql,
    insert_automation,
    insert_run,
    insert_suggestion,
)

CHECKED: dict[str, Any] = {
    "check_state": "checked",
    "verdict": "ok",
    "confidence": 98,
    "bulk_eligible": True,
}


def seed_cards(
    app: FastAPI,
    owner_id: UUID,
    *titles: str,
    checked: bool = False,
    effect: str = "create_task",
) -> list[dict[str, Any]]:
    """One pending card per title (`create_task` or `create_contact`); each is returned as
    `{"id", "version"}`."""

    payload_field = "display_name" if effect == "create_contact" else "title"

    store: Any = app.state.container.session_factory
    cards: list[dict[str, Any]] = []
    with store.begin() as session:
        connection = session.connection()
        automation_id = insert_automation(
            connection,
            str(owner_id),
            state="active",
            approved_digest=DIGEST,
            approved_at=Sql("now()"),
            allowed_effects=["create_task", "create_contact"],
            sources=["mail"],
            cadence={"frequency": "daily", "local_time": "07:00"},
        )
        run_id = insert_run(connection, str(owner_id), automation_id, state="done")
        for title in titles:
            card_id = insert_suggestion(
                connection,
                str(owner_id),
                automation_id,
                run_id,
                effect=effect,
                payload={payload_field: title},
                proposed_payload={payload_field: title},
                rationale="The mail asks for it.",
                **(CHECKED if checked else {}),
            )
            cards.append({"id": card_id, "version": 1})
    return cards


def card_row(app: FastAPI, card_id: str) -> dict[str, Any]:
    """The card's stored row."""

    store: Any = app.state.container.session_factory
    with store.begin() as session:
        row = session.execute(
            text("SELECT * FROM sidekick.automation_suggestions WHERE id = :id"),
            {"id": UUID(card_id)},
        ).mappings()
        return dict(row.one())


def count_rows(app: FastAPI, table: str) -> int:
    """How many rows `sidekick.<table>` holds."""

    store: Any = app.state.container.session_factory
    with store.begin() as session:
        return int(
            session.execute(text(f"SELECT count(*) FROM sidekick.{table}")).scalar_one()  # noqa: S608
        )
