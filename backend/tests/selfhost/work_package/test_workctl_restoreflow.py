"""The restore flow: the checks first, the way back, the swap, and what a failing step undoes."""

import re
import signal
from pathlib import Path

import pytest
from tools.workctl import restore, restoreflow

from tests.selfhost.work_package.fakestack import (
    START_HINDSIGHT,
    START_WRITERS,
    STOP_HINDSIGHT,
    STOP_WRITERS,
    FakeStack,
    Healthy,
)

STAMP = "20260101-000000"
OLD = "sidekick_before_restore_"
ARCHIVE = "crypto decrypt | tar -tz"
LOAD = "--single-transaction"
UNPACK = "docker run --rm -i --network none"
MIGRATE = "compose run --rm -T --no-deps migrate"
OWNER_ID = "7e57d0e5-aaaa-4bbb-8ccc-dddddddddddd"


class Databases(Healthy):
    """A healthy stack that also keeps the names of the databases through a restore's renames."""

    def __init__(self, fail: tuple[str, ...] = (), *, fail_once: str = "") -> None:
        super().__init__(fail)
        self.names = ["sidekick"]
        self.fail_once = fail_once

    def __call__(self, call: str) -> object:
        if self.fail_once and self.fail_once in call:
            self.fail_once = ""
            return False
        failed = any(part in call for part in self.fail)
        rename = re.search(r"RENAME TO (\w+)", call)
        if not failed and rename:
            # The rename leaves the renamed database as the only one.
            self.names = [rename.group(1)]
        if not failed and "CREATE DATABASE sidekick" in call:
            self.names = [*self.names, "sidekick"]
        if "FROM pg_database" in call and not failed:
            return "\n".join(self.names) + "\n"
        if "username = 'jobb'" in call:
            return OWNER_ID + "\n"
        return super().__call__(call)


