"""Runtime checks for the greenfield Work schema and least-privilege boundary."""

import re

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from sidekick.shared.types import new_uuid7
from tests.db import require_test_database_url


@pytest.mark.integration
def test_work_schema_has_required_project_ancestry_and_indexes() -> None:
    engine = create_engine(require_test_database_url())
    try:
        with engine.begin() as connection:
            nullable = connection.scalar(
                text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_schema = 'sidekick' AND table_name = 'projects' "
                    "AND column_name = 'domain_id'"
                )
            )
            assert nullable == "NO"
            indexes = set(
                connection.scalars(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE schemaname = 'sidekick' AND tablename IN "
                        "('domains', 'processes', 'projects', 'tasks', 'steps', 'actions')"
                    )
                )
            )
            assert {
                "ix_domains_owner_updated",
                "ix_processes_owner_domain_updated",
                "ix_projects_owner_domain_updated",
                "ix_tasks_owner_domain_updated",
                "ix_steps_task_position",
                "ix_actions_step_position",
            } <= indexes
    finally:
        engine.dispose()


@pytest.mark.integration
def test_work_runtime_role_cannot_own_ddl() -> None:
    engine = create_engine(require_test_database_url())
    try:
        with (
            engine.begin() as connection,
            pytest.raises(ProgrammingError),
            connection.begin_nested(),
        ):
            connection.execute(text("CREATE TABLE sidekick.work_runtime_ddl_probe(id integer)"))
    finally:
        engine.dispose()


@pytest.mark.integration
def test_project_domain_is_required_by_the_schema() -> None:
    """The schema itself refuses a Project without a Domain.

    This replaces a test that ran `ALTER COLUMN ... SET NOT NULL` over a NULL row and expected
    PostgreSQL to refuse: it exercised PostgreSQL, not the migration, and mutated the shared
    schema. Here the column the migration created is asserted, and the rejection is observed on
    an insert that is rolled back, so nothing is changed.
    """

    admin = create_engine(require_test_database_url("SIDEKICK_TEST_ADMIN_DATABASE_URL"))
    owner_id, project_id = new_uuid7(), new_uuid7()
    try:
        with admin.connect() as connection:
            transaction = connection.begin()
            try:
                assert (
                    connection.scalar(
                        text(
                            "SELECT is_nullable FROM information_schema.columns WHERE "
                            "table_schema = 'sidekick' AND table_name = 'projects' "
                            "AND column_name = 'domain_id'"
                        )
                    )
                    == "NO"
                )
                connection.execute(
                    text(
                        "INSERT INTO sidekick.users "
                        "(id, username, display_name, created_at) "
                        "VALUES (:id, :username, 'Reset Owner', now())"
                    ),
                    {"id": owner_id, "username": f"reset-owner-{owner_id}"},
                )
                with pytest.raises(IntegrityError, match="domain_id"):
                    connection.execute(
                        text(
                            "INSERT INTO sidekick.projects (id, owner_id, domain_id, title, "
                            "status, created_at, updated_at, version) "
                            "VALUES (:id, :owner, NULL, 'Incompatible', 'active', now(), now(), 1)"
                        ),
                        {"id": project_id, "owner": owner_id},
                    )
            finally:
                transaction.rollback()
    finally:
        admin.dispose()


@pytest.mark.integration
def test_work_projection_queries_have_owner_scoped_index_plans() -> None:
    engine = create_engine(require_test_database_url())
    try:
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL enable_seqscan = off"))
            for table in ("projects", "tasks", "domains"):
                connection.execute(text(f"ANALYZE sidekick.{table}"))
            plans = [
                connection.scalars(
                    text(
                        "EXPLAIN (FORMAT TEXT, COSTS OFF) SELECT id FROM sidekick.projects "
                        "WHERE owner_id = :owner ORDER BY updated_at DESC, id DESC LIMIT 100"
                    ),
                    {"owner": new_uuid7()},
                ).all(),
                connection.scalars(
                    text(
                        "EXPLAIN (FORMAT TEXT, COSTS OFF) SELECT id FROM sidekick.tasks "
                        "WHERE owner_id = :owner ORDER BY updated_at DESC, id DESC LIMIT 100"
                    ),
                    {"owner": new_uuid7()},
                ).all(),
                connection.scalars(
                    text(
                        "EXPLAIN (FORMAT TEXT, COSTS OFF) SELECT id FROM sidekick.domains "
                        "WHERE owner_id = :owner ORDER BY updated_at DESC, id DESC LIMIT 100"
                    ),
                    {"owner": new_uuid7()},
                ).all(),
            ]
        # Which owner index the planner picks may vary (other owner indexes exist); what matters
        # is that every projection reads through an index whose condition names the owner.
        for plan in plans:
            plan_text = " ".join(str(line) for line in plan)
            assert "Seq Scan" not in plan_text, plan_text
            assert re.search(r"Index Cond: \(owner_id = ", plan_text), plan_text
    finally:
        engine.dispose()
