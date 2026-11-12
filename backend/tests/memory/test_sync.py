"""Tests for the memory reconcile pass: rules without a database, state machine with one.

The database tests drive `MemoryReconciler` against the deterministic fake provider and a clock the
test controls. Records are written straight through the ORM (helpers shared with the query tests).
Nothing here touches the network.
"""

import logging
import re
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, Engine, delete, func, select, update
from sqlalchemy.orm import Session, sessionmaker

import sidekick.memory.application.sync_pass as pass_module
import sidekick.memory.application.sync_rules as rules_module
import sidekick.memory.application.sync_send as send_module
import sidekick.memory.domain as domain_module
from sidekick.memory.adapters.fake import FakeMemoryProvider
from sidekick.memory.application.sync import MemoryReconciler
from sidekick.memory.application.sync_rules import (
    BACKFILL_AGE,
    MAX_ATTEMPTS,
    OPERATION_DEADLINE,
    REMOVED_CATEGORY,
    SendCandidate,
    derive_doc_key,
    is_backfill,
    retain_timestamp,
    retry_backoff,
    select_batch,
)
from sidekick.memory.application.sync_state import SyncPolicy
from sidekick.memory.domain import MemoryKind
from sidekick.memory.infrastructure.lock import (  # pyright: ignore[reportPrivateUsage]
    OwnerLock,
    _lock_key,
)
from sidekick.memory.ports import (
    OPAQUE_ID_PATTERN,
    MemoryFailureCategory,
    OperationResult,
    RetainItem,
)
from sidekick.shared.config import Settings
from sidekick.shared.persistence.models import (
    ContactRow,
    MemorySettingsRow,
    MemorySourceRow,
    MemoryUsageDailyRow,
    TaskRow,
)
from sidekick.shared.types import new_uuid7
from tests.db import database_factory
from tests.support.memory_queries import (
    LONG_TEXT,
    NOW,
    _contact,  # pyright: ignore[reportPrivateUsage]
    _domain,  # pyright: ignore[reportPrivateUsage]
    _enable_all,  # pyright: ignore[reportPrivateUsage]
    _entry,  # pyright: ignore[reportPrivateUsage]
    _owner,  # pyright: ignore[reportPrivateUsage]
    _project,  # pyright: ignore[reportPrivateUsage]
    _source,  # pyright: ignore[reportPrivateUsage]
    _task,  # pyright: ignore[reportPrivateUsage]
)
from tests.support.memory_sync import (
    KEY,
    LIVE_NOW,
    FakeClock,
    ScriptedProvider,
    _drive_to_retained,
    _new_contact,
    _reconciler,
    _row,
    _rows,
    _setup,
)

#: Three days later: every fixture counts as backfill.
OLD_NOW = NOW + timedelta(days=3)

SECRET_TITLE = "Hemlig titel Zxqv"
SECRET_NOTE = "Hemlig anteckning Qwzx om Tyra Backstrom"


# --- Test doubles -----------------------------------------------------------------------------


def _snapshot(factory: sessionmaker[Session], owner_id: UUID) -> list[tuple[object, ...]]:
    return [
        (
            row.id,
            row.fingerprint,
            row.status,
            row.attempts,
            row.next_attempt_at,
            row.operation_id,
            row.source_updated_at,
            row.retained_at,
            row.failure_category,
        )
        for row in _rows(factory, owner_id)
    ]


def _usage(factory: sessionmaker[Session], owner_id: UUID) -> list[tuple[date, int, int, int]]:
    with factory() as session:
        return [
            (u.usage_date, u.retain_documents, u.backfill_documents, u.characters)
            for u in session.scalars(
                select(MemoryUsageDailyRow)
                .where(MemoryUsageDailyRow.owner_id == owner_id)
                .order_by(MemoryUsageDailyRow.usage_date)
            )
        ]


def _touch_contact(
    factory: sessionmaker[Session], contact_id: UUID, when: datetime, **values: object
) -> None:
    with factory.begin() as session:
        session.execute(
            update(ContactRow).where(ContactRow.id == contact_id).values(updated_at=when, **values)
        )


def _set_row(factory: sessionmaker[Session], row_id: UUID, **values: object) -> None:
    with factory.begin() as session:
        session.execute(
            update(MemorySourceRow).where(MemorySourceRow.id == row_id).values(**values)
        )


# --- Pure rules --------------------------------------------------------------------------------


def test_doc_key_is_a_stable_opaque_hmac_that_the_adapter_accepts() -> None:
    owner, source = uuid4(), uuid4()

    key = derive_doc_key(KEY, owner, MemoryKind.CONTACT, source)

    assert key == derive_doc_key(KEY, owner, MemoryKind.CONTACT, source)
    assert OPAQUE_ID_PATTERN.fullmatch(key)
    assert len(key) <= 128
    assert str(owner) not in key
    assert str(source) not in key
    assert re.fullmatch(r"d1_[0-9a-f]{64}", key)


def test_doc_key_changes_with_owner_kind_source_and_key() -> None:
    owner, source = uuid4(), uuid4()
    base = derive_doc_key(KEY, owner, MemoryKind.CONTACT, source)

    assert base != derive_doc_key(KEY, uuid4(), MemoryKind.CONTACT, source)
    assert base != derive_doc_key(KEY, owner, MemoryKind.TASK, source)
    assert base != derive_doc_key(KEY, owner, MemoryKind.CONTACT, uuid4())
    assert base != derive_doc_key(b"x" * 32, owner, MemoryKind.CONTACT, source)
    with pytest.raises(ValueError, match="derivation key"):
        derive_doc_key(b"", owner, MemoryKind.CONTACT, source)


def test_backoff_doubles_from_five_minutes_and_caps_at_six_hours() -> None:
    assert [retry_backoff(n) for n in range(1, 8)] == [
        timedelta(minutes=5),
        timedelta(minutes=10),
        timedelta(minutes=20),
        timedelta(minutes=40),
        timedelta(minutes=80),
        timedelta(minutes=160),
        timedelta(minutes=320),
    ]
    assert retry_backoff(9) == timedelta(hours=6)
    assert retry_backoff(10_000) == timedelta(hours=6)
    assert retry_backoff(0) == timedelta(minutes=5)


def test_backfill_starts_at_the_age_boundary() -> None:
    assert not is_backfill(NOW, NOW + BACKFILL_AGE - timedelta(seconds=1))
    assert is_backfill(NOW, NOW + BACKFILL_AGE)


def test_retain_timestamp_is_utc_midnight_or_unset() -> None:
    assert retain_timestamp(None) == "unset"
    assert retain_timestamp(date(2026, 10, 20)) == "2026-10-20T00:00:00+00:00"


def _candidate(age_minutes: int, *, backfill: bool = False) -> SendCandidate:
    row_id = new_uuid7()
    return SendCandidate(
        row_id=row_id,
        source_updated_at=NOW - timedelta(minutes=age_minutes),
        backfill=backfill,
        item=RetainItem(
            document_id=f"d1_{row_id.hex}",
            content="text",
            timestamp="unset",
            entities=(),
            tags=("k:contact",),
        ),
        fingerprint="0" * 64,
    )


def test_select_batch_is_newest_first_and_counts_live_and_backfill_separately() -> None:
    live = [_candidate(minutes) for minutes in (5, 1, 9)]
    old = [_candidate(minutes, backfill=True) for minutes in (30, 20)]

    picked = select_batch([*old, *live], live_remaining=2, backfill_remaining=1)

    assert [c.source_updated_at for c in picked] == [
        NOW - timedelta(minutes=1),
        NOW - timedelta(minutes=5),
        NOW - timedelta(minutes=20),
    ]


def test_select_batch_respects_zero_budgets_and_the_batch_limit() -> None:
    live = [_candidate(minutes) for minutes in range(30)]

    assert select_batch(live, live_remaining=0, backfill_remaining=99) == []
    assert select_batch(live, live_remaining=-3, backfill_remaining=99) == []
    assert len(select_batch(live, live_remaining=99, backfill_remaining=0)) == 20
    assert len(select_batch(live, live_remaining=4, backfill_remaining=0)) == 4


def test_policy_comes_from_settings_and_needs_a_key() -> None:
    settings = Settings(
        _env_file=None,
        memory_enabled=True,
        memory_id_derivation_key="a-memory-derivation-key",
        memory_ingest_enabled=False,
        memory_daily_retain_cap=7,
        memory_backfill_daily_cap=9,
    )

    policy = SyncPolicy.from_settings(settings)

    assert policy.id_key == b"a-memory-derivation-key"
    assert policy.enabled is True
    assert policy.ingest_enabled is False
    assert policy.quiet == timedelta(seconds=600)
    assert (policy.daily_retain_cap, policy.backfill_daily_cap) == (7, 9)
    with pytest.raises(ValueError, match="derivation key"):
        SyncPolicy.from_settings(Settings(_env_file=None, memory_enabled=True))
    with pytest.raises(ValueError, match="derivation key"):
        SyncPolicy(id_key=b"")


