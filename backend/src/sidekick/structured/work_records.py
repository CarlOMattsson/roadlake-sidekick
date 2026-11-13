"""Records and write inputs for the Work domain, shared by the MCP tools and the companion API.

Nothing here knows about FastMCP or FastAPI. The closed output models double as the MCP output
schemas, so a change to a field is a change to the MCP contract.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, tzinfo
from typing import TYPE_CHECKING, Annotated, Literal
from uuid import UUID

from pydantic import BeforeValidator, Field, model_validator

from sidekick.projects.domain import ProjectStatus
from sidekick.shared.cadence import Cadence
from sidekick.shared.errors import ValidationError
from sidekick.shared.text_guard import NoImageData
from sidekick.structured.base import Output
from sidekick.tasks.domain import Priority, RecurrenceRule, TaskStatus
from sidekick.tasks.domain.planning import MAX_ESTIMATED_MINUTES
from sidekick.work.domain import DomainStatus, ProcessStatus
from sidekick.work.domain.planning import (
    MAX_ACTION_NOTE_LENGTH,
    MAX_DEFINITION_OF_DONE_LENGTH,
    MAX_STEP_INSTRUCTION_LENGTH,
    MAX_TAGS_PER_RECORD,
)

if TYPE_CHECKING:
    pass


class EstimateTotalsRecord(Output):
    """A complete estimate summary for a bounded Task set."""

    scope: Literal["agenda_day", "project_open_tasks", "actionable_now", "selection"]
    task_count: int
    estimated_minutes_total: int
    overdue_minutes: int
    unestimated_count: int
    calculated_at: datetime


class _ProjectFields(Output):
    """A Project's fields except the description, which a list shortens (`ProjectListRecord`)."""

    id: UUID
    domain_id: UUID
    title: str
    status: str
    start_date: date | None
    """The project's earliest start: the project-level counterpart of `not_before`."""
    target_date: date | None
    created_at: datetime
    updated_at: datetime
    version: int
    archived_at: datetime | None = None
    definition_of_done: str | None = None
    tags: list[str] = Field(default_factory=list)
    estimate_totals: EstimateTotalsRecord | None = None


class ProjectRecord(_ProjectFields):
    description: str | None


class ProjectListRecord(_ProjectFields):
    """A Project as list_projects reads it: only a description excerpt; get_project has it all."""

    description_excerpt: str | None
    description_truncated: bool


class RecurrenceRecord(Output):
    """The stored recurrence rule, as `RecurrenceRule.to_data()` serialises it."""

    frequency: Literal["daily", "weekly", "monthly", "yearly"]
    interval: int = 1
    weekdays: list[int] = Field(default_factory=list[int])
    day_of_month: int | None = None
    until: date | None = None


class RecurrenceInput(Output):
    # Validated by the domain's `RecurrenceRule`; no docstring, it would be sent in every schema.

    frequency: Literal["daily", "weekly", "monthly", "yearly"]
    interval: Annotated[int, Field(ge=1, le=12)] = 1
    weekdays: Annotated[list[int], Field(max_length=7)] = Field(default_factory=list[int])
    """Weekly only: Monday is 0, Sunday is 6."""
    day_of_month: Annotated[int | None, Field(ge=1, le=31)] = None
    """Monthly only."""
    until: date | None = None
    """Last day an occurrence may fall on, in the owner's zone."""

    @model_validator(mode="after")
    def validate_rule(self) -> RecurrenceInput:
        try:
            RecurrenceRule.from_data(self.model_dump())
        except ValidationError as error:
            raise ValueError(str(error)) from error
        return self


class _TaskFields(Output):
    """A Task's fields except its description, which a list shortens (see `TaskListRecord`)."""

    id: UUID
    project_id: UUID | None
    domain_id: UUID | None
    process_id: UUID | None
    derived_domain_id: UUID | None
    title: str
    status: str
    priority: str
    due_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    version: int
    attention_requested: bool = False
    archived_at: datetime | None = None
    not_before: datetime | None = None
    """Earliest sensible start. Read by derivation only; nothing writes on passing."""
    estimated_minutes: int | None = None
    waiting_since: datetime | None = None
    follow_up_at: datetime | None = None
    waiting_on_contact_id: UUID | None = None
    blocked_reminder_cadence: Cadence | None = None
    blocked_reminder_snoozed_until: datetime | None = None
    blocked_last_reminded_at: datetime | None = None
    recurrence: RecurrenceRecord | None = None
    last_completed_at: datetime | None = None
    tags: list[str] = Field(default_factory=list)


class TaskRecord(_TaskFields):
    description: str | None


class TaskListRecord(_TaskFields):
    """A Task as list_tasks reads it: the description is only an excerpt; get_task has it all."""

    description_excerpt: str | None
    description_truncated: bool


