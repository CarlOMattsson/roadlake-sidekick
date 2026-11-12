"""The lock that keeps two changing commands from running at once."""

import fcntl
import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.selfhost.work_package.support import (
    RESTORE_STAMP,
    SCRIPT,
    backup_set,
    changes_nothing,
    docker_calls,
    docker_calls_if_any,
    ready_repo,
    run_restore,
    run_work,
    write_env,
)
from tests.support.polling import wait_until


@pytest.fixture(name="held_flock")
def _held_flock(mini_repo: Path) -> Iterator[Path]:
    """Another process (this test) holds the operations lock, as a running restore would."""

    lock = mini_repo / "deploy" / "work" / ".work.lock"
    with lock.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        lock.write_text("PID 4242: restore --apply\n", encoding="utf-8")
        yield lock


@pytest.mark.parametrize("command", ["start", "stop", "backup", "update", "init", "restore"])
def test_a_second_changing_command_is_refused_while_one_holds_the_lock(
    mini_repo: Path, held_flock: Path, command: str
) -> None:
    """Nothing can start Hindsight or the writers in the middle of a restore."""

    work = _ready_without_lock(mini_repo, held_flock)
    backup_set(work)
    args = ["restore", RESTORE_STAMP, "--apply"] if command == "restore" else [command]
    for lang, text in (("sv", "pågår redan"), ("en", "already running")):
        result = run_work(mini_repo, *args, stdin="sidekick-work\n", SIDEKICK_WORK_LANG=lang)
        assert result.returncode == 1
        assert text in result.stderr and "PID 4242: restore --apply" in result.stderr
    changes_nothing(docker_calls_if_any(mini_repo))
    assert "4242" in held_flock.read_text(encoding="utf-8"), "the holder's line is kept"


def _ready_without_lock(repo: Path, held: Path) -> Path:
    """A ready repo while the lock is held elsewhere: init uses the fallback lock."""

    work = repo / "deploy" / "work"
    assert run_work(repo, "init", SIDEKICK_WORK_NO_FLOCK="1").returncode == 0
    write_env(
        repo, SIDEKICK_WORK_MODEL_BASE_URL="http://vllm:8000/v1", SIDEKICK_WORK_MEMORY_MODEL="m"
    )
    assert not (work / ".work.lock.d").exists()
    calls = repo / "docker-calls.txt"
    calls.unlink(missing_ok=True)
    assert held.exists()
    return work


def test_status_and_the_dry_run_take_no_lock(mini_repo: Path, held_flock: Path) -> None:
    work = _ready_without_lock(mini_repo, held_flock)
    backup_set(work)
    dry = run_work(mini_repo, "restore", RESTORE_STAMP)
    assert dry.returncode == 0, dry.stderr
    status = run_work(mini_repo, "status")
    assert "pågår redan" not in status.stderr


def test_the_mkdir_lock_refuses_a_live_holder_and_takes_over_a_stale_one(mini_repo: Path) -> None:
    """Without flock (macOS): a directory lock with the holder's PID, released on exit."""

    work = ready_repo(mini_repo)
    lock_dir = work / ".work.lock.d"
    lock_dir.mkdir()
    (lock_dir / "owner").write_text(f"PID {os.getpid()}: update\n", encoding="utf-8")
    result = run_work(mini_repo, "backup", SIDEKICK_WORK_NO_FLOCK="1", SIDEKICK_WORK_LANG="en")
    assert result.returncode == 1
    assert "already running" in result.stderr and f"PID {os.getpid()}: update" in result.stderr
    assert "pg_dump" not in docker_calls_if_any(mini_repo)

    gone = subprocess.Popen(["true"])
    gone.wait()
    (lock_dir / "owner").write_text(f"PID {gone.pid}: update\n", encoding="utf-8")
    result = run_work(mini_repo, "backup", SIDEKICK_WORK_NO_FLOCK="1")
    assert result.returncode == 0, result.stderr
    assert "pg_dump" in docker_calls(mini_repo)
    assert not lock_dir.exists(), "released on the way out"


