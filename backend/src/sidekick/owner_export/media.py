"""The photo files an owner export refers to, and how they travel beside the export document.

An export document lists the photos as rows of `journal_attachments`; the bytes are not in it. A
photo row names two files by their SHA-256 digest (the photo and its thumbnail). This module reads
those names off a verified document and defines the folder layout of an export that carries its
files: `export.json` and `media/<digest>.<extension>`, the extension following the photo's type.

Nothing here logs. A digest is a name of owner data, so a message never quotes one.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import UUID

from sidekick.owner_export.catalogue import ExportRefused

PHOTO_COLLECTION = "journal_attachments"
EXPORT_DOCUMENT_NAME = "export.json"
EXPORT_MEDIA_FOLDER = "media"
EXTENSIONS: Mapping[str, str] = {"image/jpeg": "jpg", "image/webp": "webp"}
# The largest photo the store takes (a database CHECK says the same); a larger file is never read.
MAX_FILE_BYTES = 4 * 1024 * 1024
_DIGEST = re.compile(r"[0-9a-f]{64}")


class MediaFileMissing(ExportRefused):
    """A file the export refers to is not there, or no longer matches its name."""


@dataclass(frozen=True, slots=True)
class MediaFile:
    """One file of an export: its digest and the type of the photo it belongs to."""

    digest: str
    media_type: str
    # The size the photo row gives, for planning room; it is not part of what makes a file the same.
    size: int = field(default=0, compare=False)

    @property
    def export_name(self) -> str:
        return f"{self.digest}.{EXTENSIONS[self.media_type]}"


class MediaSource(Protocol):
    """Where the bytes of an export's files are read from (an export folder, or a backup)."""

    def read(self, owner_id: UUID, file: MediaFile) -> bytes:
        """The bytes of `file` of the export of `owner_id`; `MediaFileMissing` when unreadable."""
        ...


def media_files(document: Mapping[str, Any]) -> tuple[MediaFile, ...]:
    """The files the photo rows of a verified export name, each once, in digest order.

    A document of a format before 9 has no photo collection and names none.
    """

    collections = cast(Mapping[str, Any], document["collections"])
    found: dict[str, MediaFile] = {}
    for row in cast(list[Mapping[str, Any]], collections.get(PHOTO_COLLECTION, [])):
        media_type = row.get("media_type")
        if media_type not in EXTENSIONS:
            raise ExportRefused("export has a photo of an unsupported type")
        for digest_field, size_field in (
            ("content_digest", "byte_size"),
            ("thumb_digest", "thumb_size"),
        ):
            digest = row.get(digest_field)
            size = row.get(size_field)
            if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
                raise ExportRefused("export has a photo with an invalid digest")
            found.setdefault(
                digest,
                MediaFile(digest, cast(str, media_type), size if isinstance(size, int) else 0),
            )
    return tuple(found[digest] for digest in sorted(found))


def can_read(source: MediaSource, owner_id: UUID, file: MediaFile) -> bool:
    """Whether `source` gives the file's bytes, whole and matching their name."""

    try:
        source.read(owner_id, file)
    except MediaFileMissing:
        return False
    return True


def require_matching_bytes(file: MediaFile, data: bytes) -> bytes:
    """`data`, when it hashes to the file's name; otherwise `MediaFileMissing`."""

    if hashlib.sha256(data).hexdigest() != file.digest:
        raise MediaFileMissing("a photo file does not match its name")
    return data


class ExportMediaFolder:
    """The `media` folder of an export folder: plain files named `<digest>.<extension>`."""

    def __init__(self, folder: Path) -> None:
        self._folder = folder

    def read(self, owner_id: UUID, file: MediaFile) -> bytes:
        try:
            descriptor = os.open(self._folder / file.export_name, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError:  # missing, or a link put where a file belongs
            raise MediaFileMissing("a photo file is missing from the export folder") from None
        with os.fdopen(descriptor, "rb") as handle:
            data = handle.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise MediaFileMissing("a photo file is larger than any photo")
        return require_matching_bytes(file, data)
