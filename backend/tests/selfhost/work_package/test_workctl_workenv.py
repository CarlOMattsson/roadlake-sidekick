"""Reading and editing work.env with tools/workctl; an edit touches only its own key."""

import stat
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


def test_set_value_replaces_an_active_line_and_keeps_the_rest(tmp_path: Path) -> None:
    path = _env(tmp_path, "# note\nKEY=old\nOTHER=1\n")
    workenv.set_value(path, "KEY", "new value")
    assert path.read_text(encoding="utf-8") == "# note\nKEY=new value\nOTHER=1\n"


def test_set_value_uncomments_the_first_commented_line(tmp_path: Path) -> None:
    path = _env(tmp_path, "A=1\n# KEY=example\n#KEY=other\nB=2\n")
    workenv.set_value(path, "KEY", "x")
    assert path.read_text(encoding="utf-8") == "A=1\nKEY=x\nB=2\n"


def test_set_value_appends_when_the_key_is_missing(tmp_path: Path) -> None:
    path = _env(tmp_path, "A=1")
    workenv.set_value(path, "KEY", "x")
    assert path.read_text(encoding="utf-8") == "A=1\nKEY=x\n"


def test_set_value_creates_a_missing_file(tmp_path: Path) -> None:
    path = tmp_path / "work.env"
    workenv.set_value(path, "KEY", "x")
    assert path.read_text(encoding="utf-8") == "KEY=x\n"


def test_set_value_does_not_touch_a_longer_key_and_takes_the_value_literally(
    tmp_path: Path,
) -> None:
    path = _env(tmp_path, "KEY_LONGER=1\n")
    workenv.set_value(path, "KEY", r"a\nb")
    assert path.read_text(encoding="utf-8") == "KEY_LONGER=1\nKEY=a\\nb\n"


def test_set_value_keeps_mode_600_and_leaves_no_temporary_file(tmp_path: Path) -> None:
    path = _env(tmp_path, "KEY=old\n")
    path.chmod(0o644)
    workenv.set_value(path, "KEY", "new")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert [entry.name for entry in tmp_path.iterdir()] == ["work.env"]


def test_unset_value_comments_out_only_active_lines(tmp_path: Path) -> None:
    path = _env(tmp_path, "KEY=1\n# KEY=2\nKEY_LONGER=3\n")
    workenv.unset_value(path, "KEY")
    assert path.read_text(encoding="utf-8") == "# KEY=1\n# KEY=2\nKEY_LONGER=3\n"


def test_the_env_set_and_env_unset_commands_edit_the_file(tmp_path: Path) -> None:
    path = _env(tmp_path, "A=1\n")
    assert cli.main(["env-set", "--env-file", str(path), "--", "B", "2"]) == 0
    assert cli.main(["env-unset", "--env-file", str(path), "--", "A"]) == 0
    assert path.read_text(encoding="utf-8") == "# A=1\nB=2\n"


def test_set_value_keeps_the_line_breaks_of_the_file(tmp_path: Path) -> None:
    path = tmp_path / "work.env"
    path.write_bytes(b"A=1\r\nKEY=old\r\nB=2\rC=3\nD=4")
    workenv.set_value(path, "KEY", "new")
    assert path.read_bytes() == b"A=1\r\nKEY=new\r\nB=2\rC=3\nD=4"


def test_set_value_appends_with_a_line_feed_after_an_unterminated_last_line(tmp_path: Path) -> None:
    path = tmp_path / "work.env"
    path.write_bytes(b"A=1\r\nB=2")
    workenv.set_value(path, "KEY", "x")
    assert path.read_bytes() == b"A=1\r\nB=2\nKEY=x\n"


def test_unset_value_keeps_the_line_breaks_of_the_file(tmp_path: Path) -> None:
    path = tmp_path / "work.env"
    path.write_bytes(b"A=1\r\nKEY=2\rB=3\n")
    workenv.unset_value(path, "KEY")
    assert path.read_bytes() == b"A=1\r\n# KEY=2\rB=3\n"


@pytest.mark.parametrize("value", ["a\nb", "a\rb", "x\r\ny"])
def test_set_value_refuses_a_value_with_a_line_break_and_writes_nothing(
    tmp_path: Path, value: str
) -> None:
    path = _env(tmp_path, "A=1\n")
    with pytest.raises(ValueError):
        workenv.set_value(path, "KEY", value)
    assert path.read_text(encoding="utf-8") == "A=1\n"


def test_the_env_set_command_exits_1_for_a_value_with_a_line_break(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _env(tmp_path, "A=1\n")
    assert cli.main(["env-set", "--env-file", str(path), "--", "KEY", "a\nb"]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err.strip() != ""
    assert path.read_text(encoding="utf-8") == "A=1\n"
