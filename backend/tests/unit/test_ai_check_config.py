"""Database-free unit tests for the check model's settings, the refusal of its key outside the AI
worker and the factory that turns the settings into a model with its price and cost source."""

import os
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from sidekick.shared.config import Settings, refuse_ai_key_outside_ai_worker
from sidekick.shared.errors import RefusedError
from sidekick.work.domain.ai_runs import CostSource
from sidekick.work.infrastructure.anthropic_model import AnthropicModel
from sidekick.work.infrastructure.check_model import FREE, build_check_model
from sidekick.work.infrastructure.openai_compat_model import OpenAiCompatModel

KEY = "check-key-" + "k" * 32
GOOD_SECRET = "g" * 32
PRODUCTION: dict[str, Any] = {
    "environment": "production",
    "database_url": "postgresql+psycopg://u:p@db.invalid/sidekick",
    "cursor_signing_secret": GOOD_SECRET,
    "token_pepper": GOOD_SECRET,
}
PRICES = {
    "ai_check_price_input_usd_per_mtok": 1.0,
    "ai_check_price_output_usd_per_mtok": 2.0,
    "ai_check_price_cache_write_usd_per_mtok": 3.0,
    "ai_check_price_cache_read_usd_per_mtok": 0.5,
}
LOCAL = {
    "ai_check_provider": "openai_compat",
    "ai_check_model": "llama3.3",
    "ai_check_base_url": "http://ollama.internal:11434",
}
HOSTED = {
    "ai_check_provider": "openai_compat",
    "ai_check_model": "vendor/model",
    "ai_check_base_url": "https://openrouter.ai",
}


