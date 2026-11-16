"""Database-free unit tests for what an AI Step model call costs and the most it can cost."""

from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from sidekick.work.domain.ai_cost import (
    OVERHEAD_TOKENS,
    PRICES,
    ModelPrice,
    call_cost,
    call_reserve,
    price_for,
)
from sidekick.work.domain.ai_model_port import CallUsage

OPUS = "claude-opus-5-5"
SONNET = "claude-sonnet-5-5"
OPUS_PRICE = PRICES[OPUS]
SONNET_PRICE = PRICES[SONNET]
HALF_DOLLAR_PER_MTOK = ModelPrice(Decimal("0.5"), Decimal("0.5"), Decimal("0.5"), Decimal("0.5"))


def test_the_built_in_table_holds_the_listed_prices() -> None:
    assert ModelPrice(Decimal("4"), Decimal("20"), Decimal("5"), Decimal("0.20")) == OPUS_PRICE
    assert ModelPrice(Decimal("2"), Decimal("10"), Decimal("2.50"), Decimal("0.10")) == SONNET_PRICE


def test_one_input_token_of_opus_costs_four_micro_usd() -> None:
    assert call_cost(CallUsage(input_tokens=1), OPUS_PRICE) == 4


def test_a_fraction_of_a_micro_usd_rounds_up_to_a_whole_one() -> None:
    # One cache-read token of Opus is 0.20 micro-dollars.
    assert call_cost(CallUsage(cache_read_tokens=1), OPUS_PRICE) == 1


def test_a_known_call_costs_its_exact_amount() -> None:
    # 1 000 input tokens at 4 and 200 output tokens at 20 micro-dollars each.
    assert call_cost(CallUsage(input_tokens=1_000, output_tokens=200), OPUS_PRICE) == 8_000


def test_a_call_is_rounded_up_once_as_a_whole_not_per_token_kind() -> None:
    # Each token costs half a micro-dollar: rounding each kind alone would give 2, not 1.
    assert call_cost(CallUsage(input_tokens=1, output_tokens=1), HALF_DOLLAR_PER_MTOK) == 1


def test_a_call_without_tokens_costs_nothing() -> None:
    assert call_cost(CallUsage(), OPUS_PRICE) == 0


def test_reserve_takes_every_byte_as_an_input_token_and_fills_the_answer() -> None:
    # (1 000 + 2 000) bytes at max(4, 5) plus 500 answer tokens at 20.
    assert call_reserve(1_000, 500, OPUS_PRICE) == 25_000


def test_reserve_uses_the_higher_of_input_and_cache_write_for_sonnet() -> None:
    # (1 000 + 2 000) at max(2, 2.50) plus 500 answer tokens at 10.
    assert call_reserve(1_000, 500, SONNET_PRICE) == 12_500


def test_reserve_rounds_a_fractional_total_up() -> None:
    price = ModelPrice(Decimal("0.3"), Decimal("0.3"), Decimal("0.3"), Decimal("0.3"))

    # 2 000 overhead tokens at 0.3 plus one answer token at 0.3 is 600.3.
    assert call_reserve(0, 1, price) == 601


def test_all_four_overrides_win_over_the_table() -> None:
    price = price_for(OPUS, input=1.5, output=2.5, cache_write=3.5, cache_read=0.25)

    assert price == ModelPrice(Decimal("1.5"), Decimal("2.5"), Decimal("3.5"), Decimal("0.25"))


def test_overrides_also_price_a_model_the_table_does_not_know() -> None:
    price = price_for("claude-unlisted-1", input=1, output=2, cache_write=3, cache_read=4)

    assert price == ModelPrice(Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4"))


def test_a_known_model_without_overrides_gets_the_table_price() -> None:
    assert price_for(OPUS) == OPUS_PRICE
    assert price_for(SONNET) == SONNET_PRICE


def test_an_unknown_model_without_overrides_has_no_price() -> None:
    assert price_for("claude-unlisted-1") is None


@st.composite
def calls(draw: st.DrawFn) -> tuple[int, int, CallUsage]:
    """A request size, its answer limit and a call that stays inside both: no cache tokens, as
    the server sends none."""

    request_bytes = draw(st.integers(min_value=0, max_value=2_000_000))
    max_tokens = draw(st.integers(min_value=1, max_value=32_000))
    usage = CallUsage(
        input_tokens=draw(st.integers(min_value=0, max_value=request_bytes + OVERHEAD_TOKENS)),
        output_tokens=draw(st.integers(min_value=0, max_value=max_tokens)),
    )
    return request_bytes, max_tokens, usage


@given(
    call=calls(),
    price=st.sampled_from(
        [
            OPUS_PRICE,
            SONNET_PRICE,
            ModelPrice(Decimal("3"), Decimal("15"), Decimal("0.1"), Decimal("0.3")),
        ]
    ),
)
def test_no_call_within_its_bounds_costs_more_than_its_reserve(
    call: tuple[int, int, CallUsage], price: ModelPrice
) -> None:
    request_bytes, max_tokens, usage = call

    assert call_cost(usage, price) <= call_reserve(request_bytes, max_tokens, price)
