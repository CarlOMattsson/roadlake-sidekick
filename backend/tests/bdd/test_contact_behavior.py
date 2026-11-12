"""Given/When/Then BDD examples for Contact behavior."""

from datetime import UTC, datetime
from uuid import UUID

from sidekick.contacts.application.models import CreateContactCommand, UpdateContactCommand
from sidekick.contacts.application.service import ContactService
from sidekick.shared.types import Actor
from tests.support.fakes import InMemoryStore, make_cursor_codec


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 7, 19, 12, tzinfo=UTC)


def actor(user_id: int = 1) -> Actor:
    return Actor(UUID(int=user_id), frozenset({"contacts:read", "contacts:write"}))


def test_contact_creation_and_update_lifecycle() -> None:
    store = InMemoryStore()
    service = ContactService(store, FixedClock(), make_cursor_codec())

    # Create contact
    contact = service.create(
        actor(),
        command=CreateContactCommand(
            display_name=" Rasmus ",
            context_note="Some note",
            email="rasmus@example.com",
            phone="+46123456789",
        ),
        idempotency_key="contact-001",
    )

    assert contact.display_name == "Rasmus"
    assert contact.email == "rasmus@example.com"
    assert contact.phone == "+46123456789"
    assert contact.version == 1
    assert not contact.archived

    # Update contact
    updated = service.update(
        actor(),
        contact_id=contact.id,
        expected_version=1,
        command=UpdateContactCommand(
            display_name="Rasmus Updated",
        ),
        idempotency_key="contact-002",
    )

    assert updated.display_name == "Rasmus Updated"
    assert updated.version == 2

    # Archive contact
    archived = service.archive(
        actor(),
        contact_id=contact.id,
        expected_version=2,
        idempotency_key="contact-003",
    )
    assert archived.archived
    assert archived.version == 3

    # Restore contact
    restored = service.restore(
        actor(),
        contact_id=contact.id,
        expected_version=3,
        idempotency_key="contact-004",
    )
    assert not restored.archived
    assert restored.version == 4
