"""The tags of Contacts and Journal entries are part of an owner's export and come back on restore.

A format 6 export carries `contact_tags` and `journal_entry_tags`; restoring it into another owner
gives that owner the same tags on the restored records. An export of the earlier format 5 has no
such collections, restores cleanly and leaves the records without tags.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

import pytest

from sidekick.api.app import Container, create_container
from sidekick.contacts.application.models import CreateContactCommand
from sidekick.journal.domain.entry import KeyPoint, KeyPointKind
from sidekick.journal.domain.source import SourceType
from sidekick.owner_export.document import verify_export
from sidekick.owner_export.export import OwnerExportService
from sidekick.owner_export.restore import OwnerRestoreService
from sidekick.owner_export.restore_plan import build_restore_plan
from sidekick.shared.types import Actor
from sidekick.store import SqlAlchemyStore
from tests.db import database_factory
from tests.support.older_export_formats import as_format_5
from tests.support.settings import make_settings

DAY = date(2026, 7, 21)
SCOPES = frozenset({"contacts:read", "contacts:write", "journal:read", "journal:write"})


def _tagged_owner(container: Container) -> tuple[UUID, Actor]:
    owner = container.auth.provision_user("tagged-source", "Source")
    actor = Actor(owner, SCOPES)
    container.contacts.create(
        actor,
        CreateContactCommand(display_name="Anna", tags=("viktig", "familj")),
        idempotency_key="create-anna",
    )
    container.journal_capture.write_entry(
        actor,
        source_type=SourceType.TRANSCRIPT_TEXT,
        journal_date=DAY,
        occurred_at=None,
        raw_text="Words for the day",
        language=None,
        title="Day",
        summary=None,
        key_points=(KeyPoint(KeyPointKind.FACT, "A fact"),),
        tags=("vänta",),
        idempotency_key="write-day",
    )
    return owner, actor


def _restore(factory: Any, document: dict[str, Any], target: UUID) -> None:
    plan = build_restore_plan(document, target)
    assert plan.status == "ready"
    OwnerRestoreService(SqlAlchemyStore(factory)).restore(
        document, target_owner_id=target, expected_plan_checksum=plan.plan_checksum
    )


def _tags_of(container: Container, owner: UUID) -> dict[str, list[str]]:
    """The tag slugs of the owner's one contact and one journal entry."""

    actor = Actor(owner, SCOPES)
    (contact,) = container.contacts.list(actor).items
    (entry,) = container.journal.list_entries(actor, start_date=DAY, end_date=DAY).items
    return {
        "contact": sorted(
            t.slug for t in container.work_tags.for_record(actor, "contact", contact.id)
        ),
        "journal_entry": sorted(
            t.slug for t in container.work_tags.for_record(actor, "journal_entry", entry.id)
        ),
    }


@pytest.mark.integration
def test_the_tag_links_are_exported_and_restored_with_their_records() -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    source, _ = _tagged_owner(container)
    target = container.auth.provision_user("tagged-target", "Target")

    document = OwnerExportService(SqlAlchemyStore(factory)).export(Actor(source, frozenset()))

    assert verify_export(document).owner_id == source
    assert len(document["collections"]["contact_tags"]) == 2
    assert len(document["collections"]["journal_entry_tags"]) == 1
    _restore(factory, document, target)
    assert _tags_of(container, target) == {
        "contact": ["familj", "viktig"],
        "journal_entry": ["vänta"],
    }
    # The source keeps its own.
    assert _tags_of(container, source) == _tags_of(container, target)


@pytest.mark.integration
def test_an_export_of_the_earlier_format_restores_without_tag_links() -> None:
    factory = database_factory()
    container = create_container(make_settings(), factory)
    source, _ = _tagged_owner(container)
    target = container.auth.provision_user("older-target", "Target")
    exported = OwnerExportService(SqlAlchemyStore(factory)).export(Actor(source, frozenset()))
    document = as_format_5(exported)

    assert "contact_tags" not in document["collections"]
    assert verify_export(document).owner_id == source
    _restore(factory, document, target)

    assert _tags_of(container, target) == {"contact": [], "journal_entry": []}
