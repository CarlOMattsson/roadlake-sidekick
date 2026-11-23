"""The photo files of a backup: one encrypted file each, in a folder beside the backup files.

An owner backup (`.skbackup`) holds the rows of the photos; their bytes are kept in
`<backup directory>/media/`, each file as its own Fernet token (a photo is at most 4 MiB, so one
token fits in memory like the bundle does). A file is named by a keyed hash of the owner and the
photo's digest, so the folder names neither an owner nor a photo to anyone without the backup key.

The folder is incremental: a backup stores only files it does not have yet. Every backup touches the
files it lists, so a file whose modification time is older than the oldest backup that is kept is
listed by no kept backup and may go (`remove_unlisted`). Nothing here logs or names a digest.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import shutil
import stat
import uuid
from collections.abc import Collection, Iterable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken

from sidekick.owner_export.catalogue import ExportRefused
from sidekick.owner_export.media import (
    MAX_FILE_BYTES,
    MediaFile,
    MediaFileMissing,
    media_files,
    require_matching_bytes,
)
from sidekick.shared.errors import NotFoundError

MEDIA_FOLDER = "media"
_INCOMING = ".incoming"
_LABEL = b"sidekick.backup-media.v1:"
# A Fernet token is the file plus a padding block, a header and a MAC, in base64.
_TOKEN_LIMIT = (MAX_FILE_BYTES + 16 + 73) * 4 // 3 + 4
_FILE_MODE = 0o600
_DIRECTORY_MODE = 0o700


def backup_media_directory(backup_directory: Path) -> Path:
    return backup_directory / MEDIA_FOLDER


@dataclass(frozen=True, slots=True)
class MediaReference:
    """A file a backup lists: whose it is and which file it is."""

    owner_id: UUID
    file: MediaFile


class BackupMediaStore:
    """The encrypted photo files next to a backup, read and written whole, one at a time."""

    def __init__(self, folder: Path, fernet: Fernet, name_key: bytes) -> None:
        self._folder = folder
        self._fernet = fernet
        self._name_key = name_key

    def name_of(self, owner_id: UUID, digest: str) -> str:
        message = _LABEL + owner_id.bytes + digest.encode("ascii")
        return hmac.new(self._name_key, message, hashlib.sha256).hexdigest()

    def _path(self, owner_id: UUID, digest: str) -> Path:
        name = self.name_of(owner_id, digest)
        return self._folder / name[:2] / name

    def has(self, owner_id: UUID, digest: str) -> bool:
        try:
            return stat.S_ISREG(self._path(owner_id, digest).lstat().st_mode)
        except FileNotFoundError:
            return False

    def touch(self, owner_id: UUID, digest: str, when: datetime) -> bool:
        """Mark a stored file as listed by a backup made at `when`; False if there is no file.

        The time only ever rises: an older backup, or a clock set back, never makes a file look
        unlisted to a newer backup that is kept.
        """

        path = self._path(owner_id, digest)
        try:
            stamp = max(path.lstat().st_mtime, when.timestamp())
            os.utime(path, (stamp, stamp), follow_symlinks=False)
        except FileNotFoundError:
            return False
        return True

    def put(self, owner_id: UUID, file: MediaFile, data: bytes, when: datetime) -> None:
        """Encrypt and store a file atomically, then read it back. A file already under the name is
        replaced; the caller stores only files the folder does not have."""

        require_matching_bytes(file, data)
        token = self._fernet.encrypt(data)
        final = self._path(owner_id, file.digest)
        self._private_directory(final.parent)
        self._private_directory(self._folder / _INCOMING)
        temporary = self._folder / _INCOMING / uuid.uuid4().hex
        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, _FILE_MODE
        )
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(token)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, final)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        directory = os.open(final.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        self.touch(owner_id, file.digest, when)
        self.read(owner_id, file)  # what was written is what was meant

    def read(self, owner_id: UUID, file: MediaFile) -> bytes:
        """The decrypted bytes of a file; `MediaFileMissing` when absent, damaged or not a match."""

        try:
            descriptor = os.open(self._path(owner_id, file.digest), os.O_RDONLY | os.O_NOFOLLOW)
        except OSError:
            raise MediaFileMissing("a photo file is missing from the backup") from None
        with os.fdopen(descriptor, "rb") as handle:
            token = handle.read(_TOKEN_LIMIT + 1)
        if len(token) > _TOKEN_LIMIT:
            raise MediaFileMissing("a photo file in the backup is damaged")
        try:
            data = self._fernet.decrypt(token)
        except InvalidToken:
            raise MediaFileMissing("a photo file in the backup is damaged") from None
        return require_matching_bytes(file, data)

    def remove_unlisted(self, oldest_kept: datetime) -> int:
        """Delete the files no backup that is kept can list; how many went.

        Every backup touches the files it lists, so one touched before the oldest kept backup was
        made belongs to none of the kept ones.
        """

        cutoff = oldest_kept.timestamp()
        removed = 0
        for prefix in _entries(self._folder):
            if not prefix.is_dir(follow_symlinks=False) or prefix.name == _INCOMING:
                continue
            for entry in _entries(Path(prefix.path)):
                with suppress(FileNotFoundError):
                    if entry.is_file(follow_symlinks=False) and entry.stat().st_mtime < cutoff:
                        Path(entry.path).unlink()
                        removed += 1
        self._remove_stale_incoming(cutoff)
        return removed

    def _remove_stale_incoming(self, cutoff: float) -> None:
        for entry in _entries(self._folder / _INCOMING):
            with suppress(FileNotFoundError):
                if entry.is_file(follow_symlinks=False) and entry.stat().st_mtime < cutoff:
                    Path(entry.path).unlink()

    def _private_directory(self, path: Path) -> None:
        self._folder.mkdir(mode=_DIRECTORY_MODE, parents=True, exist_ok=True)
        current = self._folder
        for part in path.relative_to(self._folder).parts:
            current = current / part
            current.mkdir(mode=_DIRECTORY_MODE, exist_ok=True)


def _entries(directory: Path) -> list[os.DirEntry[str]]:
    try:
        with os.scandir(directory) as scanning:
            return list(scanning)
    except (FileNotFoundError, NotADirectoryError):
        return []


@dataclass(frozen=True, slots=True)
class MediaCheck:
    """What a look at the photo files of a backup found; counts only."""

    listed: int
    readable: int
    recorded_missing: int
    unreadable: int

    @property
    def sound(self) -> bool:
        return self.unreadable == 0


def check_media(
    store: BackupMediaStore,
    references: Iterable[MediaReference],
    recorded_missing: Collection[tuple[UUID, str]] = (),
) -> MediaCheck:
    """Read and verify every listed file once. A file the backup recorded as absent at the time
    it was made is not an error; a file that should be there and is not, or is damaged, is."""

    listed = readable = recorded = unreadable = 0
    for reference in references:
        listed += 1
        if (reference.owner_id, reference.file.digest) in recorded_missing:
            recorded += 1
            continue
        try:
            store.read(reference.owner_id, reference.file)
            readable += 1
        except MediaFileMissing:
            unreadable += 1
    return MediaCheck(listed, readable, recorded, unreadable)


class PhotoFileSource(Protocol):
    """The live photo files of the instance (`OwnerPhotoFiles`), read by owner id."""

    def read(self, owner_id: UUID, digest: str) -> bytes:
        """The bytes of a file; a `NotFoundError` when it is missing or no longer matches."""
        ...


@dataclass(frozen=True, slots=True)
class MediaCopy:
    """What copying the photo files into a backup did: counts, and the files that were gone."""

    stored: int
    reused: int
    missing: tuple[tuple[UUID, str], ...]


def _owner_of(export: Mapping[str, Any]) -> UUID:
    return UUID(str(export["owner_id"]))


def ensure_room_for(directory: Path, needed_bytes: int) -> None:
    """Refuse before any file is written when the disk cannot take `needed_bytes` more."""

    probe = directory
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        free = shutil.disk_usage(probe).free
    except OSError as error:
        raise ExportRefused("cannot determine free disk space for the backup") from error
    if free < needed_bytes:
        raise ExportRefused(
            f"not enough free disk space for the photo files: {free} bytes free, "
            f"{needed_bytes} needed"
        )


def copy_media(
    store: BackupMediaStore,
    source: PhotoFileSource,
    exports: Sequence[Mapping[str, Any]],
    *,
    when: datetime,
    media_directory: Path,
) -> MediaCopy:
    """Bring every file the exports list into the backup folder, and mark all of them as listed.

    A file the folder has is only touched. A new one is read from the live files, encrypted and
    read back. One that the live files no longer have is recorded as missing and does not stop the
    backup: the rows are still worth keeping, and `sidekick-admin media verify` is where the
    operator learns of the loss.
    """

    wanted = [(_owner_of(export), file) for export in exports for file in media_files(export)]
    absent = {(owner, file) for owner, file in wanted if not store.has(owner, file.digest)}
    # Fernet and base64 make a stored file about a third larger than the photo.
    ensure_room_for(media_directory, sum(file.size * 4 // 3 + 256 for _, file in absent))
    stored = reused = 0
    missing: list[tuple[UUID, str]] = []
    for owner, file in wanted:
        if (owner, file) not in absent and store.touch(owner, file.digest, when):
            reused += 1
            continue
        try:
            data = source.read(owner, file.digest)
        except NotFoundError:
            missing.append((owner, file.digest))
            continue
        store.put(owner, file, data, when)
        stored += 1
    return MediaCopy(
        stored, reused, tuple(sorted(missing, key=lambda pair: (str(pair[0]), pair[1])))
    )
