"""Bank lifecycle: the lost-volume check and the orphan-bank sweep.

Runs against the deterministic fake provider and the pool database. Nothing here touches the
network, reads `.env` or logs document text.
"""

import logging
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from sidekick.memory.adapters.fake import FakeMemoryProvider
from sidekick.memory.application import lifecycle
from sidekick.memory.application.sync_rules import PENDING, RETAINED
from sidekick.memory.domain import MemoryKind
from sidekick.memory.infrastructure.store import SqlAlchemyMemoryStore
from sidekick.memory.ports import MemoryProviderError, RetainItem
from sidekick.shared.persistence.models import MemorySourceRow
from sidekick.shared.types import new_uuid7
from tests.db import database_factory
from tests.support.memory_hindsight import (
    Script,
    _bank,  # pyright: ignore[reportPrivateUsage]
    _provider,  # pyright: ignore[reportPrivateUsage]
    _response,  # pyright: ignore[reportPrivateUsage]
)
from tests.support.memory_queries import (
    NOW,
    _memory_source,  # pyright: ignore[reportPrivateUsage]
    _owner,  # pyright: ignore[reportPrivateUsage]
)


class _Collect(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    @property
    def text(self) -> str:
        return "\n".join(
            f"{r.getMessage()} {sorted(r.__dict__.items(), key=lambda kv: kv[0])}"
            for r in self.records
        )

    def messages(self) -> list[str]:
        return [r.getMessage() for r in self.records]


@pytest.fixture
def logs() -> Iterator[_Collect]:
    handler = _Collect()
    logger = logging.getLogger("sidekick.memory.lifecycle")
    saved = (logger.level, logger.disabled, logger.propagate)
    logger.setLevel(logging.INFO)
    logger.disabled = False
    logger.addHandler(handler)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(saved[0])
        logger.disabled = saved[1]
        logger.propagate = saved[2]


@pytest.fixture
def factory() -> sessionmaker[Session]:
    return database_factory()


def _retained_rows(factory: sessionmaker[Session], owner: UUID, count: int = 2) -> list[UUID]:
    ids: list[UUID] = []
    for _ in range(count):
        memory_id = _memory_source(factory, owner, MemoryKind.CONTACT, new_uuid7())
        ids.append(memory_id)
        with factory.begin() as session:
            session.execute(
                update(MemorySourceRow)
                .where(MemorySourceRow.id == memory_id)
                .values(status=RETAINED, retained_at=NOW, attempts=2, operation_id="op-1")
            )
    return ids


def _rows(factory: sessionmaker[Session], owner: UUID) -> list[MemorySourceRow]:
    with factory() as session:
        rows = session.scalars(
            select(MemorySourceRow).where(MemorySourceRow.owner_id == owner)
        ).all()
        session.expunge_all()
        return list(rows)


def _retain(provider: FakeMemoryProvider, owner: UUID) -> None:
    provider.retain_batch(
        owner_id=owner,
        items=[
            RetainItem(
                document_id="v1_" + "d" * 64,
                content="Ada bor i Lund",
                timestamp="unset",
                entities=(),
                tags=(),
            )
        ],
    )


# --- Lost volume ---------------------------------------------------------------------------


def test_a_lost_volume_sets_retained_rows_back_to_pending(
    factory: sessionmaker[Session], logs: _Collect
) -> None:
    owner = _owner(factory)
    _retained_rows(factory, owner)
    provider = FakeMemoryProvider()  # an empty Hindsight: the bank does not exist

    result = lifecycle.verify_banks_after_start(SqlAlchemyMemoryStore(factory), provider)

    assert (result.owners_checked, result.owners_reset, result.rows_reset) == (1, 1, 2)
    assert result.complete
    rows = _rows(factory, owner)
    assert {row.status for row in rows} == {PENDING}
    assert all(row.retained_at == NOW for row in rows)  # evidence for a later delete is kept
    assert all(row.operation_id is None and row.attempts == 0 for row in rows)
    assert "memory_bank_lost" in logs.messages()
    assert "Ada" not in logs.text


def test_an_empty_bank_that_exists_counts_as_a_lost_volume(
    factory: sessionmaker[Session],
) -> None:
    owner = _owner(factory)
    _retained_rows(factory, owner, count=1)
    provider = FakeMemoryProvider()
    provider.banks.add(provider.bank_id_for(owner))

    result = lifecycle.verify_banks_after_start(SqlAlchemyMemoryStore(factory), provider)

    assert result.rows_reset == 1
    assert {row.status for row in _rows(factory, owner)} == {PENDING}


def test_a_bank_with_documents_is_left_alone(factory: sessionmaker[Session]) -> None:
    owner = _owner(factory)
    _retained_rows(factory, owner)
    provider = FakeMemoryProvider()
    _retain(provider, owner)

    result = lifecycle.verify_banks_after_start(SqlAlchemyMemoryStore(factory), provider)

    assert (result.owners_checked, result.owners_reset) == (1, 0)
    assert {row.status for row in _rows(factory, owner)} == {RETAINED}


def test_a_provider_failure_changes_nothing_and_asks_for_a_retry(
    factory: sessionmaker[Session], logs: _Collect
) -> None:
    owner = _owner(factory)
    _retained_rows(factory, owner)
    provider = FakeMemoryProvider(available=False)

    result = lifecycle.verify_banks_after_start(SqlAlchemyMemoryStore(factory), provider)

    assert not result.complete
    assert result.error_category == "unavailable"
    assert result.owners_reset == 0
    assert {row.status for row in _rows(factory, owner)} == {RETAINED}
    assert "memory_bank_check_unavailable" in logs.messages()

    provider.available = True  # Hindsight is back: the next try resets
    again = lifecycle.verify_banks_after_start(SqlAlchemyMemoryStore(factory), provider)
    assert again.complete and again.rows_reset == 2


def test_only_retained_rows_are_reset_and_excluded_rows_stay(
    factory: sessionmaker[Session],
) -> None:
    owner = _owner(factory)
    retained, excluded = _retained_rows(factory, owner)
    with factory.begin() as session:
        session.execute(
            update(MemorySourceRow).where(MemorySourceRow.id == excluded).values(excluded=True)
        )
    pending = _memory_source(factory, owner, MemoryKind.TASK, new_uuid7())

    result = lifecycle.verify_banks_after_start(
        SqlAlchemyMemoryStore(factory), FakeMemoryProvider()
    )

    assert result.rows_reset == 1
    by_id = {row.id: row for row in _rows(factory, owner)}
    assert by_id[retained].status == PENDING
    assert by_id[excluded].status == RETAINED
    assert by_id[pending].status == PENDING


def test_an_owner_without_retained_rows_is_not_asked_about(
    factory: sessionmaker[Session],
) -> None:
    owner = _owner(factory)
    _memory_source(factory, owner, MemoryKind.CONTACT, new_uuid7())

    class Strict(FakeMemoryProvider):
        def document_count(self, *, owner_id: UUID) -> int:
            raise AssertionError("no retained rows, so no network call")

    result = lifecycle.verify_banks_after_start(SqlAlchemyMemoryStore(factory), Strict())

    assert result.owners_checked == 0 and result.complete


class _NoCount(FakeMemoryProvider):
    """Fails the test if a document count is asked for (bank not listed, or listing failed)."""

    def document_count(self, *, owner_id: UUID) -> int:
        raise AssertionError("no document count is asked for this owner")


def test_a_bank_missing_from_the_listing_is_lost_without_a_count(
    factory: sessionmaker[Session], logs: _Collect
) -> None:
    owner = _owner(factory)
    _retained_rows(factory, owner)
    provider = _NoCount()
    provider.banks.add("v1_" + "e" * 64)  # Hindsight holds other banks, not this owner's

    result = lifecycle.verify_banks_after_start(SqlAlchemyMemoryStore(factory), provider)

    assert (result.owners_reset, result.rows_reset, result.complete) == (1, 2, True)
    assert {row.status for row in _rows(factory, owner)} == {PENDING}
    assert "memory_bank_lost" in logs.messages()


def test_a_404_on_the_documents_of_a_listed_bank_changes_nothing(
    factory: sessionmaker[Session], logs: _Collect
) -> None:
    """A wrong base path or proxy route answers 404 everywhere. The bank is listed, so no reset."""
    owner = _owner(factory)
    _retained_rows(factory, owner)
    script = Script(
        _response(200, {"banks": [{"bank_id": _bank(owner)}], "total": 1}), _response(404)
    )
    provider = _provider(script, max_retries=0)

    result = lifecycle.verify_banks_after_start(SqlAlchemyMemoryStore(factory), provider)

    assert not result.complete
    assert result.error_category == "unavailable"
    assert (result.owners_reset, result.rows_reset) == (0, 0)
    assert {row.status for row in _rows(factory, owner)} == {RETAINED}
    assert "memory_bank_check_unavailable" in logs.messages()


def test_a_failing_bank_listing_changes_nothing_and_asks_about_no_bank(
    factory: sessionmaker[Session],
) -> None:
    owner = _owner(factory)
    _retained_rows(factory, owner)

    class NoListing(_NoCount):
        def list_banks(self) -> tuple[str, ...]:
            raise MemoryProviderError("rejected")

    result = lifecycle.verify_banks_after_start(SqlAlchemyMemoryStore(factory), NoListing())

    assert not result.complete and result.error_category == "rejected"
    assert (result.owners_checked, result.owners_reset, result.rows_reset) == (0, 0, 0)
    assert {row.status for row in _rows(factory, owner)} == {RETAINED}


class _DocumentsArriveAfterTheFirstLook(FakeMemoryProvider):
    """A pass retains a document after the first look (listing 1) and before the locked recheck."""

    def __init__(self, owner: UUID) -> None:
        super().__init__()
        self._owner = owner
        self.listings = 0

    def list_banks(self) -> tuple[str, ...]:
        self.listings += 1
        if self.listings == 2:
            _retain(self, self._owner)
        return super().list_banks()


def test_documents_retained_after_the_first_look_stop_the_reset(
    factory: sessionmaker[Session], logs: _Collect
) -> None:
    owner = _owner(factory)
    _retained_rows(factory, owner)
    provider = _DocumentsArriveAfterTheFirstLook(owner)

    result = lifecycle.verify_banks_after_start(SqlAlchemyMemoryStore(factory), provider)

    assert provider.listings == 2  # the first look, then the recheck under the owner's lock
    assert result.complete and (result.owners_reset, result.rows_reset) == (0, 0)
    assert {row.status for row in _rows(factory, owner)} == {RETAINED}
    assert "memory_bank_lost" not in logs.messages()


def test_an_empty_bank_listing_resets_the_rows_and_logs_the_event(
    factory: sessionmaker[Session], logs: _Collect
) -> None:
    """A total volume loss (Hindsight lists no bank) is restored like any other loss. The empty
    listing is logged by name so it is visible. No count is asked: every bank is missing."""
    owner = _owner(factory)
    _retained_rows(factory, owner)

    result = lifecycle.verify_banks_after_start(SqlAlchemyMemoryStore(factory), _NoCount())

    assert result.complete
    assert (result.owners_reset, result.rows_reset) == (1, 2)
    assert {row.status for row in _rows(factory, owner)} == {PENDING}
    assert "memory_bank_list_empty" in logs.messages()
    assert "memory_bank_lost" in logs.messages()


class _EmptyAtTheRecheck(FakeMemoryProvider):
    """The listing under the owner's lock (the second listing) comes back empty."""

    def __init__(self) -> None:
        super().__init__()
        self.listings = 0

    def list_banks(self) -> tuple[str, ...]:
        self.listings += 1
        if self.listings == 2:
            return ()
        return super().list_banks()


def test_an_empty_listing_at_the_recheck_still_resets_the_loss(
    factory: sessionmaker[Session], logs: _Collect
) -> None:
    owner = _owner(factory)
    _retained_rows(factory, owner)
    provider = _EmptyAtTheRecheck()

    result = lifecycle.verify_banks_after_start(SqlAlchemyMemoryStore(factory), provider)

    assert provider.listings == 2
    assert result.complete
    assert (result.owners_reset, result.rows_reset, result.owners_locked) == (1, 2, 0)
    assert {row.status for row in _rows(factory, owner)} == {PENDING}
    assert "memory_bank_list_empty" in logs.messages()


# --- Orphan banks --------------------------------------------------------------------------


def _orphan(provider: FakeMemoryProvider) -> str:
    bank_id = provider.bank_id_for(uuid4())  # an owner that is not a user
    provider.banks.add(bank_id)
    return bank_id


def test_an_orphan_bank_is_deleted_and_the_living_and_foreign_banks_are_not(
    factory: sessionmaker[Session], logs: _Collect
) -> None:
    owner = _owner(factory)
    _retained_rows(factory, owner)
    provider = FakeMemoryProvider()
    _retain(provider, owner)
    living_bank = provider.bank_id_for(owner)
    orphan = _orphan(provider)
    foreign = {
        "char" + "lie-chat-bank",
        "v1_" + "A" * 64,
        "v1_" + "e" * 63,
        "_internal",
        "v2_" + "e" * 64,
    }
    provider.banks.update(foreign)

    result = lifecycle.sweep_orphan_banks(SqlAlchemyMemoryStore(factory), provider)

    assert (result.banks_ours, result.orphans_found, result.banks_deleted) == (2, 1, 1)
    assert result.refused is None and result.error_category is None
    assert provider.deleted_banks == [orphan]
    assert provider.banks == {living_bank} | foreign
    assert provider.document_count(owner_id=owner) == 1
    assert "memory_orphan_bank_deleted" in logs.messages()


def test_the_sweep_without_orphans_deletes_nothing(factory: sessionmaker[Session]) -> None:
    owner = _owner(factory)
    provider = FakeMemoryProvider()
    _retain(provider, owner)

    result = lifecycle.sweep_orphan_banks(SqlAlchemyMemoryStore(factory), provider)

    assert result.banks_deleted == 0 and provider.deleted_banks == []


def test_a_provider_failure_while_listing_deletes_nothing(factory: sessionmaker[Session]) -> None:
    _owner(factory)
    provider = FakeMemoryProvider()
    _orphan(provider)
    provider.available = False

    result = lifecycle.sweep_orphan_banks(SqlAlchemyMemoryStore(factory), provider)

    assert result.error_category == "unavailable"
    assert provider.deleted_banks == []


def test_a_failure_while_deleting_stops_the_sweep(factory: sessionmaker[Session]) -> None:
    _owner(factory)

    class Flaky(FakeMemoryProvider):
        def delete_bank(self, *, bank_id: str) -> None:
            raise MemoryProviderError("timeout")

    provider = Flaky()
    _orphan(provider)
    _orphan(provider)

    result = lifecycle.sweep_orphan_banks(SqlAlchemyMemoryStore(factory), provider)

    assert (result.banks_deleted, result.error_category) == (0, "timeout")


def test_the_sweep_refuses_when_no_living_owners_bank_is_listed(
    factory: sessionmaker[Session], logs: _Collect
) -> None:
    """A rotated derivation key or another instance makes every bank look like an orphan."""

    owner = _owner(factory)
    _retained_rows(factory, owner)
    provider = FakeMemoryProvider()  # holds no bank for the living owner
    _orphan(provider)
    _orphan(provider)

    result = lifecycle.sweep_orphan_banks(SqlAlchemyMemoryStore(factory), provider)

    assert result.refused == "no_living_bank_listed"
    assert result.banks_deleted == 0 and provider.deleted_banks == []
    assert "memory_orphan_sweep_refused" in logs.messages()


def test_the_sweep_refuses_a_flood_of_orphans(factory: sessionmaker[Session]) -> None:
    owner = _owner(factory)
    provider = FakeMemoryProvider()
    _retain(provider, owner)
    for _ in range(4):
        _orphan(provider)

    result = lifecycle.sweep_orphan_banks(SqlAlchemyMemoryStore(factory), provider, max_deletes=3)

    assert (result.refused, result.orphans_found, result.banks_deleted) == (
        "too_many_orphans",
        4,
        0,
    )
    assert provider.deleted_banks == []


def test_a_living_user_who_never_enabled_memory_does_not_block_an_orphan_clean_up(
    factory: sessionmaker[Session],
) -> None:
    _owner(factory)  # no memory rows, no bank
    provider = FakeMemoryProvider()
    orphan = _orphan(provider)

    result = lifecycle.sweep_orphan_banks(SqlAlchemyMemoryStore(factory), provider)

    assert result.banks_deleted == 1 and provider.deleted_banks == [orphan]


def test_deleting_a_bank_outside_sidekicks_format_is_refused_by_the_provider() -> None:
    provider = FakeMemoryProvider()

    for bad in ("char" + "lie-chat-bank", "v1_short", "v1_" + "G" * 64, ""):
        with pytest.raises(ValueError):
            provider.delete_bank(bank_id=bad)
    assert provider.deleted_banks == []
