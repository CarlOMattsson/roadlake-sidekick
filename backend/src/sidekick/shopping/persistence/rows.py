"""The shopping table mappings, kept free of the store so the persistence layer can import them."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from sidekick.shared.persistence.models import Base


class ShoppingListRow(Base):
    __tablename__ = "shopping_lists"
    __table_args__ = (UniqueConstraint("id", "owner_id"), {"schema": "sidekick"})
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sidekick.users.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(200))
    archived: Mapped[bool]
    version: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ShoppingItemRow(Base):
    __tablename__ = "shopping_items"
    __table_args__ = (
        UniqueConstraint("id", "owner_id"),
        ForeignKeyConstraint(
            ["list_id", "owner_id"],
            ["sidekick.shopping_lists.id", "sidekick.shopping_lists.owner_id"],
        ),
        ForeignKeyConstraint(
            ["recipient_contact_id", "owner_id"],
            ["sidekick.contacts.id", "sidekick.contacts.owner_id"],
        ),
        {"schema": "sidekick"},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sidekick.users.id", ondelete="CASCADE")
    )
    list_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[Decimal] = mapped_column(Numeric(9, 3))
    unit: Mapped[str | None] = mapped_column(String(30))
    note: Mapped[str | None] = mapped_column(String(2000))
    store: Mapped[str | None] = mapped_column(String(200))
    product_url: Mapped[str | None] = mapped_column(String(2000))
    recipient_contact_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    occasion: Mapped[str | None] = mapped_column(String(200))
    target_date: Mapped[date | None] = mapped_column(Date)
    offer_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    offer_regular_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    offer_currency: Mapped[str | None] = mapped_column(String(3))
    offer_source: Mapped[str | None] = mapped_column(String(200))
    offer_source_url: Mapped[str | None] = mapped_column(String(2000))
    offer_valid_from: Mapped[date | None] = mapped_column(Date)
    offer_valid_until: Mapped[date | None] = mapped_column(Date)
    offer_checked_on: Mapped[date | None] = mapped_column(Date)
    purchased: Mapped[bool]
    purchased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    trashed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ShoppingStatusRow(Base):
    __tablename__ = "shopping_item_status_history"
    __table_args__ = (
        ForeignKeyConstraint(
            ["item_id", "owner_id"],
            ["sidekick.shopping_items.id", "sidekick.shopping_items.owner_id"],
        ),
        {"schema": "sidekick"},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sidekick.users.id", ondelete="CASCADE")
    )
    item_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    purchased: Mapped[bool]
    item_version: Mapped[int]
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