@pytest.fixture(autouse=True)
def _desktop(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The owner and the Claude Desktop entry are tested on their own; here they are recorded."""
    done: list[str] = []
    monkeypatch.setattr(
        restoreflow.desktopsetup, "desktop_setup", lambda stack: done.append("setup")
    )
    monkeypatch.setattr(
        restoreflow.desktopsetup,
        "publish_owner",
        lambda stack, user_id: done.append(f"owner {user_id}"),
    )
    monkeypatch.setattr(
        restoreflow.desktopsetup, "drop_owner", lambda stack: done.append("no owner")
    )
    return done


def _answer(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    monkeypatch.setattr(restoreflow.prompts, "ask", lambda _prompt, **_kwargs: text)


def _stack(tmp_path: Path, answer: Healthy | None = None, *, memory: bool = True) -> FakeStack:
    stack = FakeStack(tmp_path, answer or Databases(), memory=memory)
    (stack.selfhost / "restore-ownership.sql").write_text("-- owners\n", encoding="utf-8")
    stack.backup_key_file.write_text("A" * 43 + "=\n", encoding="utf-8")
    (stack.backups / f"sidekick-{STAMP}.sql.enc").write_bytes(b"dump")
    (stack.backups / f"hindsight-{STAMP}.tar.gz.enc").write_bytes(b"archive")
    return stack


def _first(stack: FakeStack, part: str) -> int:
    return next(i for i, call in enumerate(stack.calls) if part in call)


def _changes_nothing(stack: FakeStack) -> None:
    for call in stack.calls:
        assert not call.startswith(("compose stop", "compose up", "compose run")), call
        assert "pg_dump" not in call and "psql" not in call and UNPACK not in call, call


def test_without_a_set_the_usage_and_the_sets_there_are_shown(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stack = _stack(tmp_path)
    assert restoreflow.run_restore(stack, "", apply=False) == 2
    shown = capsys.readouterr()
    assert shown.out == "" and "usage: bash tools/work.sh restore" in shown.err
    assert STAMP in shown.err


def test_a_name_that_is_no_time_stamp_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stack = _stack(tmp_path)
    assert restoreflow.run_restore(stack, "yesterday", apply=True) == 2
    assert "yesterday" in capsys.readouterr().err
    assert stack.calls == []


def test_a_dry_run_shows_the_plan_and_changes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stack = _stack(tmp_path)
    assert restoreflow.run_restore(stack, STAMP, apply=False) == 0
    shown = capsys.readouterr()
    assert f"sidekick-{STAMP}.sql.enc" in shown.out and "Dry run" in shown.out
    _changes_nothing(stack)


@pytest.mark.parametrize("missing", ["sidekick", "hindsight"])
def test_a_set_with_a_missing_file_is_refused_before_anything_is_touched(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], missing: str
) -> None:
    stack = _stack(tmp_path)
    next(stack.backups.glob(f"{missing}-*")).unlink()
    assert restoreflow.run_restore(stack, STAMP, apply=True) == 1
    assert "incomplete" in capsys.readouterr().err
    _changes_nothing(stack)


def test_without_the_memory_only_the_database_file_is_needed(tmp_path: Path) -> None:
    stack = _stack(tmp_path, memory=False)
    next(stack.backups.glob("hindsight-*")).unlink()
    assert restoreflow.run_restore(stack, STAMP, apply=False) == 0


@pytest.mark.parametrize("unreadable", ["crypto decrypt", ARCHIVE])
def test_a_set_that_cannot_be_read_with_the_key_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], unreadable: str
) -> None:
    class Unreadable(Databases):
        def __call__(self, call: str) -> object:
            return False if call == unreadable else super().__call__(call)

    stack = _stack(tmp_path, Unreadable())
    assert restoreflow.run_restore(stack, STAMP, apply=True) == 1
    assert str(stack.backup_key_file) in capsys.readouterr().err
    _changes_nothing(stack)


def test_a_missing_key_is_refused_and_never_replaced(tmp_path: Path) -> None:
    stack = _stack(tmp_path)
    stack.backup_key_file.unlink()
    assert restoreflow.run_restore(stack, STAMP, apply=True) == 1
    assert not stack.backup_key_file.exists()
    _changes_nothing(stack)


def test_a_checkout_without_the_ownership_script_is_refused(tmp_path: Path) -> None:
    stack = _stack(tmp_path)
    (stack.selfhost / "restore-ownership.sql").unlink()
    assert restoreflow.run_restore(stack, STAMP, apply=True) == 1
    _changes_nothing(stack)


def test_without_a_memory_volume_to_replace_nothing_is_done(tmp_path: Path) -> None:
    stack = _stack(tmp_path, Databases(fail=("volume ls",)))
    assert restoreflow.run_restore(stack, STAMP, apply=True) == 1
    _changes_nothing(stack)


@pytest.mark.parametrize("typed", ["", "nej", "p ", "P"])
def test_only_the_project_name_typed_exactly_goes_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, typed: str
) -> None:
    _answer(monkeypatch, typed)
    stack = _stack(tmp_path)
    assert restoreflow.run_restore(stack, STAMP, apply=True) == 1
    _changes_nothing(stack)


def test_a_restore_takes_the_way_back_first_and_replaces_database_then_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _desktop: list[str]
) -> None:
    _answer(monkeypatch, "p")
    stack = _stack(tmp_path)
    assert restoreflow.run_restore(stack, STAMP, apply=True) == 0
    order = [
        STOP_WRITERS,
        "pg_dump",
        "RENAME TO sidekick_before_restore_",
        "CREATE DATABASE sidekick",
        LOAD,
        UNPACK,
        MIGRATE,
        START_WRITERS,
        "exec -T api python -c",
    ]
    positions = [_first(stack, part) for part in order]
    assert positions == sorted(positions), positions
    # Hindsight stops for the way-back copy and for the replacement, and starts again after each.
    assert stack.calls.count(STOP_HINDSIGHT) == 2 and stack.calls.count(START_HINDSIGHT) == 2
    assert stack.calls.index(STOP_HINDSIGHT, stack.calls.index(STOP_HINDSIGHT) + 1) < _first(
        stack, UNPACK
    )
    assert _desktop == [f"owner {OWNER_ID}", "setup"]
    assert len(list(stack.backups.glob("sidekick-*.sql.enc"))) == 2, "the way back is kept"


def test_the_dump_is_decrypted_on_the_way_in_and_never_written_plain(tmp_path: Path) -> None:
    stack = _stack(tmp_path)
    job = restoreflow.Restore(stack)
    assert job.restore_database(stack.backups / f"sidekick-{STAMP}.sql.enc", OLD + STAMP)
    load = next(call for call in stack.calls if LOAD in call)
    assert load.startswith("crypto decrypt | compose exec -T postgres psql")
    assert "VERBOSITY=sqlstate" in load


@pytest.mark.parametrize(
    ("failing", "unpackings"),
    [
        ("ALTER DATABASE sidekick RENAME", 0),
        (LOAD, 0),
        (UNPACK, 2),
        (MIGRATE, 2),
    ],
)
def test_before_the_commit_point_a_failure_puts_the_database_and_the_memory_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failing: str,
    unpackings: int,
) -> None:
    _answer(monkeypatch, "p")
    # The memory that is put back is unpacked by the same command: a failing unpacking fails once.
    answer = Databases(fail_once=failing) if failing == UNPACK else Databases(fail=(failing,))
    stack = _stack(tmp_path, answer)
    assert restoreflow.run_restore(stack, STAMP, apply=True) == 1
    assert answer.names == ["sidekick"], "the previous database is the one called sidekick again"
    assert len([call for call in stack.calls if UNPACK in call]) == unpackings
    assert stack.calls[-1] == START_WRITERS and START_HINDSIGHT in stack.calls
    assert "The restore failed" in capsys.readouterr().err


def test_a_rollback_that_fails_starts_nothing_and_says_where_everything_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class Stuck(Databases):
        def __call__(self, call: str) -> object:
            if "ALTER DATABASE" in call and "RENAME TO sidekick" in call and "DROP" in call:
                return False
            return super().__call__(call)

    _answer(monkeypatch, "p")
    stack = _stack(tmp_path, Stuck(fail=(MIGRATE,)))
    assert restoreflow.run_restore(stack, STAMP, apply=True) == 1
    # The way-back backup started Hindsight itself; after the migration nothing is started.
    after_the_failure = stack.calls[_first(stack, MIGRATE) :]
    assert START_WRITERS not in after_the_failure and START_HINDSIGHT not in after_the_failure
    error = capsys.readouterr().err
    assert "Could not put everything back" in error and OLD in error


@pytest.mark.parametrize("failing", [START_WRITERS, "exec -T api python -c"])
def test_after_the_commit_point_nothing_is_rolled_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failing: str,
) -> None:
    _answer(monkeypatch, "p")
    answer = Databases(fail=(failing,))
    stack = _stack(tmp_path, answer)
    stack.environ.update(SIDEKICK_WORK_READY_TIMEOUT="0", SIDEKICK_WORK_READY_POLL="0")
    assert restoreflow.run_restore(stack, STAMP, apply=True) == 1
    assert answer.names != ["sidekick"], "the restored database stays"
    assert not any("DROP DATABASE" in call for call in stack.calls)
    assert len([call for call in stack.calls if UNPACK in call]) == 1
    assert OLD in capsys.readouterr().err


def test_a_signal_during_the_unpacking_puts_everything_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Terminated(Databases):
        signalled = False

        def __call__(self, call: str) -> object:
            if UNPACK in call and not self.signalled:
                self.signalled = True
                stack.signals.pending = 143
            return super().__call__(call)

    _answer(monkeypatch, "p")
    answer = Terminated()
    stack = _stack(tmp_path, answer)
    assert restoreflow.run_restore(stack, STAMP, apply=True) == 143
    assert answer.names == ["sidekick"]
    assert len([call for call in stack.calls if UNPACK in call]) == 2, "unpacked, then put back"
    assert stack.calls[-1] == START_WRITERS


def test_a_signal_just_before_the_cleanup_does_not_cut_the_way_back_short(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class Terminated(Databases):
        def __call__(self, call: str) -> object:
            if MIGRATE in call:
                stack.signals.record(signal.SIGTERM)  # after the last check, before the cleanup
                return False
            if "DROP DATABASE IF EXISTS sidekick" in call:
                stack.signals.record(signal.SIGINT)  # and another one during the way back
            return super().__call__(call)

    _answer(monkeypatch, "p")
    answer = Terminated()
    stack = _stack(tmp_path, answer)
    assert restoreflow.run_restore(stack, STAMP, apply=True) == 143
    assert answer.names == ["sidekick"], "the previous database is back"
    assert len([call for call in stack.calls if UNPACK in call]) == 2, "the previous memory too"
    assert stack.calls[-1] == START_WRITERS
    assert "What was there before is back" in capsys.readouterr().err


def test_a_signal_while_the_name_is_asked_for_ends_the_restore_before_anything_is_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupted(_prompt: str, **_kwargs: object) -> str:
        stack.signals.record(signal.SIGINT)
        return "p"

    monkeypatch.setattr(restoreflow.prompts, "ask", interrupted)
    stack = _stack(tmp_path)
    assert restoreflow.run_restore(stack, STAMP, apply=True) == 130
    _changes_nothing(stack)


def test_a_restored_database_without_an_owner_drops_the_remembered_one(
    tmp_path: Path, _desktop: list[str]
) -> None:
    stack = _stack(tmp_path, Healthy())
    restoreflow.Restore(stack).sync_owner()
    assert _desktop == ["no owner"]


@pytest.mark.parametrize(
    ("existing", "action"),
    [
        (["sidekick", OLD + STAMP], restore.RENAME_BACK),
        ([OLD + STAMP], restore.RENAME_BACK),
        (["sidekick"], restore.KEEP),
        ([], restore.FAIL),
    ],
)
def test_the_swap_is_undone_by_what_exists(
    tmp_path: Path, existing: list[str], action: str
) -> None:
    class Names(Databases):
        def __call__(self, call: str) -> object:
            return "\n".join(existing) + "\n" if "FROM pg_database" in call else True

    stack = _stack(tmp_path, Names())
    job = restoreflow.Restore(stack)
    job.old_db = OLD + STAMP
    assert job.rollback_database() is (action != restore.FAIL)
    renamed_back = any("RENAME TO sidekick" in call for call in stack.calls)
    assert renamed_back is (action == restore.RENAME_BACK)
    assert job.old_db == ("" if action != restore.FAIL else OLD + STAMP)


def test_the_sets_a_restore_can_name_are_listed_on_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stack = _stack(tmp_path, memory=False)
    (stack.backups / "sidekick-20260102-000000.sql.enc").write_bytes(b"dump")
    restoreflow.print_sets(stack)
    shown = capsys.readouterr()
    assert shown.out == ""
    assert shown.err == f"Complete backup sets in {stack.backups}:\n  {STAMP}\n  20260102-000000\n"
    stack.memory = True
    restoreflow.print_sets(stack)
    assert capsys.readouterr().err == f"Complete backup sets in {stack.backups}:\n  {STAMP}\n"


def test_without_any_complete_set_that_is_said(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stack = _stack(tmp_path)
    for path in stack.backups.glob("*.enc"):
        path.unlink()
    restoreflow.print_sets(stack)
    assert (
        capsys.readouterr().err
        == f"No complete backup sets (database and memory with the same time) in {stack.backups}.\n"
    )