# --- Create, edit, quiet period ----------------------------------------------------------------


@pytest.mark.integration
def test_a_new_record_is_queued_sent_and_then_retained() -> None:
    factory, owner, provider, clock, reconciler = _setup()
    contact = _new_contact(factory, owner)

    first = reconciler.reconcile_owner(owner)

    assert (first.status, first.queued, first.sent) == ("completed", 1, 1)
    row = _row(factory, contact)
    assert row.status == "submitted"
    assert row.operation_id is not None
    assert row.doc_key == derive_doc_key(KEY, owner, MemoryKind.CONTACT, contact)
    assert row.attempts == 1
    assert row.next_attempt_at == LIVE_NOW + OPERATION_DEADLINE
    assert len(provider.retain_calls) == 1
    call = provider.retain_calls[0]
    assert call.owner_id == owner
    assert [item.document_id for item in call.items] == [row.doc_key]
    assert call.items[0].timestamp == "unset"
    assert call.items[0].tags == ("k:contact",)

    clock.advance(timedelta(minutes=1))
    second = reconciler.reconcile_owner(owner)

    assert second.retained == 1
    settled = _row(factory, contact)
    assert (settled.status, settled.attempts, settled.operation_id) == ("retained", 0, None)
    assert settled.retained_at == clock.current
    assert len(provider.retain_calls) == 1


@pytest.mark.integration
def test_a_record_inside_the_quiet_period_waits_and_an_edit_inside_it_is_sent_once() -> None:
    factory, owner, provider, clock, reconciler = _setup(NOW + timedelta(minutes=5))
    contact = _new_contact(factory, owner)

    assert reconciler.reconcile_owner(owner).queued == 0
    assert _rows(factory, owner) == []

    _touch_contact(
        factory, contact, NOW + timedelta(minutes=6), context_note="Ny text efter redigering."
    )
    clock.current = NOW + timedelta(minutes=12)
    assert reconciler.reconcile_owner(owner).queued == 0
    assert provider.retain_calls == []

    clock.current = NOW + timedelta(minutes=17)
    result = reconciler.reconcile_owner(owner)

    assert (result.queued, result.sent) == (1, 1)
    assert len(provider.retain_calls) == 1
    assert "Ny text efter redigering." in provider.retain_calls[0].items[0].content


@pytest.mark.integration
def test_an_edit_after_retention_sends_a_replacement_once_and_keeps_the_document_id() -> None:
    factory, owner, provider, clock, reconciler = _setup()
    contact = _new_contact(factory, owner)
    _drive_to_retained(reconciler, owner, clock)
    doc_key = _row(factory, contact).doc_key

    _touch_contact(factory, contact, clock.current, context_note="Flyttade till Malmö.")
    clock.advance(timedelta(minutes=11))
    reconciler.reconcile_owner(owner)
    clock.advance(timedelta(minutes=1))
    reconciler.reconcile_owner(owner)

    assert [c.items[0].document_id for c in provider.retain_calls] == [doc_key, doc_key]
    assert _row(factory, contact).status == "retained"
    texts = [fact.text for fact in provider.recall(owner_id=owner, query="Malmö", max_tokens=100)]
    assert any("Malmö" in text for text in texts)
    assert not provider.recall(owner_id=owner, query="Lund", max_tokens=100)


@pytest.mark.integration
def test_a_task_status_change_does_not_change_the_fingerprint_and_sends_nothing() -> None:
    factory, owner, provider, clock, reconciler = _setup()
    task = _task(factory, owner, "Boka resa", description=LONG_TEXT)
    _drive_to_retained(reconciler, owner, clock)
    before = _row(factory, task)

    with factory.begin() as session:
        session.execute(
            update(TaskRow)
            .where(TaskRow.id == task)
            .values(status="in_progress", priority="high", updated_at=clock.current)
        )
    clock.advance(timedelta(minutes=11))
    result = reconciler.reconcile_owner(owner)

    assert (result.queued, result.sent) == (0, 0)
    after = _row(factory, task)
    assert after.fingerprint == before.fingerprint
    assert after.status == "retained"
    assert after.source_updated_at > before.source_updated_at
    assert len(provider.retain_calls) == 1


@pytest.mark.integration
def test_two_passes_in_a_row_are_a_no_op() -> None:
    factory, owner, provider, clock, reconciler = _setup()
    _new_contact(factory, owner)
    domain = _domain(factory, owner)
    _project(factory, owner, domain, "Flytt", description=LONG_TEXT)
    _task(factory, owner, "Skriv", description=LONG_TEXT)
    _entry(factory, owner, _source(factory, owner, "Råtext."), "Dag")
    _drive_to_retained(reconciler, owner, clock)
    snapshot = _snapshot(factory, owner)
    usage = _usage(factory, owner)
    calls = (len(provider.retain_calls), len(provider.delete_calls), len(provider.status_calls))

    result = reconciler.reconcile_owner(owner)

    assert (result.queued, result.sent, result.retained, result.deleted) == (0, 0, 0, 0)
    assert result.error_categories == {}
    assert _snapshot(factory, owner) == snapshot
    assert _usage(factory, owner) == usage
    assert calls == (
        len(provider.retain_calls),
        len(provider.delete_calls),
        len(provider.status_calls),
    )
    assert len(snapshot) == 4


@pytest.mark.integration
def test_all_four_kinds_are_sent_with_their_tags() -> None:
    factory, owner, provider, _clock, reconciler = _setup()
    _new_contact(factory, owner)
    domain = _domain(factory, owner)
    _project(factory, owner, domain, "Flytt", description=LONG_TEXT)
    _task(factory, owner, "Skriv", description=LONG_TEXT)
    _entry(factory, owner, _source(factory, owner, "Råtext."), "Dag")

    reconciler.reconcile_owner(owner)

    tags = sorted(item.tags[0] for call in provider.retain_calls for item in call.items)
    assert tags == ["k:contact", "k:journal_entry", "k:project", "k:task"]


# --- Lifecycle: trash, delete, domain switch, non-candidates -----------------------------------


@pytest.mark.integration
def test_trash_keeps_the_document_and_restore_costs_no_retain() -> None:
    factory, owner, provider, clock, reconciler = _setup()
    contact = _new_contact(factory, owner)
    _drive_to_retained(reconciler, owner, clock)
    retained = _snapshot(factory, owner)

    _touch_contact(factory, contact, NOW, trashed_at=clock.current)
    clock.advance(timedelta(minutes=2))
    trashed = reconciler.reconcile_owner(owner)

    assert (trashed.deleted, trashed.sent, trashed.queued) == (0, 0, 0)
    assert provider.delete_calls == []
    assert _snapshot(factory, owner) == retained

    _touch_contact(factory, contact, NOW, trashed_at=None)
    clock.advance(timedelta(minutes=2))
    restored = reconciler.reconcile_owner(owner)

    assert (restored.deleted, restored.sent, restored.queued) == (0, 0, 0)
    assert provider.delete_calls == []
    assert len(provider.retain_calls) == 1
    assert _snapshot(factory, owner) == retained


@pytest.mark.integration
def test_permanent_deletion_deletes_the_document_and_removes_the_row() -> None:
    factory, owner, provider, clock, reconciler = _setup()
    contact = _new_contact(factory, owner)
    _drive_to_retained(reconciler, owner, clock)
    doc_key = _row(factory, contact).doc_key

    with factory.begin() as session:
        session.execute(delete(ContactRow).where(ContactRow.id == contact))
    clock.advance(timedelta(minutes=1))
    result = reconciler.reconcile_owner(owner)

    assert result.deleted == 1
    assert provider.delete_calls == [(owner, doc_key)]
    assert _rows(factory, owner) == []
    assert not provider.recall(owner_id=owner, query="Lund", max_tokens=100)


@pytest.mark.integration
def test_switching_a_domain_off_deletes_that_domains_documents_only() -> None:
    factory, owner, provider, clock, reconciler = _setup()
    contact = _new_contact(factory, owner)
    task = _task(factory, owner, "Skriv", description=LONG_TEXT)
    _drive_to_retained(reconciler, owner, clock)
    contact_key = _row(factory, contact).doc_key

    with factory.begin() as session:
        session.execute(
            update(MemorySettingsRow)
            .where(MemorySettingsRow.owner_id == owner)
            .values(contacts=False)
        )
    clock.advance(timedelta(minutes=1))
    result = reconciler.reconcile_owner(owner)

    assert result.deleted == 1
    assert provider.delete_calls == [(owner, contact_key)]
    assert [row.source_id for row in _rows(factory, owner)] == [task]


