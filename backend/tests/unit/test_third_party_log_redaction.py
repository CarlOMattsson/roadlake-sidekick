"""Exception text never reaches logs written by uvicorn or other libraries; shared helpers.

The broader allowlist tests (access log, lifespan, asyncio, arbitrary loggers) are in
`test_third_party_log_allowlist.py` and reuse the server helpers defined here.
"""

import io
import logging
import sys
import warnings
from pathlib import Path

import pytest

from sidekick.shared.observability import (
    ExceptionTypeOnlyFormatter,
    harden_third_party_logging,
)
from tests.support.third_party_logs import (
    MARKER,
    assert_clean,
    failing_app,
    restored_logging,  # noqa: F401  (a fixture)
    run_server,
)


def serve_and_request(stream: io.StringIO, *, access_log: bool, path: str) -> None:
    run_server(failing_app, stream, access_log=access_log, path=path)
    # (a 500 comes back for every path: `failing_app` raises)


@pytest.mark.usefixtures("restored_logging")
def test_uvicorn_error_log_of_an_unhandled_exception_has_only_the_type() -> None:
    stream = io.StringIO()
    serve_and_request(stream, access_log=False, path="/")
    output = stream.getvalue()
    assert "Exception in ASGI application" in output
    assert "error_type=RuntimeError" in output
    assert_clean(output)
    assert "Traceback" not in output


def test_exception_text_cached_by_an_earlier_handler_is_never_written() -> None:
    try:
        raise ValueError(MARKER)
    except ValueError:
        record = logging.LogRecord("t", logging.ERROR, __file__, 1, "failed", None, sys.exc_info())
    cached = f"Traceback ... ValueError: {MARKER}"
    record.exc_text = cached
    formatter = ExceptionTypeOnlyFormatter("%(levelname)s %(message)s")
    output = formatter.format(record)
    assert output == "ERROR failed\nerror_type=ValueError"
    assert_clean(output)
    assert record.exc_text == cached
    record.exc_info = None
    assert_clean(formatter.format(record))


@pytest.mark.usefixtures("restored_logging")
def test_python_warning_is_logged_as_category_and_module_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    harden_third_party_logging(io.StringIO())
    logger = logging.getLogger("sidekick")
    logger.addHandler(caplog.handler)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("always")
            warnings.warn(MARKER, DeprecationWarning, stacklevel=1)
    finally:
        logger.removeHandler(caplog.handler)
    output = "\n".join(record.getMessage() for record in caplog.records)
    assert "python_warning category=DeprecationWarning module=test_third_party_log" in output
    assert_clean(output)


@pytest.mark.policy
def test_sidekick_registers_no_span_processor_overriding_on_ending() -> None:
    """`_on_ending` runs before `on_end` on a writable span and would see raw exception text."""

    source = Path(__file__).parents[2] / "src"
    offenders = [str(path) for path in source.rglob("*.py") if "def _on_ending" in path.read_text()]
    assert offenders == []
