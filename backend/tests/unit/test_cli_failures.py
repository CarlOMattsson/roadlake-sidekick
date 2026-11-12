"""Every operator command fails with a fixed line and an exit code, never a traceback or a value.

Each test drives the command's `main` with a failure that carries a synthetic sensitive value (a
login name, a column value) in its message, parameters and cause, then checks that neither stream
holds the value, that the line is the fixed one, and that the exit code is the documented one.
"""

import logging
import sys
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import IntegrityError, OperationalError

from sidekick import composition
from sidekick.automation import worker as automation_worker
from sidekick.backup import cli as backup_cli
from sidekick.backup import worker as backup_worker
from sidekick.companion import cli as companion_cli
from sidekick.companion import push_worker
from sidekick.license import cli as license_cli
from sidekick.memory import worker as memory_worker
from sidekick.owner_export import cli as owner_export_cli
from sidekick.shared import worker_health
from sidekick.shared.auth import cli as auth_cli
from sidekick.shared.cli_errors import (
    EXIT_CONFLICT,
    EXIT_DATABASE,
    EXIT_FAILED,
    EXIT_UNEXPECTED,
    describe_failure,
)
from sidekick.shared.config import Settings
from sidekick.shared.db_timeouts import DatabaseTimeouts
from sidekick.shared.errors.core import (
    ConflictError,
    NotFoundError,
    RefusedError,
    SidekickError,
)

SECRET = "secret-name-42"


class DriverError(Exception):
    """What psycopg raises under an IntegrityError: a SQLSTATE and the constraint it names."""

    def __init__(self, message: str, sqlstate: str, constraint: str | None) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate
        self.diag = SimpleNamespace(constraint_name=constraint)


def duplicate(
    constraint: str | None = "users_username_key", sqlstate: str = "23505"
) -> IntegrityError:
    return IntegrityError(
        f"INSERT INTO users (username) VALUES ('{SECRET}')",  # noqa: S608
        {"username": SECRET},
        DriverError(f"Key (username)=({SECRET}) already exists.", sqlstate, constraint),
    )


def unreachable() -> OperationalError:
    return OperationalError(
        f"SELECT '{SECRET}'", {"username": SECRET}, Exception(f"could not connect for {SECRET}")
    )


def invalid_command_input() -> ValidationError:
    class Shape(BaseModel):
        port: int

    try:
        Shape.model_validate({"port": SECRET})
    except ValidationError as error:
        return error
    raise AssertionError("the model accepted the value")


def invalid_settings() -> ValidationError:
    try:
        Settings(_env_file=None, **{SECRET: "x"})  # type: ignore[call-arg, arg-type]
    except ValidationError as error:
        return error
    raise AssertionError("the settings accepted the value")


def raising(error: BaseException) -> Callable[..., Any]:
    def fail(*_args: object, **_kwargs: object) -> Any:
        raise error

    return fail


def failing_async(error: BaseException) -> Callable[..., Any]:
    async def fail(*_args: object, **_kwargs: object) -> Any:
        raise error

    return fail


class FailingFactory:
    """A session factory whose every use fails, as an unreachable or constraining database does."""

    def __init__(self, error: BaseException) -> None:
        self.error = error

    def __call__(self, *_args: object, **_kwargs: object) -> Any:
        raise self.error

    def begin(self) -> Any:
        raise self.error


def exit_code(action: Callable[[], object]) -> int:
    """The process exit code of `action`: a returned int, a `SystemExit`, or 0."""

    try:
        result = action()
    except SystemExit as stop:
        return int(stop.code or 0)
    return result if isinstance(result, int) else 0


def settings_stub() -> SimpleNamespace:
    return SimpleNamespace(
        database_url="postgresql://unused",
        token_pepper="pepper" * 6,
        database_timeouts=DatabaseTimeouts(),
        license_public_key=None,
        mcp_app_locale="en",
    )


def assert_fixed_failure(capsys: pytest.CaptureFixture[str], *, message: str, command: str) -> str:
    captured = capsys.readouterr()
    assert SECRET not in captured.out + captured.err
    assert "Traceback" not in captured.err
    assert f"{command}: {message}" in captured.err
    assert "correlation id " in captured.err
    return captured.err


