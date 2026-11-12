import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet

from sidekick.backup.bundle import (
    OwnerBackupService,
    backup_file_path,
    build_backup_bundle,
    build_backup_envelope,
    decrypt_backup_envelope,
    ensure_free_space,
    newest_backup_size,
    prune_backup_files,
    verify_backup_file,
    write_backup_file,
)
from sidekick.owner_export.core import (
    EXPORT_SOURCES,
    ExportRefused,
    OwnerExportService,
    build_export_document,
)
from sidekick.shared.backup_files import latest_backup_time
from tests.support.backup import (
    CREATED_AT,
    EmptyBackupStore,
    FixedClock,
)

OWNER_ID = "00000000-0000-7000-8000-000000000001"


def empty_export(owner_id: str = OWNER_ID) -> dict[str, Any]:
    return build_export_document(
        owner_id,
        {source.name: [] for source in EXPORT_SOURCES},
        exported_at=CREATED_AT,
    )


def test_backup_round_trip_keeps_owner_data_inside_ciphertext() -> None:
    key = Fernet.generate_key()
    bundle = build_backup_bundle([empty_export()])

    envelope = build_backup_envelope(bundle, key, created_at=CREATED_AT)
    serialized = json.dumps(envelope)

    assert OWNER_ID not in serialized
    assert decrypt_backup_envelope(envelope, key) == bundle


def test_backup_rejects_wrong_key_and_tampering() -> None:
    key = Fernet.generate_key()
    envelope = build_backup_envelope(
        build_backup_bundle([empty_export()]), key, created_at=CREATED_AT
    )

    with pytest.raises(ExportRefused, match="authentication failed"):
        decrypt_backup_envelope(envelope, Fernet.generate_key())

    tampered = dict(envelope)
    tampered["sha256"] = "0" * 64
    with pytest.raises(ExportRefused, match="checksum mismatch"):
        decrypt_backup_envelope(tampered, key)


def test_backup_rejects_duplicate_owners() -> None:
    with pytest.raises(ExportRefused, match="same owner more than once"):
        build_backup_bundle([empty_export(), empty_export()])


def test_backup_write_is_private_and_retention_does_not_touch_unmanaged_files(
    tmp_path: Path,
) -> None:
    key = Fernet.generate_key()
    unmanaged = tmp_path / "keep.txt"
    unmanaged.write_text("keep", encoding="utf-8")
    paths: list[Path] = []
    for offset in range(3):
        created_at = CREATED_AT + timedelta(minutes=offset)
        path = backup_file_path(tmp_path, created_at)
        write_backup_file(
            build_backup_envelope(
                build_backup_bundle([empty_export()]), key, created_at=created_at
            ),
            path,
        )
        paths.append(path)

    assert os.stat(paths[-1]).st_mode & 0o777 == 0o600
    deleted = prune_backup_files(
        tmp_path,
        retention_count=2,
        retention_days=30,
        now=CREATED_AT + timedelta(minutes=3),
    )

    assert len(deleted) == 1
    assert paths[0] in deleted
    assert paths[1].exists() and paths[2].exists()
    assert unmanaged.exists()


def test_pruning_never_deletes_the_newest_verified_backup(tmp_path: Path) -> None:
    key = Fernet.generate_key()
    paths: list[Path] = []
    for offset in range(3):
        created_at = CREATED_AT + timedelta(minutes=offset)
        path = backup_file_path(tmp_path, created_at)
        write_backup_file(
            build_backup_envelope(
                build_backup_bundle([empty_export()]), key, created_at=created_at
            ),
            path,
        )
        paths.append(path)
    # A file time far in the past (a restored copy) must not make the verified backup prunable.
    os.utime(paths[0], (1_000_000_000, 1_000_000_000))
    deleted = prune_backup_files(
        tmp_path,
        retention_count=1,
        retention_days=1,
        now=CREATED_AT + timedelta(minutes=3),
        keep=paths[0],
    )
    assert paths[0].exists() and paths[2].exists()
    assert deleted == (paths[1],)