@pytest.mark.integration
def test_a_record_that_stops_qualifying_loses_its_document_at_once() -> None:
    factory, owner, provider, clock, reconciler = _setup()
    contact = _new_contact(factory, owner)
    _drive_to_retained(reconciler, owner, clock)
    doc_key = _row(factory, contact).doc_key

    # Blank text means a bare name: no longer a candidate. The edit is inside the quiet period,
    # and the delete must not wait for it.
    _touch_contact(factory, contact, clock.current, context_note=None)
    result = reconciler.reconcile_owner(owner)

    assert result.deleted == 1
    assert provider.delete_calls == [(owner, doc_key)]
    assert _rows(factory, owner) == []


@pytest.mark.integration
def test_a_journal_entry_replaced_by_a_new_source_loses_its_document() -> None:
    factory, owner, provider, clock, reconciler = _setup()
    old_source = _source(factory, owner, "Gammal text")
    old_entry = _entry(factory, owner, old_source, "Gammal")
    _drive_to_retained(reconciler, owner, clock)
    old_key = _row(factory, old_entry).doc_key
    new_entry = _entry(
        factory, owner, _source(factory, owner, "Ny text", replaces=old_source), "Ny"
    )

    clock.advance(timedelta(hours=1))
    result = reconciler.reconcile_owner(owner)

    assert old_key in [key for _, key in provider.delete_calls]
    assert result.deleted == 1
    assert {row.source_id for row in _rows(factory, owner)} == {new_entry}


@pytest.mark.integration
def test_two_owners_are_isolated() -> None:
    factory, owner, provider, clock, reconciler = _setup()
    other = _owner(factory)
    _enable_all(factory, other)
    mine = _new_contact(factory, owner, "Ada")
    theirs = _new_contact(factory, other, "Bo")

    reconciler.reconcile_owner(owner)

    assert {call.owner_id for call in provider.retain_calls} == {owner}
    assert _rows(factory, other) == []
    reconciler.reconcile_owner(other)
    clock.advance(timedelta(minutes=1))
    reconciler.reconcile_owner(owner)
    reconciler.reconcile_owner(other)
    assert {row.source_id for row in _rows(factory, owner)} == {mine}
    assert {row.source_id for row in _rows(factory, other)} == {theirs}
    assert _row(factory, mine).doc_key != _row(factory, theirs).doc_key

    with factory.begin() as session:
        session.execute(delete(ContactRow).where(ContactRow.id == theirs))
    clock.advance(timedelta(minutes=1))
    reconciler.reconcile_owner(owner)
    assert provider.delete_calls == []
    reconciler.reconcile_owner(other)
    assert [owner_id for owner_id, _ in provider.delete_calls] == [other]
    assert [row.source_id for row in _rows(factory, owner)] == [mine]


@pytest.mark.integration
def test_reconcile_all_runs_every_owner_that_has_memory_state() -> None:
    factory, owner, provider, _clock, reconciler = _setup()
    other = _owner(factory)
    _enable_all(factory, other)
    _owner(factory)  # An owner without memory settings is not visited.
    _new_contact(factory, owner)
    _new_contact(factory, other, "Bo")

    results = reconciler.reconcile_all()

    assert sorted(r.owner_id for r in results) == sorted([owner, other])
    assert {call.owner_id for call in provider.retain_calls} == {owner, other}


# --- Locking -----------------------------------------------------------------------------------


@pytest.mark.integration
def test_a_locked_owner_is_skipped_and_the_lock_is_released_after_a_pass() -> None:
    factory, owner, provider, _clock, reconciler = _setup()
    _new_contact(factory, owner)
    with factory() as session:
        engine = session.get_bind()
    holder = engine.connect().execution_options(isolation_level="AUTOCOMMIT")  # type: ignore[union-attr]
    try:
        holder.execute(select(func.pg_advisory_lock(_lock_key(owner))))

        skipped = reconciler.reconcile_owner(owner)

        assert skipped.status == "locked"
        assert provider.retain_calls == []
        assert _rows(factory, owner) == []
    finally:
        holder.execute(select(func.pg_advisory_unlock(_lock_key(owner))))
        holder.close()

    done = reconciler.reconcile_owner(owner)
    assert (done.status, done.sent) == ("completed", 1)
    with factory() as session:
        engine = session.get_bind()
    probe = engine.connect().execution_options(isolation_level="AUTOCOMMIT")  # type: ignore[union-attr]
    try:
        assert probe.execute(select(func.pg_try_advisory_lock(_lock_key(owner)))).scalar() is True
    finally:
        probe.execute(select(func.pg_advisory_unlock(_lock_key(owner))))
        probe.close()


@pytest.mark.integration
def test_the_lock_is_released_when_a_pass_raises() -> None:
    factory, owner, provider, clock, reconciler = _setup()
    _new_contact(factory, owner)
    provider.crash_after_retain = True

    with pytest.raises(RuntimeError):
        reconciler.reconcile_owner(owner)

    provider.crash_after_retain = False
    clock.advance(timedelta(hours=1))
    assert reconciler.reconcile_owner(owner).status == "completed"


@pytest.mark.integration
def test_a_disabled_policy_does_nothing() -> None:
    factory, owner, provider, _clock, reconciler = _setup(enabled=False)
    _new_contact(factory, owner)

    result = reconciler.reconcile_owner(owner)

    assert result.status == "disabled"
    assert provider.retain_calls == [] and _rows(factory, owner) == []


# --- Budgets -----------------------------------------------------------------------------------


@pytest.mark.integration
def test_the_daily_live_cap_limits_sending_and_resets_the_next_day() -> None:
    factory, owner, provider, clock, reconciler = _setup(daily_retain_cap=2, backfill_daily_cap=1)
    ids = [_new_contact(factory, owner, f"Kontakt {n}") for n in range(5)]
    for position, contact in enumerate(ids):
        _touch_contact(factory, contact, NOW + timedelta(minutes=position))

    first = reconciler.reconcile_owner(owner)

    assert (first.sent, first.deferred_by_budget) == (2, 3)
    sent_first = {item.document_id for c in provider.retain_calls for item in c.items}
    newest = {_row(factory, ids[3]).doc_key, _row(factory, ids[4]).doc_key}
    assert sent_first == newest
    day = LIVE_NOW.date()
    assert _usage(factory, owner)[0][:3] == (day, 2, 0)
    assert _usage(factory, owner)[0][3] > 0

    clock.advance(timedelta(minutes=5))
    again = reconciler.reconcile_owner(owner)
    assert again.sent == 0
    assert len(provider.retain_calls) == 1

    # The next UTC day the leftovers are over 24 h old, so they use the backfill cap of one.
    clock.current = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=UTC) + (
        timedelta(hours=12)
    )
    next_day = reconciler.reconcile_owner(owner)
    assert next_day.sent == 1
    usage = _usage(factory, owner)
    assert [u[:3] for u in usage] == [(day, 2, 0), (day + timedelta(days=1), 0, 1)]


@pytest.mark.integration
def test_backfill_has_its_own_cap_and_goes_newest_first() -> None:
    factory, owner, provider, _clock, reconciler = _setup(
        OLD_NOW, daily_retain_cap=0, backfill_daily_cap=3
    )
    ids = [_new_contact(factory, owner, f"Kontakt {n}") for n in range(5)]
    for position, contact in enumerate(ids):
        _touch_contact(factory, contact, NOW + timedelta(minutes=position))

    result = reconciler.reconcile_owner(owner)

    assert result.sent == 3
    sent = {item.document_id for c in provider.retain_calls for item in c.items}
    assert sent == {_row(factory, contact).doc_key for contact in ids[2:]}
    assert [u[1:3] for u in _usage(factory, owner)] == [(0, 3)]


@pytest.mark.integration
def test_a_pass_sends_one_batch_of_at_most_twenty() -> None:
    factory, owner, provider, clock, reconciler = _setup()
    for n in range(25):
        _new_contact(factory, owner, f"Kontakt {n}")

    first = reconciler.reconcile_owner(owner)
    clock.advance(timedelta(minutes=1))
    second = reconciler.reconcile_owner(owner)

    assert first.sent == 20
    assert provider.retain_attempts == [20, 5]
    assert second.sent == 5
    assert {row.status for row in _rows(factory, owner)} == {"submitted", "retained"}


@pytest.mark.integration
def test_a_zero_cap_sends_nothing_but_still_queues_and_deletes() -> None:
    factory, owner, provider, _clock, reconciler = _setup(daily_retain_cap=0, backfill_daily_cap=0)
    _new_contact(factory, owner)

    result = reconciler.reconcile_owner(owner)

    assert (result.queued, result.sent, result.deferred_by_budget) == (1, 0, 1)
    assert provider.retain_attempts == []
    assert _usage(factory, owner) == []


