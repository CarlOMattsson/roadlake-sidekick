"""The instance license record."""

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, SmallInteger, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import SCHEMA, Base


class InstanceLicenseRow(Base):
    """The instance's one license record (D-081): the signed key the owner entered
    and the highest UTC date seen, which the expiry check uses so a turned-back clock revives
    nothing. A single row (`id = 1`); no owner, because the key belongs to the installation."""

    __tablename__ = "instance_license"
    __table_args__ = (
        CheckConstraint("id = 1", name="instance_license_id_check"),
        {"schema": SCHEMA},
    )
    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    license_key: Mapped[str | None] = mapped_column(Text)
    max_seen_on: Mapped[date] = mapped_column(Date)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
