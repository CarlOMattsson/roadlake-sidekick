"""One safe failure path for every operator command (`sidekick-admin`, `sidekick-backup`, ...).

An uncaught exception ends a command with a traceback, and a database error or a settings error
quotes the values it choked on: a login name, a column value, a rejected setting. The operator
commands therefore run inside `run_guarded`, which turns any failure into one fixed line on stderr
and an exit code, and logs the error class alone (`log_failure`, never the message).

Exit codes, the same for every command:

| Code | Meaning |
| --- | --- |
| 0 | done |
| 1 | the command refused or failed in a way it describes itself |
| 2 | wrong arguments (argparse) |
| 3 | the record already exists or conflicts with existing data |
| 4 | the database failed or is unavailable |
| 5 | an unexpected error; the line names only its class |

The line ends with a correlation id that the log record carries too, so an operator can match the
two without the error text ever being printed.
"""

import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from pydantic import ValidationError as SettingsValidationError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from sidekick.shared.errors.core import (
    ConflictError,
    InternalFaultError,
    NotFoundError,
    PermissionDeniedError,
    RefusedError,
    SidekickError,
)
from sidekick.shared.observability import log_failure

LOGGER = logging.getLogger(__name__)

EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_CONFLICT = 3
EXIT_DATABASE = 4
EXIT_UNEXPECTED = 5


@dataclass(frozen=True)
class CommandFailure:
    """A fixed message and exit code; never built from the text of the error it describes."""

    message: str
    exit_code: int


UNIQUE_VIOLATION = "23505"


def _sqlstate(error: IntegrityError) -> str | None:
    """The PostgreSQL error class of the driver error behind `error` (psycopg 3 or 2)."""

    driver = error.orig
    return getattr(driver, "sqlstate", None) or getattr(driver, "pgcode", None)


def _constraint(error: IntegrityError) -> str | None:
    """The name of the constraint the database named; a schema name, never a row value."""

    diag = getattr(error.orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def describe_failure(
    error: BaseException,
    *,
    conflict_message: str | None = None,
    conflict_constraint: str | None = None,
) -> CommandFailure:
    """Map an error to its fixed line. Only the class of `error` decides; its text is ignored.

    `conflict_message` lets a command name what collided (`user already exists`). It is used only
    for a unique violation (SQLSTATE 23505) and, when `conflict_constraint` is given, only if the
    database names that very constraint; any other integrity error gets the generic text.
    """

    if isinstance(error, SettingsValidationError):
        from sidekick.shared.config import Settings

        if error.title == Settings.__name__:
            return CommandFailure(
                f"configuration is invalid ({error.error_count()} errors)", EXIT_FAILED
            )
        return CommandFailure(f"the input was rejected ({error.error_count()} errors)", EXIT_FAILED)
    if isinstance(error, IntegrityError):
        if _sqlstate(error) != UNIQUE_VIOLATION:
            return CommandFailure("the database refused the data", EXIT_DATABASE)
        named = conflict_constraint is None or _constraint(error) == conflict_constraint
        return CommandFailure(
            conflict_message
            if conflict_message and named
            else "the record already exists or conflicts with existing data",
            EXIT_CONFLICT,
        )
    if isinstance(error, SQLAlchemyError):
        return CommandFailure(
            "database error; check that it is reachable and migrated", EXIT_DATABASE
        )
    if isinstance(error, RefusedError):  # a literal sentence by contract, see RefusedError
        return CommandFailure(str(error), EXIT_FAILED)
    if isinstance(error, ConflictError):
        return CommandFailure("the request conflicts with existing data", EXIT_CONFLICT)
    if isinstance(error, NotFoundError):
        return CommandFailure("not found", EXIT_FAILED)
    if isinstance(error, PermissionDeniedError):
        return CommandFailure("not allowed", EXIT_FAILED)
    if isinstance(error, SidekickError) and not isinstance(error, InternalFaultError):
        return CommandFailure(f"the request was refused ({error.code})", EXIT_FAILED)
    return CommandFailure(f"unexpected error ({type(error).__name__})", EXIT_UNEXPECTED)


def report_failure(
    command: str,
    error: BaseException,
    *,
    conflict_message: str | None = None,
    conflict_constraint: str | None = None,
) -> int:
    """Print the fixed line with a correlation id, log the error class, return the exit code."""

    failure = describe_failure(
        error, conflict_message=conflict_message, conflict_constraint=conflict_constraint
    )
    correlation_id = uuid4().hex
    print(f"{command}: {failure.message} (correlation id {correlation_id})", file=sys.stderr)
    log_failure(LOGGER, "cli_failed", error, correlation_id=correlation_id)
    return failure.exit_code


def run_guarded(
    command: str,
    action: Callable[[], int | None],
    *,
    conflict_message: str | None = None,
    conflict_constraint: str | None = None,
) -> int:
    """Run `action` and return its exit code (0 for `None`); any failure becomes a fixed line.

    `SystemExit` (argparse, `parser.error`) and `KeyboardInterrupt` are not failures and pass.
    """

    try:
        return action() or 0
    except Exception as error:
        return report_failure(
            command,
            error,
            conflict_message=conflict_message,
            conflict_constraint=conflict_constraint,
        )
