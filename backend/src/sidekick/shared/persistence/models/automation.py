"""Assistant automation policies, kill switch, runs and task review findings."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import SCHEMA, Base


class AssistantAutomationPolicyRow(Base):
    """Sparse per-owner policy override for an automation category."""

    __tablename__ = "assistant_automation_policies"
    __table_args__ = ({"schema": SCHEMA},)
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), primary_key=True
    )
    category: Mapped[str] = mapped_column(String(48), primary_key=True)
    mode: Mapped[str] = mapped_column(String(24))
    version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AssistantAutomationControlRow(Base):
    """Owner-scoped kill switch for all autonomous work."""

    __tablename__ = "assistant_automation_control"
    __table_args__ = ({"schema": SCHEMA},)
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), primary_key=True
    )
    pause_all_automation: Mapped[bool] = mapped_column(Boolean)
    version: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AssistantAutomationRunRow(Base):
    """Durable claimable execution record for a bounded automation review."""

    __tablename__ = "assistant_automation_runs"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "kind",
            "scheduled_for",
            name="uq_automation_runs_owner_kind_schedule",
        ),
        Index("ix_automation_runs_claim", "status", "scheduled_for", "created_at", "id"),
        Index("ix_automation_runs_owner_created", "owner_id", "created_at", "id"),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(48))
    trigger: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(24))
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt: Mapped[int] = mapped_column(Integer)
    worker_id: Mapped[str | None] = mapped_column(String(120))
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(64))
    correlation_id: Mapped[str | None] = mapped_column(String(64))


class AssistantTaskReviewFindingRow(Base):
    """One bounded, owner-scoped finding produced by a Task health review."""

    __tablename__ = "assistant_task_review_findings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "owner_id"],
            [f"{SCHEMA}.tasks.id", f"{SCHEMA}.tasks.owner_id"],
            name="fk_task_review_findings_task_owner",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "run_id",
            "task_id",
            "finding_code",
            name="uq_task_review_findings_run_task_code",
        ),
        Index("ix_task_review_findings_owner_state", "owner_id", "state", "updated_at", "id"),
        Index("ix_task_review_findings_owner_task", "owner_id", "task_id", "updated_at", "id"),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.assistant_automation_runs.id", ondelete="CASCADE")
    )
    task_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    finding_code: Mapped[str] = mapped_column(String(48))
    severity: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(24))
    title: Mapped[str] = mapped_column(String(240))
    detail: Mapped[str] = mapped_column(String(1000))
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
