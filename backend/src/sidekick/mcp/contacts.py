"""MCP tool schemas and registrations for Contacts and Relationships."""

# En dashes are intentional human-facing tool copy preserved by contract snapshots.
# ruff: noqa: RUF001

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, tzinfo
from typing import Annotated, Any, cast
from uuid import UUID

from fastmcp import FastMCP
from fastmcp.apps import AppConfig
from pydantic import Field, model_validator

from sidekick.contacts.application.service import (
    CreateContactCommand,
    UpdateContactCommand,
    contact_public_data,
)
from sidekick.mcp.annotations import DESTRUCTIVE, READ, WRITE
from sidekick.mcp.correlation import request_correlation_id_or_new
from sidekick.mcp.idempotency import IdempotencyKey
from sidekick.mcp.results import output_schema, result, spoken_names
from sidekick.mcp.sidekick_app import SIDEKICK_APP_URI
from sidekick.mcp.text import CONTACT_CARD_NOTE, flat, rows_text
from sidekick.mcp.tool_context import ToolContext
from sidekick.shared.text_guard import NoImageData
from sidekick.shared.types import MAX_CURSOR_LENGTH, UNSET
from sidekick.structured.base import Output
from sidekick.structured.contacts import (
    ContactSummaryRecord,
    TaskContactPageRecord,
    task_contacts_structured,
)


class ContactPageResult(Output):
    contacts: list[ContactSummaryRecord]
    next_cursor: str | None = None
    # The search this page answered, so a view shows and repeats the same filters with its cursor.
    q: str | None = None
    include_archived: bool = False


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
    # Shown to the Contact app and to the model (D-060).
    address: str | None = None
    aliases: list[ContactAliasRecord]
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
_Cursor = Annotated[str | None, Field(max_length=MAX_CURSOR_LENGTH)]
_Relationship = Annotated[str | None, Field(max_length=80), NoImageData]
_Organization = Annotated[str | None, Field(max_length=200), NoImageData]
_Role = Annotated[str | None, Field(max_length=120), NoImageData]
_Address = Annotated[str | None, Field(max_length=500), NoImageData]


class ContactChanges(Output):
    display_name: Annotated[str | None, Field(min_length=1, max_length=200), NoImageData] = None
    context_note: Annotated[str | None, Field(max_length=10000), NoImageData] = None
    email: Annotated[str | None, Field(max_length=320), NoImageData] = None
    phone: Annotated[str | None, Field(max_length=64), NoImageData] = None
    relationship: _Relationship = None
    organization: _Organization = None
    role: _Role = None
    address: _Address = None

    @model_validator(mode="after")
    def require_change(self) -> ContactChanges:
        if not self.model_fields_set:
            raise ValueError("at least one change is required")
        if "display_name" in self.model_fields_set and self.display_name is None:
            raise ValueError("display_name cannot be null")
        return self


# Last line after a near match of a misheard name: confirm, then alias instead of a duplicate.
CLOSEST_HINT = (
    "Not an exact match; confirm the name with the user. If they confirm, add the heard "
    "spelling with add_contact_alias instead of creating a new Contact."
)
# Last line of list_contacts when a search has no hits: points Claude at the fuzzy search first.
NO_MATCH_HINT = "No match by name or alias; try search (kinds contacts) before creating."


def _profile_suffix(contact: dict[str, Any]) -> str:
    parts = [
        flat(contact[key], limit=200)
        for key in ("relationship", "role", "organization")
        if contact.get(key)
    ]
    return f" | {', '.join(parts)}" if parts else ""


# Model-facing summary lines (block 1) carry the ids the model needs for the next call.
def _contact_row(contact: dict[str, Any]) -> str:
    return (
        f"- {contact['id']} | {flat(contact['display_name'])} | v{contact['version']}"
        f"{_profile_suffix(contact)}"
    )


def _count(number: int, one: str, many: str) -> str:
    """A count with its noun, singular for one, so the spoken line reads right."""
    return f"{number} {one if number == 1 else many}"


# The spoken sentence (name, no id) comes first; line 2 keeps the id and version for the next call.
def _contact_summary(sentence: str, contact: dict[str, Any]) -> str:
    return f"{sentence}\nContact {contact['id']} v{contact['version']}."


