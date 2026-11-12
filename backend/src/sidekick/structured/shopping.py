"""The shopping item patch input, shared by the MCP tools and the companion API."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field, model_validator

from sidekick.shopping.application.schemas import (
    ItemFields,
)
from sidekick.shopping.application.service import ItemPatch
from sidekick.shopping.domain import Offer

if TYPE_CHECKING:
    pass


class ItemPatchInput(ItemFields):
    """update_shopping_item input: omitted name keeps the stored one; null or blank is refused."""

    name: Annotated[str, Field(min_length=1, max_length=200)] | None = None

    @model_validator(mode="after")
    def _name_is_never_cleared(self) -> ItemPatchInput:
        if "name" in self.model_fields_set and (self.name is None or not self.name.strip()):
            raise ValueError("name must be a non-empty string when sent")
        return self


def item_patch(item: ItemPatchInput) -> ItemPatch:
    """Only the fields the caller sent; an explicit null clears an optional field."""

    sent = item.model_fields_set
    fields: dict[str, Any] = {key: getattr(item, key) for key in sent if key != "offer"}
    if "offer" in sent:
        fields["offer"] = Offer(**item.offer.model_dump()) if item.offer else None
    return ItemPatch(**fields)
