"""Journal photo files: immutable, named by their content, written atomically.

A file lives at `<root>/<owner key>/<first two hex of the digest>/<digest>`, where the owner key
is a 64-character hex token the caller derives from the owner (never the owner's id) and the digest
is the SHA-256 of the bytes. The same bytes are stored once per owner.

A write goes to a temporary file in `<root>/.incoming`, is flushed and fsynced, and is renamed into
place, so a reader sees a whole file or none. The caller then inserts its database row; a crash
between the two leaves a file without a row, which `sweep` removes once it is old enough and no row
or retained backup refers to it. Nothing here reads a photo: it holds bytes, and the format gate in
`sidekick.journal.domain.photo_format` has already judged them. Nothing here logs.
"""

import contextlib
import hashlib
import os
import re
import stat
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sidekick.shared.errors import NotFoundError

SWEEP_MIN_AGE = timedelta(hours=24)
_TOKEN = re.compile(r"[0-9a-f]{64}")
_INCOMING = ".incoming"
_FILE_MODE = 0o600
_DIRECTORY_MODE = 0o700
_CHUNK = 1024 * 1024


class MediaNotFoundError(NotFoundError):
    safe_title = "Photo not found"


@dataclass(frozen=True, slots=True)
class SweepResult:
    removed: int
    kept: int
    stale_incoming_removed: int


def _valid_token(value: str) -> str:
    if _TOKEN.fullmatch(value) is None:
        raise ValueError("a media key is 64 lowercase hex characters")
    return value


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _age_of(info: os.stat_result, now: datetime) -> timedelta:
    return now - datetime.fromtimestamp(info.st_mtime, UTC)


class MediaStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, owner_key: str, digest: str) -> Path:
        _valid_token(owner_key)
        _valid_token(digest)
        return self._root / owner_key / digest[:2] / digest

    def put(self, owner_key: str, data: bytes) -> str:
        """Store `data` and return its SHA-256 hex digest. Safe to repeat.

        Storing bytes that are already there refreshes the file's age, so a sweep that is running
        cannot remove them between this call and the caller's row insert.
        """

        digest = hashlib.sha256(data).hexdigest()
        final = self._path(owner_key, digest)
        if self._touch_existing(final):
            return digest
        incoming = self._root / _INCOMING
        self._private_directory(incoming)
        temporary = incoming / uuid.uuid4().hex
        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, _FILE_MODE
        )
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            self._private_directory(final.parent)
            os.replace(temporary, final)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        _fsync_directory(final.parent)
        return digest

    def _private_directory(self, path: Path) -> None:
        """Create `path` and every missing level below the root with mode 0700.

        `mkdir(parents=True)` applies the mode to the last level only, so each level is made on its
        own.
        """

        self._root.mkdir(mode=_DIRECTORY_MODE, parents=True, exist_ok=True)
        current = self._root
        for part in path.relative_to(self._root).parts:
            current = current / part
            current.mkdir(mode=_DIRECTORY_MODE, exist_ok=True)

    def _touch_existing(self, path: Path) -> bool:
        try:
            if not stat.S_ISREG(path.lstat().st_mode):
                return False
            os.utime(path, follow_symlinks=False)
        except FileNotFoundError:
            return False
        return True

    def exists(self, owner_key: str, digest: str) -> bool:
        try:
            return stat.S_ISREG(self._path(owner_key, digest).lstat().st_mode)
        except FileNotFoundError:
            return False

    def read(self, owner_key: str, digest: str) -> bytes:
        path = self._path(owner_key, digest)
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError:  # missing, or a symlink put where a file belongs
            raise MediaNotFoundError("photo file not found") from None
        with os.fdopen(descriptor, "rb") as handle:
            return handle.read()

    def verify(self, owner_key: str, digest: str) -> bool:
        """True when the file exists and its bytes hash to its name."""

        try:
            data = self.read(owner_key, digest)
        except MediaNotFoundError:
            return False
        return hashlib.sha256(data).hexdigest() == digest

    def remove(self, owner_key: str, digest: str) -> bool:
        """Delete one file; True if there was one. The caller has removed the last row first."""

        try:
            self._path(owner_key, digest).unlink()
        except FileNotFoundError:
            return False
        return True

    def blobs(self) -> Iterator[tuple[str, str]]:
        """Every stored file as (owner key, digest); anything not named like a file is skipped."""

        for owner in self._directories(self._root, lambda name: _TOKEN.fullmatch(name) is not None):
            for prefix in self._directories(owner, lambda name: re.fullmatch(r"[0-9a-f]{2}", name)):
                for entry in self._entries(prefix):
                    if self._is_blob(entry, prefix.name):
                        yield owner.name, entry.name

    def sweep(
        self,
        keep: Callable[[str, str], bool],
        now: datetime,
        min_age: timedelta = SWEEP_MIN_AGE,
    ) -> SweepResult:
        """Remove files nothing refers to. Only a file older than `min_age` is ever judged.

        `keep(owner_key, digest)` is the caller's answer to "does a row, or a retained backup, refer
        to this file". It is asked only about old files. Anything that is not a regular file of the
        expected name is left alone, and a symlink is never followed. A file whose age changed since
        it was judged (a repeated `put`) is kept.
        """

        removed = kept = 0
        for owner in self._directories(self._root, lambda name: _TOKEN.fullmatch(name) is not None):
            for prefix in self._directories(owner, lambda name: re.fullmatch(r"[0-9a-f]{2}", name)):
                for entry in self._entries(prefix):
                    if not self._is_blob(entry, prefix.name):
                        continue
                    try:
                        info = entry.stat(follow_symlinks=False)
                    except FileNotFoundError:
                        continue  # removed by a concurrent remove or sweep
                    if _age_of(info, now) < min_age or keep(owner.name, entry.name):
                        kept += 1
                    elif self._remove_if_unchanged(Path(entry.path), info):
                        removed += 1
                    else:
                        kept += 1
        return SweepResult(removed, kept, self._sweep_incoming(now, min_age))

    def _sweep_incoming(self, now: datetime, min_age: timedelta) -> int:
        removed = 0
        for entry in self._entries(self._root / _INCOMING):
            if not entry.is_file(follow_symlinks=False):
                continue
            try:
                info = entry.stat(follow_symlinks=False)
                if _age_of(info, now) >= min_age:
                    Path(entry.path).unlink()  # an old temporary file belongs to no running write
                    removed += 1
            except FileNotFoundError:
                continue
        return removed

    @staticmethod
    def _is_blob(entry: os.DirEntry[str], prefix: str) -> bool:
        return (
            entry.is_file(follow_symlinks=False)
            and _TOKEN.fullmatch(entry.name) is not None
            and entry.name[:2] == prefix
        )

    def _remove_if_unchanged(self, path: Path, judged: os.stat_result) -> bool:
        """Remove `path` unless a repeated `put` touched it after it was judged.

        The file is first renamed into quarantine, which is atomic. A `put` that comes after the
        rename finds nothing at `path` and writes a new file; a `put` that came before it changed
        the modification time of the file that was moved, which is checked here, and the file is
        then put back (or dropped when a new copy has been written meanwhile).
        """

        self._private_directory(self._root / _INCOMING)
        quarantine = self._root / _INCOMING / f"swept-{uuid.uuid4().hex}"
        try:
            os.rename(path, quarantine)
        except FileNotFoundError:
            return False
        if quarantine.lstat().st_mtime_ns == judged.st_mtime_ns:
            quarantine.unlink()
            return True
        # FileExistsError: a new copy was written after the move, so this one is not needed.
        with contextlib.suppress(FileExistsError):
            os.link(quarantine, path)
        quarantine.unlink()
        return False

    @staticmethod
    def _entries(directory: Path) -> list[os.DirEntry[str]]:
        try:
            with os.scandir(directory) as scanning:
                return list(scanning)
        except (FileNotFoundError, NotADirectoryError):
            return []

    @classmethod
    def _directories(cls, directory: Path, accepts: Callable[[str], object]) -> list[Path]:
        return [
            Path(entry.path)
            for entry in cls._entries(directory)
            if entry.is_dir(follow_symlinks=False) and accepts(entry.name)
        ]
