"""Journal entry and day records and structured results, shared by MCP and the companion API."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import TYPE_CHECKING, Annotated, Any, Literal
from uuid import UUID

from pydantic import Field

from sidekick.journal.application.models import RelationChange
from sidekick.journal.domain.day_done import owner_today
from sidekick.journal.domain.entry import KeyPoint, KeyPointKind
from sidekick.journal.domain.records import DaySummaryStatus, EntryRelations, RelationLabels
from sidekick.journal.domain.source import SourceType
from sidekick.journal.domain.summary import DailySummary, SummaryContent
from sidekick.shared.errors import ValidationError
from sidekick.shared.text_guard import NoImageData
from sidekick.shared.types import MAX_CURSOR_LENGTH, Actor
from sidekick.structured.base import Output

if TYPE_CHECKING:
    from sidekick.composition import Container


class JournalKeyPoint(Output):
    kind: KeyPointKind
    text: Annotated[str, Field(min_length=1, max_length=2_000)]


class JournalEntryLink(Output):
    """One linked Project or Contact. The label is its name, left out without the read scope."""

    kind: Literal["project", "contact"]
    id: UUID
    label: Annotated[str, Field(min_length=1, max_length=200)] | None


class JournalEntryRecord(Output):
    id: UUID
    source_id: UUID
    journal_date: date
    occurred_at: datetime | None
    title: Annotated[str, Field(min_length=1, max_length=200)]
    summary: Annotated[str, Field(max_length=10_000)] | None
    key_points: Annotated[list[JournalKeyPoint], Field(max_length=50)]
    project_ids: Annotated[
        list[UUID], Field(max_length=25, json_schema_extra={"uniqueItems": True})
    ]
    task_ids: Annotated[list[UUID], Field(max_length=25, json_schema_extra={"uniqueItems": True})]
    contact_ids: Annotated[
        list[UUID], Field(max_length=25, json_schema_extra={"uniqueItems": True})
    ]
    # The Projects and Contacts above with their names, so a card or Claude can say who and what.
    links: Annotated[list[JournalEntryLink], Field(max_length=50)]
    archived: bool
    version: Annotated[int, Field(ge=1)]


class JournalEntryResult(Output):
    entry: JournalEntryRecord


class JournalEntryPageResult(Output):
    entries: Annotated[list[JournalEntryRecord], Field(max_length=50)]
    next_cursor: Annotated[str, Field(max_length=MAX_CURSOR_LENGTH)] | None
    # The owner's IANA zone and calendar date now, so a room that has no meta (the phone) can
    # say "today" the way the server does.
    owner_timezone: Annotated[str, Field(min_length=1, max_length=64)]
    today: date


class JournalSourceRecord(Output):
    id: UUID
    source_type: SourceType
    journal_date: date
    occurred_at: datetime | None
    source_recorded_at: datetime | None
    language: str | None
    replaces_source_id: UUID | None
    content_fingerprint: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    created_at: datetime


class JournalSourceReadRecord(JournalSourceRecord):
    """Provenance of one owned source; `raw_text` is present unless include_content is false."""

    raw_text: Annotated[str, Field(min_length=1, max_length=100_000)] | None


class JournalSourceReadResult(Output):
    source: JournalSourceReadRecord


class JournalSummaryRecord(Output):
    journal_date: date
    exists: bool
    origin: Literal["manual", "ai_assisted"] | None
    status: Literal["current", "stale", "failed"] | None
    content: SummaryContent | None
    entry_ids: Annotated[
        list[UUID], Field(max_length=10_000, json_schema_extra={"uniqueItems": True})
    ]
    source_fingerprint: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None
    version: Annotated[int, Field(ge=1)] | None
    changed_entry_count: Annotated[int, Field(ge=0)]


class DoneTaskRecord(Output):
    id: UUID
    title: str
    completed_at: datetime
    project_title: str | None
    recurring: bool


class DoneStepRecord(Output):
    id: UUID
    title: str
    task_id: UUID
    task_title: str
    completed_at: datetime


class DonePurchaseRecord(Output):
    id: UUID
    title: str
    list_id: UUID
    list_title: str
    purchased_at: datetime


class DoneCountsRecord(Output):
    tasks: Annotated[int, Field(ge=0)]
    steps: Annotated[int, Field(ge=0)]
    purchases: Annotated[int, Field(ge=0)]


class DayDoneRecord(Output):
    """What was completed or bought on the day (owner's zone), earliest first, 50 per list."""

    tasks: Annotated[list[DoneTaskRecord], Field(max_length=50)]
    steps: Annotated[list[DoneStepRecord], Field(max_length=50)]
    purchases: Annotated[list[DonePurchaseRecord], Field(max_length=50)]
    counts: DoneCountsRecord
    truncated: bool


class JournalDayResult(Output):
    journal_date: date
    owner_timezone: Annotated[str, Field(min_length=1, max_length=64)]
    today: date
    entries: Annotated[list[JournalEntryRecord], Field(max_length=50)]
    next_cursor: Annotated[str, Field(max_length=MAX_CURSOR_LENGTH)] | None
    # Over all active entries of the day, not this page; the value set_daily_journal_summary needs.
    entry_fingerprint: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    summary: JournalSummaryRecord
    done: DayDoneRecord


class JournalKeyPointInput(Output):
    kind: KeyPointKind
    text: Annotated[str, Field(min_length=1, max_length=2_000), NoImageData]


def entry_record(
    entry: Any,
    relations: EntryRelations,
    *,
    include_content: bool,
    labels: RelationLabels | None = None,
) -> JournalEntryRecord:
    names = labels or RelationLabels(projects={}, contacts={})
    links = [
        JournalEntryLink(
            kind="project",
            id=project_id,
            label=names.projects.get(project_id) if include_content else None,
        )
        for project_id in relations.project_ids
    ] + [
        JournalEntryLink(
            kind="contact",
            id=contact_id,
            label=names.contacts.get(contact_id) if include_content else None,
        )
        for contact_id in relations.contact_ids
    ]
    return JournalEntryRecord(
        id=entry.id,
        source_id=entry.source_id,
        journal_date=entry.journal_date,
        occurred_at=entry.occurred_at,
        title=entry.title,
        summary=entry.summary if include_content else None,
        key_points=[JournalKeyPoint(kind=point.kind, text=point.text) for point in entry.key_points]
        if include_content
        else [],
        project_ids=list(relations.project_ids),
        task_ids=list(relations.task_ids),
        contact_ids=list(relations.contact_ids),
        links=links,
        archived=entry.archived_at is not None,
        version=entry.version,
    )


def done_record(done: Any) -> DayDoneRecord:
    return DayDoneRecord(
        tasks=[
            DoneTaskRecord(
                id=item.id,
                title=item.title,
                completed_at=item.completed_at,
                project_title=item.project_title,
                recurring=item.recurring,
            )
            for item in done.tasks
        ],
        steps=[
            DoneStepRecord(
                id=item.id,
                title=item.title,
                task_id=item.task_id,
                task_title=item.task_title,
                completed_at=item.completed_at,
            )
            for item in done.steps
        ],
        purchases=[
            DonePurchaseRecord(
                id=item.id,
                title=item.title,
                list_id=item.list_id,
                list_title=item.list_title,
                purchased_at=item.purchased_at,
            )
            for item in done.purchases
        ],
        counts=DoneCountsRecord(
            tasks=done.counts.tasks, steps=done.counts.steps, purchases=done.counts.purchases
        ),
        truncated=done.truncated,
    )


def summary_record(
    journal_date: date,
    summary: DailySummary | None,
    status: DaySummaryStatus,
) -> JournalSummaryRecord:
    if summary is None:
        return JournalSummaryRecord(
            journal_date=journal_date,
            exists=False,
            origin=None,
            status=None,
            content=None,
            entry_ids=[],
            source_fingerprint=None,
            version=None,
            changed_entry_count=status.changed_entry_count,
        )
    return JournalSummaryRecord(
        journal_date=journal_date,
        exists=True,
        origin=summary.origin.value,
        status=summary.state.value if summary.state.value != "missing" else None,
        content=summary.content,
        entry_ids=list(summary.entry_ids),
        source_fingerprint=summary.source_fingerprint,
        version=summary.version,
        changed_entry_count=status.changed_entry_count,
    )


def entry_with_relations(
    container: Container,
    actor: Actor,
    entry: Any,
    *,
    include_content: bool,
) -> JournalEntryRecord:
    relations = container.journal_relations.get_entry_relations(actor, entry.id)
    return labeled_entry_record(container, actor, entry, relations, include_content=include_content)


def entry_records_with_relations(
    container: Container,
    actor: Actor,
    entries: Sequence[Any],
    *,
    include_content: bool,
) -> list[JournalEntryRecord]:
    """The entries' records with links, and with content their names: one batched read of
    every entry's links and names instead of one per entry."""

    relations = container.journal_relations.get_entries_relations(
        actor, tuple(entry.id for entry in entries), with_labels=include_content
    )
    return [
        entry_record(
            entry,
            relations[entry.id][0],
            include_content=include_content,
            labels=relations[entry.id][1],
        )
        for entry in entries
    ]


def labeled_entry_record(
    container: Container,
    actor: Actor,
    entry: Any,
    relations: EntryRelations,
    *,
    include_content: bool,
) -> JournalEntryRecord:
    """The entry record with its links named; names need the kind's read scope (D-060: Claude reads
    the owner's own text within its scope)."""

    labels = (
        container.journal_relations.get_relation_labels(actor, relations)
        if include_content
        else None
    )
    return entry_record(entry, relations, include_content=include_content, labels=labels)


def _owner_today(container: Container) -> date:
    """The owner's calendar date by the journal's own clock, in `SIDEKICK_OWNER_TIMEZONE`."""

    return owner_today(container.journal.clock.now(), container.settings.owner_zone)


def journal_entries_structured(
    container: Container,
    actor: Actor,
    *,
    from_date: date | None,
    to_date: date | None,
    include_archived: bool,
    include_content: bool,
    limit: int,
    cursor: str | None,
) -> dict[str, Any]:
    """The structured content of `list_journal_entries`; a missing bound is the other, or today."""

    today = _owner_today(container)
    page = container.journal.list_entries(
        actor,
        start_date=from_date or to_date or today,
        end_date=to_date or from_date or today,
        include_archived=include_archived,
        limit=limit,
        cursor=cursor,
    )
    return JournalEntryPageResult(
        entries=entry_records_with_relations(
            container, actor, page.items, include_content=include_content
        ),
        next_cursor=page.next_cursor,
        owner_timezone=container.settings.owner_timezone,
        today=today,
    ).model_dump(mode="json")


def source_record(source: Any) -> JournalSourceRecord:
    return JournalSourceRecord(
        id=source.id,
        source_type=source.source_type,
        journal_date=source.journal_date,
        occurred_at=source.occurred_at,
        source_recorded_at=source.source_recorded_at,
        language=source.language,
        replaces_source_id=source.replaces_source_id,
        content_fingerprint=source.content_fingerprint,
        created_at=source.created_at,
    )


def source_read_record(source: Any, *, include_content: bool) -> JournalSourceReadRecord:
    return JournalSourceReadRecord(
        **source_record(source).model_dump(),
        raw_text=source.raw_text if include_content else None,
    )


def journal_source_structured(
    container: Container, actor: Actor, source_id: UUID, *, include_content: bool
) -> dict[str, Any]:
    """The structured content of `get_journal_source`: one owned source with its immutable text."""

    source = container.journal_capture.get_source(actor, source_id)
    return JournalSourceReadResult(
        source=source_read_record(source, include_content=include_content)
    ).model_dump(mode="json")


def journal_entry_structured(
    container: Container, actor: Actor, entry_id: UUID, *, include_content: bool
) -> dict[str, Any]:
    """The structured content of `get_journal_entry`."""

    entry = container.journal.get_entry(actor, entry_id)
    return JournalEntryResult(
        entry=entry_with_relations(container, actor, entry, include_content=include_content)
    ).model_dump(mode="json")


def journal_day_structured(
    container: Container,
    actor: Actor,
    journal_date: date,
    *,
    include_archived: bool,
    include_content: bool,
    limit: int,
    cursor: str | None,
) -> dict[str, Any]:
    """The structured content of `get_journal_day`: entries, summary status and `done`."""

    day = container.journal_day.get_day(
        actor,
        journal_date=journal_date,
        include_archived=include_archived,
        limit=limit,
        cursor=cursor,
    )
    return JournalDayResult(
        journal_date=day.journal_date,
        owner_timezone=container.settings.owner_timezone,
        today=_owner_today(container),
        entries=entry_records_with_relations(
            container, actor, day.entries, include_content=include_content
        ),
        next_cursor=day.next_cursor,
        entry_fingerprint=day.entry_fingerprint,
        summary=summary_record(day.journal_date, day.summary, day.summary_status),
        done=done_record(day.done),
    ).model_dump(mode="json")


def write_journal_entry_structured(
    container: Container,
    actor: Actor,
    *,
    journal_date: date,
    title: str,
    source_text: str,
    idempotency_key: str,
    summary: str | None = None,
    key_points: list[JournalKeyPointInput] | None = None,
    project_ids: list[UUID] | None = None,
    task_ids: list[UUID] | None = None,
    contact_ids: list[UUID] | None = None,
    occurred_at: datetime | None = None,
    language: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Save the owner's own words as a source and its entry in one step; the structured content
    of `write_journal_entry`. No AI runs."""

    relations = EntryRelations(
        project_ids=tuple(project_ids or ()),
        task_ids=tuple(task_ids or ()),
        contact_ids=tuple(contact_ids or ()),
    )
    _, entry = container.journal_capture.write_entry(
        actor,
        source_type=SourceType.TRANSCRIPT_TEXT,
        journal_date=journal_date,
        occurred_at=occurred_at,
        raw_text=source_text,
        language=language,
        title=title,
        summary=summary,
        key_points=tuple(KeyPoint(point.kind, point.text) for point in key_points or ()),
        project_ids=relations.project_ids,
        task_ids=relations.task_ids,
        contact_ids=relations.contact_ids,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    return JournalEntryResult(
        entry=labeled_entry_record(container, actor, entry, relations, include_content=True)
    ).model_dump(mode="json")


def update_journal_entry_structured(
    container: Container,
    actor: Actor,
    entry_id: UUID,
    *,
    expected_version: int,
    idempotency_key: str,
    title: str | None = None,
    summary: str | None = None,
    key_points: list[JournalKeyPointInput] | None = None,
    append_key_points: list[JournalKeyPointInput] | None = None,
    append_text: str | None = None,
    add_contact_ids: list[UUID] | None = None,
    remove_contact_ids: list[UUID] | None = None,
    add_project_ids: list[UUID] | None = None,
    remove_project_ids: list[UUID] | None = None,
    correlation_id: str | None = None,
) -> tuple[dict[str, Any], EntryRelations | None]:
    """Add to, replace or relink one entry; the structured content of `update_journal_entry`.

    The second value is the entry's links before the write, set only when links changed (the MCP
    tool's summary line names the difference). Version check, idempotency and audit are the use
    case's own.
    """

    # Checked before the write: the relations are read back afterwards, so a write-only actor
    # would otherwise commit the edit and only then be refused.
    actor.require("journal:read")
    change = RelationChange(
        add_project_ids=tuple(add_project_ids or ()),
        remove_project_ids=tuple(remove_project_ids or ()),
        add_contact_ids=tuple(add_contact_ids or ()),
        remove_contact_ids=tuple(remove_contact_ids or ()),
    )
    before = (
        container.journal_relations.get_entry_relations(actor, entry_id)
        if not change.is_empty()
        else None
    )
    appended = tuple(KeyPoint(point.kind, point.text) for point in append_key_points or [])
    if appended or append_text is not None:
        # Add mode: nothing needs resending. Omitted title and summary stay as they are.
        if key_points is not None:
            raise ValidationError("send key_points to replace or append_key_points to add")
        entry = container.journal.append_to_entry(
            actor,
            entry_id=entry_id,
            expected_version=expected_version,
            append_key_points=appended,
            append_text=append_text,
            title=title,
            summary=summary,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            relation_change=change,
        )
    elif title is None and key_points is None and summary is None and not change.is_empty():
        # Links only: the content stays and the entry gets a new version.
        entry = container.journal.change_entry_relations(
            actor,
            entry_id=entry_id,
            expected_version=expected_version,
            change=change,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )
    else:
        # Replace mode: title and key_points are required, and a null or omitted summary clears it.
        if title is None or key_points is None:
            raise ValidationError(
                "send title and key_points to replace, append_key_points/append_text to add, "
                "or only link changes"
            )
        entry = container.journal.update_entry(
            actor,
            entry_id=entry_id,
            expected_version=expected_version,
            title=title,
            summary=summary,
            key_points=tuple(KeyPoint(point.kind, point.text) for point in key_points),
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            relation_change=change,
        )
    structured = JournalEntryResult(
        entry=entry_with_relations(container, actor, entry, include_content=True)
    ).model_dump(mode="json")
    return structured, before
