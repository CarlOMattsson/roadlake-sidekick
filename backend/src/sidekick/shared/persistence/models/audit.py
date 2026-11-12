"""Audit events, domain events, the activity projection and idempotent operations."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import SCHEMA, Base


class AuditEventRow(Base):
    """Sanitized append-only security and mutation record."""

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_occurred", "occurred_at", "id"),
        Index("ix_audit_events_actor", "actor_id", "occurred_at"),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    actor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.users.id", ondelete="SET NULL")
    )
    event: Mapped[str] = mapped_column(String(80))
    outcome: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str | None] = mapped_column(String(80))
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    target_type: Mapped[str | None] = mapped_column(String(40))
    target_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    # The other side of a link change (task, project or contact). No foreign key: audit outlives it.
    related_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    # Who made the change: 'you' (the app) or 'claude' (a model tool); NULL when not recorded.
    source: Mapped[str | None] = mapped_column(String(16))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IdempotencyRow(Base):
    __tablename__ = "idempotency_operations"
    __table_args__ = (
        UniqueConstraint(
            "actor_id", "operation", "idempotency_key", name="uq_idempotency_actor_operation_key"
        ),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    operation: Mapped[str] = mapped_column(String(80))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    payload_hash: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DomainEventRow(Base):
    """Authoritative append-only product event; the Activity Center is a projection."""

    __tablename__ = "domain_events"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "aggregate_type",
            "aggregate_id",
            "aggregate_version",
            name="uq_domain_events_aggregate_version",
        ),
        Index("ix_domain_events_owner_occurred", "owner_id", "occurred_at", "id"),
        Index(
            "ix_domain_events_owner_aggregate",
            "owner_id",
            "aggregate_type",
            "aggregate_id",
            "aggregate_version",
        ),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    aggregate_type: Mapped[str] = mapped_column(String(40))
    aggregate_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    aggregate_version: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(80))
    schema_version: Mapped[int] = mapped_column(Integer)
    actor_type: Mapped[str] = mapped_column(String(24))
    actor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.users.id", ondelete="SET NULL")
    )
    command_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    causation_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    automation_run_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ActivityEntryRow(Base):
    """Bounded owner-facing projection of an authoritative domain event."""

    __tablename__ = "activity_entries"
    __table_args__ = (
        Index("ix_activity_entries_owner_occurred", "owner_id", "occurred_at", "id"),
        Index("ix_activity_entries_owner_category", "owner_id", "category", "occurred_at", "id"),
        Index(
            "ix_activity_entries_owner_target",
            "owner_id",
            "aggregate_type",
            "aggregate_id",
            "occurred_at",
        ),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    domain_event_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.domain_events.id", ondelete="RESTRICT"), unique=True
    )
    category: Mapped[str] = mapped_column(String(48))
    source: Mapped[str] = mapped_column(String(24))
    operation: Mapped[str] = mapped_column(String(80))
    state: Mapped[str] = mapped_column(String(24))
    aggregate_type: Mapped[str] = mapped_column(String(40))
    aggregate_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    summary: Mapped[str] = mapped_column(String(300))
    before_values: Mapped[dict[str, Any]] = mapped_column(JSONB)
    after_values: Mapped[dict[str, Any]] = mapped_column(JSONB)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB)
    policy_mode: Mapped[str | None] = mapped_column(String(24))
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