# --- Pause and kill switch ---------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize("mode", ["owner_paused", "ingest_disabled"])
def test_pause_and_kill_switch_stop_sends_but_deletes_still_run(mode: str) -> None:
    factory, owner, provider, clock, reconciler = _setup()
    retained = _new_contact(factory, owner, "Ada")
    _drive_to_retained(reconciler, owner, clock)
    doomed_key = _row(factory, retained).doc_key
    fresh = _new_contact(factory, owner, "Bo")
    if mode == "owner_paused":
        with factory.begin() as session:
            session.execute(
                update(MemorySettingsRow)
                .where(MemorySettingsRow.owner_id == owner)
                .values(paused=True)
            )
    else:
        reconciler = _reconciler(factory, provider, clock, ingest_enabled=False)
    with factory.begin() as session:
        session.execute(delete(ContactRow).where(ContactRow.id == retained))
    clock.advance(timedelta(minutes=1))

    result = reconciler.reconcile_owner(owner)

    assert result.sending_blocked is True
    assert (result.sent, result.deleted) == (0, 1)
    assert provider.delete_calls == [(owner, doomed_key)]
    assert len(provider.retain_calls) == 1
    # The new record is queued (state is tracked) but nothing leaves the process.
    assert _row(factory, fresh).status == "pending"


class _PolicyChangingProvider(ScriptedProvider):
    """A slow retain: the owner changes the policy while the provider call is in flight."""

    def __init__(self, change: Callable[[], None]) -> None:
        super().__init__()
        self._change = change

    def retain_batch(self, *, owner_id: UUID, items: Sequence[RetainItem]) -> str:
        operation_id = super().retain_batch(owner_id=owner_id, items=items)
        self._change()
        return operation_id


@pytest.mark.integration
@pytest.mark.parametrize("change", ["paused", "kind_off", "excluded"])
def test_a_retain_that_returns_after_the_policy_changed_is_not_recorded_as_synced(
    change: str,
) -> None:
    factory = database_factory()
    owner = _owner(factory)
    _enable_all(factory, owner)
    contact = _new_contact(factory, owner)
    clock = FakeClock(LIVE_NOW)

    def owner_changes_the_policy() -> None:
        with factory.begin() as session:
            if change == "excluded":
                session.execute(
                    update(MemorySourceRow)
                    .where(MemorySourceRow.source_id == contact)
                    .values(excluded=True)
                )
            else:
                values = {"paused": True} if change == "paused" else {"contacts": False}
                session.execute(
                    update(MemorySettingsRow)
                    .where(MemorySettingsRow.owner_id == owner)
                    .values(**values)
                )

    provider = _PolicyChangingProvider(owner_changes_the_policy)

    result = _reconciler(factory, provider, clock).reconcile_owner(owner)

    assert (result.sent, result.discarded_by_policy) == (0, 1)
    row = _row(factory, contact)
    assert (row.status, row.operation_id) == ("pending", None)
    # The attempt left evidence that the document may exist, so a later removal deletes it twice.
    assert row.retained_at is not None
    # Nothing is polled or marked retained afterwards either.
    clock.advance(timedelta(minutes=1))
    assert _reconciler(factory, provider, clock).reconcile_owner(owner).retained == 0


@pytest.mark.integration
def test_a_retain_whose_policy_did_not_change_is_still_recorded_as_submitted() -> None:
    factory = database_factory()
    owner = _owner(factory)
    _enable_all(factory, owner)
    contact = _new_contact(factory, owner)
    provider = _PolicyChangingProvider(lambda: None)

    result = _reconciler(factory, provider, FakeClock(LIVE_NOW)).reconcile_owner(owner)

    assert (result.sent, result.discarded_by_policy) == (1, 0)
    assert _row(factory, contact).status == "submitted"


@pytest.mark.integration
def test_polling_continues_while_sending_is_paused() -> None:
    factory, owner, provider, clock, reconciler = _setup()
    contact = _new_contact(factory, owner)
    reconciler.reconcile_owner(owner)
    reconciler = _reconciler(factory, provider, clock, ingest_enabled=False)
    clock.advance(timedelta(minutes=1))

    result = reconciler.reconcile_owner(owner)

    assert result.retained == 1
    assert _row(factory, contact).status == "retained"


# --- Operations, failures, retries -------------------------------------------------------------


@pytest.mark.integration
def test_a_pending_operation_is_left_alone_until_it_finishes() -> None:
    factory, owner, provider, clock, reconciler = _setup()
    contact = _new_contact(factory, owner)
    provider.operation_override = OperationResult(state="pending")
    reconciler.reconcile_owner(owner)

    for _ in range(3):
        clock.advance(timedelta(minutes=5))
        result = reconciler.reconcile_owner(owner)
        assert (result.retained, result.failed, result.sent) == (0, 0, 0)
    assert _row(factory, contact).status == "submitted"
    assert len(provider.retain_calls) == 1

    provider.operation_override = None
    clock.advance(timedelta(minutes=1))
    assert reconciler.reconcile_owner(owner).retained == 1


@pytest.mark.integration
def test_an_operation_still_pending_after_the_deadline_is_lost_and_retried() -> None:
    factory, owner, provider, clock, reconciler = _setup()
    contact = _new_contact(factory, owner)
    provider.operation_override = OperationResult(state="pending")
    reconciler.reconcile_owner(owner)

    clock.advance(OPERATION_DEADLINE + timedelta(minutes=1))
    result = reconciler.reconcile_owner(owner)

    assert result.failed == 1
    row = _row(factory, contact)
    assert (row.status, row.failure_category, row.attempts) == ("failed", "operation_lost", 1)
    assert row.operation_id is None
    assert row.next_attempt_at == clock.current + timedelta(minutes=5)

    provider.operation_override = None
    clock.advance(timedelta(minutes=6))
    reconciler.reconcile_owner(owner)
    assert len(provider.retain_calls) == 2
    assert {c.items[0].document_id for c in provider.retain_calls} == {row.doc_key}


@pytest.mark.integration
def test_a_failed_operation_backs_off_then_retries_then_parks_after_six_attempts() -> None:
    factory, owner, provider, clock, reconciler = _setup()
    contact = _new_contact(factory, owner)
    provider.operation_override = OperationResult(
        state="failed", failure_category="operation_failed"
    )

    reconciler.reconcile_owner(owner)  # attempt 1 sent
    clock.advance(timedelta(minutes=1))
    reconciler.reconcile_owner(owner)  # operation failed
    row = _row(factory, contact)
    assert (row.status, row.attempts, row.failure_category) == ("failed", 1, "operation_failed")
    assert row.next_attempt_at == clock.current + timedelta(minutes=5)

    clock.advance(timedelta(minutes=4))
    assert reconciler.reconcile_owner(owner).sent == 0  # backoff not over
    assert len(provider.retain_calls) == 1

    for expected_attempts in range(2, MAX_ATTEMPTS + 1):
        clock.advance(timedelta(hours=7))
        assert reconciler.reconcile_owner(owner).sent == 1  # resend
        assert _row(factory, contact).attempts == expected_attempts
        clock.advance(timedelta(minutes=1))
        reconciler.reconcile_owner(owner)  # fails again
        if expected_attempts < MAX_ATTEMPTS:
            assert _row(factory, contact).status == "failed"

    parked = _row(factory, contact)
    assert (parked.status, parked.attempts, parked.next_attempt_at) == (
        "parked",
        MAX_ATTEMPTS,
        None,
    )
    assert parked.failure_category == "operation_failed"
    sends = len(provider.retain_calls)

    clock.advance(timedelta(days=2))
    assert reconciler.reconcile_owner(owner).sent == 0
    assert len(provider.retain_calls) == sends

    # A change of content is a new chance.
    provider.operation_override = None
    _touch_contact(factory, contact, clock.current, context_note="Helt ny text om Ada.")
    clock.advance(timedelta(minutes=11))
    changed = reconciler.reconcile_owner(owner)
    assert (changed.queued, changed.sent) == (1, 1)
    fresh = _row(factory, contact)
    assert (fresh.status, fresh.attempts, fresh.failure_category) == ("submitted", 1, None)


@pytest.mark.integration
def test_a_provider_outage_at_send_time_backs_off_refunds_and_never_loses_the_record() -> None:
    factory, owner, provider, clock, reconciler = _setup()
    contact = _new_contact(factory, owner)
    provider.retain_error = "unavailable"

    result = reconciler.reconcile_owner(owner)

    assert (result.sent, result.failed) == (0, 1)
    assert result.error_categories == {"unavailable": 1}
    row = _row(factory, contact)
    # An outage says nothing about this document: the attempt is given back, not counted.
    assert (row.status, row.failure_category, row.attempts) == ("failed", "unavailable", 0)
    assert [u[1:4] for u in _usage(factory, owner)] == [(0, 0, 0)]

    provider.retain_error = None
    clock.advance(timedelta(minutes=6))
    reconciler.reconcile_owner(owner)
    assert _row(factory, contact).status == "submitted"
    assert len(provider.retain_calls) == 1


