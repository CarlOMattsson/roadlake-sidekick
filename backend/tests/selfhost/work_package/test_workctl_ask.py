"""The guide's questions: prompts, answers, defaults, end of input, one line per question."""

import os
import pty
import signal
import subprocess
import sys
import termios
import time
from pathlib import Path

import pytest
from tools.workctl import messages, prompts

from tests.selfhost.work_package.support import REPO_ROOT, docker_calls, ready_repo, run_work

ENV = {
    "PATH": os.environ.get("PATH", ""),
    "PYTHONPATH": str(REPO_ROOT / "tools"),
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONIOENCODING": "utf-8",
}


def _workctl(*args: str, stdin: bytes = b"") -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", "workctl", *args],
        env=ENV,
        input=stdin,
        capture_output=True,
        timeout=60,
        check=False,
    )


def _pipe(data: bytes) -> int:
    read_end, write_end = os.pipe()
    os.write(write_end, data)
    os.close(write_end)
    return read_end


def test_a_question_shows_its_default_in_brackets() -> None:
    assert prompts.question("Language", "sv") == "Language [sv]: "
    assert prompts.question("Language") == "Language: "


def test_read_line_stops_at_the_newline_and_leaves_the_rest() -> None:
    fd = _pipe("först\nandra\n".encode())
    assert prompts.read_line(fd) == "först"
    assert prompts.read_line(fd) == "andra"
    assert prompts.read_line(fd) == ""
    os.close(fd)


@pytest.mark.parametrize("data", [b"", b"ja", b"first\nja"])
def test_read_line_gives_nothing_for_a_line_the_end_of_input_cut_off(data: bytes) -> None:
    fd = _pipe(data)
    if b"\n" in data:
        assert prompts.read_line(fd) == "first"
    assert prompts.read_line(fd) == ""
    os.close(fd)


def test_a_cut_off_secret_is_empty_too() -> None:
    fd = _pipe(b"s3cret")
    assert prompts.read_secret_line(fd) == ""
    os.close(fd)


def test_a_confirmation_cut_off_before_its_newline_is_no_yes() -> None:
    fd = _pipe(b"ja")
    assert prompts.confirm("Q: ", "n", fd=fd) is False
    os.close(fd)
    result = _workctl("confirm", "--key", "start_q", "--default", "n", stdin=b"ja")
    assert result.returncode == 1
    result = _workctl("ask", "--key", "purge_q", stdin=b"")
    assert result.stdout == b""


def test_a_closed_input_is_an_empty_answer() -> None:
    fd = _pipe(b"")
    os.close(fd)
    assert prompts.read_line(fd) == ""


def test_a_secret_from_a_pipe_is_read_as_it_is() -> None:
    fd = _pipe(b"s3cret\n")
    assert prompts.read_secret_line(fd) == "s3cret"
    os.close(fd)


def test_a_secret_typed_on_a_terminal_is_read_with_echo_off_and_echo_comes_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    master, slave = pty.openpty()
    echo_while_reading: list[bool] = []
    real_read_line = prompts.read_line

    def spy(fd: int = 0) -> str:
        echo_while_reading.append(bool(termios.tcgetattr(fd)[3] & termios.ECHO))
        return real_read_line(fd)

    monkeypatch.setattr(prompts, "read_line", spy)
    try:
        os.write(master, b"hunter2\n")
        assert prompts.read_secret_line(slave) == "hunter2"
        assert echo_while_reading == [False]
        assert termios.tcgetattr(slave)[3] & termios.ECHO
    finally:
        os.close(master)
        os.close(slave)


def test_ask_prompts_on_stderr_and_falls_back_to_the_default(
    capsys: pytest.CaptureFixture[str],
) -> None:
    fd = _pipe(b"\n")
    assert prompts.ask("Q [d]: ", "d", fd=fd) == "d"
    os.close(fd)
    fd = _pipe(b"typed\n")
    assert prompts.ask("Q: ", "d", fd=fd) == "typed"
    os.close(fd)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Q [d]: Q: "


def test_ask_can_keep_its_prompt_off_a_pipe(capsys: pytest.CaptureFixture[str]) -> None:
    fd = _pipe(b"x\n")
    assert prompts.ask("Q: ", only_on_terminal=True, fd=fd) == "x"
    os.close(fd)
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize(
    ("answer", "default", "expected"),
    [
        (b"ja\n", "n", True),
        (b"y\n", "n", True),
        (b"nej\n", "y", False),
        (b"\n", "y", True),
        (b"\n", "n", False),
        (b"", "y", True),
        (b"", "n", False),
    ],
)
def test_confirm_takes_the_default_for_an_empty_answer(
    answer: bytes, default: str, expected: bool
) -> None:
    fd = _pipe(answer)
    assert prompts.confirm("Q: ", default, fd=fd) is expected
    os.close(fd)


def test_the_ask_command_prints_the_message_and_returns_the_typed_answer_unchanged() -> None:
    result = _workctl("ask", "--lang", "en", "--key", "model_key_ask", stdin="åäö -x  \n".encode())
    assert result.returncode == 0
    assert result.stdout == "åäö -x  ".encode()
    assert result.stderr == messages.text("en", "model_key_ask").encode()


def test_the_ask_command_without_input_gives_an_empty_answer() -> None:
    result = _workctl("ask", "--key", "purge_q")
    assert result.returncode == 0
    assert result.stdout == b""


