"""Readiness needs every migration of the image applied, not only one with a high number.

A database that has the newest numbered migration but misses an earlier one of the chain (here a
database that applied 124 but not 121 and what depends on it) is behind the image, however the
numbers sort. The deletes run in a transaction that is rolled back.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from sidekick.shared import readiness
from tests.db import database_factory
from tests.support.migration_baseline import _admin_url, rebuilt_schema  # noqa: F401


@contextmanager
def _applied_without(*migration_ids: str) -> Iterator[sessionmaker[Session]]:
    """Sessions on a connection where the named migrations are not recorded as applied."""

    database_factory()
    engine = create_engine(_admin_url())
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                for migration_id in migration_ids:
                    connection.execute(
                        text("DELETE FROM public._yoyo_migration WHERE migration_id = :id"),
                        {"id": migration_id},
                    )
                yield sessionmaker(bind=connection)
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_a_database_with_every_migration_of_the_image_is_ready() -> None:
    with _applied_without() as factory:
        assert readiness.is_ready(factory) is True


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_a_database_that_has_the_newest_number_but_misses_an_earlier_migration_is_not_ready() -> (
    None
):
    with _applied_without("121_review", "123_ready_conversations") as factory:
        with factory() as session:
            newest = session.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM public._yoyo_migration "
                    "WHERE migration_id = '124_journal_attachment_details')"
                )
            )
        assert newest is True
        assert readiness.is_ready(factory) is False


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_a_database_ahead_of_the_image_is_still_ready(tmp_path: Path) -> None:
    """An image older than the database lists fewer migrations, all of them applied."""

    for name in ("100_schema_baseline_0_1_0", "106_drop_retired_automation_tables"):
        (tmp_path / f"{name}.py").write_text("", encoding="utf-8")
    with _applied_without() as factory:
        assert readiness.is_ready(factory, tmp_path) is True