def use_admin(monkeypatch: pytest.MonkeyPatch, service: object, *argv: str) -> None:
    monkeypatch.setattr(composition, "create_auth_service", lambda *_a, **_k: service)
    monkeypatch.setattr(auth_cli, "create_session_factory", lambda *_a, **_k: object())
    monkeypatch.setattr(auth_cli, "get_admin_settings", settings_stub)
    monkeypatch.setattr(sys, "argv", ["sidekick-admin", *argv])


def test_admin_create_user_names_a_duplicate_without_the_name(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    service = SimpleNamespace(provision_user=raising(duplicate()))
    use_admin(monkeypatch, service, "create-user", "--login", SECRET, "--display-name", SECRET)

    assert exit_code(auth_cli.main) == EXIT_CONFLICT

    assert_fixed_failure(capsys, message="user already exists", command="sidekick-admin")


def test_admin_unexpected_error_names_only_its_class(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    service = SimpleNamespace(
        create_personal_token=raising(RuntimeError(f"cannot issue for {SECRET}"))
    )
    use_admin(
        monkeypatch,
        service,
        "create-token",
        "--user-id",
        "018af000-0000-7000-8000-000000000001",
        "--label",
        SECRET,
        "--scope",
        "tasks:read",
    )

    assert exit_code(auth_cli.main) == EXIT_UNEXPECTED

    assert_fixed_failure(
        capsys, message="unexpected error (RuntimeError)", command="sidekick-admin"
    )


def test_admin_invalid_settings_do_not_echo_the_rejected_value(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    use_admin(
        monkeypatch, object(), "list-tokens", "--user-id", "018af000-0000-7000-8000-000000000001"
    )
    monkeypatch.setattr(auth_cli, "get_admin_settings", raising(invalid_settings()))

    assert exit_code(auth_cli.main) == EXIT_FAILED

    assert_fixed_failure(
        capsys,
        message=f"configuration is invalid ({invalid_settings().error_count()} errors)",
        command="sidekick-admin",
    )


def test_admin_database_outage_is_a_fixed_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    service = SimpleNamespace(list_personal_tokens=raising(unreachable()))
    use_admin(
        monkeypatch, service, "list-tokens", "--user-id", "018af000-0000-7000-8000-000000000001"
    )

    assert exit_code(auth_cli.main) == EXIT_DATABASE

    assert_fixed_failure(
        capsys,
        message="database error; check that it is reachable and migrated",
        command="sidekick-admin",
    )


def test_license_command_fails_with_a_fixed_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sidekick.shared.config.get_settings", settings_stub)
    monkeypatch.setattr(
        "sidekick.shared.persistence.create_session_factory",
        lambda *_a, **_k: FailingFactory(duplicate()),
    )
    monkeypatch.setattr(sys, "argv", ["sidekick-license", "show"])

    assert exit_code(license_cli.main) == EXIT_CONFLICT

    assert_fixed_failure(
        capsys,
        message="the record already exists or conflicts with existing data",
        command="sidekick-license",
    )


def test_companion_command_fails_with_a_fixed_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sidekick.shared.config.get_settings", settings_stub)
    monkeypatch.setattr(
        "sidekick.shared.persistence.create_session_factory",
        lambda *_a, **_k: FailingFactory(unreachable()),
    )
    monkeypatch.setattr(composition, "create_auth_service", lambda *_a, **_k: object())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sidekick-companion",
            "list",
            "--user-id",
            "018af000-0000-7000-8000-000000000001",
        ],
    )

    assert exit_code(companion_cli.main) == EXIT_DATABASE

    assert_fixed_failure(
        capsys,
        message="database error; check that it is reachable and migrated",
        command="sidekick-companion",
    )


@pytest.mark.parametrize(
    ("error", "message", "code"),
    [
        (duplicate(), "the record already exists or conflicts with existing data", EXIT_CONFLICT),
        (RuntimeError(f"broke on {SECRET}"), "unexpected error (RuntimeError)", EXIT_UNEXPECTED),
    ],
)
def test_backup_prune_fails_with_a_fixed_line(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
    message: str,
    code: int,
) -> None:
    monkeypatch.setattr(
        backup_cli,
        "get_settings",
        lambda: SimpleNamespace(
            backup_directory=".",
            backup_retention_count=1,
            backup_retention_days=1,
            backup_min_keep=1,
        ),
    )
    monkeypatch.setattr(backup_cli, "prune_backup_files", raising(error))

    assert backup_cli.main(["prune"]) == code

    assert_fixed_failure(capsys, message=message, command="sidekick-backup")


def test_backup_value_errors_report_the_type_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(backup_cli, "get_settings", raising(ValueError(f"bad {SECRET}")))

    assert backup_cli.main(["prune"]) == EXIT_FAILED

    captured = capsys.readouterr()
    assert SECRET not in captured.out + captured.err
    assert "backup operation refused: ValueError" in captured.err


def test_backup_invalid_settings_do_not_echo_the_rejected_value(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(backup_cli, "get_settings", raising(invalid_settings()))

    assert backup_cli.main(["prune"]) == EXIT_FAILED

    captured = capsys.readouterr()
    assert SECRET not in captured.out + captured.err
    assert "configuration is invalid" in captured.err


def test_owner_export_unexpected_error_is_a_fixed_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Any
) -> None:
    export = tmp_path / "export.json"
    export.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(owner_export_cli, "verify_export", raising(KeyError(SECRET)))

    assert owner_export_cli.main(["verify", str(export)]) == EXIT_UNEXPECTED

    assert_fixed_failure(
        capsys, message="unexpected error (KeyError)", command="sidekick-owner-export"
    )


WORKERS: list[tuple[str, Callable[[pytest.MonkeyPatch], Callable[[], object]], str]] = []


def _automation(monkeypatch: pytest.MonkeyPatch) -> Callable[[], object]:
    monkeypatch.setattr(automation_worker, "run_worker", failing_async(duplicate()))
    monkeypatch.setattr(sys, "argv", ["sidekick-automation-worker", "--once"])
    return automation_worker.main


def _backup_worker(monkeypatch: pytest.MonkeyPatch) -> Callable[[], object]:
    monkeypatch.setattr(backup_worker, "run_worker", failing_async(unreachable()))
    monkeypatch.setattr(sys, "argv", ["sidekick-backup-worker", "--once"])
    return backup_worker.main


def _push(monkeypatch: pytest.MonkeyPatch) -> Callable[[], object]:
    monkeypatch.setattr(push_worker, "get_settings", settings_stub)
    monkeypatch.setattr(push_worker, "run_worker", raising(RuntimeError(f"push {SECRET}")))
    monkeypatch.setattr(sys, "argv", ["sidekick-push-worker", "--once"])
    return push_worker.main


def _memory(monkeypatch: pytest.MonkeyPatch) -> Callable[[], object]:
    monkeypatch.setattr(memory_worker, "run_worker", failing_async(RuntimeError(SECRET)))
    return lambda: memory_worker.main(["--once"])


def _health(monkeypatch: pytest.MonkeyPatch) -> Callable[[], object]:
    monkeypatch.setattr(worker_health, "check_worker", raising(OSError(f"cannot read {SECRET}")))
    return lambda: worker_health.main(["memory"])


@pytest.mark.parametrize(
    ("build", "command", "message", "code"),
    [
        (
            _automation,
            "sidekick-automation-worker",
            "the record already exists or conflicts with existing data",
            EXIT_CONFLICT,
        ),
        (
            _backup_worker,
            "sidekick-backup-worker",
            "database error; check that it is reachable and migrated",
            EXIT_DATABASE,
        ),
        (_push, "sidekick-push-worker", "unexpected error (RuntimeError)", EXIT_UNEXPECTED),
        (_memory, "sidekick-memory-worker", "unexpected error (RuntimeError)", EXIT_UNEXPECTED),
        (_health, "sidekick-worker-health", "unexpected error (OSError)", EXIT_FAILED),
    ],
)
def test_worker_entry_points_fail_with_a_fixed_line(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    build: Callable[[pytest.MonkeyPatch], Callable[[], object]],
    command: str,
    message: str,
    code: int,
) -> None:
    for module in (automation_worker, backup_worker, push_worker, memory_worker):
        monkeypatch.setattr(module, "configure_worker_logging", lambda: None)
    monkeypatch.setattr(push_worker, "silence_http_loggers", lambda: None)
    run = build(monkeypatch)

    assert exit_code(run) == code

    assert_fixed_failure(capsys, message=message, command=command)


def test_a_failure_is_logged_as_its_class_and_correlation_id_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    service = SimpleNamespace(provision_user=raising(duplicate()))
    use_admin(monkeypatch, service, "create-user", "--login", SECRET, "--display-name", SECRET)
    records: list[logging.LogRecord] = []

    class Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = Collect()
    sidekick_logger = logging.getLogger("sidekick")
    sidekick_logger.addHandler(handler)
    try:
        exit_code(auth_cli.main)
    finally:
        sidekick_logger.removeHandler(handler)

    [record] = [entry for entry in records if entry.getMessage() == "cli_failed"]
    assert record.exc_info is None
    assert getattr(record, "error_type") == "IntegrityError"  # noqa: B009
    assert getattr(record, "correlation_id") in capsys.readouterr().err  # noqa: B009
    assert SECRET not in repr(record.__dict__)


@pytest.mark.parametrize(
    ("error", "message", "code"),
    [
        (invalid_command_input(), "the input was rejected (1 errors)", EXIT_FAILED),
        (
            duplicate(None),
            "the record already exists or conflicts with existing data",
            EXIT_CONFLICT,
        ),
        (duplicate("other_key", "23503"), "the database refused the data", EXIT_DATABASE),
        (RefusedError("user exists but is disabled"), "user exists but is disabled", EXIT_FAILED),
        (ConflictError(SECRET), "the request conflicts with existing data", EXIT_CONFLICT),
        (NotFoundError(SECRET), "not found", EXIT_FAILED),
        (SidekickError(SECRET), "the request was refused (sidekick_error)", EXIT_FAILED),
        (KeyError(SECRET), "unexpected error (KeyError)", EXIT_UNEXPECTED),
    ],
)
def test_describe_failure_ignores_the_text_of_the_error(
    error: Exception, message: str, code: int
) -> None:
    failure = describe_failure(error)

    assert (failure.message, failure.exit_code) == (message, code)
    assert SECRET not in failure.message


@pytest.mark.integration
def test_a_real_duplicate_login_ends_in_the_fixed_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from sidekick.shared.auth import AuthService
    from tests.db import database_factory

    auth = AuthService(database_factory(), "pepper" * 6)
    auth.provision_user(SECRET, "First")
    use_admin(monkeypatch, auth, "create-user", "--login", SECRET, "--display-name", "Second")

    assert exit_code(auth_cli.main) == EXIT_CONFLICT

    assert_fixed_failure(capsys, message="user already exists", command="sidekick-admin")


def test_admin_other_unique_clash_is_not_called_a_user_clash(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    service = SimpleNamespace(provision_user=raising(duplicate("some_other_key")))
    use_admin(monkeypatch, service, "create-user", "--login", SECRET, "--display-name", SECRET)

    assert exit_code(auth_cli.main) == EXIT_CONFLICT

    assert_fixed_failure(
        capsys,
        message="the record already exists or conflicts with existing data",
        command="sidekick-admin",
    )


def test_admin_non_unique_integrity_error_is_not_called_a_user_clash(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    service = SimpleNamespace(provision_user=raising(duplicate("users_username_key", "23503")))
    use_admin(monkeypatch, service, "create-user", "--login", SECRET, "--display-name", SECRET)

    assert exit_code(auth_cli.main) == EXIT_DATABASE

    assert_fixed_failure(capsys, message="the database refused the data", command="sidekick-admin")


@pytest.mark.integration
def test_create_token_for_an_unknown_user_says_so(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from sidekick.shared.auth import AuthService
    from tests.db import database_factory

    auth = AuthService(database_factory(), "pepper" * 6)
    use_admin(
        monkeypatch,
        auth,
        "create-token",
        "--user-id",
        "018af000-0000-7000-8000-0000000000ff",
        "--label",
        SECRET,
        "--scope",
        "tasks:read",
    )

    assert exit_code(auth_cli.main) == EXIT_FAILED

    assert_fixed_failure(capsys, message="active user not found", command="sidekick-admin")


@pytest.mark.integration
def test_create_user_on_a_disabled_login_is_a_user_clash(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from sidekick.shared.auth import AuthService
    from tests.db import database_factory

    auth = AuthService(database_factory(), "pepper" * 6)
    auth.disable_user(auth.provision_user(SECRET, "First"))
    use_admin(monkeypatch, auth, "create-user", "--login", SECRET, "--display-name", "Second")

    assert exit_code(auth_cli.main) == EXIT_CONFLICT

    assert_fixed_failure(capsys, message="user already exists", command="sidekick-admin")


@pytest.mark.integration
def test_ensure_user_on_a_disabled_login_is_refused_with_its_fixed_text() -> None:
    from sidekick.shared.auth import AuthService
    from tests.db import database_factory

    auth = AuthService(database_factory(), "pepper" * 6)
    auth.disable_user(auth.provision_user(SECRET, "First"))

    with pytest.raises(RefusedError) as refused:
        auth.ensure_user(SECRET, "Second")

    failure = describe_failure(refused.value)
    assert (failure.message, failure.exit_code) == ("user exists but is disabled", EXIT_FAILED)


@pytest.mark.parametrize(
    ("argv", "failing_file", "shown"),
    [
        (["verify", "{dir}/in.skbackup"], "in.skbackup", "(backup file: in.skbackup)"),
        (
            ["extract-export", "{dir}/in.skbackup", "{dir}/gone/out.json"],
            "gone/out.json",
            "(output file: out.json)",
        ),
    ],
)
def test_backup_os_error_names_the_argument_and_the_file_not_the_directory(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Any,
    argv: list[str],
    failing_file: str,
    shown: str,
) -> None:
    def missing(*_args: object, **_kwargs: object) -> Any:
        raise FileNotFoundError(2, "No such file or directory", f"{tmp_path}/{failing_file}")

    monkeypatch.setattr(backup_cli, "_verify", missing)
    monkeypatch.setattr(backup_cli, "_extract_export", missing)

    assert backup_cli.main([part.format(dir=tmp_path) for part in argv]) == EXIT_FAILED

    err = capsys.readouterr().err
    assert f"No such file or directory {shown}" in err
    assert str(tmp_path) not in err


def test_backup_os_error_on_the_key_file_names_the_option_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Any
) -> None:
    export = tmp_path / "export.json"
    export.write_text("{}", encoding="utf-8")
    key_file = tmp_path / "secret-key-file"
    monkeypatch.setattr(backup_cli, "_import_store", lambda: object())

    code = backup_cli.main(
        ["import", str(export), "--target-owner", OWNER, "--key-file", str(key_file)]
    )

    err = capsys.readouterr().err
    assert code == EXIT_FAILED
    assert "(--key-file)" in err
    assert "secret-key-file" not in err
    assert str(tmp_path) not in err


OWNER = "00000000-0000-7000-8000-000000000001"


@pytest.mark.parametrize(
    ("error", "code", "text"),
    [
        (duplicate(), EXIT_CONFLICT, "the record already exists or conflicts with existing data"),
        (unreachable(), EXIT_DATABASE, "database error; check that it is reachable and migrated"),
    ],
)
def test_backup_import_follows_the_exit_code_table(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Any,
    error: Exception,
    code: int,
    text: str,
) -> None:
    export = tmp_path / "export.json"
    export.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(backup_cli, "_import_store", lambda: object())
    monkeypatch.setattr(backup_cli, "load_export_document", lambda *_a, **_k: {})
    monkeypatch.setattr(backup_cli, "plan_import", raising(error))

    assert backup_cli.main(["import", str(export), "--target-owner", OWNER]) == code

    assert_fixed_failure(capsys, message=text, command="sidekick-backup")