def _linked_contact_name(ctx: ToolContext, contact_id: UUID) -> str:
    """The Contact's name for a link reply. Without contacts:read the reply stays generic."""
    actor = ctx.actor_provider()
    if "contacts:read" not in actor.scopes:
        return "the Contact"
    return flat(ctx.container.contacts.get(actor, contact_id).display_name)


_TASK_PRIORITY_RANK = {"urgent": 0, "high": 1, "normal": 2, "low": 3}


def _brief_identity(contact: dict[str, Any]) -> str:
    """`Name (role, organization).`; the relationship stands in when neither is set."""
    details = [
        flat(contact[key], limit=200) for key in ("role", "organization") if contact.get(key)
    ]
    if not details and contact.get("relationship"):
        details = [flat(contact["relationship"], limit=200)]
    name = flat(contact["display_name"])
    return f"{name} ({', '.join(details)})." if details else f"{name}."


def _urgency(task: dict[str, Any]) -> tuple[bool, bool, float, int]:
    """Sort key, smallest first: a due follow-up, then the earliest due date, then priority."""
    due = task["due_at"]
    due_ts = datetime.fromisoformat(due).timestamp() if due else 0.0
    return (
        not task["follow_up_due"],
        due is None,
        due_ts,
        _TASK_PRIORITY_RANK.get(task["priority"], len(_TASK_PRIORITY_RANK)),
    )


def _brief_tasks(tasks: list[dict[str, Any]], *, more: bool, other: bool = False) -> str:
    """The open Task count and the most urgent one. `more` means the page is not the whole list.

    `other` says the count leaves out the Tasks that wait on this Contact, which are named apart.
    """
    noun = "other open" if other else "open"
    open_tasks = [task for task in tasks if task["status"] != "completed"]
    scope = f" in the first {len(tasks)}" if more else ""
    if not open_tasks:
        return f"No {noun} tasks{scope}."
    urgent = min(open_tasks, key=_urgency)
    if urgent["follow_up_due"]:
        detail = " (follow-up overdue)"
    elif urgent["due_at"]:
        due = datetime.fromisoformat(urgent["due_at"]).date().isoformat()
        detail = f" (due {due})"
    else:
        detail = ""
    count = _count(len(open_tasks), f"{noun} task", f"{noun} tasks")
    if more:
        count = f"At least {count}"
    return f"{count}, most urgent: {flat(urgent['title'], limit=120)}{detail}."


def _is_waited_on(task: dict[str, Any]) -> bool:
    """An open Task that waits on this Contact and has a start date, so its wait can be counted."""
    return (
        task["status"] != "completed"
        and bool(task.get("waiting_on_contact"))
        and task.get("waiting_since") is not None
    )


def _brief_waiting(
    contact: dict[str, Any], waiting: list[dict[str, Any]], *, now: datetime, zone: tzinfo
) -> str:
    """`You are waiting on <name> for 9 days: <title>.`, for the longest wait; more are counted."""
    longest = min(waiting, key=lambda task: datetime.fromisoformat(task["waiting_since"]))
    since = datetime.fromisoformat(longest["waiting_since"]).astimezone(zone).date()
    days = max(0, (now.astimezone(zone).date() - since).days)
    duration = "since today" if days == 0 else f"for {_count(days, 'day', 'days')}"
    suffix = " (follow-up overdue)" if longest["follow_up_due"] else ""
    sentence = (
        f"You are waiting on {flat(contact['display_name'])} {duration}: "
        f"{flat(longest['title'], limit=120)}{suffix}"
    )
    if len(waiting) > 1:
        sentence += f", and {len(waiting) - 1} more"
    return sentence + "."


