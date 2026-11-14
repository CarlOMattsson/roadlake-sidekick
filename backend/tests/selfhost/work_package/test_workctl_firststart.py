"""The hint after a failed first start, gathered through the stack.

The decisions themselves are tested in test_workctl_diagnose."""

from pathlib import Path

import pytest
from tools.workctl import firststart

from tests.selfhost.work_package.fakestack import FakeStack

AUTH = 'FATAL: password authentication failed for user "sidekick_migrator"'
MIGRATE_LOG = "logs --no-color --tail 80 migrate"
TABLE = "coalesce(to_regclass"
COUNT = "select count(*)"
VOLUMES = "volume ls"


def _stack(tmp_path: Path, replies: dict[str, str | None]) -> FakeStack:
    def answer(call: str) -> str | None:
        for part, reply in replies.items():
            if part in call:
                return reply
        return ""

    return FakeStack(tmp_path, answer)


def test_an_unmigrated_database_after_a_role_failure_names_the_volume(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stack = _stack(tmp_path, {MIGRATE_LOG: AUTH, TABLE: "absent", VOLUMES: "p_pgdata\n"})
    firststart.print_hint(stack, 0)
    assert "docker volume rm p_pgdata" in capsys.readouterr().err


def test_only_the_lines_of_this_start_count_as_evidence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stack = _stack(tmp_path, {TABLE: "absent", VOLUMES: "p_pgdata\n"})
    stack.log.write_text(AUTH + "\nsecond\n", encoding="utf-8")
    firststart.print_hint(stack, 2)
    assert capsys.readouterr().err == ""
    firststart.print_hint(stack, 0)
    assert "docker volume rm p_pgdata" in capsys.readouterr().err


@pytest.mark.parametrize(
    "replies",
    [
        {TABLE: None},
        {TABLE: "_yoyo_migration", COUNT: None},
        {TABLE: "_yoyo_migration", COUNT: "4"},
        {TABLE: "something_else"},
        {TABLE: "absent", VOLUMES: None},
    ],
)
def test_an_unknown_or_used_database_gets_no_hint(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], replies: dict[str, str | None]
) -> None:
    stack = _stack(tmp_path, {MIGRATE_LOG: AUTH, VOLUMES: "p_pgdata\n", **replies})
    firststart.print_hint(stack, 0)
    assert capsys.readouterr().err == ""
