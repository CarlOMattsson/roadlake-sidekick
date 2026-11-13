"""The closed catalogue of what an owner export contains and which schema heads it accepts.

The export catalogue is deliberately closed.  It is not a database dump: each
owner-scoped product relation is named here, while authentication material,
operational leases, derived Hindsight metadata, and non-owner-scoped audit data
are explicitly excluded.  A future restore path can therefore evolve against a
stable, reviewable format instead of accepting arbitrary table input.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sidekick.owner_export.persistence import is_derived_column
from sidekick.references.persistence import ExternalReferenceRow, TaskExternalReferenceRow
from sidekick.shared.errors.core import ValidationError
from sidekick.shared.persistence.models import (
    ActionRow,
    ActivityEntryRow,
    ContactAliasRow,
    ContactRow,
    ContactTagRow,
    DailyJournalSummaryEntryRow,
    DailyJournalSummaryRow,
    DomainEventRow,
    DomainRow,
    DomainTagRow,
    JournalDraftRow,
    JournalEntryContactRow,
    JournalEntryProjectRow,
    JournalEntryRow,
    JournalEntryTagRow,
    JournalEntryTaskRow,
    JournalProcessingRunRow,
    JournalSourceRow,
    JournalSummaryProposalRow,
    MemorySettingsRow,
    ProcessRow,
    ProcessRunRow,
    ProcessRunTemplateRow,
    ProcessTagRow,
    ProjectContactRow,
    ProjectRow,
    ProjectTagRow,
    SavedViewRow,
    StepRow,
    TaskContactRow,
    TaskRow,
    TaskStatusHistoryRow,
    TaskTagRow,
    WorkTagRow,
)
from sidekick.shopping.persistence.rows import ShoppingItemRow, ShoppingListRow, ShoppingStatusRow

EXPORT_FORMAT = "sidekick.owner-export"
EXPORT_FORMAT_VERSION = 6
# Format 5 (written at migration 106) has no tag links for Contacts and Journal entries; migration
# 107 added them. A format 5 export is still read: those two collections are simply absent and
# restore as empty.
FORMAT_WITHOUT_TAG_LINKS = 5
COLLECTIONS_ADDED_IN_FORMAT_6: frozenset[str] = frozenset({"contact_tags", "journal_entry_tags"})
# Format 4 also carried four collections of the retired automation engine. Migration 106 dropped
# their tables, which were empty on every installation. A format 4 export is still read: it must
# hold exactly these collections, all empty, and they are ignored. One that holds a row is refused
# rather than silently losing it. It has no tag links either.
FORMAT_WITH_RETIRED_COLLECTIONS = 4
RETIRED_COLLECTIONS: frozenset[str] = frozenset(
    {
        "assistant_automation_policies",
        "assistant_automation_control",
        "assistant_automation_runs",
        "assistant_task_review_findings",
    }
)
# Every migration of the chain, in order, with whether it leaves the exported tables and columns
# alone (an index, say). An export stamped at any head from the last format-changing migration
# onward is readable by this version; an export from before it is refused. A test pins this list to
# the files in `migrations/`, so a new migration forces a decision here.
SCHEMA_CHAIN: tuple[tuple[str, bool], ...] = (
    ("100_schema_baseline_0_1_0", False),
    ("106_drop_retired_automation_tables", False),
    ("107_contact_and_journal_entry_tags", False),
)
SCHEMA_HEAD = SCHEMA_CHAIN[-1][0]

# The heads of the development chain that the baseline folded in before the first release (the
# baseline `100_baseline_0_1_0`, then 101 to 105). Their files are gone, but the owner's
# installation and its exports carry these ids, and none of those migrations changed the export
# format, so an export stamped with any of them is a format 4 export.
FOLDED_CHAIN_HEADS: frozenset[str] = frozenset(
    {
        "100_baseline_0_1_0",
        "101_tasks_project_and_due_indexes",
        "102_event_ledger_append_only",
        "103_trash_sweep_delete_grants",
        "104_audit_event_source",
        "105_drop_sessions_and_password_hash",
    }
)


def accepted_schema_heads(chain: tuple[tuple[str, bool], ...]) -> frozenset[str]:
    """The heads an export may carry: from the last format-changing migration to the newest."""

    last_format_change = max(
        index for index, (_, format_neutral) in enumerate(chain) if not format_neutral
    )
    return frozenset(migration for migration, _ in chain[last_format_change:])


# The schema heads an export may carry, by its format version. A format 4 export was written at the
# baseline or at a head of the folded chain, a format 5 export at migration 106 and a format 6
# export at migration 107 or later.
ACCEPTED_SCHEMA_HEADS_BY_FORMAT: dict[int, frozenset[str]] = {
    EXPORT_FORMAT_VERSION: accepted_schema_heads(SCHEMA_CHAIN),
    FORMAT_WITHOUT_TAG_LINKS: frozenset({"106_drop_retired_automation_tables"}),
    FORMAT_WITH_RETIRED_COLLECTIONS: FOLDED_CHAIN_HEADS | {SCHEMA_CHAIN[0][0]},
}


class ExportRefused(ValidationError):
    """An export, backup or restore was refused for a reason that names no owner data.

    The message holds a fixed reason or a collection/field name, never a row value, so the
    command line may print it. Any other error from a restore is reported by its type only.
    """


@dataclass(frozen=True, slots=True)
class ExportSource:
    """One explicitly approved owner-scoped relation in the export contract."""

    name: str
    row_type: type[Any]
    redacted_fields: frozenset[str] = frozenset()


EXPORT_SOURCES: tuple[ExportSource, ...] = (
    ExportSource("domains", DomainRow),
    ExportSource("processes", ProcessRow),
    ExportSource("process_run_templates", ProcessRunTemplateRow),
    ExportSource("process_runs", ProcessRunRow),
    ExportSource("projects", ProjectRow),
    ExportSource("tasks", TaskRow),
    ExportSource("task_status_history", TaskStatusHistoryRow),
    ExportSource("steps", StepRow),
    ExportSource("actions", ActionRow),
    ExportSource("work_tags", WorkTagRow),
    ExportSource("domain_tags", DomainTagRow),
    ExportSource("process_tags", ProcessTagRow),
    ExportSource("project_tags", ProjectTagRow),
    ExportSource("task_tags", TaskTagRow),
    ExportSource("contact_tags", ContactTagRow),
    ExportSource("journal_entry_tags", JournalEntryTagRow),
    ExportSource("saved_work_views", SavedViewRow),
    ExportSource("domain_events", DomainEventRow),
    ExportSource("activity_entries", ActivityEntryRow),
    ExportSource("contacts", ContactRow),
    ExportSource("shopping_lists", ShoppingListRow),
    ExportSource("shopping_items", ShoppingItemRow),
    ExportSource("shopping_item_status_history", ShoppingStatusRow),
    ExportSource("contact_aliases", ContactAliasRow),
    ExportSource("project_contacts", ProjectContactRow),
    ExportSource("task_contacts", TaskContactRow),
    ExportSource("external_references", ExternalReferenceRow),
    ExportSource("task_external_references", TaskExternalReferenceRow),
    ExportSource("journal_sources", JournalSourceRow),
    ExportSource("journal_processing_runs", JournalProcessingRunRow),
    ExportSource("journal_drafts", JournalDraftRow),
    ExportSource("journal_summary_proposals", JournalSummaryProposalRow),
    ExportSource("journal_entries", JournalEntryRow),
    ExportSource("journal_entry_projects", JournalEntryProjectRow),
    ExportSource("journal_entry_tasks", JournalEntryTaskRow),
    ExportSource("journal_entry_contacts", JournalEntryContactRow),
    ExportSource("daily_journal_summaries", DailyJournalSummaryRow),
    ExportSource("daily_journal_summary_entries", DailyJournalSummaryEntryRow),
    ExportSource("memory_settings", MemorySettingsRow),
)

# Authentication, instance configuration, operational state and derived memory stay local.
EXCLUDED_COLLECTIONS: tuple[str, ...] = (
    "users_and_password_hashes",
    "sessions_and_csrf_digests",
    "personal_access_tokens",
    "idempotency_operations",
    "audit_events_without_owner_scope",
    "process_run_outbox_worker_state",
    "memory_sources_derived_metadata",
    "memory_usage_daily_derived_counters",
    "hindsight_memory_bank_content",
)

SOURCES_BY_NAME = {source.name: source for source in EXPORT_SOURCES}
TABLE_TO_SOURCE = {source.row_type.__table__.name: source.name for source in EXPORT_SOURCES}


def source_fields(source: ExportSource) -> tuple[str, ...]:
    return tuple(
        column.name
        for column in source.row_type.__table__.columns
        if column.name not in source.redacted_fields and not is_derived_column(column)
    )