def _meeting_brief(
    structured: dict[str, Any], *, now: datetime | None = None, zone: tzinfo | None = None
) -> str:
    """Line 1 of the context text: a few plain sentences with no id, safe to read aloud.

    It uses only the data `get_contact_context` already returns. A Task that waits on this Contact
    comes first, as "You are waiting on <name> for 9 days: <title>.", and is left out of the open
    count after it, so "No open tasks" is never said while one waits. The newest linked Journal
    entry is named by its date only; its title stays in the JSON block as before.
    """
    contact = structured["contact"]
    tasks = structured["tasks"]
    waiting = [task for task in tasks["items"] if _is_waited_on(task)]
    others = [task for task in tasks["items"] if not _is_waited_on(task)]
    more = tasks["next_cursor"] is not None
    sentences = [_brief_identity(contact)]
    if waiting:
        sentences.append(
            _brief_waiting(contact, waiting, now=now or datetime.now(UTC), zone=zone or UTC)
        )
        if any(task["status"] != "completed" for task in others) or more:
            sentences.append(_brief_tasks(others, more=more, other=True))
    else:
        sentences.append(_brief_tasks(others, more=more))
    journal = structured["journal_entries"]
    if journal["readable"] and journal["items"]:
        sentences.append(f"Latest linked journal entry: {journal['items'][0]['journal_date']}.")
    return " ".join(sentences)


def _contact_context_text(
    structured: dict[str, Any], *, now: datetime | None = None, zone: tzinfo | None = None
) -> str:
    contact = structured["contact"]
    projects = structured["projects"]["items"]
    tasks = structured["tasks"]["items"]
    lines = [
        _meeting_brief(structured, now=now, zone=zone),
        f"Contact {contact['id']} v{contact['version']}",
    ]
    for label, key in (
        ("Relationship", "relationship"),
        ("Organization", "organization"),
        ("Role", "role"),
    ):
        if contact.get(key):
            lines.append(f"{label}: {flat(contact[key], limit=200)}")
    if contact["context_note"]:
        lines.append(f"Context: {flat(contact['context_note'], limit=500)}")
    lines.extend(f"- alias {alias['id']} | {flat(alias['value'])}" for alias in contact["aliases"])
    lines.append(f"Projects: {len(projects)}")
    lines.extend(
        f"- project {p['id']} | {flat(p['title'])} | {p['status']} | v{p['version']}"
        for p in projects
    )
    lines.append(f"Tasks: {len(tasks)}")
    lines.extend(
        f"- task {t['id']} | {flat(t['title'])} | {t['status']} | v{t['version']}"
        + (" | waiting on contact" if t["waiting_on_contact"] else "")
        for t in tasks
    )
    journal = structured["journal_entries"]
    entries = journal["items"]
    if not journal["readable"]:
        lines.append("Journal entries: not readable with this session's scopes")
    elif not entries:
        lines.append("Journal entries: no linked journal entries")
    else:
        more = " (older links not shown)" if journal["has_more"] else ""
        lines.append(f"Journal entries: {len(entries)} newest{more}")
        lines.extend(
            # Ids and dates here; the titles are in block 2 (D-060).
            f"- journal entry {e['id']} | {e['journal_date']}"
            for e in entries
        )
    lines.append(CONTACT_CARD_NOTE)
    return "\n".join(lines)


def _summary_record(item: Any) -> ContactSummaryRecord:
    return ContactSummaryRecord(
        id=item.id,
        display_name=item.display_name,
        archived=item.archived,
        updated_at=item.updated_at,
        version=item.version,
        relationship=item.relationship,
        organization=item.organization,
        role=item.role,
    )


def _closest_contacts(ctx: ToolContext, q: str) -> list[Any]:
    """Contacts close to a misheard name, empty without contacts:read or any near match."""
    actor = ctx.actor_provider()
    return [
        ctx.container.contacts.get(actor, hit.id)
        for hit in ctx.container.search.closest_contacts(actor, q)
    ]


def _closest_reply(structured: dict[str, Any], closest: list[Any]) -> Any:
    """A misheard name ("Elijas" for "Elias"): the same word-level search as `search`."""
    structured["contacts"] = [_summary_record(item).model_dump(mode="json") for item in closest]
    names = [item.display_name for item in closest]
    label = "Closest match" if len(names) == 1 else "Closest matches"
    header = f"{label}: {spoken_names(names, total=len(names))}?"
    text = rows_text(header, [_contact_row(contact) for contact in structured["contacts"]])
    return result(structured, f"{text}\n{CLOSEST_HINT}")


def _contact_result(contact: Any) -> dict[str, Any]:
    return ContactResult(
        contact=ContactRecord.model_validate(contact_public_data(contact))
    ).model_dump(mode="json")


