"""Every app resource declares the instance's license state in its head (D-081), next to the rooms
and the build, so the app shows or hides its reminder without a request of its own."""

from __future__ import annotations

import json
from datetime import date
from html import unescape
from pathlib import Path

import pytest
from fastmcp import Client
from mcp.types import TextResourceContents

from sidekick.api.app import Container, create_container
from sidekick.license.public_key import PLACEHOLDER_PUBLIC_KEY
from sidekick.mcp import app_meta
from sidekick.mcp.server import create_mcp_server
from sidekick.mcp.sidekick_app import SIDEKICK_APP_URI
from sidekick.shared.types import Actor, new_uuid7
from tests.db import database_factory
from tests.support.license_support import OWNER_PUBLIC, signed_key
from tests.support.settings import make_settings

ALL_APP_URIS = (SIDEKICK_APP_URI,)
HTML = "<!doctype html><html><head></head><body>UNIFIED</body></html>"
READER = Actor(new_uuid7(), frozenset({"tasks:read", "journal:read", "shopping:read"}))
UNLICENSED_JSON = {"state": "unlicensed"}
TAG = '<meta name="sidekick-license" content="'


@pytest.fixture(autouse=True)
def served_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / app_meta.UNIFIED_APP_FILE).write_text(HTML, encoding="utf-8")
    monkeypatch.setattr("sidekick.mcp.app_meta.APPS_DIR", tmp_path)


def container_with(public_key: str) -> Container:
    settings = make_settings().model_copy(update={"license_public_key": public_key})
    return create_container(settings, database_factory())


def declared(html: str) -> dict[str, str | None]:
    assert html.count(TAG) == 1
    return json.loads(unescape(html.split(TAG, 1)[1].split('">', 1)[0]))


async def read(container: Container, uri: str) -> str:
    server = create_mcp_server(container, actor_provider=lambda: READER, enable_auth=False)
    async with Client(server) as client:
        content = (await client.read_resource(uri))[0]
    assert isinstance(content, TextResourceContents)
    return content.text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_instance_without_a_key_declares_itself_unlicensed_in_every_app() -> None:
    container = container_with(OWNER_PUBLIC)
    for uri in ALL_APP_URIS:
        html = await read(container, uri)
        assert declared(html) == UNLICENSED_JSON, uri
        # Next to the other declarations, never instead of them.
        assert '<meta name="sidekick-rooms" content="' in html, uri
        assert '<meta name="sidekick-app-locale" content="' in html, uri


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_stored_key_is_declared_with_who_what_and_until_when_but_never_the_key() -> None:
    container = container_with(OWNER_PUBLIC)
    licensee = 'Bolaget "AB" <Co> & Söner'
    key = signed_key(expires=date(2099, 1, 1), kind="org", licensee=licensee)
    assert container.license.set_key(key).accepted
    for uri in ALL_APP_URIS:
        html = await read(container, uri)
        assert declared(html) == {
            "state": "licensed",
            "licensee": licensee,
            "kind": "org",
            "expires": "2099-01-01",
        }, uri
        assert key not in html and key.split(".")[2] not in html
        # The free-text name cannot break out of the attribute.
        assert "<Co>" not in html and '"AB"' not in html


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_licensee_that_tries_to_close_the_tag_and_script_stays_inert_text() -> None:
    container = container_with(OWNER_PUBLIC)
    licensee = "\"><script>x</script>&'"
    assert container.license.set_key(signed_key(licensee=licensee)).accepted
    for uri in ALL_APP_URIS:
        html = await read(container, uri)
        assert "<script>x" not in html and "</script>&" not in html, uri
        assert html.count("<script") == 0, uri
        assert declared(html)["licensee"] == licensee, uri


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_declaration_follows_the_stored_key_without_a_restart() -> None:
    container = container_with(OWNER_PUBLIC)
    assert declared(await read(container, SIDEKICK_APP_URI))["state"] == "unlicensed"
    container.license.set_key(signed_key(expires=date(2020, 1, 1)))
    assert declared(await read(container, SIDEKICK_APP_URI))["state"] == "expired"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_placeholder_public_key_declares_unlicensed_whatever_is_stored() -> None:
    working = container_with(OWNER_PUBLIC)
    assert working.license.set_key(signed_key()).accepted
    # Same database, an instance that has no real public key.
    settings = make_settings().model_copy(update={"license_public_key": PLACEHOLDER_PUBLIC_KEY})
    placeholder = create_container(settings, working.session_factory)
    for uri in ALL_APP_URIS:
        assert declared(await read(placeholder, uri)) == UNLICENSED_JSON, uri
