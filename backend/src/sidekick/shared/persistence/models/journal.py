"""Journal sources, processing runs, drafts, entries and daily summaries."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import SCHEMA, Base


class JournalSourceRow(Base):
    __tablename__ = "journal_sources"
    __table_args__ = (
        Index("ix_journal_sources_timeline", "owner_id", "journal_date", "created_at", "id"),
        Index("ix_journal_sources_replacement", "owner_id", "replaces_source_id"),
        CheckConstraint(
            "source_type IN ('manual_text', 'transcript_text')",
            name="ck_journal_sources_type",
        ),
        CheckConstraint(
            "length(raw_text) BETWEEN 1 AND 100000 AND length(btrim(raw_text)) > 0",
            name="ck_journal_sources_raw_text",
        ),
        CheckConstraint(
            "content_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_journal_sources_fingerprint",
        ),
        CheckConstraint(
            "language IS NULL OR length(language) BETWEEN 2 AND 35",
            name="ck_journal_sources_language",
        ),
        CheckConstraint(
            "replaces_source_id IS NULL OR replaces_source_id <> id",
            name="ck_journal_sources_not_self_replacement",
        ),
        ForeignKeyConstraint(
            ["replaces_source_id", "owner_id"],
            [f"{SCHEMA}.journal_sources.id", f"{SCHEMA}.journal_sources.owner_id"],
            name="fk_journal_sources_replacement_owner",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "owner_id", name="uq_journal_sources_id_owner"),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    source_type: Mapped[str] = mapped_column(String(24))
    journal_date: Mapped[date] = mapped_column(Date)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_text: Mapped[str] = mapped_column(Text)
    content_fingerprint: Mapped[str] = mapped_column(CHAR(64))
    language: Mapped[str | None] = mapped_column(String(35))
    replaces_source_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    trashed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed("setweight(to_tsvector('swedish', coalesce(raw_text, '')), 'C')", persisted=True),
    )
    entries: Mapped[list["JournalEntryRow"]] = relationship(
        back_populates="source",
        foreign_keys="[JournalEntryRow.source_id, JournalEntryRow.owner_id]",
    )
    drafts: Mapped[list["JournalDraftRow"]] = relationship(
        back_populates="source",
        foreign_keys="[JournalDraftRow.source_id, JournalDraftRow.owner_id]",
    )


class JournalProcessingRunRow(Base):
    __tablename__ = "journal_processing_runs"
    __table_args__ = (
        Index(
            "ix_journal_processing_runs_owner_operation",
            "owner_id",
            "operation",
            "journal_date",
            "created_at",
            "id",
        ),
        Index("ix_journal_processing_runs_source", "owner_id", "source_id", "created_at", "id"),
        CheckConstraint(
            "operation IN ('entry_draft', 'daily_summary')",
            name="ck_journal_processing_runs_operation",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name="ck_journal_processing_runs_status",
        ),
        CheckConstraint("length(btrim(provider)) > 0", name="ck_journal_processing_runs_provider"),
        CheckConstraint("length(btrim(model_id)) > 0", name="ck_journal_processing_runs_model"),
        CheckConstraint(
            "length(btrim(prompt_version)) > 0",
            name="ck_journal_processing_runs_prompt_version",
        ),
        CheckConstraint(
            "length(btrim(schema_version)) > 0",
            name="ck_journal_processing_runs_schema_version",
        ),
        CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name="ck_journal_processing_runs_input_tokens",
        ),
        CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="ck_journal_processing_runs_output_tokens",
        ),
        CheckConstraint(
            "input_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_journal_processing_runs_fingerprint",
        ),
        CheckConstraint(
            "jsonb_typeof(candidate_catalog) = 'object'",
            name="ck_journal_processing_runs_catalog",
        ),
        CheckConstraint(
            "failure_category IS NULL OR failure_category IN "
            "('provider_configuration', 'provider_timeout', 'provider_unavailable', "
            "'model_unavailable', 'invalid_provider_response', 'invalid_model_output')",
            name="ck_journal_processing_runs_failure",
        ),
        CheckConstraint(
            "attempt_count BETWEEN 1 AND 100",
            name="ck_journal_processing_runs_attempt_count",
        ),
        CheckConstraint(
            "(operation = 'entry_draft' AND source_id IS NOT NULL) OR "
            "(operation = 'daily_summary' AND source_id IS NULL)",
            name="ck_journal_processing_runs_source_operation",
        ),
        CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name="ck_journal_processing_runs_timing",
        ),
        ForeignKeyConstraint(
            ["source_id", "owner_id"],
            [f"{SCHEMA}.journal_sources.id", f"{SCHEMA}.journal_sources.owner_id"],
            name="fk_journal_processing_runs_source_owner",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "owner_id", name="uq_journal_processing_runs_id_owner"),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    source_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    operation: Mapped[str] = mapped_column(String(24))
    journal_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16))
    provider: Mapped[str] = mapped_column(String(64))
    model_id: Mapped[str] = mapped_column(String(200))
    prompt_version: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[str] = mapped_column(String(64))
    input_fingerprint: Mapped[str] = mapped_column(CHAR(64))
    candidate_catalog: Mapped[dict[str, Any]] = mapped_column(JSONB)
    provider_response_id: Mapped[str | None] = mapped_column(String(200))
    failure_category: Mapped[str | None] = mapped_column(String(40))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class JournalDraftRow(Base):
    __tablename__ = "journal_drafts"
    __table_args__ = (
        Index("ix_journal_drafts_source", "owner_id", "source_id", "created_at", "id"),
        CheckConstraint(
            "state IN ('pending_review', 'finalized', 'rejected', 'superseded')",
            name="ck_journal_drafts_state",
        ),
        CheckConstraint("length(btrim(title)) > 0", name="ck_journal_drafts_title"),
        CheckConstraint(
            "summary IS NULL OR length(summary) <= 10000", name="ck_journal_drafts_summary"
        ),
        CheckConstraint(
            "jsonb_typeof(key_points) = 'array' AND jsonb_array_length(key_points) <= 50",
            name="ck_journal_drafts_key_points",
        ),
        CheckConstraint(
            "jsonb_typeof(relation_suggestions) = 'object'",
            name="ck_journal_drafts_relation_suggestions",
        ),
        CheckConstraint(
            "jsonb_typeof(task_proposals) = 'array' AND jsonb_array_length(task_proposals) <= 20",
            name="ck_journal_drafts_task_proposals",
        ),
        CheckConstraint("version >= 1", name="ck_journal_drafts_version"),
        ForeignKeyConstraint(
            ["source_id", "owner_id"],
            [f"{SCHEMA}.journal_sources.id", f"{SCHEMA}.journal_sources.owner_id"],
            name="fk_journal_drafts_source_owner",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["processing_run_id", "owner_id"],
            [f"{SCHEMA}.journal_processing_runs.id", f"{SCHEMA}.journal_processing_runs.owner_id"],
            name="fk_journal_drafts_processing_run_owner",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["catalog_run_id", "owner_id"],
            [f"{SCHEMA}.journal_processing_runs.id", f"{SCHEMA}.journal_processing_runs.owner_id"],
            name="fk_journal_drafts_catalog_run_owner",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "owner_id", name="uq_journal_drafts_id_owner"),
        UniqueConstraint("processing_run_id", name="uq_journal_drafts_processing_run"),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    source_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    processing_run_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    catalog_run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    state: Mapped[str] = mapped_column(String(24))
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str | None] = mapped_column(Text)
    key_points: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    relation_suggestions: Mapped[dict[str, Any]] = mapped_column(JSONB)
    task_proposals: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lifecycle_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[JournalSourceRow] = relationship(
        back_populates="drafts",
        foreign_keys=[source_id, owner_id],
    )


class JournalSummaryProposalRow(Base):
    __tablename__ = "journal_summary_proposals"
    __table_args__ = (
        Index("ix_journal_summary_proposals_day", "owner_id", "journal_date", "created_at", "id"),
        CheckConstraint(
            "entry_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_journal_summary_proposals_fingerprint",
        ),
        CheckConstraint(
            "jsonb_typeof(content) = 'object'", name="ck_journal_summary_proposals_content"
        ),
        CheckConstraint(
            "state IN ('pending_review', 'accepted', 'rejected', 'superseded')",
            name="ck_journal_summary_proposals_state",
        ),
        CheckConstraint("version >= 1", name="ck_journal_summary_proposals_version"),
        ForeignKeyConstraint(
            ["run_id", "owner_id"],
            [f"{SCHEMA}.journal_processing_runs.id", f"{SCHEMA}.journal_processing_runs.owner_id"],
            name="fk_journal_summary_proposals_run_owner",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "owner_id", name="uq_journal_summary_proposals_id_owner"),
        UniqueConstraint("run_id", name="uq_journal_summary_proposals_run"),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    journal_date: Mapped[date] = mapped_column(Date)
    entry_fingerprint: Mapped[str] = mapped_column(CHAR(64))
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(String(24))
    version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lifecycle_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JournalEntryRow(Base):
    __tablename__ = "journal_entries"
    __table_args__ = (
        Index(
            "ix_journal_entries_timeline",
            "owner_id",
            "journal_date",
            "archived_at",
            "occurred_at",
            "created_at",
            "id",
        ),
        Index("ix_journal_entries_source", "owner_id", "source_id"),
        CheckConstraint("length(btrim(title)) > 0", name="ck_journal_entries_title"),
        CheckConstraint(
            "summary IS NULL OR length(summary) <= 10000", name="ck_journal_entries_summary"
        ),
        CheckConstraint(
            "jsonb_typeof(key_points) = 'array' AND jsonb_array_length(key_points) <= 50",
            name="ck_journal_entries_key_points",
        ),
        CheckConstraint("version >= 1", name="ck_journal_entries_version"),
        CheckConstraint(
            "archived_at IS NULL OR archived_at >= created_at", name="ck_journal_entries_archive"
        ),
        ForeignKeyConstraint(
            ["source_id", "owner_id"],
            [f"{SCHEMA}.journal_sources.id", f"{SCHEMA}.journal_sources.owner_id"],
            name="fk_journal_entries_source_owner",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "owner_id", name="uq_journal_entries_id_owner"),
        UniqueConstraint("owner_id", "source_id", name="uq_journal_entries_owner_source"),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    source_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    journal_date: Mapped[date] = mapped_column(Date)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str | None] = mapped_column(Text)
    key_points: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trashed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('simple', coalesce(title, '')), 'A') || "
            "setweight(to_tsvector('swedish', coalesce(summary, '')), 'B')",
            persisted=True,
        ),
    )
    source: Mapped[JournalSourceRow] = relationship(
        back_populates="entries",
        foreign_keys=[source_id, owner_id],
    )
    projects: Mapped[list["JournalEntryProjectRow"]] = relationship(
        back_populates="entry", cascade="all, delete-orphan"
    )
    tasks: Mapped[list["JournalEntryTaskRow"]] = relationship(
        back_populates="entry", cascade="all, delete-orphan"
    )
    contacts: Mapped[list["JournalEntryContactRow"]] = relationship(
        back_populates="entry", cascade="all, delete-orphan"
    )


class JournalEntryProjectRow(Base):
    __tablename__ = "journal_entry_projects"
    __table_args__ = (
        Index("ix_journal_entry_projects_reverse", "owner_id", "project_id", "entry_id"),
        PrimaryKeyConstraint("owner_id", "entry_id", "project_id"),
        ForeignKeyConstraint(
            ["entry_id", "owner_id"],
            [f"{SCHEMA}.journal_entries.id", f"{SCHEMA}.journal_entries.owner_id"],
            name="fk_journal_entry_projects_entry",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["project_id", "owner_id"],
            [f"{SCHEMA}.projects.id", f"{SCHEMA}.projects.owner_id"],
            name="fk_journal_entry_projects_project",
            ondelete="RESTRICT",
        ),
        {"schema": SCHEMA},
    )
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    entry_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    entry: Mapped[JournalEntryRow] = relationship(back_populates="projects")


class JournalEntryTaskRow(Base):
    __tablename__ = "journal_entry_tasks"
    __table_args__ = (
        Index("ix_journal_entry_tasks_reverse", "owner_id", "task_id", "entry_id"),
        PrimaryKeyConstraint("owner_id", "entry_id", "task_id"),
        ForeignKeyConstraint(
            ["entry_id", "owner_id"],
            [f"{SCHEMA}.journal_entries.id", f"{SCHEMA}.journal_entries.owner_id"],
            name="fk_journal_entry_tasks_entry",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["task_id", "owner_id"],
            [f"{SCHEMA}.tasks.id", f"{SCHEMA}.tasks.owner_id"],
            name="fk_journal_entry_tasks_task",
            ondelete="RESTRICT",
        ),
        {"schema": SCHEMA},
    )
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    entry_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    task_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    entry: Mapped[JournalEntryRow] = relationship(back_populates="tasks")


class JournalEntryContactRow(Base):
    __tablename__ = "journal_entry_contacts"
    __table_args__ = (
        Index("ix_journal_entry_contacts_reverse", "owner_id", "contact_id", "entry_id"),
        PrimaryKeyConstraint("owner_id", "entry_id", "contact_id"),
        ForeignKeyConstraint(
            ["entry_id", "owner_id"],
            [f"{SCHEMA}.journal_entries.id", f"{SCHEMA}.journal_entries.owner_id"],
            name="fk_journal_entry_contacts_entry",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["contact_id", "owner_id"],
            [f"{SCHEMA}.contacts.id", f"{SCHEMA}.contacts.owner_id"],
            name="fk_journal_entry_contacts_contact",
            ondelete="RESTRICT",
        ),
        {"schema": SCHEMA},
    )
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    entry_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    contact_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    entry: Mapped[JournalEntryRow] = relationship(back_populates="contacts")


class JournalEntryTagRow(Base):
    """A link from a Journal entry to a tag of the owner's vocabulary (`work_tags`)."""

    __tablename__ = "journal_entry_tags"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tag_id", "owner_id"],
            [f"{SCHEMA}.work_tags.id", f"{SCHEMA}.work_tags.owner_id"],
            name="fk_journal_entry_tags_tag_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["journal_entry_id", "owner_id"],
            [f"{SCHEMA}.journal_entries.id", f"{SCHEMA}.journal_entries.owner_id"],
            name="fk_journal_entry_tags_target_owner",
            ondelete="CASCADE",
        ),
        Index("ix_journal_entry_tags_reverse", "owner_id", "journal_entry_id", "tag_id"),
        {"schema": SCHEMA},
    )
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    journal_entry_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DailyJournalSummaryRow(Base):
    __tablename__ = "daily_journal_summaries"
    __table_args__ = (
        CheckConstraint(
            "origin IN ('manual', 'ai_assisted')", name="ck_daily_journal_summaries_origin"
        ),
        CheckConstraint("status IN ('current', 'stale')", name="ck_daily_journal_summaries_status"),
        CheckConstraint(
            "length(overview) BETWEEN 1 AND 20000 AND length(btrim(overview)) > 0",
            name="ck_daily_journal_summaries_overview",
        ),
        CheckConstraint(
            "jsonb_typeof(content) = 'object'", name="ck_daily_journal_summaries_content"
        ),
        CheckConstraint(
            "source_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_daily_journal_summaries_fingerprint",
        ),
        CheckConstraint("version >= 1", name="ck_daily_journal_summaries_version"),
        CheckConstraint(
            "(origin = 'manual' AND processing_run_id IS NULL AND accepted_proposal_id IS NULL) "
            "OR (origin = 'ai_assisted' AND processing_run_id IS NOT NULL "
            "AND accepted_proposal_id IS NOT NULL)",
            name="ck_daily_journal_summaries_origin_provenance",
        ),
        ForeignKeyConstraint(
            ["processing_run_id", "owner_id"],
            [f"{SCHEMA}.journal_processing_runs.id", f"{SCHEMA}.journal_processing_runs.owner_id"],
            name="fk_daily_journal_summaries_run_owner",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["accepted_proposal_id", "owner_id"],
            [
                f"{SCHEMA}.journal_summary_proposals.id",
                f"{SCHEMA}.journal_summary_proposals.owner_id",
            ],
            name="fk_daily_journal_summaries_proposal_owner",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "owner_id", name="uq_daily_journal_summaries_id_owner"),
        UniqueConstraint("owner_id", "journal_date", name="uq_daily_journal_summaries_owner_date"),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    journal_date: Mapped[date] = mapped_column(Date)
    origin: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(16))
    overview: Mapped[str] = mapped_column(Text)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)
    source_fingerprint: Mapped[str] = mapped_column(CHAR(64))
    processing_run_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    accepted_proposal_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    version: Mapped[int] = mapped_column(Integer)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    manual_edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provenance_entries: Mapped[list["DailyJournalSummaryEntryRow"]] = relationship(
        back_populates="summary", cascade="all, delete-orphan"
    )


