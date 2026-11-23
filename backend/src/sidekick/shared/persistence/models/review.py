"""Mappings for repetition: the owner's settings, the cards and the log of answers.

The application role can read, insert and update `review_settings`, do all four on `review_cards`,
and only read and insert `review_log` (migration 121): a log row is written once and never changed
or deleted, and leaves only with its card or its owner, through the foreign keys. A card holds no
copy of what it asks about; nothing here is logged.
"""

from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Double,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import SCHEMA, Base


class ReviewSettingsRow(Base):
    """One row per owner, written on first use. Repetition is off until the owner turns it on."""

    __tablename__ = "review_settings"
    __table_args__ = (
        CheckConstraint("new_per_day BETWEEN 0 AND 50", name="ck_review_settings_new_per_day"),
        CheckConstraint(
            "max_reviews_per_day BETWEEN 10 AND 1000", name="ck_review_settings_max_reviews_per_day"
        ),
        CheckConstraint(
            "desired_retention BETWEEN 0.80 AND 0.97", name="ck_review_settings_desired_retention"
        ),
        CheckConstraint("version >= 1", name="ck_review_settings_version"),
        {"schema": SCHEMA},
    )
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    include_contacts: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    include_library: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    new_per_day: Mapped[int] = mapped_column(SmallInteger, default=10, server_default=text("10"))
    max_reviews_per_day: Mapped[int] = mapped_column(
        SmallInteger, default=200, server_default=text("200")
    )
    push_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    push_local_time: Mapped[time] = mapped_column(
        Time, default=time(18, 0), server_default=text("'18:00'")
    )
    desired_retention: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), default=Decimal("0.90"), server_default=text("0.90")
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReviewCardRow(Base):
    """One card per contact (face to name) or per library fact, with its cached schedule.

    The schedule columns are what folding the card's log gives; `scheduler_version` names the rules
    that did it. Exactly the key that matches `source_kind` is set. `library_fact_id` carries no
    foreign key until the table of library facts exists. A card the source no longer supports is
    retired (`retired_at`), not deleted, and comes back with its history if the source returns.
    """

    __tablename__ = "review_cards"
    __table_args__ = (
        ForeignKeyConstraint(
            ["contact_id", "owner_id"],
            [f"{SCHEMA}.contacts.id", f"{SCHEMA}.contacts.owner_id"],
            name="fk_review_cards_contact_owner",
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "owner_id", name="uq_review_cards_id_owner"),
        CheckConstraint(
            "(source_kind = 'contact_face' AND contact_id IS NOT NULL "
            "AND library_fact_id IS NULL) OR (source_kind = 'library_fact' "
            "AND library_fact_id IS NOT NULL AND contact_id IS NULL)",
            name="ck_review_cards_source",
        ),
        CheckConstraint(
            "fsrs_state IN ('new', 'learning', 'review', 'relearning')",
            name="ck_review_cards_fsrs_state",
        ),
        CheckConstraint(
            "(fsrs_state = 'new' AND due_at IS NULL AND stability IS NULL "
            "AND difficulty IS NULL AND step IS NULL) "
            "OR (fsrs_state <> 'new' AND due_at IS NOT NULL)",
            name="ck_review_cards_schedule",
        ),
        CheckConstraint("step IS NULL OR step >= 0", name="ck_review_cards_step"),
        CheckConstraint("reps >= 0 AND lapses >= 0", name="ck_review_cards_counts"),
        CheckConstraint("version >= 1", name="ck_review_cards_version"),
        Index(
            "uq_review_cards_contact",
            "owner_id",
            "contact_id",
            unique=True,
            postgresql_where=text("contact_id IS NOT NULL"),
        ),
        Index(
            "uq_review_cards_library_fact",
            "owner_id",
            "library_fact_id",
            unique=True,
            postgresql_where=text("library_fact_id IS NOT NULL"),
        ),
        Index(
            "ix_review_cards_due",
            "owner_id",
            "due_at",
            postgresql_where=text(
                "due_at IS NOT NULL AND suspended_at IS NULL AND retired_at IS NULL"
            ),
        ),
        Index(
            "ix_review_cards_new",
            "owner_id",
            "created_at",
            "id",
            postgresql_where=text(
                "fsrs_state = 'new' AND suspended_at IS NULL AND retired_at IS NULL"
            ),
        ),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    source_kind: Mapped[str] = mapped_column(String(16))
    contact_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    library_fact_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    fsrs_state: Mapped[str] = mapped_column(String(10), default="new", server_default=text("'new'"))
    step: Mapped[int | None] = mapped_column(SmallInteger)
    stability: Mapped[float | None] = mapped_column(Double)
    difficulty: Mapped[float | None] = mapped_column(Double)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reps: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    lapses: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    introduced_on: Mapped[date | None] = mapped_column(Date)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scheduler_version: Mapped[str] = mapped_column(String(40))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReviewLogRow(Base):
    """One answer; the authority every schedule is folded from. Written once, never changed.

    `reviewed_at` is the owner's answer time (the client's clock, clamped by the application) and
    `received_at` the server's. `client_review_id` makes a replayed answer a no-op.
    """

    __tablename__ = "review_log"
    __table_args__ = (
        ForeignKeyConstraint(
            ["card_id", "owner_id"],
            [f"{SCHEMA}.review_cards.id", f"{SCHEMA}.review_cards.owner_id"],
            name="fk_review_log_card_owner",
            ondelete="CASCADE",
        ),
        UniqueConstraint("card_id", "client_review_id", name="uq_review_log_card_client_review"),
        CheckConstraint("rating BETWEEN 1 AND 4", name="ck_review_log_rating"),
        CheckConstraint("channel IN ('app', 'companion')", name="ck_review_log_channel"),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms BETWEEN 0 AND 600000", name="ck_review_log_duration"
        ),
        CheckConstraint(
            "char_length(client_review_id) BETWEEN 1 AND 64", name="ck_review_log_client_review_id"
        ),
        Index("ix_review_log_owner_reviewed", "owner_id", "reviewed_at"),
        Index("ix_review_log_card_reviewed", "card_id", "reviewed_at"),
        {"schema": SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    card_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    rating: Mapped[int] = mapped_column(SmallInteger)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    client_review_id: Mapped[str] = mapped_column(String(64))
    channel: Mapped[str] = mapped_column(String(10))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    clock_adjusted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
