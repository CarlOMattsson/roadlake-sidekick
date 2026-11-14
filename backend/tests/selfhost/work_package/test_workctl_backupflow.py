"""The backup flow: its order, what a failure leaves behind and what always starts again."""

import signal
import stat
from pathlib import Path

import pytest
from tools.workctl import backupflow
from tools.workctl.stack import Stop

from tests.selfhost.work_package.fakestack import (
    START_HINDSIGHT,
    START_WRITERS,
    STOP_HINDSIGHT,
    STOP_WRITERS,
    FakeStack,
    Healthy,
)


def _stack(tmp_path: Path, answer: Healthy | None = None, *, memory: bool = True) -> FakeStack:
    return FakeStack(tmp_path, answer or Healthy(), memory=memory)


def _sets(stack: FakeStack) -> tuple[list[Path], list[Path]]:
    return sorted(stack.backups.glob("sidekick-*.sql.enc")), sorted(
        stack.backups.glob("hindsight-*.tar.gz.enc")
    )


def _order(stack: FakeStack, *parts: str) -> None:
    """Every part is in a call, and the calls come in this order."""
    positions = [next(i for i, call in enumerate(stack.calls) if part in call) for part in parts]
    assert positions == sorted(positions), positions


def test_a_backup_is_both_copies_with_one_stamp_between_a_pause_and_a_start(tmp_path: Path) -> None:
    stack = _stack(tmp_path)
    assert backupflow.run_backup(stack) == 0
    (db,), (mem,) = _sets(stack)
    assert db.name.removeprefix("sidekick-").removesuffix(".sql.enc") == (
        mem.name.removeprefix("hindsight-").removesuffix(".tar.gz.enc")
    )
    assert stat.S_IMODE(db.stat().st_mode) == stat.S_IMODE(mem.stat().st_mode) == 0o600
    assert stat.S_IMODE(stack.backups.stat().st_mode) == 0o700
    assert not list(stack.backups.glob("*.part"))
    _order(
        stack,
        STOP_WRITERS,
        "pg_dump",
        STOP_HINDSIGHT,
        "--network none",
        START_HINDSIGHT,
        "tar -tz",
        START_WRITERS,
    )
    assert stack.calls.count(STOP_WRITERS) == 1 == stack.calls.count(START_WRITERS)


def test_each_file_is_flushed_before_it_is_renamed_and_the_directory_after_it(
    tmp_path: Path,
) -> None:
    stack = _stack(tmp_path)
    assert backupflow.run_backup(stack) == 0
    (db,), (mem,) = _sets(stack)
    assert stack.synced[:2] == [db.with_name(db.name + ".part"), stack.backups]
    assert stack.synced[2:4] == [mem.with_name(mem.name + ".part"), stack.backups]


def test_nothing_is_paused_when_no_writer_is_running(tmp_path: Path) -> None:
    stack = _stack(tmp_path, Healthy(running=()))
    assert backupflow.run_backup(stack) == 0
    assert not any(
        call.startswith("compose stop api") or call == START_WRITERS for call in stack.calls
    )


def test_without_the_memory_only_the_database_is_copied(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stack = _stack(tmp_path, memory=False)
    assert backupflow.run_backup(stack) == 0
    assert _sets(stack)[1] == []
    assert not any("hindsight" in call or "volume ls" in call for call in stack.calls)
    assert "only the database" in capsys.readouterr().out


def test_without_a_memory_volume_yet_only_the_database_is_copied(tmp_path: Path) -> None:
    stack = _stack(tmp_path, Healthy(fail=("volume ls",)))
    assert backupflow.run_backup(stack) == 0
    assert _sets(stack)[1] == []
    assert STOP_HINDSIGHT not in stack.calls


@pytest.mark.parametrize(
    ("failing", "hindsight_stopped"),
    [("pg_dump", False), ("--network none", True), (STOP_HINDSIGHT, True)],
)
def test_a_failed_copy_keeps_no_file_and_starts_everything_again(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], failing: str, hindsight_stopped: bool
) -> None:
    stack = _stack(tmp_path, Healthy(fail=(failing,)))
    assert backupflow.run_backup(stack) == 1
    assert _sets(stack) == ([], [])
    assert not list(stack.backups.glob("*.part"))
    assert stack.calls.count(START_WRITERS) == 1
    assert (START_HINDSIGHT in stack.calls) is hindsight_stopped
    assert "The backup failed" in capsys.readouterr().err


