"""Integration tests for SQLAlchemy ORM models of contacts and relationships."""

import pytest

from sidekick.shared.persistence.models import (
    ContactAliasRow,
    ContactRow,
    ProjectContactRow,
    TaskContactRow,
)


@pytest.mark.integration
def test_orm_mapping_attributes() -> None:
    # Verify that the mapped columns match the requirements of 002
    assert hasattr(ContactRow, "id")
    assert hasattr(ContactRow, "owner_id")
    assert hasattr(ContactRow, "display_name")
    assert hasattr(ContactRow, "display_name_key")
    assert hasattr(ContactRow, "context_note")
    assert hasattr(ContactRow, "email")
    assert hasattr(ContactRow, "email_key")
    assert hasattr(ContactRow, "phone")
    assert hasattr(ContactRow, "phone_key")
    assert hasattr(ContactRow, "created_at")
    assert hasattr(ContactRow, "updated_at")
    assert hasattr(ContactRow, "archived_at")
    assert hasattr(ContactRow, "version")

    assert hasattr(ContactAliasRow, "id")
    assert hasattr(ContactAliasRow, "owner_id")
    assert hasattr(ContactAliasRow, "contact_id")
    assert hasattr(ContactAliasRow, "display_value")
    assert hasattr(ContactAliasRow, "normalized_key")
    assert hasattr(ContactAliasRow, "created_at")

    assert hasattr(ProjectContactRow, "owner_id")
    assert hasattr(ProjectContactRow, "project_id")
    assert hasattr(ProjectContactRow, "contact_id")
    assert hasattr(ProjectContactRow, "created_at")

    assert hasattr(TaskContactRow, "owner_id")
    assert hasattr(TaskContactRow, "task_id")
    assert hasattr(TaskContactRow, "contact_id")
    assert hasattr(TaskContactRow, "created_at")
