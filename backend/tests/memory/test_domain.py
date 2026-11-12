"""Pure memory rules: candidate filters, golden documents, forbidden fields, fingerprints."""

from dataclasses import fields
from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from sidekick.journal.domain.entry import KeyPointKind
from sidekick.memory import domain
from sidekick.memory.domain import (
    ContactInput,
    JournalEntryInput,
    KeyPointInput,
    LinkedContactInput,
    MemoryDocument,
    MemoryKind,
    ProjectInput,
    TaskInput,
    canonical_document,
    is_memory_candidate,
)
from sidekick.projects.domain import ProjectStatus
from sidekick.tasks.domain import Priority, Task, TaskStatus

LONG_TASK_TEXT = "x" * 120
MID_TEXT = "y" * 40


def journal_entry(**overrides: object) -> JournalEntryInput:
    values: dict[str, object] = {
        "journal_date": date(2026, 10, 12),
        "title": "Ny jobb",
        "summary": "Sara bytte jobb till Volvo.",
        "key_points": (
            KeyPointInput(KeyPointKind.FACT, "Sara arbetar nu på Volvo"),
            KeyPointInput(KeyPointKind.DECISION, "Jag säger upp mig"),
        ),
        "raw_text": "Lång text\nandra raden",
        "contacts": (LinkedContactInput("Sara", "kollega"), LinkedContactInput("Anna")),
        "project_titles": ("Karriär",),
    }
    values.update(overrides)
    return JournalEntryInput(**values)  # type: ignore[arg-type]


def contact(**overrides: object) -> ContactInput:
    values: dict[str, object] = {
        "display_name": "Sara Lindqvist",
        "aliases": ("Saran",),
        "relationship": "kollega",
        "organization": "Volvo",
        "role": "Ingenjör",
        "context_note": "Träffas på torsdagar.",
    }
    values.update(overrides)
    return ContactInput(**values)  # type: ignore[arg-type]


def project(**overrides: object) -> ProjectInput:
    values: dict[str, object] = {
        "title": "Köksrenovering",
        "description": "Byta stommen i köket och nya skåp.",
        "definition_of_done": "Köket används varje dag igen.",
        "status": ProjectStatus.COMPLETED,
        "start_date": date(2026, 1, 5),
        "target_date": date(2026, 6, 30),
        "contact_names": ("Sara", "Anna"),
    }
    values.update(overrides)
    return ProjectInput(**values)  # type: ignore[arg-type]


def task(**overrides: object) -> TaskInput:
    values: dict[str, object] = {
        "title": "Ring försäkringsbolaget",
        "description": "Be dem skicka om offerten för bilförsäkringen, och fråga om självrisken.",
        "project_title": "Bilen",
        "contact_names": ("Sara",),
        "completed_on": date(2026, 10, 20),
        "is_recurring": False,
    }
    values.update(overrides)
    return TaskInput(**values)  # type: ignore[arg-type]


def document_of(record: domain.MemoryRecord) -> MemoryDocument:
    document = canonical_document(record)
    assert document is not None
    return document


# --- Golden documents -------------------------------------------------------------------------


def test_journal_entry_golden_document() -> None:
    document = document_of(journal_entry())

    assert document.kind is MemoryKind.JOURNAL_ENTRY
    assert document.text == (
        "Dagbok 2026-10-12\n"
        "Titel: Ny jobb\n"
        "Sammanfattning: Sara bytte jobb till Volvo.\n"
        "Nyckelpunkter:\n"
        "- Fakta: Sara arbetar nu på Volvo\n"
        "- Beslut: Jag säger upp mig\n"
        "Kopplade personer: Anna; Sara (kollega)\n"
        "Kopplade projekt: Karriär\n"
        "Råtext:\n"
        "Lång text\n"
        "andra raden"
    )
    assert document.context == "Sidekicks dagbok"
    assert document.tags == ("k:journal_entry",)
    assert document.entities == ("Anna", "Sara")
    assert document.event_date == date(2026, 10, 12)


