"""Closed wire contracts of the shopping MCP tools."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from sidekick.shopping.domain import ItemDetails, Offer, OfferStatus


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OfferInput(Closed):
    price: Annotated[Decimal, Field(gt=0, le=99999999.99, max_digits=10, decimal_places=2)]
    valid_from: date
    valid_until: date
    source: Annotated[str, Field(min_length=1, max_length=200)]
    checked_on: date
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] = "SEK"
    regular_price: Annotated[
        Decimal | None, Field(gt=0, le=99999999.99, max_digits=10, decimal_places=2)
    ] = None
    source_url: Annotated[str | None, Field(max_length=2000)] = None


class ItemFields(Closed):
    """Item fields shared by the required-name input and the update that keeps an omitted name."""

    quantity: Annotated[Decimal, Field(gt=0, le=999999.999, max_digits=9, decimal_places=3)] = (
        Decimal("1")
    )
    unit: Annotated[str | None, Field(max_length=30)] = None
    note: Annotated[str | None, Field(max_length=2000)] = None
    store: Annotated[str | None, Field(max_length=200)] = None
    product_url: Annotated[str | None, Field(max_length=2000)] = None
    recipient_contact_id: UUID | None = None
    occasion: Annotated[str | None, Field(max_length=200)] = None
    target_date: date | None = None
    offer: OfferInput | None = None


class ItemInput(ItemFields):
    name: Annotated[str, Field(min_length=1, max_length=200)]

    def domain(self) -> ItemDetails:
        fields = self.model_dump(exclude={"offer"})
        return ItemDetails(**fields, offer=Offer(**self.offer.model_dump()) if self.offer else None)


class BatchItem(ItemInput):
    client_ref: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]

    def domain(self) -> ItemDetails:
        return ItemInput.model_validate(self.model_dump(exclude={"client_ref"})).domain()


class ListRecord(Closed):
    id: UUID
    name: str
    archived: bool
    version: int
    created_at: datetime
    updated_at: datetime


class ListSummary(ListRecord):
    # Unpurchased, untrashed items in the list. Only the list read carries it.
    open_count: Annotated[int, Field(ge=0)]


class ItemRecord(ItemInput):
    id: UUID
    list_id: UUID
    purchased: bool
    purchased_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime
    offer_status: OfferStatus
    recipient_contact_name: str | None = None
    """Display name of the gift recipient; only set when contacts:read is held."""


class ListsResult(Closed):
    lists: Annotated[list[ListSummary], Field(max_length=100)]
    next_offset: int | None


class ListResult(Closed):
    shopping_list: ListRecord


class ListDetail(ListResult):
    items: Annotated[list[ItemRecord], Field(max_length=100)]
    next_offset: int | None
    evaluated_on: date
    # The store filter the read used (case as sent, trimmed), or null for the whole list.
    store: str | None = None


class AddedItem(Closed):
    client_ref: str
    item: ItemRecord
    # True when merge_duplicates folded this input into an unpurchased item of the same name and
    # unit: `item` is then that existing item with its increased quantity.
    merged: bool = False


class BatchResult(Closed):
    items: Annotated[list[AddedItem], Field(max_length=50)]
    evaluated_on: date
    list_name: str
    # How many inputs were merged into existing items instead of creating new rows.
    merged_count: int = 0
    # Unpurchased, untrashed items in the list after this write.
    # None in results stored before this field existed (idempotent replay).
    open_count: int | None = None


class ItemResult(Closed):
    item: ItemRecord
    evaluated_on: date
    list_name: str
    # Unpurchased, untrashed items in the list after this write.
    # None in results stored before this field existed (idempotent replay).
    open_count: int | None = None


class PurchaseTarget(Closed):
    item_id: UUID
    version: Annotated[int, Field(ge=1)]


class PurchasedBatchResult(Closed):
    items: Annotated[list[ItemRecord], Field(max_length=50)]
    # Items that were already in the asked state and were left as they were.
    unchanged_item_ids: Annotated[list[UUID], Field(max_length=50)] = Field(
        default_factory=list[UUID]
    )
    evaluated_on: date
    # Unpurchased, untrashed items in the list after this write when all items share one list,
    # else None. None also in results stored before this field existed (idempotent replay).
    open_count: int | None = None


class PurchaseOutcome(ItemResult):
    """What `set_purchased` returns: the ItemResult plus an internal flag transports drop."""

    # True when the item was already in the asked state and was left as it was.
    unchanged: bool