@pytest.mark.integration
def test_an_ambiguous_timeout_is_not_refunded_because_the_batch_may_have_arrived() -> None:
    factory, owner, provider, _clock, reconciler = _setup()
    _new_contact(factory, owner)
    provider.retain_error = "timeout"

    reconciler.reconcile_owner(owner)

    assert _usage(factory, owner)[0][1] == 1


@pytest.mark.integration
def test_three_failures_in_a_row_pause_sending_for_thirty_minutes() -> None:
    factory, owner, provider, clock, reconciler = _setup()
    contact = _new_contact(factory, owner)
    provider.retain_error = "unavailable"

    reconciler.reconcile_owner(owner)
    clock.advance(timedelta(minutes=6))
    reconciler.reconcile_owner(owner)
    clock.advance(timedelta(minutes=11))
    third = reconciler.reconcile_owner(owner)
    assert third.sending_blocked is True
    assert _row(factory, contact).attempts == 0  # provider-wide failures are not counted
    assert provider.retain_attempts == [1, 1, 1]

    provider.retain_error = None
    clock.advance(timedelta(minutes=21))  # backoff is over, the pause is not
    blocked = reconciler.reconcile_owner(owner)
    assert (blocked.sending_blocked, blocked.sent) == (True, 0)

    clock.advance(timedelta(minutes=10))
    resumed = reconciler.reconcile_owner(owner)
    assert (resumed.sending_blocked, resumed.sent) == (False, 1)


@pytest.mark.integration
def test_one_bad_document_in_a_rejected_batch_does_not_take_its_neighbours_down() -> None:
    factory, owner, provider, _clock, reconciler = _setup()
    ids = [_new_contact(factory, owner, f"Kontakt {n}") for n in range(3)]
    bad_key = derive_doc_key(KEY, owner, MemoryKind.CONTACT, ids[1])
    provider.reject_ids = {bad_key}

    result = reconciler.reconcile_owner(owner)

    assert (result.sent, result.failed) == (2, 1)
    assert provider.retain_attempts == [3, 1, 1, 1]
    assert _row(factory, ids[1]).status == "failed"
    assert _row(factory, ids[1]).failure_category == "rejected"
    assert {_row(factory, ids[0]).status, _row(factory, ids[2]).status} == {"submitted"}
    assert _usage(factory, owner)[0][1] == 2  # the rejected document was refunded
    assert result.sending_blocked is False


@pytest.mark.integration
def test_a_provider_that_goes_down_while_polling_leaves_submissions_untouched() -> None:
    factory, owner, provider, clock, reconciler = _setup()
    contact = _new_contact(factory, owner)
    reconciler.reconcile_owner(owner)
    provider.status_error = "unavailable"
    clock.advance(timedelta(minutes=1))

    result = reconciler.reconcile_owner(owner)

    assert result.error_categories == {"unavailable": 1}
    assert _row(factory, contact).status == "submitted"


# --- Crash safety, deletion ordering, exclusion, versions --------------------------------------


@pytest.mark.integration
def test_a_crash_between_send_and_commit_resends_the_same_document_without_duplicates() -> None:
    factory, owner, provider, clock, reconciler = _setup()
    contact = _new_contact(factory, owner)
    provider.crash_after_retain = True

    with pytest.raises(RuntimeError):
        reconciler.reconcile_owner(owner)

    row = _row(factory, contact)
    assert (row.status, row.attempts) == ("pending", 1)
    assert row.next_attempt_at == LIVE_NOW + timedelta(minutes=5)
    assert _usage(factory, owner)[0][1] == 1  # charged: conservative on a crash
    facts_after_crash = provider.recall(owner_id=owner, query="Lund", max_tokens=100)

    provider.crash_after_retain = False
    restarted = _reconciler(factory, provider, clock)
    clock.advance(timedelta(minutes=1))
    assert restarted.reconcile_owner(owner).sent == 0  # not before the retry time
    clock.advance(timedelta(minutes=5))
    assert restarted.reconcile_owner(owner).sent == 1

    assert len(provider.retain_calls) == 2
    assert {c.items[0].document_id for c in provider.retain_calls} == {row.doc_key}
    assert provider.recall(owner_id=owner, query="Lund", max_tokens=100) == facts_after_crash
    assert _row(factory, contact).attempts == 2


@pytest.mark.integration
def test_a_delete_waits_for_a_submitted_operation_to_finish() -> None:
    factory, owner, provider, clock, reconciler = _setup()
    contact = _new_contact(factory, owner)
    provider.operation_override = OperationResult(state="pending")
    reconciler.reconcile_owner(owner)
    doc_key = _row(factory, contact).doc_key
    with factory.begin() as session:
        session.execute(delete(ContactRow).where(ContactRow.id == contact))

    clock.advance(timedelta(minutes=1))
    waiting = reconciler.reconcile_owner(owner)

    assert (waiting.deleted, waiting.delete_deferred) == (0, 1)
    assert provider.delete_calls == []
    assert _row(factory, contact).status == "submitted"

    provider.operation_override = None
    clock.advance(timedelta(minutes=1))
    done = reconciler.reconcile_owner(owner)

    assert (done.retained, done.deleted) == (1, 1)
    assert provider.delete_calls == [(owner, doc_key)]
    assert _rows(factory, owner) == []


@pytest.mark.integration
def test_a_failed_delete_is_retried_every_pass_without_an_attempt_limit() -> None:
    factory, owner, provider, clock, reconciler = _setup()
    contact = _new_contact(factory, owner)
    _drive_to_retained(reconciler, owner, clock)
    with factory.begin() as session:
        session.execute(delete(ContactRow).where(ContactRow.id == contact))
    provider.delete_error = "unavailable"

    for _ in range(MAX_ATTEMPTS + 2):
        clock.advance(timedelta(minutes=1))
        result = reconciler.reconcile_owner(owner)
        assert (result.deleted, result.delete_failed) == (0, 1)
    assert len(_rows(factory, owner)) == 1

    provider.delete_error = None
    clock.advance(timedelta(minutes=1))
    assert reconciler.reconcile_owner(owner).deleted == 1
    assert _rows(factory, owner) == []


@pytest.mark.integration
def test_exclusion_deletes_the_document_but_keeps_the_marker_and_is_reversible() -> None:
    factory, owner, provider, clock, reconciler = _setup()
    contact = _new_contact(factory, owner)
    _drive_to_retained(reconciler, owner, clock)
    row = _row(factory, contact)
    _set_row(factory, row.id, excluded=True)

    clock.advance(timedelta(minutes=1))
    excluded = reconciler.reconcile_owner(owner)

    assert excluded.deleted == 1
    assert provider.delete_calls == [(owner, row.doc_key)]
    marker = _row(factory, contact)
    assert (marker.excluded, marker.status, marker.failure_category) == (
        True,
        "parked",
        REMOVED_CATEGORY,
    )

    clock.advance(timedelta(minutes=1))
    quiet = reconciler.reconcile_owner(owner)
    assert (quiet.deleted, quiet.sent, quiet.queued) == (0, 0, 0)
    assert len(provider.delete_calls) == 1 and len(provider.retain_calls) == 1

    _set_row(factory, row.id, excluded=False)
    clock.advance(timedelta(minutes=1))
    back = reconciler.reconcile_owner(owner)
    assert (back.queued, back.sent) == (1, 1)
    assert len(provider.retain_calls) == 2
    assert _row(factory, contact).status == "submitted"


@pytest.mark.integration
def test_a_pipeline_version_bump_resends_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    factory, owner, _provider, clock, reconciler = _setup()
    contact = _new_contact(factory, owner)
    _drive_to_retained(reconciler, owner, clock)
    before = _row(factory, contact)

    monkeypatch.setattr(domain_module, "MEMORY_PIPELINE_VERSION", 2)
    monkeypatch.setattr(pass_module, "MEMORY_PIPELINE_VERSION", 2)
    monkeypatch.setattr(rules_module, "MEMORY_PIPELINE_VERSION", 2)
    clock.advance(timedelta(minutes=1))
    result = reconciler.reconcile_owner(owner)

    assert (result.queued, result.sent) == (1, 1)
    after = _row(factory, contact)
    assert after.pipeline_version == 2
    assert after.fingerprint != before.fingerprint
    assert after.doc_key == before.doc_key


