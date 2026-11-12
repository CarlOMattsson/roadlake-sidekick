"""`SIDEKICK_<NAME>_FILE`: every secret setting can be read from a file, not the environment."""

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError
from pydantic_settings import SettingsError

from sidekick.shared.config import Settings
from sidekick.shared.config.secret_files import (
    MAX_SECRET_FILE_BYTES,
    is_secret_field,
    secret_file_variable_names,
)

SECRET_FIELDS = sorted(
    name for name, field in Settings.model_fields.items() if is_secret_field(field)
)
SECRET = "file-secret-" + "s" * 32


def _write(path: Path, content: str | bytes) -> str:
    path.write_bytes(content.encode() if isinstance(content, str) else content)
    return str(path)


def _revealed(value: object) -> object:
    return value.get_secret_value() if isinstance(value, SecretStr) else value


def test_the_secret_settings_are_exactly_the_ones_that_get_a_file_variable() -> None:
    assert SECRET_FIELDS == [
        "backup_encryption_key",
        "cursor_signing_secret",
        "database_url",
        "mcp_oauth_github_client_secret",
        "mcp_oauth_signing_key",
        "memory_hindsight_api_token",
        "memory_id_derivation_key",
        "push_auth_token",
        "token_pepper",
    ]
    assert secret_file_variable_names(Settings) == {
        f"SIDEKICK_{name.upper()}_FILE" for name in SECRET_FIELDS
    }


@pytest.mark.parametrize("field", SECRET_FIELDS)
def test_every_secret_setting_reads_its_value_from_the_named_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, field: str
) -> None:
    value = "postgresql+psycopg://u:p@db.invalid/sidekick" if field == "database_url" else SECRET
    monkeypatch.delenv(f"SIDEKICK_{field.upper()}", raising=False)
    if field == "push_auth_token":
        monkeypatch.setenv("SIDEKICK_PUSH_AUTH_HOST", "ntfy.example.com")
        monkeypatch.setenv("SIDEKICK_PUSH_ALLOWED_HOSTS", "ntfy.example.com")
    monkeypatch.setenv(f"SIDEKICK_{field.upper()}_FILE", _write(tmp_path / field, value + "\n"))

    assert _revealed(getattr(Settings(_env_file=None), field)) == value


@pytest.mark.parametrize("content", ["value", "value\n", "value\r\n", "value\n\n"])
def test_only_the_trailing_line_break_is_dropped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, content: str
) -> None:
    monkeypatch.setenv("SIDEKICK_MEMORY_ID_DERIVATION_KEY_FILE", _write(tmp_path / "k", content))

    key = Settings(_env_file=None).memory_id_derivation_key
    assert key is not None and key.get_secret_value() == "value"


def test_inner_and_leading_whitespace_is_kept(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SIDEKICK_MEMORY_ID_DERIVATION_KEY_FILE", _write(tmp_path / "k", " a b\n"))

    key = Settings(_env_file=None).memory_id_derivation_key
    assert key is not None and key.get_secret_value() == " a b"


def test_the_plain_variable_still_works_without_a_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIDEKICK_TOKEN_PEPPER", SECRET)

    assert Settings(_env_file=None).token_pepper == SECRET


@pytest.mark.parametrize("field", SECRET_FIELDS)
def test_a_value_and_a_file_for_the_same_setting_is_a_configuration_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, field: str
) -> None:
    name = f"SIDEKICK_{field.upper()}"
    monkeypatch.setenv(name, SECRET)
    monkeypatch.setenv(f"{name}_FILE", _write(tmp_path / "f", SECRET))

    with pytest.raises(SettingsError) as caught:
        Settings(_env_file=None)
    message = str(caught.value)
    assert f"{name} and {name}_FILE are both set" in message
    assert SECRET not in message


def test_an_empty_variable_does_not_conflict_with_a_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Compose passes an unset-but-listed name through as an empty string."""

    monkeypatch.setenv("SIDEKICK_PUSH_AUTH_TOKEN", "")
    monkeypatch.setenv("SIDEKICK_PUSH_AUTH_HOST", "ntfy.example.com")
    monkeypatch.setenv("SIDEKICK_PUSH_ALLOWED_HOSTS", "ntfy.example.com")
    monkeypatch.setenv("SIDEKICK_PUSH_AUTH_TOKEN_FILE", _write(tmp_path / "t", "tk_abc\n"))

    token = Settings(_env_file=None).push_auth_token
    assert token is not None and token.get_secret_value() == "tk_abc"


def test_an_empty_file_variable_counts_as_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIDEKICK_TOKEN_PEPPER_FILE", "")
    monkeypatch.setenv("SIDEKICK_TOKEN_PEPPER", SECRET)

    assert Settings(_env_file=None).token_pepper == SECRET


def test_a_missing_file_is_a_clear_error_that_names_the_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SIDEKICK_TOKEN_PEPPER_FILE", str(tmp_path / "absent"))

    with pytest.raises(SettingsError, match="SIDEKICK_TOKEN_PEPPER_FILE names a file that cannot"):
        Settings(_env_file=None)


def test_a_directory_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A bind mount of a missing host file becomes a directory."""

    monkeypatch.setenv("SIDEKICK_TOKEN_PEPPER_FILE", str(tmp_path))

    with pytest.raises(SettingsError, match="cannot be read"):
        Settings(_env_file=None)


