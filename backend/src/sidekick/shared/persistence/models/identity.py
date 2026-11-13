"""Users and personal access tokens (MCP and companion credentials)."""

from datetime import datetime
from typing import ClassVar
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import SCHEMA, Base


class UserRow(Base):
    __tablename__ = "users"
    # SQLAlchemy's declarative base types `__table_args__` as an instance attribute.
    __table_args__: ClassVar[dict[str, str]] = {  # pyright: ignore[reportIncompatibleVariableOverride]
        "schema": SCHEMA
    }
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    username: Mapped[str] = mapped_column(String(120), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PersonalAccessTokenRow(Base):
    __tablename__ = "personal_access_tokens"
    __table_args__ = (Index("ix_pat_digest", "token_digest", unique=True), {"schema": SCHEMA})
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String(120))
    token_digest: Mapped[str] = mapped_column(String(64))
    scopes: Mapped[list[str]] = mapped_column(JSONB)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # `mcp` (a personal MCP token) or `companion` (a paired device). Each verifier
    # accepts only its own purpose; a companion row always has an expiry (database check).
    purpose: Mapped[str] = mapped_column(String(20), default="mcp")
    # Set only while a renewed companion credential's predecessor is still accepted: the
    # predecessor's keyed digest and when it stops working. Both or neither.
    previous_token_digest: Mapped[str | None] = mapped_column(String(64))
    previous_valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
