"""The restore drill for journal photos: back up, lose the files, restore into a fresh owner.

Each step is the command an operator runs (`sidekick-backup create` through the service,
`import`, `extract-export-folder`, `sidekick-admin media verify`), against the test database and
temporary folders only. Images are synthetic (`tests/support/photo_files.py`).
"""

import json
import shutil
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from sidekick import composition
from sidekick.admin import cli as admin_cli
from sidekick.api.app import create_container
from sidekick.backup import cli as backup_cli
from sidekick.backup.bundle import BackupResult, OwnerBackupService
from sidekick.backup.media import backup_media_directory
from sidekick.composition import Container
from sidekick.journal.application.photos import PhotoUpload
from sidekick.journal.domain.entry import KeyPoint, KeyPointKind
from sidekick.journal.domain.photo import JournalPhoto, PhotoDetails, PhotoLocation, PhotoTarget
from sidekick.journal.domain.source import SourceType
from sidekick.shared.persistence.stores.base import StoreBase
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support import photo_files
from tests.support.settings import make_settings

KEY = Fernet.generate_key().decode("ascii")
DAY = date(2026, 11, 22)
NOW = datetime(2026, 11, 22, 9, tzinfo=UTC)
# Backups are made on a clock well ahead of the files' real write times, so a file's listed time is
# the backup's and not the moment the test wrote it.
START = datetime(2100, 1, 1, 12, tzinfo=UTC)
SCOPES = frozenset({"journal:read", "journal:write"})
PLACE = "Plats-hemlig-marker-81"


class Clock:
    def __init__(self, now: datetime) -> None:
        self.at = now

    def now(self) -> datetime:
        return self.at


