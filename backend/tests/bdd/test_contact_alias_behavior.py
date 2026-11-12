"""BDD examples for Contact Alias uniqueness, bounds, and version transitions."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from sidekick.contacts.application.service import (
    ContactService,
    CreateContactCommand,
)
from sidekick.shared.errors import ValidationError
from sidekick.shared.types import Actor
from tests.support.fakes import InMemoryStore, make_cursor_codec


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 7, 19, 12, tzinfo=UTC)


def actor(user_id: int = 1) -> Actor:
    return Actor(UUID(int=user_id), frozenset({"contacts:read", "contacts:write"}))


def test_alias_max_count_enforcement() -> None:
    store = InMemoryStore()
    service = ContactService(store, FixedClock(), make_cursor_codec())

    # 1. Create a Contact
    contact = service.create(
        actor(),
        command=CreateContactCommand(display_name="Rasmus"),
        idempotency_key="contact-alias-max-test",
    )

    # 2. Add 20 aliases
    for i in range(20):
        # The add_alias method is expected to exist and should increment version and lock
        contact = service.add_alias(
            actor(),
            contact_id=contact.id,
            value=f"Alias {i}",
            expected_version=contact.version,
            idempotency_key=f"alias-add-{i}",
        )
    assert len(contact.aliases) == 20
    assert contact.version == 21

    # 3. Adding the 21st alias should raise a ValidationError
    with pytest.raises(ValidationError, match="maximum of 20 aliases"):
        service.add_alias(
            actor(),
            contact_id=contact.id,
            value="Too Many",
            expected_version=contact.version,
            idempotency_key="alias-add-21",
        )
