"""The store port the shopping use cases depend on."""

from typing import Protocol
from uuid import UUID

from sidekick.shared.types import AuditingStore, IdempotentStore, TransactionalStore, TxSession
from sidekick.shopping.domain import PurchaseChange, ShoppingItem, ShoppingList


class ShoppingStore(TransactionalStore, IdempotentStore, AuditingStore, Protocol):
    """What the shopping use cases need from storage; every method is scoped to one owner."""

    def get_list(
        self, session: TxSession, owner: UUID, list_id: UUID, *, lock: bool = False
    ) -> ShoppingList: ...
    def get_item(self, session: TxSession, owner: UUID, item_id: UUID) -> ShoppingItem: ...
    def add_list(self, session: TxSession, shopping_list: ShoppingList) -> None: ...
    def save_list(self, session: TxSession, shopping_list: ShoppingList) -> None: ...
    def add_item(self, session: TxSession, item: ShoppingItem) -> None: ...
    def save_item(self, session: TxSession, item: ShoppingItem) -> None: ...
    def add_purchase_change(self, session: TxSession, change: PurchaseChange) -> None: ...
    def list_lists(
        self,
        session: TxSession,
        owner: UUID,
        *,
        include_archived: bool,
        offset: int,
        limit: int,
    ) -> list[ShoppingList]: ...
    def list_items(
        self,
        session: TxSession,
        owner: UUID,
        list_id: UUID,
        *,
        store_name: str | None,
        offset: int,
        limit: int,
    ) -> list[ShoppingItem]: ...
    def open_items(self, session: TxSession, owner: UUID, list_id: UUID) -> list[ShoppingItem]: ...
    def open_count(self, session: TxSession, owner: UUID, list_id: UUID) -> int: ...
    def open_counts(
        self, session: TxSession, owner: UUID, list_ids: list[UUID]
    ) -> dict[UUID, int]: ...
    def has_active_contact(self, session: TxSession, owner: UUID, contact_id: UUID) -> bool: ...
    def contact_display_names(
        self, session: TxSession, owner: UUID, contact_ids: tuple[UUID, ...]
    ) -> dict[UUID, tuple[str, bool]]: ...
