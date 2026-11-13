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
    ForeignKeyConstraint,
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
        UniqueConstraint("id", "owner_id", name="uq_memory_sources_id_owner"),
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
        CheckConstraint(
            "forget_salt IS NULL OR forget_salt ~ '^[0-9a-f]{32}$'",
            name="ck_memory_settings_forget_salt",
        ),
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
    #: 16 random bytes as lower-case hex: the salt of this owner's forgotten-statement keys. NULL
    #: until the owner first asks Sidekick to forget a statement.
    forget_salt: Mapped[str | None] = mapped_column(CHAR(32))
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


class MemoryForgottenFactRow(Base):
    """One statement the owner asked Sidekick to stop using. The statement itself is never stored.

    `text_key` is the salted digest from `sidekick.memory.forgetting`. `released_at` is NULL while
    the statement is forgotten and set when the owner takes it back.
    """

    __tablename__ = "memory_forgotten_facts"
    __table_args__ = (
        UniqueConstraint("id", "owner_id", name="uq_memory_forgotten_facts_id_owner"),
        UniqueConstraint("owner_id", "text_key", name="uq_memory_forgotten_facts_key"),
        CheckConstraint("text_key ~ '^[0-9a-f]{64}$'", name="ck_memory_forgotten_facts_text_key"),
        ForeignKeyConstraint(
            ["origin_source_id", "owner_id"],
            [f"{SCHEMA}.memory_sources.id", f"{SCHEMA}.memory_sources.owner_id"],
            name="fk_memory_forgotten_facts_origin_owner",
            ondelete="SET NULL (origin_source_id)",
        ),
        CheckConstraint(
            "released_at IS NULL OR released_at >= created_at",
            name="ck_memory_forgotten_facts_released",
        ),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    text_key: Mapped[str] = mapped_column(CHAR(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    origin_source_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))


class MemoryForgottenUnitRow(Base):
    """A provider fact id that carries a forgotten statement, and where hiding it stands.

    The table is also the reconcile pass's queue. A unit shares its owner with the statement and
    the source row (composite keys).
    """

    __tablename__ = "memory_forgotten_units"
    __table_args__ = (
        UniqueConstraint(
            "memory_source_id", "provider_fact_id", name="uq_memory_forgotten_units_fact"
        ),
        Index("ix_memory_forgotten_units_due", "state", "next_attempt_at", "id"),
        Index("ix_memory_forgotten_units_fact", "forgotten_id"),
        ForeignKeyConstraint(
            ["forgotten_id", "owner_id"],
            [f"{SCHEMA}.memory_forgotten_facts.id", f"{SCHEMA}.memory_forgotten_facts.owner_id"],
            name="fk_memory_forgotten_units_fact_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["memory_source_id", "owner_id"],
            [f"{SCHEMA}.memory_sources.id", f"{SCHEMA}.memory_sources.owner_id"],
            name="fk_memory_forgotten_units_source_owner",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "length(btrim(provider_fact_id)) > 0", name="ck_memory_forgotten_units_provider_fact_id"
        ),
        CheckConstraint(
            "state IN ('pending', 'invalidated', 'reverting', 'parked')",
            name="ck_memory_forgotten_units_state",
        ),
        CheckConstraint("attempts >= 0", name="ck_memory_forgotten_units_attempts"),
        CheckConstraint(
            "state <> 'parked' OR failure_category IS NOT NULL",
            name="ck_memory_forgotten_units_parked",
        ),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    forgotten_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    memory_source_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    provider_fact_id: Mapped[str] = mapped_column(String(200))
    state: Mapped[str] = mapped_column(String(12))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_category: Mapped[str | None] = mapped_column(String(40))