@pytest.fixture(autouse=True)
def no_ai_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Only the variables a test sets itself, and no `.env` file to find."""

    for name in [name for name in os.environ if name.startswith("SIDEKICK_AI_")]:
        monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)


def settings(**fields: Any) -> Settings:
    return Settings(_env_file=None, **fields)


# Settings


def test_the_check_is_off_and_holds_no_key_by_default() -> None:
    config = settings()

    assert config.ai_check_provider == "off"
    assert config.ai_check_api_key is None
    assert config.ai_check_base_url == ""
    assert build_check_model(settings()) is None


def test_a_local_server_is_accepted_without_a_key() -> None:
    config = settings(**LOCAL)

    assert config.ai_check_base_url == "http://ollama.internal:11434"
    assert config.ai_check_api_key is None


def test_the_hosted_origin_is_accepted_and_a_trailing_slash_dropped() -> None:
    config = settings(**{**HOSTED, "ai_check_base_url": "https://openrouter.ai/"})

    assert config.ai_check_base_url == "https://openrouter.ai"


@pytest.mark.parametrize(
    "base_url",
    [
        "https://api.example.com",
        "https://openrouter.ai/api/v1",
        "http://169.254.169.254",
        "http://127.0.0.1:11434",
        "http://user:pass@ollama.internal",
    ],
)
def test_a_destination_that_is_neither_hosted_nor_private_never_starts(base_url: str) -> None:
    with pytest.raises(ValidationError, match="base URL"):
        settings(**{**LOCAL, "ai_check_base_url": base_url})


def test_loopback_is_allowed_in_development_only_with_its_flag() -> None:
    config = settings(
        **{**LOCAL, "ai_check_base_url": "http://127.0.0.1:11434", "ai_check_allow_loopback": True}
    )

    assert config.ai_check_base_url == "http://127.0.0.1:11434"


def test_loopback_is_refused_in_production() -> None:
    with pytest.raises(ValidationError, match="not valid in production"):
        settings(**PRODUCTION, ai_check_allow_loopback=True)


def test_a_check_that_is_on_needs_its_model() -> None:
    with pytest.raises(ValidationError, match="AI_CHECK_MODEL"):
        settings(ai_check_provider="anthropic")


def test_openai_compat_needs_its_base_url() -> None:
    with pytest.raises(ValidationError, match="AI_CHECK_BASE_URL"):
        settings(ai_check_provider="openai_compat", ai_check_model="m")


@pytest.mark.parametrize("given", list(PRICES))
def test_a_price_given_alone_is_refused(given: str) -> None:
    with pytest.raises(ValidationError, match="all four together"):
        settings(**{given: 1.0})


def test_the_key_is_never_shown_in_the_settings_text() -> None:
    config = settings(**LOCAL, ai_check_api_key=SecretStr(KEY))

    assert KEY not in repr(config)
    assert KEY not in str(config)


def test_the_key_is_read_from_its_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    key_file = tmp_path / "ai_check_api_key"
    key_file.write_text(KEY + "\n", encoding="utf-8")
    monkeypatch.setenv("SIDEKICK_AI_CHECK_API_KEY_FILE", str(key_file))

    loaded = Settings(_env_file=None).ai_check_api_key

    assert loaded is not None and loaded.get_secret_value() == KEY


# The key stays in the AI worker


def test_production_refuses_the_check_key_outside_the_ai_worker() -> None:
    with_key = settings(**PRODUCTION, ai_check_api_key=KEY)

    with pytest.raises(RefusedError, match="AI_CHECK_API_KEY") as caught:
        refuse_ai_key_outside_ai_worker(with_key)

    assert KEY not in str(caught.value)


def test_production_without_a_check_key_is_accepted() -> None:
    refuse_ai_key_outside_ai_worker(settings(**PRODUCTION))


def test_development_may_hold_the_check_key() -> None:
    refuse_ai_key_outside_ai_worker(settings(ai_check_api_key=KEY))


# The factory


def test_a_local_server_without_a_price_is_free_and_counted_as_none() -> None:
    model = build_check_model(settings(**LOCAL))

    assert model is not None
    assert isinstance(model.port, OpenAiCompatModel)
    assert (model.provider, model.name) == ("openai_compat", "llama3.3")
    assert model.cost_source is CostSource.NONE
    assert model.price == FREE


def test_a_priced_private_server_is_counted_by_its_price() -> None:
    model = build_check_model(settings(**LOCAL, **PRICES))

    assert model is not None
    assert model.cost_source is CostSource.PRICE_TABLE
    assert model.price.input == 1
    assert model.price.cache_read == pytest.approx(0.5)


def test_the_hosted_route_needs_its_key_and_its_price() -> None:
    with pytest.raises(RefusedError, match="gives no key"):
        build_check_model(settings(**HOSTED, **PRICES))
    with pytest.raises(RefusedError, match="no built-in price") as caught:
        build_check_model(settings(**HOSTED, ai_check_api_key=KEY))

    assert KEY not in str(caught.value)


def test_the_hosted_route_with_key_and_price_is_booked_by_the_price() -> None:
    model = build_check_model(settings(**HOSTED, **PRICES, ai_check_api_key=KEY))

    assert model is not None
    assert isinstance(model.port, OpenAiCompatModel)
    assert model.cost_source is CostSource.PRICE_TABLE


def test_the_anthropic_check_uses_the_workers_anthropic_key_and_the_built_in_price() -> None:
    config = {"ai_check_provider": "anthropic", "ai_check_model": "claude-sonnet-5-5"}
    with pytest.raises(RefusedError, match="gives no key"):
        build_check_model(settings(**config))

    model = build_check_model(settings(**config, ai_anthropic_api_key="sk-ant-test"))

    assert model is not None
    assert isinstance(model.port, AnthropicModel)
    assert model.cost_source is CostSource.PRICE_TABLE
    assert model.price.input == 2


def test_an_unpriced_anthropic_model_is_refused() -> None:
    config = {"ai_check_provider": "anthropic", "ai_check_model": "claude-unknown-1"}

    with pytest.raises(RefusedError, match="no built-in price"):
        build_check_model(settings(**config, ai_anthropic_api_key="sk-ant-test"))
