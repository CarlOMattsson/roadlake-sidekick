"""What a signal does to a flow: it never cuts a cleanup short and it ends a question at once."""

import os
import signal
import threading
from pathlib import Path

import pytest
from tools.workctl import prompts
from tools.workctl.stack import Signals, Stop

from tests.selfhost.work_package.fakestack import FakeStack


def test_a_signal_is_acted_on_once_by_check() -> None:
    signals = Signals()
    signals.record(signal.SIGTERM)
    with pytest.raises(Stop) as stop:
        signals.check()
    assert stop.value.code == 143
    signals.check()


def test_release_forgets_what_was_recorded() -> None:
    signals = Signals()
    signals.record(signal.SIGINT)
    signals.release()
    assert signals.pending == 0
    signals.check()


def test_during_a_cleanup_a_signal_is_kept_for_after_it() -> None:
    signals = Signals()
    signals.record(signal.SIGINT)
    signals.defer()
    signals.check()
    signals.record(signal.SIGTERM)
    signals.check()
    assert signals.take() == 130, "the first signal decides the status"
    assert signals.take() == 0


def test_a_question_is_ended_at_once_by_a_signal_that_came_before_it() -> None:
    signals = Signals()
    signals.record(signal.SIGHUP)
    with pytest.raises(Stop) as stop, signals.interruptible():
        pytest.fail("the question must not be asked")
    assert stop.value.code == 129


def test_a_question_is_ended_at_once_by_a_signal_during_it() -> None:
    signals = Signals()
    with pytest.raises(Stop) as stop, signals.interruptible():
        signals.record(signal.SIGINT)
    assert stop.value.code == 130
    assert signals.pending == 0 and not signals.raising


def test_a_signal_that_arrives_while_the_input_is_read_ends_the_read(tmp_path: Path) -> None:
    """The real thing: a blocking read on a pipe, the handler installed, a TERM sent to it."""
    reader, writer = os.pipe()
    stack = FakeStack(tmp_path)
    main = threading.get_ident()
    sender = threading.Timer(0.3, signal.pthread_kill, (main, signal.SIGTERM))
    try:
        with stack.caught_signals():
            sender.start()
            with pytest.raises(Stop) as stop, stack.signals.interruptible():
                prompts.read_line(reader)
        assert stop.value.code == 143
    finally:
        sender.cancel()
        sender.join()
        os.close(reader)
        os.close(writer)
