"""Readiness: every numbered migration file must be applied; any failure is not ready."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from sidekick.shared import readiness
from sidekick.shared.db_timeouts import DatabaseTimeouts


def test_expected_migrations_are_every_numbered_file_in_number_order(tmp_path: Path) -> None:
    for name in ("010_ten", "001_initial", "009_nine", "yoyo", "notes"):
        (tmp_path / f"{name}.py").write_text("", encoding="utf-8")

    assert readiness.expected_migration_ids(tmp_path) == ["001_initial", "009_nine", "010_ten"]


def test_the_repository_migrations_are_real_files_in_number_order() -> None:
    expected = readiness.expected_migration_ids()
    assert all((readiness.DEFAULT_MIGRATIONS_DIR / f"{name}.py").is_file() for name in expected)
    assert expected == sorted(expected)


def test_no_migrations_directory_is_not_ready(tmp_path: Path) -> None:
    def never_called() -> None:
        raise AssertionError("the database must not be asked without an expected revision")

    assert readiness.is_ready(never_called, tmp_path) is False  # type: ignore[arg-type]


def test_a_database_that_does_not_answer_is_not_ready(tmp_path: Path) -> None:
    (tmp_path / "001_initial.py").write_text("", encoding="utf-8")

    def unreachable() -> None:
        raise ConnectionError("database down")

    assert readiness.is_ready(unreachable, tmp_path) is False  # type: ignore[arg-type]


@pytest.mark.parametrize(("ready", "status", "word"), [(True, 0, "ok"), (False, 1, "not ready")])
def test_command_reports_one_word_and_the_exit_status(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    ready: bool,
    status: int,
    word: str,
) -> None:
    monkeypatch.setattr(
        "sidekick.shared.config.get_settings",
        lambda: SimpleNamespace(
            database_url="postgresql+psycopg://unused", database_timeouts=DatabaseTimeouts()
        ),
    )
    monkeypatch.setattr(
        "sidekick.shared.persistence.create_session_factory", lambda _url, **_kw: object()
    )
    monkeypatch.setattr(readiness, "is_ready", lambda _factory: ready)
    with pytest.raises(SystemExit) as raised:
        readiness.main()
    assert raised.value.code == status
    assert capsys.readouterr().out == f"{word}\n"
