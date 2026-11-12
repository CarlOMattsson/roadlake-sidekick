"""Direct Journal rows for search tests.

Real entries come from AI review, which these tests skip.
"""

from datetime import UTC, date, datetime
from hashlib import sha256
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from sidekick.shared.persistence.models import JournalEntryRow, JournalSourceRow
from sidekick.shared.types import new_uuid7


def insert_source(
    factory: sessionmaker[Session],
    owner_id: UUID,
    raw_text: str,
    journal_date: date = date(2026, 10, 20),
) -> UUID:
    source_id = new_uuid7()
    with factory.begin() as session:
        session.add(
            JournalSourceRow(
                id=source_id,
                owner_id=owner_id,
                source_type="manual_text",
                journal_date=journal_date,
                raw_text=raw_text,
                content_fingerprint=sha256(raw_text.encode()).hexdigest(),
                created_at=datetime.now(UTC),
            )
        )
    return source_id


def insert_entry(
    factory: sessionmaker[Session],
    owner_id: UUID,
    source_id: UUID,
    title: str,
    *,
    summary: str | None = None,
    journal_date: date = date(2026, 10, 20),
) -> UUID:
    entry_id = new_uuid7()
    now = datetime.now(UTC)
    with factory.begin() as session:
        session.add(
            JournalEntryRow(
                id=entry_id,
                owner_id=owner_id,
                source_id=source_id,
                journal_date=journal_date,
                title=title,
                summary=summary,
                key_points=[],
                version=1,
                created_at=now,
                updated_at=now,
            )
        )
    return entry_id
