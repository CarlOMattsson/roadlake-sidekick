"""Mappings for automations: the registry, its runs, the facts and suggestions they produce.

The application role can read, insert and update these tables and delete nothing (migration 116);
`AutomationCheckRow` is append-only, so it has no UPDATE either. Text columns are the owner's data,
or text written by an AI that is untrusted, and are never logged.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import SCHEMA, Base


class AutomationRow(Base):
    """An automation the owner defined; never a Task, and archived rather than erased.

    `spec_digest` is the SHA-256 over the canonical JSON of the definition: `purpose`,
    `instruction`, `sources`, `runner`, `cadence`, `allowed_effects`, `apply_mode`, `auto_effects`,
    `bulk_threshold`, `auto_threshold`, `max_suggestions_per_run`, `run_budget_microusd` and
    `model_tier`, but not the title or the state. The application computes it. An automation may run
    only while its state is `active` and `approved_digest` equals `spec_digest`, so changing any of
    those fields, `model_tier` included, takes the approval away.
    """

    __tablename__ = "automations"
    __table_args__ = (
        UniqueConstraint("id", "owner_id", name="uq_automations_id_owner"),
        Index("ix_automations_owner_state", "owner_id", "state"),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(120))
    purpose: Mapped[str] = mapped_column(String(300))
    instruction: Mapped[str] = mapped_column(Text)
    sources: Mapped[list[str]] = mapped_column(ARRAY(String(16)), default=list)
    runner: Mapped[str] = mapped_column(String(12))
    cadence: Mapped[dict[str, Any]] = mapped_column(JSONB(none_as_null=True))
    allowed_effects: Mapped[list[str]] = mapped_column(ARRAY(String(32)), default=list)
    apply_mode: Mapped[str] = mapped_column(String(16), default="suggest")
    auto_effects: Mapped[list[str]] = mapped_column(ARRAY(String(32)), default=list)
    bulk_threshold: Mapped[int] = mapped_column(SmallInteger, default=90)
    auto_threshold: Mapped[int] = mapped_column(SmallInteger, default=95)
    max_suggestions_per_run: Mapped[int] = mapped_column(SmallInteger, default=15)
    run_budget_microusd: Mapped[int] = mapped_column(BigInteger, default=1_000_000)
    model_tier: Mapped[str] = mapped_column(String(12), default="standard")
    state: Mapped[str] = mapped_column(String(12), default="draft")
    spec_digest: Mapped[str] = mapped_column(CHAR(64))
    approved_digest: Mapped[str | None] = mapped_column(CHAR(64))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AutomationRunRow(Base):
    """One attempt at one occurrence of an automation; also the queue of the server runner.

    At most one attempt per `(automation_id, occurrence_key)` is active at a time. `summary` is
    written by the AI and is untrusted. Cost columns follow `AiStepRunRow`.
    """

    __tablename__ = "automation_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["automation_id", "owner_id"],
            [f"{SCHEMA}.automations.id", f"{SCHEMA}.automations.owner_id"],
            name="fk_automation_runs_automation_owner",
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "owner_id", name="uq_automation_runs_id_owner"),
        UniqueConstraint(
            "id", "automation_id", "owner_id", name="uq_automation_runs_id_automation_owner"
        ),
        UniqueConstraint(
            "automation_id",
            "occurrence_key",
            "attempt",
            name="uq_automation_runs_occurrence_attempt",
        ),
        Index(
            "uq_automation_runs_one_active",
            "automation_id",
            "occurrence_key",
            unique=True,
            postgresql_where=text("state IN ('queued', 'running', 'checking')"),
        ),
        Index("ix_automation_runs_owner_state", "owner_id", "state"),
        Index("ix_automation_runs_owner_created", "owner_id", "created_at"),
        Index("ix_automation_runs_automation", "automation_id", "created_at"),
        Index(
            "ix_automation_runs_server_queue",
            "lease_until",
            postgresql_where=text(
                "runner = 'server' AND (state IN ('queued', 'running', 'checking') "
                "OR reserved_microusd > 0)"
            ),
        ),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    automation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    occurrence_key: Mapped[str] = mapped_column(String(40))
    attempt: Mapped[int] = mapped_column(Integer)
    runner: Mapped[str] = mapped_column(String(12))
    state: Mapped[str] = mapped_column(String(12))
    stage: Mapped[str | None] = mapped_column(String(10))
    spec_digest: Mapped[str] = mapped_column(CHAR(64))
    session_digest: Mapped[str | None] = mapped_column(CHAR(64))
    credential_kind: Mapped[str] = mapped_column(String(12))
    worker_id: Mapped[str | None] = mapped_column(String(80))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    datapoint_count: Mapped[int] = mapped_column(Integer, default=0)
    suggestion_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0)
    flagged_count: Mapped[int] = mapped_column(Integer, default=0)
    auto_applied_count: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str | None] = mapped_column(String(300))
    outcome: Mapped[str | None] = mapped_column(String(16))
    model: Mapped[str | None] = mapped_column(String(120))
    checker_model: Mapped[str | None] = mapped_column(String(120))
    input_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    reserved_microusd: Mapped[int] = mapped_column(BigInteger, default=0)
    cost_microusd: Mapped[int] = mapped_column(BigInteger, default=0)
    cost_source: Mapped[str] = mapped_column(String(16), default="none")
    version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AutomationDatapointRow(Base):
    """A fact a run read: never an action. A purge sets `fields` and `purged_at`; rows stay.

    `source_fingerprint` is a keyed hash of the client's source reference; the reference itself is
    never stored. `source_label` is untrusted text and is shown escaped.
    """

    __tablename__ = "automation_datapoints"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "automation_id", "owner_id"],
            [
                f"{SCHEMA}.automation_runs.id",
                f"{SCHEMA}.automation_runs.automation_id",
                f"{SCHEMA}.automation_runs.owner_id",
            ],
            name="fk_automation_datapoints_run_automation_owner",
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "owner_id", name="uq_automation_datapoints_id_owner"),
        Index("ix_automation_datapoints_run", "run_id"),
        Index(
            "ix_automation_datapoints_purge",
            "purge_after",
            postgresql_where=text("purged_at IS NULL"),
        ),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    automation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(16))
    fields: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    source_kind: Mapped[str] = mapped_column(String(12))
    source_fingerprint: Mapped[str] = mapped_column(CHAR(64))
    source_label: Mapped[str | None] = mapped_column(String(160))
    source_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    purge_after: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AutomationSuggestionRow(Base):
    """A decision card drafted from datapoints. `rationale` is untrusted and shown escaped.

    `payload` holds the owner's edits and `proposed_payload` what was proposed; both are NULL, with
    `payload_purged_at` set, after the retention period. `confidence` comes only from the
    independent checker. `dedupe_fingerprint` is unique per automation across every state, so a
    dismissed suggestion is never proposed again.
    """

    __tablename__ = "automation_suggestions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "automation_id", "owner_id"],
            [
                f"{SCHEMA}.automation_runs.id",
                f"{SCHEMA}.automation_runs.automation_id",
                f"{SCHEMA}.automation_runs.owner_id",
            ],
            name="fk_automation_suggestions_run_automation_owner",
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "owner_id", name="uq_automation_suggestions_id_owner"),
        UniqueConstraint(
            "automation_id", "dedupe_fingerprint", name="uq_automation_suggestions_dedupe"
        ),
        Index("ix_automation_suggestions_owner_state", "owner_id", "state", "bulk_eligible"),
        Index("ix_automation_suggestions_run", "run_id"),
        Index(
            "ix_automation_suggestions_pending_expiry",
            "expires_at",
            postgresql_where=text("state = 'pending'"),
        ),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    automation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    effect: Mapped[str] = mapped_column(String(32))
    effect_version: Mapped[int] = mapped_column(SmallInteger)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    proposed_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    rationale: Mapped[str | None] = mapped_column(String(300))
    datapoint_ids: Mapped[list[UUID]] = mapped_column(ARRAY(PGUUID(as_uuid=True)), default=list)
    dedupe_fingerprint: Mapped[str] = mapped_column(CHAR(64))
    state: Mapped[str] = mapped_column(String(12))
    screening_flags: Mapped[list[str]] = mapped_column(ARRAY(String(32)), default=list)
    check_state: Mapped[str] = mapped_column(String(12), default="off")
    verdict: Mapped[str | None] = mapped_column(String(12))
    confidence: Mapped[int | None] = mapped_column(SmallInteger)
    bulk_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[str | None] = mapped_column(String(8))
    decision_channel: Mapped[str | None] = mapped_column(String(12))
    applied_kind: Mapped[str | None] = mapped_column(String(24))
    applied_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    applied_version: Mapped[int | None] = mapped_column(Integer)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    apply_error: Mapped[str | None] = mapped_column(String(24))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload_purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AutomationCheckRow(Base):
    """One attempt of the independent check of a suggestion; append-only.

    The checker returns codes from a closed set and no free text, so nothing here can carry an
    instruction back to the owner's screen. The cost of a check is booked on the run.
    """

    __tablename__ = "automation_checks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["suggestion_id", "owner_id"],
            [f"{SCHEMA}.automation_suggestions.id", f"{SCHEMA}.automation_suggestions.owner_id"],
            name="fk_automation_checks_suggestion_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["run_id", "owner_id"],
            [f"{SCHEMA}.automation_runs.id", f"{SCHEMA}.automation_runs.owner_id"],
            name="fk_automation_checks_run_owner",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "suggestion_id", "attempt", name="uq_automation_checks_suggestion_attempt"
        ),
        Index("ix_automation_checks_run", "run_id"),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    suggestion_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer)
    checker: Mapped[str] = mapped_column(String(16))
    model: Mapped[str] = mapped_column(String(120))
    verdict: Mapped[str] = mapped_column(String(12))
    confidence: Mapped[int | None] = mapped_column(SmallInteger)
    reason_codes: Mapped[list[str]] = mapped_column(ARRAY(String(32)), default=list)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AutomationReportCursorRow(Base):
    """The instant up to which the owner has seen the automation report."""

    __tablename__ = "automation_report_cursors"
    __table_args__ = ({"schema": SCHEMA},)
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), primary_key=True
    )
    seen_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
