"""Concrete shopping tables and owner-filtered PostgreSQL operations."""

from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from sidekick.shared.errors import ConflictError, NotFoundError
from sidekick.shared.persistence.models import ContactRow
from sidekick.shopping.persistence.rows import ShoppingItemRow, ShoppingListRow
from sidekick.store import SqlAlchemyStore


class ShoppingStore(SqlAlchemyStore):
    @staticmethod
    def ensure_contact_unlinked(session: Session, owner: UUID, contact_id: UUID) -> None:
        # Serialize deletion with recipient validation, then explain the FK refusal.
        contact = session.scalar(
            select(ContactRow)
            .where(
                ContactRow.id == contact_id,
                ContactRow.owner_id == owner,
            )
            .with_for_update()
        )
        if (
            contact is not None
            and session.scalar(
                select(ShoppingItemRow.id)
                .where(
                    ShoppingItemRow.owner_id == owner,
                    ShoppingItemRow.recipient_contact_id == contact_id,
                )
                .limit(1)
            )
            is not None
        ):
            raise ConflictError(
                "unlink shopping gift recipients before removing contact; a shopping item in "
                "the trash may still name this contact, so restore or change that item first"
            )

    @staticmethod
    def get_list(
        session: Session, owner: UUID, list_id: UUID, *, lock: bool = False
    ) -> ShoppingListRow:
        statement = select(ShoppingListRow).where(
            ShoppingListRow.id == list_id, ShoppingListRow.owner_id == owner
        )
        row = session.scalar(statement.with_for_update() if lock else statement)
        if row is None:
            raise NotFoundError("shopping list not found")
        return row

    @staticmethod
    def get_item(session: Session, owner: UUID, item_id: UUID) -> ShoppingItemRow:
        # A trashed item is hidden everywhere, so edits to it fail as not found until restored.
        row = session.scalar(
            select(ShoppingItemRow)
            .where(
                ShoppingItemRow.id == item_id,
                ShoppingItemRow.owner_id == owner,
                ShoppingItemRow.trashed_at.is_(None),
            )
            .with_for_update()
        )
        if row is None:
            raise NotFoundError("shopping item not found")
        return row

    @staticmethod
    def list_lists(
        session: Session, owner: UUID, *, include_archived: bool, offset: int, limit: int
    ) -> list[ShoppingListRow]:
        """The owner's lists, oldest first, from `offset`; at most `limit` rows."""

        query = select(ShoppingListRow).where(ShoppingListRow.owner_id == owner)
        if not include_archived:
            query = query.where(ShoppingListRow.archived.is_(False))
        return list(
            session.scalars(
                query.order_by(ShoppingListRow.created_at, ShoppingListRow.id)
                .offset(offset)
                .limit(limit)
            )
        )

    @staticmethod
    def list_items(
        session: Session,
        owner: UUID,
        list_id: UUID,
        *,
        store_name: str | None,
        offset: int,
        limit: int,
    ) -> list[ShoppingItemRow]:
        """Untrashed items of one list, oldest first, from `offset`; at most `limit` rows.

        `store_name` keeps the items whose store equals it, ignoring case, plus the items with
        no store; None keeps every item.
        """

        conditions = [
            ShoppingItemRow.owner_id == owner,
            ShoppingItemRow.list_id == list_id,
            ShoppingItemRow.trashed_at.is_(None),
        ]
        if store_name is not None:
            conditions.append(
                or_(
                    ShoppingItemRow.store.is_(None),
                    func.lower(ShoppingItemRow.store) == store_name.lower(),
                )
            )
        return list(
            session.scalars(
                select(ShoppingItemRow)
                .where(*conditions)
                .order_by(ShoppingItemRow.created_at, ShoppingItemRow.id)
                .offset(offset)
                .limit(limit)
            )
        )

    @staticmethod
    def open_items(session: Session, owner: UUID, list_id: UUID) -> list[ShoppingItemRow]:
        """Unpurchased, untrashed items of the list, oldest first."""

        return list(
            session.scalars(
                select(ShoppingItemRow)
                .where(
                    ShoppingItemRow.owner_id == owner,
                    ShoppingItemRow.list_id == list_id,
                    ShoppingItemRow.purchased.is_(False),
                    ShoppingItemRow.trashed_at.is_(None),
                )
                .order_by(ShoppingItemRow.created_at, ShoppingItemRow.id)
            )
        )

    @staticmethod
    def active_contact(session: Session, owner: UUID, contact_id: UUID) -> ContactRow | None:
        """The owner's live (not archived, not trashed) contact, share-locked against deletion."""

        return session.scalar(
            select(ContactRow)
            .where(
                ContactRow.id == contact_id,
                ContactRow.owner_id == owner,
                ContactRow.archived.is_(False),
                ContactRow.trashed_at.is_(None),
            )
            .with_for_update(read=True)
        )

    @staticmethod
    def open_count(session: Session, owner: UUID, list_id: UUID) -> int:
        """Unpurchased, untrashed items of the list, counted in one query after this write."""

        session.flush()
        count = session.scalar(
            select(func.count())
            .select_from(ShoppingItemRow)
            .where(
                ShoppingItemRow.owner_id == owner,
                ShoppingItemRow.list_id == list_id,
                ShoppingItemRow.purchased.is_(False),
                ShoppingItemRow.trashed_at.is_(None),
            )
        )
        return int(count or 0)

    @staticmethod
    def open_counts(session: Session, owner: UUID, list_ids: list[UUID]) -> dict[UUID, int]:
        """Unpurchased, untrashed items per list for the given lists, in one grouped query.
        Lists without open items are absent from the result."""

        if not list_ids:
            return {}
        rows = session.execute(
            select(ShoppingItemRow.list_id, func.count())
            .where(
                ShoppingItemRow.owner_id == owner,
                ShoppingItemRow.list_id.in_(list_ids),
                ShoppingItemRow.purchased.is_(False),
                ShoppingItemRow.trashed_at.is_(None),
            )
            .group_by(ShoppingItemRow.list_id)
        ).all()
        return {list_id: int(count) for list_id, count in rows}
