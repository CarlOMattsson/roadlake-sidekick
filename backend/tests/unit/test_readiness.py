"""Readiness: the expected revision is the newest migration file; any failure is not ready."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from sidekick.shared import readiness
from sidekick.shared.db_timeouts import DatabaseTimeouts


def test_expected_head_is_the_newest_numbered_migration(tmp_path: Path) -> None:
    for name in ("001_initial", "009_nine", "010_ten", "yoyo", "notes"):
        (tmp_path / f"{name}.py").write_text("", encoding="utf-8")
    (tmp_path / "011_not_python.sql").write_text("", encoding="utf-8")
    assert readiness.expected_schema_head(tmp_path) == "010_ten"


def test_the_repository_head_is_a_real_migration_file() -> None:
    head = readiness.expected_schema_head()
    assert (readiness.DEFAULT_MIGRATIONS_DIR / f"{head}.py").is_file()


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
