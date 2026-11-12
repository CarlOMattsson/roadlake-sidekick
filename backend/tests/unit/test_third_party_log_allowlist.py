"""Nothing from third-party code reaches a log: no message, argument, path or exception text.

Each test reproduces one way content got through (or could) with a marker for personal data, then
checks the marker is in no output: not on the stream the hardened handlers write to, not on the
process's stdout or stderr, and not in a record any handler received.
"""

import asyncio
import gc
import io
import logging
import socket
import subprocess
import sys
import textwrap
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import httpx
import pytest
from starlette.applications import Starlette

from sidekick.shared.observability import harden_third_party_logging
from sidekick.shared.observability.third_party_logs import third_party_message
from tests.support.polling import poll_until
from tests.support.third_party_logs import (
    FRAGMENTS,
    MARKER,
    assert_clean,
    failing_app,
    restored_logging,  # noqa: F401  (fixture)
    run_server,
)

PATH_WITH_ADDRESS = "/anna.svensson@example.com"
OK_APP_SOURCE = textwrap.dedent(
    """
    from sidekick.shared.observability import harden_third_party_logging


    async def app(scope, receive, send):
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                else:
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


    def factory():
        harden_third_party_logging()
        return app
    """
)


# --- finding 1: the access log stays off, whatever the flag, and never names a path ---------------


@pytest.mark.usefixtures("restored_logging")
@pytest.mark.parametrize("access_log", [False, True])
def test_access_log_never_names_a_path_in_process(
    access_log: bool, capfd: pytest.CaptureFixture[str]
) -> None:
    stream = io.StringIO()
    run_server(failing_app, stream, access_log=access_log, path=f"{PATH_WITH_ADDRESS}?code=abc")
    captured = capfd.readouterr()
    everything = stream.getvalue() + captured.out + captured.err
    assert "Exception in ASGI application" in everything  # the server did log, and was reached
    for fragment in (*FRAGMENTS, "GET /", "HTTP/1.1", "127.0.0.1:", "code="):
        assert fragment not in everything
    access = logging.getLogger("uvicorn.access")
    assert access.disabled
    assert not access.hasHandlers()


@pytest.mark.parametrize("flag", [["--no-access-log"], []])
def test_access_log_never_names_a_path_in_a_real_uvicorn_process(
    flag: list[str], tmp_path: Path
) -> None:
    """The command-line server, with `--no-access-log` and with the access log left on."""

    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "safe_app.py").write_text(OK_APP_SOURCE, encoding="utf-8")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    command = [sys.executable, "-m", "uvicorn", "safe_app:factory", "--factory"]
    command += ["--app-dir", str(app_dir), "--host", "127.0.0.1", "--port", str(port), *flag]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        status = 0

        def answers() -> bool:
            nonlocal status
            try:
                url = f"http://127.0.0.1:{port}{PATH_WITH_ADDRESS}?code=abc"
                status = httpx.get(url, timeout=2).status_code
            except httpx.TransportError:
                return False
            return status == 200

        poll_until(answers, timeout=30, interval=0.1)
        assert status == 200
    finally:
        process.terminate()
        try:
            output, _ = process.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
            output, _ = process.communicate()
    assert "Application startup complete" in output
    assert "Uvicorn running" in output
    for fragment in (*FRAGMENTS, "GET /", "HTTP/1.1", "127.0.0.1", "code=", str(port)):
        assert fragment not in output


# --- finding 2: a failed lifespan carries its traceback as the message ----------------------------


def failing_lifespan_app(phase: Literal["startup", "shutdown"]) -> Starlette:
    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        if phase == "startup":
            raise RuntimeError(MARKER)
        yield
        raise RuntimeError(MARKER)

    return Starlette(lifespan=lifespan)


@pytest.mark.usefixtures("restored_logging")
@pytest.mark.parametrize("phase", ["startup", "shutdown"])
def test_failed_lifespan_logs_no_traceback_text(
    phase: Literal["startup", "shutdown"], capfd: pytest.CaptureFixture[str]
) -> None:
    stream = io.StringIO()
    run_server(
        failing_lifespan_app(phase),
        stream,
        access_log=False,
        path="/" if phase == "shutdown" else None,
    )
    captured = capfd.readouterr()
    everything = stream.getvalue() + captured.out + captured.err
    assert f"Application {phase} failed" in everything
    for fragment in (*FRAGMENTS, "Traceback", "RuntimeError(", "File "):
        assert fragment not in everything
    assert "third_party_log" in everything  # the traceback message was replaced, not dropped