def test_journal_entry_raw_text_is_sent_without_character_cap() -> None:
    raw = "ord " * 5_000  # 20 000 characters, well above the design's superseded 8 000 cap
    document = document_of(journal_entry(raw_text=raw))

    assert document.text.endswith("Råtext:\n" + raw.strip())


def test_journal_entry_minimal_has_only_title_and_date() -> None:
    document = document_of(
        journal_entry(
            summary="   ",
            key_points=(),
            raw_text=None,
            contacts=(),
            project_titles=(),
        )
    )

    assert document.text == "Dagbok 2026-10-12\nTitel: Ny jobb"
    assert document.entities == ()


def test_contact_golden_document() -> None:
    document = document_of(contact())

    assert document.kind is MemoryKind.CONTACT
    assert document.text == (
        "Kontakt: Sara Lindqvist\n"
        "Alias: Saran\n"
        "Relation: kollega\n"
        "Organisation: Volvo\n"
        "Roll: Ingenjör\n"
        "Kontext: Träffas på torsdagar."
    )
    assert document.context == "Sidekicks kontakter"
    assert document.tags == ("k:contact",)
    assert document.entities == ("Sara Lindqvist",)
    assert document.event_date is None


def test_project_golden_document_with_completed_status() -> None:
    document = document_of(project())

    assert document.kind is MemoryKind.PROJECT
    assert document.text == (
        "Projekt: Köksrenovering\n"
        "Beskrivning: Byta stommen i köket och nya skåp.\n"
        "Klart när: Köket används varje dag igen.\n"
        "Startdatum: 2026-01-05\n"
        "Måldatum: 2026-06-30\n"
        "Slutstatus: avslutat\n"
        "Kopplade personer: Anna; Sara"
    )
    assert document.context == "Sidekicks projekt"
    assert document.tags == ("k:project",)
    assert document.entities == ("Anna", "Sara")
    assert document.event_date == date(2026, 1, 5)


def test_project_golden_document_running_status_is_not_sent() -> None:
    document = document_of(project(status=ProjectStatus.PAUSED, contact_names=("Anna",)))

    assert document.text == (
        "Projekt: Köksrenovering\n"
        "Beskrivning: Byta stommen i köket och nya skåp.\n"
        "Klart när: Köket används varje dag igen.\n"
        "Startdatum: 2026-01-05\n"
        "Måldatum: 2026-06-30\n"
        "Kopplade personer: Anna"
    )
    assert "paused" not in document.text
    assert "Slutstatus" not in document.text


def test_task_golden_document() -> None:
    document = document_of(task())

    assert document.kind is MemoryKind.TASK
    assert document.text == (
        "Uppgift: Ring försäkringsbolaget\n"
        "Projekt: Bilen\n"
        "Beskrivning: Be dem skicka om offerten för bilförsäkringen, och fråga om självrisken.\n"
        "Kopplade personer: Sara\n"
        "Slutförd: 2026-10-20"
    )
    assert document.context == "Sidekicks uppgifter"
    assert document.tags == ("k:task",)
    assert document.entities == ("Sara",)
    assert document.event_date == date(2026, 10, 20)


# --- Candidate rules --------------------------------------------------------------------------


def test_journal_entry_is_always_a_candidate() -> None:
    assert is_memory_candidate(
        journal_entry(
            title="x",
            summary=None,
            key_points=(),
            raw_text=None,
            contacts=(),
            project_titles=(),
        )
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"context_note": "Träffas på torsdagar."},
        {"relationship": "syster"},
        {"organization": "Volvo"},
        {"role": "Ingenjör"},
    ],
)
def test_contact_is_candidate_with_any_context_field(overrides: dict[str, object]) -> None:
    values: dict[str, object] = {
        "aliases": (),
        "relationship": None,
        "organization": None,
        "role": None,
        "context_note": None,
    }
    values.update(overrides)
    assert is_memory_candidate(contact(**values))


def test_contact_with_only_a_name_and_alias_is_not_a_candidate() -> None:
    bare = contact(
        aliases=("Saran",),
        relationship=None,
        organization=None,
        role=None,
        context_note=None,
    )
    assert not is_memory_candidate(bare)
    assert canonical_document(bare) is None


