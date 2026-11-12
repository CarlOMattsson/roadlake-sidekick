"""Domains, processes, projects, tags and saved views."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Computed,
    Date,
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


class DomainRow(Base):
    __tablename__ = "domains"
    __table_args__ = (
        Index("ix_domains_owner_updated", "owner_id", "updated_at", "id"),
        UniqueConstraint("id", "owner_id", name="uq_domains_id_owner"),
        CheckConstraint("status IN ('active', 'archived')", name="ck_domains_status"),
        CheckConstraint(
            "accent IS NULL OR accent IN ('slate', 'blue', 'teal', 'green', 'amber', 'orange', "
            "'rose', 'violet')",
            name="ck_domains_accent",
        ),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer)
    review_cadence: Mapped[str | None] = mapped_column(String(12))
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trashed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accent: Mapped[str | None] = mapped_column(Text)


class ProcessRow(Base):
    __tablename__ = "processes"
    __table_args__ = (
        Index("ix_processes_owner_domain_updated", "owner_id", "domain_id", "updated_at", "id"),
        ForeignKeyConstraint(
            ["domain_id", "owner_id"],
            [f"{SCHEMA}.domains.id", f"{SCHEMA}.domains.owner_id"],
            name="fk_processes_domain_owner",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "owner_id", name="uq_processes_id_owner"),
        CheckConstraint(
            "status IN ('active', 'paused', 'completed', 'archived')",
            name="ck_processes_status",
        ),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    domain_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer)
    cadence: Mapped[str | None] = mapped_column(String(12))
    next_expected_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trashed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProcessRunTemplateRow(Base):
    __tablename__ = "process_run_templates"
    __table_args__ = (
        ForeignKeyConstraint(
            ["process_id", "owner_id"],
            [f"{SCHEMA}.processes.id", f"{SCHEMA}.processes.owner_id"],
            name="fk_process_run_templates_process_owner",
            ondelete="CASCADE",
        ),
        UniqueConstraint("process_id", "owner_id", name="uq_process_run_templates_process_owner"),
        Index("ix_process_run_templates_owner_updated", "owner_id", "updated_at", "id"),
        CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'urgent')",
            name="ck_process_run_templates_priority",
        ),
        CheckConstraint(
            "estimated_minutes IS NULL OR estimated_minutes BETWEEN 1 AND 12000",
            name="ck_process_run_templates_estimate",
        ),
        CheckConstraint(
            "due_after_days BETWEEN 0 AND 365",
            name="ck_process_run_templates_due_after",
        ),
        CheckConstraint("version >= 1", name="ck_process_run_templates_version"),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    process_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(20))
    estimated_minutes: Mapped[int | None] = mapped_column(Integer)
    due_after_days: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    structure: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)


class ProcessRunRow(Base):
    __tablename__ = "process_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["process_id", "owner_id"],
            [f"{SCHEMA}.processes.id", f"{SCHEMA}.processes.owner_id"],
            name="fk_process_runs_process_owner",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["task_id", "owner_id"],
            [f"{SCHEMA}.tasks.id", f"{SCHEMA}.tasks.owner_id"],
            name="fk_process_runs_task_owner",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "owner_id", "process_id", "scheduled_for", name="uq_process_runs_process_schedule"
        ),
        UniqueConstraint("task_id", "owner_id", name="uq_process_runs_task_owner"),
        Index("ix_process_runs_owner_created", "owner_id", "created_at", "id"),
        Index("ix_process_runs_process_scheduled", "owner_id", "process_id", "scheduled_for", "id"),
        CheckConstraint("template_version >= 1", name="ck_process_runs_template_version"),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    process_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    task_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    template_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProcessRunOutboxRow(Base):
    """Durable scheduled-run intent claimed by the Sidekick worker."""

    __tablename__ = "process_run_outbox"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "process_id",
            "scheduled_for",
            name="uq_process_run_outbox_schedule",
        ),
        UniqueConstraint("process_run_id", name="uq_process_run_outbox_process_run"),
        Index("ix_process_run_outbox_due", "status", "scheduled_for", "id"),
        Index("ix_process_run_outbox_owner", "owner_id", "created_at", "id"),
        CheckConstraint(
            "status IN ('queued','processing','delivered','failed')",
            name="ck_process_run_outbox_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_process_run_outbox_attempts"),
        CheckConstraint(
            "status <> 'delivered' OR (processed_at IS NOT NULL AND process_run_id IS NOT NULL)",
            name="ck_process_run_outbox_processed",
        ),
        CheckConstraint(
            "status <> 'processing' OR (worker_id IS NOT NULL AND claimed_at IS NOT NULL)",
            name="ck_process_run_outbox_processing",
        ),
        ForeignKeyConstraint(
            ["process_id", "owner_id"],
            [f"{SCHEMA}.processes.id", f"{SCHEMA}.processes.owner_id"],
            name="fk_process_run_outbox_process_owner",
            ondelete="RESTRICT",
        ),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    process_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String(120))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    process_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.process_runs.id", ondelete="RESTRICT")
    )
    last_error: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProjectRow(Base):
    __tablename__ = "projects"
    __table_args__ = (
        Index("ix_projects_owner_updated", "owner_id", "updated_at", "id"),
        UniqueConstraint("id", "owner_id", name="uq_projects_id_owner"),
        ForeignKeyConstraint(
            ["domain_id", "owner_id"],
            [f"{SCHEMA}.domains.id", f"{SCHEMA}.domains.owner_id"],
            name="fk_projects_domain_owner",
            ondelete="RESTRICT",
        ),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    domain_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))
    start_date: Mapped[date | None] = mapped_column(Date)
    target_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer)
    definition_of_done: Mapped[str | None] = mapped_column(Text)
    trashed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('simple', coalesce(title, '')), 'A') || "
            "setweight(to_tsvector('swedish', coalesce(description, '')), 'B')",
            persisted=True,
        ),
    )


class WorkTagRow(Base):
    """Owner-scoped tag vocabulary: normalized `slug` matches, `label` is displayed."""

    __tablename__ = "work_tags"
    __table_args__ = (
        UniqueConstraint("id", "owner_id", name="uq_work_tags_id_owner"),
        UniqueConstraint("owner_id", "slug", name="uq_work_tags_owner_slug"),
        Index("ix_work_tags_owner_label", "owner_id", "label", "id"),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    slug: Mapped[str] = mapped_column(String(60))
    label: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer)


class DomainTagRow(Base):
    __tablename__ = "domain_tags"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tag_id", "owner_id"],
            [f"{SCHEMA}.work_tags.id", f"{SCHEMA}.work_tags.owner_id"],
            name="fk_domain_tags_tag_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["domain_id", "owner_id"],
            [f"{SCHEMA}.domains.id", f"{SCHEMA}.domains.owner_id"],
            name="fk_domain_tags_target_owner",
            ondelete="CASCADE",
        ),
        Index("ix_domain_tags_reverse", "owner_id", "domain_id", "tag_id"),
        {"schema": SCHEMA},
    )
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    domain_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProcessTagRow(Base):
    __tablename__ = "process_tags"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tag_id", "owner_id"],
            [f"{SCHEMA}.work_tags.id", f"{SCHEMA}.work_tags.owner_id"],
            name="fk_process_tags_tag_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["process_id", "owner_id"],
            [f"{SCHEMA}.processes.id", f"{SCHEMA}.processes.owner_id"],
            name="fk_process_tags_target_owner",
            ondelete="CASCADE",
        ),
        Index("ix_process_tags_reverse", "owner_id", "process_id", "tag_id"),
        {"schema": SCHEMA},
    )
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    process_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProjectTagRow(Base):
    __tablename__ = "project_tags"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tag_id", "owner_id"],
            [f"{SCHEMA}.work_tags.id", f"{SCHEMA}.work_tags.owner_id"],
            name="fk_project_tags_tag_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["project_id", "owner_id"],
            [f"{SCHEMA}.projects.id", f"{SCHEMA}.projects.owner_id"],
            name="fk_project_tags_target_owner",
            ondelete="CASCADE",
        ),
        Index("ix_project_tags_reverse", "owner_id", "project_id", "tag_id"),
        {"schema": SCHEMA},
    )
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TaskTagRow(Base):
    __tablename__ = "task_tags"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tag_id", "owner_id"],
            [f"{SCHEMA}.work_tags.id", f"{SCHEMA}.work_tags.owner_id"],
            name="fk_task_tags_tag_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["task_id", "owner_id"],
            [f"{SCHEMA}.tasks.id", f"{SCHEMA}.tasks.owner_id"],
            name="fk_task_tags_target_owner",
            ondelete="CASCADE",
        ),
        Index("ix_task_tags_reverse", "owner_id", "task_id", "tag_id"),
        {"schema": SCHEMA},
    )
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    task_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SavedViewRow(Base):
    __tablename__ = "saved_work_views"
    __table_args__ = (
        UniqueConstraint("id", "owner_id", name="uq_saved_work_views_id_owner"),
        Index("ix_saved_work_views_owner_name", "owner_id", "name", "id"),
        CheckConstraint("octet_length(definition::text) <= 8192", name="ck_saved_work_views_size"),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
