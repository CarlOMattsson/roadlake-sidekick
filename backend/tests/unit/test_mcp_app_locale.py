"""The Sidekick MCP App language is a Sidekick setting: Swedish by default, never the host's."""

import pytest
from pydantic import ValidationError

from sidekick.mcp.app_meta import with_app_context, with_app_locale, with_owner_timezone
from sidekick.shared.config import Settings


def test_the_default_mcp_app_locale_is_swedish() -> None:
    assert Settings().mcp_app_locale == "sv"


def test_the_mcp_app_locale_is_read_from_its_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIDEKICK_MCP_APP_LOCALE", "en")
    assert Settings().mcp_app_locale == "en"


def test_an_unsupported_mcp_app_locale_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIDEKICK_MCP_APP_LOCALE", "de")
    with pytest.raises(ValidationError):
        Settings()


def test_the_locale_is_declared_once_in_the_document_head() -> None:
    html = '<!doctype html><html><head><meta charset="utf-8"></head><body></body></html>'
    declared = with_app_locale(html, "en")
    assert declared.count('name="sidekick-app-locale"') == 1
    assert '<head><meta name="sidekick-app-locale" content="en"><meta charset="utf-8">' in declared


def test_the_owner_timezone_is_declared_once_in_the_document_head() -> None:
    html = '<!doctype html><html><head><meta charset="utf-8"></head><body></body></html>'
    declared = with_owner_timezone(html, "America/New_York")
    assert declared.count('name="sidekick-owner-timezone"') == 1
    assert '<meta name="sidekick-owner-timezone" content="America/New_York">' in declared


def test_the_app_document_carries_the_owner_timezone_and_defaults_to_stockholm() -> None:
    html = "<html><head></head><body></body></html>"
    custom = with_app_context(html, "sv", [], None, owner_timezone="Asia/Tokyo")
    default = with_app_context(html, "sv", [], None)
    assert 'name="sidekick-owner-timezone" content="Asia/Tokyo"' in custom
    assert 'name="sidekick-owner-timezone" content="Europe/Stockholm"' in default


def test_the_ai_usage_row_is_declared_only_when_switched_on() -> None:
    html = "<html><head></head><body></body></html>"
    assert Settings.model_fields["mcp_app_show_ai_usage"].default is False
    assert "sidekick-ai-usage" not in with_app_context(html, "sv", [], None)
    shown = with_app_context(html, "sv", [], None, show_ai_usage=True)
    assert shown.count('<meta name="sidekick-ai-usage" content="on">') == 1


def test_the_room_strip_icons_default_to_auto_and_declare_nothing() -> None:
    html = "<html><head></head><body></body></html>"
    assert Settings.model_fields["mcp_app_nav_icons"].default == "auto"
    assert "sidekick-nav-icons" not in with_app_context(html, "sv", [], None)
    assert "sidekick-nav-icons" not in with_app_context(html, "sv", [], None, nav_icons="auto")


def test_the_room_strip_icons_are_declared_for_every_choice_but_auto() -> None:
    html = "<html><head></head><body></body></html>"
    for choice in ("off", "label", "only"):
        declared = with_app_context(html, "sv", [], None, nav_icons=choice)
        assert declared.count(f'<meta name="sidekick-nav-icons" content="{choice}">') == 1


def test_the_room_strip_icons_are_read_from_their_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIDEKICK_MCP_APP_NAV_ICONS", "only")
    assert Settings().mcp_app_nav_icons == "only"
    monkeypatch.setenv("SIDEKICK_MCP_APP_NAV_ICONS", "big")
    with pytest.raises(ValidationError):
        Settings()


def test_the_ai_usage_setting_is_read_from_its_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIDEKICK_MCP_APP_SHOW_AI_USAGE", "true")
    assert Settings().mcp_app_show_ai_usage is True
