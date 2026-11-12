"""Readiness against a real migrated database, read through the runtime role (baseline grant)."""

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from sidekick.shared import readiness
from tests.db import database_factory

pytestmark = pytest.mark.integration


def test_a_migrated_database_is_ready() -> None:
    assert readiness.is_ready(database_factory()) is True


def test_a_database_behind_the_image_is_not_ready(tmp_path: Path) -> None:
    (tmp_path / "999_from_the_future.py").write_text("", encoding="utf-8")
    assert readiness.is_ready(database_factory(), tmp_path) is False


def test_a_database_ahead_of_the_image_is_still_ready(tmp_path: Path) -> None:
    """An expand-class rollback runs an older image on a newer schema; that must stay ready."""

    (tmp_path / "100_baseline_0_1_0.py").write_text("", encoding="utf-8")
    assert readiness.is_ready(database_factory(), tmp_path) is True


def test_the_runtime_role_can_read_but_never_change_the_migration_record() -> None:
    factory = database_factory()
    with factory() as session:
        assert session.scalar(text("SELECT count(*) FROM public._yoyo_migration")) > 0
    with factory() as session, pytest.raises(ProgrammingError):
        session.execute(text("DELETE FROM public._yoyo_migration"))
