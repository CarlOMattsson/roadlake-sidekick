"""The photo file store: content-addressed, atomic, per owner, swept only when unreferenced."""

import hashlib
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sidekick.journal.infrastructure.media_store import (
    SWEEP_MIN_AGE,
    MediaNotFoundError,
    MediaStore,
)

OWNER = hashlib.sha256(b"owner one").hexdigest()
OTHER = hashlib.sha256(b"owner two").hexdigest()
PHOTO = b"\xff\xd8\xff photo bytes"


def digest_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def age(path: Path, by: timedelta) -> None:
    moment = (datetime.now(UTC) - by).timestamp()
    os.utime(path, (moment, moment), follow_symlinks=False)


@pytest.fixture
def store(tmp_path: Path) -> MediaStore:
    return MediaStore(tmp_path / "media")


def blob_path(root: Path, owner: str, data: bytes) -> Path:
    digest = digest_of(data)
    return root / owner / digest[:2] / digest


def test_a_file_is_named_by_its_content_under_its_owner(store: MediaStore, tmp_path: Path) -> None:
    digest = store.put(OWNER, PHOTO)
    assert digest == digest_of(PHOTO)
    path = blob_path(tmp_path / "media", OWNER, PHOTO)
    assert path.read_bytes() == PHOTO
    assert store.read(OWNER, digest) == PHOTO
    assert store.exists(OWNER, digest)
    assert store.verify(OWNER, digest)


def test_files_and_directories_are_private_to_the_service(
    store: MediaStore, tmp_path: Path
) -> None:
    store.put(OWNER, PHOTO)
    path = blob_path(tmp_path / "media", OWNER, PHOTO)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_every_directory_level_is_private(store: MediaStore, tmp_path: Path) -> None:
    store.put(OWNER, PHOTO)
    root = tmp_path / "media"
    path = blob_path(root, OWNER, PHOTO)
    for directory in (root, root / ".incoming", root / OWNER, path.parent):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700


def test_the_same_bytes_are_stored_once_and_a_repeat_changes_nothing(
    store: MediaStore, tmp_path: Path
) -> None:
    first = store.put(OWNER, PHOTO)
    second = store.put(OWNER, PHOTO)
    assert first == second
    files = [path for path in (tmp_path / "media").rglob("*") if path.is_file()]
    assert files == [blob_path(tmp_path / "media", OWNER, PHOTO)]


def test_another_owner_does_not_see_the_file(store: MediaStore) -> None:
    digest = store.put(OWNER, PHOTO)
    assert not store.exists(OTHER, digest)
    with pytest.raises(MediaNotFoundError):
        store.read(OTHER, digest)


def test_a_write_leaves_no_temporary_file(store: MediaStore, tmp_path: Path) -> None:
    store.put(OWNER, PHOTO)
    assert list((tmp_path / "media" / ".incoming").iterdir()) == []


def test_a_failed_write_leaves_no_file_and_no_temporary_file(
    store: MediaStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_: object, **__: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError, match="disk full"):
        store.put(OWNER, PHOTO)
    monkeypatch.undo()
    assert not store.exists(OWNER, digest_of(PHOTO))
    assert list((tmp_path / "media" / ".incoming").iterdir()) == []


@pytest.mark.parametrize(
    "bad", ["", "abc", "../" * 20, "A" * 64, "g" * 64, ("a" * 64) + "\n", "a" * 63, "a" * 65]
)
def test_a_key_that_is_not_a_digest_is_refused_before_any_path_is_built(
    store: MediaStore, bad: str
) -> None:
    for call in (
        lambda: store.exists(bad, digest_of(PHOTO)),
        lambda: store.exists(OWNER, bad),
        lambda: store.read(OWNER, bad),
        lambda: store.remove(bad, digest_of(PHOTO)),
        lambda: store.put(bad, PHOTO),
    ):
        with pytest.raises(ValueError, match="media key"):
            call()