class Drill:
    """A source owner with two photos (one on an entry, one on a day) and the tools of the drill."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        self.factory: sessionmaker[Session] = database_factory()
        self.media = tmp_path / "media"  # a folder of its own, so a count of unused files is exact
        self.settings = make_settings().model_copy(update={"media_directory": self.media})
        self.container: Container = create_container(self.settings, self.factory)
        self.service = self.container.journal_photos
        self.store = StoreBase(self.factory)
        self.backups = tmp_path / "backups"
        self.clock = Clock(START)
        self.source = self.container.auth.provision_user("drill-source", "Source")
        self.actor = Actor(self.source, SCOPES)
        _, self.entry = self.container.journal_capture.write_entry(
            self.actor,
            source_type=SourceType.TRANSCRIPT_TEXT,
            journal_date=DAY,
            occurred_at=NOW,
            raw_text="Synthetic source text",
            language="sv",
            title="Synthetic entry",
            summary=None,
            key_points=(KeyPoint(KeyPointKind.FACT, "A synthetic fact."),),
            idempotency_key="drill-entry",
        )
        self.entry_photo = self.add(
            "entry-photo",
            PhotoTarget(entry_id=self.entry.id),
            photo_files.jpeg(640, 480),
            photo_files.jpeg(320, 240),
            PhotoDetails(location=PhotoLocation(59.33, 18.07, PLACE), orientation=6),
        )
        self.day_photo = self.add(
            "day-photo",
            PhotoTarget(journal_date=DAY),
            photo_files.jpeg(800, 600),
            photo_files.jpeg(300, 200),
            PhotoDetails(),
        )
        settings = SimpleNamespace(
            backup_encryption_key=SecretStr(KEY),
            media_directory=self.media,
            token_pepper=self.settings.token_pepper,
        )
        monkeypatch.setattr(backup_cli, "_import_store", lambda: self.store)
        monkeypatch.setattr(backup_cli, "get_settings", lambda: settings)

    def add(
        self,
        key: str,
        target: PhotoTarget,
        photo: bytes,
        thumbnail: bytes,
        details: PhotoDetails,
    ) -> JournalPhoto:
        return self.service.add_photo(
            self.actor,
            target,
            PhotoUpload(photo=photo, thumbnail=thumbnail, alt_text=None, details=details),
            idempotency_key=key,
        )

    def backup(self, *, retention_count: int = 5) -> BackupResult:
        return OwnerBackupService(self.store, self.clock, photo_files=self.service.files).create(
            directory=self.backups,
            key=KEY,
            retention_count=retention_count,
            retention_days=30,
        )

    def owner(self, name: str) -> UUID:
        return self.container.auth.provision_user(name, name)

    def lose_the_files_of(self, owner: UUID) -> None:
        shutil.rmtree(self.media / self.service.files.key_of(owner))

    def photo_rows(self, owner: UUID) -> int:
        with self.factory() as session:
            return int(
                session.scalar(
                    text("SELECT count(*) FROM sidekick.journal_attachments WHERE owner_id = :o"),
                    {"o": owner},
                )
                or 0
            )

    def stored_files(self) -> list[Path]:
        folder = backup_media_directory(self.backups)
        return sorted(
            path for path in folder.rglob("*") if path.is_file() and ".incoming" not in str(path)
        )


@pytest.fixture
def drill(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Drill:
    return Drill(monkeypatch, tmp_path)


def cli(capsys: pytest.CaptureFixture[str], *args: str | Path | UUID) -> tuple[int, str, str]:
    code = backup_cli.main([*map(str, args)])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def newest_backup(drill: Drill) -> Path:
    return max(drill.backups.glob("*.skbackup"))


@pytest.mark.integration
def test_the_photos_come_back_from_a_backup_after_the_files_are_lost(
    drill: Drill, capsys: pytest.CaptureFixture[str]
) -> None:
    result = drill.backup()
    assert (result.media_stored, result.media_missing) == (4, 0)
    assert len(drill.stored_files()) == 4
    backup = newest_backup(drill)
    media = backup_media_directory(drill.backups)

    code, out, err = cli(capsys, "verify", backup, "--media-directory", media)
    assert (code, err) == (0, "")
    assert json.loads(out)["media"] == {
        "files": 4,
        "readable": 4,
        "recorded_missing": 0,
        "unreadable": 0,
    }

    drill.lose_the_files_of(drill.source)  # the volume is gone; the backup is what is left
    target = drill.owner("drill-target")

    code, out, err = cli(
        capsys, "import", backup, "--target-owner", target, "--media-directory", media
    )
    plan = json.loads(out)
    assert (code, err) == (0, "")
    assert plan["media"] == {"files": 4, "readable": 4, "recorded_missing": 0, "unreadable": 0}
    assert drill.photo_rows(target) == 0  # the plan writes nothing

    code, out, err = cli(
        capsys,
        "import",
        backup,
        "--target-owner",
        target,
        "--media-directory",
        media,
        "--apply",
        "--plan-checksum",
        plan["plan_checksum"],
    )
    applied = json.loads(out)
    assert (code, err) == (0, "")
    assert applied["verified"] is True
    assert (applied["media_restored"], applied["media_missing"]) == (4, 0)
    assert applied["collection_counts"]["journal_attachments"] == 2

    reader = Actor(target, SCOPES)
    (day,) = drill.service.day_summary(reader, DAY).ids
    shown, full = drill.service.read_file(reader, day, "photo")
    _, little = drill.service.read_file(reader, day, "thumb")
    assert (full, little) == (photo_files.jpeg(800, 600), photo_files.jpeg(300, 200))
    assert shown.id == day
    with drill.factory() as session:
        place = session.scalar(
            text(
                "SELECT location_name FROM sidekick.journal_attachments "
                "WHERE owner_id = :o AND location_name IS NOT NULL"
            ),
            {"o": target},
        )
    assert place == PLACE


@pytest.mark.integration
def test_a_restore_without_the_photo_files_is_refused_before_anything_is_written(
    drill: Drill, capsys: pytest.CaptureFixture[str]
) -> None:
    drill.backup()
    backup = newest_backup(drill)
    target = drill.owner("drill-target")
    code, out, _ = cli(capsys, "import", backup, "--target-owner", target)
    plan = json.loads(out)
    assert code == 0
    assert plan["media"]["readable"] == 0 and plan["media"]["unreadable"] == 4

    code, out, err = cli(
        capsys,
        "import",
        backup,
        "--target-owner",
        target,
        "--apply",
        "--plan-checksum",
        plan["plan_checksum"],
    )

    assert code == 1 and out == ""
    assert "pass --media-directory" in err
    assert drill.photo_rows(target) == 0


@pytest.mark.integration
def test_a_file_lost_before_the_backup_is_recorded_and_the_restore_goes_on(
    drill: Drill, capsys: pytest.CaptureFixture[str]
) -> None:
    drill.service.files.remove(drill.source, [drill.day_photo.thumb_digest])

    result = drill.backup()

    assert (result.media_stored, result.media_missing) == (3, 1)
    backup = newest_backup(drill)
    media = backup_media_directory(drill.backups)
    code, out, _ = cli(capsys, "verify", backup, "--media-directory", media)
    assert code == 0
    assert json.loads(out)["media"]["recorded_missing"] == 1
    target = drill.owner("drill-target")
    _, out, _ = cli(capsys, "import", backup, "--target-owner", target, "--media-directory", media)
    plan = json.loads(out)
    assert plan["media"] == {"files": 4, "readable": 3, "recorded_missing": 1, "unreadable": 0}
    _, out, _ = cli(
        capsys,
        "import",
        backup,
        "--target-owner",
        target,
        "--media-directory",
        media,
        "--apply",
        "--plan-checksum",
        plan["plan_checksum"],
    )
    applied = json.loads(out)
    assert (applied["verified"], applied["media_restored"], applied["media_missing"]) == (
        True,
        3,
        1,
    )


@pytest.mark.integration
def test_a_backup_check_fails_when_a_stored_photo_file_is_gone(
    drill: Drill, capsys: pytest.CaptureFixture[str]
) -> None:
    drill.backup()
    drill.stored_files()[0].unlink()

    code, out, err = cli(
        capsys,
        "verify",
        newest_backup(drill),
        "--media-directory",
        backup_media_directory(drill.backups),
    )

    assert code == 1
    assert json.loads(out)["media"]["unreadable"] == 1
    assert "missing or damaged" in err


@pytest.mark.integration
def test_the_next_backup_stores_only_new_files_and_pruning_drops_files_no_kept_backup_lists(
    drill: Drill,
) -> None:
    first = drill.backup(retention_count=1)
    assert first.media_stored == 4
    drill.clock.at = START + timedelta(hours=2)
    drill.add(
        "third",
        PhotoTarget(journal_date=DAY),
        photo_files.jpeg(700, 500),
        photo_files.jpeg(250, 150),
        PhotoDetails(),
    )

    second = drill.backup(retention_count=1)

    assert second.media_stored == 2
    assert second.pruned_count == 1
    assert len(drill.stored_files()) == 6
    with drill.factory.begin() as session:  # the owner erased a photo for good
        session.execute(
            text("DELETE FROM sidekick.journal_attachments WHERE id = :id"),
            {"id": drill.day_photo.id},
        )
    drill.clock.at = START + timedelta(hours=4)

    third = drill.backup(retention_count=1)

    assert third.media_stored == 0
    assert len(drill.stored_files()) == 4  # the erased photo and its thumbnail left with it


@pytest.mark.integration
def test_an_export_folder_with_the_photos_restores_into_another_owner(
    drill: Drill, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    drill.backup()
    folder = tmp_path / "export"

    code, out, err = cli(capsys, "extract-export-folder", newest_backup(drill), folder)

    assert (code, err) == (0, "")
    assert json.loads(out)["media_files"] == 4
    assert len(list((folder / "media").iterdir())) == 4
    target = drill.owner("drill-target")
    _, out, _ = cli(capsys, "import", folder, "--target-owner", target)
    plan = json.loads(out)
    assert plan["media"]["readable"] == 4
    code, out, err = cli(
        capsys,
        "import",
        folder,
        "--target-owner",
        target,
        "--apply",
        "--plan-checksum",
        plan["plan_checksum"],
    )
    applied = json.loads(out)
    assert (code, err) == (0, "")
    assert (applied["verified"], applied["media_restored"]) == (True, 4)
    assert drill.photo_rows(target) == 2


@pytest.mark.integration
def test_media_verify_counts_what_is_lost_and_names_nothing(
    drill: Drill, capsys: pytest.CaptureFixture[str]
) -> None:
    assert composition.audit_photo_files(drill.settings).sound
    stray = drill.service.files.put(drill.source, photo_files.jpeg(100, 100))
    assert stray

    assert admin_cli.run_media_verify(drill.settings) is True
    counts = json.loads(capsys.readouterr().out)
    assert counts == {"corrupt": 0, "missing": 0, "ok": 4, "referenced": 4, "unused": 1}

    drill.lose_the_files_of(drill.source)

    assert admin_cli.run_media_verify(drill.settings) is False
    lost = capsys.readouterr().out
    assert json.loads(lost)["missing"] == 4
    assert drill.entry_photo.content_digest not in lost
    assert str(drill.source) not in lost
