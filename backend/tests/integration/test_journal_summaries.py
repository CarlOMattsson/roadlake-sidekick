"""PostgreSQL/application verification for entry lifecycle and manual daily summaries.

Summaries are written by the owner or the connected assistant; the server runs no summary
pipeline of its own, so no processing run is ever created.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text

from sidekick.api.app import Container, create_container
from sidekick.contacts.application.models import CreateContactCommand
from sidekick.journal.domain.analysis import Perspective
from sidekick.journal.domain.entry import KeyPoint, KeyPointKind
from sidekick.journal.domain.source import SourceType
from sidekick.journal.domain.summary import (
    SummaryContent,
    SummaryOrigin,
    SummaryState,
    entry_fingerprint,
)
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings

JOURNAL_DATE = date(2026, 7, 21)
SCOPES = frozenset(
    {
        "journal:read",
        "journal:write",
        "projects:read",
        "projects:write",
        "tasks:read",
        "tasks:write",
        "contacts:read",
        "contacts:write",
    }
)


def summary_content(
    entry_id: object, overview: str = "Dagens manuella översikt."
) -> SummaryContent:
    return SummaryContent.model_validate(
        {
            "overview": overview,
            "overview_entry_ids": [entry_id],
            "themes": [
                {
                    "title": "Uppföljning",
                    "summary": "Nästa steg blev tydliga.",
                    "perspective": Perspective.INTERPRETATION,
                    "entry_ids": [entry_id],
                }
            ],
            "important_events": [
                {
                    "text": "Ett beslut dokumenterades.",
                    "perspective": Perspective.FACT,
                    "entry_ids": [entry_id],
                }
            ],
            "decisions": [],
            "commitments": [],
            "open_questions": [],
            "unresolved_items": [],
            "contradictions": [],
        }
    )


def make_state() -> tuple[Container, Actor]:
    container = create_container(make_settings(), database_factory())
    owner_id = container.auth.provision_user("journal_summary_owner", "Journal summary owner")
    return container, Actor(owner_id, SCOPES)


@pytest.mark.integration
def test_entry_lifecycle_preserves_provenance_relations_and_guarded_manual_summary() -> None:
    container, actor = make_state()
    domain = container.contexts.create_domain(
        actor, name="Operations", description=None, idempotency_key="journal-summary-domain"
    )
    project = container.projects.create(
        actor,
        title="Sammanfattning projekt",
        domain_id=domain.id,
        idempotency_key="journal-summary-project",
    )
    task = container.tasks.create(
        actor,
        title="Sammanfattning uppgift",
        project_id=project.id,
        idempotency_key="journal-summary-task",
    )
    contact = container.contacts.create(
        actor,
        CreateContactCommand(display_name="Sammanfattning kontakt"),
        "journal-summary-contact",
    )
    source = container.journal_capture.create_source(
        actor,
        source_type=SourceType.MANUAL_TEXT,
        journal_date=JOURNAL_DATE,
        occurred_at=datetime(2026, 7, 21, 7, 0, tzinfo=UTC),
        source_recorded_at=datetime(2026, 7, 24, 6, 0, tzinfo=UTC),
        raw_text="En syntetisk källa för sammanfattning.",
        language="sv",
        replaces_source_id=None,
        idempotency_key="journal-summary-source",
    )
    key_points = (KeyPoint(KeyPointKind.DECISION, "Följ upp beslutet."),)
    entry = container.journal_capture.create_manual_entry(
        actor,
        source_id=source.id,
        title="Sammanfattningsbar journalpost",
        summary="Ett beslut och en uppföljning.",
        key_points=key_points,
        project_ids=(project.id,),
        task_ids=(task.id,),
        contact_ids=(contact.id,),
        idempotency_key="journal-summary-entry",
    )

    saved = container.journal_day.put_manual_summary(
        actor,
        journal_date=JOURNAL_DATE,
        expected_entry_fingerprint=entry_fingerprint([entry]),
        expected_summary_version=None,
        content=summary_content(entry.id),
        idempotency_key="journal-summary-summary-create",
    )
    assert saved.origin is SummaryOrigin.MANUAL
    assert saved.state is SummaryState.CURRENT
    assert saved.entry_ids == (entry.id,)
    assert saved.changed_entry_count == 0

    updated = container.journal.update_entry(
        actor,
        entry_id=entry.id,
        expected_version=1,
        title="Uppdaterad journalpost",
        summary=entry.summary,
        key_points=key_points,
        idempotency_key="journal-summary-entry-update",
    )
    assert updated.version == 2
    assert updated.source_id == source.id
    assert updated.journal_date == JOURNAL_DATE
    relations = container.journal_relations.get_entry_relations(actor, entry.id)
    assert relations.project_ids == (project.id,)
    assert relations.task_ids == (task.id,)
    assert relations.contact_ids == (contact.id,)

    stale = container.journal_day.get_day(actor, journal_date=JOURNAL_DATE)
    assert stale.summary_status.state == "stale"
    assert stale.summary_status.summary_id == saved.id
    assert stale.summary_status.version == 1
    assert stale.summary_status.changed_entry_count == 1

    archived = container.journal.archive_entry(
        actor,
        entry_id=entry.id,
        expected_version=2,
        idempotency_key="journal-summary-entry-archive",
    )
    assert archived.archived_at is not None
    restored = container.journal.restore_entry(
        actor,
        entry_id=entry.id,
        expected_version=3,
        idempotency_key="journal-summary-entry-restore",
    )
    assert restored.archived_at is None
    assert restored.version == 4
    assert restored.source_id == source.id
    assert restored.journal_date == JOURNAL_DATE
    relations = container.journal_relations.get_entry_relations(actor, entry.id)
    assert relations.project_ids == (project.id,)
    assert relations.task_ids == (task.id,)
    assert relations.contact_ids == (contact.id,)

    refreshed = container.journal_day.put_manual_summary(
        actor,
        journal_date=JOURNAL_DATE,
        expected_entry_fingerprint=entry_fingerprint([restored]),
        expected_summary_version=1,
        content=summary_content(restored.id, "Den aktuella manuella översikten."),
        idempotency_key="journal-summary-summary-refresh",
    )
    assert refreshed.version == 2
    assert refreshed.state is SummaryState.CURRENT

    with container.session_factory() as session:
        assert (
            session.execute(
                text(
                    "SELECT count(*) FROM sidekick.journal_processing_runs "
                    "WHERE owner_id = :owner_id"
                ),
                {"owner_id": actor.user_id},
            ).scalar_one()
            == 0
        )
