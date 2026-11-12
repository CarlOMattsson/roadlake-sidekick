"""The saved Work view record."""

from dataclasses import dataclass
from datetime import datetime
from typing import TypedDict
from uuid import UUID


class SavedViewDefinition(TypedDict, total=False):
    """The filters a saved view may name, and never anything executable.

    The keys are the whole allow-list (`SAVED_VIEW_FIELDS`); the values are what the owner saved,
    checked by `validate_definition` before a definition is stored.
    """

    name: str
    view: str
    context: str
    status: str
    priority: str
    priorities: list[str]
    attention: str
    archive: str
    kind: str
    q: str
    sort: str
    group: str
    version: int
    tags: list[str]
    tag_match: str
    actionable: str
    waiting: str
    estimate: str


SAVED_VIEW_FIELDS = frozenset(SavedViewDefinition.__optional_keys__)


@dataclass(frozen=True, slots=True)
class SavedView:
    id: UUID
    owner_id: UUID
    name: str
    definition: SavedViewDefinition
    version: int
    archived_at: datetime | None = None
