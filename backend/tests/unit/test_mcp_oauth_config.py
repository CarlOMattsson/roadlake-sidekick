"""`github_oauth` MCP authentication fails closed and never echoes a secret."""

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from sidekick.shared.config import (
    Settings,
    parse_mcp_oauth_identities,
    parse_mcp_oauth_redirect_uris,
    parse_mcp_oauth_scopes,
)

USER = "018af000-0000-7000-8000-000000000001"
SECRET_SENTINEL = "client-secret-sentinel-0123456789"
KEY_SENTINEL = "signing-key-sentinel-0123456789-abcdefgh"


def oauth_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "test",
        "mcp_auth_mode": "github_oauth",
        "mcp_public_base_url": "https://box.tail1234.ts.net",
        "mcp_oauth_github_client_id": "Ov23liClientId",
        "mcp_oauth_github_client_secret": SECRET_SENTINEL,
        "mcp_oauth_signing_key": KEY_SENTINEL,
        "mcp_oauth_storage_dir": Path("/var/lib/sidekick/oauth"),
        "mcp_oauth_allowed_identities": f"github:12345={USER}",
        "mcp_oauth_scopes": "projects:read,tasks:read",
    }
    values.update(overrides)
    return Settings(**values)


def test_default_mode_is_the_unchanged_personal_token_and_needs_no_oauth_setting() -> None:
    settings = Settings()
    assert settings.mcp_auth_mode == "pat"
    assert settings.mcp_public_base_url == ""
    assert settings.mcp_oauth_github_client_secret is None


def test_a_complete_github_oauth_configuration_is_accepted_and_parsed() -> None:
    settings = oauth_settings()
    assert settings.mcp_oauth_identities == {"github:12345": UUID(USER)}
    assert settings.mcp_oauth_scope_set == {"projects:read", "tasks:read"}
    assert settings.mcp_oauth_redirect_uris == ("https://claude.ai/api/mcp/auth_callback",)
    assert settings.mcp_oauth_enable_cimd is False
    assert settings.mcp_public_base_url == "https://box.tail1234.ts.net"


def test_a_trailing_slash_on_the_public_origin_is_normalised() -> None:
    assert (
        oauth_settings(mcp_public_base_url="https://box.tail1234.ts.net/").mcp_public_base_url
        == "https://box.tail1234.ts.net"
    )


def test_plain_http_is_accepted_only_for_loopback() -> None:
    assert oauth_settings(mcp_public_base_url="http://127.0.0.1:8100").mcp_public_base_url == (
        "http://127.0.0.1:8100"
    )
    with pytest.raises(ValidationError, match="HTTPS"):
        oauth_settings(mcp_public_base_url="http://box.tail1234.ts.net")


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"mcp_public_base_url": ""}, "SIDEKICK_MCP_PUBLIC_BASE_URL is required"),
        ({"mcp_public_base_url": "https://box.example/mcp"}, "bare origin"),
        ({"mcp_public_base_url": "https://user:pw@box.example"}, "bare origin"),
        ({"mcp_public_base_url": "not a url"}, "absolute URL"),
        ({"mcp_public_base_url": "https://*.ts.net"}, "one concrete host"),
        ({"mcp_oauth_github_client_id": " "}, "CLIENT_ID is required"),
        ({"mcp_oauth_github_client_secret": None}, "CLIENT_SECRET is required"),
        ({"mcp_oauth_github_client_secret": " "}, "CLIENT_SECRET is required"),
        ({"mcp_oauth_signing_key": None}, "SIGNING_KEY is required"),
        ({"mcp_oauth_signing_key": "too-short"}, "SIGNING_KEY is required"),
        ({"mcp_oauth_signing_key": "development-" + "x" * 40}, "not a placeholder"),
        ({"mcp_oauth_signing_key": " " * 40}, "SIGNING_KEY is required"),
        ({"mcp_oauth_signing_key": "  replace-with-" + "x" * 40 + " "}, "not a placeholder"),
        ({"mcp_oauth_storage_dir": None}, "STORAGE_DIR must be an absolute path"),
        ({"mcp_oauth_storage_dir": Path("relative/dir")}, "STORAGE_DIR must be an absolute path"),
        ({"mcp_oauth_allowed_identities": ""}, "at least one identity"),
        ({"mcp_oauth_allowed_identities": "github:abc=" + USER}, "entry 1 must look like"),
        ({"mcp_oauth_allowed_identities": "octocat=" + USER}, "entry 1 must look like"),
        ({"mcp_oauth_allowed_identities": "github:1=not-a-uuid"}, "invalid user uuid"),
        ({"mcp_oauth_allowed_identities": f"github:1={USER},github:1={USER}"}, "repeats"),
        ({"mcp_oauth_scopes": ""}, "at least one scope"),
        ({"mcp_oauth_scopes": "projects:read,preferences:write"}, "outside the public MCP scopes"),
        ({"mcp_oauth_scopes": "preferences:read"}, "outside the public MCP scopes"),
        ({"mcp_oauth_allowed_redirect_uris": ""}, "at least one URI"),
        ({"mcp_oauth_allowed_redirect_uris": "http://evil.example/cb"}, "must be HTTPS"),
        ({"mcp_oauth_allowed_redirect_uris": "*"}, "one concrete host"),
        ({"mcp_oauth_allowed_redirect_uris": "https://*"}, "one concrete host"),
        ({"mcp_oauth_allowed_redirect_uris": "https://*.example.com/cb"}, "one concrete host"),
        ({"mcp_oauth_allowed_redirect_uris": "https://claude.ai/*,https://*/x"}, "concrete host"),
    ],
)
def test_github_oauth_fails_closed_on_every_incomplete_or_unsafe_setting(
    override: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValidationError, match=message) as error:
        oauth_settings(**override)
    rendered = str(error.value)
    # A startup error names the setting, never a configured value.
    assert SECRET_SENTINEL not in rendered
    assert KEY_SENTINEL not in rendered