# --- finding 3: asyncio puts the exception's repr into its message --------------------------------


@pytest.mark.usefixtures("restored_logging")
def test_asyncio_never_retrieved_exception_is_not_in_the_log(
    capfd: pytest.CaptureFixture[str],
) -> None:
    stream = io.StringIO()
    harden_third_party_logging(stream)
    loop = asyncio.new_event_loop()
    try:
        future = loop.create_future()
        future.set_exception(RuntimeError(MARKER))
        del future
        gc.collect()
    finally:
        loop.close()
    captured = capfd.readouterr()
    everything = stream.getvalue() + captured.out + captured.err
    assert "ERROR asyncio third_party_log" in everything  # it did log
    assert_clean(everything)
    assert "RuntimeError(" not in everything


# --- the rule itself: any other logger, message, argument or exception ----------------------------

ARBITRARY_LOGGERS = (
    "somelib",
    "somelib.sub.module",
    "httpx",
    "sqlalchemy.engine.Engine",
    "urllib3.connectionpool",
    "mcp.server.lowlevel.server",
    "uvicorn.error",
    "uvicorn.asgi",
    "starlette.routing",
    "root",
)


def _log_every_way(logger: logging.Logger) -> None:
    logger.warning(f"{MARKER} in an f-string")
    logger.warning("a %s message", MARKER)
    logger.warning("a %(who)s message", {"who": MARKER})
    logger.error(RuntimeError(MARKER))  # the message is an exception object
    logger.error("%r", [MARKER, {"k": MARKER}])
    logger.info("stack", stack_info=True, extra={"detail": MARKER})
    try:
        raise RuntimeError(MARKER)
    except RuntimeError:
        logger.exception("failed for %s", MARKER)
        logger.error(MARKER, exc_info=True)
        logger.critical("again", exc_info=sys.exc_info())


@pytest.fixture
def root_without_handlers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(logging.root, "handlers", [])
    monkeypatch.setattr(logging.root, "level", logging.NOTSET)


@pytest.mark.usefixtures("restored_logging", "root_without_handlers")
def test_arbitrary_third_party_loggers_never_write_message_arguments_or_exception(
    capfd: pytest.CaptureFixture[str],
) -> None:
    stream = io.StringIO()
    harden_third_party_logging(stream)
    seen: list[str] = []

    class Recorder(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            seen.append(f"{record.getMessage()} {record.args!r} {record.exc_info!r} {record.msg!r}")

    recorder = Recorder(logging.DEBUG)
    try:
        for name in ARBITRARY_LOGGERS:
            logger = logging.getLogger(name)
            logger.setLevel(logging.DEBUG)
            logger.addHandler(recorder)  # a foreign handler sees the rewritten record too
            _log_every_way(logger)
    finally:
        for name in ARBITRARY_LOGGERS:
            logging.getLogger(name).removeHandler(recorder)
            logging.getLogger(name).setLevel(logging.NOTSET)
    captured = capfd.readouterr()
    everything = "\n".join([stream.getvalue(), captured.out, captured.err, *seen])
    assert "third_party_log" in everything
    assert "error_type=RuntimeError" in everything
    assert_clean(everything)
    for fragment in ("Traceback", "RuntimeError(", "detail", "in an f-string"):
        assert fragment not in everything


@pytest.mark.parametrize(
    ("logger", "message", "expected"),
    [
        ("uvicorn.error", "Started server process [%d]", "Started server process"),
        (
            "uvicorn.error",
            "Uvicorn running on %s://%s:%d (Press CTRL+C to quit)",
            "Uvicorn running",
        ),
        ("uvicorn.error", "Shutting down", "Shutting down"),
        ("uvicorn.error", "Application startup complete.", "Application startup complete"),
        ("uvicorn.error", f"Traceback ... {MARKER}", "third_party_log"),
        ("asyncio", "Task exception was never retrieved", "third_party_log"),
        ("somelib", "Started server process [%d]", "third_party_log"),
    ],
)
def test_only_reviewed_uvicorn_lines_keep_a_label(logger: str, message: str, expected: str) -> None:
    assert third_party_message(logger, message, None) == expected
    assert third_party_message(logger, message, (ValueError, ValueError(), None)) == (
        f"{expected} error_type=ValueError"
    )
