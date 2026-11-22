"""`ContactService.create_in_session` writes inside the caller's transaction."""

import pytest

from sidekick.api.app import create_app
from sidekick.contacts.application.models import CreateContactCommand
from sidekick.contacts.application.service import ContactService
from sidekick.contacts.domain.contact import Contact
from sidekick.shared.errors import NotFoundError, PermissionDeniedError
from sidekick.shared.types import Actor, TxSession
from tests.db import database_factory
from tests.support.settings import make_settings


class _Abort(Exception):
    pass


def _service_and_owner() -> tuple[ContactService, Actor]:
    container = create_app(make_settings(), database_factory()).state.container
    owner_id = container.auth.provision_user("in-session-owner", "Owner")
    owner = Actor(owner_id, frozenset({"contacts:read", "contacts:write"}))
    service: ContactService = container.contacts
    return service, owner


@pytest.mark.integration
def test_contact_created_in_a_session_is_kept_when_the_session_commits() -> None:
    service, owner = _service_and_owner()
    command = CreateContactCommand("Kept", aliases=["K"], tags=["work"])

    contact = service.store.transaction(
        lambda session: service.create_in_session(session, owner, command, "corr-keep")
    )

    saved = service.get(owner, contact.id)
    assert saved.display_name == "Kept"
    assert [alias.value for alias in saved.aliases] == ["K"]


@pytest.mark.integration
def test_contact_created_in_a_session_is_rolled_back_with_the_session() -> None:
    service, owner = _service_and_owner()
    created: list[Contact] = []

    def operation(session: TxSession) -> None:
        command = CreateContactCommand("Gone", aliases=["G"], tags=["work"])
        created.append(service.create_in_session(session, owner, command, "corr-gone"))
        raise _Abort

    with pytest.raises(_Abort):
        service.store.transaction(operation)

    assert len(created) == 1
    with pytest.raises(NotFoundError):
        service.get(owner, created[0].id)
    assert service.list(owner, q="Gone").items == []


@pytest.mark.integration
def test_create_in_a_session_requires_the_contacts_write_scope() -> None:
    service, owner = _service_and_owner()
    read_only = Actor(owner.user_id, frozenset({"contacts:read"}))

    with pytest.raises(PermissionDeniedError):
        service.store.transaction(
            lambda session: service.create_in_session(
                session, read_only, CreateContactCommand("Denied"), None
            )
        )
    assert service.list(owner, q="Denied").items == []
