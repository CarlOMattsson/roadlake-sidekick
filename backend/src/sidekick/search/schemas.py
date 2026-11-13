"""Closed wire contracts for search results, shared by every transport.

Journal hits carry ids, a journal date, where the match was found and the entry title. They
never carry a summary, raw text or excerpt (D-058: logs and telemetry never carry user content);
the owner reads text through the journal
entry tools. A source hit without an entry has `title: None`.
"""

from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from sidekick.search.domain import Kind


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskHitRecord(Closed):
    id: UUID
    title: str
    status: str
    version: int


class ProjectHitRecord(Closed):
    id: UUID
    title: str
    status: str
    version: int


class ContactHitRecord(Closed):
    id: UUID
    display_name: str
    version: int


class JournalHitRecord(Closed):
    id: UUID
    id_type: Literal["entry", "source"]
    journal_date: date
    matched_in: Literal["entry", "source_text"]
    title: str | None


class TaskSearchPage(Closed):
    hits: list[TaskHitRecord]
    next_cursor: str | None = None


class ProjectSearchPage(Closed):
    hits: list[ProjectHitRecord]
    next_cursor: str | None = None


class ContactSearchPage(Closed):
    hits: list[ContactHitRecord]
    next_cursor: str | None = None


class JournalSearchPage(Closed):
    hits: list[JournalHitRecord]
    next_cursor: str | None = None


class SearchResult(Closed):
    """Only the kinds that were searched appear, and `searched` lists exactly those kinds."""

    searched: list[Kind]
    tasks: TaskSearchPage | None = None
    projects: ProjectSearchPage | None = None
    contacts: ContactSearchPage | None = None
    journal: JournalSearchPage | None = None
