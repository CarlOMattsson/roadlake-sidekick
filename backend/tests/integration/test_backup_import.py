"""`sidekick-backup import`: plan first, apply with the plan checksum.

A source owner is created with a few tasks, exported, and written both as an encrypted
`.skbackup` and as a plain export. Each is imported into a freshly provisioned empty owner and
the per-collection counts must match those of the source export.
"""

import io
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy.orm import Session, sessionmaker

from sidekick.api.app import create_container
from sidekick.backup import cli as backup_cli
from sidekick.backup.bundle import build_backup_bundle, build_backup_envelope, write_backup_file
from sidekick.owner_export.catalogue import EXPORT_SOURCES
from sidekick.owner_export.document import build_export_document, verify_export
from sidekick.owner_export.export import OwnerExportService
from sidekick.shared.persistence.stores.base import StoreBase
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings

KEY = Fernet.generate_key().decode("ascii")
SOURCE_TITLES = ("Water the plants", "Call the dentist", "Book the train")
CREATED_AT = datetime(2026, 11, 10, tzinfo=UTC)


@dataclass(frozen=True)
class Sources:
    """The same owner as an encrypted backup and as a plain export, with the expected counts."""

    backup: Path
    export: Path
    counts: dict[str, int]
    document: dict[str, Any]


class Harness:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, key: str | None) -> None:
        self.factory: sessionmaker[Session] = database_factory()
        self.store = StoreBase(self.factory)
        monkeypatch.setattr(backup_cli, "_import_store", lambda: self.store)
        secret = None if key is None else SecretStr(key)
        monkeypatch.setattr(
            backup_cli, "get_settings", lambda: SimpleNamespace(backup_encryption_key=secret)
        )

    def owner(self, name: str) -> UUID:
        return create_container(make_settings(), self.factory).auth.provision_user(name, name)

    def counts(self, owner: UUID) -> dict[str, int]:
        document = OwnerExportService(self.store).export(Actor(owner, frozenset()))
        return {k: v for k, v in verify_export(document).collection_counts.items() if v}

    def write_sources(self, directory: Path) -> Sources:
        source = self.owner("import-source")
        tasks = create_container(make_settings(), self.factory).tasks
        actor = Actor(source, frozenset({"tasks:read", "tasks:write"}))
        for index, title in enumerate(SOURCE_TITLES):
            tasks.create(actor, title=title, idempotency_key=f"import-source-{index}")
        document = OwnerExportService(self.store).export(Actor(source, frozenset()))
        export = directory / "owner-export.json"
        export.write_text(json.dumps(document), encoding="utf-8")
        backup = directory / "owner.skbackup"
        write_backup_file(
            build_backup_envelope(build_backup_bundle([document]), KEY, created_at=CREATED_AT),
            backup,
        )
        counts = {k: v for k, v in verify_export(document).collection_counts.items() if v}
        return Sources(backup, export, counts, document)


def run(capsys: pytest.CaptureFixture[str], *args: str | Path | UUID) -> tuple[int, str, str]:
    code = backup_cli.main(["import", *map(str, args)])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def plan_checksum(out: str) -> str:
    checksum = json.loads(out)["plan_checksum"]
    assert isinstance(checksum, str)
    return checksum


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    return Harness(monkeypatch, KEY)


KINDS = ("backup", "export")


@pytest.mark.integration
@pytest.mark.parametrize("kind", KINDS)
def test_both_inputs_import_into_an_empty_owner_with_the_source_counts(
    harness: Harness, capsys: pytest.CaptureFixture[str], tmp_path: Path, kind: str
) -> None:
    sources = harness.write_sources(tmp_path)
    source = getattr(sources, kind)
    assert sources.counts["tasks"] == len(SOURCE_TITLES)
    target = harness.owner("import-target")
    before = harness.counts(target)

    code, out, err = run(capsys, source, "--target-owner", target)
    assert (code, err) == (0, "")
    checksum = plan_checksum(out)
    assert harness.counts(target) == before  # the plan writes nothing

    code, out, err = run(
        capsys, source, "--target-owner", target, "--apply", "--plan-checksum", checksum
    )
    result = json.loads(out)
    assert (code, err) == (0, "")
    assert result["verified"] is True
    assert result["plan_checksum"] == checksum
    assert result["target_owner_id"] == str(target)
    assert result["collection_counts"] == {
        **{name: 0 for name in result["collection_counts"]},
        **sources.counts,
    }
    assert harness.counts(target) == sources.counts


