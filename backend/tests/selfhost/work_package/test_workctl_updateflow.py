"""The update flow: what is put back before the migration, what is left alone after it.

Also the wait for the api to be ready."""

from pathlib import Path

import pytest
from tools.workctl import backupflow, readiness, updateflow
from tools.workctl.stack import Stop

from tests.selfhost.work_package.fakestack import (
    START_WRITERS,
    STOP_WRITERS,
    FakeStack,
    Healthy,
)

BEFORE = "a" * 40
AFTER = "b" * 40
IMAGE = "roadlake-sidekick:work"
MIGRATE = "compose run --rm -T --no-deps migrate"
BUILD = "compose build api"
RETAG = f"docker tag sha256:old {IMAGE}"
RESET = f"run git -C {{repo}} reset --keep {BEFORE}"


class Update(Healthy):
    """A healthy stack with a checkout that moves from ``BEFORE`` to ``AFTER`` when it is pulled."""

    def __init__(self, fail: tuple[str, ...] = (), *, class_status: int = 0) -> None:
        super().__init__(fail)
        self.head = BEFORE
        self.class_status = class_status

    def __call__(self, call: str) -> object:
        if any(part in call for part in self.fail):
            return False
        if call == "git rev-parse HEAD":
            return self.head
        if call == "git rev-parse --abbrev-ref HEAD":
            return "main"
        if call.endswith("pull --ff-only"):
            self.head = AFTER
            return True
        if call.endswith("reset --keep " + BEFORE):
            self.head = BEFORE
            return True
        if "check-release-migration-class.py" in call:
            return self.class_status
        if call.startswith("docker image inspect"):
            return "sha256:old\n"
        if call.startswith("compose exec -T api python -c"):
            return True
        return super().__call__(call)


