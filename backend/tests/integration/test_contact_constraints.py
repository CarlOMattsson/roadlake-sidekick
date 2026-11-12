"""Integration tests for database-level constraints on contacts, aliases, and relations."""

# SQL strings intentionally retain their schema-level readability.
# ruff: noqa: E501, SIM117

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from sidekick.shared.types.core import new_uuid7
from tests.db import require_test_database_url


@pytest.fixture(scope="module")
def engine():
    return create_engine(require_test_database_url())


@pytest.mark.integration
def test_contact_constraints_and_composite_keys(engine) -> None:
    owner_id_1 = new_uuid7()
    owner_id_2 = new_uuid7()

    with engine.begin() as conn:
        # Create users to satisfy FKs
        conn.execute(
            text(
                "INSERT INTO sidekick.users (id, username, display_name, created_at) "
                "VALUES (:id, :username, :name, now())"
            ),
            [
                {"id": owner_id_1, "username": f"user_{owner_id_1}", "name": "Owner 1"},
                {"id": owner_id_2, "username": f"user_{owner_id_2}", "name": "Owner 2"},
            ],
        )

        contact_id_1 = new_uuid7()

        # 1. Test basic insert
        conn.execute(
            text(
                "INSERT INTO sidekick.contacts (id, owner_id, display_name, display_name_key, created_at, updated_at, version, archived) "
                "VALUES (:id, :owner_id, 'Rasmus', 'rasmus', now(), now(), 1, false)"
            ),
            {"id": contact_id_1, "owner_id": owner_id_1},
        )

        # Archive state has one consistent representation across both stored columns.
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(
                text("UPDATE sidekick.contacts SET archived = true WHERE id = :id"),
                {"id": contact_id_1},
            )
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(
                text("UPDATE sidekick.contacts SET archived_at = now() WHERE id = :id"),
                {"id": contact_id_1},
            )

        # 2. Verify we cannot insert contact with blank name (should trigger check constraint)
        with pytest.raises(IntegrityError):
            with conn.begin_nested():
                conn.execute(
                    text(
                        "INSERT INTO sidekick.contacts (id, owner_id, display_name, display_name_key, created_at, updated_at, version, archived) "
                        "VALUES (:id, :owner_id, '', '', now(), now(), 1, false)"
                    ),
                    {"id": new_uuid7(), "owner_id": owner_id_1},
                )

        # 3. Verify paired email constraint
        with pytest.raises(IntegrityError):
            with conn.begin_nested():
                conn.execute(
                    text(
                        "INSERT INTO sidekick.contacts (id, owner_id, display_name, display_name_key, email, email_key, created_at, updated_at, version, archived) "
                        "VALUES (:id, :owner_id, 'Rasmus', 'rasmus', 'rasmus@example.com', NULL, now(), now(), 1, false)"
                    ),
                    {"id": new_uuid7(), "owner_id": owner_id_1},
                )

        # 4. Verify paired phone constraint
        with pytest.raises(IntegrityError):
            with conn.begin_nested():
                conn.execute(
                    text(
                        "INSERT INTO sidekick.contacts (id, owner_id, display_name, display_name_key, phone, phone_key, created_at, updated_at, version, archived) "
                        "VALUES (:id, :owner_id, 'Rasmus', 'rasmus', '+123', NULL, now(), now(), 1, false)"
                    ),
                    {"id": new_uuid7(), "owner_id": owner_id_1},
                )

        # 5. Verify same-contact unique alias constraint
        alias_id_1 = new_uuid7()
        conn.execute(
            text(
                "INSERT INTO sidekick.contact_aliases (id, owner_id, contact_id, display_value, normalized_key, created_at) "
                "VALUES (:id, :owner_id, :contact_id, 'Raz', 'raz', now())"
            ),
            {"id": alias_id_1, "owner_id": owner_id_1, "contact_id": contact_id_1},
        )

        # Adding same alias to same contact should trigger unique violation
        with pytest.raises(IntegrityError):
            with conn.begin_nested():
                conn.execute(
                    text(
                        "INSERT INTO sidekick.contact_aliases (id, owner_id, contact_id, display_value, normalized_key, created_at) "
                        "VALUES (:id, :owner_id, :contact_id, 'Raz', 'raz', now())"
                    ),
                    {"id": new_uuid7(), "owner_id": owner_id_1, "contact_id": contact_id_1},
                )

        # 6. Verify cross-owner project contact constraint
        domain_id = new_uuid7()
        project_id = new_uuid7()
        # Every Project needs an owner-consistent Domain ancestry.
        conn.execute(
            text(
                "INSERT INTO sidekick.domains (id, owner_id, name, status, version, created_at, updated_at) "
                "VALUES (:id, :owner_id, 'Domain 1', 'active', 1, now(), now())"
            ),
            {"id": domain_id, "owner_id": owner_id_1},
        )
        # Create a project owned by Owner 1
        conn.execute(
            text(
                "INSERT INTO sidekick.projects "
                "(id, owner_id, domain_id, title, status, version, created_at, updated_at) "
                "VALUES (:id, :owner_id, :domain_id, 'Project 1', 'active', 1, now(), now())"
            ),
            {"id": project_id, "owner_id": owner_id_1, "domain_id": domain_id},
        )

        # Link works for project & contact owned by the same user
        conn.execute(
            text(
                "INSERT INTO sidekick.project_contacts (owner_id, project_id, contact_id, created_at) "
                "VALUES (:owner_id, :project_id, :contact_id, now())"
            ),
            {"owner_id": owner_id_1, "project_id": project_id, "contact_id": contact_id_1},
        )

        # Create a contact owned by Owner 2
        contact_id_2 = new_uuid7()
        conn.execute(
            text(
                "INSERT INTO sidekick.contacts (id, owner_id, display_name, display_name_key, created_at, updated_at, version, archived) "
                "VALUES (:id, :owner_id, 'Rasmus 2', 'rasmus 2', now(), now(), 1, false)"
            ),
            {"id": contact_id_2, "owner_id": owner_id_2},
        )

        # Linking Project (Owner 1) with Contact (Owner 2) under Owner 2's session
        with pytest.raises(IntegrityError):
            with conn.begin_nested():
                conn.execute(
                    text(
                        "INSERT INTO sidekick.project_contacts (owner_id, project_id, contact_id, created_at) "
                        "VALUES (:owner_id, :project_id, :contact_id, now())"
                    ),
                    {"owner_id": owner_id_2, "project_id": project_id, "contact_id": contact_id_2},
                )
