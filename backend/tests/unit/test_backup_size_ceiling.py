"""The in-memory ceiling of owner backups: create, verify and import refuse oversize input."""

import hashlib
import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from sidekick.backup import bundle as bundle_module
from sidekick.backup import cli as backup_cli
from sidekick.backup import importer as importer_module
from sidekick.backup.bundle import (
    MAX_BACKUP_FILE_BYTES,
    MAX_BACKUP_TOKEN_BYTES,
    MAX_BUNDLE_PLAINTEXT_BYTES,
    BackupTooLarge,
    OwnerBackupService,
    bounded_canonical_json,
    build_backup_bundle,
    build_backup_envelope,
    decrypt_backup_envelope,
    read_backup_file_bytes,
    verify_backup_file,
    write_backup_file,
)
from sidekick.backup.importer import load_export_document
from sidekick.owner_export.core import (
    EXPORT_SOURCES,
    ExportBudget,
    ExportRefused,
    OwnerExportService,
    build_export_document,
    canonical_json,
)
from tests.support.backup import EmptyBackupStore, FixedClock

OWNER_ID = "00000000-0000-7000-8000-000000000001"
CREATED_AT = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
TARGET = "00000000-0000-7000-8000-0000000000aa"


def empty_export() -> dict[str, Any]:
    return build_export_document(
        OWNER_ID, {source.name: [] for source in EXPORT_SOURCES}, exported_at=CREATED_AT
    )


def test_the_ceiling_matches_the_snapshot_tool_and_the_token_bound_covers_it() -> None:
    assert MAX_BUNDLE_PLAINTEXT_BYTES == 512 * 1024 * 1024
    assert MAX_BACKUP_TOKEN_BYTES > MAX_BUNDLE_PLAINTEXT_BYTES
    assert MAX_BACKUP_FILE_BYTES > MAX_BACKUP_TOKEN_BYTES


def test_bounded_json_is_byte_identical_to_canonical_json() -> None:
    value = {"b": [1, 'å\u2028"x'], "a": {"z": None, "y": 1.5}, "c": "日本"}
    assert bounded_canonical_json(value, 10_000) == canonical_json(value)


def test_an_old_bundle_encrypted_with_canonical_json_still_decrypts() -> None:
    key = Fernet.generate_key()
    bundle = build_backup_bundle([empty_export()])
    envelope = build_backup_envelope(bundle, key, created_at=CREATED_AT)
    # What the format has always been: one Fernet token over canonical JSON.
    legacy = Fernet(key).encrypt(canonical_json(bundle)).decode("ascii")
    assert Fernet(key).decrypt(envelope["ciphertext"].encode("ascii")) == canonical_json(bundle)
    envelope["ciphertext"] = legacy
    envelope["sha256"] = hashlib.sha256(legacy.encode("ascii")).hexdigest()
    assert decrypt_backup_envelope(envelope, key) == bundle


def test_creating_an_oversize_bundle_is_refused_before_encryption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bundle_module, "MAX_BUNDLE_PLAINTEXT_BYTES", 100)
    bundle = build_backup_bundle([empty_export()])

    with pytest.raises(BackupTooLarge, match=r"bundle is over the 0 MiB ceiling") as raised:
        build_backup_envelope(bundle, Fernet.generate_key(), created_at=CREATED_AT)

    assert isinstance(raised.value, ExportRefused)
    assert OWNER_ID not in str(raised.value)


def test_a_bundle_under_a_lowered_ceiling_still_round_trips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = Fernet.generate_key()
    bundle = build_backup_bundle([empty_export()])
    size = len(canonical_json(bundle))
    monkeypatch.setattr(bundle_module, "MAX_BUNDLE_PLAINTEXT_BYTES", size)

    envelope = build_backup_envelope(bundle, key, created_at=CREATED_AT)
    path = tmp_path / "sidekick-backup.skbackup"
    write_backup_file(envelope, path)

    assert decrypt_backup_envelope(envelope, key) == bundle
    assert verify_backup_file(path, key) == 1


def test_the_service_counts_a_too_large_refusal_with_a_reason_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Telemetry:
        def __init__(self) -> None:
            self.counts: list[dict[str, str]] = []

        def count(self, _name: str, attributes: dict[str, str]) -> None:
            self.counts.append(attributes)

    monkeypatch.setattr(
        OwnerExportService, "export_all", lambda _self, _budget=None: [empty_export()]
    )
    monkeypatch.setattr(bundle_module, "MAX_BUNDLE_PLAINTEXT_BYTES", 100)
    telemetry = Telemetry()

    with pytest.raises(BackupTooLarge):
        OwnerBackupService(EmptyBackupStore(), FixedClock(), telemetry).create(  # type: ignore[arg-type]
            directory=tmp_path,
            key=Fernet.generate_key(),
            retention_count=30,
            retention_days=30,
        )

    assert list(tmp_path.iterdir()) == []
    assert telemetry.counts == [
        {
            "owner_backup.operation": "create",
            "outcome": "refused",
            "owner_backup.reason": "too_large",
        }
    ]