@pytest.mark.integration
def test_a_full_pass_catches_a_change_that_did_not_touch_updated_at() -> None:
    factory, owner, _provider, clock, reconciler = _setup()
    contact = _new_contact(factory, owner)
    _drive_to_retained(reconciler, owner, clock)
    with factory.begin() as session:
        session.execute(
            update(ContactRow)
            .where(ContactRow.id == contact)
            .values(context_note="Ändrad utan att updated_at rörs.")
        )
    clock.advance(timedelta(minutes=1))
    assert reconciler.reconcile_owner(owner).queued == 0

    full = reconciler.reconcile_owner(owner, full=True)

    assert (full.queued, full.sent) == (1, 1)


# --- Redaction -----------------------------------------------------------------------------------


class _Collect(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def sync_logs() -> Iterator[list[logging.LogRecord]]:
    """Capture the sync logger directly, so the suite's logging setup cannot hide records."""

    logger = logging.getLogger("sidekick.memory.sync")
    handler = _Collect()
    previous = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    try:
        yield handler.records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)


def _all_log_text(records: list[logging.LogRecord]) -> str:
    parts: list[str] = []
    for record in records:
        parts.append(record.getMessage())
        parts.append(repr(sorted((k, repr(v)) for k, v in record.__dict__.items())))
    return "\n".join(parts)


@pytest.mark.integration
def test_logs_and_results_never_contain_titles_text_or_names(
    sync_logs: list[logging.LogRecord],
) -> None:
    factory, owner, provider, clock, reconciler = _setup()
    contact = _contact(
        factory, owner, "Tyra Backstrom", context_note=SECRET_NOTE, relationship="vän"
    )
    domain = _domain(factory, owner)
    _project(factory, owner, domain, SECRET_TITLE, description=SECRET_NOTE)
    _entry(factory, owner, _source(factory, owner, SECRET_NOTE), SECRET_TITLE)
    provider.reject_ids = {derive_doc_key(KEY, owner, MemoryKind.CONTACT, contact)}

    results = [reconciler.reconcile_owner(owner)]
    clock.advance(timedelta(minutes=1))
    results.append(reconciler.reconcile_owner(owner))
    with factory.begin() as session:
        session.execute(delete(ContactRow).where(ContactRow.id == contact))
    provider.delete_error = "unavailable"
    clock.advance(timedelta(minutes=1))
    results.append(reconciler.reconcile_owner(owner))

    text = _all_log_text(sync_logs) + "\n".join(repr(r) for r in results)
    assert sync_logs, "the pass logs one structured record"
    for secret in (SECRET_TITLE, SECRET_NOTE, "Tyra", "Backstrom", "Hemlig"):
        assert secret not in text
    assert any(getattr(r, "correlation_id", None) for r in sync_logs)
    # Log records carry no owner or bank identifier at all.
    assert {getattr(r, "owner_id", None) for r in sync_logs} == {None}
    assert str(owner) not in _all_log_text(sync_logs)
    assert results[0].correlation_id != results[1].correlation_id


@pytest.mark.integration
def test_an_unexpected_failure_is_logged_by_type_only_and_the_correlation_id_is_kept(
    sync_logs: list[logging.LogRecord],
) -> None:
    factory, owner, provider, _clock, reconciler = _setup()
    _contact(factory, owner, "Ada", context_note=SECRET_NOTE)
    provider.crash_after_retain = True

    with pytest.raises(RuntimeError):
        reconciler.reconcile_owner(owner, correlation_id="corr-123")

    failures = [r for r in sync_logs if r.getMessage() == "memory_sync_failed"]
    assert len(failures) == 1
    record = failures[0]
    assert record.__dict__["error_type"] == "RuntimeError"
    assert record.__dict__["correlation_id"] == "corr-123"
    assert record.exc_info is None
    assert "simulated crash" not in _all_log_text(sync_logs)
    assert SECRET_NOTE not in _all_log_text(sync_logs)


# --- No resurrection after a delete ---


def _engine_of(factory: sessionmaker[Session]) -> Engine:
    with factory() as session:
        bind = session.get_bind()
    assert isinstance(bind, Engine)
    return bind


def _doc_present(provider: FakeMemoryProvider, owner: UUID, doc_key: str) -> bool:
    return any(
        fact.document_id == doc_key
        for fact in provider.recall(owner_id=owner, query="Lund granne", max_tokens=200)
    )


def _late_retain(provider: ScriptedProvider, owner: UUID, doc_key: str) -> None:
    """The provider applies an old, never-confirmed retain after the document was deleted."""

    provider.retain_batch(
        owner_id=owner,
        items=[
            RetainItem(
                document_id=doc_key,
                content="Ada bor i Lund och är granne.",
                timestamp="unset",
                entities=(),
                tags=("k:contact",),
            )
        ],
    )


def _delete_contact(factory: sessionmaker[Session], contact: UUID) -> None:
    with factory.begin() as session:
        session.execute(delete(ContactRow).where(ContactRow.id == contact))


def _assert_two_stage_delete(
    factory: sessionmaker[Session],
    owner: UUID,
    provider: ScriptedProvider,
    clock: FakeClock,
    reconciler: MemoryReconciler,
    contact: UUID,
    doc_key: str,
) -> None:
    """The record is permanently deleted: first delete keeps a marker, second one drops it."""

    _delete_contact(factory, contact)
    first = reconciler.reconcile_owner(owner)

    assert first.deleted == 1
    assert provider.delete_calls == [(owner, doc_key)]
    marker = _row(factory, contact)
    assert (marker.status, marker.failure_category) == ("parked", REMOVED_CATEGORY)
    assert (marker.operation_id, marker.attempts) == (None, 0)
    assert marker.next_attempt_at == clock.current + OPERATION_DEADLINE

    # The late retain brings the document back while the marker holds.
    _late_retain(provider, owner, doc_key)
    assert _doc_present(provider, owner, doc_key)
    clock.advance(OPERATION_DEADLINE - timedelta(minutes=1))
    waiting = reconciler.reconcile_owner(owner)
    assert (waiting.deleted, waiting.delete_deferred) == (0, 1)
    assert len(provider.delete_calls) == 1
    assert len(_rows(factory, owner)) == 1

    clock.advance(timedelta(minutes=2))
    second = reconciler.reconcile_owner(owner)

    assert second.deleted == 1
    assert provider.delete_calls == [(owner, doc_key)] * 2
    assert not _doc_present(provider, owner, doc_key)
    assert _rows(factory, owner) == []


@pytest.mark.integration
def test_a_crash_after_the_provider_accepted_the_retain_cannot_resurrect_a_deleted_record() -> None:
    factory, owner, provider, clock, reconciler = _setup()
    contact = _new_contact(factory, owner)
    provider.crash_after_retain = True
    with pytest.raises(RuntimeError):
        reconciler.reconcile_owner(owner)
    provider.crash_after_retain = False
    row = _row(factory, contact)
    assert (row.status, row.attempts) == ("pending", 1)
    clock.advance(timedelta(minutes=1))

    _assert_two_stage_delete(factory, owner, provider, clock, reconciler, contact, row.doc_key)


@pytest.mark.integration
def test_a_failed_submitted_commit_cannot_resurrect_a_deleted_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, owner, provider, clock, reconciler = _setup()
    contact = _new_contact(factory, owner)

    def broken_commit(_self: object, _items: object, _operation_id: str) -> None:
        raise RuntimeError("simulated failure while committing `submitted`")

    with monkeypatch.context() as patched:
        patched.setattr(send_module.BatchSender, "_mark_submitted", broken_commit)  # pyright: ignore[reportPrivateUsage]
        with pytest.raises(RuntimeError):
            reconciler.reconcile_owner(owner)
    row = _row(factory, contact)
    assert (row.status, row.operation_id) == ("pending", None)
    assert len(provider.retain_calls) == 1  # the provider did accept it
    clock.advance(timedelta(minutes=1))

    _assert_two_stage_delete(factory, owner, provider, clock, reconciler, contact, row.doc_key)


@pytest.mark.integration
def test_a_timed_out_retain_cannot_resurrect_a_deleted_record() -> None:
    factory, owner, provider, clock, reconciler = _setup()
    contact = _new_contact(factory, owner)
    provider.retain_error = "timeout"
    reconciler.reconcile_owner(owner)
    provider.retain_error = None
    row = _row(factory, contact)
    # The timeout was released as a provider-wide failure, yet the bank may hold the document.
    assert (row.status, row.attempts) == ("failed", 0)
    assert row.retained_at is not None
    clock.advance(timedelta(minutes=1))

    _assert_two_stage_delete(factory, owner, provider, clock, reconciler, contact, row.doc_key)