class ProjectDetailRecord(ProjectRecord):
    """A Project as get_project reads it: its fields plus the counts of its Tasks."""

    tasks_done: int = 0
    tasks_total: int = 0
    tasks_overdue: int = 0
    """Tasks not completed whose due instant has passed."""


class ProjectDetailOutput(Output):
    project: ProjectDetailRecord


class ProjectOutput(Output):
    project: ProjectRecord


class ProjectPageOutput(Output):
    projects: list[ProjectListRecord]
    next_cursor: str | None = None


class TaskDetailRecord(TaskRecord):
    """A Task as get_task reads it: its fields plus the Project's title and the Step counts."""

    project_title: str | None = None
    """The Project the Task belongs to, by title (at most 120 characters); null otherwise."""
    steps_done: int = 0
    steps_total: int = 0


class TaskDetailOutput(Output):
    task: TaskDetailRecord


class TaskOutput(Output):
    task: TaskRecord


class TaskPageOutput(Output):
    tasks: list[TaskListRecord]
    next_cursor: str | None = None


class WorkItemRecord(Output):
    """One projected Work record, field for field the REST `WorkItemView`."""

    kind: str
    id: UUID
    parent_id: UUID | None
    title: str
    status: str
    priority: str | None = None
    due_at: datetime | None = None
    attention_requested: bool = False
    version: int
    archived: bool = False
    agenda_group: Literal["overdue", "today", "upcoming", "scheduled_later"] | None = None
    domain_id: UUID | None = None
    process_id: UUID | None = None
    project_id: UUID | None = None
    project_title: str | None = None
    domain_accent: str | None = None
    task_id: UUID | None = None
    earliest_start: datetime | None = None
    actionable_now: bool = True
    estimated_minutes: int | None = None
    waiting: bool = False
    waiting_since: datetime | None = None
    follow_up_at: datetime | None = None
    waiting_on_contact_id: UUID | None = None
    waiting_on_contact_name: str | None = None
    """Display name of the Contact a waiting Task waits on; only set when contacts:read is held."""
    follow_up_due: bool = False
    blocked_reminder_due: bool = False
    blocked_reminder_cadence: Cadence | None = None
    blocked_reminder_snoozed_until: datetime | None = None
    recurrence: RecurrenceRecord | None = None
    last_completed_at: datetime | None = None
    review_due: bool = False
    review_cadence: Cadence | None = None
    cadence: Cadence | None = None
    tags: list[str] = Field(default_factory=list)


class WorkItemPageOutput(Output):
    items: list[WorkItemRecord]
    next_cursor: str | None = None
    filters: dict[str, str | list[str]] = Field(default_factory=dict)


class WorkBoardOutput(Output):
    """Work records grouped by status, in manual board order within each column."""

    columns: dict[str, list[WorkItemRecord]]
    next_cursor: str | None = None
    filters: dict[str, str | list[str]] = Field(default_factory=dict)
    # Status names whose columns the owner has ordered by hand, in column order. No rank values.
    manually_ordered: list[str] = Field(default_factory=list)


DomainAccent = Literal["slate", "blue", "teal", "green", "amber", "orange", "rose", "violet"]


DOMAIN_ACCENT_DESCRIPTION = (
    "Colour accent shown next to the domain name: one of the eight names slate, blue, teal, "
    "green, amber, orange, rose or violet."
)


class DomainRecord(Output):
    id: UUID
    name: str
    description: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    version: int
    review_cadence: str | None = None
    last_reviewed_at: datetime | None = None
    accent: DomainAccent | None = None
    tags: list[str] = Field(default_factory=list)


class ProcessRecord(Output):
    id: UUID
    domain_id: UUID
    name: str
    description: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    version: int
    cadence: str | None = None
    tags: list[str] = Field(default_factory=list)


class DomainPageOutput(Output):
    domains: list[DomainRecord]
    next_cursor: str | None = None


class DomainOutput(Output):
    domain: DomainRecord


class ProcessPageOutput(Output):
    processes: list[ProcessRecord]
    next_cursor: str | None = None


class ProcessOutput(Output):
    process: ProcessRecord


class StepRecord(Output):
    id: UUID
    task_id: UUID
    title: str
    status: str
    position: int
    due_at: datetime | None
    version: int
    attention_requested: bool = False
    archived_at: datetime | None = None
    instruction: str | None = None


class ActionRecord(Output):
    id: UUID
    step_id: UUID
    title: str
    status: str
    position: int
    due_at: datetime | None
    version: int
    attention_requested: bool = False
    archived_at: datetime | None = None
    note: str | None = None


class StepPageOutput(Output):
    items: list[StepRecord]
    next_cursor: str | None = None