@pytest.mark.parametrize("failing", ["crypto decrypt", "crypto decrypt | tar -tz"])
def test_a_copy_that_cannot_be_read_back_does_not_count(tmp_path: Path, failing: str) -> None:
    class Unreadable(Healthy):
        def __call__(self, call: str) -> object:
            return False if call == failing else super().__call__(call)

    stack = _stack(tmp_path, Unreadable())
    assert backupflow.run_backup(stack) == 1
    assert _sets(stack) == ([], [])


def test_a_dump_without_its_end_marker_does_not_count(tmp_path: Path) -> None:
    class Cut(Healthy):
        def __call__(self, call: str) -> object:
            return b"-- cut off\n" if call == "crypto decrypt" else super().__call__(call)

    stack = _stack(tmp_path, Cut())
    assert backupflow.run_backup(stack) == 1
    assert _sets(stack) == ([], [])


def test_a_failed_restart_of_the_writers_is_tried_again_by_the_cleanup(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stack = _stack(tmp_path, Healthy(fail=(START_WRITERS,)))
    assert backupflow.run_backup(stack) == 1
    assert stack.calls.count(START_WRITERS) == 2
    assert "did not start again" in capsys.readouterr().err
    assert _sets(stack)[0], "the finished files are kept"


def test_a_signal_during_the_archive_ends_the_backup_after_the_cleanup(tmp_path: Path) -> None:
    class Terminated(Healthy):
        def __call__(self, call: str) -> object:
            if "--network none" in call:
                stack.signals.pending = 143
            return super().__call__(call)

    stack = _stack(tmp_path, Terminated())
    assert backupflow.run_backup(stack) == 143
    assert _sets(stack) == ([], [])
    assert START_HINDSIGHT in stack.calls and START_WRITERS in stack.calls
    assert not list(stack.backups.glob("*.part"))


def test_signals_during_the_cleanup_do_not_stop_it_from_starting_everything_again(
    tmp_path: Path,
) -> None:
    class Terminated(Healthy):
        def __call__(self, call: str) -> object:
            if "--network none" in call:
                stack.signals.record(signal.SIGTERM)
            if call == START_HINDSIGHT:
                stack.signals.record(signal.SIGINT)
            return super().__call__(call)

    stack = _stack(tmp_path, Terminated())
    assert backupflow.run_backup(stack) == 143
    assert stack.calls[-1] == START_WRITERS


def test_writers_that_cannot_be_told_apart_stop_the_backup_before_anything_changes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    class Unknown(Healthy):
        def __call__(self, call: str) -> object:
            return None if call == "live api" else super().__call__(call)

    stack = _stack(tmp_path, Unknown())
    assert backupflow.run_backup(stack) == 1
    assert not any("pg_dump" in call for call in stack.calls)
    assert "api memory-worker automation-worker" in capsys.readouterr().err


def test_a_writer_that_is_still_active_after_the_stop_ends_the_backup(tmp_path: Path) -> None:
    class Stubborn(Healthy):
        def __call__(self, call: str) -> object:
            if call.startswith("compose stop "):
                return True
            return super().__call__(call)

    stack = _stack(tmp_path, Stubborn())
    assert backupflow.run_backup(stack) == 1
    assert not any("pg_dump" in call for call in stack.calls)
    assert stack.calls.count(START_WRITERS) == 1, "the cleanup starts what was stopped"


@pytest.mark.parametrize("keep", ["0", "x", "-1", ""])
def test_a_bad_number_of_sets_to_keep_changes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], keep: str
) -> None:
    stack = _stack(tmp_path)
    stack.environ["SIDEKICK_WORK_KEEP_BACKUPS"] = keep
    assert backupflow.run_backup(stack) == 1
    assert stack.calls == []
    assert keep in capsys.readouterr().err


