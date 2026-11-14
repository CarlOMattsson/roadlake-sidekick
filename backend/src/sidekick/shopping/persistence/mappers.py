"""Row to record mappers for shopping lists, items and purchase changes, and back."""

from sidekick.shopping.domain import (
    DETAIL_FIELDS,
    OFFER_FIELDS,
    ItemDetails,
    Offer,
    PurchaseChange,
    ShoppingItem,
    ShoppingList,
)
from sidekick.shopping.persistence.rows import ShoppingItemRow, ShoppingListRow, ShoppingStatusRow


def list_from_row(row: ShoppingListRow) -> ShoppingList:
    return ShoppingList(
        id=row.id,
        owner_id=row.owner_id,
        name=row.name,
        archived=row.archived,
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def list_row(shopping_list: ShoppingList) -> ShoppingListRow:
    return ShoppingListRow(
        id=shopping_list.id,
        owner_id=shopping_list.owner_id,
        name=shopping_list.name,
        archived=shopping_list.archived,
        version=shopping_list.version,
        created_at=shopping_list.created_at,
        updated_at=shopping_list.updated_at,
    )


def apply_list(row: ShoppingListRow, shopping_list: ShoppingList) -> None:
    row.name, row.archived = shopping_list.name, shopping_list.archived
    row.version, row.updated_at = shopping_list.version, shopping_list.updated_at


def item_from_row(row: ShoppingItemRow) -> ShoppingItem:
    offer = (
        Offer(**{key: getattr(row, f"offer_{key}") for key in OFFER_FIELDS})
        if row.offer_price is not None
        else None
    )
    return ShoppingItem(
        id=row.id,
        owner_id=row.owner_id,
        list_id=row.list_id,
        details=ItemDetails(**{key: getattr(row, key) for key in DETAIL_FIELDS}, offer=offer),
        purchased=row.purchased,
        purchased_at=row.purchased_at,
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def apply_item(row: ShoppingItemRow, item: ShoppingItem) -> None:
    """Copy every editable and versioned field of the item onto its row."""

    details = item.details
    for key in DETAIL_FIELDS:
        setattr(row, key, getattr(details, key))
    for key in OFFER_FIELDS:
        setattr(row, f"offer_{key}", getattr(details.offer, key) if details.offer else None)
    row.purchased, row.purchased_at = item.purchased, item.purchased_at
    row.version, row.updated_at = item.version, item.updated_at


def item_row(item: ShoppingItem) -> ShoppingItemRow:
    row = ShoppingItemRow(
        id=item.id,
        owner_id=item.owner_id,
        list_id=item.list_id,
        created_at=item.created_at,
    )
    apply_item(row, item)
    return row


def purchase_change_row(change: PurchaseChange) -> ShoppingStatusRow:
    return ShoppingStatusRow(
        id=change.id,
        owner_id=change.owner_id,
        item_id=change.item_id,
        purchased=change.purchased,
        item_version=change.item_version,
        changed_at=change.changed_at,
    )