class ActionPageOutput(Output):
    items: list[ActionRecord]
    next_cursor: str | None = None


class StepOutput(Output):
    step: StepRecord


class ActionOutput(Output):
    action: ActionRecord


class TagRecord(Output):
    """One owner-scoped vocabulary entry."""

    id: UUID
    slug: str
    label: str
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None
    version: int


class TagPageOutput(Output):
    tags: list[TagRecord]
    next_cursor: str | None = None


class HierarchyNodeRecord(Output):
    """One node of the Work hierarchy, field for field the REST `HierarchyNode`."""

    kind: str
    id: UUID
    parent_id: UUID | None
    title: str
    status: str
    version: int
    accent: str | None = None


class HierarchyStepRecord(Output):
    """One active Step under a hierarchy Task: the compact fields only."""

    id: UUID
    title: str
    status: str


class HierarchyTaskRecord(Output):
    """One active Task under a hierarchy Project or Process, with its ordered Steps."""

    id: UUID
    parent_id: UUID
    """The Project, or else the Process, that the Task belongs to."""
    title: str
    status: str
    version: int
    due_at: datetime | None
    steps: list[HierarchyStepRecord] = Field(default_factory=list[HierarchyStepRecord])


class HierarchyOutput(Output):
    nodes: list[HierarchyNodeRecord]
    truncated: bool
    next_cursor: str | None = None
    """Pass as `cursor` to get the next page of nodes; null when every node has been returned."""
    tasks: list[HierarchyTaskRecord] = Field(default_factory=list[HierarchyTaskRecord])
    """Filled only when the tool was asked for `include_tasks`; otherwise left out of the JSON."""


class SavedViewFilters(Output):
    """The closed set of fields a saved Work view may name; nothing executable."""

    view: Literal["dashboard", "hierarchy", "list", "board", "agenda"]
    context: Literal["all", "domain", "process", "project", "task"]
    q: Annotated[str | None, Field(max_length=200)] = None
    status: TaskStatus | None = None
    priority: Priority | None = None
    priorities: Annotated[list[Priority] | None, Field(max_length=4)] = None
    attention: Literal["all", "requested"] | None = None
    archive: Literal["active", "archived", "all"] | None = None
    kind: Literal["all", "domain", "process", "project", "task", "step", "action"] | None = None
    sort: (
        Literal[
            "updated_desc",
            "due_asc",
            "title_asc",
            "priority_desc",
            "not_before_asc",
            "estimate_asc",
        ]
        | None
    ) = None
    group: Literal["none", "kind", "status", "context"] | None = None
    tags: Annotated[list[Annotated[str, Field(max_length=80)]] | None, Field(max_length=5)] = None
    tag_match: Literal["any", "all"] | None = None
    actionable: Literal["all", "now", "later"] | None = None
    waiting: Literal["all", "waiting", "not_waiting"] | None = None
    estimate: Literal["all", "estimated", "unestimated"] | None = None


class SavedViewDefinitionRecord(Output):
    """A stored definition as read back; values are what the owner saved, so they stay loose."""

    view: str
    context: str
    name: str | None = None
    version: int | None = None
    q: str | None = None
    status: str | None = None
    priority: str | None = None
    priorities: list[str] | None = None
    attention: str | None = None
    archive: str | None = None
    kind: str | None = None
    sort: str | None = None
    group: str | None = None
    tags: list[str] | None = None
    tag_match: str | None = None
    actionable: str | None = None
    waiting: str | None = None
    estimate: str | None = None


class SavedViewRecord(Output):
    id: UUID
    name: str
    definition: SavedViewDefinitionRecord
    version: int
    archived_at: datetime | None = None


class SavedViewOutput(Output):
    saved_view: SavedViewRecord


class SavedViewListOutput(Output):
    saved_views: list[SavedViewRecord]


# The priorities an MCP write may set. A stored `urgent` Task still reads back with `urgent`.
WritePriority = Literal["low", "normal", "high"]


