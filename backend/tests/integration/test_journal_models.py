"""SQLAlchemy metadata parity tests for the Journal persistence in the 0.1.0 baseline."""

# ruff: noqa: E501, SIM300

from pathlib import Path

import pytest
from sqlalchemy import (
    CHAR,
    CheckConstraint,
    ForeignKeyConstraint,
    UniqueConstraint,
    create_engine,
    text,
)

from sidekick.shared.persistence.models import (
    Base,
    DailyJournalSummaryEntryRow,
    DailyJournalSummaryRow,
    JournalDraftRow,
    JournalEntryContactRow,
    JournalEntryProjectRow,
    JournalEntryRow,
    JournalEntryTaskRow,
    JournalProcessingRunRow,
    JournalSourceRow,
    JournalSummaryProposalRow,
)
from tests.db import require_test_database_url

EXPECTED_COLUMNS = {
    "journal_sources": {
        "id",
        "owner_id",
        "source_type",
        "journal_date",
        "occurred_at",
        "source_recorded_at",
        "raw_text",
        "content_fingerprint",
        "language",
        "replaces_source_id",
        "created_at",
        "trashed_at",
        "search_vector",
    },
    "journal_processing_runs": {
        "id",
        "owner_id",
        "source_id",
        "operation",
        "journal_date",
        "status",
        "provider",
        "model_id",
        "prompt_version",
        "schema_version",
        "input_fingerprint",
        "candidate_catalog",
        "provider_response_id",
        "failure_category",
        "input_tokens",
        "output_tokens",
        "started_at",
        "finished_at",
        "lease_expires_at",
        "attempt_count",
        "created_at",
    },
    "journal_drafts": {
        "id",
        "owner_id",
        "source_id",
        "processing_run_id",
        "catalog_run_id",
        "state",
        "title",
        "summary",
        "key_points",
        "relation_suggestions",
        "task_proposals",
        "version",
        "created_at",
        "updated_at",
        "lifecycle_at",
    },
    "journal_summary_proposals": {
        "id",
        "owner_id",
        "run_id",
        "journal_date",
        "entry_fingerprint",
        "content",
        "state",
        "version",
        "created_at",
        "updated_at",
        "lifecycle_at",
    },
    "journal_entries": {
        "id",
        "owner_id",
        "source_id",
        "journal_date",
        "occurred_at",
        "title",
        "summary",
        "key_points",
        "version",
        "created_at",
        "updated_at",
        "archived_at",
        "trashed_at",
        "search_vector",
    },
    "journal_entry_projects": {"owner_id", "entry_id", "project_id", "created_at"},
    "journal_entry_tasks": {"owner_id", "entry_id", "task_id", "created_at"},
    "journal_entry_contacts": {"owner_id", "entry_id", "contact_id", "created_at"},
    "daily_journal_summaries": {
        "id",
        "owner_id",
        "journal_date",
        "origin",
        "status",
        "overview",
        "content",
        "source_fingerprint",
        "processing_run_id",
        "accepted_proposal_id",
        "version",
        "generated_at",
        "updated_at",
        "manual_edited_at",
    },
    "daily_journal_summary_entries": {
        "owner_id",
        "summary_id",
        "entry_id",
        "entry_version",
        "ordinal",
    },
}
EXPECTED_INDEXES = {
    "ix_journal_sources_timeline",
    "ix_journal_sources_replacement",
    "ix_journal_processing_runs_owner_operation",
    "ix_journal_processing_runs_source",
    "ix_journal_drafts_source",
    "ix_journal_summary_proposals_day",
    "ix_journal_entries_timeline",
    "ix_journal_entries_source",
    "ix_journal_entry_projects_reverse",
    "ix_journal_entry_tasks_reverse",
    "ix_journal_entry_contacts_reverse",
    "ix_daily_journal_summary_entries_entry",
}
EXPECTED_UNIQUES = {
    "uq_journal_sources_id_owner",
    "uq_journal_processing_runs_id_owner",
    "uq_journal_drafts_id_owner",
    "uq_journal_drafts_processing_run",
    "uq_journal_summary_proposals_id_owner",
    "uq_journal_summary_proposals_run",
    "uq_journal_entries_id_owner",
    "uq_journal_entries_owner_source",
    "uq_daily_journal_summaries_id_owner",
    "uq_daily_journal_summaries_owner_date",
    "uq_daily_journal_summary_entries_ordinal",
}
EXPECTED_CHECKS = {
    "ck_journal_sources_type",
    "ck_journal_sources_raw_text",
    "ck_journal_sources_fingerprint",
    "ck_journal_sources_language",
    "ck_journal_sources_not_self_replacement",
    "ck_journal_processing_runs_operation",
    "ck_journal_processing_runs_status",
    "ck_journal_processing_runs_provider",
    "ck_journal_processing_runs_model",
    "ck_journal_processing_runs_prompt_version",
    "ck_journal_processing_runs_schema_version",
    "ck_journal_processing_runs_fingerprint",
    "ck_journal_processing_runs_catalog",
    "ck_journal_processing_runs_failure",
    "ck_journal_processing_runs_input_tokens",
    "ck_journal_processing_runs_output_tokens",
    "ck_journal_processing_runs_attempt_count",
    "ck_journal_processing_runs_source_operation",
    "ck_journal_processing_runs_timing",
    "ck_journal_drafts_state",
    "ck_journal_drafts_title",
    "ck_journal_drafts_summary",
    "ck_journal_drafts_key_points",
    "ck_journal_drafts_relation_suggestions",
    "ck_journal_drafts_task_proposals",
    "ck_journal_drafts_version",
    "ck_journal_summary_proposals_fingerprint",
    "ck_journal_summary_proposals_content",
    "ck_journal_summary_proposals_state",
    "ck_journal_summary_proposals_version",
    "ck_journal_entries_title",
    "ck_journal_entries_summary",
    "ck_journal_entries_key_points",
    "ck_journal_entries_version",
    "ck_journal_entries_archive",
    "ck_daily_journal_summaries_origin",
    "ck_daily_journal_summaries_status",
    "ck_daily_journal_summaries_overview",
    "ck_daily_journal_summaries_content",
    "ck_daily_journal_summaries_fingerprint",
    "ck_daily_journal_summaries_version",
    "ck_daily_journal_summaries_origin_provenance",
    "ck_daily_journal_summary_entries_version",
    "ck_daily_journal_summary_entries_ordinal",
}
EXPECTED_FOREIGN_KEYS = {
    "fk_journal_sources_replacement_owner",
    "fk_journal_processing_runs_source_owner",
    "fk_journal_drafts_source_owner",
    "fk_journal_drafts_processing_run_owner",
    "fk_journal_drafts_catalog_run_owner",
    "fk_journal_summary_proposals_run_owner",
    "fk_journal_entries_source_owner",
    "fk_journal_entry_projects_entry",
    "fk_journal_entry_projects_project",
    "fk_journal_entry_tasks_entry",
    "fk_journal_entry_tasks_task",
    "fk_journal_entry_contacts_entry",
    "fk_journal_entry_contacts_contact",
    "fk_daily_journal_summaries_run_owner",
    "fk_daily_journal_summaries_proposal_owner",
    "fk_daily_journal_summary_entries_summary",
    "fk_daily_journal_summary_entries_entry",
}
EXPECTED_PRIMARY_KEYS = {
    "journal_sources": ("id",),
    "journal_processing_runs": ("id",),
    "journal_drafts": ("id",),
    "journal_summary_proposals": ("id",),
    "journal_entries": ("id",),
    "journal_entry_projects": ("owner_id", "entry_id", "project_id"),
    "journal_entry_tasks": ("owner_id", "entry_id", "task_id"),
    "journal_entry_contacts": ("owner_id", "entry_id", "contact_id"),
    "daily_journal_summaries": ("id",),
    "daily_journal_summary_entries": ("owner_id", "summary_id", "entry_id"),
}
EXPECTED_ROWS = {
    JournalSourceRow,
    JournalProcessingRunRow,
    JournalDraftRow,
    JournalSummaryProposalRow,
    JournalEntryRow,
    JournalEntryProjectRow,
    JournalEntryTaskRow,
    JournalEntryContactRow,
    DailyJournalSummaryRow,
    DailyJournalSummaryEntryRow,
}


