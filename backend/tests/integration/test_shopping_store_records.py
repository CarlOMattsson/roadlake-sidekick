"""The shopping store takes and returns domain records: rows never leave the persistence layer."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from sidekick.shared.auth import AuthService
from sidekick.shared.errors import NotFoundError
from sidekick.shared.types import new_uuid7
from sidekick.shopping.domain import ItemDetails, Offer, PurchaseChange, ShoppingItem, ShoppingList
from sidekick.shopping.persistence.store import ShoppingStore
from tests.db import database_factory

NOW = datetime(2026, 7, 21, 10, 0, tzinfo=UTC)
LATER = datetime(2026, 7, 21, 11, 0, tzinfo=UTC)


def _list(owner: UUID) -> ShoppingList:
    return ShoppingList(
        id=new_uuid7(), owner_id=owner, name="Vecka", archived=False, version=1,
        created_at=NOW, updated_at=NOW,
    )  # fmt: skip


def _item(shopping_list: ShoppingList, details: ItemDetails) -> ShoppingItem:
    return ShoppingItem(
        id=new_uuid7(), owner_id=shopping_list.owner_id, list_id=shopping_list.id,
        details=details, purchased=False, purchased_at=None, version=1,
        created_at=NOW, updated_at=NOW,
    )  # fmt: skip


@pytest.mark.integration
def test_lists_and_items_round_trip_through_records_and_saves_replace_every_field() -> None:
    factory = database_factory()
    auth = AuthService(factory, "pepper" * 8)
    owner = auth.provision_user("records-owner", "Owner")
    stranger = auth.provision_user("records-stranger", "Stranger")
    store = ShoppingStore(factory)
    offer = Offer(
        price=Decimal("39.90"), valid_from=date(2026, 7, 20), valid_until=date(2026, 7, 27),
        source="Leaflet", checked_on=date(2026, 7, 21), regular_price=Decimal("49.90"),
    )  # fmt: skip
    shopping_list = _list(owner)
    item = _item(
        shopping_list,
        ItemDetails("Kaffe", quantity=Decimal("2.500"), unit="kg", store="ICA", offer=offer),
    )

    def write(session: Session) -> None:
        store.add_list(session, shopping_list)
        store.add_item(session, item)

    store.transaction(write)

    def read(session: Session) -> None:
        assert store.get_list(session, owner, shopping_list.id) == shopping_list
        assert store.get_item(session, owner, item.id) == item
        assert store.open_items(session, owner, shopping_list.id) == [item]
        with pytest.raises(NotFoundError):
            store.get_item(session, stranger, item.id)
        with pytest.raises(NotFoundError):
            store.get_list(session, stranger, shopping_list.id)

    store.transaction(read)

    bought = replace(
        item,
        details=replace(item.details, quantity=Decimal("1"), offer=None, note="Ground"),
        purchased=True, purchased_at=LATER, version=2, updated_at=LATER,
    )  # fmt: skip
    renamed = replace(shopping_list, name="Helgen", archived=True, version=2, updated_at=LATER)

    def change(session: Session) -> None:
        store.save_item(session, bought)
        store.save_list(session, renamed)
        store.add_purchase_change(
            session, PurchaseChange(new_uuid7(), owner, item.id, True, 2, LATER)
        )

    store.transaction(change)

    def reread(session: Session) -> None:
        assert store.get_item(session, owner, item.id) == bought
        assert store.get_list(session, owner, shopping_list.id) == renamed
        assert store.open_items(session, owner, shopping_list.id) == []
        assert store.open_count(session, owner, shopping_list.id) == 0

    store.transaction(reread)