def test_a_file_that_is_not_text_or_is_too_large_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SIDEKICK_TOKEN_PEPPER_FILE", _write(tmp_path / "bin", b"\xff\xfe" * 20))
    with pytest.raises(SettingsError, match="not UTF-8 text"):
        Settings(_env_file=None)

    monkeypatch.setenv(
        "SIDEKICK_TOKEN_PEPPER_FILE", _write(tmp_path / "big", b"x" * (MAX_SECRET_FILE_BYTES + 1))
    )
    with pytest.raises(SettingsError, match="over 65536 bytes"):
        Settings(_env_file=None)


def test_a_file_value_is_validated_like_a_variable_and_never_quoted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SIDEKICK_TOKEN_PEPPER_FILE", _write(tmp_path / "short", "too-short\n"))

    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None)
    assert "too-short" not in str(caught.value)


def test_production_takes_the_required_secrets_from_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for name in ("DATABASE_URL", "CURSOR_SIGNING_SECRET", "TOKEN_PEPPER"):
        monkeypatch.delenv(f"SIDEKICK_{name}", raising=False)
    monkeypatch.setenv("SIDEKICK_ENVIRONMENT", "production")
    monkeypatch.setenv(
        "SIDEKICK_DATABASE_URL_FILE",
        _write(tmp_path / "db", "postgresql+psycopg://u:p@db.invalid/sidekick\n"),
    )
    monkeypatch.setenv("SIDEKICK_CURSOR_SIGNING_SECRET_FILE", _write(tmp_path / "c", SECRET))
    monkeypatch.setenv("SIDEKICK_TOKEN_PEPPER_FILE", _write(tmp_path / "p", SECRET + "p"))

    settings = Settings(_env_file=None)

    assert settings.environment == "production"
    assert settings.database_url.endswith("@db.invalid/sidekick")


def test_a_placeholder_in_a_secret_file_is_still_refused_in_production(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SIDEKICK_ENVIRONMENT", "production")
    monkeypatch.setenv("SIDEKICK_DATABASE_URL", "postgresql+psycopg://u:p@db.invalid/sidekick")
    monkeypatch.setenv("SIDEKICK_TOKEN_PEPPER", SECRET)
    monkeypatch.setenv(
        "SIDEKICK_CURSOR_SIGNING_SECRET_FILE", _write(tmp_path / "c", "replace-with-" + "x" * 32)
    )

    with pytest.raises(ValidationError, match="cursor signing secret must be configured"):
        Settings(_env_file=None)


def test_a_file_variable_of_a_setting_that_is_not_secret_is_still_undeclared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIDEKICK_OWNER_TIMEZONE_FILE", "/run/secrets/x")

    with pytest.raises(ValidationError, match="SIDEKICK_OWNER_TIMEZONE_FILE"):
        Settings(_env_file=None)


def test_the_file_value_outranks_the_dotenv_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("SIDEKICK_MEMORY_ID_DERIVATION_KEY=from-dotenv\n")
    monkeypatch.setenv(
        "SIDEKICK_MEMORY_ID_DERIVATION_KEY_FILE", _write(tmp_path / "k", "from-file")
    )

    key = Settings(_env_file=env_file).memory_id_derivation_key
    assert key is not None and key.get_secret_value() == "from-file"


@pytest.mark.parametrize("name", ["sidekick_token_pepper", "Sidekick_Token_Pepper"])
def test_the_conflict_check_ignores_the_case_of_the_plain_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str
) -> None:
    monkeypatch.delenv("SIDEKICK_TOKEN_PEPPER", raising=False)
    monkeypatch.setenv(name, SECRET)
    monkeypatch.setenv("SIDEKICK_TOKEN_PEPPER_FILE", _write(tmp_path / "p", SECRET))

    with pytest.raises(SettingsError, match="are both set"):
        Settings(_env_file=None)


@pytest.mark.parametrize("content", ["", "\n", "  \r\n"])
def test_a_file_that_is_named_but_empty_stops_the_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, content: str
) -> None:
    """The push token is optional, but naming an empty file for it is a mistake, not "unset"."""

    monkeypatch.delenv("SIDEKICK_PUSH_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("SIDEKICK_PUSH_AUTH_TOKEN_FILE", _write(tmp_path / "t", content))

    with pytest.raises(SettingsError, match="SIDEKICK_PUSH_AUTH_TOKEN_FILE names an empty file"):
        Settings(_env_file=None)


def test_an_optional_secret_that_is_not_set_at_all_stays_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SIDEKICK_PUSH_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("SIDEKICK_PUSH_AUTH_TOKEN_FILE", raising=False)

    assert Settings(_env_file=None).push_auth_token is None