@pytest.mark.integration
def test_every_005_table_column_index_key_and_relationship_has_orm_parity() -> None:
    tables = {
        table.name: table for table in Base.metadata.tables.values() if table.schema == "sidekick"
    }
    for table_name, columns in EXPECTED_COLUMNS.items():
        assert table_name in tables
        assert set(tables[table_name].columns.keys()) == columns

    journal_tables = {table_name: tables[table_name] for table_name in EXPECTED_COLUMNS}
    index_names = {index.name for table in journal_tables.values() for index in table.indexes}
    assert EXPECTED_INDEXES <= index_names
    unique_names = {
        constraint.name
        for table in journal_tables.values()
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert EXPECTED_UNIQUES <= unique_names
    check_names = {
        constraint.name
        for table in journal_tables.values()
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    foreign_key_names = {
        constraint.name
        for table in journal_tables.values()
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint) and constraint.name is not None
    }
    assert check_names >= EXPECTED_CHECKS
    assert foreign_key_names >= EXPECTED_FOREIGN_KEYS
    for table_name, primary_key_columns in EXPECTED_PRIMARY_KEYS.items():
        assert (
            tuple(column.name for column in tables[table_name].primary_key.columns)
            == primary_key_columns
        )
    assert all(
        any(isinstance(item, ForeignKeyConstraint) for item in row.__table__.constraints)
        for row in EXPECTED_ROWS
    )
    assert all(
        any(isinstance(item, CheckConstraint) for item in row.__table__.constraints)
        for row in (
            JournalSourceRow,
            JournalProcessingRunRow,
            JournalDraftRow,
            JournalSummaryProposalRow,
            JournalEntryRow,
            DailyJournalSummaryRow,
            DailyJournalSummaryEntryRow,
        )
    )

    fingerprint_columns = (
        JournalSourceRow.content_fingerprint,
        JournalProcessingRunRow.input_fingerprint,
        JournalSummaryProposalRow.entry_fingerprint,
        DailyJournalSummaryRow.source_fingerprint,
    )
    assert all(
        isinstance(column.type, CHAR) and column.type.length == 64 for column in fingerprint_columns
    )
    run_checks = {
        constraint.name
        for constraint in JournalProcessingRunRow.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert run_checks >= {
        "ck_journal_processing_runs_provider",
        "ck_journal_processing_runs_model",
        "ck_journal_processing_runs_prompt_version",
        "ck_journal_processing_runs_schema_version",
        "ck_journal_processing_runs_input_tokens",
        "ck_journal_processing_runs_output_tokens",
    }


@pytest.mark.integration
def test_database_tables_constraints_indexes_and_grants_match_orm() -> None:
    engine = create_engine(require_test_database_url())
    with engine.connect() as conn:
        db_columns = {
            row.table_name: set()
            for row in conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'sidekick'"
                )
            )
        }
        for table_name, column_name in conn.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'sidekick'"
            )
        ):
            db_columns.setdefault(table_name, set()).add(column_name)
        for table_name, columns in EXPECTED_COLUMNS.items():
            assert db_columns[table_name] == columns

        index_names = set(
            conn.scalars(text("SELECT indexname FROM pg_indexes WHERE schemaname = 'sidekick'"))
        )
        assert EXPECTED_INDEXES <= index_names
        constraint_names = set(
            conn.scalars(
                text(
                    "SELECT conname FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace "
                    "WHERE n.nspname = 'sidekick'"
                )
            )
        )
        assert EXPECTED_UNIQUES <= constraint_names
        assert EXPECTED_CHECKS <= constraint_names
        assert EXPECTED_FOREIGN_KEYS <= constraint_names

        expected_grants = {
            "journal_sources": {"SELECT", "INSERT"},
            "journal_processing_runs": {"SELECT", "INSERT", "UPDATE"},
            "journal_drafts": {"SELECT", "INSERT", "UPDATE"},
            "journal_summary_proposals": {"SELECT", "INSERT", "UPDATE"},
            "journal_entries": {"SELECT", "INSERT", "UPDATE"},
            "journal_entry_projects": {"SELECT", "INSERT", "DELETE"},
            "journal_entry_tasks": {"SELECT", "INSERT", "DELETE"},
            "journal_entry_contacts": {"SELECT", "INSERT", "DELETE"},
            "daily_journal_summaries": {"SELECT", "INSERT", "UPDATE"},
            "daily_journal_summary_entries": {"SELECT", "INSERT", "DELETE"},
        }
        for table_name, allowed in expected_grants.items():
            for operation in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                assert conn.scalar(
                    text("SELECT has_table_privilege('sidekick_app', :table, :operation)"),
                    {"table": f"sidekick.{table_name}", "operation": operation},
                ) is (operation in allowed)


def test_baseline_declares_source_immutability_and_authoritative_entry_uniqueness() -> None:
    migration = Path(__file__).resolve().parents[3] / "migrations" / "100_schema_baseline_0_1_0.py"
    sql = migration.read_text(encoding="utf-8")
    assert "GRANT SELECT,INSERT ON TABLE sidekick.journal_sources TO sidekick_app" in sql
    assert "ON TABLE sidekick.journal_sources TO sidekick_app" in sql
    assert "GRANT UPDATE ON sidekick.journal_sources" not in sql
    assert "GRANT DELETE ON sidekick.journal_sources" not in sql
    assert "ADD CONSTRAINT uq_journal_entries_owner_source UNIQUE (owner_id, source_id)" in sql