class DailyJournalSummaryEntryRow(Base):
    __tablename__ = "daily_journal_summary_entries"
    __table_args__ = (
        Index("ix_daily_journal_summary_entries_entry", "owner_id", "entry_id", "summary_id"),
        PrimaryKeyConstraint("owner_id", "summary_id", "entry_id"),
        CheckConstraint("entry_version >= 1", name="ck_daily_journal_summary_entries_version"),
        CheckConstraint("ordinal >= 0", name="ck_daily_journal_summary_entries_ordinal"),
        UniqueConstraint(
            "owner_id",
            "summary_id",
            "ordinal",
            name="uq_daily_journal_summary_entries_ordinal",
        ),
        ForeignKeyConstraint(
            ["summary_id", "owner_id"],
            [f"{SCHEMA}.daily_journal_summaries.id", f"{SCHEMA}.daily_journal_summaries.owner_id"],
            name="fk_daily_journal_summary_entries_summary",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["entry_id", "owner_id"],
            [f"{SCHEMA}.journal_entries.id", f"{SCHEMA}.journal_entries.owner_id"],
            name="fk_daily_journal_summary_entries_entry",
            ondelete="RESTRICT",
        ),
        {"schema": SCHEMA},
    )
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    summary_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    entry_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    entry_version: Mapped[int] = mapped_column(Integer)
    ordinal: Mapped[int] = mapped_column(Integer)
    summary: Mapped[DailyJournalSummaryRow] = relationship(back_populates="provenance_entries")
