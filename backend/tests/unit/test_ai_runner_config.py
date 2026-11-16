"""Database-free unit tests for running AI Steps on the server: its settings, the Anthropic key's
handling and whether the server can run a step at all."""

import os
from collections.abc import Iterable
from decimal import Decimal
from itertools import combinations
from pathlib import Path
from typing import Any, Literal

import pytest
from pydantic import SecretStr, ValidationError

from sidekick.shared.config import Settings, refuse_ai_key_outside_ai_worker
from sidekick.shared.config.ai_runner import AiRunnerSettings
from sidekick.shared.errors import ConflictError, RefusedError
from sidekick.work.application.ai_store import ServerRunnerConfig

PRICE_FIELDS = (
    "ai_price_input_usd_per_mtok",
    "ai_price_output_usd_per_mtok",
    "ai_price_cache_write_usd_per_mtok",
    "ai_price_cache_read_usd_per_mtok",
)
KEY = "test-anthropic-key-" + "k" * 32
GOOD_SECRET = "g" * 32
PRODUCTION: dict[str, Any] = {
    "environment": "production",
    "database_url": "postgresql+psycopg://u:p@db.invalid/sidekick",
    "cursor_signing_secret": GOOD_SECRET,
    "token_pepper": GOOD_SECRET,
}


def given_prices(names: Iterable[str]) -> dict[str, Any]:
    """Each named price set to 1.0, as keyword arguments."""

    return dict.fromkeys(names, 1.0)


@pytest.fixture(autouse=True)
def no_ai_runner_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Only the variables a test sets itself: the process environment must not leak into them.
    The test runs in an empty directory, so the relative `.env` path finds no file."""

    for name in [name for name in os.environ if name.startswith("SIDEKICK_AI_")]:
        monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)


# Defaults


def test_the_server_runner_is_off_and_holds_no_key_by_default() -> None:
    settings = AiRunnerSettings()

    assert settings.ai_runner_enabled is False
    assert settings.ai_model == "claude-opus-5-5"
    assert settings.ai_anthropic_api_key is None
    assert settings.ai_max_output_tokens == 16_000
    assert settings.ai_server_starts_per_day == 50


def test_all_four_prices_given_together_are_accepted() -> None:
    settings = AiRunnerSettings(**given_prices(PRICE_FIELDS))

    assert settings.ai_price_input_usd_per_mtok == 1.0
    assert settings.ai_price_cache_read_usd_per_mtok == 1.0


def test_no_price_given_is_accepted() -> None:
    settings = AiRunnerSettings()

    assert settings.ai_price_input_usd_per_mtok is None


@pytest.mark.parametrize(
    "names",
    [names for size in (1, 2, 3) for names in combinations(PRICE_FIELDS, size)],
)
def test_a_part_of_the_prices_is_refused(names: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError, match="all four together"):
        AiRunnerSettings(**given_prices(names))


def test_a_call_may_not_outlast_the_time_the_worker_has_to_finish_when_stopped() -> None:
    assert AiRunnerSettings(ai_request_timeout_seconds=300).ai_request_timeout_seconds == 300
    with pytest.raises(ValidationError):
        AiRunnerSettings(ai_request_timeout_seconds=301)


# The key


def test_the_key_never_shows_in_repr_or_str() -> None:
    settings = AiRunnerSettings(ai_anthropic_api_key=SecretStr(KEY))

    assert settings.ai_anthropic_api_key is not None
    assert settings.ai_anthropic_api_key.get_secret_value() == KEY
    assert KEY not in repr(settings)
    assert KEY not in str(settings)


def test_the_key_can_be_read_from_a_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    key_file = tmp_path / "anthropic-key"
    key_file.write_text(KEY + "\n", encoding="utf-8")
    monkeypatch.setenv("SIDEKICK_AI_ANTHROPIC_API_KEY_FILE", str(key_file))

    settings = Settings()

    assert settings.ai_anthropic_api_key is not None
    assert settings.ai_anthropic_api_key.get_secret_value() == KEY


def test_production_refuses_the_key_outside_the_ai_worker() -> None:
    settings = Settings(ai_anthropic_api_key=SecretStr(KEY), **PRODUCTION)

    with pytest.raises(RefusedError):
        refuse_ai_key_outside_ai_worker(settings)


@pytest.mark.parametrize("environment", ["development", "test"])
def test_the_key_is_allowed_outside_production(
    environment: Literal["development", "test"],
) -> None:
    settings = Settings(
        environment=environment,
        ai_anthropic_api_key=SecretStr(KEY),
    )

    refuse_ai_key_outside_ai_worker(settings)


def test_production_without_the_key_starts() -> None:
    settings = Settings(**PRODUCTION)

    refuse_ai_key_outside_ai_worker(settings)


# ServerRunnerConfig


def test_the_runner_is_not_available_while_it_is_off() -> None:
    config = ServerRunnerConfig.from_settings(Settings())

    assert config.enabled is False
    assert config.available is False


def test_the_runner_is_available_with_a_known_model() -> None:
    config = ServerRunnerConfig.from_settings(Settings(ai_runner_enabled=True))

    assert config.available is True
    assert config.price is not None
    assert config.price.input == Decimal("4")
    assert config.require_price() == config.price


def test_asking_for_a_price_while_the_runner_is_off_is_a_conflict() -> None:
    config = ServerRunnerConfig.from_settings(Settings())

    with pytest.raises(ConflictError) as caught:
        config.require_price()

    assert caught.value.reason == "ai_runner_off"


def test_an_unknown_model_without_prices_cannot_run() -> None:
    config = ServerRunnerConfig.from_settings(
        Settings(ai_runner_enabled=True, ai_model="claude-unlisted-1")
    )

    assert config.price is None
    assert config.available is False
    with pytest.raises(ConflictError) as caught:
        config.require_price()
    assert caught.value.reason == "ai_runner_off"


def test_an_unknown_model_with_all_four_prices_can_run() -> None:
    config = ServerRunnerConfig.from_settings(
        Settings(
            ai_runner_enabled=True,
            ai_model="claude-unlisted-1",
            ai_price_input_usd_per_mtok=1.0,
            ai_price_output_usd_per_mtok=2.0,
            ai_price_cache_write_usd_per_mtok=3.0,
            ai_price_cache_read_usd_per_mtok=0.5,
        )
    )

    assert config.available is True
    assert config.price is not None
    assert config.price.cache_read == Decimal("0.5")
