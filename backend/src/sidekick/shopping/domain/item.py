"""Shopping rules independent of transports, providers and persistence."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from sidekick.shared.errors import ValidationError

OfferStatus = Literal["none", "upcoming", "current", "expired"]

DETAIL_FIELDS = (
    "name",
    "quantity",
    "unit",
    "note",
    "store",
    "product_url",
    "recipient_contact_id",
    "occasion",
    "target_date",
)
OFFER_FIELDS = (
    "price",
    "regular_price",
    "currency",
    "source",
    "source_url",
    "valid_from",
    "valid_until",
    "checked_on",
)


def text(value: str | None, maximum: int, *, required: bool = False) -> str | None:
    if value is not None:
        value = value.strip() or None
    if (required and value is None) or (value is not None and len(value) > maximum):
        raise ValidationError("invalid shopping text")
    return value


def required_text(value: str | None, maximum: int) -> str:
    """Like `text(..., required=True)`, but typed as a str: a missing or blank value raises."""

    cleaned = text(value, maximum, required=True)
    if (
        cleaned is None
    ):  # unreachable while `text` enforces `required`; kept as a real check, not an assert
        raise ValidationError("invalid shopping text")
    return cleaned


def web_url(value: str | None) -> str | None:
    value = text(value, 2000)
    if value is not None:
        try:
            parsed = urlsplit(value)
            valid = (
                parsed.scheme in {"https", "http"}
                and parsed.hostname
                and not parsed.username
                and not parsed.password
                and not any(ord(c) < 32 or c == "\\" for c in value)
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValidationError("invalid shopping link")
    return value


@dataclass(frozen=True, slots=True)
class Offer:
    price: Decimal
    valid_from: date
    valid_until: date
    source: str
    checked_on: date
    currency: str = "SEK"
    regular_price: Decimal | None = None
    source_url: str | None = None

    def __post_init__(self) -> None:
        if not self.price.is_finite() or not 0 < self.price <= Decimal("99999999.99"):
            raise ValidationError("invalid offer price")
        if self.price != self.price.quantize(Decimal("0.01")):
            raise ValidationError("offer price precision")
        if self.regular_price is not None and (
            not self.regular_price.is_finite()
            or not self.price < self.regular_price <= Decimal("99999999.99")
            or self.regular_price != self.regular_price.quantize(Decimal("0.01"))
        ):
            raise ValidationError("invalid regular price")
        if self.valid_until < self.valid_from:
            raise ValidationError("invalid offer date range")
        if len(self.currency) != 3 or not all("A" <= c <= "Z" for c in self.currency):
            raise ValidationError("invalid offer currency")
        object.__setattr__(self, "source", text(self.source, 200, required=True))
        object.__setattr__(self, "source_url", web_url(self.source_url))

    def status(self, on_date: date) -> OfferStatus:
        if on_date < self.valid_from:
            return "upcoming"
        return "expired" if on_date > self.valid_until else "current"


@dataclass(frozen=True, slots=True)
class ItemDetails:
    name: str
    quantity: Decimal = Decimal("1")
    unit: str | None = None
    note: str | None = None
    store: str | None = None
    product_url: str | None = None
    recipient_contact_id: UUID | None = None
    occasion: str | None = None
    target_date: date | None = None
    offer: Offer | None = None

    def __post_init__(self) -> None:
        for field, maximum in (
            ("name", 200),
            ("unit", 30),
            ("note", 2000),
            ("store", 200),
            ("occasion", 200),
        ):
            object.__setattr__(
                self, field, text(getattr(self, field), maximum, required=field == "name")
            )
        if (
            not self.quantity.is_finite()
            or not 0 < self.quantity <= Decimal("999999.999")
            or self.quantity != self.quantity.quantize(Decimal("0.001"))
        ):
            raise ValidationError("invalid shopping quantity")
        object.__setattr__(self, "product_url", web_url(self.product_url))