@pytest.mark.integration
def test_a_lost_operation_cannot_resurrect_a_deleted_record() -> None:
    factory, owner, provider, clock, reconciler = _setup()
    contact = _new_contact(factory, owner)
    provider.operation_override = OperationResult(state="pending")
    reconciler.reconcile_owner(owner)
    clock.advance(OPERATION_DEADLINE + timedelta(minutes=1))
    reconciler.reconcile_owner(owner)  # declared lost
    row = _row(factory, contact)
    assert (row.status, row.failure_category) == ("failed", "operation_lost")
    provider.operation_override = None

    _assert_two_stage_delete(factory, owner, provider, clock, reconciler, contact, row.doc_key)


@pytest.mark.integration
def test_a_failed_operation_row_that_is_deleted_gets_a_second_delete() -> None:
    factory, owner, provider, clock, reconciler = _setup()
    contact = _new_contact(factory, owner)
    provider.operation_override = OperationResult(
        state="failed", failure_category="operation_failed"
    )
    reconciler.reconcile_owner(owner)
    clock.advance(timedelta(minutes=1))
    reconciler.reconcile_owner(owner)
    row = _row(factory, contact)
    assert row.status == "failed"
    provider.operation_override = None

    _assert_two_stage_delete(factory, owner, provider, clock, reconciler, contact, row.doc_key)


@pytest.mark.integration
def test_a_row_that_never_reached_the_provider_is_dropped_after_one_delete() -> None:
    factory, owner, provider, _clock, reconciler = _setup()
    source = uuid4()
    with factory.begin() as session:
        row_id = new_uuid7()
        session.add(
            MemorySourceRow(
                id=row_id,
                owner_id=owner,
                source_kind=MemoryKind.CONTACT.value,
                source_id=source,
                doc_key=f"doc-{row_id}",
                fingerprint="a" * 64,
                pipeline_version=1,
                status="pending",
                attempts=0,
                source_updated_at=NOW,
                excluded=False,
            )
        )

    result = reconciler.reconcile_owner(owner)

    assert result.deleted == 1
    assert len(provider.delete_calls) == 1
    assert _rows(factory, owner) == []


@pytest.mark.integration
def test_a_settled_retained_row_is_dropped_after_one_delete() -> None:
    factory, owner, _provider, clock, reconciler = _setup()
    contact = _new_contact(factory, owner)
    _drive_to_retained(reconciler, owner, clock)
    _delete_contact(factory, contact)

    result = reconciler.reconcile_owner(owner)

    assert result.deleted == 1
    assert _rows(factory, owner) == []


@pytest.mark.integration
def test_an_unconfirmed_row_whose_domain_is_switched_off_keeps_a_marker_for_the_second_delete() -> (
    None
):
    factory, owner, provider, clock, reconciler = _setup()
    contact = _new_contact(factory, owner)
    provider.crash_after_retain = True
    with pytest.raises(RuntimeError):
        reconciler.reconcile_owner(owner)
    provider.crash_after_retain = False
    doc_key = _row(factory, contact).doc_key
    with factory.begin() as session:
        session.execute(
            update(MemorySettingsRow)
            .where(MemorySettingsRow.owner_id == owner)
            .values(contacts=False)
        )
    clock.advance(timedelta(minutes=1))

    reconciler.reconcile_owner(owner)

    marker = _row(factory, contact)
    assert (marker.status, marker.failure_category) == ("parked", REMOVED_CATEGORY)
    clock.advance(OPERATION_DEADLINE + timedelta(minutes=1))
    reconciler.reconcile_owner(owner)
    assert _rows(factory, owner) == []
    assert provider.delete_calls == [(owner, doc_key)] * 2


@pytest.mark.integration
def test_a_marker_of_a_live_record_finishes_its_second_delete_before_the_record_is_resent() -> None:
    factory, owner, provider, clock, reconciler = _setup()
    contact = _new_contact(factory, owner)
    provider.crash_after_retain = True
    with pytest.raises(RuntimeError):
        reconciler.reconcile_owner(owner)
    provider.crash_after_retain = False
    row = _row(factory, contact)
    # What `--wipe --and-pause` leaves behind for a record that still exists.
    _set_row(
        factory,
        row.id,
        status="parked",
        failure_category=REMOVED_CATEGORY,
        attempts=0,
        operation_id=None,
        next_attempt_at=clock.current + OPERATION_DEADLINE,
    )
    clock.advance(timedelta(minutes=1))

    waiting = reconciler.reconcile_owner(owner)

    assert (waiting.queued, waiting.sent, waiting.delete_deferred) == (0, 0, 1)
    assert len(provider.retain_calls) == 1
    assert provider.delete_calls == []

    clock.advance(OPERATION_DEADLINE)
    second = reconciler.reconcile_owner(owner)
    assert (second.deleted, second.sent) == (1, 0)
    assert provider.delete_calls == [(owner, row.doc_key)]
    assert _rows(factory, owner) == []

    clock.advance(timedelta(minutes=1))
    again = reconciler.reconcile_owner(owner)  # the record is queued afresh
    assert (again.queued, again.sent) == (1, 1)


@pytest.mark.integration
def test_an_excluded_unconfirmed_row_gets_its_second_delete_and_keeps_its_marker() -> None:
    factory, owner, provider, clock, reconciler = _setup()
    contact = _new_contact(factory, owner)
    provider.crash_after_retain = True
    with pytest.raises(RuntimeError):
        reconciler.reconcile_owner(owner)
    provider.crash_after_retain = False
    row = _row(factory, contact)
    _set_row(factory, row.id, excluded=True)
    clock.advance(timedelta(minutes=1))

    reconciler.reconcile_owner(owner)
    first = _row(factory, contact)
    assert first.excluded is True
    assert first.next_attempt_at == clock.current + OPERATION_DEADLINE

    clock.advance(OPERATION_DEADLINE + timedelta(minutes=1))
    reconciler.reconcile_owner(owner)

    settled = _row(factory, contact)
    assert (settled.excluded, settled.status, settled.next_attempt_at) == (True, "parked", None)
    assert provider.delete_calls == [(owner, row.doc_key)] * 2
    clock.advance(timedelta(minutes=1))
    assert reconciler.reconcile_owner(owner).deleted == 0


# --- Provider-wide failures are not attempts ---


@pytest.mark.integration
@pytest.mark.parametrize("category", ["unavailable", "timeout", "unauthorized", "rate_limited"])
def test_provider_wide_failures_never_count_toward_parking(
    category: MemoryFailureCategory,
) -> None:
    factory, owner, provider, clock, reconciler = _setup()
    contact = _new_contact(factory, owner)
    provider.retain_error = category

    for _ in range(MAX_ATTEMPTS + 3):
        reconciler.reconcile_owner(owner)
        clock.advance(timedelta(hours=1))  # past the backoff and the breaker pause

    row = _row(factory, contact)
    assert (row.status, row.failure_category, row.attempts) == ("failed", category, 0)
    assert len(provider.retain_attempts) >= MAX_ATTEMPTS + 3

    provider.retain_error = None
    reconciler.reconcile_owner(owner)
    assert _row(factory, contact).status == "submitted"


@pytest.mark.integration
def test_a_provider_wide_operation_failure_gives_the_attempt_back() -> None:
    factory, owner, provider, clock, reconciler = _setup()
    contact = _new_contact(factory, owner)
    provider.operation_override = OperationResult(state="failed", failure_category="rate_limited")
    reconciler.reconcile_owner(owner)
    clock.advance(timedelta(minutes=1))

    reconciler.reconcile_owner(owner)

    row = _row(factory, contact)
    assert (row.status, row.failure_category, row.attempts) == ("failed", "rate_limited", 0)


@pytest.mark.integration
def test_a_rejected_document_still_counts_and_parks() -> None:
    factory, owner, provider, clock, reconciler = _setup()
    contact = _new_contact(factory, owner)
    provider.reject_ids = {derive_doc_key(KEY, owner, MemoryKind.CONTACT, contact)}

    for _ in range(MAX_ATTEMPTS):
        reconciler.reconcile_owner(owner)
        clock.advance(timedelta(hours=7))

    row = _row(factory, contact)
    assert (row.status, row.failure_category, row.attempts) == ("parked", "rejected", MAX_ATTEMPTS)


# --- Daily character cap ---


def _candidate_chars(chars: int, age_minutes: int, *, backfill: bool = False) -> SendCandidate:
    row_id = new_uuid7()
    return SendCandidate(
        row_id=row_id,
        source_updated_at=NOW - timedelta(minutes=age_minutes),
        backfill=backfill,
        item=RetainItem(
            document_id=f"d1_{row_id.hex}",
            content="x" * chars,
            timestamp="unset",
            entities=(),
            tags=("k:contact",),
        ),
        fingerprint="0" * 64,
    )


def test_select_batch_skips_a_document_longer_than_what_is_left_today() -> None:
    newest_big = _candidate_chars(60, 1)
    small = _candidate_chars(30, 5)
    other_small = _candidate_chars(30, 9)

    picked = select_batch(
        [other_small, newest_big, small],
        live_remaining=9,
        backfill_remaining=9,
        char_cap=100,
        chars_used=50,
    )

    assert picked == [small]  # 60 > 50 left waits; one 30 fits; the next 30 does not (20 left)


