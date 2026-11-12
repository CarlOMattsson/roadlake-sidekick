"""Closed wire contracts used by both external-reference transports."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

Kind = Literal["mail", "calendar_event", "document"]
Provider = Literal["google_gmail", "google_calendar", "google_drive", "other"]
Source = Literal["claude_connector", "manual"]


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReferenceRecord(Closed):
    id: UUID
    kind: Kind
    provider: Provider
    account_ref: str
    external_id: str
    instance_ref: str | None
    title: str
    url: str | None
    occurs_at: datetime | None
    snapshot_at: datetime
    source: Source
    version: int
    created_at: datetime
    updated_at: datetime
    linked_at: datetime


class LinkResult(Closed):
    task_id: UUID
    reference: ReferenceRecord
    linked: bool
    relation_created: bool


class UnlinkResult(Closed):
    task_id: UUID
    reference_id: UUID
    linked: bool
    reference_removed: bool


class ReferencePage(Closed):
    task_id: UUID
    items: list[ReferenceRecord]
    next_cursor: str | None = None
