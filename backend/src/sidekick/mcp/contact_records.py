"""Result and input models of the Contact tools."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import Field, model_validator

from sidekick.contacts.application.serialization import contact_public_data
from sidekick.contacts.domain.contact import Contact
from sidekick.shared.text_guard import NoImageData
from sidekick.shared.types import MAX_CURSOR_LENGTH
from sidekick.structured.base import Output
from sidekick.structured.contacts import ContactSummaryRecord
from sidekick.structured.tags import TagMatch, TagsInput


class ContactPageResult(Output):
    contacts: list[ContactSummaryRecord]
    next_cursor: str | None = None
    # The search this page answered, so a view shows and repeats the same filters with its cursor.
    q: str | None = None
    include_archived: bool = False
    tags: list[str] = Field(default_factory=list)
    tag_match: TagMatch = "any"


class ContactAliasRecord(Output):
    id: UUID
    value: str
    created_at: datetime


class ContactRecord(Output):
    id: UUID
    display_name: str
    context_note: str | None
    email: str | None
    phone: str | None
    relationship: str | None = None
    organization: str | None = None
    role: str | None = None
    # Shown to the Contact app and to the model (D-060: the host model may read the owner's own
    # content, within the token's scopes).
    address: str | None = None
    aliases: list[ContactAliasRecord]
    tags: list[str] = Field(default_factory=list)
    archived: bool
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    version: int


class ContactResult(Output):
    contact: ContactRecord


class ProjectSummaryRecord(Output):
    id: UUID
    title: str
    status: str
    updated_at: datetime
    version: int


class TaskSummaryRecord(Output):
    """A linked Task in Contact context.

    `waiting_on_contact` is the only relationship claim: this Task explicitly waits
    on this Contact. Other linked Tasks are linked work, not promises to the Contact.
    """

    id: UUID
    project_id: UUID | None
    title: str
    status: str
    priority: str
    due_at: datetime | None
    updated_at: datetime
    version: int
    waiting_on_contact: bool = False
    waiting_since: datetime | None = None
    follow_up_at: datetime | None = None
    follow_up_due: bool = False


class JournalEntryLinkRecord(Output):
    """A Journal entry linked to this Contact: id, date and title only, never its content."""

    id: UUID
    journal_date: date
    title: Annotated[str, Field(min_length=1, max_length=200)]


class JournalEntryContextRecord(Output):
    """The newest linked Journal entries, bounded to 10.

    `readable` is false when the session lacks `journal:read`; then `items` is empty and
    nothing about the Contact's entries is implied. `has_more` means older links exist.
    """

    items: Annotated[list[JournalEntryLinkRecord], Field(max_length=10)]
    has_more: bool = False
    readable: bool


class ProjectContextPageRecord(Output):
    items: list[ProjectSummaryRecord]
    next_cursor: str | None = None


class TaskContextPageRecord(Output):
    items: list[TaskSummaryRecord]
    next_cursor: str | None = None


class ContactContextResult(Output):
    contact: ContactRecord
    projects: ProjectContextPageRecord
    tasks: TaskContextPageRecord
    journal_entries: JournalEntryContextRecord


class ProjectContactResult(Output):
    contact_id: UUID
    project_id: UUID
    linked: bool


class TaskContactResult(Output):
    contact_id: UUID
    task_id: UUID
    linked: bool


# Parameter types shared by several tools; the JSON schema each produces is pinned by the contract.
Cursor = Annotated[str | None, Field(max_length=MAX_CURSOR_LENGTH)]
Relationship = Annotated[str | None, Field(max_length=80), NoImageData]
Organization = Annotated[str | None, Field(max_length=200), NoImageData]
Role = Annotated[str | None, Field(max_length=120), NoImageData]
Address = Annotated[str | None, Field(max_length=500), NoImageData]


class ContactChanges(Output):
    display_name: Annotated[str | None, Field(min_length=1, max_length=200), NoImageData] = None
    context_note: Annotated[str | None, Field(max_length=10000), NoImageData] = None
    email: Annotated[str | None, Field(max_length=320), NoImageData] = None
    phone: Annotated[str | None, Field(max_length=64), NoImageData] = None
    relationship: Relationship = None
    organization: Organization = None
    role: Role = None
    address: Address = None
    tags: TagsInput = Field(default_factory=list)

    @model_validator(mode="after")
    def require_change(self) -> ContactChanges:
        if not self.model_fields_set:
            raise ValueError("at least one change is required")
        if "display_name" in self.model_fields_set and self.display_name is None:
            raise ValueError("display_name cannot be null")
        return self


def contact_result(contact: Contact, tags: list[str]) -> dict[str, Any]:
    """The result of a Contact tool: the Contact as stored and its tag slugs."""

    return ContactResult(
        contact=ContactRecord.model_validate({**contact_public_data(contact), "tags": tags})
    ).model_dump(mode="json")
