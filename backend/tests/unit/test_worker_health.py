"""Worker health: heartbeat file, healthcheck command, the loops that beat, the compose wiring."""

import asyncio
import os
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
import yaml

from sidekick.automation import worker as automation_worker
from sidekick.backup import worker as backup_worker
from sidekick.companion import push_worker
from sidekick.companion.push_delivery import PushDeliveryService
from sidekick.memory import worker as memory_worker
from sidekick.memory.application.sync import MemoryReconciler
from sidekick.memory.application.sync_state import ReconcileResult
from sidekick.shared import worker_health
from sidekick.shared.backup_files import latest_backup_time
from sidekick.shared.config import Settings
from sidekick.shared.worker_health import (
    SUCCESS_WINDOW_SECONDS,
    WORK_BUDGET_SECONDS,
    WORKERS,
    WorkerHeartbeat,
    check_last_backup,
    check_worker,
    heartbeat_path,
    main,
)

SELFHOST = Path(__file__).resolve().parents[3] / "deploy" / "selfhost"

HEALTH_CHECK_CODE = yaml.safe_load((SELFHOST / "compose.yaml").read_text(encoding="utf-8"))[
    "x-sidekick-worker-health-check"
]

# compose service -> (command of the service, worker name the healthcheck is told)
COMPOSE_WORKERS = {
    "automation-worker": ("sidekick-automation-worker", "automation"),
    "backup": ("sidekick-backup-worker", "backup"),
    "memory-worker": ("sidekick-memory-worker", "memory"),
    "push": ("sidekick-push-worker", "push"),
}


class _Stop(Exception):
    """Ends a worker loop after its first sleep."""


class _FakeClock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.current = start

    def __call__(self) -> float:
        return self.current


