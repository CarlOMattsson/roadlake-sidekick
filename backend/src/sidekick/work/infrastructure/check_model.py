"""The model that checks proposals, built from the settings: the one place that knows which
adapter a provider name means and what its calls cost.

Only the AI worker calls this, because only it may hold a key. Nothing here logs.
"""

from dataclasses import dataclass
from decimal import Decimal

from sidekick.shared.config import Settings
from sidekick.shared.errors.core import RefusedError
from sidekick.shared.private_endpoint import is_hosted_model_url
from sidekick.work.domain.ai_cost import ModelPrice, price_for
from sidekick.work.domain.ai_model_port import ModelPort
from sidekick.work.domain.ai_runs import CostSource
from sidekick.work.infrastructure.anthropic_model import AnthropicModel
from sidekick.work.infrastructure.openai_compat_model import OpenAiCompatModel

FREE = ModelPrice(Decimal(0), Decimal(0), Decimal(0), Decimal(0))


@dataclass(frozen=True, slots=True)
class CheckModel:
    """A model ready to call, with the price and the cost source its calls are booked under."""

    provider: str
    name: str
    port: ModelPort
    price: ModelPrice
    cost_source: CostSource


def build_check_model(settings: Settings) -> CheckModel | None:
    """The configured check model, None while the check is off, or the refusal to start."""

    provider = settings.ai_check_provider
    if provider == "off":
        return None
    name = settings.ai_check_model
    timeout = settings.ai_request_timeout_seconds
    given = _given_price(settings, name)
    if provider == "anthropic":
        anthropic_key = settings.ai_anthropic_api_key
        if anthropic_key is None:
            raise RefusedError(
                "the AI check uses Anthropic but SIDEKICK_AI_ANTHROPIC_API_KEY_FILE gives no key"
            )
        return CheckModel(
            provider,
            name,
            AnthropicModel(anthropic_key.get_secret_value(), name, timeout),
            _require_price(given),
            CostSource.PRICE_TABLE,
        )
    hosted = is_hosted_model_url(settings.ai_check_base_url)
    key = settings.ai_check_api_key
    if hosted and key is None:
        raise RefusedError(
            "the AI check uses OpenRouter but SIDEKICK_AI_CHECK_API_KEY_FILE gives no key"
        )
    port = OpenAiCompatModel(
        key.get_secret_value() if key is not None else None,
        name,
        settings.ai_check_base_url,
        timeout,
        max_response_bytes=settings.ai_check_max_response_bytes,
        allow_loopback=settings.ai_check_allow_loopback,
    )
    if not hosted and given is None:
        # A private server with no price is the owner's own hardware: it costs nothing to count.
        return CheckModel(provider, name, port, FREE, CostSource.NONE)
    return CheckModel(provider, name, port, _require_price(given), CostSource.PRICE_TABLE)


def _given_price(settings: Settings, model: str) -> ModelPrice | None:
    return price_for(
        model,
        input=settings.ai_check_price_input_usd_per_mtok,
        output=settings.ai_check_price_output_usd_per_mtok,
        cache_write=settings.ai_check_price_cache_write_usd_per_mtok,
        cache_read=settings.ai_check_price_cache_read_usd_per_mtok,
    )


def _require_price(price: ModelPrice | None) -> ModelPrice:
    if price is None:
        raise RefusedError(
            "the check model has no built-in price; "
            "set all four SIDEKICK_AI_CHECK_PRICE_* variables"
        )
    return price
