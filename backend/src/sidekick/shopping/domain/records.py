"""The shopping records a store returns and saves: lists, items and purchase changes."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from .item import ItemDetails


@dataclass(frozen=True, slots=True)
class ShoppingList:
    id: UUID
    owner_id: UUID
    name: str
    archived: bool
    version: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ShoppingItem:
    id: UUID
    owner_id: UUID
    list_id: UUID
    details: ItemDetails
    purchased: bool
    purchased_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class PurchaseChange:
    """One row of an item's purchase history: the state it moved to and the version it got."""

    id: UUID
    owner_id: UUID
    item_id: UUID
    purchased: bool
    item_version: int
    changed_at: datetime
