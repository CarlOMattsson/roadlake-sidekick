"""The restore, prompt and owner-account checks of tools/workctl."""

import io
import sys
from pathlib import Path

import pytest
from tools.workctl import cli, owner, prompts, restore


def _backups(tmp_path: Path, files: dict[str, str]) -> Path:
    for name, content in files.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    return tmp_path


def test_a_set_needs_the_memory_archive_only_when_the_memory_is_on(tmp_path: Path) -> None:
    directory = _backups(
        tmp_path,
        {
            "sidekick-20261101-100000.sql.enc": "db",
            "sidekick-20261102-100000.sql.enc": "db",
            "hindsight-20261102-100000.tar.gz.enc": "mem",
            "sidekick-20261103-100000.sql.enc": "db",
            "hindsight-20261103-100000.tar.gz.enc": "",
            "hindsight-20261104-100000.tar.gz.enc": "mem",
        },
    )
    assert restore.complete_sets(directory, memory=True) == ["20261102-100000"]
    assert restore.complete_sets(directory, memory=False) == [
        "20261101-100000",
        "20261102-100000",
        "20261103-100000",
    ]


def test_no_sets_in_a_missing_directory(tmp_path: Path) -> None:
    assert restore.complete_sets(tmp_path / "absent", memory=False) == []


@pytest.mark.parametrize(
    ("argument", "expected"),
    [
        ("20261102-100000", ("/b", "20261102-100000")),
        ("sidekick-20261102-100000.sql.enc", (".", "20261102-100000")),
        ("hindsight-20261102-100000.tar.gz.enc", (".", "20261102-100000")),
        ("/x/y/sidekick-20261102-100000.sql.enc", ("/x/y", "20261102-100000")),
        ("rel/hindsight-20261102-100000.tar.gz.enc", ("rel", "20261102-100000")),
        ("/sidekick-20261102-100000.sql.enc", ("/", "20261102-100000")),
        ("dir/20261102-100000", ("dir", "20261102-100000")),
        ("sidekick-hindsight-20261102-100000.sql.enc", (".", "20261102-100000")),
    ],
)
def test_a_reference_names_its_directory_and_time_stamp(
    argument: str, expected: tuple[str, str]
) -> None:
    assert restore.parse_reference(argument, "/b") == expected


@pytest.mark.parametrize(
    "argument",
    [
        "",
        "latest",
        "2026-11-02",
        "20261102-1000",
        "20261102-100000x",
        "sidekick-x.sql.enc",
        "a/",
        "x/y\n",
    ],
)
def test_anything_that_is_not_a_time_stamp_names_nothing(argument: str) -> None:
    assert restore.parse_reference(argument, "/b") is None


def test_a_trailing_newline_is_not_part_of_a_time_stamp() -> None:
    assert restore.parse_reference("20261102-100000\n", "/b") is None


@pytest.mark.parametrize(
    ("existing", "action"),
    [
        (["sidekick", "old"], restore.RENAME_BACK),
        (["old"], restore.RENAME_BACK),
        (["sidekick"], restore.KEEP),
        ([], restore.FAIL),
        (["sidekick_other"], restore.FAIL),
        (["old_not"], restore.FAIL),
    ],
)
def test_the_rollback_follows_which_database_names_exist(existing: list[str], action: str) -> None:
    assert restore.rollback_action(existing, "old") == action


@pytest.mark.parametrize("answer", ["j", "J", "y", "Y", "ja", "JA", "yes", "YES", "Yes"])
def test_these_answers_are_yes(answer: str) -> None:
    assert prompts.is_yes(answer)


@pytest.mark.parametrize("answer", ["", "n", "no", "N", "Ja", "yEs", "jaa", " y", "y ", "1"])
def test_everything_else_is_no(answer: str) -> None:
    assert not prompts.is_yes(answer)


@pytest.mark.parametrize(
    ("answer", "chosen"),
    [
        ("1", "a"),
        ("3", "c"),
        ("01", "a"),
        ("0", "0"),
        ("4", "4"),
        ("", ""),
        ("my-model", "my-model"),
        ("2x", "2x"),
        ("-1", "-1"),
        ("²", "²"),
    ],
)
def test_a_number_picks_from_the_list_and_anything_else_is_taken_as_typed(
    answer: str, chosen: str
) -> None:
    assert prompts.pick_choice(answer, ["a", "b", "c"]) == chosen


def test_an_empty_list_takes_every_answer_as_typed() -> None:
    assert prompts.pick_choice("1", []) == "1"


@pytest.mark.parametrize(
    "value",
    ["123e4567-e89b-12d3-a456-426614174000", "123E4567-E89B-12D3-A456-426614174000"],
)
def test_a_uuid_is_recognised_in_either_case(value: str) -> None:
    assert owner.is_uuid(value)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "123e4567-e89b-12d3-a456-42661417400",
        "123e4567-e89b-12d3-a456-4266141740000",
        "123e4567e89b12d3a456426614174000",
        "123e4567-e89b-12d3-a456-42661417400g",
        "123e4567-e89b-12d3-a456-426614174000\n",
        "x\n123e4567-e89b-12d3-a456-426614174000",
        "123e4567-e89b-12d3-a456-426614174000' or '1'='1",
    ],
)
def test_anything_else_is_not_a_uuid(value: str) -> None:
    assert not owner.is_uuid(value)


def test_the_commands_answer_with_exit_codes_and_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["is-uuid", "--", "123e4567-e89b-12d3-a456-426614174000"]) == 0
    assert cli.main(["is-uuid", "--", "nope"]) == 1
    assert cli.main(["is-yes", "--", "ja"]) == 0
    assert cli.main(["is-yes", "--", "-n"]) == 1
    capsys.readouterr()

    assert cli.main(["pick", "--answer=2", "--", "-first", "second"]) == 0
    assert capsys.readouterr().out == "second\n"
    assert cli.main(["pick", "--answer=-x", "--"]) == 0
    assert capsys.readouterr().out == "-x\n"

    monkeypatch.setattr(sys, "stdin", io.StringIO("sidekick\nold\n"))
    assert cli.main(["rollback-action", "--old", "old"]) == 0
    assert capsys.readouterr().out == "rename-back\n"

    ref_args = ["restore-ref", "--lang", "en", "--backups", str(tmp_path)]
    assert cli.main([*ref_args, "--", "20261102-100000"]) == 0
    assert capsys.readouterr().out == f"{tmp_path}\n20261102-100000\n"
    assert cli.main([*ref_args, "--", "latest"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("latest is neither a time stamp (YYYYMMDD-HHMMSS)")


def test_the_backup_sets_command_lists_them_or_says_there_are_none(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["backup-sets", "--lang", "en", "--dir", str(tmp_path), "--memory", "off"]
    assert cli.main(args) == 0
    assert capsys.readouterr().out == (
        f"No complete backup sets (database and memory with the same time) in {tmp_path}.\n"
    )
    _backups(
        tmp_path,
        {"sidekick-20261102-100000.sql.enc": "db", "sidekick-20261101-100000.sql.enc": "db"},
    )
    assert cli.main(args) == 0
    assert capsys.readouterr().out == (
        f"Complete backup sets in {tmp_path}:\n  20261101-100000\n  20261102-100000\n"
    )
    assert cli.main([*args[:-1], "on"]) == 0
    assert "No complete backup sets" in capsys.readouterr().out
