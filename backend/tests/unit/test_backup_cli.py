"""CLI tests for `extract-export`: decrypt one owner export from a backup, no database involved."""

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from sidekick.backup import cli as backup_cli
from sidekick.backup.bundle import build_backup_bundle, build_backup_envelope, write_backup_file
from sidekick.owner_export.catalogue import EXPORT_SOURCES, ExportRefused
from sidekick.owner_export.document import build_export_document

OWNER_ID = "00000000-0000-7000-8000-000000000001"
OTHER_OWNER_ID = "00000000-0000-7000-8000-000000000002"
CREATED_AT = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


def empty_export(owner_id: str = OWNER_ID) -> dict[str, Any]:
    return build_export_document(
        owner_id,
        {source.name: [] for source in EXPORT_SOURCES},
        exported_at=CREATED_AT,
    )


def use_key(monkeypatch: pytest.MonkeyPatch, key: bytes | None) -> None:
    """Replace the settings lookup so the test never reads `.env` or a real secret."""

    secret = None if key is None else SecretStr(key.decode("ascii"))
    monkeypatch.setattr(
        backup_cli,
        "get_settings",
        lambda: SimpleNamespace(backup_encryption_key=secret),
    )


def write_backup(path: Path, exports: list[dict[str, Any]], key: bytes) -> Path:
    envelope = build_backup_envelope(build_backup_bundle(exports), key, created_at=CREATED_AT)
    write_backup_file(envelope, path)
    return path


def test_extract_export_writes_the_verified_owner_export_privately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    key = Fernet.generate_key()
    use_key(monkeypatch, key)
    export = empty_export()
    backup = write_backup(tmp_path / "sidekick-backup.skbackup", [export], key)
    output = tmp_path / "export.json"

    assert backup_cli.main(["extract-export", str(backup), str(output)]) == 0

    assert json.loads(output.read_text(encoding="utf-8")) == export
    assert output.stat().st_mode & 0o777 == 0o600
    assert json.loads(capsys.readouterr().out) == {
        "collection_counts": export["manifest"]["collection_counts"],
        "owner_id": OWNER_ID,
        "sha256": export["manifest"]["sha256"],
    }


def test_extract_export_refuses_to_overwrite_an_existing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    key = Fernet.generate_key()
    use_key(monkeypatch, key)
    backup = write_backup(tmp_path / "sidekick-backup.skbackup", [empty_export()], key)
    output = tmp_path / "export.json"
    output.write_bytes(b"keep me")

    assert backup_cli.main(["extract-export", str(backup), str(output)]) == 1

    assert output.read_bytes() == b"keep me"
    assert "backup operation refused" in capsys.readouterr().err


def test_extract_export_with_the_wrong_key_fails_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    backup = write_backup(
        tmp_path / "sidekick-backup.skbackup", [empty_export()], Fernet.generate_key()
    )
    use_key(monkeypatch, Fernet.generate_key())
    output = tmp_path / "export.json"

    assert backup_cli.main(["extract-export", str(backup), str(output)]) == 1

    assert not output.exists()
    assert "authentication failed" in capsys.readouterr().err


def test_extract_export_without_a_configured_key_fails_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    backup = write_backup(
        tmp_path / "sidekick-backup.skbackup", [empty_export()], Fernet.generate_key()
    )
    use_key(monkeypatch, None)
    output = tmp_path / "export.json"

    assert backup_cli.main(["extract-export", str(backup), str(output)]) == 1

    assert not output.exists()
    assert "SIDEKICK_BACKUP_ENCRYPTION_KEY is required" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("damage", "expected_error"),
    [
        ("not-json", "Expecting property name"),
        ("checksum", "checksum mismatch"),
    ],
)
def test_extract_export_refuses_a_damaged_backup_and_writes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    damage: str,
    expected_error: str,
) -> None:
    key = Fernet.generate_key()
    use_key(monkeypatch, key)
    backup = write_backup(tmp_path / "sidekick-backup.skbackup", [empty_export()], key)
    if damage == "not-json":
        backup.write_text("{not json", encoding="utf-8")
    else:
        envelope = json.loads(backup.read_text(encoding="utf-8"))
        envelope["sha256"] = "0" * 64
        backup.write_text(json.dumps(envelope), encoding="utf-8")
    output = tmp_path / "export.json"

    assert backup_cli.main(["extract-export", str(backup), str(output)]) == 1

    assert not output.exists()
    assert expected_error in capsys.readouterr().err


def test_extract_export_refuses_a_backup_with_several_owners(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    key = Fernet.generate_key()
    use_key(monkeypatch, key)
    backup = write_backup(
        tmp_path / "sidekick-backup.skbackup",
        [empty_export(), empty_export(OTHER_OWNER_ID)],
        key,
    )
    output = tmp_path / "export.json"

    assert backup_cli.main(["extract-export", str(backup), str(output)]) == 1

    assert not output.exists()
    assert "exactly one owner export" in capsys.readouterr().err


SECRET_VALUE = "FAILING-ROW-VALUE-4711"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ValueError(f"Invalid isoformat string: '{SECRET_VALUE}'"), "import failed: ValueError"),
        (TypeError(f"cannot parse {SECRET_VALUE}"), "import failed: TypeError"),
        (RuntimeError(f"row {SECRET_VALUE} violates a constraint"), "import failed: RuntimeError"),
        (ExportRefused("target owner must be empty before restore"), "target owner must be empty"),
    ],
)
def test_a_failing_import_reports_the_error_type_never_the_failing_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
    expected: str,
) -> None:
    export = tmp_path / "export.json"
    export.write_text(json.dumps(empty_export()), encoding="utf-8")
    monkeypatch.setattr(backup_cli, "_import_store", lambda: object())

    def failing(*_args: object, **_kwargs: object) -> None:
        raise error

    monkeypatch.setattr(backup_cli, "plan_import", failing)

    assert backup_cli.main(["import", str(export), "--target-owner", OWNER_ID]) == 1

    captured = capsys.readouterr()
    assert expected in captured.err
    assert SECRET_VALUE not in captured.err + captured.out
