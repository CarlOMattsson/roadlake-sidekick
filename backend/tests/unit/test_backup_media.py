"""The photo files of a backup and of an export folder: encrypted one by one, named by a keyed
hash, copied incrementally, and read back only when they still match their name."""

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from cryptography.fernet import Fernet

from sidekick.backup.bundle import (
    build_backup_bundle,
    build_backup_envelope,
    decrypt_backup_envelope,
    open_media_store,
    recorded_missing_files,
)
from sidekick.backup.export_folder import write_export_folder
from sidekick.backup.media import MediaReference, check_media, copy_media
from sidekick.journal.infrastructure.media_files import OwnerPhotoFiles
from sidekick.journal.infrastructure.media_store import MediaNotFoundError
from sidekick.owner_export import cli as owner_export_cli
from sidekick.owner_export.catalogue import EXPORT_SOURCES, SOURCES_BY_NAME, ExportRefused
from sidekick.owner_export.document import (
    build_export_document,
    export_checksum,
    verify_export,
)
from sidekick.owner_export.media import (
    ExportMediaFolder,
    MediaFile,
    MediaFileMissing,
    media_files,
)
from tests.support import photo_files
from tests.support.older_export_formats import as_format_8, as_format_9

OWNER = UUID("00000000-0000-7000-8000-000000000001")
OTHER = UUID("00000000-0000-7000-8000-000000000002")
# Well ahead of the real time the test files are written at: a file's listed time never falls.
WHEN = datetime(2100, 1, 1, 12, 0, tzinfo=UTC)
KEY = Fernet.generate_key()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


PHOTO = photo_files.jpeg(640, 480)
THUMB = photo_files.jpeg(320, 240)
SECOND = photo_files.jpeg(800, 600)
SECOND_THUMB = photo_files.jpeg(300, 200)


def attachment(
    photo: bytes, thumb: bytes, *, owner: UUID = OWNER, number: int = 1
) -> dict[str, Any]:
    row: dict[str, Any] = dict.fromkeys(
        SOURCES_BY_NAME["journal_attachments"].row_type.__table__.c.keys()
    )
    row.update(
        id=f"00000000-0000-7000-8000-0000000001{number:02d}",
        owner_id=str(owner),
        journal_date="2026-11-22",
        media_type="image/jpeg",
        byte_size=len(photo),
        width=640,
        height=480,
        content_digest=digest(photo),
        thumb_digest=digest(thumb),
        thumb_size=len(thumb),
        position=number,
        version=1,
        created_at=WHEN.isoformat(),
        updated_at=WHEN.isoformat(),
    )
    return row


def export_with(*rows: dict[str, Any], owner: UUID = OWNER) -> dict[str, Any]:
    collections: dict[str, list[dict[str, Any]]] = {source.name: [] for source in EXPORT_SOURCES}
    collections["journal_attachments"] = list(rows)
    return build_export_document(owner, collections, exported_at=WHEN)  # type: ignore[arg-type]


class LiveFiles:
    """Stands in for the instance's photo files: a dict by (owner, digest)."""

    def __init__(self, *items: tuple[UUID, bytes]) -> None:
        self.files = {(owner, digest(data)): data for owner, data in items}
        self.reads = 0

    def read(self, owner_id: UUID, digest: str) -> bytes:
        self.reads += 1
        try:
            return self.files[(owner_id, digest)]
        except KeyError:
            raise MediaNotFoundError("gone") from None


def test_an_export_names_each_file_once_with_the_type_of_its_photo() -> None:
    one = attachment(PHOTO, THUMB, number=1)
    again = attachment(PHOTO, THUMB, number=2)  # the same bytes on a second row

    files = media_files(export_with(one, again))

    assert {file.digest for file in files} == {digest(PHOTO), digest(THUMB)}
    assert len(files) == 2
    assert {file.media_type for file in files} == {"image/jpeg"}
    assert {file.export_name for file in files} == {f"{digest(PHOTO)}.jpg", f"{digest(THUMB)}.jpg"}
    assert {file.size for file in files} == {len(PHOTO), len(THUMB)}


