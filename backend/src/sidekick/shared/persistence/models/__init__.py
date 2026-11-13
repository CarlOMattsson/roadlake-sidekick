"""SQLAlchemy mappings for Sidekick persistence, grouped by domain.

This package replaces the former single `models.py`. Every public name that module exposed is
re-exported here, including its import aliases, so existing importers stay unchanged.
"""

from datetime import date, datetime
from typing import Any, ClassVar
from uuid import UUID

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .audit import ActivityEntryRow, AuditEventRow, DomainEventRow, IdempotencyRow
from .base import RETAINED_UNMAPPED_TABLES, SCHEMA, Base
from .companion import CompanionPairingRow, PushOutboxRow, PushReminderRow, PushSubscriptionRow
from .contacts import (
    ContactAliasRow,
    ContactRow,
    ContactTagRow,
    ProjectContactRow,
    TaskContactRow,
)
from .identity import PersonalAccessTokenRow, UserRow
from .journal import (
    DailyJournalSummaryEntryRow,
    DailyJournalSummaryRow,
    JournalDraftRow,
    JournalEntryContactRow,
    JournalEntryProjectRow,
    JournalEntryRow,
    JournalEntryTagRow,
    JournalEntryTaskRow,
    JournalProcessingRunRow,
    JournalSourceRow,
    JournalSummaryProposalRow,
)
from .license import InstanceLicenseRow
from .memory import (
    MemoryForgottenFactRow,
    MemoryForgottenUnitRow,
    MemorySettingsRow,
    MemorySourceRow,
    MemoryUsageDailyRow,
)
from .tasks import ActionRow, StepRow, TaskRow, TaskStatusHistoryRow
from .work import (
    DomainRow,
    DomainTagRow,
    ProcessRow,
    ProcessRunOutboxRow,
    ProcessRunRow,
    ProcessRunTemplateRow,
    ProcessTagRow,
    ProjectRow,
    ProjectTagRow,
    SavedViewRow,
    TaskTagRow,
    WorkTagRow,
)

__all__ = [
    "CHAR",
    "JSONB",
    "PGUUID",
    "RETAINED_UNMAPPED_TABLES",
    "SCHEMA",
    "TSVECTOR",
    "UUID",
    "ActionRow",
    "ActivityEntryRow",
    "Any",
    "AuditEventRow",
    "Base",
    "BigInteger",
    "Boolean",
    "CheckConstraint",
    "ClassVar",
    "CompanionPairingRow",
    "Computed",
    "ContactAliasRow",
    "ContactRow",
    "ContactTagRow",
    "DailyJournalSummaryEntryRow",
    "DailyJournalSummaryRow",
    "Date",
    "DateTime",
    "DeclarativeBase",
    "DomainEventRow",
    "DomainRow",
    "DomainTagRow",
    "ForeignKey",
    "ForeignKeyConstraint",
    "IdempotencyRow",
    "Index",
    "InstanceLicenseRow",
    "Integer",
    "JournalDraftRow",
    "JournalEntryContactRow",
    "JournalEntryProjectRow",
    "JournalEntryRow",
    "JournalEntryTagRow",
    "JournalEntryTaskRow",
    "JournalProcessingRunRow",
    "JournalSourceRow",
    "JournalSummaryProposalRow",
    "Mapped",
    "MemoryForgottenFactRow",
    "MemoryForgottenUnitRow",
    "MemorySettingsRow",
    "MemorySourceRow",
    "MemoryUsageDailyRow",
    "PersonalAccessTokenRow",
    "PrimaryKeyConstraint",
    "ProcessRow",
    "ProcessRunOutboxRow",
    "ProcessRunRow",
    "ProcessRunTemplateRow",
    "ProcessTagRow",
    "ProjectContactRow",
    "ProjectRow",
    "ProjectTagRow",
    "PushOutboxRow",
    "PushReminderRow",
    "PushSubscriptionRow",
    "SavedViewRow",
    "SmallInteger",
    "StepRow",
    "String",
    "TaskContactRow",
    "TaskRow",
    "TaskStatusHistoryRow",
    "TaskTagRow",
    "Text",
    "UniqueConstraint",
    "UserRow",
    "WorkTagRow",
    "date",
    "datetime",
    "mapped_column",
    "relationship",
    "text",
]
