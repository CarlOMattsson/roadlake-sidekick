"""Third-party log records are rewritten to a fixed template when they are created.

A library's message, its arguments and its exception can all echo request content: uvicorn logs
a traceback as the *message* of a failed lifespan, asyncio puts `exception=...` into the message
through a Future's repr, httpx logs URLs. Scrubbing each known leak leaves the next one open. So
the rule is an allowlist applied where every handler sees it, at record creation:

* a record from `sidekick` or `sidekick.*` is untouched (its message is an event name by
  convention);
* a record from `uvicorn*` whose message starts with one of the reviewed prefixes below becomes
  that constant label, nothing else of the message or its arguments;
* every other record becomes `third_party_log`, plus `error_type=<ExceptionClass>` when an
  exception was attached. The message, the arguments, the traceback and `stack_info` are gone
  before any handler (Sidekick's, pytest's, a library's own) can read them.
"""

import logging
from typing import Any, cast

THIRD_PARTY_LOG = "third_party_log"
_OWN_LOGGERS = ("sidekick", "sidekick.")
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.")
_FACTORY_MARK = "_sidekick_safe_record_factory"

# (message prefix, fixed label written instead). Operational lines uvicorn emits itself with no
# request content in them; the label never contains the address, process id or file name that the
# real message carried.
_UVICORN_LABELS: tuple[tuple[str, str], ...] = (
    ("Started server process", "Started server process"),
    ("Finished server process", "Finished server process"),
    ("Waiting for application startup", "Waiting for application startup"),
    ("Application startup complete", "Application startup complete"),
    ("Application startup failed", "Application startup failed"),
    ("Waiting for application shutdown", "Waiting for application shutdown"),
    ("Application shutdown complete", "Application shutdown complete"),
    ("Application shutdown failed", "Application shutdown failed"),
    ("Uvicorn running on", "Uvicorn running"),
    ("Shutting down", "Shutting down"),
    ("Waiting for connections to close", "Waiting for connections to close"),
    ("Waiting for background tasks to complete", "Waiting for background tasks to complete"),
    ("Started reloader process", "Started reloader process"),
    ("Stopping reloader process", "Stopping reloader process"),
    ("Exception in ASGI application", "Exception in ASGI application"),
    ("Exception in 'lifespan' protocol", "Exception in lifespan protocol"),
    ("ASGI 'lifespan' protocol appears unsupported", "Lifespan protocol unsupported"),
    ("Invalid HTTP request received", "Invalid HTTP request received"),
)


def exception_class(exc_info: object) -> str | None:
    """The class name of a record's `exc_info`, or None; never the message or the traceback."""

    if isinstance(exc_info, tuple):
        parts = cast(tuple[object, ...], exc_info)
        if len(parts) == 3 and isinstance(parts[0], type):
            return parts[0].__name__
    return None


def is_sidekick_logger(name: str) -> bool:
    return name == _OWN_LOGGERS[0] or name.startswith(_OWN_LOGGERS[1])


def third_party_message(name: str, msg: object, exc_info: object) -> str:
    """The only text a third-party record may carry: a fixed label and an exception class."""

    label = THIRD_PARTY_LOG
    if isinstance(msg, str) and (name == "uvicorn" or name.startswith(_UVICORN_LOGGERS[1])):
        for prefix, fixed in _UVICORN_LABELS:
            if msg.startswith(prefix):
                label = fixed
                break
    error_type = exception_class(exc_info)
    return f"{label} error_type={error_type}" if error_type else label


def install_safe_record_factory() -> None:
    """Wrap the process-wide record factory so third-party records are rewritten on creation.

    Idempotent. The previous factory still builds the record (so any factory another library
    installed keeps working); only the message, arguments, exception and stack of a non-Sidekick
    record are replaced before it is returned.
    """

    previous = logging.getLogRecordFactory()
    if getattr(previous, _FACTORY_MARK, False):
        return

    def factory(
        name: str,
        level: int,
        fn: str,
        lno: int,
        msg: object,
        args: Any,
        exc_info: Any,
        func: str | None = None,
        sinfo: str | None = None,
        **kwargs: Any,
    ) -> logging.LogRecord:
        if is_sidekick_logger(name):
            return previous(name, level, fn, lno, msg, args, exc_info, func, sinfo, **kwargs)
        safe = third_party_message(name, msg, exc_info)
        return previous(name, level, fn, lno, safe, (), None, func, None, **kwargs)

    setattr(factory, _FACTORY_MARK, True)
    logging.setLogRecordFactory(factory)