def test_the_ask_command_fills_the_message_without_a_colon() -> None:
    result = _workctl(
        "ask", "--lang", "en", "--key", "rs_confirm_q", "--", "-proj", stdin=b"-proj\n"
    )
    assert result.stdout == b"-proj"
    assert result.stderr == (messages.text("en", "rs_confirm_q") % "-proj").encode()


def test_the_ask_command_can_stay_silent_on_a_pipe() -> None:
    result = _workctl("ask", "--key", "purge_q", "--only-on-terminal", stdin=b"ja\n")
    assert result.stdout == b"ja"
    assert result.stderr == b""


def test_the_secret_ask_command_ends_the_line_on_stderr_and_never_on_stdout() -> None:
    result = _workctl("ask", "--lang", "en", "--key", "model_key_ask", "--secret", stdin=b"abc\n")
    assert result.stdout == b"abc"
    assert result.stderr == f"{messages.text('en', 'model_key_ask')}\n".encode()


def test_two_ask_commands_on_one_pipe_read_one_line_each(tmp_path: Path) -> None:
    script = (
        'workctl() { python3 -m workctl "$@"; }; '
        'a="$(workctl ask --key purge_q)"; b="$(workctl ask --key purge_q)"; echo "$a|$b"'
    )
    result = subprocess.run(
        ["bash", "-c", script],
        env=ENV,
        input=b"one\ntwo\nthree\n",
        capture_output=True,
        cwd=tmp_path,
        timeout=60,
        check=False,
    )
    assert result.stdout == b"one|two\n"


@pytest.mark.parametrize(
    ("answer", "code"),
    [(b"j\n", 0), (b"nej\n", 1), (b"\n", 0), (b"", 0)],
)
def test_the_confirm_command_exits_zero_for_a_yes(answer: bytes, code: int) -> None:
    result = _workctl("confirm", "--lang", "en", "--key", "start_q", "--default", "y", stdin=answer)
    assert result.returncode == code
    assert result.stdout == b""
    assert result.stderr == f"{messages.text('en', 'start_q')}: ".encode()


def test_the_confirm_command_default_no_is_no_at_end_of_input() -> None:
    result = _workctl("confirm", "--key", "auto_q", "--default", "n")
    assert result.returncode == 1


# Upper bound for the child's start-up and exit; the tests wait for the terminal state and the exit
# itself, so this only turns a genuine hang into a failure on a machine that is far oversubscribed.
GUARD_SECONDS = 120


def _wait_for_echo_state(fd: int, echo: bool) -> None:
    deadline = time.monotonic() + GUARD_SECONDS
    while bool(termios.tcgetattr(fd)[3] & termios.ECHO) != echo:
        assert time.monotonic() < deadline, "the terminal never reached the expected echo state"
        time.sleep(0.02)


def _default_signal_handlers() -> None:
    for number in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, signal.SIG_DFL)


@pytest.mark.parametrize("sent", [signal.SIGTERM, signal.SIGHUP])
def test_a_signal_during_a_secret_prompt_puts_the_echo_back(sent: signal.Signals) -> None:
    master, slave = pty.openpty()
    child = subprocess.Popen(
        [sys.executable, "-m", "workctl", "ask", "--key", "model_key_ask", "--secret"],
        env=ENV,
        stdin=slave,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        # A run under nohup ignores SIGHUP, and an ignored signal stays ignored in the child.
        preexec_fn=_default_signal_handlers,
    )
    try:
        _wait_for_echo_state(slave, echo=False)
        child.send_signal(sent)
        child.communicate(timeout=GUARD_SECONDS)
        assert child.returncode == -sent
        assert termios.tcgetattr(slave)[3] & termios.ECHO
    finally:
        child.kill()
        os.close(master)
        os.close(slave)


def test_the_handlers_of_a_secret_prompt_are_put_back() -> None:
    before = signal.getsignal(signal.SIGTERM)
    master, slave = pty.openpty()
    try:
        os.write(master, b"x\n")
        prompts.read_secret_line(slave)
    finally:
        os.close(master)
        os.close(slave)
    assert signal.getsignal(signal.SIGTERM) == before


def _break_ask(repo: Path) -> None:
    with (repo / "tools" / "workctl" / "prompts.py").open("a", encoding="utf-8") as handle:
        handle.write("\n\ndef ask(*_args: object, **_kwargs: object) -> str:\n")
        handle.write('    raise RuntimeError("boom")\n')


def test_a_failing_workctl_stops_the_guide_instead_of_giving_an_empty_answer(
    mini_repo: Path,
) -> None:
    _break_ask(mini_repo)
    result = run_work(mini_repo, "setup", stdin="sv\n\n\n\n")
    assert result.returncode != 0
    assert "boom" in result.stderr
    assert not (mini_repo / "docker-calls.txt").exists()


def test_a_failing_workctl_does_not_pass_for_an_answer_to_purge(mini_repo: Path) -> None:
    ready_repo(mini_repo)
    _break_ask(mini_repo)
    result = run_work(mini_repo, "stop", "--purge", stdin="ja\n")
    assert result.returncode != 0
    calls = mini_repo / "docker-calls.txt"
    assert not calls.exists() or "down -v" not in docker_calls(mini_repo)