def test_only_the_newest_sets_are_kept_and_the_new_one_is_never_pruned(tmp_path: Path) -> None:
    stack = _stack(tmp_path)
    stack.environ["SIDEKICK_WORK_KEEP_BACKUPS"] = "2"
    stack.backups.mkdir(exist_ok=True)
    stack.backup_key_file.write_text("x" * 43 + "=\n", encoding="utf-8")
    for day in range(1, 5):
        for name in (
            f"sidekick-2026010{day}-000000.sql.enc",
            f"hindsight-2026010{day}-000000.tar.gz.enc",
        ):
            (stack.backups / name).write_text("x", encoding="utf-8")
    assert backupflow.run_backup(stack) == 0
    dumps, archives = _sets(stack)
    assert dumps[0].name == "sidekick-20260104-000000.sql.enc"
    assert len(dumps) == len(archives) == 2


def test_a_failed_set_prunes_nothing(tmp_path: Path) -> None:
    stack = _stack(tmp_path, Healthy(fail=("pg_dump",)))
    stack.environ["SIDEKICK_WORK_KEEP_BACKUPS"] = "1"
    stack.backup_key_file.write_text("x" * 43 + "=\n", encoding="utf-8")
    for day in (1, 2):
        (stack.backups / f"sidekick-2026010{day}-000000.sql.enc").write_text("x", encoding="utf-8")
    assert backupflow.run_backup(stack) == 1
    assert len(_sets(stack)[0]) == 2


def test_take_leaves_the_writers_paused_for_the_caller(tmp_path: Path) -> None:
    stack = _stack(tmp_path)
    backup = backupflow.Backup(stack, "7")
    backup.take()
    assert backup.paused == list(backupflow.WRITERS)
    assert backup.db is not None and backup.db.is_file()
    assert backup.mem is not None and backup.mem.is_file()
    assert START_WRITERS not in stack.calls
    backup.abort()
    assert START_WRITERS in stack.calls and backup.paused == []


def test_a_missing_key_with_backups_in_place_is_never_replaced(tmp_path: Path) -> None:
    stack = _stack(tmp_path)
    stack.backups.mkdir(exist_ok=True)
    (stack.backups / "sidekick-20260101-000000.sql.enc").write_text("x", encoding="utf-8")
    with pytest.raises(Stop) as stop:
        backupflow.Backup(stack, "7").take()
    assert stop.value.code == 1
    assert not stack.backup_key_file.exists()
    assert stack.calls == []


def _free(monkeypatch: pytest.MonkeyPatch, value: int | None) -> None:
    monkeypatch.setattr(backupflow.backupfiles, "free_bytes", lambda _directory: value)


def test_too_little_room_stops_the_backup_before_anything_is_paused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    floor = 64 * 1048576
    _free(monkeypatch, 1000)
    stack = _stack(tmp_path)
    assert backupflow.run_backup(stack) == 1
    assert f"1000 bytes free, {floor} needed" in capsys.readouterr().err
    assert stack.calls == []


def test_a_free_size_that_cannot_be_read_stops_the_backup_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _free(monkeypatch, None)
    stack = _stack(tmp_path)
    assert backupflow.run_backup(stack) == 1
    assert "Could not tell whether there is room" in capsys.readouterr().err
    assert stack.calls == []


def test_the_first_backup_creates_the_key_and_reports_it_without_its_content(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stack = _stack(tmp_path)
    assert not stack.backup_key_file.exists()
    assert backupflow.run_backup(stack) == 0
    key = stack.backup_key_file.read_text(encoding="ascii").strip()
    out = capsys.readouterr().out
    assert f"A new key for the backups was created: {stack.backup_key_file}" in out
    assert key not in out
    assert stat.S_IMODE(stack.backup_key_file.stat().st_mode) == 0o600
