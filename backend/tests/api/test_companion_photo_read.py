"""`GET /companion/v1/journal/photos/{photo_id}`: the phone reads a photo back (Android).

The route calls the same use case as the app-only `get_journal_photo` tool. It needs the read
capability, answers only for the caller's own photos, and never writes a caption, a byte or an id
to the logs. Synthetic images only.
"""

from __future__ import annotations

import base64
import logging
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from sidekick.api import companion_photos
from sidekick.structured.journal_photos import trash_journal_photo_structured
from tests.support.companion import bearer, companion_app, owner, owner_actor, paired_token
from tests.support.companion_photos import (
    ALT,
    PHOTO,
    PHOTOS,
    READ_ONLY,
    TASKS_ONLY,
    THUMB,
    WRITE_ONLY,
    upload,
)


def read(client: TestClient, token: str, photo_id: str, size: str | None = None) -> Any:
    query = f"?size={size}" if size else ""
    return client.get(f"{PHOTOS}/{photo_id}{query}", headers=bearer(token))


@pytest.mark.integration
def test_a_photo_is_read_back_as_thumbnail_or_file_with_its_record() -> None:
    app = companion_app()
    user_id = owner(app)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        added = upload(client, token, {"journal_date": "2026-11-22", "alt_text": ALT})
        photo_id = added.json()["photo"]["id"]
        thumb = read(client, token, photo_id)
        file = read(client, token, photo_id, "photo")

    assert thumb.status_code == 200 and file.status_code == 200
    assert thumb.headers["cache-control"] == "no-store"
    assert thumb.json()["size"] == "thumb" and file.json()["size"] == "photo"
    assert base64.b64decode(thumb.json()["data"]) == THUMB
    assert base64.b64decode(file.json()["data"]) == PHOTO
    assert thumb.json()["photo"]["id"] == photo_id and thumb.json()["photo"]["alt_text"] == ALT
    assert "digest" not in thumb.text


@pytest.mark.integration
def test_reading_a_photo_needs_the_read_capability_and_the_owners_own_photo() -> None:
    app = companion_app()
    mine = owner(app, "mine")
    theirs = owner(app, "theirs")
    with TestClient(app) as client:
        their_token = paired_token(client, app, theirs)
        added = upload(client, their_token, {"journal_date": "2026-11-22"})
        their_photo = added.json()["photo"]["id"]
        writer_only = paired_token(client, app, theirs, scopes=WRITE_ONLY)
        tasks = paired_token(client, app, theirs, scopes=TASKS_ONLY)
        reader = paired_token(client, app, theirs, scopes=READ_ONLY)
        my_token = paired_token(client, app, mine)

        assert read(client, writer_only, their_photo).status_code == 403
        assert read(client, tasks, their_photo).status_code == 403
        assert client.get(f"{PHOTOS}/{their_photo}").status_code == 401
        assert read(client, reader, their_photo).status_code == 200
        foreign = read(client, my_token, their_photo)
        missing = read(client, my_token, str(uuid4()))
        bad_size = read(client, their_token, their_photo, "full")

    assert foreign.status_code == 404 and missing.status_code == 404
    assert their_photo not in foreign.text
    assert bad_size.status_code == 422


@pytest.mark.integration
def test_a_trashed_photo_is_not_read_and_a_photo_too_big_for_one_answer_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = companion_app()
    user_id = owner(app)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        photo = upload(client, token, {"journal_date": "2026-11-22"}).json()["photo"]
        with monkeypatch.context() as small:
            small.setattr(companion_photos, "MAX_RESPONSE_BYTES", 100)
            too_big = read(client, token, photo["id"], "photo")
        trash_journal_photo_structured(
            app.state.container,
            owner_actor(user_id),
            UUID(photo["id"]),
            version=photo["version"],
            idempotency_key=f"trash-{uuid4().hex}",
            correlation_id=None,
        )
        gone = read(client, token, photo["id"])

    assert too_big.status_code == 422
    assert gone.status_code == 404


@pytest.mark.integration
def test_no_byte_or_caption_of_a_read_photo_reaches_the_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = companion_app()
    user_id = owner(app)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        added = upload(client, token, {"journal_date": "2026-11-22", "alt_text": ALT})
        photo_id = added.json()["photo"]["id"]
        with caplog.at_level(logging.DEBUG):
            assert read(client, token, photo_id).status_code == 200
    logged = "\n".join(
        record.getMessage() + str(getattr(record, "__dict__", "")) for record in caplog.records
    )
    for secret in (ALT, token, photo_id):
        assert secret not in logged, secret
    assert "journal.photo_read" in logged