def test_a_backup_is_fsynced_and_its_directory_entry_is_flushed_after_the_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = Fernet.generate_key()
    flushed: list[str] = []
    real_fsync = os.fsync

    def recording_fsync(descriptor: int) -> None:
        flushed.append("directory" if os.path.isdir(f"/proc/self/fd/{descriptor}") else "file")
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", recording_fsync)
    path = backup_file_path(tmp_path, CREATED_AT)
    write_backup_file(
        build_backup_envelope(build_backup_bundle([empty_export()]), key, created_at=CREATED_AT),
        path,
    )
    assert flushed == ["file", "directory"]


def test_temporary_and_partial_names_count_for_neither_monitoring_nor_retention(
    tmp_path: Path,
) -> None:
    finished = backup_file_path(tmp_path, CREATED_AT)
    finished.write_text("{}", encoding="utf-8")
    # The names write_backup_file uses while it works, and a few lookalikes.
    newer = backup_file_path(tmp_path, CREATED_AT + timedelta(days=5))
    lookalikes = [
        newer.with_name(f".{newer.name}.{'a' * 32}.tmp"),
        newer.with_name(newer.name + ".partial"),
        newer.with_name("." + newer.name),
        tmp_path / "sidekick-backup-notastamp-aaaaaaaaaaaa.skbackup",
    ]
    for path in lookalikes:
        path.write_text("x", encoding="utf-8")
    assert latest_backup_time(tmp_path) == CREATED_AT
    deleted = prune_backup_files(
        tmp_path,
        retention_count=1,
        retention_days=3650,
        now=CREATED_AT,
    )
    assert deleted == ()
    assert all(path.exists() for path in lookalikes)


def test_owner_backup_service_exports_all_owners_atomically(tmp_path: Path) -> None:
    key = Fernet.generate_key()
    result = OwnerBackupService(EmptyBackupStore(), FixedClock()).create(
        directory=tmp_path,
        key=key,
        retention_count=30,
        retention_days=30,
    )

    assert result.owner_count == 0
    assert result.path.exists()
    assert (
        decrypt_backup_envelope(json.loads(result.path.read_text(encoding="utf-8")), key)["exports"]
        == []
    )


def export_with_dangling_reference() -> dict[str, Any]:
    """A status-history row (a real foreign key) whose task the export does not contain.

    A polymorphic history reference to a removed record is allowed; a foreign key is not.
    """

    source = next(source for source in EXPORT_SOURCES if source.name == "task_status_history")
    row: dict[str, Any] = {column.name: None for column in source.row_type.__table__.columns}
    row.update(
        {
            "id": "00000000-0000-7000-8000-000000000010",
            "owner_id": OWNER_ID,
            "task_id": "00000000-0000-7000-8000-000000000011",
        }
    )
    collections: dict[str, list[dict[str, Any]]] = {s.name: [] for s in EXPORT_SOURCES}
    collections[source.name] = [row]
    return build_export_document(OWNER_ID, collections, exported_at=CREATED_AT)  # type: ignore[arg-type]


def test_a_backup_with_a_dangling_reference_is_refused_and_leaves_earlier_backups_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = Fernet.generate_key()
    service = OwnerBackupService(EmptyBackupStore(), FixedClock())
    kept = service.create(directory=tmp_path, key=key, retention_count=1, retention_days=30)
    monkeypatch.setattr(
        OwnerExportService,
        "export_all",
        lambda _self, _budget=None: [export_with_dangling_reference()],
    )

    with pytest.raises(ExportRefused, match=r"unresolved references: task_status_history\[0\]"):
        service.create(directory=tmp_path, key=key, retention_count=1, retention_days=30)

    # Nothing was written, and the refusal did not prune the last good backup.
    assert list(tmp_path.iterdir()) == [kept.path]


