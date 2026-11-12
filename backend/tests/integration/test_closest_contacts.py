"""Misheard names ("Elijas" for "Elias"): word-level trigram suggestions in search and list."""

from typing import Any

import pytest

from sidekick.api.app import create_container
from sidekick.contacts.application.models import CreateContactCommand
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings

SCOPES = frozenset({"contacts:read", "contacts:write", "tasks:read", "projects:read"})


def _setup(username: str) -> tuple[Any, Actor]:
    container = create_container(make_settings(), database_factory())
    user_id = container.auth.provision_user(username, username.title())
    return container, Actor(user_id, SCOPES)


def _create(container: Any, actor: Actor, name: str, key: str) -> Any:
    return container.contacts.create(actor, CreateContactCommand(name), f"closest-{key}")


def _names(container: Any, actor: Actor, query: str) -> list[str]:
    return [hit.display_name for hit in container.search.closest_contacts(actor, query)]


@pytest.mark.integration
def test_closest_contacts_finds_misheard_first_name_and_nothing_unrelated() -> None:
    container, actor = _setup("closest-names")
    _create(container, actor, "Elias Svensson", "elias")
    _create(container, actor, "Anna Lind", "anna")
    _create(container, actor, "Peter Berg", "peter")

    assert _names(container, actor, "Elijas") == ["Elias Svensson"]
    assert _names(container, actor, "Ana") == ["Anna Lind"]
    # Last name alone, and a two-word query where both words must match.
    assert _names(container, actor, "Svenson") == ["Elias Svensson"]
    assert _names(container, actor, "Elijas Svenson") == ["Elias Svensson"]
    assert _names(container, actor, "Elijas Berg") == []
    # Negative cases: unrelated names and queries too short to compare.
    assert _names(container, actor, "Zebulon") == []
    assert _names(container, actor, "El") == []
    assert _names(container, actor, "A") == []
    assert _names(container, actor, "!!") == []


@pytest.mark.integration
def test_closest_contacts_matches_short_names_one_or_two_edits_apart() -> None:
    # Peter and Petra are two substitutions apart: a 5-letter term allows two edits.
    container, actor = _setup("closest-petra")
    _create(container, actor, "Petra Lind", "petra")
    assert _names(container, actor, "Peter") == ["Petra Lind"]

    container, actor = _setup("closest-peter")
    _create(container, actor, "Peter Berg", "peter")
    assert _names(container, actor, "Petra") == ["Peter Berg"]


@pytest.mark.integration
def test_closest_contacts_does_not_suggest_a_longer_name_for_a_short_term() -> None:
    # "Johanna" ends in "anna", but it is three insertions from "Anna" and must not be suggested.
    container, actor = _setup("closest-johanna")
    _create(container, actor, "Anna Lind", "anna")
    _create(container, actor, "Johanna Berg", "johanna")
    assert _names(container, actor, "Anna") == ["Anna Lind"]

    container, actor = _setup("closest-johanna-only")
    _create(container, actor, "Johanna Berg", "johanna-only")
    assert _names(container, actor, "Anna") == []


@pytest.mark.integration
def test_closest_contacts_matches_aliases_without_returning_them() -> None:
    container, actor = _setup("closest-alias")
    contact = _create(container, actor, "Margareta Holm", "marga")
    container.contacts.add_alias(actor, contact.id, "Greta", contact.version, "closest-alias-1")

    hits = container.search.closest_contacts(actor, "Gretta")
    assert [hit.display_name for hit in hits] == ["Margareta Holm"]
    assert "Greta" not in repr(hits)


@pytest.mark.integration
def test_closest_contacts_is_owner_scoped_and_skips_archived() -> None:
    container, actor = _setup("closest-owner-a")
    other_id = container.auth.provision_user("closest-owner-b", "B")
    other = Actor(other_id, SCOPES)
    _create(container, other, "Elias Svensson", "other-elias")
    archived = _create(container, actor, "Elias Archived", "archived")
    container.contacts.archive(actor, archived.id, archived.version, "closest-archive-1")

    assert _names(container, actor, "Elijas") == []
    assert _names(container, other, "Elijas") == ["Elias Svensson"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_and_list_contacts_suggest_closest_match_on_line_one() -> None:
    container, actor = _setup("closest-mcp")
    created = _create(container, actor, "Elias Svensson", "mcp-elias")
    server = create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)

    listed = await server.call_tool("list_contacts", {"q": "Elijas"})
    lines = listed.content[0].text.split("\n")
    assert lines[0] == "Closest match: Elias Svensson?"
    assert str(created.id) in lines[1]
    assert "add_contact_alias" in lines[-1]
    names = [c["display_name"] for c in listed.structured_content["contacts"]]
    assert names == ["Elias Svensson"]

    searched = await server.call_tool("search", {"query": "Elijas"})
    lines = searched.content[0].text.split("\n")
    assert lines[0] == "Closest match: Elias Svensson?"
    assert str(created.id) in lines[1]
    hit_ids = [h["id"] for h in searched.structured_content["contacts"]["hits"]]
    assert hit_ids == [str(created.id)]

    # No near match: the old answers stay.
    miss = await server.call_tool("list_contacts", {"q": "Zebulon"})
    assert miss.content[0].text.split("\n")[0] == "No contacts found."
    assert miss.structured_content["contacts"] == []
    miss_search = await server.call_tool("search", {"query": "Zebulon"})
    assert miss_search.content[0].text == "No matches."

    # An exact hit never gets the suggestion.
    exact = await server.call_tool("list_contacts", {"q": "elias"})
    assert exact.content[0].text.startswith("1 contact: Elias Svensson.")

    # One or two characters never suggest anything.
    short = await server.call_tool("list_contacts", {"q": "Ze"})
    assert short.content[0].text.split("\n")[0] == "No contacts found."
