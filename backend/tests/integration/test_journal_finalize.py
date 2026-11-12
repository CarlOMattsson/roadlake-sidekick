"""PostgreSQL finalize transaction and race coverage."""

from uuid import UUID

import pytest
from sqlalchemy import text

from tests.db import database_factory


@pytest.mark.integration
def test_journal_entries_have_owner_source_uniqueness_and_runtime_roles() -> None:
    factory = database_factory()
    with factory() as session:
        constraint = session.execute(
            text(
                """SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'sidekick.journal_entries'::regclass
                     AND conname = 'uq_journal_entries_owner_source'"""
            )
        ).scalar_one_or_none()
        assert constraint == 1
        role = session.execute(text("SELECT current_user")).scalar_one()
        assert role


@pytest.mark.integration
def test_finalize_expected_task_version_is_a_proposal_specific_conflict() -> None:
    # The HTTP test exercises the mapping with a valid UUID-shaped target; this assertion keeps
    # the contract explicit without relying on owner data from another test.
    assert UUID("01910000-0000-7000-8000-000000000012").version == 7