_BARE_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _bare_date_as_date(value: object) -> object:
    """A YYYY-MM-DD string becomes a date; anything else goes on to the datetime check."""

    if isinstance(value, str) and _BARE_DATE.fullmatch(value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return value
    return value


# A due date is an ISO datetime (with or without offset) or a bare date. end_of_day_due_at
# turns a bare date into 23:59 in the owner's zone.
DueAtInput = Annotated[datetime | date | None, BeforeValidator(_bare_date_as_date)]


def end_of_day_due_at(value: datetime | date | None, zone: tzinfo) -> datetime | None:
    """A bare date means end of that day, 23:59 in the owner's zone. Datetimes stay as given."""

    if value is None or isinstance(value, datetime):
        return value
    return datetime.combine(value, time(23, 59), tzinfo=zone)


class TaskChanges(Output):
    """Fields to change: omitted stays, null clears where allowed."""

    title: Annotated[str | None, Field(min_length=1, max_length=200), NoImageData] = None
    description: Annotated[str | None, Field(max_length=10_000), NoImageData] = None
    status: TaskStatus | None = None
    priority: WritePriority | None = None
    project_id: UUID | None = None
    domain_id: UUID | None = None
    process_id: UUID | None = None
    due_at: DueAtInput = None
    not_before: datetime | None = None
    estimated_minutes: Annotated[int | None, Field(ge=1, le=MAX_ESTIMATED_MINUTES)] = None
    waiting_since: datetime | None = None
    follow_up_at: datetime | None = None
    waiting_on_contact_id: UUID | None = None
    recurrence: RecurrenceInput | None = None
    """The Task's own repeat rule; null removes it. Independent of any Process."""
    last_completed_at: datetime | None = None
    """Undo of a recurring completion: send the value the Task had before (null for none)."""
    tags: Annotated[
        list[Annotated[str, NoImageData]] | None,
        Field(max_length=MAX_TAGS_PER_RECORD),
    ] = None

    @model_validator(mode="after")
    def require_change(self) -> TaskChanges:
        if not self.model_fields_set:
            raise ValueError("at least one change is required")
        if "title" in self.model_fields_set and self.title is None:
            raise ValueError("title cannot be null")
        return self


class StepChanges(Output):
    title: Annotated[str | None, Field(min_length=1, max_length=200)] = None
    status: TaskStatus | None = None
    due_at: datetime | None = None
    attention_requested: bool | None = None
    instruction: Annotated[str | None, Field(max_length=MAX_STEP_INSTRUCTION_LENGTH)] = None


class ActionChanges(Output):
    title: Annotated[str | None, Field(min_length=1, max_length=200)] = None
    due_at: datetime | None = None
    attention_requested: bool | None = None
    note: Annotated[str | None, Field(max_length=MAX_ACTION_NOTE_LENGTH)] = None


class ProjectChanges(Output):
    """Fields to change: omitted stays, null clears where allowed."""

    domain_id: UUID | None = None
    title: Annotated[str | None, Field(min_length=1, max_length=200)] = None
    description: Annotated[str | None, Field(max_length=10_000)] = None
    status: ProjectStatus | None = None
    start_date: date | None = None
    target_date: date | None = None
    definition_of_done: Annotated[str | None, Field(max_length=MAX_DEFINITION_OF_DONE_LENGTH)] = (
        None
    )
    tags: Annotated[list[str] | None, Field(max_length=MAX_TAGS_PER_RECORD)] = None

    @model_validator(mode="after")
    def require_change(self) -> ProjectChanges:
        if not self.model_fields_set:
            raise ValueError("at least one change is required")
        if "title" in self.model_fields_set and self.title is None:
            raise ValueError("title cannot be null")
        if "domain_id" in self.model_fields_set and self.domain_id is None:
            raise ValueError("project domain cannot be cleared")
        return self


class DomainChanges(Output):
    """Fields to change: omitted stays, null clears where allowed."""

    name: Annotated[str | None, Field(min_length=1, max_length=200)] = None
    description: Annotated[str | None, Field(max_length=10_000)] = None
    status: DomainStatus | None = None
    review_cadence: Cadence | None = None
    last_reviewed_at: datetime | None = None
    accent: Annotated[
        DomainAccent | None, Field(description=f"{DOMAIN_ACCENT_DESCRIPTION} Null clears it.")
    ] = None
    tags: Annotated[list[str] | None, Field(max_length=MAX_TAGS_PER_RECORD)] = None

    @model_validator(mode="after")
    def require_change(self) -> DomainChanges:
        if not self.model_fields_set:
            raise ValueError("at least one change is required")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name cannot be null")
        return self


class ProcessChanges(Output):
    """Fields to change: omitted stays, null clears where allowed."""

    name: Annotated[str | None, Field(min_length=1, max_length=200)] = None
    description: Annotated[str | None, Field(max_length=10_000)] = None
    status: ProcessStatus | None = None
    domain_id: UUID | None = None
    cadence: Cadence | None = None
    tags: Annotated[list[str] | None, Field(max_length=MAX_TAGS_PER_RECORD)] = None

    @model_validator(mode="after")
    def require_change(self) -> ProcessChanges:
        if not self.model_fields_set:
            raise ValueError("at least one change is required")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name cannot be null")
        if "domain_id" in self.model_fields_set and self.domain_id is None:
            raise ValueError("process domain cannot be cleared")
        return self


class ReorderItem(Output):
    id: UUID
    version: int = Field(ge=1)
