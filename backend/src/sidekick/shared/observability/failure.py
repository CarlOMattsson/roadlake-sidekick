"""One safe way to log an unexpected failure: the event name and the exception class only."""

import logging
from typing import Any

from .setup import safe_log_fields


def log_failure(logger: logging.Logger, event: str, error: BaseException, **extra: Any) -> None:
    """Log `event` at ERROR with `error_type=<ExceptionClass>`.

    Never attaches the exception to the record: its message, its traceback and its frame locals
    (SQL parameters, row values) can echo personal data, so none of them reach any handler.
    `extra` is filtered through the log allowlist like every other call site.
    """

    fields = safe_log_fields({**extra, "error_type": type(error).__name__})
    logger.error(event, extra=fields)
