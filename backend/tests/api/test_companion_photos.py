"""`POST /companion/v1/journal/photos`: the phone adds a photo as a multipart form (Android).

The route calls the same use case as the app-only `add_journal_photo` tool. The checks are the
ones an owner relies on: the right capability and scopes, an entry that is the caller's own, a file
the format gate accepts, a body that is capped and parsed only after authentication, and fields
that never reach the logs. Synthetic images only.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from sidekick.api.body_limits import MAX_PHOTO_UPLOAD_BODY_BYTES
from sidekick.journal.domain.entry import KeyPoint, KeyPointKind
from sidekick.journal.domain.source import SourceType
from tests.db import create_test_session_factory, require_test_database_url
from tests.support import photo_files
from tests.support.companion import bearer, companion_app, owner, owner_actor, paired_token

PHOTOS = "/companion/v1/journal/photos"
WRITE_CAPABILITIES = {"companion:journal:write", "companion:journal:read"}
READ_ONLY = {"companion:journal:read"}
WRITE_ONLY = {"companion:journal:write"}
TASKS_ONLY = {"companion:tasks:read", "companion:tasks:complete"}
ALT = "Alt-text-hemlig-marker-91"
CAMERA = "Kamera-hemlig-marker-92"
PLACE = "Plats-hemlig-marker-93"
PHOTO = photo_files.jpeg()
THUMB = photo_files.jpeg(320, 240)


def entry_of(app: FastAPI, user_id: UUID) -> str:
    _, entry = app.state.container.journal_capture.write_entry(
        owner_actor(user_id),
        source_type=SourceType.TRANSCRIPT_TEXT,
        journal_date=date(2026, 11, 22),
        occurred_at=datetime(2026, 11, 22, 9, tzinfo=UTC),
        raw_text="Synthetic source text",
        language="sv",
        title="Synthetic entry",
        summary=None,
        key_points=(KeyPoint(KeyPointKind.FACT, "A synthetic fact."),),
        idempotency_key=f"entry-{uuid4().hex}",
    )
    return str(entry.id)


def upload(
    client: TestClient,
    token: str,
    fields: dict[str, Any],
    *,
    photo: bytes = PHOTO,
    thumbnail: bytes = THUMB,
    key: str | None = None,
) -> Any:
    return client.post(
        PHOTOS,
        headers={**bearer(token), "Idempotency-Key": key or f"photo-{uuid4().hex}"},
        files={
            "photo": ("photo.jpg", photo, "image/jpeg"),
            "thumbnail": ("thumb.jpg", thumbnail, "image/jpeg"),
        },
        data=fields,
    )


def count_photos(app: FastAPI) -> int:
    with create_test_session_factory(require_test_database_url())() as session:
        return int(session.scalar(text("SELECT count(*) FROM sidekick.journal_attachments")) or 0)


@pytest.mark.integration
def test_a_photo_is_added_to_an_entry_with_its_fields_and_read_back_through_the_service() -> None:
    app = companion_app()
    user_id = owner(app)
    entry_id = entry_of(app, user_id)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        response = upload(
            client,
            token,
            {
                "entry_id": entry_id,
                "alt_text": ALT,
                "taken_at": "2026-07-04T15:30:00+02:00",
                "lat": "59.3293",
                "lon": "18.0686",
                "place": PLACE,
                "camera": CAMERA,
                "orientation": "6",
            },
        )

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    photo = response.json()["photo"]
    assert photo["entry_id"] == entry_id and photo["journal_date"] is None
    assert (photo["media_type"], photo["width"], photo["height"]) == ("image/jpeg", 640, 480)
    assert (photo["alt_text"], photo["alt_text_by"], photo["camera"]) == (ALT, "you", CAMERA)
    assert photo["location"] == {"lat": 59.3293, "lon": 18.0686, "name": PLACE}
    assert photo["orientation"] == 6 and photo["version"] == 1
    assert photo["taken_at"].startswith("2026-07-04T")
    assert "digest" not in response.text
    stored = app.state.container.journal_photos
    _, bytes_back = stored.read_file(owner_actor(user_id), UUID(photo["id"]), "photo")
    assert bytes_back == PHOTO


@pytest.mark.integration
def test_a_photo_can_hang_on_a_day_and_a_retry_with_the_same_key_stores_one() -> None:
    app = companion_app()
    user_id = owner(app)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        fields = {"journal_date": "2026-11-22"}
        first = upload(client, token, fields, key="retry-key-0001")
        again = upload(client, token, fields, key="retry-key-0001")
        changed = upload(
            client, token, fields, photo=photo_files.jpeg(641, 480), key="retry-key-0001"
        )

    assert first.status_code == 200 and again.status_code == 200
    assert first.json()["photo"]["id"] == again.json()["photo"]["id"]
    assert first.json()["photo"]["journal_date"] == "2026-11-22"
    assert changed.status_code == 409
    assert count_photos(app) == 1


@pytest.mark.integration
def test_the_capabilities_and_the_credential_are_checked_before_anything_is_read() -> None:
    app = companion_app()
    user_id = owner(app)
    entry_id = entry_of(app, user_id)
    fields = {"entry_id": entry_id}
    with TestClient(app) as client:
        reader = paired_token(client, app, user_id, scopes=READ_ONLY)
        writer_only = paired_token(client, app, user_id, scopes=WRITE_ONLY)
        tasks = paired_token(client, app, user_id, scopes=TASKS_ONLY)
        full = paired_token(client, app, user_id, scopes=WRITE_CAPABILITIES)

        assert upload(client, reader, fields).status_code == 403
        assert upload(client, writer_only, fields).status_code == 403
        assert upload(client, tasks, fields).status_code == 403
        anonymous = client.post(
            PHOTOS,
            headers={"Idempotency-Key": "anonymous-0001"},
            files={"photo": ("p.jpg", PHOTO, "image/jpeg")},
        )
        assert anonymous.status_code == 401
        assert upload(client, "rsc_" + "x" * 40, fields).status_code == 401
        assert count_photos(app) == 0
        assert upload(client, full, fields).status_code == 200


@pytest.mark.integration
def test_an_entry_of_another_owner_or_none_is_not_found_and_nothing_is_stored() -> None:
    app = companion_app()
    mine = owner(app, "mine")
    theirs = owner(app, "theirs")
    their_entry = entry_of(app, theirs)
    with TestClient(app) as client:
        token = paired_token(client, app, mine)
        foreign = upload(client, token, {"entry_id": their_entry})
        missing = upload(client, token, {"entry_id": str(uuid4())})

    assert foreign.status_code == 404 and missing.status_code == 404
    assert their_entry not in foreign.text
    assert count_photos(app) == 0
    media = app.state.container.settings.media_directory
    key = app.state.container.journal_photos.files.key_of(mine)
    assert not (media / key).exists()


@pytest.mark.integration
def test_a_file_with_metadata_a_mixed_pair_and_a_thumbnail_too_big_are_refused() -> None:
    app = companion_app()
    user_id = owner(app)
    entry_id = entry_of(app, user_id)
    fields = {"entry_id": entry_id}
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        with_gps = upload(client, token, fields, photo=photo_files.gps_jpeg())
        junk = upload(client, token, fields, photo=b"not an image at all")
        mixed = upload(client, token, fields, thumbnail=photo_files.lossy_webp(320, 240))
        big = upload(client, token, fields, thumbnail=photo_files.jpeg(1000, 800))

    for refused in (with_gps, junk, mixed, big):
        assert refused.status_code == 422, refused.text
    assert count_photos(app) == 0


@pytest.mark.integration
def test_the_form_is_strict_about_its_parts() -> None:
    app = companion_app()
    user_id = owner(app)
    entry_id = entry_of(app, user_id)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        bad_fields: list[dict[str, Any]] = [
            {},
            {"entry_id": entry_id, "journal_date": "2026-11-22"},
            {"entry_id": "not-an-id"},
            {"entry_id": entry_id, "lat": "59.3"},
            {"entry_id": entry_id, "lat": "95", "lon": "10"},
            {"entry_id": entry_id, "place": PLACE},
            {"entry_id": entry_id, "orientation": "9"},
            {"entry_id": entry_id, "taken_at": "yesterday"},
            {"entry_id": entry_id, "owner_id": str(user_id)},
            {"entry_id": [entry_id, entry_id]},
            {"entry_id": entry_id, "alt_text": "data:image/jpeg;base64," + "QUJD" * 60},
        ]
        for fields in bad_fields:
            response = upload(client, token, fields)
            assert response.status_code == 422, (fields, response.text)
            assert response.json()["code"] == "validation_error"
        missing_file = client.post(
            PHOTOS,
            headers={**bearer(token), "Idempotency-Key": "missing-file-01"},
            files={"photo": ("p.jpg", PHOTO, "image/jpeg")},
            data={"entry_id": entry_id},
        )
        assert missing_file.status_code == 422
        no_key = client.post(
            PHOTOS,
            headers=bearer(token),
            files={"photo": ("p.jpg", PHOTO, "image/jpeg"), "thumbnail": ("t.jpg", THUMB, "x")},
            data={"entry_id": entry_id},
        )
        assert no_key.status_code in (400, 422)

    assert count_photos(app) == 0


@pytest.mark.integration
def test_a_json_body_is_the_wrong_media_type_and_an_oversized_body_is_refused_at_ingress() -> None:
    app = companion_app()
    user_id = owner(app)
    entry_id = entry_of(app, user_id)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        headers = {**bearer(token), "Idempotency-Key": "media-type-0001"}
        wrong = client.post(PHOTOS, headers=headers, json={"entry_id": entry_id})
        assert wrong.status_code == 415

        oversized = b"x" * (MAX_PHOTO_UPLOAD_BODY_BYTES + 1)
        boundary = "----sidekick-test-boundary"
        too_big = client.post(
            PHOTOS,
            headers={**headers, "Content-Type": f"multipart/form-data; boundary={boundary}"},
            content=oversized,
        )
        assert too_big.status_code == 413
        assert too_big.json()["code"] == "payload_too_large"
        anonymous = client.post(
            PHOTOS,
            headers={
                "Idempotency-Key": "media-type-0001",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            content=oversized,
        )
        assert anonymous.status_code == 413

    assert count_photos(app) == 0


@pytest.mark.integration
def test_no_field_or_byte_of_an_upload_reaches_the_logs(caplog: pytest.LogCaptureFixture) -> None:
    app = companion_app()
    user_id = owner(app)
    entry_id = entry_of(app, user_id)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        with caplog.at_level(logging.DEBUG):
            ok = upload(
                client,
                token,
                {
                    "entry_id": entry_id,
                    "alt_text": ALT,
                    "lat": "59.3293",
                    "lon": "18.0686",
                    "place": PLACE,
                    "camera": CAMERA,
                },
            )
            refused = upload(
                client,
                token,
                {"entry_id": entry_id, "alt_text": ALT, "camera": CAMERA},
                photo=photo_files.gps_jpeg(),
            )
    assert ok.status_code == 200 and refused.status_code == 422

    logged = "\n".join(
        record.getMessage() + str(getattr(record, "__dict__", "")) for record in caplog.records
    )
    for secret in (ALT, CAMERA, PLACE, "59.3293", "18.0686", token, entry_id):
        assert secret not in logged, secret
    assert "journal.photo_add" in logged
