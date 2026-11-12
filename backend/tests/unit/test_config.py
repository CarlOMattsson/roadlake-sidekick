"""Configuration security boundaries."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from sidekick.shared.auth import ALL_SCOPES, MCP_SCOPES
from sidekick.shared.config import Settings


def test_production_rejects_development_secrets() -> None:
    with pytest.raises(ValidationError, match="cursor signing secret"):
        Settings(environment="production")


_PRODUCTION_SECRETS = {
    "environment": "production",
    "database_url": "postgresql+psycopg://u:p@db.invalid/sidekick",
}
_GOOD = "g" * 32


@pytest.mark.parametrize("field", ["cursor_signing_secret", "token_pepper"])
@pytest.mark.parametrize(
    "value",
    [
        " " * 32,
        "\t\n ",
        "",
        "  development-" + "d" * 32,
        "replace-with-" + "r" * 32 + "  ",
        "\n replace-with-" + "r" * 32,
    ],
)
def test_production_refuses_blank_whitespace_and_padded_placeholders(
    field: str, value: str
) -> None:
    other = "token_pepper" if field == "cursor_signing_secret" else "cursor_signing_secret"
    settings: dict[str, object] = {**_PRODUCTION_SECRETS, field: value, other: _GOOD}
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None, **settings)  # type: ignore[arg-type]
    message = str(caught.value)
    # Too short a value is refused by the field's own length rule; the rest by the placeholder rule.
    expected = "must be configured" if len(value) >= 32 else "at least 32 characters"
    assert expected in message
    # The message names the setting, never the value (the padded placeholder's body is distinctive).
    assert value.strip() not in message or not value.strip()


def test_production_accepts_a_real_secret_even_with_padding() -> None:
    settings = Settings(
        _env_file=None,
        **_PRODUCTION_SECRETS,  # type: ignore[arg-type]
        cursor_signing_secret=_GOOD,
        token_pepper=" " + _GOOD,
    )
    assert settings.environment == "production"


def test_a_blank_cursor_secret_outside_production_falls_back_to_the_process_key() -> None:
    settings = Settings(_env_file=None, cursor_signing_secret=" " * 32)
    assert settings.cursor_signing_key.strip()
    assert settings.cursor_signing_key != " " * 32


def test_the_chat_scopes_are_retired() -> None:
    assert not {"chat:read", "chat:write"} & (ALL_SCOPES | set(MCP_SCOPES))


def test_memory_hindsight_rejects_non_private_destination() -> None:
    with pytest.raises(ValidationError, match="approved private host"):
        Settings(_env_file=None, memory_hindsight_base_url="https://memory.example.com")


def test_the_retired_desktop_mode_is_rejected() -> None:
    with pytest.raises(ValidationError, match="environment"):
        Settings(_env_file=None, environment="desktop")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "name",
    [
        "SIDEKICK_CHAT_MODEL_PROVIDER",
        "SIDEKICK_JOURNAL_AI_ENABLED",
        "SIDEKICK_DESKTOP_STATIC_DIR",
        "SIDEKICK_VOICE_MCP_OWNER_ID",
        "SIDEKICK_MEMORY_PROVDER",
    ],
)
def test_the_name_of_a_removed_or_misspelt_setting_stops_settings_loading(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str
) -> None:
    """No list of removed names is tolerated: any undeclared SIDEKICK_ name stops the start."""

    monkeypatch.setenv(name, "x")
    with pytest.raises(ValidationError, match="undeclared SIDEKICK_ setting"):
        Settings(_env_file=None)
    monkeypatch.delenv(name)

    env_file = tmp_path / ".env"
    env_file.write_text(f"{name}=x\n")
    with pytest.raises(ValidationError):
        Settings(_env_file=env_file)


_MEMORY_HINDSIGHT: dict[str, object] = {
    "memory_enabled": True,
    "memory_provider": "hindsight",
    "memory_hindsight_base_url": "http://hindsight:8888",
    "memory_hindsight_api_token": "memory-test-secret",
    "memory_id_derivation_key": "memory-derivation-secret",
}


def test_memory_is_off_and_fake_by_default() -> None:
    settings = Settings(_env_file=None)

    assert settings.memory_enabled is False
    assert settings.memory_provider == "fake"
    assert settings.memory_ingest_enabled is True
    assert settings.memory_hindsight_base_url == ""
    assert settings.memory_hindsight_api_token is None
    assert settings.memory_id_derivation_key is None
    assert settings.memory_allow_loopback is False
    assert settings.memory_quiet_seconds == 600
    assert settings.memory_daily_retain_cap == 40
    assert settings.memory_backfill_daily_cap == 150
    assert settings.memory_daily_char_cap == 400_000


def test_memory_fake_provider_needs_no_credentials() -> None:
    settings = Settings(_env_file=None, memory_enabled=True)

    assert settings.memory_enabled is True
    assert settings.memory_provider == "fake"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"memory_quiet_seconds": 599}, "greater than or equal to 600"),
        ({"memory_daily_retain_cap": -1}, "greater than or equal to 0"),
        ({"memory_backfill_daily_cap": 5001}, "less than or equal to 5000"),
        ({"memory_daily_char_cap": 10_000_001}, "less than or equal to 10000000"),
        ({"memory_daily_char_cap": -1}, "greater than or equal to 0"),
    ],
)
def test_memory_bounds_are_enforced(overrides: dict[str, int], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Settings(_env_file=None, **overrides)


def test_memory_hindsight_accepts_the_compose_service_destination() -> None:
    settings = Settings(_env_file=None, **_MEMORY_HINDSIGHT)

    assert settings.memory_hindsight_base_url == "http://hindsight:8888"
    assert settings.memory_ingest_enabled is True


def test_memory_kill_switch_stops_ingest_with_hindsight_still_configured() -> None:
    settings = Settings(_env_file=None, **_MEMORY_HINDSIGHT, memory_ingest_enabled=False)

    assert settings.memory_ingest_enabled is False
    assert settings.memory_provider == "hindsight"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"memory_hindsight_base_url": ""}, "MEMORY_HINDSIGHT_BASE_URL is required"),
        ({"memory_hindsight_api_token": None}, "MEMORY_HINDSIGHT_API_TOKEN is required"),
        ({"memory_hindsight_api_token": "   "}, "MEMORY_HINDSIGHT_API_TOKEN is required"),
        ({"memory_id_derivation_key": None}, "MEMORY_ID_DERIVATION_KEY is required"),
        ({"memory_hindsight_base_url": "https://memory.example.com"}, "approved private host"),
        ({"memory_hindsight_base_url": "http://8.8.8.8:8888"}, "approved private host"),
        ({"memory_hindsight_base_url": "http://127.0.0.1:18890"}, "approved private host"),
        ({"memory_hindsight_base_url": "http://169.254.169.254"}, "approved private host"),
        ({"memory_hindsight_base_url": "http://0.0.0.0:8888"}, "approved private host"),
        ({"memory_hindsight_base_url": "http://hindsight:8888/extra"}, "credentials or a path"),
    ],
)
def test_memory_refuses_incoherent_or_non_private_destinations(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        Settings(_env_file=None, **{**_MEMORY_HINDSIGHT, **overrides})


@pytest.mark.parametrize("environment", ["development", "test"])
def test_memory_loopback_needs_the_explicit_flag_outside_production(environment: str) -> None:
    settings = Settings(
        _env_file=None,
        environment=environment,
        **{
            **_MEMORY_HINDSIGHT,
            "memory_hindsight_base_url": "http://127.0.0.1:18890",
            "memory_allow_loopback": True,
        },
    )

    assert settings.memory_hindsight_base_url == "http://127.0.0.1:18890"
    assert settings.memory_allow_loopback is True


def test_memory_loopback_is_refused_in_production_even_with_the_flag() -> None:
    production: dict[str, object] = {
        "environment": "production",
        "cursor_signing_secret": "x" * 32,
        "token_pepper": "y" * 32,
    }
    with pytest.raises(ValidationError, match="not valid in production"):
        Settings(_env_file=None, **production, memory_allow_loopback=True)
    with pytest.raises(ValidationError, match="approved private host"):
        Settings(
            _env_file=None,
            **production,
            **{**_MEMORY_HINDSIGHT, "memory_hindsight_base_url": "http://127.0.0.1:18890"},
        )


def test_production_refuses_the_fake_memory_provider_when_memory_is_enabled() -> None:
    production: dict[str, object] = {
        "environment": "production",
        "cursor_signing_secret": "x" * 32,
        "token_pepper": "y" * 32,
    }
    with pytest.raises(ValidationError, match="fake is not valid in production"):
        Settings(_env_file=None, **production, memory_enabled=True)


def test_production_allows_the_fake_memory_provider_only_while_memory_is_off() -> None:
    production: dict[str, object] = {
        "environment": "production",
        "cursor_signing_secret": "x" * 32,
        "token_pepper": "y" * 32,
    }
    settings = Settings(_env_file=None, **production)

    assert settings.memory_enabled is False
    assert settings.memory_provider == "fake"


def test_production_accepts_memory_on_hindsight() -> None:
    production: dict[str, object] = {
        "environment": "production",
        "cursor_signing_secret": "x" * 32,
        "token_pepper": "y" * 32,
    }
    settings = Settings(_env_file=None, **production, **_MEMORY_HINDSIGHT)

    assert settings.memory_provider == "hindsight"


def test_repr_and_str_of_settings_hide_the_secret_values() -> None:
    """A settings object that lands in a log line, traceback or debug print must not leak."""

    database_url = "postgresql+psycopg://sidekick_app:db-password-canary@db.invalid/sidekick"
    cursor_secret = "cursor-secret-canary-" + "c" * 16
    pepper = "token-pepper-canary-" + "p" * 16
    settings = Settings(
        _env_file=None,
        environment="production",
        database_url=database_url,
        cursor_signing_secret=cursor_secret,
        token_pepper=pepper,
    )

    for rendered in (repr(settings), str(settings)):
        for secret in (database_url, "db-password-canary", cursor_secret, pepper):
            assert secret not in rendered
    # Behaviour is unchanged: the values are still plain strings for callers.
    assert settings.database_url == database_url
    assert settings.cursor_signing_secret == cursor_secret
    assert settings.token_pepper == pepper
