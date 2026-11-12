"""Unit tests for the Contact profile fields: relationship, organization, role, address."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from sidekick.contacts.application.service import (
    UpdateContactCommand,
    contact_to_data,
)
from sidekick.contacts.domain.contact import Contact
from sidekick.contacts.domain.normalization import PROFILE_FIELD_LIMITS, normalize_profile_text
from sidekick.shared.errors import ValidationError
from sidekick.shared.replay import id_replay_record
from sidekick.shared.types import UNSET

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def make_contact(**overrides: object) -> Contact:
    values: dict[str, object] = {
        "id": UUID(int=1),
        "owner_id": UUID(int=2),
        "display_name": "Anna",
        "display_name_key": "anna",
        "context_note": None,
        "email": None,
        "email_key": None,
        "phone": None,
        "phone_key": None,
        "aliases": [],
        "archived": False,
        "created_at": NOW,
        "updated_at": NOW,
        "archived_at": None,
    }
    values.update(overrides)
    return Contact(**values)  # type: ignore[arg-type]


def test_the_limits_are_the_agreed_ones() -> None:
    assert PROFILE_FIELD_LIMITS == {
        "relationship": 80,
        "organization": 200,
        "role": 120,
        "address": 500,
    }


@pytest.mark.parametrize("field", list(PROFILE_FIELD_LIMITS))
def test_normalize_trims_clears_blank_and_enforces_the_limit(field: str) -> None:
    limit = PROFILE_FIELD_LIMITS[field]
    assert normalize_profile_text(None, field) is None
    assert normalize_profile_text("   ", field) is None
    assert normalize_profile_text("  syster  ", field) == "syster"
    assert normalize_profile_text("x" * limit, field) == "x" * limit
    with pytest.raises(ValidationError):
        normalize_profile_text("x" * (limit + 1), field)
    with pytest.raises(ValidationError):
        normalize_profile_text("bad\u0000value", field)


def test_update_sets_changes_and_clears_each_profile_field() -> None:
    contact = make_contact()

    updated = contact.update(
        now=NOW,
        relationship="syster",
        organization="Acme AB",
        role="VD",
        address="Storgatan 1, 111 22 Stad",
    )
    assert (updated.relationship, updated.organization, updated.role, updated.address) == (
        "syster",
        "Acme AB",
        "VD",
        "Storgatan 1, 111 22 Stad",
    )
    assert updated.version == 2

    untouched = updated.update(now=NOW, display_name="Anna B")
    assert untouched.relationship == "syster"
    assert untouched.address == "Storgatan 1, 111 22 Stad"

    cleared = untouched.update(
        now=NOW, relationship=None, organization=None, role=None, address=None
    )
    assert (cleared.relationship, cleared.organization, cleared.role, cleared.address) == (
        None,
        None,
        None,
        None,
    )


@pytest.mark.parametrize("field", list(PROFILE_FIELD_LIMITS))
def test_update_rejects_over_long_values(field: str) -> None:
    with pytest.raises(ValidationError):
        make_contact().update(now=NOW, **{field: "x" * (PROFILE_FIELD_LIMITS[field] + 1)})


@pytest.mark.parametrize("field", list(PROFILE_FIELD_LIMITS))
def test_the_aggregate_refuses_over_long_values(field: str) -> None:
    with pytest.raises(ValidationError):
        make_contact(**{field: "x" * (PROFILE_FIELD_LIMITS[field] + 1)})


def test_update_command_only_reports_the_fields_that_were_set() -> None:
    assert UpdateContactCommand().changes() == {}
    command = UpdateContactCommand(role=None, address="Storgatan 1")
    assert command.changes() == {"role": None, "address": "Storgatan 1"}
    assert command.relationship is UNSET


def test_idempotency_record_keeps_only_the_contact_id() -> None:
    contact = make_contact(relationship="kollega", organization="Acme", role="CTO", address="X 1")
    assert id_replay_record(contact_to_data(contact)) == {"id": str(contact.id)}
