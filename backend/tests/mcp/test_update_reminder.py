"""Every app resource declares the update reminder (SIDEKICK_UPDATE_REMINDER_DAYS) in its head."""

from collections.abc import Mapping
from pathlib import Path

import pytest
from fastmcp import Client
from mcp.types import TextResourceContents

from sidekick.api.app import create_container
from sidekick.mcp import app_meta
from sidekick.mcp.server import create_mcp_server
from sidekick.mcp.sidekick_app import SIDEKICK_APP_URI
from sidekick.shared import build_info
from sidekick.shared.types import Actor, new_uuid7
from tests.support.settings import make_settings

ALL_APP_URIS = (SIDEKICK_APP_URI,)
HTML = "<!doctype html><html><head></head><body>UNIFIED</body></html>"
BUILD = {"build_commit": "abc1234", "build_date": "2026-11-09T19:38:35+01:00"}


def no_checkout(repo: Path) -> None:
    return None


@pytest.fixture(autouse=True)
def served_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / app_meta.UNIFIED_APP_FILE).write_text(HTML, encoding="utf-8")
    monkeypatch.setattr("sidekick.mcp.app_meta.APPS_DIR", tmp_path)
    build_info.resolved_build_info.cache_clear()


async def read_all(overrides: Mapping[str, object]) -> dict[str, str]:
    settings = make_settings().model_copy(update=overrides)
    reader = Actor(new_uuid7(), frozenset({"tasks:read", "journal:read", "shopping:read"}))
    server = create_mcp_server(
        create_container(settings), actor_provider=lambda: reader, enable_auth=False
    )
    pages: dict[str, str] = {}
    async with Client(server) as client:
        for uri in ALL_APP_URIS:
            content = (await client.read_resource(uri))[0]
            assert isinstance(content, TextResourceContents)
            pages[uri] = content.text
    return pages


@pytest.mark.asyncio
async def test_every_app_resource_declares_the_running_build_and_the_days() -> None:
    for uri, html in (await read_all(BUILD)).items():
        assert '<meta name="sidekick-build-commit" content="abc1234">' in html, uri
        assert '<meta name="sidekick-build-date" content="2026-11-09T18:38:35+00:00">' in html, uri
        assert '<meta name="sidekick-update-days" content="14">' in html, uri


@pytest.mark.asyncio
async def test_the_days_setting_is_declared_as_given() -> None:
    for html in (await read_all({**BUILD, "update_reminder_days": 30})).values():
        assert '<meta name="sidekick-update-days" content="30">' in html


@pytest.mark.asyncio
async def test_zero_days_declares_nothing() -> None:
    for uri, html in (await read_all({**BUILD, "update_reminder_days": 0})).items():
        assert "sidekick-build" not in html, uri
        assert "sidekick-update-days" not in html, uri


@pytest.mark.asyncio
async def test_an_unknown_date_declares_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(build_info, "read_git_build_info", no_checkout)
    for uri, html in (await read_all({})).items():
        assert "sidekick-build" not in html, uri
        assert "sidekick-update-days" not in html, uri