def test_a_backup_file_is_encrypted_named_by_a_keyed_hash_and_read_back_whole(
    tmp_path: Path,
) -> None:
    store = open_media_store(tmp_path, KEY)
    file = MediaFile(digest(PHOTO), "image/jpeg")

    store.put(OWNER, file, PHOTO, WHEN)

    (stored,) = [path for path in tmp_path.rglob("*") if path.is_file()]
    assert PHOTO not in stored.read_bytes()
    assert digest(PHOTO) not in stored.name and str(OWNER) not in stored.name
    assert stored.name == store.name_of(OWNER, file.digest)
    assert stored.stat().st_mode & 0o777 == 0o600
    assert store.read(OWNER, file) == PHOTO
    assert store.has(OWNER, file.digest) and not store.has(OTHER, file.digest)


def test_the_file_name_depends_on_the_owner_and_on_the_backup_key(tmp_path: Path) -> None:
    first = open_media_store(tmp_path, KEY)
    second = open_media_store(tmp_path, Fernet.generate_key())

    assert first.name_of(OWNER, digest(PHOTO)) != first.name_of(OTHER, digest(PHOTO))
    assert first.name_of(OWNER, digest(PHOTO)) != second.name_of(OWNER, digest(PHOTO))


def test_a_file_that_is_damaged_missing_or_read_with_another_key_is_never_returned(
    tmp_path: Path,
) -> None:
    store = open_media_store(tmp_path, KEY)
    file = MediaFile(digest(PHOTO), "image/jpeg")
    store.put(OWNER, file, PHOTO, WHEN)
    (stored,) = [path for path in tmp_path.rglob("*") if path.is_file()]

    with pytest.raises(MediaFileMissing):
        open_media_store(tmp_path, Fernet.generate_key()).read(OWNER, file)
    with pytest.raises(MediaFileMissing):
        store.read(OTHER, file)
    stored.write_bytes(stored.read_bytes()[:-8] + b"AAAAAAAA")
    with pytest.raises(MediaFileMissing):
        store.read(OWNER, file)


def test_a_file_whose_bytes_do_not_match_its_name_is_refused_on_the_way_in(
    tmp_path: Path,
) -> None:
    store = open_media_store(tmp_path, KEY)

    with pytest.raises(MediaFileMissing):
        store.put(OWNER, MediaFile(digest(PHOTO), "image/jpeg"), THUMB, WHEN)
    assert [path for path in tmp_path.rglob("*") if path.is_file()] == []


def test_files_older_than_the_oldest_kept_backup_go_and_the_listed_ones_stay(
    tmp_path: Path,
) -> None:
    store = open_media_store(tmp_path, KEY)
    old = MediaFile(digest(PHOTO), "image/jpeg")
    kept = MediaFile(digest(THUMB), "image/jpeg")
    store.put(OWNER, old, PHOTO, WHEN)
    store.put(OWNER, kept, THUMB, WHEN)
    later = WHEN + timedelta(days=3)
    assert store.touch(OWNER, kept.digest, later)  # a later backup lists it again

    removed = store.remove_unlisted(WHEN + timedelta(days=1))

    assert removed == 1
    assert not store.has(OWNER, old.digest)
    assert store.has(OWNER, kept.digest)
    assert not store.touch(OWNER, old.digest, later)


def test_a_second_backup_copies_only_files_it_does_not_have_and_marks_all_as_listed(
    tmp_path: Path,
) -> None:
    store = open_media_store(tmp_path, KEY)
    live = LiveFiles((OWNER, PHOTO), (OWNER, THUMB))
    exports = [export_with(attachment(PHOTO, THUMB))]

    first = copy_media(store, live, exports, when=WHEN, media_directory=tmp_path)
    reads_after_first = live.reads
    again = copy_media(
        store, live, exports, when=WHEN + timedelta(hours=1), media_directory=tmp_path
    )

    assert (first.stored, first.reused, first.missing) == (2, 0, ())
    assert (again.stored, again.reused, again.missing) == (0, 2, ())
    assert live.reads == reads_after_first  # nothing was read for the files it already had
    mtimes = {path.stat().st_mtime for path in tmp_path.rglob("*") if path.is_file()}
    assert mtimes == {(WHEN + timedelta(hours=1)).timestamp()}


def test_a_file_the_instance_has_lost_is_recorded_and_does_not_stop_the_copy(
    tmp_path: Path,
) -> None:
    store = open_media_store(tmp_path, KEY)
    live = LiveFiles((OWNER, PHOTO))  # the thumbnail is gone
    exports = [export_with(attachment(PHOTO, THUMB))]

    copied = copy_media(store, live, exports, when=WHEN, media_directory=tmp_path)

    assert (copied.stored, copied.missing) == (1, ((OWNER, digest(THUMB)),))
    check = check_media(
        store,
        [MediaReference(OWNER, file) for file in media_files(exports[0])],
        {(OWNER, digest(THUMB))},
    )
    assert (check.listed, check.readable, check.recorded_missing, check.sound) == (2, 1, 1, True)


