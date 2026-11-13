"""The interactive guide's questions: asking one on the terminal, what counts as a yes, and a numbered choice."""

from __future__ import annotations

import os
import re
import signal
import sys
import termios
from collections.abc import Callable, Sequence
from types import FrameType

# What signal.signal returns and accepts.
_Handler = Callable[[int, FrameType | None], object] | int | signal.Handlers | None

YES_ANSWERS = frozenset({"j", "J", "y", "Y", "ja", "JA", "yes", "YES", "Yes"})
NUMBER = re.compile(r"[0-9]+")


def is_yes(answer: str) -> bool:
    return answer in YES_ANSWERS


def pick_choice(answer: str, choices: Sequence[str]) -> str:
    """The choice a number between 1 and ``len(choices)`` names; anything else is a typed value, taken as it is."""
    if NUMBER.fullmatch(answer) and 1 <= int(answer) <= len(choices):
        return choices[int(answer) - 1]
    return answer


def read_line(fd: int = 0) -> str:
    """One complete line from ``fd`` without its newline; ``""`` at end of input.

    A last line that ends without a newline is not an answer (the end of the input cut it off), as with the shell's
    ``read``: it gives ``""``, so a half-typed ``ja`` never confirms anything.

    Reads byte by byte, so nothing beyond the line is consumed: the next question (this process or the next one) finds
    the following line of a pipe where it was left."""
    data = bytearray()
    while True:
        try:
            byte = os.read(fd, 1)
        except OSError:  # a closed input is the end of the input
            return ""
        if not byte:
            return ""
        if byte == b"\n":
            return data.decode("utf-8", errors="surrogateescape")
        data += byte


def read_secret_line(fd: int = 0) -> str:
    """``read_line`` with the terminal's echo off while typing; input that is not a terminal is read as is.

    The echo is back on however the read ends, also when SIGTERM or SIGHUP ends the process: the handler restores the
    terminal, puts the previous handler back and sends the signal again."""
    try:
        saved = termios.tcgetattr(fd)
    except termios.error:
        return read_line(fd)
    hidden = list(saved)
    hidden[3] &= ~termios.ECHO

    def restore() -> None:
        termios.tcsetattr(fd, termios.TCSANOW, saved)

    previous: dict[int, _Handler] = {}

    def on_signal(number: int, _frame: object) -> None:
        restore()
        signal.signal(number, previous[number])
        os.kill(os.getpid(), number)

    for number in (signal.SIGTERM, signal.SIGHUP):
        previous[number] = signal.signal(number, on_signal)
    termios.tcsetattr(fd, termios.TCSANOW, hidden)
    try:
        return read_line(fd)
    finally:
        restore()
        for number, handler in previous.items():
            signal.signal(number, handler)


def question(text: str, default: str = "") -> str:
    """The prompt line of a question: ``text [default]: ``, or ``text: `` when there is no default."""
    return f"{text} [{default}]: " if default else f"{text}: "


def ask(prompt: str, default: str = "", *, secret: bool = False, only_on_terminal: bool = False, fd: int = 0) -> str:
    """Show ``prompt`` on stderr, read one line and give the default for an empty one (or end of input).

    ``only_on_terminal`` shows the prompt only when the input is a terminal. A secret's own line break is
    written afterwards, because the typed Enter was not echoed."""
    if not only_on_terminal or os.isatty(fd):
        sys.stderr.write(prompt)
        sys.stderr.flush()
    answer = read_secret_line(fd) if secret else read_line(fd)
    if secret:
        sys.stderr.write("\n")
        sys.stderr.flush()
    return answer or default


def confirm(prompt: str, default: str, *, fd: int = 0) -> bool:
    """A yes/no question; an empty answer counts as ``default`` (``y`` or ``n``)."""
    return is_yes(ask(prompt, default, fd=fd))
