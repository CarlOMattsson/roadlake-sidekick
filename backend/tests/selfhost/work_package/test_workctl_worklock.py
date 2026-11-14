"""The lock of a flow that is started without work.sh."""

import fcntl
import os
from pathlib import Path

import pytest
from tools.workctl import backupflow, worklock

from tests.selfhost.work_package.fakestack import FakeStack


def _stack(tmp_path: Path, *, held: bool = False) -> FakeStack:
    stack = FakeStack(tmp_path)
    if held:
        stack.environ[worklock.HELD_VARIABLE] = "1"
    return stack


def _take_elsewhere(stack: FakeStack) -> int:
    """Another process's hold of the lock: a separate open file description of the same file."""
    fd = os.open(stack.work / worklock.LOCK_FILE, os.O_RDWR | os.O_CREAT)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    os.write(fd, b"PID 4242: update\n")
    return fd


def test_the_lock_is_taken_for_the_flow_and_names_its_holder(tmp_path: Path) -> None:
    stack = _stack(tmp_path)
    seen: list[str] = []

    def flow() -> int:
        seen.append((stack.work / worklock.LOCK_FILE).read_text(encoding="utf-8"))
        return 0

    assert worklock.run_locked(stack, "backup", flow) == 0
    assert seen == [f"PID {os.getpid()}: backup\n"]
    other = _take_elsewhere(stack)  # free again once the flow ended
    os.close(other)


def test_a_busy_lock_refuses_the_flow_with_a_message_and_changes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stack = _stack(tmp_path)
    other = _take_elsewhere(stack)
    try:
        assert backupflow.run_backup(stack) == 1
    finally:
        os.close(other)
    error = capsys.readouterr().err
    assert "PID 4242: update" in error and "Nothing changed" in error
    assert stack.calls == []


def test_a_caller_that_holds_the_lock_is_not_locked_out_by_it(tmp_path: Path) -> None:
    stack = _stack(tmp_path, held=True)
    other = _take_elsewhere(stack)
    try:
        assert worklock.run_locked(stack, "backup", lambda: 7) == 7
    finally:
        os.close(other)


def test_a_command_that_only_reads_takes_no_lock(tmp_path: Path) -> None:
    stack = _stack(tmp_path)
    other = _take_elsewhere(stack)
    try:
        assert worklock.run_locked(stack, "restore --apply", lambda: 0, needed=False) == 0
    finally:
        os.close(other)