def test_two_takers_of_one_stale_mkdir_lock_cannot_both_hold_it(tmp_path: Path) -> None:
    """Both read one stale lock; the slow one must not delete the lock the fast one just took."""

    # The real take_lock, sourced out of work.sh (never the script itself), with `kill` replaced so
    # that the slow taker pauses after it has judged the owner dead, the race window.
    text = SCRIPT.read_text(encoding="utf-8")
    start, end = text.index("lock_busy() {"), text.index("release_lock() {")
    names = ("lock.d", "gate", "paused", "holding", "done")
    lock_dir, gate, paused, holding, done = (tmp_path / n for n in names)
    harness = tmp_path / "harness.sh"
    harness.write_text(
        'errf() { echo "$1" >&2; }\n'
        f"LOCK_DIR={lock_dir}; LOCK_FILE={tmp_path}/lock; export SIDEKICK_WORK_NO_FLOCK=1\n"
        + text[start:end]
        + 'if [ "$1" = slow ]; then\n'
        f"  kill() {{ touch {paused}; while [ ! -e {gate} ]; do sleep 0.05; done; return 1; }}\n"
        "fi\n"
        'take_lock "$1"\n'
        f"touch {holding}-$1\n"
        f'while [ ! -e {done} ] && [ "$1" = fast ]; do sleep 0.05; done\n',
        encoding="utf-8",
    )
    gone = subprocess.Popen(["true"])
    gone.wait()
    lock_dir.mkdir()
    (lock_dir / "owner").write_text(f"PID {gone.pid}: update\n", encoding="utf-8")

    def wait_for(path: Path) -> None:
        wait_until(path.exists, timeout=10, what=f"{path.name} to appear", interval=0.05)

    slow = subprocess.Popen(["bash", str(harness), "slow"], stderr=subprocess.PIPE, text=True)
    wait_for(paused)  # the slow taker has read the stale owner and judged it dead
    fast = subprocess.Popen(["bash", str(harness), "fast"], stderr=subprocess.PIPE, text=True)
    try:
        wait_for(Path(f"{holding}-fast"))  # the fast taker took the stale lock and holds it
        gate.touch()  # now the slow one goes on with the stale verdict it formed earlier
        _, slow_err = slow.communicate(timeout=20)
        assert slow.returncode == 1, "the slow taker must be refused"
        assert not Path(f"{holding}-slow").exists()
        assert (lock_dir / "owner").read_text(encoding="utf-8").startswith(f"PID {fast.pid}:")
        assert not list(tmp_path.glob("lock.d.stale.*")), "no leftover renamed directory"
        assert slow_err
    finally:
        done.touch()
        fast.communicate(timeout=20)
        slow.kill()


def test_the_mkdir_lock_is_released_when_the_command_fails(mini_repo: Path) -> None:
    work = ready_repo(mini_repo)
    result = run_work(mini_repo, "backup", STUB_FAIL="database", SIDEKICK_WORK_NO_FLOCK="1")
    assert result.returncode == 1
    assert not (work / ".work.lock.d").exists()


def test_a_failing_restore_never_shows_or_logs_the_failing_row(mini_repo: Path) -> None:
    """psql quotes the rejected value in its messages; the restore asks for the error code only."""

    work = ready_repo(mini_repo)
    backup_set(work)
    result = run_restore(mini_repo, STUB_FAIL="load_leak")
    assert result.returncode == 1
    assert "Återställningen misslyckades vid" in result.stderr
    log = (work / "work.log").read_text(encoding="utf-8")
    assert "22P02" in log, "the error code is kept for diagnosis"
    for text in (result.stdout, result.stderr, log):
        assert "FAILING-ROW-VALUE-4711" not in text
    assert "VERBOSITY=sqlstate" in docker_calls(mini_repo)
