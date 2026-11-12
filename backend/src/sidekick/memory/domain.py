"""Pure derived-memory rules: candidate filters, canonical Hindsight documents, fingerprints.

No database, clock, network, or framework code lives here. The inputs are plain dataclasses that
`sidekick.memory.application.queries` fills from database rows. Each input carries exactly the
fields that are allowed to leave Sidekick, and nothing else.
Forbidden values (contact e-mail, phone and address; identifiers; task status, priority, due date,
estimate and rank; project running status and rank) have no field here, so they cannot reach a
document.

`MEMORY_PIPELINE_VERSION` must be bumped whenever the Hindsight mission or the canonical text format
changes. It is part of every fingerprint, so a bump re-sends every document.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from sidekick.journal.domain.entry import KeyPointKind
from sidekick.projects.domain import ProjectStatus

MEMORY_PIPELINE_VERSION = 1

JOURNAL_CONTEXT = "Sidekicks dagbok"
CONTACT_CONTEXT = "Sidekicks kontakter"
PROJECT_CONTEXT = "Sidekicks projekt"
TASK_CONTEXT = "Sidekicks uppgifter"

PROJECT_TEXT_MIN_CHARS = 40
TASK_LONG_TEXT_MIN_CHARS = 120
TASK_CONTACT_TEXT_MIN_CHARS = 40

_KEY_POINT_LABELS: dict[KeyPointKind, str] = {
    KeyPointKind.FACT: "Fakta",
    KeyPointKind.REFLECTION: "Reflektion",
    KeyPointKind.DECISION: "Beslut",
    KeyPointKind.COMMITMENT: "Åtagande",
    KeyPointKind.QUESTION: "Fråga",
}


class MemoryKind(StrEnum):
    JOURNAL_ENTRY = "journal_entry"
    CONTACT = "contact"
    PROJECT = "project"
    TASK = "task"


@dataclass(frozen=True, slots=True)
class KeyPointInput:
    kind: KeyPointKind
    text: str


@dataclass(frozen=True, slots=True)
class LinkedContactInput:
    name: str
    relationship: str | None = None


@dataclass(frozen=True, slots=True)
class JournalEntryInput:
    """A stored, finalized journal entry. Its raw text is sent without a character cap."""

    journal_date: date
    title: str
    summary: str | None
    key_points: tuple[KeyPointInput, ...]
    raw_text: str | None
    contacts: tuple[LinkedContactInput, ...]
    project_titles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ContactInput:
    """A Contact. Email, phone and address are deliberately not representable here."""

    display_name: str
    aliases: tuple[str, ...]
    relationship: str | None
    organization: str | None
    role: str | None
    context_note: str | None


@dataclass(frozen=True, slots=True)
class ProjectInput:
    """A Project. Its running status and rank are deliberately not representable here."""

    title: str
    description: str | None
    definition_of_done: str | None
    status: ProjectStatus
    start_date: date | None
    target_date: date | None
    contact_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TaskInput:
    """A Task. Status, priority, due date, estimate and rank are deliberately not representable.

    `contact_names` must include the waiting-on contact when there is one. `completed_on` is the
    completion date in the owner's time zone, computed by the caller.
    """

    title: str
    description: str | None
    project_title: str | None
    contact_names: tuple[str, ...]
    completed_on: date | None
    is_recurring: bool


MemoryRecord = JournalEntryInput | ContactInput | ProjectInput | TaskInput


@dataclass(frozen=True, slots=True)
class MemoryDocument:
    """The exact content sent to Hindsight for one Sidekick record, plus its fingerprint."""

    kind: MemoryKind
    text: str
    context: str
    tags: tuple[str, ...]
    entities: tuple[str, ...]
    event_date: date | None
    fingerprint: str


def _clean(value: str | None) -> str | None:
    """Normalize line endings, trim, and treat blank text as absent."""

    if value is None:
        return None
    cleaned = value.replace("\r\n", "\n").strip()
    return cleaned or None


def _length(value: str | None) -> int:
    return len(_clean(value) or "")


def _has_text(value: str | None) -> bool:
    return _clean(value) is not None


def _sorted_names(names: tuple[str, ...]) -> tuple[str, ...]:
    cleaned = [name.strip() for name in names if name.strip()]
    return tuple(sorted(cleaned, key=lambda name: (name.casefold(), name)))


def _contact_label(contact: LinkedContactInput) -> str:
    relationship = _clean(contact.relationship)
    name = contact.name.strip()
    return f"{name} ({relationship})" if relationship is not None else name


def _journal_is_candidate() -> bool:
    # Every stored entry qualifies. Drafts are never JournalEntry rows.
    return True


def _contact_is_candidate(contact: ContactInput) -> bool:
    return (
        _has_text(contact.context_note)
        or _has_text(contact.relationship)
        or _has_text(contact.organization)
        or _has_text(contact.role)
    )


def _project_is_candidate(project: ProjectInput) -> bool:
    return (
        _length(project.description) >= PROJECT_TEXT_MIN_CHARS
        or _length(project.definition_of_done) >= PROJECT_TEXT_MIN_CHARS
        or bool(_sorted_names(project.contact_names))
    )


def _task_is_candidate(task: TaskInput) -> bool:
    if task.is_recurring:
        return False
    description_length = _length(task.description)
    return description_length >= TASK_LONG_TEXT_MIN_CHARS or (
        bool(_sorted_names(task.contact_names))
        and description_length >= TASK_CONTACT_TEXT_MIN_CHARS
    )


def is_memory_candidate(record: MemoryRecord) -> bool:
    """Return whether a record may be sent to memory at all, before any LLM step."""

    if isinstance(record, JournalEntryInput):
        return _journal_is_candidate()
    if isinstance(record, ContactInput):
        return _contact_is_candidate(record)
    if isinstance(record, ProjectInput):
        return _project_is_candidate(record)
    return _task_is_candidate(record)


def memory_kind_of(record: MemoryRecord) -> MemoryKind:
    if isinstance(record, JournalEntryInput):
        return MemoryKind.JOURNAL_ENTRY
    if isinstance(record, ContactInput):
        return MemoryKind.CONTACT
    if isinstance(record, ProjectInput):
        return MemoryKind.PROJECT
    return MemoryKind.TASK


def _fingerprint(
    *,
    kind: MemoryKind,
    text: str,
    context: str,
    tags: tuple[str, ...],
    entities: tuple[str, ...],
    event_date: date | None,
) -> str:
    payload: dict[str, object] = {
        "pipeline_version": MEMORY_PIPELINE_VERSION,
        "kind": kind.value,
        "text": text,
        "context": context,
        "tags": list(tags),
        "entities": list(entities),
        "event_date": event_date.isoformat() if event_date is not None else None,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _document(
    kind: MemoryKind,
    *,
    text: str,
    context: str,
    entities: tuple[str, ...],
    event_date: date | None,
) -> MemoryDocument:
    tags = (f"k:{kind.value}",)
    return MemoryDocument(
        kind=kind,
        text=text,
        context=context,
        tags=tags,
        entities=entities,
        event_date=event_date,
        fingerprint=_fingerprint(
            kind=kind,
            text=text,
            context=context,
            tags=tags,
            entities=entities,
            event_date=event_date,
        ),
    )


def _journal_document(entry: JournalEntryInput) -> MemoryDocument:
    contacts = sorted(entry.contacts, key=lambda contact: (contact.name.casefold(), contact.name))
    lines = [
        f"Dagbok {entry.journal_date.isoformat()}",
        f"Titel: {entry.title.strip()}",
    ]
    summary = _clean(entry.summary)
    if summary is not None:
        lines.append(f"Sammanfattning: {summary}")
    if entry.key_points:
        lines.append("Nyckelpunkter:")
        for point in entry.key_points:
            lines.append(f"- {_KEY_POINT_LABELS[point.kind]}: {_clean(point.text) or ''}")
    if contacts:
        labels = "; ".join(_contact_label(contact) for contact in contacts)
        lines.append(f"Kopplade personer: {labels}")
    projects = _sorted_names(entry.project_titles)
    if projects:
        lines.append(f"Kopplade projekt: {'; '.join(projects)}")
    raw_text = _clean(entry.raw_text)
    if raw_text is not None:
        lines.append("Råtext:")
        lines.append(raw_text)
    return _document(
        MemoryKind.JOURNAL_ENTRY,
        text="\n".join(lines),
        context=JOURNAL_CONTEXT,
        entities=_sorted_names(tuple(contact.name for contact in contacts)),
        event_date=entry.journal_date,
    )


def _contact_document(contact: ContactInput) -> MemoryDocument:
    name = contact.display_name.strip()
    lines = [f"Kontakt: {name}"]
    aliases = _sorted_names(contact.aliases)
    if aliases:
        lines.append(f"Alias: {'; '.join(aliases)}")
    for label, value in (
        ("Relation", contact.relationship),
        ("Organisation", contact.organization),
        ("Roll", contact.role),
        ("Kontext", contact.context_note),
    ):
        cleaned = _clean(value)
        if cleaned is not None:
            lines.append(f"{label}: {cleaned}")
    return _document(
        MemoryKind.CONTACT,
        text="\n".join(lines),
        context=CONTACT_CONTEXT,
        entities=(name,),
        event_date=None,
    )


def _project_document(project: ProjectInput) -> MemoryDocument:
    lines = [f"Projekt: {project.title.strip()}"]
    for label, value in (
        ("Beskrivning", project.description),
        ("Klart när", project.definition_of_done),
    ):
        cleaned = _clean(value)
        if cleaned is not None:
            lines.append(f"{label}: {cleaned}")
    if project.start_date is not None:
        lines.append(f"Startdatum: {project.start_date.isoformat()}")
    if project.target_date is not None:
        lines.append(f"Måldatum: {project.target_date.isoformat()}")
    # Only a final outcome is part of memory. A running status is never sent.
    if project.status is ProjectStatus.COMPLETED:
        lines.append("Slutstatus: avslutat")
    contacts = _sorted_names(project.contact_names)
    if contacts:
        lines.append(f"Kopplade personer: {'; '.join(contacts)}")
    return _document(
        MemoryKind.PROJECT,
        text="\n".join(lines),
        context=PROJECT_CONTEXT,
        entities=contacts,
        event_date=project.start_date,
    )


def _task_document(task: TaskInput) -> MemoryDocument:
    lines = [f"Uppgift: {task.title.strip()}"]
    project_title = task.project_title.strip() if task.project_title else ""
    if project_title:
        lines.append(f"Projekt: {project_title}")
    description = _clean(task.description)
    if description is not None:
        lines.append(f"Beskrivning: {description}")
    contacts = _sorted_names(task.contact_names)
    if contacts:
        lines.append(f"Kopplade personer: {'; '.join(contacts)}")
    if task.completed_on is not None:
        lines.append(f"Slutförd: {task.completed_on.isoformat()}")
    return _document(
        MemoryKind.TASK,
        text="\n".join(lines),
        context=TASK_CONTEXT,
        entities=contacts,
        event_date=task.completed_on,
    )


def canonical_document(record: MemoryRecord) -> MemoryDocument | None:
    """Return the exact document for a candidate record, or None when it must not be sent."""

    if not is_memory_candidate(record):
        return None
    if isinstance(record, JournalEntryInput):
        return _journal_document(record)
    if isinstance(record, ContactInput):
        return _contact_document(record)
    if isinstance(record, ProjectInput):
        return _project_document(record)
    return _task_document(record)