def test_a_backup_check_finds_a_file_that_should_be_there_and_is_not(tmp_path: Path) -> None:
    store = open_media_store(tmp_path, KEY)
    live = LiveFiles((OWNER, PHOTO), (OWNER, THUMB))
    exports = [export_with(attachment(PHOTO, THUMB))]
    copy_media(store, live, exports, when=WHEN, media_directory=tmp_path)
    next(path for path in tmp_path.rglob("*") if path.is_file()).unlink()

    check = check_media(store, [MediaReference(OWNER, f) for f in media_files(exports[0])])

    assert (check.readable, check.unreadable, check.sound) == (1, 1, False)


def test_the_bundle_keeps_the_list_of_lost_files_inside_the_ciphertext() -> None:
    export = export_with(attachment(PHOTO, THUMB))
    missing = [[str(OWNER), digest(THUMB)]]

    bundle = build_backup_bundle([export], missing)
    envelope = build_backup_envelope(bundle, KEY, created_at=WHEN)
    opened = decrypt_backup_envelope(envelope, KEY)

    assert digest(THUMB) not in json.dumps(envelope)
    assert recorded_missing_files(opened) == {(OWNER, digest(THUMB))}
    assert "media_missing" not in build_backup_bundle([export])


@pytest.mark.parametrize(
    "bad",
    [
        [[str(OTHER), "a" * 64]],  # an owner the backup does not hold
        [[str(OWNER), "not-a-digest"]],
        [[str(OWNER)]],
        [[str(OWNER), "a" * 64, "extra"]],
        ["a" * 64],
        [[1, 2]],
    ],
)
def test_a_list_of_lost_files_that_is_not_valid_is_refused(bad: list[Any]) -> None:
    with pytest.raises(ExportRefused, match="missing photo file"):
        build_backup_bundle([export_with(attachment(PHOTO, THUMB))], bad)


