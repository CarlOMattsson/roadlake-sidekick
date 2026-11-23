"""An owner export as a folder: `export.json` with the photo files beside it in `media/`.

This is how an export that carries its photos is written (export format 10): the document, and one
plain file per photo and thumbnail, named by digest and type. The folder is made here and must not
exist; everything in it is private to the user that made it.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import UUID

from sidekick.owner_export.catalogue import ExportRefused
from sidekick.owner_export.document import canonical_json, verify_export
from sidekick.owner_export.media import (
    EXPORT_DOCUMENT_NAME,
    EXPORT_MEDIA_FOLDER,
    MediaSource,
    media_files,
)

_FILE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW


def _write_new_file(path: Path, data: bytes) -> None:
    descriptor = os.open(path, _FILE_FLAGS, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def write_export_folder(
    folder: Path,
    document: Mapping[str, Any],
    media: MediaSource,
    recorded_missing: frozenset[tuple[UUID, str]] = frozenset(),
) -> dict[str, int]:
    """Create `folder` with the verified export and its photo files; counts of what was written.

    A file the backup recorded as already gone is left out. A file that should be readable and is
    not stops the export, and the half-made folder is removed again.
    """

    owner = verify_export(document).owner_id
    files = media_files(document)
    try:
        folder.mkdir(mode=0o700)  # an existing path is refused: nothing is ever overwritten
    except FileExistsError:
        raise ExportRefused("output folder already exists") from None
    try:
        _write_new_file(folder / EXPORT_DOCUMENT_NAME, canonical_json(dict(document)) + b"\n")
        (folder / EXPORT_MEDIA_FOLDER).mkdir(mode=0o700)
        written = left_out = 0
        for file in files:
            if (owner, file.digest) in recorded_missing:
                left_out += 1
                continue
            _write_new_file(
                folder / EXPORT_MEDIA_FOLDER / file.export_name, media.read(owner, file)
            )
            written += 1
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return {"media_files": written, "media_left_out": left_out}
