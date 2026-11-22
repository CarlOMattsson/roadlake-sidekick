"""Migration 116 adds the six automation tables and nothing else, and its constraints hold.

The upgrade keeps every existing row, the rollback returns the schema to exactly what migration 115
built, and the rows the application writes are bound by the closed value sets, the limits and the
owner-scoped foreign keys of the tables. The row tests run as the runtime role in a transaction
that is rolled back.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import IntegrityError
from yoyo import get_backend, read_migrations

from tests.db import database_factory, require_test_database_url
from tests.support.automation_rows import (
    DIGEST,
    insert_automation,
    insert_check,
    insert_datapoint,
    insert_owner,
    insert_run,
    insert_suggestion,
)
from tests.support.migration_baseline import (
    AUTOMATIONS,
    CONTACT_SLACK,
    _admin_url,
    _applied_ids,
    _apply,
    _migration_url,
    _reset_schema,
    _run,
    _snapshot,
    _tables,
    chain_through,
    ids_through,
    rebuilt_schema,  # noqa: F401  (a fixture, used through `usefixtures`)
)

NEW_TABLES = {
    "automations",
    "automation_runs",
    "automation_datapoints",
    "automation_suggestions",
    "automation_checks",
    "automation_report_cursors",
}
OWNER = "00000000-0000-4000-8000-000000000001"


def _tables_now() -> set[str]:
    engine = create_engine(_admin_url())
    try:
        with engine.connect() as connection:
            return _tables(connection)
    finally:
        engine.dispose()


def _users() -> int:
    engine = create_engine(_admin_url())
    try:
        with engine.connect() as connection:
            return connection.execute(text("SELECT count(*) FROM sidekick.users")).scalar_one()
    finally:
        engine.dispose()


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_the_tables_are_added_empty_and_every_existing_row_is_kept(tmp_path: Path) -> None:
    _reset_schema()
    _apply(chain_through(tmp_path, CONTACT_SLACK))
    _run(
        "INSERT INTO sidekick.users (id, username, display_name, created_at) "
        "VALUES (:id, 'kept', 'Kept', now())",
        {"id": OWNER},
    )
    before = _tables_now()
    assert NEW_TABLES.isdisjoint(before)

    _apply(chain_through(tmp_path, AUTOMATIONS))

    assert _tables_now() == before | NEW_TABLES
    assert _applied_ids() == ids_through(AUTOMATIONS)
    assert _users() == 1
    engine = create_engine(_admin_url())
    try:
        with engine.connect() as connection:
            counts = [
                connection.execute(text(f"SELECT count(*) FROM sidekick.{table}")).scalar_one()  # noqa: S608
                for table in sorted(NEW_TABLES)
            ]
    finally:
        engine.dispose()
    assert counts == [0] * len(NEW_TABLES)


@pytest.mark.integration
@pytest.mark.xdist_group("migrations")
@pytest.mark.usefixtures("rebuilt_schema")
def test_a_rollback_returns_the_schema_to_what_migration_115_built(tmp_path: Path) -> None:
    _reset_schema()
    _apply(chain_through(tmp_path, CONTACT_SLACK))
    expected = _snapshot()

    _reset_schema()
    through = chain_through(tmp_path, AUTOMATIONS)
    _apply(through)
    _run(
        "INSERT INTO sidekick.users (id, username, display_name, created_at) "
        "VALUES (:id, 'kept', 'Kept', now())",
        {"id": OWNER},
    )
    engine = create_engine(_admin_url())
    try:
        with engine.begin() as connection:
            automation = insert_automation(connection, OWNER)
            run = insert_run(connection, OWNER, automation)
            suggestion = insert_suggestion(connection, OWNER, automation, run)
            insert_datapoint(connection, OWNER, automation, run)
            insert_check(connection, OWNER, suggestion, run)
    finally:
        engine.dispose()
    backend = get_backend(_migration_url())
    migration = next(item for item in read_migrations(str(through)) if item.id == AUTOMATIONS)

    with backend.lock():
        backend.rollback_one(migration)

    assert _snapshot() == expected
    assert _applied_ids() == ids_through(CONTACT_SLACK)
    assert _users() == 1
    # The migration applies again.
    _apply(through)
    assert _tables_now() >= NEW_TABLES


@contextmanager
def _owner_and_automation(**overrides: Any) -> Iterator[tuple[Connection, str, str]]:
    """An owner and an automation written by the runtime role; nothing is committed."""

    database_factory()
    engine = create_engine(require_test_database_url())
    owner = str(uuid4())
    try:
        with engine.connect() as connection:
            insert_owner(connection, owner)
            automation = insert_automation(connection, owner, **overrides)
            try:
                yield connection, owner, automation
            finally:
                connection.rollback()
    finally:
        engine.dispose()


def _expect_refused(**overrides: Any) -> None:
    with (
        pytest.raises(IntegrityError),
        _owner_and_automation(**overrides),
    ):
        pass


@pytest.mark.integration
def test_an_automation_defaults_to_one_dollar_per_run_the_standard_tier_and_suggest_only() -> None:
    with _owner_and_automation() as (connection, _, automation):
        row = (
            connection.execute(
                text(
                    "SELECT run_budget_microusd, model_tier, apply_mode, state, bulk_threshold, "
                    "auto_threshold, max_suggestions_per_run, sources, allowed_effects, "
                    "auto_effects, approved_digest FROM sidekick.automations WHERE id = :id"
                ),
                {"id": automation},
            )
            .tuples()
            .one()
        )

    assert row == (1_000_000, "standard", "suggest", "draft", 90, 95, 15, [], [], [], None)


@pytest.mark.integration
def test_the_strong_tier_is_accepted() -> None:
    with _owner_and_automation(model_tier="strong"):
        pass


@pytest.mark.integration
@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"model_tier": "cheap"}, id="model-tier-cheap"),
        pytest.param({"run_budget_microusd": 0}, id="run-budget-zero"),
        pytest.param({"state": "deleted"}, id="state-deleted"),
        pytest.param({"runner": "cloud"}, id="runner-cloud"),
        pytest.param({"sources": ["mail", "telegram"]}, id="source-outside-set"),
        pytest.param({"instruction": ""}, id="instruction-empty"),
        pytest.param({"instruction": "x" * 4001}, id="instruction-over-limit"),
        pytest.param({"cadence": []}, id="cadence-empty"),
        pytest.param({"allowed_effects": ["send_mail"]}, id="allowed-effect-outside-catalogue"),
        pytest.param(
            {"allowed_effects": ["create_task", "trash_task"]},
            id="allowed-effect-second-outside-catalogue",
        ),
        pytest.param({"apply_mode": "always"}, id="apply-mode-outside-set"),
        pytest.param({"approved_digest": DIGEST}, id="approved-digest-without-approval"),
        pytest.param({"approved_at": "2026-11-22T10:00:00+00:00"}, id="approved-at-without-digest"),
        pytest.param(
            {
                "apply_mode": "suggest",
                "allowed_effects": ["create_task"],
                "auto_effects": ["create_task"],
            },
            id="suggest-with-auto-effects",
        ),
        pytest.param(
            {"apply_mode": "auto_low_risk", "auto_effects": ["create_task"]},
            id="auto-low-risk-effect-not-allowed",
        ),
        pytest.param(
            {
                "apply_mode": "auto_low_risk",
                "allowed_effects": ["add_shopping_items"],
                "auto_effects": ["add_shopping_items"],
            },
            id="auto-low-risk-shopping-items",
        ),
        pytest.param({"bulk_threshold": 79}, id="bulk-threshold-below-range"),
        pytest.param({"bulk_threshold": 100}, id="bulk-threshold-above-range"),
        pytest.param({"auto_threshold": 89}, id="auto-threshold-below-range"),
        pytest.param(
            {"bulk_threshold": 95, "auto_threshold": 92},
            id="auto-threshold-below-bulk-threshold",
        ),
        pytest.param({"max_suggestions_per_run": 0}, id="max-suggestions-zero"),
        pytest.param({"max_suggestions_per_run": 26}, id="max-suggestions-over-limit"),
        pytest.param({"version": 0}, id="version-zero"),
    ],
)
def test_an_automation_outside_its_closed_sets_and_limits_is_refused(
    overrides: dict[str, Any],
) -> None:
    _expect_refused(**overrides)


@pytest.mark.integration
def test_auto_apply_is_representable_only_for_a_creating_effect_the_automation_may_propose() -> (
    None
):
    with _owner_and_automation(
        apply_mode="auto_low_risk",
        allowed_effects=["create_task", "create_contact"],
        auto_effects=["create_task"],
        approved_digest=DIGEST,
        approved_at="2026-11-22T10:00:00+00:00",
    ):
        pass


@pytest.mark.integration
def test_only_one_attempt_per_occurrence_is_active_and_a_later_attempt_follows_a_finished_one() -> (
    None
):
    with _owner_and_automation() as (connection, owner, automation):
        first = insert_run(connection, owner, automation, state="queued")
        with pytest.raises(IntegrityError), connection.begin_nested():
            insert_run(connection, owner, automation, attempt=2, state="running")
        connection.execute(
            text("UPDATE sidekick.automation_runs SET state = 'failed' WHERE id = :id"),
            {"id": first},
        )
        second = insert_run(connection, owner, automation, attempt=2, state="queued")
        with pytest.raises(IntegrityError), connection.begin_nested():
            insert_run(connection, owner, automation, attempt=2, state="failed")

    assert first != second


@pytest.mark.integration
@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"runner": "any"}, id="runner-outside-set"),
        pytest.param({"state": "paused"}, id="state-outside-set"),
        pytest.param({"stage": "answer"}, id="stage-outside-set"),
        pytest.param({"credential_kind": "password"}, id="credential-kind-outside-set"),
        pytest.param({"outcome": "great"}, id="outcome-outside-set"),
        pytest.param({"cost_source": "guess"}, id="cost-source-outside-set"),
        pytest.param({"attempt": 0}, id="attempt-zero"),
        pytest.param({"cost_microusd": -1}, id="cost-negative"),
        pytest.param({"datapoint_count": -1}, id="datapoint-count-negative"),
    ],
)
def test_a_run_outside_its_closed_sets_and_limits_is_refused(overrides: dict[str, Any]) -> None:
    with (
        pytest.raises(IntegrityError),
        _owner_and_automation() as (connection, owner, automation),
    ):
        insert_run(connection, owner, automation, **overrides)


@pytest.mark.integration
def test_a_row_cannot_point_at_another_owners_automation_or_run() -> None:
    with _owner_and_automation() as (connection, owner, automation):
        other = str(uuid4())
        insert_owner(connection, other)
        with pytest.raises(IntegrityError), connection.begin_nested():
            insert_run(connection, other, automation)
        run = insert_run(connection, owner, automation)
        with pytest.raises(IntegrityError), connection.begin_nested():
            insert_suggestion(connection, other, automation, run)
        with pytest.raises(IntegrityError), connection.begin_nested():
            insert_datapoint(connection, other, automation, run)
        suggestion = insert_suggestion(connection, owner, automation, run)
        with pytest.raises(IntegrityError), connection.begin_nested():
            insert_check(connection, other, suggestion, run)


@pytest.mark.integration
def test_a_row_cannot_point_at_a_run_of_another_automation_of_the_same_owner() -> None:
    with _owner_and_automation() as (connection, owner, automation):
        other_automation = insert_automation(connection, owner)
        other_run = insert_run(connection, owner, other_automation)
        with pytest.raises(IntegrityError), connection.begin_nested():
            insert_suggestion(connection, owner, automation, other_run)
        with pytest.raises(IntegrityError), connection.begin_nested():
            insert_datapoint(connection, owner, automation, other_run)
        insert_suggestion(connection, owner, other_automation, other_run)
        insert_datapoint(connection, owner, other_automation, other_run)


@pytest.mark.integration
def test_a_suggestion_is_never_proposed_twice_for_one_automation_in_any_state() -> None:
    fingerprint = "f" * 64
    with _owner_and_automation() as (connection, owner, automation):
        run = insert_run(connection, owner, automation)
        insert_suggestion(
            connection, owner, automation, run, dedupe_fingerprint=fingerprint, state="dismissed"
        )
        with pytest.raises(IntegrityError), connection.begin_nested():
            insert_suggestion(connection, owner, automation, run, dedupe_fingerprint=fingerprint)
        other_automation = insert_automation(connection, owner)
        other_run = insert_run(connection, owner, other_automation)
        insert_suggestion(
            connection, owner, other_automation, other_run, dedupe_fingerprint=fingerprint
        )


@pytest.mark.integration
@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"effect": "send_mail"}, id="effect-outside-catalogue"),
        pytest.param({"effect": "delete_task"}, id="effect-delete-task"),
        pytest.param({"state": "approved"}, id="state-outside-set"),
        pytest.param({"check_state": "done"}, id="check-state-outside-set"),
        pytest.param({"verdict": "fine"}, id="verdict-outside-set"),
        pytest.param({"confidence": 101}, id="confidence-over-range"),
        pytest.param({"confidence": -1}, id="confidence-negative"),
        pytest.param({"payload": {"title": "x" * 9000}}, id="payload-over-limit"),
        pytest.param({"payload": None}, id="payload-missing"),
        pytest.param(
            {"payload_purged_at": "2026-11-22T10:00:00+00:00"}, id="payload-purged-at-set"
        ),
        pytest.param(
            {"datapoint_ids": [str(uuid4()) for _ in range(11)]},
            id="datapoint-ids-over-limit",
        ),
        pytest.param({"decided_by": "you"}, id="decided-by-without-decided-at"),
        pytest.param(
            {
                "decided_at": "2026-11-22T10:00:00+00:00",
                "decided_by": "robot",
                "decision_channel": "app",
            },
            id="decided-by-outside-set",
        ),
        pytest.param(
            {
                "decided_at": "2026-11-22T10:00:00+00:00",
                "decided_by": "you",
                "decision_channel": "policy",
            },
            id="owner-decision-on-policy-channel",
        ),
        pytest.param(
            {
                "decided_at": "2026-11-22T10:00:00+00:00",
                "decided_by": "policy",
                "decision_channel": "app",
            },
            id="policy-decision-on-app-channel",
        ),
        pytest.param({"applied_kind": "task"}, id="applied-kind-without-applied-id"),
        pytest.param({"effect_version": 0}, id="effect-version-zero"),
    ],
)
def test_a_suggestion_outside_its_closed_sets_and_limits_is_refused(
    overrides: dict[str, Any],
) -> None:
    with (
        pytest.raises(IntegrityError),
        _owner_and_automation() as (connection, owner, automation),
    ):
        run = insert_run(connection, owner, automation)
        insert_suggestion(connection, owner, automation, run, **overrides)


@pytest.mark.integration
def test_a_purged_suggestion_and_a_policy_decision_are_representable() -> None:
    decided: dict[str, Any] = {
        "decided_at": "2026-11-22T10:00:00+00:00",
        "decided_by": "policy",
        "decision_channel": "policy",
        "applied_kind": "task",
        "applied_id": str(uuid4()),
        "applied_version": 1,
    }
    with _owner_and_automation() as (connection, owner, automation):
        run = insert_run(connection, owner, automation)
        insert_suggestion(connection, owner, automation, run, state="applied", **decided)
        insert_suggestion(
            connection,
            owner,
            automation,
            run,
            state="expired",
            payload=None,
            proposed_payload=None,
            rationale=None,
            payload_purged_at="2026-12-22T10:00:00+00:00",
        )


@pytest.mark.integration
@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"kind": "invoice"}, id="kind-outside-set"),
        pytest.param({"source_kind": "sms"}, id="source-kind-outside-set"),
        pytest.param({"fields": {"note": "x" * 5000}}, id="fields-over-limit"),
        pytest.param({"fields": None}, id="fields-missing"),
        pytest.param({"purged_at": "2026-12-22T10:00:00+00:00"}, id="purged-at-with-fields"),
    ],
)
def test_a_datapoint_outside_its_closed_sets_and_limits_is_refused(
    overrides: dict[str, Any],
) -> None:
    with (
        pytest.raises(IntegrityError),
        _owner_and_automation() as (connection, owner, automation),
    ):
        run = insert_run(connection, owner, automation)
        insert_datapoint(connection, owner, automation, run, **overrides)


@pytest.mark.integration
def test_a_purged_datapoint_keeps_its_row_without_the_fields() -> None:
    with _owner_and_automation() as (connection, owner, automation):
        run = insert_run(connection, owner, automation)
        insert_datapoint(
            connection,
            owner,
            automation,
            run,
            fields=None,
            source_label=None,
            purged_at="2026-12-22T10:00:00+00:00",
        )


@pytest.mark.integration
@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"checker": "local"}, id="checker-outside-set"),
        pytest.param({"verdict": "great"}, id="verdict-outside-set"),
        pytest.param({"verdict": "error", "confidence": 50}, id="error-verdict-with-confidence"),
        pytest.param({"confidence": 101}, id="confidence-over-range"),
        pytest.param({"reason_codes": ["because"]}, id="reason-code-outside-set"),
        pytest.param({"attempt": 0}, id="attempt-zero"),
    ],
)
def test_a_check_outside_its_closed_sets_and_limits_is_refused(overrides: dict[str, Any]) -> None:
    with (
        pytest.raises(IntegrityError),
        _owner_and_automation() as (connection, owner, automation),
    ):
        run = insert_run(connection, owner, automation)
        suggestion = insert_suggestion(connection, owner, automation, run)
        insert_check(connection, owner, suggestion, run, **overrides)


@pytest.mark.integration
def test_a_check_attempt_is_written_once_and_carries_only_codes_from_the_closed_set() -> None:
    with _owner_and_automation() as (connection, owner, automation):
        run = insert_run(connection, owner, automation)
        suggestion = insert_suggestion(connection, owner, automation, run)
        insert_check(
            connection,
            owner,
            suggestion,
            run,
            verdict="suspicious",
            confidence=12,
            reason_codes=["instruction_like_text", "out_of_scope"],
        )
        insert_check(
            connection, owner, suggestion, run, attempt=2, verdict="error", confidence=None
        )
        with pytest.raises(IntegrityError), connection.begin_nested():
            insert_check(connection, owner, suggestion, run, attempt=2)