def test_incomplete_oauth_settings_are_ignored_while_the_mode_is_pat() -> None:
    assert Settings(mcp_oauth_scopes="tasks:read").mcp_auth_mode == "pat"


def test_a_retired_chat_scope_in_the_oauth_policy_is_refused_never_granted() -> None:
    assert parse_mcp_oauth_scopes(" tasks:read ") == {"tasks:read"}
    for value in ("chat:write", "chat:write, tasks:read ,chat:read", "chat:write,made:up"):
        with pytest.raises(ValueError, match="outside the public MCP scopes"):
            parse_mcp_oauth_scopes(value)


def test_the_identity_parser_keys_on_the_numeric_id_only() -> None:
    parsed = parse_mcp_oauth_identities(f" github:0042 = {USER} , github:7={USER.upper()} ")
    assert set(parsed) == {"github:42", "github:7"}
    assert parse_mcp_oauth_identities("") == {}


def test_the_scope_policy_can_never_exceed_the_public_mcp_ceiling() -> None:
    assert parse_mcp_oauth_scopes("tasks:read, tasks:write") == {"tasks:read", "tasks:write"}
    for outside in ("preferences:read", "preferences:write", "admin"):
        with pytest.raises(ValueError, match="outside the public MCP scopes"):
            parse_mcp_oauth_scopes(f"tasks:read,{outside}")


def test_redirect_uri_patterns_allow_https_and_loopback_wildcards_only() -> None:
    assert parse_mcp_oauth_redirect_uris("https://claude.ai/api/mcp/auth_callback") == (
        "https://claude.ai/api/mcp/auth_callback",
    )
    assert parse_mcp_oauth_redirect_uris("http://localhost:*/callback")
    with pytest.raises(ValueError, match="must be HTTPS"):
        parse_mcp_oauth_redirect_uris("javascript:alert(1)")


def test_upstream_cache_is_capped_at_one_hour() -> None:
    assert (
        oauth_settings(mcp_oauth_upstream_cache_seconds=3600).mcp_oauth_upstream_cache_seconds
        == 3600
    )
    assert oauth_settings(mcp_oauth_upstream_cache_seconds=0).mcp_oauth_upstream_cache_seconds == 0
    with pytest.raises(ValidationError):
        oauth_settings(mcp_oauth_upstream_cache_seconds=3601)
    with pytest.raises(ValidationError):
        oauth_settings(mcp_oauth_upstream_cache_seconds=604_800)


def test_the_oauth_session_lasts_thirty_days_by_default_and_is_capped() -> None:
    assert oauth_settings().mcp_oauth_session_days == 30
    assert oauth_settings(mcp_oauth_session_days=90).mcp_oauth_session_days == 90
    for refused in (0, -1, 91, 365):
        with pytest.raises(ValidationError):
            oauth_settings(mcp_oauth_session_days=refused)
