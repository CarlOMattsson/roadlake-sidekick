"""What a webhook call does, as calls of the same use cases the MCP tools and the app use.

Shopping: one item on a named list, or on the owner's default list when none is named. The default
list is the owner's oldest active list (the order of `list_lists`), so a call without a list lands
where the owner's own first list is. An owner with no active list gets `NotFoundError`; a webhook
never creates a list.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sidekick.shared.errors import NotFoundError
from sidekick.shared.types import Actor
from sidekick.shopping.application.schemas import BatchItem
from sidekick.shopping.application.service import ShoppingService

# One item per call; the batch's own reference is never shown.
ITEM_CLIENT_REF = "webhook"


@dataclass(frozen=True, slots=True)
class AddedShoppingItem:
    list_id: UUID
    item_id: UUID


def add_shopping_item(
    shopping: ShoppingService,
    actor: Actor,
    item: BatchItem,
    list_id: UUID | None,
    *,
    idempotency_key: str,
    correlation_id: str | None,
) -> AddedShoppingItem:
    """Add `item` to `list_id`, or to the owner's oldest active list."""

    target = list_id if list_id is not None else _default_list_id(shopping, actor)
    added = shopping.add_items(
        actor,
        target,
        [item],
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    return AddedShoppingItem(list_id=target, item_id=added.items[0].item.id)


def _default_list_id(shopping: ShoppingService, actor: Actor) -> UUID:
    lists = shopping.list_lists(actor, limit=1).lists
    if not lists:
        raise NotFoundError("no active shopping list")
    return lists[0].id