def _project_context_page(page: Any) -> ProjectContextPageRecord:
    return ProjectContextPageRecord(
        items=[
            ProjectSummaryRecord(
                id=p.id,
                title=p.title,
                status=p.status.value,
                updated_at=p.updated_at,
                version=p.version,
            )
            for p in page.items
        ],
        next_cursor=page.next_cursor,
    )


def _task_context_page(page: Any, marks: Mapping[UUID, Mapping[str, Any]]) -> TaskContextPageRecord:
    return TaskContextPageRecord(
        items=[
            TaskSummaryRecord(
                id=t.id,
                project_id=t.project_id,
                title=t.title,
                status=t.status.value,
                priority=t.priority.value,
                due_at=t.due_at,
                updated_at=t.updated_at,
                version=t.version,
                waiting_on_contact=marks[t.id]["waiting_on_contact"],
                waiting_since=marks[t.id]["waiting_since"],
                follow_up_at=marks[t.id]["follow_up_at"],
                follow_up_due=marks[t.id]["follow_up_due"],
            )
            for t in page.items
        ],
        next_cursor=page.next_cursor,
    )


def _journal_context(entries: Any) -> JournalEntryContextRecord:
    return JournalEntryContextRecord(
        items=[
            JournalEntryLinkRecord(id=entry.id, journal_date=entry.journal_date, title=entry.title)
            for entry in entries.items
        ],
        has_more=entries.has_more,
        readable=entries.readable,
    )


def _update_command(changes: ContactChanges) -> UpdateContactCommand:
    """Fields the caller sent are mapped; the rest stay UNSET."""

    def sent(name: str) -> Any:
        return getattr(changes, name) if name in changes.model_fields_set else UNSET

    return UpdateContactCommand(
        display_name=cast(str, sent("display_name")),
        context_note=sent("context_note"),
        email=sent("email"),
        phone=sent("phone"),
        relationship=sent("relationship"),
        organization=sent("organization"),
        role=sent("role"),
        address=sent("address"),
    )


def _project_link_result(res: Mapping[str, Any]) -> dict[str, Any]:
    return ProjectContactResult(
        contact_id=UUID(res["contact_id"]),
        project_id=UUID(res["project_id"]),
        linked=res["linked"],
    ).model_dump(mode="json")


def _task_link_result(res: Mapping[str, Any]) -> dict[str, Any]:
    return TaskContactResult(
        contact_id=UUID(res["contact_id"]),
        task_id=UUID(res["task_id"]),
        linked=res["linked"],
    ).model_dump(mode="json")


def _register_list_contacts(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="list_contacts",
        description=(
            "Use this to resolve a person the user mentions (name, alias, email or phone) to a "
            "Contact id. It returns a bounded set of the authenticated user's Contacts matching "
            "preferred name, alias, or exact email/phone. If exactly one active Contact matches, "
            "use its id. If several match, ask the user which one, briefly naming the candidates. "
            'If no match, try search with kinds=["contacts"] before creating; create the Contact '
            "only when the user is describing a new person. "
            "Duplicate candidates are returned separately."
        ),
        output_schema=output_schema(ContactPageResult),
        annotations=READ,
    )
    @ctx.instrument("list_contacts")
    def list_contacts(
        q: Annotated[str | None, Field(min_length=1, max_length=200)] = None,
        include_archived: bool = False,
        limit: Annotated[int, Field(ge=1, le=100)] = 25,
        cursor: _Cursor = None,
    ) -> Any:
        page = ctx.container.contacts.list(
            ctx.actor_provider(),
            q=q,
            include_archived=include_archived,
            limit=limit,
            cursor=cursor,
        )
        structured = ContactPageResult(
            contacts=[_summary_record(item) for item in page.items],
            next_cursor=page.next_cursor,
            q=q,
            include_archived=include_archived,
        ).model_dump(mode="json")
        closest = _closest_contacts(ctx, q) if not page.items and q and cursor is None else []
        if closest:
            return _closest_reply(structured, closest)
        if page.items:
            names = spoken_names([item.display_name for item in page.items], total=len(page.items))
            header = f"{_count(len(page.items), 'contact', 'contacts')}: {names}."
        else:
            header = "No contacts found."
        text = rows_text(header, [_contact_row(contact) for contact in structured["contacts"]])
        if not page.items:
            text = f"{text}\n{NO_MATCH_HINT}"
        return result(structured, text)


