"""`sidekick-backup-worker --once` is the updater's pre-update backup: its exit status is honest."""

import json
import logging
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from pydantic import SecretStr

from sidekick.backup import worker as backup_worker
from sidekick.backup.bundle import BackupTooLarge
from sidekick.shared.cli_errors import EXIT_UNEXPECTED
from sidekick.shared.db_timeouts import DatabaseTimeouts
from sidekick.shared.observability import AllowlistJsonFormatter


class FakeService:
    """Stands in for OwnerBackupService; `fail` makes the single iteration raise."""

    fail = False
    calls = 0
    last_kwargs: ClassVar[dict[str, Any]] = {}

    def __init__(self, _store: object) -> None:
        pass

    def create(self, **kwargs: Any) -> SimpleNamespace:
        type(self).calls += 1
        type(self).last_kwargs = kwargs
        if type(self).fail:
            raise OSError("disk full")
        return SimpleNamespace(owner_count=1, pruned_count=0)


@pytest.fixture(name="settings")
def _settings(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        backup_enabled=True,
        backup_encryption_key=SecretStr("k" * 44),
        backup_directory=str(tmp_path),
        backup_retention_count=3,
        backup_retention_days=30,
        backup_min_keep=4,
        backup_space_margin_pct=175,
        backup_interval_seconds=3600,
        database_url="postgresql+psycopg://unused",
        environment="test",
        database_timeouts=DatabaseTimeouts(),
    )


@pytest.fixture(name="worker")
def _worker(monkeypatch: pytest.MonkeyPatch, settings: SimpleNamespace) -> type[FakeService]:
    FakeService.fail = False
    FakeService.calls = 0
    monkeypatch.setattr(backup_worker, "get_settings", lambda: settings)
    monkeypatch.setattr(backup_worker, "OwnerBackupService", FakeService)
    monkeypatch.setattr(backup_worker, "create_session_factory", lambda _url, **_kw: object())
    monkeypatch.setattr(backup_worker, "StoreBase", lambda _factory: object())
    monkeypatch.setattr(backup_worker, "configure_worker_logging", lambda: None)
    monkeypatch.setattr(sys, "argv", ["sidekick-backup-worker", "--once"])
    return FakeService


def test_once_exits_zero_when_the_backup_succeeds(worker: type[FakeService]) -> None:
    backup_worker.main()  # returns normally: exit status 0
    assert worker.calls == 1
    # The retention floor and the free-space margin from the settings reach the service.
    assert worker.last_kwargs["min_keep"] == 4
    assert worker.last_kwargs["space_margin_percent"] == 175


def test_once_exits_nonzero_when_the_backup_fails(worker: type[FakeService]) -> None:
    worker.fail = True
    with pytest.raises(SystemExit) as raised:
        backup_worker.main()
    assert raised.value.code == 1
    assert worker.calls == 1


def test_once_exits_nonzero_when_the_key_is_missing(
    worker: type[FakeService], settings: SimpleNamespace
) -> None:
    settings.backup_encryption_key = None
    with pytest.raises(SystemExit) as raised:
        backup_worker.main()
    assert raised.value.code == EXIT_UNEXPECTED
    assert worker.calls == 0


class _Collector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture(name="logged")
def _logged() -> Iterator[_Collector]:
    """The worker's own records. `sidekick` does not propagate to root, so caplog sees none."""

    logger = logging.getLogger("sidekick.backup.worker")
    collector = _Collector()
    previous = logger.level
    logger.addHandler(collector)
    logger.setLevel(logging.INFO)
    yield collector
    logger.removeHandler(collector)
    logger.setLevel(previous)


def test_a_run_logs_a_random_run_id_and_counters_and_nothing_else(
    worker: type[FakeService], logged: _Collector, settings: SimpleNamespace
) -> None:
    backup_worker.main()
    (record,) = [r for r in logged.records if r.getMessage().endswith("completed")]
    assert re.fullmatch(r"[0-9a-f]{32}", record.backup_run_id)
    assert (record.outcome, record.backup_owner_count, record.backup_pruned_count) == (
        "success",
        1,
        0,
    )
    rendered = json.loads(AllowlistJsonFormatter("%(message)s").format(record))
    assert rendered["backup_run_id"] == record.backup_run_id
    assert "dropped_field_count" not in rendered
    assert str(settings.backup_directory) not in json.dumps(rendered)


def test_a_failed_run_logs_its_run_id_and_never_the_error_text(
    worker: type[FakeService], logged: _Collector
) -> None:
    worker.fail = True
    with pytest.raises(SystemExit):
        backup_worker.main()
    (record,) = logged.records
    assert re.fullmatch(r"[0-9a-f]{32}", record.backup_run_id)
    assert record.outcome == "failed"
    rendered = json.loads(AllowlistJsonFormatter("%(message)s").format(record))
    assert rendered["backup_run_id"] == record.backup_run_id
    assert rendered["error_type"] == "OSError"
    assert "disk full" not in json.dumps(rendered)
    assert "dropped_field_count" not in rendered


def test_run_ids_differ_between_runs(worker: type[FakeService], logged: _Collector) -> None:
    backup_worker.main()
    backup_worker.main()
    assert len({r.backup_run_id for r in logged.records}) == 2


def test_a_too_large_bundle_is_a_safe_refusal_without_a_traceback(
    worker: type[FakeService], logged: _Collector, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(_self: FakeService, **_kwargs: Any) -> SimpleNamespace:
        raise BackupTooLarge("backup bundle is over the 512 MiB ceiling")

    monkeypatch.setattr(worker, "create", refuse)
    with pytest.raises(SystemExit) as raised:
        backup_worker.main()
    assert raised.value.code == 1
    (record,) = logged.records
    assert record.exc_info is None
    assert record.outcome == "refused"
    rendered = json.loads(AllowlistJsonFormatter("%(message)s").format(record))
    assert rendered["backup_run_id"] == record.backup_run_id
    assert "dropped_field_count" not in rendered
    assert "512" not in json.dumps(rendered)
