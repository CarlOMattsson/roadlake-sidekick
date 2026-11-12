"""Contacts, their aliases and the links from projects and tasks to contacts."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import SCHEMA, Base


class ContactRow(Base):
    __tablename__ = "contacts"
    __table_args__ = (
        Index("ix_contacts_search", "owner_id", "archived", "display_name_key", "id"),
        Index("ix_contacts_email", "owner_id", "email_key"),
        Index("ix_contacts_phone", "owner_id", "phone_key"),
        CheckConstraint(
            "(archived = false AND archived_at IS NULL) OR "
            "(archived = true AND archived_at IS NOT NULL)",
            name="ck_contacts_archive_consistency",
        ),
        UniqueConstraint("id", "owner_id", name="uq_contacts_id_owner"),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    display_name: Mapped[str] = mapped_column(String(200))
    display_name_key: Mapped[str] = mapped_column(String(200))
    context_note: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(String(320))
    email_key: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(64))
    phone_key: Mapped[str | None] = mapped_column(String(64))
    # Shadows the imported `relationship()` only inside this class body, which uses none.
    relationship: Mapped[str | None] = mapped_column(String(80))
    organization: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[str | None] = mapped_column(String(120))
    address: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    trashed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('simple', coalesce(display_name, '')), 'A') || "
            "setweight(to_tsvector('swedish', coalesce(context_note, '')), 'B')",
            persisted=True,
        ),
    )


class ContactAliasRow(Base):
    __tablename__ = "contact_aliases"
    __table_args__ = (
        Index("ix_contact_aliases_search", "owner_id", "normalized_key", "contact_id"),
        Index("ix_contact_aliases_stable", "owner_id", "contact_id", "normalized_key", "id"),
        UniqueConstraint("owner_id", "contact_id", "normalized_key", name="uq_contact_aliases_key"),
        ForeignKeyConstraint(
            ["contact_id", "owner_id"],
            [f"{SCHEMA}.contacts.id", f"{SCHEMA}.contacts.owner_id"],
            name="fk_aliases_contact_owner",
            ondelete="CASCADE",
        ),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    contact_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    display_value: Mapped[str] = mapped_column(String(120))
    normalized_key: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('simple', coalesce(display_value, '')), 'A')", persisted=True
        ),
    )


class ProjectContactRow(Base):
    __tablename__ = "project_contacts"
    __table_args__ = (
        Index("ix_project_contacts_reverse", "owner_id", "contact_id", "project_id"),
        ForeignKeyConstraint(
            ["project_id", "owner_id"],
            [f"{SCHEMA}.projects.id", f"{SCHEMA}.projects.owner_id"],
            name="fk_project_contacts_project",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["contact_id", "owner_id"],
            [f"{SCHEMA}.contacts.id", f"{SCHEMA}.contacts.owner_id"],
            name="fk_project_contacts_contact",
            ondelete="CASCADE",
        ),
        {"schema": SCHEMA},
    )
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), primary_key=True
    )
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    contact_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TaskContactRow(Base):
    __tablename__ = "task_contacts"
    __table_args__ = (
        Index("ix_task_contacts_reverse", "owner_id", "contact_id", "task_id"),
        ForeignKeyConstraint(
            ["task_id", "owner_id"],
            [f"{SCHEMA}.tasks.id", f"{SCHEMA}.tasks.owner_id"],
            name="fk_task_contacts_task",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["contact_id", "owner_id"],
            [f"{SCHEMA}.contacts.id", f"{SCHEMA}.contacts.owner_id"],
            name="fk_task_contacts_contact",
            ondelete="CASCADE",
        ),
        {"schema": SCHEMA},
    )
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), primary_key=True
    )
    task_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    contact_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