def _register_get_contact_context(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="get_contact_context",
        description=(
            "Use this after the Contact id is known, for example from list_contacts or "
            "create_contact, to retrieve that owned active Contact, bounded current "
            "Project/Task context and up to 10 newest linked Journal entries (id, date and "
            "title only; read a Journal entry for its content), or to answer who a Contact is. "
            "Do not use it to retrieve archived/future-domain data or read another user's context. "
            "When the app card opens, reply in one or two sentences and do not repeat its contents "
            "as a list or table."
        ),
        output_schema=output_schema(ContactContextResult),
        annotations=READ,
        app=AppConfig(resource_uri=SIDEKICK_APP_URI),
    )
    @ctx.instrument("get_contact_context")
    def get_contact_context(
        contact_id: UUID,
        project_limit: Annotated[int, Field(ge=1, le=25)] = 10,
        project_cursor: _Cursor = None,
        task_limit: Annotated[int, Field(ge=1, le=25)] = 10,
        task_cursor: _Cursor = None,
        include_completed: bool = False,
    ) -> Any:
        container = ctx.container
        res = container.contacts.get_contact_context(
            ctx.actor_provider(),
            contact_id,
            project_limit=project_limit,
            project_cursor=project_cursor,
            task_limit=task_limit,
            task_cursor=task_cursor,
            include_completed=include_completed,
        )
        structured = ContactContextResult(
            contact=ContactRecord.model_validate(contact_public_data(res["contact"])),
            projects=_project_context_page(res["projects"]),
            tasks=_task_context_page(res["tasks"], res["task_marks"]),
            journal_entries=_journal_context(res["journal_entries"]),
        ).model_dump(mode="json")
        return result(
            structured,
            _contact_context_text(
                structured, now=datetime.now(UTC), zone=container.settings.owner_zone
            ),
        )


def _register_list_task_contacts(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="list_task_contacts",
        description=(
            "Use this after a Task UUID is known to list the owned Contacts linked to that Task "
            "as a bounded, paginated page of Contact summaries. Do not use it to read another "
            "user's Task."
        ),
        output_schema=output_schema(TaskContactPageRecord),
        annotations=READ,
    )
    @ctx.instrument("list_task_contacts")
    def list_task_contacts(
        task_id: UUID,
        limit: Annotated[int, Field(ge=1, le=50)] = 20,
        cursor: _Cursor = None,
    ) -> Any:
        structured = task_contacts_structured(
            ctx.container, ctx.actor_provider(), task_id, limit=limit, cursor=cursor
        )
        return result(
            structured,
            rows_text(
                f"Found {len(structured['items'])} linked Contacts.",
                [_contact_row(contact) for contact in structured["items"]],
            ),
        )


