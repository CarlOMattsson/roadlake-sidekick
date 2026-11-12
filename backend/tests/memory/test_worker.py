"""Tests for the memory worker CLI: argument rules and the maintenance commands.

The database tests call `main()` against the deterministic fake provider, with settings built
explicitly and the session factory and provider injected through monkeypatch. Nothing here reads
`.env`, touches the network or logs document text.
"""

import asyncio
import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

import sidekick.memory.worker as worker
from sidekick.memory.adapters.fake import FakeMemoryProvider
from sidekick.memory.application.lifecycle import BankCheckResult, SweepResult
from sidekick.memory.application.sync import (
    PARKED,
    PENDING,
    REMOVED_CATEGORY,
    RETAINED,
    SUBMITTED,
    MemoryReconciler,
    SyncPolicy,
)
from sidekick.memory.domain import MemoryKind
from sidekick.memory.infrastructure.store import SqlAlchemyMemoryStore
from sidekick.shared.config import Settings
from sidekick.shared.persistence.models import MemorySettingsRow, MemorySourceRow
from tests.db import database_factory
from tests.support.memory_queries import (
    NOW,
    _contact,  # pyright: ignore[reportPrivateUsage]
    _enable_all,  # pyright: ignore[reportPrivateUsage]
    _memory_source,  # pyright: ignore[reportPrivateUsage]
    _owner,  # pyright: ignore[reportPrivateUsage]
)

KEY = "w" * 32
SECRET_NOTE = "bor i Lund och är granne"


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "memory_enabled": True,
        "memory_id_derivation_key": KEY,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


