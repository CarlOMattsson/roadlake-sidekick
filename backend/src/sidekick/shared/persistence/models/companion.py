"""Companion pairing, push subscriptions, push outbox and push reminders."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import SCHEMA, Base


class CompanionPairingRow(Base):
    """A single-use, short-lived pairing secret an operator issued for one companion device.

    Only the keyed digest of the secret is stored. `consumed_at` is set exactly once, by the
    exchange that creates the device credential (`device_token_id`).
    """

    __tablename__ = "companion_pairings"
    __table_args__ = (
        Index("ix_companion_pairings_digest", "secret_digest", unique=True),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String(120))
    scopes: Mapped[list[str]] = mapped_column(JSONB)
    secret_digest: Mapped[str] = mapped_column(String(64))
    device_lifetime_days: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    device_token_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.personal_access_tokens.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PushSubscriptionRow(Base):
    """The UnifiedPush endpoint a paired companion device registered.

    At most one active row per pairing (partial unique index). `endpoint` is a capability to push
    to the phone: it is never logged; `endpoint_host` is what logs and metrics may carry.
    """

    __tablename__ = "push_subscriptions"
    __table_args__ = (
        Index(
            "ix_push_subscriptions_active_pairing",
            "pairing_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    pairing_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.companion_pairings.id", ondelete="CASCADE")
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    endpoint: Mapped[str] = mapped_column(Text)
    endpoint_host: Mapped[str] = mapped_column(String(253))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_count: Mapped[int] = mapped_column(Integer, default=0)


class PushOutboxRow(Base):
    """One push still to be sent to a subscription: a `w` (wake) or an `r`
    (reminders to show). It carries no URL and no content; the worker reads the endpoint from the
    subscription at send time. Pending is `delivered_at IS NULL AND next_attempt_at IS NOT NULL`;
    a NULL `next_attempt_at` on an undelivered row means the worker gave up."""

    __tablename__ = "push_outbox"
    __table_args__ = (
        Index(
            "ix_push_outbox_pending_wake",
            "subscription_id",
            unique=True,
            postgresql_where=text(
                "kind = 'w' AND delivered_at IS NULL AND next_attempt_at IS NOT NULL"
            ),
        ),
        Index(
            "ix_push_outbox_reminder_dedup",
            "subscription_id",
            "dedup_key",
            unique=True,
            postgresql_where=text("kind = 'r'"),
        ),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    subscription_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.push_subscriptions.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(1))
    dedup_key: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_kind: Mapped[str | None] = mapped_column(String(32))


class PushReminderRow(Base):
    """What a phone fetches after an `r` push: a morning summary (two counts), a
    due reminder (a Task title snapshot and its `due_at`) or a device test. The content lives only
    here, never in `push_outbox`. `dedup_key` is unique per owner; `acked_at` is set once shown."""

    __tablename__ = "push_reminders"
    __table_args__ = (
        UniqueConstraint("user_id", "dedup_key", name="uq_push_reminders_dedup"),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(7))
    task_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.tasks.id", ondelete="CASCADE")
    )
    dedup_key: Mapped[str] = mapped_column(String(128))
    payload_title: Mapped[str | None] = mapped_column(String(200))
    summary_today: Mapped[int | None] = mapped_column(Integer)
    summary_overdue: Mapped[int | None] = mapped_column(Integer)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
