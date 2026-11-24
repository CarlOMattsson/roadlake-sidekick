"""What the companion photo tests share: route, capability sets, synthetic files and the upload."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from tests.support import photo_files
from tests.support.companion import bearer

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
