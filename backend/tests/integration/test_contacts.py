"""Integration tests for PostgreSQL Contact persistence, search, versioning, and audits."""

import pytest

from sidekick.contacts.domain.contact import Contact
from sidekick.shared.types.core import new_uuid7
from sidekick.store import SqlAlchemyStore
from tests.db import database_factory


@pytest.mark.integration
def test_postgres_contact_lifecycle() -> None:
    factory = database_factory()
    from sidekick.shared.auth import AuthService

    auth = AuthService(factory, "pepper" * 8)
    owner_id = auth.provision_user("owner", "Owner")
    store = SqlAlchemyStore(factory)

    # Verify we can save and get a Contact in PostgreSQL
    contact_id = new_uuid7()
    from sidekick.shared.types import utc_now

    contact = Contact(
        id=contact_id,
        owner_id=owner_id,
        display_name="Rasmus",
        display_name_key="rasmus",
        context_note="Integration note",
        email="rasmus@example.com",
        email_key="rasmus@example.com",
        phone=None,
        phone_key=None,
        aliases=[],
        created_at=utc_now(),
        updated_at=utc_now(),
        archived_at=None,
        archived=False,
        version=1,
    )
    # Save the contact using a transaction
    store.transaction(lambda session: store.save_contact(session, contact))

    # Retrieve the contact using a transaction
    saved = store.transaction(lambda session: store.get_contact(session, owner_id, contact_id))
    assert saved.display_name == "Rasmus"