def test_a_written_backup_that_cannot_be_restored_is_removed_and_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = Fernet.generate_key()
    monkeypatch.setattr(
        OwnerExportService, "export_all", lambda _self, _budget=None: [empty_export()]
    )
    # The pre-write check passes; the read-back of the written file is what finds the damage.
    monkeypatch.setattr(
        "sidekick.backup.bundle.verify_backup_file",
        lambda *_args: (_ for _ in ()).throw(ExportRefused("written backup cannot be read back")),
    )

    with pytest.raises(ExportRefused, match="cannot be read back"):
        OwnerBackupService(EmptyBackupStore(), FixedClock()).create(
            directory=tmp_path, key=key, retention_count=30, retention_days=30
        )

    assert list(tmp_path.iterdir()) == []


def test_verify_backup_file_refuses_a_backup_whose_export_holds_a_dangling_reference(
    tmp_path: Path,
) -> None:
    key = Fernet.generate_key()
    envelope = build_backup_envelope(
        build_backup_bundle([export_with_dangling_reference()]), key, created_at=CREATED_AT
    )
    path = tmp_path / "sidekick-backup.skbackup"
    write_backup_file(envelope, path)

    with pytest.raises(ExportRefused, match="unresolved references"):
        verify_backup_file(path, key)
    with pytest.raises(ExportRefused, match="cannot be read back"):
        verify_backup_file(tmp_path / "missing.skbackup", key)


def test_verify_backup_file_counts_owners_of_a_good_backup(tmp_path: Path) -> None:
    key = Fernet.generate_key()
    path = tmp_path / "sidekick-backup.skbackup"
    write_backup_file(
        build_backup_envelope(build_backup_bundle([empty_export()]), key, created_at=CREATED_AT),
        path,
    )

    assert verify_backup_file(path, key) == 1


class _Usage:
    def __init__(self, free: int) -> None:
        self.free = free


def _write_backups(directory: Path, count: int) -> list[Path]:
    key = Fernet.generate_key()
    paths: list[Path] = []
    for offset in range(count):
        created_at = CREATED_AT + timedelta(minutes=offset)
        path = backup_file_path(directory, created_at)
        write_backup_file(
            build_backup_envelope(
                build_backup_bundle([empty_export()]), key, created_at=created_at
            ),
            path,
        )
        paths.append(path)
    return paths


def test_the_newest_min_keep_backups_survive_the_age_and_count_limits(tmp_path: Path) -> None:
    paths = _write_backups(tmp_path, 5)
    for path in paths:
        os.utime(path, (1_000_000_000, 1_000_000_000))  # all far older than the age limit
    other = tmp_path / ".sidekick-backup-hidden.tmp"
    other.write_text("not a finished backup", encoding="utf-8")

    deleted = prune_backup_files(
        tmp_path,
        retention_count=2,
        retention_days=1,
        now=CREATED_AT + timedelta(days=400),
        min_keep=3,
    )

    assert set(deleted) == {paths[0], paths[1]}
    assert all(path.exists() for path in paths[2:])
    assert other.exists()


def test_min_keep_must_be_positive(tmp_path: Path) -> None:
    with pytest.raises(ExportRefused, match="retention must be positive"):
        prune_backup_files(
            tmp_path, retention_count=1, retention_days=1, now=CREATED_AT, min_keep=0
        )


def test_newest_backup_size_reads_only_finished_names(tmp_path: Path) -> None:
    assert newest_backup_size(tmp_path / "missing") == 0
    paths = _write_backups(tmp_path, 2)
    (tmp_path / "sidekick-backup-99999999T999999Z-aaaaaaaaaaaa.skbackup.tmp").write_bytes(
        b"x" * 10_000
    )
    assert newest_backup_size(tmp_path) == paths[1].stat().st_size


