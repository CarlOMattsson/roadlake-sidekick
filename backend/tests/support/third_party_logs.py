"""Shared test helpers moved out of `tests/unit/test_third_party_log_redaction.py`."""

import io
import logging
import threading
import warnings
from collections.abc import Iterator

import httpx
import pytest
import uvicorn
from starlette.types import ASGIApp, Receive, Scope, Send

from sidekick.shared.observability import (
    HTTP_CLIENT_LOGGERS,
    harden_third_party_logging,
)
from tests.support.polling import wait_until

MARKER = "anna.svensson@example.com ringde om Johans tandrot"


FRAGMENTS = ("anna", "example.com", "Johan", "tandrot")


LOGGER_NAMES = ("", "uvicorn", "uvicorn.error", "uvicorn.asgi", "uvicorn.access", "py.warnings")


def assert_clean(text: str) -> None:
    for fragment in FRAGMENTS:
        assert fragment not in text


@pytest.fixture
def restored_logging() -> Iterator[None]:
    saved = {
        name: (list(logging.getLogger(name).handlers), logging.getLogger(name).propagate)
        for name in LOGGER_NAMES
    }
    client_levels = {name: logging.getLogger(name).level for name in HTTP_CLIENT_LOGGERS}
    access = logging.getLogger("uvicorn.access")
    access_state = (access.disabled, list(access.filters))
    showwarning = warnings.showwarning
    yield
    for name, (handlers, propagate) in saved.items():
        logging.getLogger(name).handlers = handlers
        logging.getLogger(name).propagate = propagate
    for name, level in client_levels.items():
        logging.getLogger(name).setLevel(level)
    access.disabled, access.filters = access_state[0], access_state[1]
    warnings.showwarning = showwarning


async def failing_app(scope: Scope, receive: Receive, send: Send) -> None:
    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            else:
                await send({"type": "lifespan.shutdown.complete"})
                return
    raise RuntimeError(MARKER)


def run_server(
    app: ASGIApp, stream: io.StringIO, *, access_log: bool, path: str | None = None
) -> None:
    """Run a real uvicorn server in-process; with a `path`, request it once, then stop it."""

    def factory() -> object:
        harden_third_party_logging(stream)  # as `configure_observability` does at composition
        return app

    config = uvicorn.Config(
        factory, factory=True, host="127.0.0.1", port=0, access_log=access_log, lifespan="on"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        if path is not None:
            wait_until(lambda: server.started, timeout=15, what="the server to start")
            port = server.servers[0].sockets[0].getsockname()[1]
            httpx.get(f"http://127.0.0.1:{port}{path}", timeout=10)
    finally:
        if path is not None:
            server.should_exit = True
        thread.join(timeout=15)
    assert not thread.is_alive()
