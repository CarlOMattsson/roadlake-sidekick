"""What a model call costs, and the most it can cost before it is made.

Money is counted in millionths of a US dollar. A price in dollars per million tokens is then the
same number as the micro-dollars one token costs. Sums are rounded up to a whole micro-dollar, so
Sidekick's figure errs high: the provider's invoice is the record.
"""

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

from sidekick.work.domain.ai_model_port import CallUsage

OVERHEAD_TOKENS = 2_000
"""Added to a request's size when its input is priced before the call: framing and the schema."""


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """US dollars per million tokens."""

    input: Decimal
    output: Decimal
    cache_write: Decimal
    cache_read: Decimal


PRICES: dict[str, ModelPrice] = {
    # From https://platform.claude.com/docs/en/about-claude/pricing, read 2026-11-16.
    "claude-opus-5-5": ModelPrice(Decimal("4"), Decimal("20"), Decimal("5"), Decimal("0.20")),
    "claude-sonnet-5-5": ModelPrice(Decimal("2"), Decimal("10"), Decimal("2.50"), Decimal("0.10")),
}


def price_for(
    model: str,
    *,
    input: float | None = None,
    output: float | None = None,
    cache_write: float | None = None,
    cache_read: float | None = None,
) -> ModelPrice | None:
    """The configured price of `model`: the owner's own figures when all four are given, else the
    built-in table, else none (the model cannot be run, because its cost cannot be counted)."""

    given = (input, output, cache_write, cache_read)
    if all(price is not None for price in given):
        return ModelPrice(*(Decimal(str(price)) for price in given))
    return PRICES.get(model)


def _round_up(amount: Decimal) -> int:
    return int(amount.to_integral_value(rounding=ROUND_CEILING))


def call_cost(usage: CallUsage, price: ModelPrice) -> int:
    """What a finished call cost, from the token counts the provider reported."""

    return _round_up(
        usage.input_tokens * price.input
        + usage.output_tokens * price.output
        + usage.cache_write_tokens * price.cache_write
        + usage.cache_read_tokens * price.cache_read
    )


def call_reserve(request_bytes: int, max_tokens: int, price: ModelPrice) -> int:
    """The most a call can cost: every byte of the request is taken as an input token (a token is
    never shorter than a byte) and the answer fills `max_tokens`. A call without server tools and
    without prompt caching never costs more than this."""

    return _round_up(
        (request_bytes + OVERHEAD_TOKENS) * max(price.input, price.cache_write)
        + max_tokens * price.output
    )