def _register_create_contact(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="create_contact",
        description=(
            "Use this only when the user has asked to create one Contact. Optional aliases "
            "and metadata are stored only in Sidekick; no message or external lookup occurs. "
            "Safe to retry with the "
            "same key and payload."
        ),
        output_schema=output_schema(ContactResult),
        annotations=WRITE,
        app=AppConfig(resource_uri=SIDEKICK_APP_URI),
    )
    @ctx.instrument("create_contact")
    def create_contact(
        display_name: Annotated[str, NoImageData],
        idempotency_key: IdempotencyKey,
        context_note: Annotated[str | None, NoImageData] = None,
        email: Annotated[str | None, NoImageData] = None,
        phone: Annotated[str | None, NoImageData] = None,
        aliases: list[Annotated[str, NoImageData]] | None = None,
        relationship: _Relationship = None,
        organization: _Organization = None,
        role: _Role = None,
        address: _Address = None,
    ) -> Any:
        cmd = CreateContactCommand(
            display_name=display_name,
            context_note=context_note,
            email=email,
            phone=phone,
            aliases=aliases,
            relationship=relationship,
            organization=organization,
            role=role,
            address=address,
        )
        contact = ctx.container.contacts.create(
            ctx.actor_provider(),
            command=cmd,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        structured = _contact_result(contact)
        record = structured["contact"]
        return result(
            structured,
            _contact_summary(f"Created contact {flat(record['display_name'])}.", record),
        )


def _register_update_contact(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="update_contact",
        description=(
            "Use this for explicit edits to one known owned active Contact. Supply the "
            "observed version; omitted fields stay unchanged and explicit null clears "
            "optional metadata. Do not use this "
            "for aliases or work links."
        ),
        output_schema=output_schema(ContactResult),
        annotations=WRITE,
        app=AppConfig(resource_uri=SIDEKICK_APP_URI),
    )
    @ctx.instrument("update_contact")
    def update_contact(
        contact_id: UUID,
        expected_version: int,
        idempotency_key: IdempotencyKey,
        changes: ContactChanges,
    ) -> Any:
        contact = ctx.container.contacts.update(
            ctx.actor_provider(),
            contact_id=contact_id,
            expected_version=expected_version,
            command=_update_command(changes),
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        structured = _contact_result(contact)
        record = structured["contact"]
        return result(
            structured,
            _contact_summary(f"Updated contact {flat(record['display_name'])}.", record),
        )


def _register_archive_contact(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="archive_contact",
        description=(
            "Use this when the user explicitly wants to hide one known Contact from active views. "
            "Archive is reversible, preserves typed links, and does not delete Contact data."
        ),
        output_schema=output_schema(ContactResult),
        annotations=WRITE,
    )
    @ctx.instrument("archive_contact")
    def archive_contact(
        contact_id: UUID, expected_version: int, idempotency_key: IdempotencyKey
    ) -> Any:
        contact = ctx.container.contacts.archive(
            ctx.actor_provider(),
            contact_id=contact_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        structured = _contact_result(contact)
        # The version changes on archive, so the id and new version stay in the text for restore.
        record = structured["contact"]
        return result(
            structured,
            _contact_summary(
                f"Archived contact {flat(record['display_name'])}; "
                "its data and links remain restorable.",
                record,
            ),
        )


def _register_restore_contact(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="restore_contact",
        description=(
            "Use this when the user explicitly wants to return one archived owned Contact "
            "to active "
            "views. It does not restore or modify related Projects or Tasks."
        ),
        output_schema=output_schema(ContactResult),
        annotations=WRITE,
    )
    @ctx.instrument("restore_contact")
    def restore_contact(
        contact_id: UUID, expected_version: int, idempotency_key: IdempotencyKey
    ) -> Any:
        contact = ctx.container.contacts.restore(
            ctx.actor_provider(),
            contact_id=contact_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        structured = _contact_result(contact)
        record = structured["contact"]
        return result(
            structured,
            _contact_summary(f"Restored contact {flat(record['display_name'])}.", record),
        )


def _register_add_contact_alias(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="add_contact_alias",
        description=(
            "Use this to add one alternative name to a known active Contact using its "
            "current version. Equivalent aliases on the same Contact are not duplicated; "
            "the same alias may identify "
            "other Contacts."
        ),
        output_schema=output_schema(ContactResult),
        annotations=WRITE,
    )
    @ctx.instrument("add_contact_alias")
    def add_contact_alias(
        contact_id: UUID, value: str, expected_version: int, idempotency_key: IdempotencyKey
    ) -> Any:
        contact = ctx.container.contacts.add_alias(
            ctx.actor_provider(),
            contact_id=contact_id,
            value=value,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        structured = _contact_result(contact)
        record = structured["contact"]
        return result(
            structured,
            _contact_summary(f"Added the Contact alias to {flat(record['display_name'])}.", record),
        )


def _register_remove_contact_alias(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="remove_contact_alias",
        description=(
            "Use this only when the user wants to remove one known alias ID from an active "
            "Contact. "
            "It deletes that alias record but not the Contact or any work link."
        ),
        output_schema=output_schema(ContactResult),
        annotations=DESTRUCTIVE,
        app=AppConfig(visibility=["app"]),
    )
    @ctx.instrument("remove_contact_alias")
    def remove_contact_alias(
        contact_id: UUID, alias_id: UUID, expected_version: int, idempotency_key: IdempotencyKey
    ) -> Any:
        contact = ctx.container.contacts.remove_alias(
            ctx.actor_provider(),
            contact_id=contact_id,
            alias_id=alias_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        return result(_contact_result(contact), "Removed the Contact alias.")


def _register_link_contact_to_project(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="link_contact_to_project",
        description=(
            "Use this after the Contact and Project ids are known, for example from list_contacts, "
            "create_contact, list_projects or get_work_hierarchy. "
            "It records that the Project involves the Contact; it does not alter either "
            "record or contact an external system."
        ),
        output_schema=output_schema(ProjectContactResult),
        annotations=WRITE,
    )
    @ctx.instrument("link_contact_to_project")
    def link_contact_to_project(
        contact_id: UUID, project_id: UUID, idempotency_key: IdempotencyKey
    ) -> Any:
        res = ctx.container.contacts.link_project(
            ctx.actor_provider(),
            contact_id=contact_id,
            project_id=project_id,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        name = _linked_contact_name(ctx, contact_id)
        return result(_project_link_result(res), f"Linked {name} and the Project.")


def _register_unlink_contact_from_project(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="unlink_contact_from_project",
        description=(
            "Use this only when the user wants to remove the known Contact–Project relation. "
            "It deletes the semantic link but does not delete or edit the Contact or Project."
        ),
        output_schema=output_schema(ProjectContactResult),
        annotations=DESTRUCTIVE,
        app=AppConfig(visibility=["app"]),
    )
    @ctx.instrument("unlink_contact_from_project")
    def unlink_contact_from_project(
        contact_id: UUID, project_id: UUID, idempotency_key: IdempotencyKey
    ) -> Any:
        res = ctx.container.contacts.unlink_project(
            ctx.actor_provider(),
            contact_id=contact_id,
            project_id=project_id,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        return result(_project_link_result(res), "Removed the Contact–Project link.")


def _register_link_contact_to_task(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="link_contact_to_task",
        description=(
            "Use this after the Contact and Task ids are known, for example from list_contacts, "
            "create_contact, list_projects or get_work_hierarchy. "
            "It records that the Task concerns the Contact; it does not alter either "
            "record or contact an external system."
        ),
        output_schema=output_schema(TaskContactResult),
        annotations=WRITE,
    )
    @ctx.instrument("link_contact_to_task")
    def link_contact_to_task(
        contact_id: UUID, task_id: UUID, idempotency_key: IdempotencyKey
    ) -> Any:
        res = ctx.container.contacts.link_task(
            ctx.actor_provider(),
            contact_id=contact_id,
            task_id=task_id,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        name = _linked_contact_name(ctx, contact_id)
        return result(_task_link_result(res), f"Linked {name} and the Task.")


def _register_unlink_contact_from_task(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="unlink_contact_from_task",
        description=(
            "Use this only when the user wants to remove the known Contact–Task relation. "
            "It deletes the semantic link but does not delete or edit the Contact or Task."
        ),
        output_schema=output_schema(TaskContactResult),
        annotations=DESTRUCTIVE,
        app=AppConfig(visibility=["app"]),
    )
    @ctx.instrument("unlink_contact_from_task")
    def unlink_contact_from_task(
        contact_id: UUID, task_id: UUID, idempotency_key: IdempotencyKey
    ) -> Any:
        res = ctx.container.contacts.unlink_task(
            ctx.actor_provider(),
            contact_id=contact_id,
            task_id=task_id,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        return result(_task_link_result(res), "Removed the Contact–Task link.")


_REGISTRARS = (
    _register_list_contacts,
    _register_get_contact_context,
    _register_list_task_contacts,
    _register_create_contact,
    _register_update_contact,
    _register_archive_contact,
    _register_restore_contact,
    _register_add_contact_alias,
    _register_remove_contact_alias,
    _register_link_contact_to_project,
    _register_unlink_contact_from_project,
    _register_link_contact_to_task,
    _register_unlink_contact_from_task,
)


def register_contacts_tools(mcp: FastMCP, ctx: ToolContext) -> None:
    """Register all 13 curated Contact and relationship tools."""
    for register in _REGISTRARS:
        register(mcp, ctx)
