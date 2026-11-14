"""`sidekick-automation-worker --once` exits non-zero when its single iteration fails."""

import asyncio
import sys
from types import SimpleNamespace

import pytest

from sidekick.automation import worker as automation_worker
from sidekick.shared.cli_errors import EXIT_FAILED
from sidekick.shared.db_timeouts import DatabaseTimeouts

SECRET = "row-value-that-must-not-be-printed"


class FakeProcessRuns:
    """Stands in for the process-run service; `fail` makes the single iteration raise."""

    def __init__(self) -> None:
        self.fail = False

    def recover_stalled_outbox(self) -> None:
        return None

    def run_due(self, _worker_id: str) -> list[object]:
        if self.fail:
            raise RuntimeError(f"database said {SECRET}")
        return []


class FakeHeartbeat:
    def __init__(self, _worker: str) -> None:
        pass

    def beat(self, _sleep_seconds: float = 0) -> None:
        return None

    def succeeded(self) -> None:
        return None


@pytest.fixture(name="process_runs")
def _process_runs(monkeypatch: pytest.MonkeyPatch) -> FakeProcessRuns:
    runs = FakeProcessRuns()
    container = SimpleNamespace(process_runs=runs)
    settings = SimpleNamespace(
        database_url="postgresql+psycopg://unused", database_timeouts=DatabaseTimeouts()
    )
    monkeypatch.setattr(automation_worker, "get_settings", lambda: settings)
    monkeypatch.setattr(automation_worker, "create_container", lambda _settings: container)
    monkeypatch.setattr(automation_worker, "create_session_factory", lambda _url, **_kw: object())
    monkeypatch.setattr(automation_worker, "StoreBase", lambda _factory: object())
    monkeypatch.setattr(automation_worker, "prune_idempotency_records", lambda _store: 0)
    monkeypatch.setattr(automation_worker, "WorkerHeartbeat", FakeHeartbeat)
    monkeypatch.setattr(automation_worker, "configure_worker_logging", lambda: None)
    monkeypatch.setattr(sys, "argv", ["sidekick-automation-worker", "--once"])
    return runs


def test_once_returns_true_when_the_iteration_succeeds(process_runs: FakeProcessRuns) -> None:
    assert asyncio.run(automation_worker.run_worker(once=True)) is True


def test_once_returns_false_when_the_iteration_fails(process_runs: FakeProcessRuns) -> None:
    process_runs.fail = True
    assert asyncio.run(automation_worker.run_worker(once=True)) is False


def test_once_exits_zero_when_the_iteration_succeeds(process_runs: FakeProcessRuns) -> None:
    automation_worker.main()  # returns normally: exit status 0


def test_once_exits_nonzero_when_the_iteration_fails(
    process_runs: FakeProcessRuns, capsys: pytest.CaptureFixture[str]
) -> None:
    process_runs.fail = True
    with pytest.raises(SystemExit) as raised:
        automation_worker.main()
    assert raised.value.code == EXIT_FAILED
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert SECRET not in captured.out + captured.err
