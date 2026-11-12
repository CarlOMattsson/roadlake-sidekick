"""Offer validity and safe shopping details without a framework or database."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from sidekick.shared.errors import ValidationError
from sidekick.shopping.application.schemas import ItemRecord, ItemResult, PurchasedBatchResult
from sidekick.shopping.domain import ItemDetails, Offer


def test_offer_boundaries_are_inclusive_and_future_purchases_need_no_date():
    offer = Offer(
        Decimal("49.90"),
        date(2026, 10, 19),
        date(2026, 10, 25),
        "Weekly leaflet",
        date(2026, 10, 24),
    )
    assert [offer.status(date(2026, 10, day)) for day in (18, 19, 25, 26)] == [
        "upcoming",
        "current",
        "current",
        "expired",
    ]
    idea = ItemDetails("  Future IKEA shelf  ", store="IKEA")
    assert idea.name == "Future IKEA shelf" and idea.target_date is None


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "https://user:password@example.org/",
        "//example.org",
        "https://example.org/\\hidden",
    ],
)
def test_product_links_reject_executable_or_credential_urls(url):
    with pytest.raises(ValidationError):
        ItemDetails("A gift", product_url=url)


def test_offer_rejects_a_false_discount_and_reversed_dates():
    for kwargs in ({"regular_price": Decimal("40")}, {"valid_until": date(2026, 10, 18)}):
        args = dict(
            price=Decimal("49.90"),
            valid_from=date(2026, 10, 19),
            valid_until=date(2026, 10, 25),
            source="Leaflet",
            checked_on=date(2026, 10, 24),
        )
        with pytest.raises(ValidationError):
            Offer(**{**args, **kwargs})


def test_results_without_open_count_validate_as_none_for_idempotent_replays():
    # Results stored before open_count existed are replayed without it; they must still validate.
    now = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)
    item = ItemRecord(
        name="Mjölk",
        id=uuid4(),
        list_id=uuid4(),
        purchased=False,
        purchased_at=None,
        version=1,
        created_at=now,
        updated_at=now,
        offer_status="none",
    )
    stored_item = {"item": item.model_dump(mode="json"), "evaluated_on": "2026-11-05"}
    single = ItemResult.model_validate({**stored_item, "list_name": "Veckohandel"})
    assert single.open_count is None
    batch = PurchasedBatchResult.model_validate(
        {"items": [item.model_dump(mode="json")], "evaluated_on": "2026-11-05"}
    )
    assert batch.open_count is None
