"""Integration tests for alias persistence, retries, search, and owner isolation."""

import pytest

from sidekick.api.app import create_app
from sidekick.contacts.application.models import CreateContactCommand
from sidekick.shared.errors import ConflictError, NotFoundError, ValidationError
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings


@pytest.mark.integration
def test_postgres_alias_uniqueness_and_isolation() -> None:
    app = create_app(make_settings(), database_factory())
    owner_id = app.state.container.auth.provision_user("alias-owner", "Owner")
    other_id = app.state.container.auth.provision_user("alias-other", "Other")
    owner = Actor(owner_id, frozenset({"contacts:read", "contacts:write"}))
    other = Actor(other_id, frozenset({"contacts:read", "contacts:write"}))
    service = app.state.container.contacts
    first = service.create(owner, CreateContactCommand("First"), "alias-first")
    second = service.create(owner, CreateContactCommand("Second"), "alias-second")

    added = service.add_alias(owner, first.id, " Straße ", first.version, "alias-add")
    replay = service.add_alias(owner, first.id, " Straße ", first.version, "alias-add")
    assert replay == added
    with pytest.raises(ConflictError):
        service.add_alias(owner, first.id, "Other", first.version, "alias-add")
    with pytest.raises(ValidationError):
        service.add_alias(owner, first.id, "STRASSE", added.version, "alias-duplicate")

    second = service.add_alias(owner, second.id, "STRASSE", second.version, "alias-other-contact")
    matches = service.list(owner, q="strasse")
    assert {contact.id for contact in matches.items} == {first.id, second.id}
    with pytest.raises(NotFoundError):
        service.get(other, first.id)
    assert second.aliases[0].value == "STRASSE"
