"""Mappings for ready conversations: the owner's schedules and the days skipped or started.

The application role can read, insert and update `ready_conversations` but not delete them (a
conversation is paused or archived), and can do all four on `ready_conversation_days`, the rows of
which it deletes once they are 60 days old (migration 123). `instruction` is the owner's own text
for Claude; nothing here is logged.
"""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import SCHEMA, Base


class ReadyConversationRow(Base):
    """One standing conversation: when it is ready, what to read when it starts, what to say."""

    __tablename__ = "ready_conversations"
    __table_args__ = (
        UniqueConstraint("id", "owner_id", name="uq_ready_conversations_id_owner"),
        CheckConstraint("char_length(title) BETWEEN 1 AND 80", name="ck_ready_conversations_title"),
        CheckConstraint(
            "(instruction IS NULL AND instruction_written_by IS NULL "
            "AND NOT instruction_edited_by_model) "
            "OR (instruction IS NOT NULL AND instruction_written_by IS NOT NULL "
            "AND instruction_written_by IN ('you', 'claude'))",
            name="ck_ready_conversations_instruction_provenance",
        ),
        CheckConstraint(
            "kind IN ('evening_review', 'morning_plan', 'weekly_review', 'custom')",
            name="ck_ready_conversations_kind",
        ),
        CheckConstraint(
            "instruction IS NULL OR char_length(instruction) BETWEEN 1 AND 2000",
            name="ck_ready_conversations_instruction",
        ),
        CheckConstraint(
            "cardinality(ingredients) <= 10 AND ingredients <@ ARRAY["
            "'tasks_done_today', 'tasks_due_today', 'tasks_due_tomorrow', 'overdue', 'waiting', "
            "'suggestions', 'journal_today', 'review', 'automation_report', 'shopping_open']"
            "::character varying[]",
            name="ck_ready_conversations_ingredients",
        ),
        CheckConstraint(
            "jsonb_typeof(cadence) = 'object' AND octet_length(cadence::text) <= 2048",
            name="ck_ready_conversations_cadence",
        ),
        CheckConstraint(
            "state IN ('active', 'paused', 'archived')", name="ck_ready_conversations_state"
        ),
        CheckConstraint("version >= 1", name="ck_ready_conversations_version"),
        Index("ix_ready_conversations_owner_state", "owner_id", "state"),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(16))
    instruction: Mapped[str | None] = mapped_column(Text)
    instruction_written_by: Mapped[str | None] = mapped_column(String(8))
    instruction_edited_by_model: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    ingredients: Mapped[list[str]] = mapped_column(
        ARRAY(String(24)), default=list, server_default=text("'{}'")
    )
    cadence: Mapped[dict[str, Any]] = mapped_column(JSONB(none_as_null=True))
    state: Mapped[str] = mapped_column(
        String(10), default="active", server_default=text("'active'")
    )
    version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReadyConversationDayRow(Base):
    """What happened to a conversation on one calendar day: skipped, started, or reopened.

    Transient: not part of the owner export, and pruned after 60 days.
    """

    __tablename__ = "ready_conversation_days"
    __table_args__ = (
        ForeignKeyConstraint(
            ["conversation_id", "owner_id"],
            [f"{SCHEMA}.ready_conversations.id", f"{SCHEMA}.ready_conversations.owner_id"],
            name="fk_ready_conversation_days_conversation_owner",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "state IN ('skipped', 'started', 'open')", name="ck_ready_conversation_days_state"
        ),
        CheckConstraint("version >= 1", name="ck_ready_conversation_days_version"),
        Index("ix_ready_conversation_days_owner_day", "owner_id", "day"),
        {"schema": SCHEMA},
    )
    conversation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    state: Mapped[str] = mapped_column(String(8))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer)
