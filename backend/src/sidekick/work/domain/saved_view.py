"""The saved Work view record."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class SavedView:
    id: UUID
    owner_id: UUID
    name: str
    definition: dict[str, Any]
    version: int
    archived_at: datetime | None = None
