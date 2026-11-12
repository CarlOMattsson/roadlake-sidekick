"""Reading work.env with tools/workctl: last assignment wins, surrounding quotes are stripped."""

from pathlib import Path

import pytest
from tools.workctl import cli, workenv


def _env(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "work.env"
    path.write_text(text, encoding="utf-8")
    return path


def test_env_value_of_a_missing_file_is_empty(tmp_path: Path) -> None:
    assert workenv.env_value(tmp_path / "absent.env", "KEY") == ""


def test_env_value_of_a_missing_key_is_empty(tmp_path: Path) -> None:
    assert workenv.env_value(_env(tmp_path, "OTHER=1\n"), "KEY") == ""


def test_env_value_returns_the_last_assignment(tmp_path: Path) -> None:
    assert workenv.env_value(_env(tmp_path, "KEY=one\nKEY=two\nOTHER=x\n"), "KEY") == "two"


def test_env_value_ignores_commented_assignments(tmp_path: Path) -> None:
    assert workenv.env_value(_env(tmp_path, "KEY=one\n# KEY=two\n"), "KEY") == "one"


def test_env_value_allows_leading_whitespace(tmp_path: Path) -> None:
    assert workenv.env_value(_env(tmp_path, "  \tKEY=one\n"), "KEY") == "one"


def test_env_value_keeps_spaces_and_equal_signs_inside_the_value(tmp_path: Path) -> None:
    assert workenv.env_value(_env(tmp_path, "KEY=a b = c \n"), "KEY") == "a b = c "


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('"two words"', "two words"),
        ("'two words'", "two words"),
        ("\"'nested'\"", "nested"),
        ('"unbalanced', '"unbalanced'),
        ('"', '"'),
        ('""', ""),
        ("", ""),
    ],
)
def test_env_value_strips_one_pair_of_quotes_of_each_kind(
    tmp_path: Path, raw: str, expected: str
) -> None:
    assert workenv.env_value(_env(tmp_path, f"KEY={raw}\n"), "KEY") == expected


def test_env_value_does_not_match_a_longer_key_name(tmp_path: Path) -> None:
    assert workenv.env_value(_env(tmp_path, "KEY_LONGER=x\n"), "KEY") == ""


def test_env_value_treats_the_key_as_literal_text(tmp_path: Path) -> None:
    assert workenv.env_value(_env(tmp_path, "KEYxA=1\nKEY.A=2\n"), "KEY.A") == "2"


def test_env_value_keeps_a_carriage_return_of_a_windows_file(tmp_path: Path) -> None:
    path = tmp_path / "work.env"
    path.write_bytes(b"KEY=value\r\n")
    assert workenv.env_value(path, "KEY") == "value\r"


@pytest.mark.parametrize("value", ["on", "ON", "true", "yes", "1", ""])
def test_memory_is_wanted_for_the_on_words_and_an_empty_value(tmp_path: Path, value: str) -> None:
    assert workenv.memory_wanted(_env(tmp_path, f"SIDEKICK_WORK_MEMORY={value}\n"))


@pytest.mark.parametrize("value", ["off", "OFF", "no", "0", "false", "maybe"])
def test_memory_is_not_wanted_for_anything_else(tmp_path: Path, value: str) -> None:
    assert not workenv.memory_wanted(_env(tmp_path, f"SIDEKICK_WORK_MEMORY={value}\n"))


def test_memory_is_wanted_when_the_setting_does_not_exist(tmp_path: Path) -> None:
    assert workenv.memory_wanted(_env(tmp_path, "OTHER=1\n"))
    assert workenv.memory_wanted(tmp_path / "absent.env")


def test_the_env_value_command_prints_the_value_and_a_newline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env_file = _env(tmp_path, "KEY='a b'\n")
    assert cli.main(["env-value", "--env-file", str(env_file), "--", "KEY"]) == 0
    assert capsys.readouterr().out == "a b\n"


def test_the_env_value_command_prints_an_empty_line_for_a_missing_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["env-value", "--env-file", str(tmp_path / "absent.env"), "KEY"]) == 0
    assert capsys.readouterr().out == "\n"


@pytest.mark.parametrize(("value", "code"), [("on", 0), ("off", 1)])
def test_the_memory_wanted_command_answers_with_its_exit_code(
    tmp_path: Path, value: str, code: int
) -> None:
    env_file = _env(tmp_path, f"SIDEKICK_WORK_MEMORY={value}\n")
    assert cli.main(["memory-wanted", "--env-file", str(env_file)]) == code