def test_a_symlink_where_a_file_belongs_is_not_followed(store: MediaStore, tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_bytes(b"not a photo")
    digest = digest_of(PHOTO)
    link = blob_path(tmp_path / "media", OWNER, PHOTO)
    link.parent.mkdir(parents=True)
    link.symlink_to(secret)
    assert not store.exists(OWNER, digest)
    with pytest.raises(MediaNotFoundError):
        store.read(OWNER, digest)


def test_verify_notices_a_file_that_changed_and_a_file_that_is_gone(
    store: MediaStore, tmp_path: Path
) -> None:
    digest = store.put(OWNER, PHOTO)
    blob_path(tmp_path / "media", OWNER, PHOTO).write_bytes(PHOTO + b"!")
    assert not store.verify(OWNER, digest)
    assert store.remove(OWNER, digest)
    assert not store.remove(OWNER, digest)
    assert not store.verify(OWNER, digest)


# Sweep ---------------------------------------------------------------------------------------


def test_sweep_removes_an_old_file_nothing_refers_to(store: MediaStore, tmp_path: Path) -> None:
    store.put(OWNER, PHOTO)
    path = blob_path(tmp_path / "media", OWNER, PHOTO)
    age(path, SWEEP_MIN_AGE + timedelta(minutes=1))
    result = store.sweep(lambda *_: False, datetime.now(UTC))
    assert (result.removed, result.kept) == (1, 0)
    assert not path.exists()


def test_sweep_keeps_a_file_that_a_row_or_a_retained_backup_refers_to(
    store: MediaStore, tmp_path: Path
) -> None:
    store.put(OWNER, PHOTO)
    path = blob_path(tmp_path / "media", OWNER, PHOTO)
    age(path, timedelta(days=30))
    asked: list[tuple[str, str]] = []

    def keep(owner: str, digest: str) -> bool:
        asked.append((owner, digest))
        return True

    result = store.sweep(keep, datetime.now(UTC))
    assert (result.removed, result.kept) == (0, 1)
    assert path.exists()
    assert asked == [(OWNER, digest_of(PHOTO))]


def test_sweep_never_judges_a_file_younger_than_a_day(store: MediaStore, tmp_path: Path) -> None:
    store.put(OWNER, PHOTO)
    path = blob_path(tmp_path / "media", OWNER, PHOTO)
    age(path, SWEEP_MIN_AGE - timedelta(minutes=1))

    def never(*_: str) -> bool:
        raise AssertionError("a young file must not be judged")

    result = store.sweep(never, datetime.now(UTC))
    assert (result.removed, result.kept) == (0, 1)
    assert path.exists()


def test_storing_old_bytes_again_makes_them_young_so_a_sweep_spares_them(
    store: MediaStore, tmp_path: Path
) -> None:
    store.put(OWNER, PHOTO)
    path = blob_path(tmp_path / "media", OWNER, PHOTO)
    age(path, timedelta(days=3))
    store.put(OWNER, PHOTO)
    result = store.sweep(lambda *_: False, datetime.now(UTC))
    assert result.removed == 0
    assert path.exists()


def test_sweep_spares_a_file_that_was_stored_again_while_it_was_being_judged(
    store: MediaStore, tmp_path: Path
) -> None:
    store.put(OWNER, PHOTO)
    path = blob_path(tmp_path / "media", OWNER, PHOTO)
    age(path, timedelta(days=3))

    def keep_after_a_repeat(owner: str, digest: str) -> bool:
        store.put(owner, PHOTO)
        return False

    result = store.sweep(keep_after_a_repeat, datetime.now(UTC))
    assert result.removed == 0
    assert path.exists()


def test_sweep_skips_a_file_that_vanishes_while_it_is_being_listed(
    store: MediaStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.put(OWNER, PHOTO)
    path = blob_path(tmp_path / "media", OWNER, PHOTO)
    age(path, timedelta(days=3))

    class Vanished:
        def __init__(self, entry: os.DirEntry[str]) -> None:
            self.name, self.path = entry.name, entry.path

        def is_file(self, *, follow_symlinks: bool) -> bool:
            return True

        def stat(self, *, follow_symlinks: bool) -> os.stat_result:
            raise FileNotFoundError(self.path)

    real = MediaStore._entries

    def listing(directory: Path) -> list:  # type: ignore[type-arg]
        return [Vanished(e) if e.name == digest_of(PHOTO) else e for e in real(directory)]

    monkeypatch.setattr(MediaStore, "_entries", staticmethod(listing))
    result = store.sweep(lambda *_: False, datetime.now(UTC))
    assert (result.removed, result.kept) == (0, 0)


def test_a_put_that_lands_right_after_the_sweep_moved_the_file_writes_a_new_one(
    store: MediaStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.put(OWNER, PHOTO)
    path = blob_path(tmp_path / "media", OWNER, PHOTO)
    age(path, timedelta(days=3))
    real_rename = os.rename

    def rename_then_put(source: Path, target: Path) -> None:
        real_rename(source, target)
        store.put(OWNER, PHOTO)  # the owner uploads the same photo at this instant

    monkeypatch.setattr(os, "rename", rename_then_put)
    store.sweep(lambda *_: False, datetime.now(UTC))
    monkeypatch.undo()
    assert path.read_bytes() == PHOTO
    assert store.verify(OWNER, digest_of(PHOTO))
    assert list((tmp_path / "media" / ".incoming").iterdir()) == []


def test_a_file_touched_before_the_move_is_put_back(
    store: MediaStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.put(OWNER, PHOTO)
    path = blob_path(tmp_path / "media", OWNER, PHOTO)
    age(path, timedelta(days=3))
    real_rename = os.rename

    def touch_then_rename(source: Path, target: Path) -> None:
        store.put(OWNER, PHOTO)  # touches the file just before it is moved
        real_rename(source, target)

    monkeypatch.setattr(os, "rename", touch_then_rename)
    result = store.sweep(lambda *_: False, datetime.now(UTC))
    monkeypatch.undo()
    assert result.removed == 0
    assert path.read_bytes() == PHOTO
    assert list((tmp_path / "media" / ".incoming").iterdir()) == []


def test_sweep_only_touches_regular_files_of_the_expected_name(
    store: MediaStore, tmp_path: Path
) -> None:
    store.put(OWNER, PHOTO)
    root = tmp_path / "media"
    path = blob_path(root, OWNER, PHOTO)
    stranger = path.parent / "notes.txt"
    stranger.write_text("keep")
    wrong_prefix = root / OWNER / "ff" / digest_of(PHOTO)
    wrong_prefix.parent.mkdir()
    wrong_prefix.write_bytes(b"misfiled")
    outside = tmp_path / "outside"
    outside.write_bytes(b"outside")
    link = path.parent / digest_of(b"link")
    link.symlink_to(outside)
    (root / "not-an-owner").mkdir()
    (root / "not-an-owner" / "ab").mkdir()
    for old in (path, stranger, wrong_prefix, outside):
        age(old, timedelta(days=9))
    age(link, timedelta(days=9))
    result = store.sweep(lambda *_: False, datetime.now(UTC))
    assert result.removed == 1
    assert not path.exists()
    assert stranger.exists() and wrong_prefix.exists() and outside.exists() and link.is_symlink()


def test_sweep_removes_stale_temporary_files_from_a_crashed_write(
    store: MediaStore, tmp_path: Path
) -> None:
    store.put(OWNER, PHOTO)
    stale = tmp_path / "media" / ".incoming" / "crashed"
    stale.write_bytes(b"half")
    fresh = tmp_path / "media" / ".incoming" / "running"
    fresh.write_bytes(b"in progress")
    age(stale, timedelta(days=2))
    result = store.sweep(lambda *_: True, datetime.now(UTC))
    assert result.stale_incoming_removed == 1
    assert not stale.exists() and fresh.exists()


def test_sweep_of_a_store_that_was_never_written_is_empty(tmp_path: Path) -> None:
    result = MediaStore(tmp_path / "never").sweep(lambda *_: False, datetime.now(UTC))
    assert (result.removed, result.kept, result.stale_incoming_removed) == (0, 0, 0)


def test_the_media_directory_setting_has_a_default_and_can_be_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sidekick.shared.config import Settings

    monkeypatch.delenv("SIDEKICK_MEDIA_DIRECTORY", raising=False)
    assert Settings(_env_file=None).media_directory == Path(".sidekick/media")  # type: ignore[call-arg]
    monkeypatch.setenv("SIDEKICK_MEDIA_DIRECTORY", str(tmp_path))
    assert Settings(_env_file=None).media_directory == tmp_path  # type: ignore[call-arg]