@pytest.fixture
def wired(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[sessionmaker[Session], UUID, FakeMemoryProvider]:
    """One owner with every domain on, the fake provider, and the worker's wiring replaced."""

    factory = database_factory()
    owner = _owner(factory)
    _enable_all(factory, owner)
    provider = FakeMemoryProvider()
    settings = _settings()
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    monkeypatch.setattr(worker, "create_session_factory", lambda _url, **_kw: factory)
    monkeypatch.setattr(worker, "build_provider", lambda _settings: provider)
    return factory, owner, provider


class _Collect(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    @property
    def text(self) -> str:
        return "\n".join(r.getMessage() for r in self.records)


@pytest.fixture
def caplog() -> Iterator[_Collect]:
    """Capture the memory loggers directly, so another test's logging setup (propagation, level,
    `disabled`) cannot hide records. Shadows pytest's `caplog` on purpose."""

    handler = _Collect()
    saved: list[tuple[logging.Logger, int, bool, bool]] = []
    for name in ("sidekick.memory.worker", "sidekick.memory.sync"):
        logger = logging.getLogger(name)
        saved.append((logger, logger.level, logger.disabled, logger.propagate))
        logger.setLevel(logging.INFO)
        logger.disabled = False
        logger.addHandler(handler)
    try:
        yield handler
    finally:
        for logger, level, disabled, propagate in saved:
            logger.removeHandler(handler)
            logger.setLevel(level)
            logger.disabled = disabled
            logger.propagate = propagate


def _two_contacts(factory: sessionmaker[Session], owner: UUID) -> None:
    for name in ("Ada", "Bo"):
        _contact(factory, owner, name, context_note=f"{name} {SECRET_NOTE}.")


def _statuses(factory: sessionmaker[Session], owner: UUID) -> list[str]:
    with factory() as session:
        return sorted(
            session.scalars(
                select(MemorySourceRow.status).where(MemorySourceRow.owner_id == owner)
            ).all()
        )


# --- Argument rules (no database) ---


def test_no_flags_means_the_loop_with_no_action() -> None:
    args = worker.build_parser().parse_args([])

    assert args.once is False
    assert args.rebuild_owner is None
    assert args.wipe is False
    assert args.forget_owner is None
    assert args.confirm is False


def test_owner_ids_are_parsed_as_uuids_and_bad_ones_are_refused(
    capsys: pytest.CaptureFixture[str],
) -> None:
    owner = uuid4()

    args = worker.build_parser().parse_args(["--rebuild-owner", str(owner)])

    assert args.rebuild_owner == owner
    with pytest.raises(SystemExit) as refused:
        worker.build_parser().parse_args(["--forget-owner", "not-a-uuid", "--confirm"])
    assert refused.value.code == 2
    assert "invalid UUID" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        ["--wipe"],
        ["--forget-owner", str(uuid4())],
    ],
)
def test_wipe_and_forget_owner_are_refused_without_confirm(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as refused:
        worker.main(argv)

    assert refused.value.code == 2
    assert "--confirm" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        ["--wipe", "--forget-owner", str(uuid4()), "--confirm"],
        ["--wipe", "--rebuild-owner", str(uuid4())],
        ["--wipe", "--confirm", "--once"],
        ["--confirm"],
        ["--once", "--forget-owner", str(uuid4()), "--confirm"],
    ],
)
def test_conflicting_action_flags_are_refused(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as refused:
        worker.main(argv)

    assert refused.value.code == 2


# --- Database tests ---


def test_once_runs_one_pass_and_the_next_pass_sees_the_operation_finish(
    wired: tuple[sessionmaker[Session], UUID, FakeMemoryProvider],
    caplog: _Collect,
) -> None:
    factory, owner, provider = wired
    _two_contacts(factory, owner)

    assert worker.main(["--once"]) == 0
    # The first pass polls nothing and sends both documents in one batch.
    assert _statuses(factory, owner) == [SUBMITTED, SUBMITTED]
    assert [len(call.items) for call in provider.retain_calls] == [2]

    assert worker.main(["--once"]) == 0
    assert _statuses(factory, owner) == [RETAINED, RETAINED]
    assert len(provider.retain_calls) == 1
    # Logs carry ids and counts only, never the record text.
    assert SECRET_NOTE not in caplog.text


def test_disabled_worker_logs_one_line_and_builds_no_provider(
    wired: tuple[sessionmaker[Session], UUID, FakeMemoryProvider],
    monkeypatch: pytest.MonkeyPatch,
    caplog: _Collect,
) -> None:
    factory, owner, _provider = wired
    _two_contacts(factory, owner)
    monkeypatch.setattr(worker, "get_settings", lambda: _settings(memory_enabled=False))

    def no_provider(_settings: Settings) -> FakeMemoryProvider:
        raise AssertionError("a disabled worker must not build a provider")

    monkeypatch.setattr(worker, "build_provider", no_provider)

    assert worker.main(["--once"]) == 0
    assert [r.getMessage() for r in caplog.records].count(
        "memory worker disabled; no reconcile passes"
    ) == 1
    assert _statuses(factory, owner) == []


def test_rebuild_owner_marks_rows_and_the_next_pass_resends_them(
    wired: tuple[sessionmaker[Session], UUID, FakeMemoryProvider],
) -> None:
    factory, owner, provider = wired
    _two_contacts(factory, owner)
    assert worker.main(["--once"]) == 0
    assert worker.main(["--once"]) == 0
    assert _statuses(factory, owner) == [RETAINED, RETAINED]

    # Without --once the command only marks the rows and returns; the running loop resends them.
    assert worker.main(["--rebuild-owner", str(owner)]) == 0
    assert _statuses(factory, owner) == [PENDING, PENDING]
    assert len(provider.retain_calls) == 1

    assert worker.main(["--rebuild-owner", str(owner), "--once"]) == 0
    assert [len(call.items) for call in provider.retain_calls] == [2, 2]
    assert _statuses(factory, owner) == [SUBMITTED, SUBMITTED]


def test_wipe_deletes_documents_and_rows_but_keeps_exclusion_markers(
    wired: tuple[sessionmaker[Session], UUID, FakeMemoryProvider],
) -> None:
    factory, owner, provider = wired
    _two_contacts(factory, owner)
    assert worker.main(["--once"]) == 0
    assert worker.main(["--once"]) == 0
    excluded_id = _contact(factory, owner, "Cy", context_note=f"Cy {SECRET_NOTE}.")
    marker_memory_id = _memory_source(
        factory, owner, MemoryKind.CONTACT, excluded_id, excluded=True
    )

    assert worker.main(["--wipe", "--and-pause", "--confirm"]) == 0

    with factory() as session:
        rows = list(
            session.scalars(select(MemorySourceRow).where(MemorySourceRow.owner_id == owner))
        )
    # Two sent rows are gone; the excluded record keeps its marker so it is not sent again.
    assert [(row.id, row.status, row.failure_category, row.excluded) for row in rows] == [
        (marker_memory_id, PARKED, REMOVED_CATEGORY, True)
    ]
    # Two sent documents and the excluded record's document (`_memory_source` names it doc-<id>).
    assert len(provider.delete_calls) == 3
    assert f"doc-{marker_memory_id}" in {doc for _owner, doc in provider.delete_calls}


def test_forget_owner_touches_only_that_owner(
    wired: tuple[sessionmaker[Session], UUID, FakeMemoryProvider],
) -> None:
    factory, owner, provider = wired
    other = _owner(factory)
    _enable_all(factory, other)
    _two_contacts(factory, owner)
    _two_contacts(factory, other)
    assert worker.main(["--once"]) == 0
    assert worker.main(["--once"]) == 0

    assert worker.main(["--forget-owner", str(owner), "--confirm"]) == 0

    assert _statuses(factory, owner) == []
    assert _statuses(factory, other) == [RETAINED, RETAINED]
    assert {current for current, _doc in provider.delete_calls} == {owner}


# --- Forget, wipe, rebuild and the nightly pass ---


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.current = now

    def now(self) -> datetime:
        return self.current


def _settings_row(factory: sessionmaker[Session], owner: UUID) -> MemorySettingsRow | None:
    with factory() as session:
        return session.get(MemorySettingsRow, owner)


def _unconfirmed_row(
    factory: sessionmaker[Session], owner: UUID, *, status: str = "failed"
) -> tuple[UUID, str]:
    """A row that was attempted but never confirmed: the bank may still receive its retain."""

    source = _contact(factory, owner, "Dee", context_note=f"Dee {SECRET_NOTE}.")
    memory_id = _memory_source(factory, owner, MemoryKind.CONTACT, source)
    with factory.begin() as session:
        session.execute(
            update(MemorySourceRow)
            .where(MemorySourceRow.id == memory_id)
            .values(
                status=status,
                attempts=2,
                retained_at=NOW,
                failure_category="timeout",
                next_attempt_at=NOW,
                operation_id="op-x" if status == "submitted" else None,
            )
        )
    return memory_id, f"doc-{memory_id}"


class _SpyProvider(FakeMemoryProvider):
    """Records the owner's settings at the moment of each delete."""

    def __init__(self, factory: sessionmaker[Session], owner: UUID) -> None:
        super().__init__()
        self._factory = factory
        self._owner = owner
        self.settings_at_delete: list[tuple[bool, bool, bool, bool, bool]] = []

    def delete_document(self, *, owner_id: UUID, document_id: str) -> None:
        with self._factory() as session:
            row = session.get(MemorySettingsRow, self._owner)
            assert row is not None
            self.settings_at_delete.append(
                (row.paused, row.journal, row.contacts, row.projects, row.tasks)
            )
        super().delete_document(owner_id=owner_id, document_id=document_id)


def test_forget_owner_pauses_and_switches_every_domain_off_before_deleting(
    wired: tuple[sessionmaker[Session], UUID, FakeMemoryProvider],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, owner, _provider = wired
    spy = _SpyProvider(factory, owner)
    monkeypatch.setattr(worker, "build_provider", lambda _settings: spy)
    _two_contacts(factory, owner)
    assert worker.main(["--once"]) == 0
    assert worker.main(["--once"]) == 0
    before = _settings_row(factory, owner)
    assert before is not None
    assert (before.paused, before.journal, before.contacts) == (False, True, True)

    assert worker.main(["--forget-owner", str(owner), "--confirm"]) == 0

    after = _settings_row(factory, owner)
    assert after is not None
    assert (after.paused, after.journal, after.contacts, after.projects, after.tasks) == (
        True,
        False,
        False,
        False,
        False,
    )
    assert after.version == before.version + 1
    assert len(spy.settings_at_delete) == 2
    assert set(spy.settings_at_delete) == {(True, False, False, False, False)}
    assert _statuses(factory, owner) == []


def test_forget_owner_creates_the_settings_row_when_there_is_none(
    wired: tuple[sessionmaker[Session], UUID, FakeMemoryProvider],
) -> None:
    factory, _owner_with_settings, _provider = wired
    bare = _owner(factory)  # no memory_settings row
    source = _contact(factory, bare, "Eva", context_note=f"Eva {SECRET_NOTE}.")
    _memory_source(factory, bare, MemoryKind.CONTACT, source)
    assert _settings_row(factory, bare) is None

    assert worker.main(["--forget-owner", str(bare), "--confirm"]) == 0

    row = _settings_row(factory, bare)
    assert row is not None
    assert (row.paused, row.journal, row.contacts, row.projects, row.tasks) == (
        True,
        False,
        False,
        False,
        False,
    )
    assert _statuses(factory, bare) == []


def test_wipe_is_refused_while_ingest_is_enabled_unless_it_also_pauses(
    wired: tuple[sessionmaker[Session], UUID, FakeMemoryProvider],
    caplog: _Collect,
) -> None:
    factory, owner, provider = wired
    _two_contacts(factory, owner)
    assert worker.main(["--once"]) == 0
    assert worker.main(["--once"]) == 0

    assert worker.main(["--wipe", "--confirm"]) == 1

    assert provider.delete_calls == []
    assert _statuses(factory, owner) == [RETAINED, RETAINED]
    paused = _settings_row(factory, owner)
    assert paused is not None and paused.paused is False
    assert "memory wipe refused" in caplog.text

    assert worker.main(["--wipe", "--and-pause", "--confirm"]) == 0

    assert len(provider.delete_calls) == 2
    assert _statuses(factory, owner) == []
    after = _settings_row(factory, owner)
    assert after is not None
    # Only the pause is set: the owner's domain choices are kept, unlike a forget.
    assert (after.paused, after.journal, after.contacts) == (True, True, True)


def test_wipe_and_pause_pauses_every_owner_including_those_without_rows(
    wired: tuple[sessionmaker[Session], UUID, FakeMemoryProvider],
) -> None:
    factory, owner, _provider = wired
    other = _owner(factory)
    _enable_all(factory, other)  # settings only, no memory rows
    _two_contacts(factory, owner)
    assert worker.main(["--once"]) == 0
    assert worker.main(["--once"]) == 0

    assert worker.main(["--wipe", "--and-pause", "--confirm"]) == 0

    for who in (owner, other):
        row = _settings_row(factory, who)
        assert row is not None and row.paused is True


def test_wipe_with_ingest_disabled_needs_no_pause_flag(
    wired: tuple[sessionmaker[Session], UUID, FakeMemoryProvider],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, owner, provider = wired
    _two_contacts(factory, owner)
    assert worker.main(["--once"]) == 0
    assert worker.main(["--once"]) == 0
    monkeypatch.setattr(worker, "get_settings", lambda: _settings(memory_ingest_enabled=False))

    assert worker.main(["--wipe", "--confirm"]) == 0

    assert len(provider.delete_calls) == 2
    row = _settings_row(factory, owner)
    assert row is not None and row.paused is False


@pytest.mark.parametrize(
    "argv", [["--and-pause"], ["--forget-owner", str(uuid4()), "--and-pause", "--confirm"]]
)
def test_and_pause_only_applies_to_wipe(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as refused:
        worker.main(argv)

    assert refused.value.code == 2


def test_wipe_keeps_a_marker_for_an_unconfirmed_row_and_the_worker_finishes_the_delete(
    wired: tuple[sessionmaker[Session], UUID, FakeMemoryProvider],
) -> None:
    factory, owner, provider = wired
    memory_id, doc_key = _unconfirmed_row(factory, owner)
    retained = _contact(factory, owner, "Fay", context_note=f"Fay {SECRET_NOTE}.")
    settled = _memory_source(factory, owner, MemoryKind.CONTACT, retained)
    with factory.begin() as session:
        session.execute(
            update(MemorySourceRow)
            .where(MemorySourceRow.id == settled)
            .values(status="retained", retained_at=NOW)
        )

    assert worker.main(["--forget-owner", str(owner), "--confirm"]) == 0

    with factory() as session:
        rows = list(
            session.scalars(select(MemorySourceRow).where(MemorySourceRow.owner_id == owner))
        )
    # The settled row is gone; the unconfirmed one waits for its second delete.
    assert [(r.id, r.status, r.failure_category) for r in rows] == [
        (memory_id, PARKED, REMOVED_CATEGORY)
    ]
    assert rows[0].next_attempt_at is not None
    assert rows[0].next_attempt_at > NOW

    # The running worker's pass (owner paused, domains off) makes the second delete when due.
    reconciler = MemoryReconciler(
        SqlAlchemyMemoryStore(factory),
        provider,
        SyncPolicy.from_settings(_settings()),
        clock=_Clock(rows[0].next_attempt_at + timedelta(minutes=1)),
    )
    reconciler.reconcile_owner(owner)
    assert _statuses(factory, owner) == []
    assert [d for _o, d in provider.delete_calls].count(doc_key) == 2


def test_wipe_defers_a_marker_whose_second_delete_is_not_due(
    wired: tuple[sessionmaker[Session], UUID, FakeMemoryProvider],
) -> None:
    factory, owner, provider = wired
    _unconfirmed_row(factory, owner)
    clock = _Clock(datetime.now(UTC))
    first = worker.wipe_owner(factory, provider, owner, clock=clock)
    assert (first.documents_deleted, first.markers_kept, first.second_delete_pending) == (1, 1, 1)

    again = worker.wipe_owner(factory, provider, owner, clock=clock)

    assert (again.documents_deleted, again.deferred) == (0, 1)
    clock.current += timedelta(hours=3)
    final = worker.wipe_owner(factory, provider, owner, clock=clock)
    assert (final.documents_deleted, final.rows_removed, final.deferred) == (1, 1, 0)
    assert _statuses(factory, owner) == []


def test_wipe_defers_a_submitted_row_and_deletes_nothing_for_it(
    wired: tuple[sessionmaker[Session], UUID, FakeMemoryProvider],
) -> None:
    factory, owner, provider = wired
    _unconfirmed_row(factory, owner, status="submitted")

    result = worker.wipe_owner(factory, provider, owner)

    assert (result.deferred, result.documents_deleted) == (1, 0)
    assert provider.delete_calls == []
    assert _statuses(factory, owner) == [SUBMITTED]


def test_rebuild_keeps_the_operation_id_of_submitted_rows_and_the_evidence_of_failed_ones(
    wired: tuple[sessionmaker[Session], UUID, FakeMemoryProvider],
) -> None:
    factory, owner, provider = wired
    submitted_id, _ = _unconfirmed_row(factory, owner, status="submitted")
    failed_id, failed_key = _unconfirmed_row(factory, owner)
    marker_source = _contact(factory, owner, "Gus", context_note=f"Gus {SECRET_NOTE}.")
    marker_id = _memory_source(factory, owner, MemoryKind.CONTACT, marker_source)
    with factory.begin() as session:
        session.execute(
            update(MemorySourceRow)
            .where(MemorySourceRow.id == submitted_id)
            .values(operation_id="op-keep", failure_category=None)
        )
        session.execute(
            update(MemorySourceRow)
            .where(MemorySourceRow.id == failed_id)
            .values(retained_at=None)  # an older row without the evidence column set
        )
        session.execute(
            update(MemorySourceRow)
            .where(MemorySourceRow.id == marker_id)
            .values(
                status=PARKED,
                failure_category=REMOVED_CATEGORY,
                next_attempt_at=NOW + timedelta(hours=2),
            )
        )

    assert worker.main(["--rebuild-owner", str(owner)]) == 0

    with factory() as session:
        rows = {r.id: r for r in session.scalars(select(MemorySourceRow))}
    submitted = rows[submitted_id]
    assert (submitted.status, submitted.operation_id) == (SUBMITTED, "op-keep")
    assert (rows[marker_id].status, rows[marker_id].next_attempt_at) == (
        PARKED,
        NOW + timedelta(hours=2),
    )
    failed = rows[failed_id]
    assert (failed.status, failed.attempts, failed.failure_category) == (PENDING, 0, None)
    assert failed.retained_at is not None  # the bank may hold it although attempts were reset

    # A record deleted after a rebuild is still deleted twice.
    first = worker.wipe_owner(factory, provider, owner)
    assert first.markers_kept >= 1
    assert (owner, failed_key) in provider.delete_calls
    kept = {r.id: r for r in _rows_of(factory, owner)}
    assert kept[failed_id].status == PARKED
    assert kept[failed_id].next_attempt_at is not None


def _rows_of(factory: sessionmaker[Session], owner: UUID) -> list[MemorySourceRow]:
    with factory() as session:
        return list(
            session.scalars(select(MemorySourceRow).where(MemorySourceRow.owner_id == owner))
        )


# --- The nightly full pass ---


def test_full_pass_schedule_runs_at_startup_and_after_three_utc_each_day() -> None:
    schedule = worker.FullPassSchedule()
    start = datetime(2026, 10, 28, 10, 0, tzinfo=UTC)

    assert schedule.due(start)
    schedule.mark_done(start)
    assert not schedule.due(start + timedelta(hours=1))
    assert not schedule.due(datetime(2026, 10, 29, 2, 59, tzinfo=UTC))
    assert schedule.due(datetime(2026, 10, 29, 3, 0, tzinfo=UTC))
    schedule.mark_done(datetime(2026, 10, 29, 3, 0, tzinfo=UTC))
    assert not schedule.due(datetime(2026, 10, 29, 23, 0, tzinfo=UTC))
    assert schedule.due(datetime(2026, 10, 30, 3, 1, tzinfo=UTC))


def test_a_start_before_three_utc_runs_a_second_full_pass_the_same_morning() -> None:
    schedule = worker.FullPassSchedule()
    start = datetime(2026, 10, 28, 1, 0, tzinfo=UTC)
    schedule.mark_done(start)

    assert not schedule.due(datetime(2026, 10, 28, 2, 59, tzinfo=UTC))
    assert schedule.due(datetime(2026, 10, 28, 3, 0, tzinfo=UTC))


class _Stop(Exception):
    pass


def test_the_loop_runs_a_full_pass_at_startup_and_once_after_three_utc(
    wired: tuple[sessionmaker[Session], UUID, FakeMemoryProvider],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _Clock(datetime(2026, 10, 28, 10, 0, tzinfo=UTC))
    flags: list[bool] = []

    def fake_run_pass(**kwargs: Any) -> list[object]:
        flags.append(kwargs["full"])
        return []

    async def fake_sleep(_seconds: float) -> None:
        if len(flags) >= 5:
            raise _Stop
        clock.current += timedelta(hours=6)

    monkeypatch.setattr(worker, "run_pass", fake_run_pass)
    monkeypatch.setattr(worker.asyncio, "sleep", fake_sleep)

    with pytest.raises(_Stop):
        asyncio.run(worker.run_worker(clock=clock))

    # 10:00 (startup), 16:00, 22:00, 04:00 the next day, 10:00.
    assert flags == [True, False, False, True, False]


def test_a_failed_full_pass_is_tried_again_on_the_next_loop(
    wired: tuple[sessionmaker[Session], UUID, FakeMemoryProvider],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _Clock(datetime(2026, 10, 28, 10, 0, tzinfo=UTC))
    flags: list[bool] = []

    def fake_run_pass(**kwargs: Any) -> list[object]:
        flags.append(kwargs["full"])
        if len(flags) == 1:
            raise RuntimeError("provider exploded with SECRET")
        return []

    async def fake_sleep(_seconds: float) -> None:
        if len(flags) >= 3:
            raise _Stop

    monkeypatch.setattr(worker, "run_pass", fake_run_pass)
    monkeypatch.setattr(worker.asyncio, "sleep", fake_sleep)

    with pytest.raises(_Stop):
        asyncio.run(worker.run_worker(clock=clock))

    assert flags == [True, True, False]


def test_main_keeps_the_http_client_loggers_at_warning(
    wired: tuple[sessionmaker[Session], UUID, FakeMemoryProvider],
) -> None:
    saved = {name: logging.getLogger(name).level for name in ("httpx", "httpcore")}
    try:
        for name in saved:
            logging.getLogger(name).setLevel(logging.DEBUG)

        assert worker.main(["--once"]) == 0

        assert logging.getLogger("httpx").level == logging.WARNING
        assert logging.getLogger("httpcore").level == logging.WARNING
    finally:
        for name, level in saved.items():
            logging.getLogger(name).setLevel(level)


def test_the_bank_check_runs_at_start_and_is_repeated_until_hindsight_answers(
    wired: tuple[sessionmaker[Session], UUID, FakeMemoryProvider],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _Clock(datetime(2026, 10, 28, 10, 0, tzinfo=UTC))
    checks: list[bool] = []
    passes: list[bool] = []

    def fake_check(_factory: object, _provider: object) -> BankCheckResult:
        checks.append(True)
        return BankCheckResult(complete=len(checks) >= 3)

    def fake_run_pass(**kwargs: Any) -> list[object]:
        passes.append(kwargs["full"])
        return []

    async def fake_sleep(_seconds: float) -> None:
        if len(passes) >= 5:
            raise _Stop

    monkeypatch.setattr(worker, "verify_banks_after_start", fake_check)
    monkeypatch.setattr(worker, "run_pass", fake_run_pass)
    monkeypatch.setattr(worker.asyncio, "sleep", fake_sleep)

    with pytest.raises(_Stop):
        asyncio.run(worker.run_worker(clock=clock))

    assert len(checks) == 3  # two incomplete tries, one complete, then never again


def test_the_orphan_sweep_runs_only_after_a_full_pass(
    wired: tuple[sessionmaker[Session], UUID, FakeMemoryProvider],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _Clock(datetime(2026, 10, 28, 10, 0, tzinfo=UTC))
    passes: list[bool] = []
    sweeps: list[int] = []

    def fake_run_pass(**kwargs: Any) -> list[object]:
        passes.append(kwargs["full"])
        return []

    def fake_sweep(_factory: object, _provider: object) -> SweepResult:
        sweeps.append(len(passes))
        return SweepResult()

    async def fake_sleep(_seconds: float) -> None:
        if len(passes) >= 5:
            raise _Stop
        clock.current += timedelta(hours=6)

    monkeypatch.setattr(worker, "run_pass", fake_run_pass)
    monkeypatch.setattr(worker, "sweep_orphan_banks", fake_sweep)
    monkeypatch.setattr(worker.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(worker, "get_settings", lambda: _settings(memory_orphan_sweep_enabled=True))

    with pytest.raises(_Stop):
        asyncio.run(worker.run_worker(clock=clock))

    assert passes == [True, False, False, True, False]
    assert sweeps == [1, 4]  # after the startup pass and after the pass following 03:00


# --- Orphan-bank sweep switch (off by default) ---------------------------------------------------


def _add_orphan(provider: FakeMemoryProvider) -> str:
    bank_id = provider.bank_id_for(uuid4())  # an owner that is not a user
    provider.banks.add(bank_id)
    return bank_id


def _run_real_loop(monkeypatch: pytest.MonkeyPatch, settings: Settings, *, stop_after: int) -> None:
    """Run the real worker loop with the real sweep, the fake provider and 6-hour steps.

    Four passes give two full passes (the first, and the one after 03:00 UTC the next day).
    """

    clock = _Clock(datetime(2026, 10, 28, 10, 0, tzinfo=UTC))
    passes: list[bool] = []
    monkeypatch.setattr(worker, "get_settings", lambda: settings)

    def fake_run_pass(**kwargs: Any) -> list[object]:
        passes.append(kwargs["full"])
        return []

    async def fake_sleep(_seconds: float) -> None:
        if len(passes) >= stop_after:
            raise _Stop
        clock.current += timedelta(hours=6)

    monkeypatch.setattr(worker, "run_pass", fake_run_pass)
    monkeypatch.setattr(worker.asyncio, "sleep", fake_sleep)
    with pytest.raises(_Stop):
        asyncio.run(worker.run_worker(clock=clock))
    assert passes == [True, False, False, True]


def test_the_orphan_sweep_is_off_by_default_and_deletes_nothing(
    wired: tuple[sessionmaker[Session], UUID, FakeMemoryProvider],
    monkeypatch: pytest.MonkeyPatch,
    caplog: _Collect,
) -> None:
    _factory, _owner_id, provider = wired
    orphan = _add_orphan(provider)

    _run_real_loop(monkeypatch, _settings(), stop_after=4)

    assert provider.deleted_banks == []
    assert orphan in provider.banks
    messages = [record.getMessage() for record in caplog.records]
    assert messages.count("memory_orphan_sweep_disabled") == 2  # once per full pass, not per pass


def test_the_orphan_sweep_deletes_orphans_when_switched_on(
    wired: tuple[sessionmaker[Session], UUID, FakeMemoryProvider],
    monkeypatch: pytest.MonkeyPatch,
    caplog: _Collect,
) -> None:
    _factory, _owner_id, provider = wired
    orphan = _add_orphan(provider)
    settings = _settings(memory_orphan_sweep_enabled=True)

    _run_real_loop(monkeypatch, settings, stop_after=4)

    assert provider.deleted_banks == [orphan]
    messages = [record.getMessage() for record in caplog.records]
    assert "memory_orphan_sweep_disabled" not in messages