def _backup_bytes(key: bytes) -> bytes:
    """A backup file as `write_backup_file` writes it: canonical JSON, `ciphertext` first."""

    envelope = build_backup_envelope(
        build_backup_bundle([empty_export()]), key, created_at=CREATED_AT
    )
    return canonical_json(envelope)


def test_the_importer_loads_a_backup_and_a_plain_export_under_the_ceiling() -> None:
    key = Fernet.generate_key()
    export = empty_export()

    from_backup = load_export_document(_backup_bytes(key), key=key, source_owner=None)
    from_export = load_export_document(json.dumps(export).encode(), key=None, source_owner=None)

    assert from_backup == export == from_export


# Boundary tests: with the limit lowered to N, a size of exactly N passes and N + 1 is refused.


def test_bounded_json_passes_at_the_limit_and_refuses_one_byte_over() -> None:
    value = {"a": ["x" * 20, {"b": 1}], "c": "ö"}
    size = len(canonical_json(value))

    assert bounded_canonical_json(value, size) == canonical_json(value)
    with pytest.raises(BackupTooLarge):
        bounded_canonical_json(value, size - 1)


def test_reading_a_backup_file_passes_at_the_limit_and_refuses_one_byte_over(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    limit = 64
    monkeypatch.setattr(bundle_module, "MAX_BACKUP_FILE_BYTES", limit)
    exact, over = tmp_path / "exact", tmp_path / "over"
    exact.write_bytes(b"x" * limit)
    over.write_bytes(b"x" * (limit + 1))

    assert read_backup_file_bytes(exact) == b"x" * limit
    with pytest.raises(BackupTooLarge, match="file is over"):
        read_backup_file_bytes(over)


def test_decrypting_passes_at_the_token_limit_and_refuses_one_byte_over(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = Fernet.generate_key()
    bundle = build_backup_bundle([empty_export()])
    envelope = build_backup_envelope(bundle, key, created_at=CREATED_AT)
    size = len(envelope["ciphertext"])

    monkeypatch.setattr(bundle_module, "MAX_BACKUP_TOKEN_BYTES", size)
    assert decrypt_backup_envelope(envelope, key) == bundle
    monkeypatch.setattr(bundle_module, "MAX_BACKUP_TOKEN_BYTES", size - 1)
    with pytest.raises(BackupTooLarge, match="ciphertext is over"):
        decrypt_backup_envelope(envelope, key)


def test_decrypting_passes_at_the_plaintext_limit_and_refuses_one_byte_over(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = Fernet.generate_key()
    bundle = build_backup_bundle([empty_export()])
    envelope = build_backup_envelope(bundle, key, created_at=CREATED_AT)
    size = len(canonical_json(bundle))

    monkeypatch.setattr(bundle_module, "MAX_BUNDLE_PLAINTEXT_BYTES", size)
    assert decrypt_backup_envelope(envelope, key) == bundle
    monkeypatch.setattr(bundle_module, "MAX_BUNDLE_PLAINTEXT_BYTES", size - 1)
    with pytest.raises(BackupTooLarge, match="bundle is over"):
        decrypt_backup_envelope(envelope, key)


def test_the_importer_holds_a_backup_to_the_file_limit_exactly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = Fernet.generate_key()
    raw = _backup_bytes(key)

    monkeypatch.setattr(importer_module, "MAX_BACKUP_FILE_BYTES", len(raw))
    assert load_export_document(raw, key=key, source_owner=None) == empty_export()
    monkeypatch.setattr(importer_module, "MAX_BACKUP_FILE_BYTES", len(raw) - 1)
    with pytest.raises(BackupTooLarge, match="input is over the"):
        load_export_document(raw, key=key, source_owner=None)


@pytest.mark.parametrize("key_given", [False, True])
def test_the_importer_holds_a_plain_export_to_the_plaintext_limit_before_parsing(
    monkeypatch: pytest.MonkeyPatch, key_given: bool
) -> None:
    key = Fernet.generate_key() if key_given else None
    raw = json.dumps(empty_export()).encode("utf-8")

    monkeypatch.setattr(importer_module, "MAX_BUNDLE_PLAINTEXT_BYTES", len(raw))
    assert load_export_document(raw, key=key, source_owner=None) == empty_export()
    monkeypatch.setattr(importer_module, "MAX_BUNDLE_PLAINTEXT_BYTES", len(raw) - 1)
    with pytest.raises(BackupTooLarge, match="input is over the"):
        load_export_document(raw, key=key, source_owner=None)
    # Not even JSON: the size check runs first, so nothing is parsed.
    with pytest.raises(BackupTooLarge):
        load_export_document(b"x" * len(raw), key=key, source_owner=None)


def test_the_import_command_reads_standard_input_with_a_cap_of_one_byte_over(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    reads: list[int] = []

    class Buffer:
        def read(self, size: int = -1) -> bytes:
            reads.append(size)
            return b""

    monkeypatch.setattr(backup_cli, "MAX_BACKUP_FILE_BYTES", 123)
    monkeypatch.setattr(backup_cli.sys, "stdin", SimpleNamespace(buffer=Buffer()))
    monkeypatch.setattr(
        backup_cli, "get_settings", lambda: SimpleNamespace(backup_encryption_key=None)
    )

    code = backup_cli.main(["import", "-", "--target-owner", TARGET])

    assert (code, reads) == (1, [124])
    assert "not a backup or an owner export" in capsys.readouterr().err


def test_the_import_command_reports_an_oversize_file_safely_and_touches_no_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    key = Fernet.generate_key()
    path = tmp_path / "owner.skbackup"
    path.write_bytes(_backup_bytes(key))
    monkeypatch.setattr(importer_module, "MAX_BACKUP_FILE_BYTES", 10)
    monkeypatch.setattr(
        backup_cli,
        "get_settings",
        lambda: SimpleNamespace(backup_encryption_key=SecretStr(key.decode("ascii"))),
    )

    def no_store() -> None:
        raise AssertionError("the database must not be opened for oversize input")

    monkeypatch.setattr(backup_cli, "_import_store", no_store)

    code = backup_cli.main(["import", str(path), "--target-owner", str(uuid.UUID(TARGET))])

    captured = capsys.readouterr()
    assert (code, captured.out) == (1, "")
    assert "over the" in captured.err and "MiB ceiling" in captured.err
    assert OWNER_ID not in captured.err and key.decode("ascii") not in captured.err


class _SpyRows:
    """An owner-scoped row stream that counts how many rows the export actually pulled."""

    def __init__(self, total: int) -> None:
        self.total = total
        self.pulled = 0

    def __iter__(self) -> Iterator[Any]:
        row_type = EXPORT_SOURCES[0].row_type
        for index in range(self.total):
            self.pulled += 1
            yield row_type(id=uuid.UUID(int=index), owner_id=uuid.UUID(OWNER_ID))


class _SpyStore:
    def __init__(self, rows: _SpyRows) -> None:
        self._rows = rows

    def snapshot_transaction(self, operation: Any) -> Any:
        class Session:
            def scalars(self, _query: object) -> Any:
                return self

            def all(self) -> list[uuid.UUID]:
                return [uuid.UUID(OWNER_ID)]

        return operation(Session())

    def export_owner_rows(self, _session: object, *, owner_id: uuid.UUID, row_type: type) -> Any:
        return self._rows if row_type is EXPORT_SOURCES[0].row_type else []


def test_an_export_over_the_budget_is_refused_without_reading_the_rest_of_the_data() -> None:
    rows = _SpyRows(total=10_000)

    with pytest.raises(BackupTooLarge, match="bundle is over the 0 MiB ceiling") as raised:
        OwnerExportService(_SpyStore(rows)).export_all(  # type: ignore[arg-type]
            ExportBudget(2_000, lambda: BackupTooLarge("backup bundle is over the 0 MiB ceiling"))
        )

    assert 1 <= rows.pulled < 100
    assert OWNER_ID not in str(raised.value)


def test_an_export_under_the_budget_reads_everything_and_matches_an_unbudgeted_export() -> None:
    plain = OwnerExportService(_SpyStore(_SpyRows(total=20)), FixedClock()).export_all()  # type: ignore[arg-type]
    rows = _SpyRows(total=20)

    budgeted = OwnerExportService(_SpyStore(rows), FixedClock()).export_all(  # type: ignore[arg-type]
        ExportBudget(10_000_000, lambda: BackupTooLarge("never"))
    )

    assert rows.pulled == 20
    assert budgeted == plain
    assert len(budgeted[0]["collections"][EXPORT_SOURCES[0].name]) == 20


def test_the_backup_service_stops_reading_at_the_ceiling_counts_it_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    counts: list[dict[str, str]] = []

    class Telemetry:
        def count(self, _name: str, attributes: dict[str, str]) -> None:
            counts.append(attributes)

    rows = _SpyRows(total=10_000)
    monkeypatch.setattr(bundle_module, "MAX_BUNDLE_PLAINTEXT_BYTES", 2_000)

    with pytest.raises(BackupTooLarge, match="bundle is over the"):
        OwnerBackupService(_SpyStore(rows), FixedClock(), Telemetry()).create(  # type: ignore[arg-type]
            directory=tmp_path,
            key=Fernet.generate_key(),
            retention_count=30,
            retention_days=30,
        )

    assert rows.pulled < 100
    assert list(tmp_path.iterdir()) == []
    assert counts == [
        {
            "owner_backup.operation": "create",
            "outcome": "refused",
            "owner_backup.reason": "too_large",
        }
    ]
