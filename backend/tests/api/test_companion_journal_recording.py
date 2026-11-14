"""The recorded journal answers the phone tests replay.

The file is `frontend/tests/fixtures/companion-journal.json`.

The mobile journal test in `frontend/tests/mobile/journal-mobile-roundtrip.test.tsx` cannot start
this backend, so it replays answers this backend gave: a hand-written entry saved, then the day, the
entry and the source read back. This test records the same four calls and fails when the shape of
any answer (its keys and value types, not its ids or times) differs from the committed file, so the
replayed answers cannot drift from what the routes really send. Refresh the file after an intended
change with `RECORD_COMPANION_FIXTURES=1`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.support.companion import bearer, companion_app, owner, paired_token

FIXTURE = Path(__file__).resolve().parents[3] / "frontend/tests/fixtures/companion-journal.json"
DAY = "2026-11-10"
TITLE = "Promenad på Södermalm"
TEXT = "Gick längs vattnet och funderade på nästa vecka.\nÅ, vilken kväll!"


def shape(value: Any) -> Any:
    """Keys and value types of an answer; a list is the shape of its first item."""
    if isinstance(value, dict):
        return {key: shape(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [shape(value[0])] if value else []
    return "null" if value is None else type(value).__name__


def record() -> dict[str, Any]:
    app = companion_app()
    user_id = owner(app)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        headers = {**bearer(token), "Idempotency-Key": "recording-0001"}
        written = client.post(
            "/companion/v1/journal/entries",
            headers=headers,
            json={"journal_date": DAY, "title": TITLE, "source_text": TEXT},
        )
        entry = written.json()["entry"]
        day = client.get(f"/companion/v1/journal/days/{DAY}?limit=50", headers=bearer(token))
        read = client.get(f"/companion/v1/journal/entries/{entry['id']}", headers=bearer(token))
        source = client.get(
            f"/companion/v1/journal/sources/{entry['source_id']}", headers=bearer(token)
        )
        empty = client.get("/companion/v1/journal/days/2026-11-11", headers=bearer(token))
    for response in (written, day, read, source, empty):
        assert response.status_code == 200, response.text
    return {
        "write": written.json(),
        "day": day.json(),
        "entry": read.json(),
        "source": source.json(),
        "emptyDay": empty.json(),
    }


@pytest.mark.integration
def test_the_recorded_journal_answers_have_the_shape_the_routes_send() -> None:
    recorded = record()
    if os.environ.get("RECORD_COMPANION_FIXTURES") == "1":
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(
            json.dumps(recorded, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    committed = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert {name: shape(value) for name, value in recorded.items()} == {
        name: shape(value) for name, value in committed.items()
    }
    # The recording is the scenario the phone test replays: a hand-written entry has no summary.
    assert committed["write"]["entry"]["summary"] is None
    assert committed["write"]["entry"]["key_points"] == []
    assert committed["source"]["source"]["raw_text"] == TEXT