def test_an_export_folder_holds_the_document_and_each_file_and_can_be_verified(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    export = export_with(attachment(PHOTO, THUMB), attachment(SECOND, SECOND_THUMB, number=2))
    store = open_media_store(tmp_path / "backup-media", KEY)
    live = LiveFiles(*((OWNER, data) for data in (PHOTO, THUMB, SECOND, SECOND_THUMB)))
    copy_media(store, live, [export], when=WHEN, media_directory=tmp_path)
    folder = tmp_path / "export"

    written = write_export_folder(folder, export, store)

    assert written == {"media_files": 4, "media_left_out": 0}
    assert (folder / "export.json").stat().st_mode & 0o777 == 0o600
    assert (folder / "media").stat().st_mode & 0o777 == 0o700
    assert (folder / "media" / f"{digest(PHOTO)}.jpg").read_bytes() == PHOTO
    assert verify_export(json.loads((folder / "export.json").read_text())).owner_id == OWNER
    assert owner_export_cli.main(["verify", str(folder)]) == 0
    assert json.loads(capsys.readouterr().out)["media"] == {"files": 4, "unreadable": 0}

    (folder / "media" / f"{digest(THUMB)}.jpg").write_bytes(b"changed")
    assert owner_export_cli.main(["verify", str(folder)]) == 1
    assert "photo files are missing or damaged" in capsys.readouterr().err


def test_an_export_folder_is_never_written_over_and_a_failure_leaves_nothing_behind(
    tmp_path: Path,
) -> None:
    export = export_with(attachment(PHOTO, THUMB))
    store = open_media_store(tmp_path / "backup-media", KEY)
    existing = tmp_path / "taken"
    existing.mkdir()

    with pytest.raises(ExportRefused, match="already exists"):
        write_export_folder(existing, export, store)
    assert list(existing.iterdir()) == []

    folder = tmp_path / "half"
    with pytest.raises(MediaFileMissing):
        write_export_folder(folder, export, store)  # the store holds none of the files
    assert not folder.exists()


def test_a_file_the_backup_recorded_as_lost_is_left_out_of_the_export_folder(
    tmp_path: Path,
) -> None:
    export = export_with(attachment(PHOTO, THUMB))
    store = open_media_store(tmp_path / "backup-media", KEY)
    live = LiveFiles((OWNER, PHOTO))
    copy_media(store, live, [export], when=WHEN, media_directory=tmp_path)

    written = write_export_folder(
        tmp_path / "export", export, store, frozenset({(OWNER, digest(THUMB))})
    )

    assert written == {"media_files": 1, "media_left_out": 1}


def test_an_export_folder_is_read_back_only_while_the_files_match_their_names(
    tmp_path: Path,
) -> None:
    (tmp_path / f"{digest(PHOTO)}.jpg").write_bytes(PHOTO)
    (tmp_path / f"{digest(THUMB)}.jpg").write_bytes(b"not the thumbnail")
    (tmp_path / "link.jpg").symlink_to(tmp_path / f"{digest(PHOTO)}.jpg")
    folder = ExportMediaFolder(tmp_path)

    assert folder.read(OWNER, MediaFile(digest(PHOTO), "image/jpeg")) == PHOTO
    with pytest.raises(MediaFileMissing):
        folder.read(OWNER, MediaFile(digest(THUMB), "image/jpeg"))
    with pytest.raises(MediaFileMissing):
        folder.read(OWNER, MediaFile(digest(SECOND), "image/jpeg"))
    os.symlink(tmp_path / f"{digest(PHOTO)}.jpg", tmp_path / f"{digest(SECOND)}.jpg")
    with pytest.raises(MediaFileMissing):  # a link where a file belongs is not followed
        folder.read(OWNER, MediaFile(digest(SECOND), "image/jpeg"))


def test_the_media_check_counts_lost_damaged_and_unused_files_and_names_none(
    tmp_path: Path,
) -> None:
    files = OwnerPhotoFiles.at(tmp_path, "a-secret-for-the-test-only")
    for data in (PHOTO, THUMB, SECOND):
        files.put(OWNER, data)
    unused = files.put(OWNER, SECOND_THUMB)
    next(path for path in tmp_path.rglob(digest(THUMB)) if path.is_file()).write_bytes(
        b"changed on disk"
    )
    references = [
        (OWNER, digest(PHOTO)),
        (OWNER, digest(THUMB)),  # damaged
        (OWNER, digest(SECOND)),
        (OWNER, "f" * 64),  # lost
    ]
    assert files.read(OWNER, unused) == SECOND_THUMB

    audit = files.audit(references)

    assert (audit.referenced, audit.ok, audit.missing, audit.corrupt, audit.orphaned) == (
        4,
        2,
        1,
        1,
        1,
    )
    assert not audit.sound
    assert files.audit([(OWNER, digest(d)) for d in (PHOTO, SECOND)]).sound


def test_a_format_10_export_must_carry_the_photo_collection_and_an_older_one_need_not() -> None:
    document = export_with(attachment(PHOTO, THUMB))
    assert verify_export(document).collection_counts["journal_attachments"] == 1

    stripped = json.loads(json.dumps(document))
    del stripped["collections"]["journal_attachments"]
    del stripped["manifest"]["collection_counts"]["journal_attachments"]
    stripped["manifest"]["sha256"] = export_checksum(stripped)
    with pytest.raises(ExportRefused, match="collection catalogue"):
        verify_export(stripped)

    for older in (as_format_9(export_with()), as_format_8(export_with())):
        assert "journal_attachments" not in older["collections"]
        assert verify_export(older).collection_counts["journal_attachments"] == 0
        assert media_files(older) == ()


def test_a_later_listing_is_never_undone_by_an_older_one(tmp_path: Path) -> None:
    """Two backups that overlap, or a clock set back, must not lower the time of a listed file."""

    store = open_media_store(tmp_path, KEY)
    file = MediaFile(digest(PHOTO), "image/jpeg")
    newer = WHEN + timedelta(days=2)
    store.put(OWNER, file, PHOTO, newer)

    assert store.touch(OWNER, file.digest, WHEN)  # an older backup lists it too

    (stored,) = [path for path in tmp_path.rglob("*") if path.is_file()]
    assert stored.stat().st_mtime == newer.timestamp()
    assert store.remove_unlisted(WHEN + timedelta(days=1)) == 0
    assert store.has(OWNER, file.digest)


def test_the_older_restore_command_refuses_an_export_with_photos(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "export.json"
    path.write_text(json.dumps(export_with(attachment(PHOTO, THUMB))), encoding="utf-8")

    code = owner_export_cli.main(
        [
            "restore",
            str(path),
            "--apply",
            "--target-owner-id",
            str(OTHER),
            "--plan-checksum",
            "a" * 64,
        ]
    )

    assert code == 1
    assert "sidekick-backup import" in capsys.readouterr().err