@pytest.mark.integration
def test_output_holds_no_owner_content(
    harness: Harness, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    sources = harness.write_sources(tmp_path)
    target = harness.owner("import-target")
    code, out, err = run(capsys, sources.backup, "--target-owner", target)
    checksum = plan_checksum(out)
    code2, out2, err2 = run(
        capsys, sources.backup, "--target-owner", target, "--apply", "--plan-checksum", checksum
    )
    assert (code, code2) == (0, 0)
    for text in (out, err, out2, err2):
        assert not any(title in text for title in SOURCE_TITLES)


@pytest.mark.integration
@pytest.mark.parametrize("kind", KINDS)
def test_a_checksum_mismatch_is_refused_and_writes_nothing(
    harness: Harness, capsys: pytest.CaptureFixture[str], tmp_path: Path, kind: str
) -> None:
    source = getattr(harness.write_sources(tmp_path), kind)
    target = harness.owner("import-target")
    before = harness.counts(target)

    code, out, err = run(
        capsys, source, "--target-owner", target, "--apply", "--plan-checksum", "0" * 64
    )

    assert (code, out) == (1, "")
    assert "restore plan checksum mismatch" in err
    assert harness.counts(target) == before


@pytest.mark.integration
def test_apply_needs_a_checksum_and_a_checksum_needs_apply(
    harness: Harness, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    export = harness.write_sources(tmp_path).export
    target = harness.owner("import-target")
    with pytest.raises(SystemExit) as no_checksum:
        backup_cli.main(["import", str(export), "--target-owner", str(target), "--apply"])
    with pytest.raises(SystemExit) as no_apply:
        backup_cli.main(
            ["import", str(export), "--target-owner", str(target), "--plan-checksum", "0" * 64]
        )
    assert (no_checksum.value.code, no_apply.value.code) == (2, 2)
    assert harness.counts(target) == {"memory_settings": 1}
    capsys.readouterr()


@pytest.mark.integration
@pytest.mark.parametrize("kind", KINDS)
def test_a_non_empty_target_owner_is_refused(
    harness: Harness, capsys: pytest.CaptureFixture[str], tmp_path: Path, kind: str
) -> None:
    sources = harness.write_sources(tmp_path)
    source = getattr(sources, kind)
    target = harness.owner("import-target")
    _, out, _ = run(capsys, source, "--target-owner", target)
    checksum = plan_checksum(out)
    args = (source, "--target-owner", target, "--apply", "--plan-checksum", checksum)
    assert run(capsys, *args)[0] == 0

    code, out, err = run(capsys, *args)

    assert (code, out) == (1, "")
    assert "target owner must be empty before restore" in err
    assert harness.counts(target) == sources.counts


@pytest.mark.integration
def test_a_missing_target_owner_is_refused(
    harness: Harness, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    export = harness.write_sources(tmp_path).export
    code, out, err = run(capsys, export, "--target-owner", "00000000-0000-7000-8000-00000000dead")
    assert (code, out) == (1, "")
    assert "target owner does not exist" in err


@pytest.mark.integration
def test_a_wrong_key_is_refused_before_anything_is_planned(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    wrong = Fernet.generate_key().decode("ascii")
    harness = Harness(monkeypatch, wrong)
    backup = harness.write_sources(tmp_path).backup
    target = harness.owner("import-target")

    code, out, err = run(capsys, backup, "--target-owner", target)

    assert (code, out) == (1, "")
    assert "backup authentication failed" in err
    assert wrong not in err


@pytest.mark.integration
def test_an_encrypted_backup_without_any_key_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    harness = Harness(monkeypatch, None)
    backup = harness.write_sources(tmp_path).backup
    target = harness.owner("import-target")
    code, out, err = run(capsys, backup, "--target-owner", target)
    assert (code, out) == (1, "")
    assert "encryption key is required" in err


@pytest.mark.integration
def test_a_key_file_replaces_the_environment_key_and_must_be_private(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    harness = Harness(monkeypatch, None)
    backup = harness.write_sources(tmp_path).backup
    target = harness.owner("import-target")
    key_file = tmp_path / "backup.key"
    key_file.write_text(KEY, encoding="ascii")

    key_file.chmod(0o644)
    code, out, err = run(capsys, backup, "--target-owner", target, "--key-file", key_file)
    assert (code, out) == (1, "")
    assert "mode 600" in err

    key_file.chmod(0o600)
    code, out, err = run(capsys, backup, "--target-owner", target, "--key-file", key_file)
    assert (code, err) == (0, "")
    assert json.loads(out)["status"] == "ready"


@pytest.mark.integration
def test_a_backup_can_be_read_from_standard_input(
    harness: Harness,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    backup = harness.write_sources(tmp_path).backup
    target = harness.owner("import-target")
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(backup.read_bytes())))
    code, out, err = run(capsys, "-", "--target-owner", target)
    assert (code, err) == (0, "")
    assert json.loads(out)["status"] == "ready"


@pytest.mark.integration
def test_several_owners_need_a_source_owner(
    harness: Harness, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    export = harness.write_sources(tmp_path).document
    other = build_export_document(
        UUID("00000000-0000-7000-8000-000000000002"),
        {source.name: [] for source in EXPORT_SOURCES},
        exported_at=CREATED_AT,
    )
    path = tmp_path / "two.skbackup"
    write_backup_file(
        build_backup_envelope(build_backup_bundle([export, other]), KEY, created_at=CREATED_AT),
        path,
    )
    target = harness.owner("import-target")

    code, out, err = run(capsys, path, "--target-owner", target)
    assert (code, out) == (1, "")
    assert "2 owners" in err

    code, out, err = run(
        capsys, path, "--target-owner", target, "--source-owner", export["owner_id"]
    )
    assert (code, err) == (0, "")
    assert json.loads(out)["source_owner_id"] == export["owner_id"]


@pytest.mark.integration
def test_unrecognised_input_is_refused(
    harness: Harness, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    target = harness.owner("import-target")
    junk = tmp_path / "junk.json"
    junk.write_text(json.dumps({"format": "something-else"}), encoding="utf-8")
    code, out, err = run(capsys, junk, "--target-owner", target)
    assert (code, out) == (1, "")
    assert "not a backup or an owner export" in err