def test_contact_blank_context_fields_do_not_count() -> None:
    blank = contact(
        relationship="   ",
        organization="",
        role="\n",
        context_note="  ",
    )
    assert not is_memory_candidate(blank)


def test_project_description_threshold_is_forty_characters() -> None:
    assert not is_memory_candidate(
        project(description="a" * 39, definition_of_done=None, contact_names=())
    )
    assert is_memory_candidate(
        project(description="a" * 40, definition_of_done=None, contact_names=())
    )


def test_project_definition_of_done_threshold_is_forty_characters() -> None:
    assert not is_memory_candidate(
        project(description=None, definition_of_done="b" * 39, contact_names=())
    )
    assert is_memory_candidate(
        project(description=None, definition_of_done="b" * 40, contact_names=())
    )


def test_project_threshold_ignores_surrounding_whitespace() -> None:
    padded = project(description="  " + "a" * 39 + "  ", definition_of_done=None, contact_names=())
    assert not is_memory_candidate(padded)


def test_project_with_linked_contact_is_a_candidate_even_when_short() -> None:
    short = project(description="kort", definition_of_done=None, contact_names=("Anna",))
    assert is_memory_candidate(short)


def test_project_without_text_or_contacts_is_not_a_candidate() -> None:
    bare = project(description=None, definition_of_done=None, contact_names=())
    assert canonical_document(bare) is None


def test_task_long_description_is_a_candidate_without_contacts() -> None:
    assert not is_memory_candidate(task(description="a" * 119, contact_names=()))
    assert is_memory_candidate(task(description="a" * 120, contact_names=()))


def test_task_with_contact_needs_only_forty_characters() -> None:
    assert is_memory_candidate(task(description=MID_TEXT, contact_names=("Sara",)))
    assert not is_memory_candidate(task(description="a" * 39, contact_names=("Sara",)))


def test_task_forty_characters_without_contact_is_not_a_candidate() -> None:
    assert not is_memory_candidate(task(description=MID_TEXT, contact_names=()))


def test_recurring_task_is_never_a_candidate() -> None:
    assert canonical_document(task(description=LONG_TASK_TEXT, is_recurring=True)) is None
    assert (
        canonical_document(task(description=MID_TEXT, is_recurring=True, contact_names=("Sara",)))
        is None
    )


# --- Forbidden fields -------------------------------------------------------------------------


def _field_names(record_type: type) -> set[str]:
    return {field.name for field in fields(record_type)}


def test_contact_input_cannot_carry_email_phone_or_address() -> None:
    names = _field_names(ContactInput)
    assert not names & {"email", "email_key", "phone", "phone_key", "address"}
    assert not names & {"id", "owner_id", "version", "archived", "archived_at"}


def test_task_input_cannot_carry_status_priority_due_estimate_or_rank() -> None:
    names = _field_names(TaskInput)
    assert not names & {
        "status",
        "priority",
        "due_at",
        "estimated_minutes",
        "board_rank",
        "not_before",
        "recurrence",
        "waiting_on_contact_id",
    }
    assert not names & {"id", "owner_id", "version", "process_id", "domain_id"}


def test_journal_input_cannot_carry_identifiers_source_or_version() -> None:
    names = _field_names(JournalEntryInput)
    assert not names & {"id", "owner_id", "source_id", "source_recorded_at", "version"}


def test_project_input_has_no_rank_or_contact_identifiers() -> None:
    names = _field_names(ProjectInput)
    assert not names & {"id", "owner_id", "domain_id", "board_rank", "rank"}


@pytest.mark.parametrize(
    "record",
    [journal_entry(), contact(), project(), task()],
    ids=["journal_entry", "contact", "project", "task"],
)
def test_no_forbidden_labels_appear_in_any_document(record: domain.MemoryRecord) -> None:
    text = document_of(record).text
    for forbidden in (
        "Status:",
        "Prioritet",
        "Förfallodatum",
        "Uppskattning",
        "Rank",
        "E-post",
        "Telefon",
        "Adress",
        "Version",
        "owner",
        "source",
        "Id:",
    ):
        assert forbidden not in text


# --- Fingerprints -----------------------------------------------------------------------------


