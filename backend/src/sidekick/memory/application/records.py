"""The shape of the two memory rows as the use cases see them.

The persistence layer returns ORM rows; the use cases read and change them through these
structural types, so no application module imports `sidekick.shared.persistence`. The attributes
are the columns of `memory_settings` and `memory_sources`; the store adds and loads the rows.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID


class MemorySettingsRecord(Protocol):
    """One owner's memory settings: the four domain switches, the pause switch and the version."""

    owner_id: UUID
    journal: bool
    contacts: bool
    projects: bool
    tasks: bool
    paused: bool
    version: int
    created_at: datetime
    updated_at: datetime


class MemorySourceRecord(Protocol):
    """Synchronisation state of one owner record against the memory bank."""

    id: UUID
    owner_id: UUID
    source_kind: str
    source_id: UUID
    doc_key: str
    fingerprint: str
    pipeline_version: int
    status: str
    attempts: int
    next_attempt_at: datetime | None
    operation_id: str | None
    source_updated_at: datetime
    retained_at: datetime | None
    failure_category: str | None
    excluded: bool