def _stack(tmp_path: Path, answer: Update | None = None) -> FakeStack:
    stack = FakeStack(tmp_path, answer or Update())
    (stack.work / "work.env").write_text("SIDEKICK_WORK_ENABLED=1\n", encoding="utf-8")
    (stack.work / "gateway.haproxy.cfg").write_text("global\n# @ALLOWLIST@\n", encoding="utf-8")
    (stack.selfhost / "postgres-init.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    return stack


@pytest.fixture(autouse=True)
def _desktop_setup(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """The Claude Desktop setup is tested on its own; here it only records that it ran."""
    done: list[Path] = []
    monkeypatch.setattr(
        updateflow.desktopsetup, "desktop_setup", lambda stack: done.append(stack.repo)
    )
    return done


def _run(stack: FakeStack, *, allow_breaking: bool = False) -> int:
    return updateflow.run_update(stack, allow_breaking, [])


def _count(stack: FakeStack, part: str) -> int:
    return sum(part in call for call in stack.calls)


def test_a_good_update_keeps_the_writers_stopped_until_the_new_version_is_ready(
    tmp_path: Path, _desktop_setup: list[Path]
) -> None:
    stack = _stack(tmp_path)
    assert _run(stack) == 0
    assert _desktop_setup == [stack.repo]
    calls = stack.calls
    assert calls.index(f"docker tag sha256:old {IMAGE.replace('work', 'previous')}") < calls.index(
        BUILD
    )
    assert calls.index(BUILD) < calls.index(STOP_WRITERS) < _first(calls, "pg_dump")
    assert _first(calls, "pg_dump") < calls.index(MIGRATE)
    assert calls.index(MIGRATE) < _first(calls, "--force-recreate")
    assert START_WRITERS not in calls
    assert (stack.gen / ".gateway.applied").is_file()
    assert (stack.gen / "build-info.json").is_file()


def _first(calls: list[str], part: str) -> int:
    return next(i for i, call in enumerate(calls) if part in call)


def test_a_failed_build_puts_the_old_image_name_and_nothing_else_back(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stack = _stack(tmp_path, Update(fail=(BUILD,)))
    assert _run(stack) == 1
    assert STOP_WRITERS not in stack.calls
    assert RETAG in stack.calls
    assert "the previous version keeps running" in capsys.readouterr().err


@pytest.mark.parametrize("failing", ["pg_dump", "--network none"])
def test_a_failed_backup_puts_the_code_the_image_and_the_writers_back(
    tmp_path: Path, failing: str
) -> None:
    answer = Update(fail=(failing,))
    stack = _stack(tmp_path, answer)
    assert _run(stack) == 1
    assert answer.head == BEFORE
    assert MIGRATE not in stack.calls
    assert stack.calls.index(RETAG) < stack.calls.index(START_WRITERS)


def test_a_refused_migration_class_puts_the_code_back_before_anything_is_stopped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    answer = Update(class_status=1)
    stack = _stack(tmp_path, answer)
    assert _run(stack) == 1
    assert answer.head == BEFORE
    assert BUILD not in stack.calls and STOP_WRITERS not in stack.calls
    assert "migrations" in capsys.readouterr().err


def test_a_class_check_that_cannot_run_is_not_a_refusal_of_the_class(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stack = _stack(tmp_path, Update(class_status=2))
    assert _run(stack) == 1
    assert "could not check the migration class" in capsys.readouterr().err


def test_an_update_to_the_same_commit_asks_nothing_of_the_class_check(tmp_path: Path) -> None:
    class Same(Update):
        def __call__(self, call: str) -> object:
            if call.endswith("pull --ff-only"):
                return True
            return super().__call__(call)

    stack = _stack(tmp_path, Same())
    assert _run(stack) == 0
    assert _count(stack, "check-release-migration-class.py") == 0


def test_a_breaking_update_is_declared_as_such(tmp_path: Path) -> None:
    stack = _stack(tmp_path)
    assert _run(stack, allow_breaking=True) == 0
    check = next(call for call in stack.calls if "check-release-migration-class.py" in call)
    assert "--release-class breaking" in check and f"--installed {BEFORE}" in check


def test_the_message_of_a_refused_class_check_is_chosen_by_the_exit_status() -> None:
    assert updateflow.migration_refusal(1) == "up_contract"
    assert updateflow.migration_refusal(2) == "up_class_fail"
    assert updateflow.migration_refusal(127) == "up_class_fail"


def test_a_code_that_cannot_be_put_back_names_the_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    class Stuck(Update):
        def __call__(self, call: str) -> object:
            return 1 if "reset --keep" in call else super().__call__(call)

    stack = _stack(tmp_path, Stuck(class_status=1))
    assert _run(stack) == 1
    assert f"reset --keep {BEFORE}" in capsys.readouterr().err


def test_a_retag_that_fails_is_said_plainly_and_the_old_version_is_not_claimed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stack = _stack(tmp_path, Update(fail=(RETAG, "pg_dump")))
    assert _run(stack) == 1
    shown = capsys.readouterr()
    assert "WARNING" in shown.err and "is NOT running" in shown.err
    assert "the previous version runs again" not in shown.out + shown.err


@pytest.mark.parametrize(
    "failing",
    [MIGRATE, "--force-recreate", "compose up -d --wait --wait-timeout 420"],
)
def test_from_the_migration_on_nothing_is_restored_and_the_writers_stay_stopped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], failing: str
) -> None:
    answer = Update(fail=(failing,))
    stack = _stack(tmp_path, answer)
    assert _run(stack) == 1
    assert answer.head == AFTER, "the code is not moved back"
    assert START_WRITERS not in stack.calls
    assert RETAG not in stack.calls
    assert stack.calls[-1] == STOP_WRITERS, "whatever the failing step started is stopped again"
    error = capsys.readouterr().err
    assert str(stack.backups) in error and "nothing was rolled back automatically" in error
    assert f"git -C {stack.repo} checkout {BEFORE}" in error


def test_a_readiness_that_never_comes_leaves_the_writers_stopped(tmp_path: Path) -> None:
    class Slow(Update):
        def __call__(self, call: str) -> object:
            if call.startswith("compose exec -T api python -c"):
                return False
            return super().__call__(call)

    stack = _stack(tmp_path, Slow())
    stack.environ.update(SIDEKICK_WORK_READY_TIMEOUT="0", SIDEKICK_WORK_READY_POLL="0")
    assert _run(stack) == 1
    assert START_WRITERS not in stack.calls and stack.calls[-1] == STOP_WRITERS


def test_a_signal_during_the_recreate_leaves_the_writers_stopped_without_a_story(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    class Terminated(Update):
        def __call__(self, call: str) -> object:
            if "--force-recreate" in call:
                stack.signals.pending = 143
            return super().__call__(call)

    stack = _stack(tmp_path, Terminated())
    assert _run(stack) == 143
    assert stack.calls[-1] == STOP_WRITERS
    assert "nothing was rolled back" not in capsys.readouterr().err


def test_the_writers_are_the_workers_that_write(tmp_path: Path) -> None:
    assert backupflow.WRITERS == ("api", "memory-worker", "automation-worker")
    assert Stop(3).code == 3


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


@pytest.mark.parametrize(("ready_after", "ready"), [(0, True), (2, True), (99, False)])
def test_the_readiness_wait_polls_until_the_deadline(
    tmp_path: Path, ready_after: int, ready: bool
) -> None:
    clock = _Clock()
    tries: list[str] = []

    def answer(call: str) -> bool:
        tries.append(call)
        return len(tries) > ready_after

    stack = FakeStack(tmp_path, answer)
    stack.environ.update(SIDEKICK_WORK_READY_TIMEOUT="10", SIDEKICK_WORK_READY_POLL="3")
    assert readiness.wait_ready(stack, clock, clock.sleep) is ready
    assert all(call.startswith("compose exec -T api python -c") for call in tries)
    assert clock.slept == [3.0] * (len(tries) - 1)
    if not ready:
        assert len(tries) == 5, "tries at 0, 3, 6, 9 and 12 seconds"