@pytest.fixture(name="tmp_dir")
def _tmp_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Points the default heartbeat directory (the temp directory) at a test directory."""

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    return tmp_path


def test_a_fresh_heartbeat_is_ok_and_a_missing_one_is_not(tmp_path: Path) -> None:
    clock = _FakeClock()
    assert check_worker("memory", directory=tmp_path, now=clock) == "missing"
    WorkerHeartbeat("memory", directory=tmp_path, clock=clock).beat(60)
    assert check_worker("memory", directory=tmp_path, now=clock) == "ok"


def test_the_heartbeat_goes_stale_after_the_work_budget_plus_the_sleep(tmp_path: Path) -> None:
    clock = _FakeClock()
    WorkerHeartbeat("push", directory=tmp_path, clock=clock).beat(10)
    limit = WORK_BUDGET_SECONDS["push"] + 10

    clock.current += limit
    assert check_worker("push", directory=tmp_path, now=clock) == "ok"
    clock.current += 1
    assert check_worker("push", directory=tmp_path, now=clock) == "stale"


def test_a_new_beat_renews_the_promise(tmp_path: Path) -> None:
    clock = _FakeClock()
    heartbeat = WorkerHeartbeat("automation", directory=tmp_path, clock=clock)
    heartbeat.beat(30)
    clock.current += 10_000
    assert check_worker("automation", directory=tmp_path, now=clock) == "stale"
    heartbeat.beat(30)
    heartbeat.succeeded()
    assert check_worker("automation", directory=tmp_path, now=clock) == "ok"


def test_each_worker_has_its_own_file(tmp_path: Path) -> None:
    clock = _FakeClock()
    WorkerHeartbeat("memory", directory=tmp_path, clock=clock).beat()
    assert check_worker("backup", directory=tmp_path, now=clock) == "missing"
    assert len({heartbeat_path(worker, tmp_path) for worker in WORKERS}) == len(WORKERS)


@pytest.mark.parametrize(
    "content", ["", "garbage", "1.0", "1.0 2.0 3.0 4.0 5.0", "1.0 0", "1.0 -5"]
)
def test_an_unreadable_heartbeat_is_invalid(tmp_path: Path, content: str) -> None:
    heartbeat_path("backup", tmp_path).write_text(content, encoding="ascii")
    assert check_worker("backup", directory=tmp_path) == "invalid"


def test_a_heartbeat_that_is_not_text_is_invalid(tmp_path: Path) -> None:
    heartbeat_path("backup", tmp_path).write_bytes(b"\xff\xfe")
    assert check_worker("backup", directory=tmp_path) == "invalid"


def test_an_unknown_worker_never_reaches_the_file_system(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        heartbeat_path("../etc/passwd", tmp_path)


def test_a_failed_write_is_logged_by_class_only_and_does_not_stop_the_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    logged: list[dict[str, Any]] = []
    monkeypatch.setattr(
        worker_health.LOGGER, "warning", lambda _message, **kwargs: logged.append(kwargs["extra"])
    )
    WorkerHeartbeat("memory", directory=tmp_path / "missing-dir").beat(60)
    assert logged == [{"error_type": "FileNotFoundError"}]


def test_no_temporary_file_is_left_behind(tmp_path: Path) -> None:
    WorkerHeartbeat("memory", directory=tmp_path).beat(60)
    assert [path.name for path in tmp_path.iterdir()] == ["sidekick-heartbeat-memory"]


def test_the_command_prints_one_word_and_fails_unless_ok(
    tmp_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as missing:
        main(["memory"])
    assert missing.value.code == 1
    assert capsys.readouterr().out == "missing\n"

    WorkerHeartbeat("memory").beat(60)
    with pytest.raises(SystemExit) as fine:
        main(["memory"])
    assert fine.value.code == 0
    assert capsys.readouterr().out == "ok\n"


def test_the_command_refuses_an_unknown_worker(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as refused:
        main(["nonsense"])
    assert refused.value.code == 2


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def test_the_idle_memory_worker_beats_while_memory_is_off(
    tmp_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_sleep(_seconds: float) -> None:
        raise _Stop

    monkeypatch.setattr(memory_worker, "get_settings", lambda: _settings(memory_enabled=False))
    monkeypatch.setattr(memory_worker, "create_session_factory", lambda _url, **_kw: None)
    monkeypatch.setattr(memory_worker.asyncio, "sleep", fake_sleep)

    with pytest.raises(_Stop):
        asyncio.run(memory_worker.run_worker())

    assert check_worker("memory") == "ok"


def test_the_memory_worker_beats_at_the_start_of_every_pass(
    tmp_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    beats: list[float] = []

    def fake_run_pass(**_kwargs: Any) -> list[object]:
        beats.append(1.0 if heartbeat_path("memory").exists() else 0.0)
        return []

    async def fake_sleep(_seconds: float) -> None:
        raise _Stop

    async def fake_check(*_args: Any) -> bool:
        return True

    monkeypatch.setattr(
        memory_worker,
        "get_settings",
        lambda: _settings(memory_enabled=True, memory_provider="fake"),
    )
    monkeypatch.setattr(memory_worker, "create_session_factory", lambda _url, **_kw: None)
    monkeypatch.setattr(memory_worker, "build_provider", lambda _settings: None)
    monkeypatch.setattr(memory_worker, "_guarded", fake_check)
    monkeypatch.setattr(memory_worker, "run_pass", fake_run_pass)
    monkeypatch.setattr(memory_worker.asyncio, "sleep", fake_sleep)

    with pytest.raises(_Stop):
        asyncio.run(memory_worker.run_worker())

    assert beats == [1.0], "the beat comes before the pass, so a hung pass is what goes stale"


def test_the_automation_worker_beats_each_iteration(
    tmp_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    process_runs = SimpleNamespace(
        recover_stalled_outbox=lambda: None, run_due=lambda _worker_id: []
    )

    async def fake_sleep(_seconds: float) -> None:
        raise _Stop

    monkeypatch.setattr(automation_worker, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        automation_worker, "create_container", lambda _s: SimpleNamespace(process_runs=process_runs)
    )
    monkeypatch.setattr(automation_worker, "create_session_factory", lambda _url, **_kw: None)
    monkeypatch.setattr(automation_worker, "SqlAlchemyStore", lambda _factory: None)
    monkeypatch.setattr(automation_worker, "prune_idempotency_records", lambda _store: 0)
    monkeypatch.setattr(automation_worker.asyncio, "sleep", fake_sleep)

    with pytest.raises(_Stop):
        asyncio.run(automation_worker.run_worker())

    assert check_worker("automation") == "ok"


def test_the_backup_worker_beats_even_with_backups_off(
    tmp_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_sleep(_seconds: float) -> None:
        raise _Stop

    monkeypatch.setattr(backup_worker, "get_settings", lambda: _settings(backup_enabled=False))
    monkeypatch.setattr(backup_worker, "create_session_factory", lambda _url, **_kw: None)
    monkeypatch.setattr(backup_worker, "SqlAlchemyStore", lambda _factory: None)
    monkeypatch.setattr(backup_worker, "OwnerBackupService", lambda _store: None)
    monkeypatch.setattr(backup_worker.asyncio, "sleep", fake_sleep)

    with pytest.raises(_Stop):
        asyncio.run(backup_worker.run_worker())

    assert check_worker("backup") == "ok"


def test_the_push_worker_beats_while_push_is_off(
    tmp_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_sleep(seconds: float) -> None:
        assert seconds == push_worker.IDLE_SLEEP_SECONDS
        raise _Stop

    monkeypatch.setattr(push_worker.time, "sleep", fake_sleep)

    with pytest.raises(_Stop):
        push_worker.run_worker(_settings(push_enabled=False))

    assert check_worker("push") == "ok"


def test_the_memory_worker_marks_a_successful_pass_and_not_a_failed_one(
    tmp_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outcomes = iter([[], RuntimeError("database down")])
    marks: list[float] = []

    def fake_run_pass(**_kwargs: Any) -> list[object]:
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def fake_sleep(_seconds: float) -> None:
        marks.append(_last_success("memory"))
        if len(marks) == 2:
            raise _Stop

    async def fake_check(*_args: Any) -> bool:
        return True

    monkeypatch.setattr(
        memory_worker,
        "get_settings",
        lambda: _settings(memory_enabled=True, memory_provider="fake"),
    )
    monkeypatch.setattr(memory_worker, "create_session_factory", lambda _url, **_kw: None)
    monkeypatch.setattr(memory_worker, "build_provider", lambda _settings: None)
    monkeypatch.setattr(memory_worker, "_guarded", fake_check)
    monkeypatch.setattr(memory_worker, "run_pass", fake_run_pass)
    monkeypatch.setattr(memory_worker.asyncio, "sleep", fake_sleep)

    with pytest.raises(_Stop):
        asyncio.run(memory_worker.run_worker())

    assert marks[0] > 0, "a pass that completed is a success"
    assert marks[1] == marks[0], "a failing pass leaves the earlier success time untouched"


def test_the_idle_workers_count_idle_as_success(
    tmp_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_sleep(_seconds: float) -> None:
        raise _Stop

    monkeypatch.setattr(push_worker.time, "sleep", fake_sleep)
    with pytest.raises(_Stop):
        push_worker.run_worker(_settings(push_enabled=False))
    assert _last_success("push") > 0


def test_the_automation_worker_marks_success_only_when_the_iteration_works(
    tmp_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_run_due(_worker_id: str) -> list[object]:
        raise RuntimeError("database down")

    process_runs = SimpleNamespace(recover_stalled_outbox=lambda: None, run_due=broken_run_due)

    async def fake_sleep(_seconds: float) -> None:
        raise _Stop

    monkeypatch.setattr(automation_worker, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        automation_worker, "create_container", lambda _s: SimpleNamespace(process_runs=process_runs)
    )
    monkeypatch.setattr(automation_worker, "create_session_factory", lambda _url, **_kw: None)
    monkeypatch.setattr(automation_worker, "SqlAlchemyStore", lambda _factory: None)
    monkeypatch.setattr(automation_worker, "prune_idempotency_records", lambda _store: 0)
    monkeypatch.setattr(automation_worker.asyncio, "sleep", fake_sleep)

    with pytest.raises(_Stop):
        asyncio.run(automation_worker.run_worker())

    assert _last_success("automation") == 0, "a failed iteration is not a success"
    assert check_worker("automation") == "ok", "the loop is alive and still inside its window"


def test_the_push_worker_does_not_mark_a_failed_iteration(
    tmp_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Broken:
        def run_once(self) -> int:
            raise RuntimeError("database down")

    scheduler = SimpleNamespace(run_once=lambda: None)

    def fake_sleep(_seconds: float) -> None:
        raise _Stop

    monkeypatch.setattr(push_worker.time, "sleep", fake_sleep)

    with pytest.raises(_Stop):
        push_worker.run_worker(
            _settings(push_enabled=True), build=lambda _settings: (_Broken(), scheduler)
        )

    assert _last_success("push") == 0


def _last_success(worker: str) -> float:
    return float(heartbeat_path(worker).read_text(encoding="ascii").split()[3])


def test_a_new_worker_is_healthy_until_the_success_window_runs_out(tmp_path: Path) -> None:
    clock = _FakeClock()
    heartbeat = WorkerHeartbeat("push", directory=tmp_path, clock=clock)
    window = SUCCESS_WINDOW_SECONDS["push"]
    heartbeat.beat(5)
    assert check_worker("push", directory=tmp_path, now=clock) == "ok"

    # The loop keeps beating, so it is alive, but no iteration succeeds.
    clock.current += window
    heartbeat.beat(5)
    assert check_worker("push", directory=tmp_path, now=clock) == "ok"
    clock.current += 1
    heartbeat.beat(5)
    assert check_worker("push", directory=tmp_path, now=clock) == "failing"


def test_a_success_renews_the_window_and_each_worker_has_its_own(tmp_path: Path) -> None:
    clock = _FakeClock()
    heartbeat = WorkerHeartbeat("memory", directory=tmp_path, clock=clock)
    heartbeat.beat(60)
    clock.current += SUCCESS_WINDOW_SECONDS["memory"] + 1
    heartbeat.beat(60)
    assert check_worker("memory", directory=tmp_path, now=clock) == "failing"
    heartbeat.succeeded()
    assert check_worker("memory", directory=tmp_path, now=clock) == "ok"
    clock.current += SUCCESS_WINDOW_SECONDS["memory"] + 1
    heartbeat.beat(60)
    assert check_worker("memory", directory=tmp_path, now=clock) == "failing"
    assert set(SUCCESS_WINDOW_SECONDS) == {"automation", "memory", "push"}


def test_a_stale_heartbeat_is_reported_before_a_failing_one(tmp_path: Path) -> None:
    clock = _FakeClock()
    WorkerHeartbeat("push", directory=tmp_path, clock=clock).beat(5)
    clock.current += 100_000
    assert check_worker("push", directory=tmp_path, now=clock) == "stale"


@pytest.mark.parametrize("content", ["1000000.0 300.0", "1000000.0 300.0 900000.0"])
def test_a_heartbeat_file_from_an_older_writer_is_never_failing(
    tmp_path: Path, content: str
) -> None:
    heartbeat_path("push", tmp_path).write_text(content + "\n", encoding="ascii")
    assert check_worker("push", directory=tmp_path, now=lambda: 1_000_100.0) == "ok"


def test_the_backup_worker_is_not_judged_on_the_success_marker(tmp_path: Path) -> None:
    clock = _FakeClock()
    heartbeat = WorkerHeartbeat("backup", directory=tmp_path, clock=clock)
    heartbeat.beat(_NIGHTLY)
    clock.current += 3600 * 20
    heartbeat.beat(_NIGHTLY)
    assert check_worker("backup", directory=tmp_path, now=clock) == "ok"


def test_the_command_answers_failing_when_the_worker_lives_but_never_succeeds(
    tmp_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    now = time.time()
    heartbeat_path("push").write_text(f"{now:.3f} 400.0 {now - 7200:.3f} 0.000\n", encoding="ascii")
    with pytest.raises(SystemExit) as failing:
        main(["push"])
    assert failing.value.code == 1
    assert capsys.readouterr().out == "failing\n"


def test_every_worker_has_a_work_budget() -> None:
    assert set(WORK_BUDGET_SECONDS) == set(WORKERS)
    assert all(budget > 0 for budget in WORK_BUDGET_SECONDS.values())


def test_every_compose_worker_is_health_checked_with_its_own_name() -> None:
    services = yaml.safe_load((SELFHOST / "compose.yaml").read_text(encoding="utf-8"))["services"]
    on_api_image = {
        name
        for name, service in services.items()
        if service.get("command") and service["command"][0].startswith("sidekick-")
    }
    assert on_api_image == set(COMPOSE_WORKERS), "a new worker needs a heartbeat and a healthcheck"
    for name, (command, worker) in COMPOSE_WORKERS.items():
        service = services[name]
        assert service["command"] == [command]
        health = service["healthcheck"]
        assert health["test"] == ["CMD", "python", "-c", HEALTH_CHECK_CODE, worker], name
        assert worker in WORKERS
        # The heartbeat is written to /tmp, the only writable path of the read-only container.
        assert service["read_only"] is True and service["tmpfs"] == ["/tmp"], name
        assert health["start_period"] and health["interval"] and health["retries"], name


def _run_check(
    tmp_path: Path, modules: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run the compose healthcheck code; `modules` is a fake `sidekick` package (else the real)."""

    env = {**os.environ, "TMPDIR": str(tmp_path)}
    if modules is not None:
        for relative, content in {
            "sidekick/__init__.py": "",
            "sidekick/shared/__init__.py": "",
            **modules,
        }.items():
            target = tmp_path / "pkg" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        env["PYTHONPATH"] = str(tmp_path / "pkg")
    return subprocess.run(
        [sys.executable, "-c", HEALTH_CHECK_CODE, "memory"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_healthcheck_is_strict_for_an_image_with_the_heartbeat_module(tmp_path: Path) -> None:
    assert _run_check(tmp_path).returncode == 1  # never beat: missing
    WorkerHeartbeat("memory", directory=tmp_path).beat(60)
    result = _run_check(tmp_path)
    assert (result.returncode, result.stdout) == (0, "ok\n")


def test_the_healthcheck_fails_when_the_heartbeat_module_is_missing(tmp_path: Path) -> None:
    result = _run_check(tmp_path, modules={})
    assert result.returncode == 1
    assert "sidekick.shared.worker_health" in result.stderr


def test_the_healthcheck_does_not_hide_a_broken_heartbeat_module(tmp_path: Path) -> None:
    broken = {"sidekick/shared/worker_health.py": "import a_module_that_does_not_exist\n"}
    result = _run_check(tmp_path, modules=broken)
    assert result.returncode == 1
    assert "a_module_that_does_not_exist" in result.stderr


def test_the_health_command_is_an_installed_script() -> None:
    pyproject = (SELFHOST.parents[1] / "backend" / "pyproject.toml").read_text(encoding="utf-8")
    assert 'sidekick-worker-health = "sidekick.shared.worker_health:main"' in pyproject


# --- last successful backup: a signal separate from the worker heartbeat ---

_NIGHTLY = 86_400
_BACKUP_NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


def _backup_file(directory: Path, created: datetime, name_suffix: str = "abc123456789") -> Path:
    path = (
        directory / f"sidekick-backup-{created.strftime('%Y%m%dT%H%M%SZ')}-{name_suffix}.skbackup"
    )
    path.write_bytes(b"{}")
    return path


def test_latest_backup_time_is_the_newest_valid_file_name(tmp_path: Path) -> None:
    assert latest_backup_time(tmp_path) is None
    assert latest_backup_time(tmp_path / "absent") is None
    _backup_file(tmp_path, _BACKUP_NOW - timedelta(days=2))
    newest = _BACKUP_NOW - timedelta(hours=3)
    _backup_file(tmp_path, newest)
    (tmp_path / "sidekick-backup-garbage-x.skbackup").write_bytes(b"")
    (tmp_path / "notes.txt").write_text("x", encoding="ascii")
    assert latest_backup_time(tmp_path) == newest


def test_a_recent_backup_is_ok_and_none_is_missing(tmp_path: Path) -> None:
    now = _BACKUP_NOW.timestamp()
    assert check_last_backup(tmp_path, _NIGHTLY, now=lambda: now) == "backup_missing"
    _backup_file(tmp_path, _BACKUP_NOW - timedelta(hours=1))
    assert check_last_backup(tmp_path, _NIGHTLY, now=lambda: now) == "ok"


def test_a_nightly_backup_goes_stale_after_26_hours(tmp_path: Path) -> None:
    _backup_file(tmp_path, _BACKUP_NOW)
    limit = _BACKUP_NOW.timestamp() + 26 * 3600
    assert check_last_backup(tmp_path, _NIGHTLY, now=lambda: limit) == "ok"
    assert check_last_backup(tmp_path, _NIGHTLY, now=lambda: limit + 1) == "backup_stale"


def _backup_settings(directory: Path, *, enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        backup_enabled=enabled, backup_directory=directory, backup_interval_seconds=_NIGHTLY
    )


def _beat_backup_worker_started(*, hours_ago: float) -> None:
    """A backup worker that started `hours_ago` ago and beat just now."""

    times = iter([time.time() - hours_ago * 3600, time.time()])
    WorkerHeartbeat("backup", clock=lambda: next(times)).beat(_NIGHTLY)


def test_a_new_worker_without_a_backup_is_healthy_until_interval_plus_grace(
    tmp_dir: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    backups = tmp_path_factory.mktemp("backups")
    monkeypatch.setattr("sidekick.shared.config.get_settings", lambda: _backup_settings(backups))
    _beat_backup_worker_started(hours_ago=1)

    with pytest.raises(SystemExit) as waiting:
        main(["backup"])
    assert waiting.value.code == 0
    captured = capsys.readouterr()
    assert captured.out == "ok\n"
    assert "waiting for the first backup" in captured.err

    _beat_backup_worker_started(hours_ago=27)  # past 24 h + 2 h with nothing written
    with pytest.raises(SystemExit) as overdue:
        main(["backup"])
    assert overdue.value.code == 1
    assert capsys.readouterr().out == "backup_missing\n"


def test_check_last_backup_waits_for_the_first_backup_only_inside_the_grace(
    tmp_path: Path,
) -> None:
    now = _BACKUP_NOW.timestamp()
    limit = _NIGHTLY + 7200
    kwargs = {"now": lambda: now}
    inside = check_last_backup(tmp_path, _NIGHTLY, started_at=now - limit, **kwargs)
    outside = check_last_backup(tmp_path, _NIGHTLY, started_at=now - limit - 1, **kwargs)
    unknown = check_last_backup(tmp_path, _NIGHTLY, started_at=None, **kwargs)
    assert (inside, outside, unknown) == (
        "waiting_first_backup",
        "backup_missing",
        "backup_missing",
    )


def test_the_heartbeat_carries_the_start_time_and_older_files_still_parse(tmp_path: Path) -> None:
    clock = _FakeClock()
    heartbeat = WorkerHeartbeat("backup", directory=tmp_path, clock=clock)
    clock.current += 50
    heartbeat.beat(10)
    assert heartbeat_path("backup", tmp_path).read_text(encoding="ascii").split()[2] == (
        "1000000.000"
    )
    heartbeat_path("backup", tmp_path).write_text(f"{clock():.3f} 100\n", encoding="ascii")
    assert check_worker("backup", directory=tmp_path, now=clock) == "ok"


def test_only_finished_backup_names_count(tmp_path: Path) -> None:
    finished = _BACKUP_NOW - timedelta(days=1)
    _backup_file(tmp_path, finished)
    later = (_BACKUP_NOW - timedelta(hours=1)).strftime("%Y%m%dT%H%M%SZ")
    for name in (
        f".sidekick-backup-{later}-abc123456789.skbackup.0123456789ab.tmp",  # writer temporary
        f".sidekick-backup-{later}-abc123456789.skbackup",  # hidden
        f"sidekick-backup-{later}-abc123456789.skbackup.tmp",
        f"sidekick-backup-{later}-abc123456789.tmp.skbackup",
        f"sidekick-backup-{later}.skbackup",  # no unique part: partial name
        f"sidekick-backup-{later}-abc12.skbackup",
        f"sidekick-backup-{later}-ABC123456789.skbackup",
    ):
        (tmp_path / name).write_bytes(b"{}")
    (tmp_path / f"sidekick-backup-{later}-dddddddddddd.skbackup").mkdir()  # not a file
    assert latest_backup_time(tmp_path) == finished


def test_the_backup_healthcheck_fails_on_a_live_worker_without_a_recent_backup(
    tmp_dir: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    backups = tmp_path_factory.mktemp("backups")
    monkeypatch.setattr("sidekick.shared.config.get_settings", lambda: _backup_settings(backups))
    _beat_backup_worker_started(hours_ago=30)  # the loop is alive and has run for 30 h ...

    with pytest.raises(SystemExit) as missing:  # ... but no backup ever succeeded
        main(["backup"])
    assert missing.value.code == 1
    assert capsys.readouterr().out == "backup_missing\n"

    _backup_file(backups, datetime.now(UTC) - timedelta(hours=30))
    with pytest.raises(SystemExit) as stale:
        main(["backup"])
    assert stale.value.code == 1
    assert capsys.readouterr().out == "backup_stale\n"

    _backup_file(backups, datetime.now(UTC) - timedelta(hours=1))
    with pytest.raises(SystemExit) as fine:
        main(["backup"])
    assert fine.value.code == 0
    assert capsys.readouterr().out == "ok\n"


def test_the_backup_healthcheck_ignores_recency_with_backups_off_and_a_dead_loop_stays_missing(
    tmp_dir: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    backups = tmp_path_factory.mktemp("backups")
    monkeypatch.setattr(
        "sidekick.shared.config.get_settings", lambda: _backup_settings(backups, enabled=False)
    )
    with pytest.raises(SystemExit):
        main(["backup"])
    assert capsys.readouterr().out == "missing\n"  # no heartbeat: that verdict comes first

    WorkerHeartbeat("backup").beat(_NIGHTLY)
    with pytest.raises(SystemExit) as fine:
        main(["backup"])
    assert fine.value.code == 0
    assert capsys.readouterr().out == "ok\n"


def test_a_broken_configuration_does_not_hide_the_heartbeat_verdict(
    tmp_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken() -> None:
        raise ValueError("secret-looking detail must not be printed")

    monkeypatch.setattr("sidekick.shared.config.get_settings", broken)
    WorkerHeartbeat("backup").beat(_NIGHTLY)
    with pytest.raises(SystemExit) as fine:
        main(["backup"])
    assert fine.value.code == 0
    captured = capsys.readouterr()
    assert captured.out == "ok\n"
    assert "secret-looking" not in captured.out + captured.err


# --- a cycle in which every unit of work failed is not a success ------------------------------


def _owner_result(status: str = "completed", **errors: int) -> ReconcileResult:
    result = ReconcileResult(
        owner_id=uuid4(),
        correlation_id="cid",
        status=status,  # type: ignore[arg-type]
    )
    result.error_categories.update(errors)
    return result


def test_a_memory_pass_is_a_success_when_nothing_failed_or_there_is_nothing_to_do() -> None:
    assert memory_worker.pass_succeeded([])
    assert memory_worker.pass_succeeded([_owner_result()])
    assert memory_worker.pass_succeeded([_owner_result("locked"), _owner_result("disabled")])
    # One document rejected is not a provider failure.
    assert memory_worker.pass_succeeded([_owner_result(rejected=1)])


def test_a_memory_pass_in_which_every_owner_failed_is_not_a_success() -> None:
    assert not memory_worker.pass_succeeded([_owner_result("failed")])
    assert not memory_worker.pass_succeeded([_owner_result("lock_lost")])
    assert not memory_worker.pass_succeeded([_owner_result(unavailable=2)])
    assert not memory_worker.pass_succeeded([_owner_result("failed"), _owner_result(timeout=1)])


def test_a_memory_pass_with_one_working_owner_is_a_success() -> None:
    assert memory_worker.pass_succeeded([_owner_result("failed"), _owner_result()])


def test_reconcile_all_returns_a_failed_result_for_an_owner_whose_pass_raised() -> None:
    owner_id = uuid4()

    class _Broken(MemoryReconciler):
        def __init__(self) -> None:
            pass

        def owners(self) -> list[UUID]:
            return [owner_id]

        def reconcile_owner(self, *_a: object, **_kw: object) -> ReconcileResult:
            raise RuntimeError("database down with SECRET")

    (result,) = _Broken().reconcile_all()

    assert result.owner_id == owner_id and result.status == "failed" and not result.healthy


@pytest.mark.parametrize(
    ("results", "marked"),
    [
        ([_owner_result("failed"), _owner_result(unavailable=1)], False),
        ([_owner_result("failed"), _owner_result()], True),
        ([], True),
    ],
)
def test_the_memory_worker_marks_a_pass_only_when_an_owner_pass_worked(
    tmp_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    results: list[ReconcileResult],
    marked: bool,
) -> None:
    async def fake_sleep(_seconds: float) -> None:
        raise _Stop

    async def fake_check(*_args: Any) -> bool:
        return True

    monkeypatch.setattr(
        memory_worker,
        "get_settings",
        lambda: _settings(memory_enabled=True, memory_provider="fake"),
    )
    monkeypatch.setattr(memory_worker, "create_session_factory", lambda _url, **_kw: None)
    monkeypatch.setattr(memory_worker, "build_provider", lambda _settings: None)
    monkeypatch.setattr(memory_worker, "_guarded", fake_check)
    monkeypatch.setattr(memory_worker, "run_pass", lambda **_kw: results)
    monkeypatch.setattr(memory_worker.asyncio, "sleep", fake_sleep)

    with pytest.raises(_Stop):
        asyncio.run(memory_worker.run_worker())

    assert (_last_success("memory") > 0) is marked


class _FakeDeliveryStore:
    """Rows are opaque tokens: the first `failing` of the claimed rows raise on lease renewal."""

    def __init__(self, claims: int, failing: int) -> None:
        self.rows: list[Any] = [object() for _ in range(claims)]
        self.failing = failing
        self.waiting = False

    def claim_due(self, *_args: object) -> list[Any]:
        return self.rows

    def renew_lease(self, claim: object, _lease: object) -> bool:
        if self.rows.index(claim) < self.failing:
            raise RuntimeError("database down")
        return False

    def failed_rows_waiting(self) -> bool:
        return self.waiting


def _push_service(claims: int, failing: int) -> tuple[Any, _FakeDeliveryStore]:
    """A delivery service whose first `failing` of `claims` rows raise unexpectedly."""

    store = _FakeDeliveryStore(claims, failing)
    service = PushDeliveryService(store, None, frozenset())  # type: ignore[arg-type]
    return service, store


@pytest.mark.parametrize(
    ("claims", "failing", "cycle_failed"),
    [(0, 0, False), (3, 0, False), (3, 2, False), (3, 3, True)],
)
def test_a_push_cycle_fails_only_when_every_delivery_raised(
    claims: int, failing: int, cycle_failed: bool
) -> None:
    service, _ = _push_service(claims, failing)

    assert service.run_once() == claims
    assert service.last_run_failed is cycle_failed


@pytest.mark.parametrize("waiting", [True, False])
def test_an_empty_push_poll_ends_a_failed_state_only_when_no_failed_row_waits(
    waiting: bool,
) -> None:
    service, store = _push_service(2, 2)
    assert service.run_once() == 2 and service.last_run_failed is True

    store.rows = []
    store.waiting = waiting

    assert service.run_once() == 0
    assert service.last_run_failed is waiting


def test_a_push_cycle_without_failures_ends_a_failed_state() -> None:
    service, store = _push_service(2, 2)
    assert service.run_once() == 2 and service.last_run_failed is True

    store.rows = [object(), object()]
    store.failing = 0

    assert service.run_once() == 2
    assert service.last_run_failed is False


def test_the_push_worker_does_not_mark_a_cycle_in_which_every_delivery_failed(
    tmp_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = SimpleNamespace(run_once=lambda: 2, last_run_failed=True)
    scheduler = SimpleNamespace(run_once=lambda: None)

    def fake_sleep(_seconds: float) -> None:
        raise _Stop

    monkeypatch.setattr(push_worker.time, "sleep", fake_sleep)

    with pytest.raises(_Stop):
        push_worker.run_worker(
            _settings(push_enabled=True), build=lambda _settings: (service, scheduler)
        )

    assert _last_success("push") == 0