def test_select_batch_sends_an_oversize_document_alone_on_a_fresh_day_only() -> None:
    oversize = _candidate_chars(500, 40)
    small = _candidate_chars(10, 1)

    fresh = select_batch(
        [small, oversize], live_remaining=9, backfill_remaining=9, char_cap=100, chars_used=0
    )
    busy = select_batch(
        [small, oversize], live_remaining=9, backfill_remaining=9, char_cap=100, chars_used=10
    )

    assert fresh == [oversize]
    assert busy == [small]


def test_select_batch_with_a_zero_char_cap_sends_nothing_and_none_means_unlimited() -> None:
    docs = [_candidate_chars(500, n) for n in range(3)]

    assert select_batch(docs, live_remaining=9, backfill_remaining=9, char_cap=0) == []
    assert len(select_batch(docs, live_remaining=9, backfill_remaining=9)) == 3


def test_policy_takes_the_char_cap_from_settings_and_refuses_a_negative_one() -> None:
    settings = Settings(
        _env_file=None,
        memory_enabled=True,
        memory_id_derivation_key="a-memory-derivation-key",
        memory_daily_char_cap=1234,
    )

    assert SyncPolicy.from_settings(settings).daily_char_cap == 1234
    assert SyncPolicy(id_key=KEY).daily_char_cap == 400_000
    with pytest.raises(ValueError, match="caps"):
        SyncPolicy(id_key=KEY, daily_char_cap=-1)


@pytest.mark.integration
def test_the_character_cap_is_enforced_across_passes_and_resets_the_next_day() -> None:
    factory, owner, provider, clock, first = _setup(daily_retain_cap=1)
    ids = [_new_contact(factory, owner, f"Kontakt {n}") for n in range(3)]
    for position, contact in enumerate(ids):
        _touch_contact(factory, contact, NOW + timedelta(minutes=position))
    first.reconcile_owner(owner)
    one_document = _usage(factory, owner)[0][3]
    assert one_document > 0

    # Room for exactly one more document of this size today.
    tight = _reconciler(factory, provider, clock, daily_char_cap=2 * one_document + 1)
    clock.advance(timedelta(minutes=1))
    second = tight.reconcile_owner(owner)

    assert (second.sent, second.deferred_by_budget) == (1, 1)
    assert _usage(factory, owner)[0][3] == 2 * one_document
    clock.advance(timedelta(minutes=1))
    third = tight.reconcile_owner(owner)
    assert (third.sent, third.deferred_by_budget) == (0, 1)
    assert _usage(factory, owner)[0][3] == 2 * one_document

    clock.current = datetime.combine(
        LIVE_NOW.date() + timedelta(days=1), datetime.min.time(), tzinfo=UTC
    ) + timedelta(hours=12)
    next_day = tight.reconcile_owner(owner)
    assert next_day.sent == 1


@pytest.mark.integration
def test_the_conditional_upsert_refuses_a_batch_past_the_character_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, owner, provider, clock, first = _setup()
    for n in range(2):
        _new_contact(factory, owner, f"Kontakt {n}")
    first.reconcile_owner(owner)
    one_document = _usage(factory, owner)[0][3] // 2
    for n in range(2, 4):
        _new_contact(factory, owner, f"Kontakt {n}")
    # A budget view that ignores the characters, so only the atomic upsert can say no.
    monkeypatch.setattr(send_module, "select_batch", lambda candidates, **_kw: list(candidates))
    tight = _reconciler(factory, provider, clock, daily_char_cap=3 * one_document)

    result = tight.reconcile_owner(owner)

    assert result.sent == 0
    assert result.deferred_by_budget == 2
    assert _usage(factory, owner)[0][3] == 2 * one_document


@pytest.mark.integration
def test_a_document_longer_than_the_whole_cap_is_sent_alone_on_a_fresh_day() -> None:
    factory, owner, provider, clock, reconciler = _setup(daily_char_cap=1)
    ids = [_new_contact(factory, owner, f"Kontakt {n}") for n in range(3)]
    for position, contact in enumerate(ids):
        _touch_contact(factory, contact, NOW + timedelta(minutes=position))

    first = reconciler.reconcile_owner(owner)

    assert (first.sent, first.deferred_by_budget) == (1, 2)
    assert [len(call.items) for call in provider.retain_calls] == [1]
    clock.advance(timedelta(minutes=5))
    assert reconciler.reconcile_owner(owner).sent == 0  # the day's characters are used up
    clock.current = datetime.combine(
        LIVE_NOW.date() + timedelta(days=1), datetime.min.time(), tzinfo=UTC
    ) + timedelta(hours=12)
    assert reconciler.reconcile_owner(owner).sent == 1


@pytest.mark.integration
def test_a_zero_character_cap_queues_but_sends_nothing() -> None:
    factory, owner, provider, _clock, reconciler = _setup(daily_char_cap=0)
    _new_contact(factory, owner)

    result = reconciler.reconcile_owner(owner)

    assert (result.queued, result.sent) == (1, 0)
    assert provider.retain_calls == []


# --- Full pass picks up changes that never touch updated_at ---


@pytest.mark.integration
def test_a_full_pass_updates_a_journal_document_when_a_linked_contact_is_renamed_or_trashed() -> (
    None
):
    factory, owner, _provider, clock, reconciler = _setup()
    contact = _new_contact(factory, owner, "Ada")
    entry = _entry(
        factory,
        owner,
        _source(factory, owner, "Råtext."),
        "Fika",
        summary="Vi träffades och pratade länge om resan.",
        contacts=(contact,),
    )
    _drive_to_retained(reconciler, owner, clock)
    before = _row(factory, entry)

    with factory.begin() as session:
        session.execute(
            update(ContactRow).where(ContactRow.id == contact).values(display_name="Beda")
        )
    clock.advance(timedelta(minutes=1))
    assert reconciler.reconcile_owner(owner).queued == 0  # an ordinary pass cannot see it

    renamed = reconciler.reconcile_owner(owner, full=True)

    assert renamed.queued >= 1
    after = _row(factory, entry)
    assert after.fingerprint != before.fingerprint
    assert after.status in ("pending", "submitted")

    clock.advance(timedelta(minutes=1))
    reconciler.reconcile_owner(owner)  # completes the operation
    with factory.begin() as session:
        session.execute(
            update(ContactRow).where(ContactRow.id == contact).values(trashed_at=clock.current)
        )
    clock.advance(timedelta(minutes=1))
    reconciler.reconcile_owner(owner, full=True)
    assert _row(factory, entry).fingerprint != after.fingerprint


# --- Owner lock ---


@pytest.mark.integration
def test_the_owner_lock_is_public_and_released_cleanly() -> None:
    factory = database_factory()
    owner = _owner(factory)
    engine = _engine_of(factory)
    lock = OwnerLock(engine, owner)

    assert lock.acquire()
    assert not OwnerLock(engine, owner).acquire()
    lock.release()
    again = OwnerLock(engine, owner)
    assert again.acquire()
    again.release()


@pytest.mark.integration
def test_a_lock_that_cannot_be_confirmed_released_discards_its_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = database_factory()
    owner = _owner(factory)
    engine = _engine_of(factory)
    invalidated: list[bool] = []
    original = Connection.invalidate

    def spy(self: Connection, exception: BaseException | None = None) -> None:
        invalidated.append(True)
        original(self, exception)

    monkeypatch.setattr(Connection, "invalidate", spy)
    lock = OwnerLock(engine, owner)
    assert lock.acquire()
    connection = lock._connection  # pyright: ignore[reportPrivateUsage]
    assert connection is not None
    # Unlock behind the lock's back: the second unlock then answers False.
    connection.execute(select(func.pg_advisory_unlock(_lock_key(owner)))).close()

    lock.release()

    assert invalidated == [True]
    # The lock is free for the next worker.
    other = OwnerLock(engine, owner)
    assert other.acquire()
    other.release()
    assert invalidated == [True]  # a clean release does not discard anything


@pytest.mark.integration
def test_a_lock_whose_connection_fails_during_release_is_invalidated() -> None:
    factory = database_factory()
    owner = _owner(factory)
    engine = _engine_of(factory)
    events: list[str] = []

    class BrokenConnection:
        def execute(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("connection lost")

        def invalidate(self) -> None:
            events.append("invalidate")

        def close(self) -> None:
            events.append("close")

    lock = OwnerLock(engine, owner)
    lock._connection = BrokenConnection()  # type: ignore[assignment]  # pyright: ignore[reportPrivateUsage]

    lock.release()

    assert events == ["invalidate", "close"]
