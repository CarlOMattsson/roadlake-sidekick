"""Memory-bank sync state, owner memory settings and daily usage counters."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import SCHEMA, Base


class MemorySourceRow(Base):
    """Synchronisation state of one owner record against the memory bank.

    There is deliberately no foreign key to the source record, which can be of several kinds.
    A row outlives a permanent deletion as a tombstone until the worker has removed its
    document from the bank. `doc_key` is the stable Hindsight document identity.
    """

    __tablename__ = "memory_sources"
    __table_args__ = (
        UniqueConstraint("doc_key", name="uq_memory_sources_doc_key"),
        UniqueConstraint("owner_id", "source_kind", "source_id", name="uq_memory_sources_source"),
        Index("ix_memory_sources_due", "status", "next_attempt_at", "id"),
        CheckConstraint(
            "source_kind IN ('journal_entry', 'contact', 'project', 'task')",
            name="ck_memory_sources_kind",
        ),
        CheckConstraint("length(btrim(doc_key)) > 0", name="ck_memory_sources_doc_key"),
        CheckConstraint("fingerprint ~ '^[0-9a-f]{64}$'", name="ck_memory_sources_fingerprint"),
        CheckConstraint("pipeline_version >= 1", name="ck_memory_sources_pipeline_version"),
        CheckConstraint(
            "status IN ('pending', 'submitted', 'retained', 'failed', 'parked')",
            name="ck_memory_sources_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_memory_sources_attempts"),
        CheckConstraint(
            "status <> 'submitted' OR operation_id IS NOT NULL",
            name="ck_memory_sources_submitted",
        ),
        CheckConstraint(
            "status <> 'retained' OR retained_at IS NOT NULL",
            name="ck_memory_sources_retained",
        ),
        CheckConstraint(
            "status NOT IN ('failed', 'parked') OR failure_category IS NOT NULL",
            name="ck_memory_sources_failed",
        ),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    source_kind: Mapped[str] = mapped_column(String(20))
    source_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    doc_key: Mapped[str] = mapped_column(String(128))
    fingerprint: Mapped[str] = mapped_column(CHAR(64))
    pipeline_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    operation_id: Mapped[str | None] = mapped_column(String(200))
    source_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    retained_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_category: Mapped[str | None] = mapped_column(String(40))
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)


class MemorySettingsRow(Base):
    """The owner's memory choice: which domains feed the bank, and the global pause switch.

    The four domains default to on; the owner can still switch each one off.
    """

    __tablename__ = "memory_settings"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_memory_settings_version"),
        {"schema": SCHEMA},
    )
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), primary_key=True
    )
    journal: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    contacts: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    projects: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    tasks: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MemoryUsageDailyRow(Base):
    """Documents and characters sent to the memory bank per owner and day, for the caps."""

    __tablename__ = "memory_usage_daily"
    __table_args__ = (
        PrimaryKeyConstraint("owner_id", "usage_date"),
        CheckConstraint("retain_documents >= 0", name="ck_memory_usage_daily_retain"),
        CheckConstraint("backfill_documents >= 0", name="ck_memory_usage_daily_backfill"),
        CheckConstraint("characters >= 0", name="ck_memory_usage_daily_characters"),
        {"schema": SCHEMA},
    )
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    usage_date: Mapped[date] = mapped_column(Date)
    retain_documents: Mapped[int] = mapped_column(Integer, default=0)
    backfill_documents: Mapped[int] = mapped_column(Integer, default=0)
    characters: Mapped[int] = mapped_column(BigInteger, default=0)