def _task_input_from_domain_task(domain_task: Task) -> TaskInput:
    """Map a domain Task the way the application layer will: allowed fields only."""

    return TaskInput(
        title=domain_task.title,
        description=domain_task.description,
        project_title="Bilen",
        contact_names=("Sara",),
        completed_on=domain_task.completed_at.date() if domain_task.completed_at else None,
        is_recurring=domain_task.recurrence is not None,
    )


def _domain_task(**overrides: object) -> Task:
    now = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
    values: dict[str, object] = {
        "id": UUID("018af000-0000-7000-8000-0000000000aa"),
        "owner_id": UUID("018af000-0000-7000-8000-000000000001"),
        "project_id": None,
        "title": "Ring försäkringsbolaget",
        "description": "Be dem skicka om offerten för bilförsäkringen, och fråga om självrisken.",
        "status": TaskStatus.TODO,
        "priority": Priority.NORMAL,
        "due_at": None,
        "completed_at": None,
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return Task(**values)  # type: ignore[arg-type]


def test_task_status_priority_due_and_estimate_changes_keep_the_fingerprint() -> None:
    base = document_of(_task_input_from_domain_task(_domain_task()))
    variants = [
        _domain_task(status=TaskStatus.IN_PROGRESS),
        _domain_task(status=TaskStatus.BLOCKED),
        _domain_task(priority=Priority.URGENT),
        _domain_task(due_at=datetime(2026, 11, 1, 12, 0, tzinfo=UTC)),
        _domain_task(estimated_minutes=45),
        _domain_task(board_rank=3),
    ]
    for variant in variants:
        assert document_of(_task_input_from_domain_task(variant)).fingerprint == base.fingerprint


def test_task_completion_changes_the_fingerprint_through_the_completion_date() -> None:
    # Design 2.1 lists "slutfört datum" in the task document, so completing a task is a change.
    open_task = document_of(_task_input_from_domain_task(_domain_task()))
    completed = document_of(
        _task_input_from_domain_task(
            _domain_task(
                status=TaskStatus.COMPLETED,
                completed_at=datetime(2026, 10, 20, 15, 0, tzinfo=UTC),
            )
        )
    )
    assert completed.fingerprint != open_task.fingerprint
    assert completed.text.endswith("Slutförd: 2026-10-20")


def test_fingerprint_is_deterministic_and_text_sensitive() -> None:
    first = document_of(contact())
    again = document_of(contact())
    renamed = document_of(contact(context_note="Träffas på fredagar."))

    assert first.fingerprint == again.fingerprint
    assert len(first.fingerprint) == 64
    assert renamed.fingerprint != first.fingerprint


def test_fingerprint_changes_when_a_linked_contact_is_renamed() -> None:
    before = document_of(project(contact_names=("Sara",)))
    after = document_of(project(contact_names=("Sara Lindqvist",)))
    assert before.fingerprint != after.fingerprint


def test_fingerprint_includes_the_pipeline_version(monkeypatch: pytest.MonkeyPatch) -> None:
    current = document_of(contact()).fingerprint
    monkeypatch.setattr(domain, "MEMORY_PIPELINE_VERSION", domain.MEMORY_PIPELINE_VERSION + 1)
    bumped = document_of(contact()).fingerprint
    assert bumped != current


def test_input_order_does_not_change_text_or_fingerprint() -> None:
    forward = document_of(
        journal_entry(
            contacts=(LinkedContactInput("Sara", "kollega"), LinkedContactInput("Anna")),
            project_titles=("Karriär", "Hälsa"),
        )
    )
    backward = document_of(
        journal_entry(
            contacts=(LinkedContactInput("Anna"), LinkedContactInput("Sara", "kollega")),
            project_titles=("Hälsa", "Karriär"),
        )
    )
    assert forward.text == backward.text
    assert forward.fingerprint == backward.fingerprint


def test_documents_have_no_document_identifier_or_owner_fields() -> None:
    # doc_key (HMAC), owner, and Sidekick identifiers are assigned outside the pure domain.
    assert {field.name for field in fields(MemoryDocument)} == {
        "kind",
        "text",
        "context",
        "tags",
        "entities",
        "event_date",
        "fingerprint",
    }