def test_a_backup_is_refused_before_any_export_when_the_disk_is_too_full(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exported: list[str] = []
    monkeypatch.setattr(
        OwnerExportService, "export_all", lambda _self, _budget=None: exported.append("x") or []
    )
    monkeypatch.setattr("sidekick.backup.bundle.shutil.disk_usage", lambda _path: _Usage(1024))
    target = tmp_path / "does" / "not" / "exist"

    with pytest.raises(ExportRefused, match="not enough free disk space"):
        OwnerBackupService(EmptyBackupStore(), FixedClock()).create(
            directory=target, key=Fernet.generate_key(), retention_count=30, retention_days=30
        )

    assert exported == [] and not target.exists()


def test_the_space_needed_is_the_newest_backup_times_the_margin_but_at_least_the_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _write_backups(tmp_path, 1)
    size = paths[0].stat().st_size
    seen: list[str] = []

    def usage(path: Path) -> _Usage:
        seen.append(str(path))
        return _Usage(size * 2)

    monkeypatch.setattr("sidekick.backup.bundle.shutil.disk_usage", usage)
    ensure_free_space(tmp_path, margin_percent=200, floor_bytes=0)  # needs exactly 2 * size
    with pytest.raises(ExportRefused, match="not enough free disk space"):
        ensure_free_space(tmp_path, margin_percent=201, floor_bytes=0)
    with pytest.raises(ExportRefused, match="not enough free disk space"):
        ensure_free_space(tmp_path, margin_percent=100, floor_bytes=size * 2 + 1)
    with pytest.raises(ExportRefused, match="at least 100"):
        ensure_free_space(tmp_path, margin_percent=99)
    assert seen and all(path == str(tmp_path) for path in seen)


def test_a_free_size_that_cannot_be_read_is_a_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(_path: Path) -> _Usage:
        raise OSError("no such device")

    monkeypatch.setattr("sidekick.backup.bundle.shutil.disk_usage", broken)
    with pytest.raises(ExportRefused, match="cannot determine free disk space"):
        ensure_free_space(tmp_path)


class LaterClock:
    def now(self) -> datetime:
        return CREATED_AT + timedelta(days=1)


def _fail_fsync_when(monkeypatch: pytest.MonkeyPatch, *, directory: bool) -> None:
    real_fsync = os.fsync

    def failing_fsync(descriptor: int) -> None:
        if os.path.isdir(f"/proc/self/fd/{descriptor}") == directory:
            raise OSError(5, "injected fsync failure")
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", failing_fsync)


@pytest.mark.parametrize("directory_fsync", [True, False], ids=["directory-fsync", "file-fsync"])
def test_a_failed_durable_write_is_refused_leaves_no_backup_and_prunes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, directory_fsync: bool
) -> None:
    key = Fernet.generate_key()
    good = OwnerBackupService(EmptyBackupStore(), FixedClock()).create(
        directory=tmp_path, key=key, retention_count=1, retention_days=30
    )
    pruned: list[object] = []
    real_prune = prune_backup_files
    monkeypatch.setattr(
        "sidekick.backup.bundle.prune_backup_files",
        lambda *args, **kwargs: pruned.append(args) or real_prune(*args, **kwargs),
    )
    _fail_fsync_when(monkeypatch, directory=directory_fsync)

    with pytest.raises(ExportRefused, match="could not be written durably"):
        OwnerBackupService(EmptyBackupStore(), LaterClock()).create(
            directory=tmp_path, key=key, retention_count=1, retention_days=30
        )

    # The unproven file is gone, so it is not "the newest good backup", and the older one survives.
    assert pruned == []
    assert list(tmp_path.iterdir()) == [good.path]
    assert verify_backup_file(good.path, key) == 0


def test_write_backup_file_propagates_a_directory_fsync_error_and_removes_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = Fernet.generate_key()
    _fail_fsync_when(monkeypatch, directory=True)
    path = backup_file_path(tmp_path, CREATED_AT)

    with pytest.raises(OSError, match="injected fsync failure"):
        write_backup_file(
            build_backup_envelope(
                build_backup_bundle([empty_export()]), key, created_at=CREATED_AT
            ),
            path,
        )

    assert list(tmp_path.iterdir()) == []
