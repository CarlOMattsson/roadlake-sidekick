"""The rule shared by every group that lets the owner state a model's price."""

from collections.abc import Sequence


def require_prices_together(prefix: str, prices: Sequence[float | None]) -> None:
    """Raise unless the four prices (input, output, cache write, cache read) are all given or
    none is: a model priced by only some of them could not have its calls counted."""

    if any(price is not None for price in prices) and any(price is None for price in prices):
        raise ValueError(f"{prefix}* must be set all four together or not at all")
