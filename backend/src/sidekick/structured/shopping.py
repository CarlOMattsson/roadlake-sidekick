"""The shopping item patch input, shared by the MCP tools and the companion API."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from sidekick.shopping.application.schemas import (
    ItemFields,
    ItemResult,
)
from sidekick.shopping.application.service import ItemPatch
from sidekick.shopping.domain import Offer
from sidekick.structured.base import PartialChanges, WithIgnoredNulls


class ItemPatchInput(PartialChanges, ItemFields):
    """update_shopping_item input: an omitted or null field stays; `clear` empties one."""

    fixed_fields = frozenset({"name", "quantity"})
    requires_change = False

    name: Annotated[str | None, Field(min_length=1, max_length=200)] = None

    @model_validator(mode="after")
    def _name_is_never_blank(self) -> ItemPatchInput:
        if self.name is not None and not self.name.strip():
            raise ValueError("name must be a non-empty string when sent")
        return self


ItemClear = Literal[
    "unit",
    "note",
    "store",
    "product_url",
    "recipient_contact_id",
    "occasion",
    "target_date",
    "offer",
]


class UpdatedItemResult(ItemResult, WithIgnoredNulls):
    """update_shopping_item's reply: the item and the nulls that were not applied."""


def item_patch(item: ItemPatchInput) -> ItemPatch:
    """Only the fields the caller sent or cleared (resolved changes)."""

    sent = item.model_fields_set
    fields: dict[str, Any] = {key: getattr(item, key) for key in sent if key != "offer"}
    if "offer" in sent:
        fields["offer"] = Offer(**item.offer.model_dump()) if item.offer else None
    return ItemPatch(**fields)
