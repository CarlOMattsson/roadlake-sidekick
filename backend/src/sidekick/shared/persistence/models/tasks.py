"""Tasks, their status history, steps and actions."""

from datetime import datetime
from typing import Any
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
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import SCHEMA, Base


class TaskRow(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_owner_updated", "owner_id", "updated_at", "id"),
        ForeignKeyConstraint(
            ["project_id", "owner_id"],
            [f"{SCHEMA}.projects.id", f"{SCHEMA}.projects.owner_id"],
            name="fk_tasks_project_owner",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["waiting_on_contact_id", "owner_id"],
            [f"{SCHEMA}.contacts.id", f"{SCHEMA}.contacts.owner_id"],
            name="fk_tasks_waiting_contact_owner",
            ondelete="RESTRICT",
        ),
        # Declared in the 0.1.0 baseline schema; without them here the owner export cannot see the
        # relation and a restore would leave domain_id/process_id pointing at the old ids.
        ForeignKeyConstraint(
            ["domain_id", "owner_id"],
            [f"{SCHEMA}.domains.id", f"{SCHEMA}.domains.owner_id"],
            name="fk_tasks_domain_owner",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["process_id", "owner_id"],
            [f"{SCHEMA}.processes.id", f"{SCHEMA}.processes.owner_id"],
            name="fk_tasks_process_owner",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "owner_id", name="uq_tasks_id_owner"),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    project_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    domain_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    process_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))
    priority: Mapped[str] = mapped_column(String(20))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer)
    attention_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    board_rank: Mapped[int | None] = mapped_column(Integer)
    not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    estimated_minutes: Mapped[int | None] = mapped_column(Integer)
    waiting_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    follow_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    waiting_on_contact_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    blocked_reminder_cadence: Mapped[str | None] = mapped_column(String(12))
    blocked_reminder_snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    blocked_last_reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recurrence: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    last_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trashed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('simple', coalesce(title, '')), 'A') || "
            "setweight(to_tsvector('swedish', coalesce(description, '')), 'B')",
            persisted=True,
        ),
    )


class TaskStatusHistoryRow(Base):
    __tablename__ = "task_status_history"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "owner_id"],
            [f"{SCHEMA}.tasks.id", f"{SCHEMA}.tasks.owner_id"],
            name="fk_task_status_history_task_owner",
            ondelete="CASCADE",
        ),
        Index("ix_task_status_history_owner_task_changed", "owner_id", "task_id", "changed_at"),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    task_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(32))


class StepRow(Base):
    __tablename__ = "steps"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "owner_id"],
            [f"{SCHEMA}.tasks.id", f"{SCHEMA}.tasks.owner_id"],
            name="fk_steps_task_owner",
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "owner_id", name="uq_steps_id_owner"),
        Index("ix_steps_task_position", "owner_id", "task_id", "position", "id"),
        CheckConstraint("position >= 0", name="ck_steps_position"),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    task_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20))
    position: Mapped[int] = mapped_column(Integer)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attention_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    instruction: Mapped[str | None] = mapped_column(Text)
    trashed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ActionRow(Base):
    __tablename__ = "actions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["step_id", "owner_id"],
            [f"{SCHEMA}.steps.id", f"{SCHEMA}.steps.owner_id"],
            name="fk_actions_step_owner",
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "owner_id", name="uq_actions_id_owner"),
        Index("ix_actions_step_position", "owner_id", "step_id", "position", "id"),
        CheckConstraint("position >= 0", name="ck_actions_position"),
        CheckConstraint("status IN ('open', 'completed')", name="ck_actions_status"),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    step_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20))
    position: Mapped[int] = mapped_column(Integer)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attention_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)
    trashed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
