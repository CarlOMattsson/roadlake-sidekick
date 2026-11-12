"""Shared test helpers moved out of `tests/memory/test_sync.py`."""

from collections.abc import Sequence
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from sidekick.memory.adapters.fake import FakeMemoryProvider
from sidekick.memory.application.sync import (
    MemoryReconciler,
    ReconcileResult,
    SyncPolicy,
)
from sidekick.memory.infrastructure.store import SqlAlchemyMemoryStore
from sidekick.memory.ports import (
    MemoryFailureCategory,
    MemoryProviderError,
    OperationResult,
    RetainItem,
)
from sidekick.shared.persistence.models import (
    MemorySourceRow,
)
from tests.db import database_factory
from tests.support.memory_queries import (
    NOW,
    _contact,  # pyright: ignore[reportPrivateUsage]
    _enable_all,  # pyright: ignore[reportPrivateUsage]
    _owner,  # pyright: ignore[reportPrivateUsage]
)

KEY = b"k" * 32


QUIET = timedelta(minutes=10)


#: One hour after the fixtures were written: past the quiet period, inside the live window.
LIVE_NOW = NOW + timedelta(hours=1)


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.current = now

    def now(self) -> datetime:
        return self.current

    def advance(self, delta: timedelta) -> None:
        self.current += delta


class ScriptedProvider(FakeMemoryProvider):
    """The fake provider plus switches that make it fail or hold operations on demand."""

    def __init__(self) -> None:
        super().__init__()
        self.retain_error: MemoryFailureCategory | None = None
        self.reject_ids: set[str] = set()
        self.operation_override: OperationResult | None = None
        self.status_error: MemoryFailureCategory | None = None
        self.delete_error: MemoryFailureCategory | None = None
        self.crash_after_retain = False
        self.retain_attempts: list[int] = []
        self.status_calls: list[str] = []

    def retain_batch(self, *, owner_id: UUID, items: Sequence[RetainItem]) -> str:
        self.retain_attempts.append(len(items))
        if self.retain_error is not None:
            raise MemoryProviderError(self.retain_error)
        if any(item.document_id in self.reject_ids for item in items):
            raise MemoryProviderError("rejected")
        operation_id = super().retain_batch(owner_id=owner_id, items=items)
        if self.crash_after_retain:
            raise RuntimeError("simulated crash after the provider accepted the batch")
        return operation_id

    def operation_status(self, *, owner_id: UUID, operation_id: str) -> OperationResult:
        self.status_calls.append(operation_id)
        if self.status_error is not None:
            raise MemoryProviderError(self.status_error)
        if self.operation_override is not None:
            return self.operation_override
        return super().operation_status(owner_id=owner_id, operation_id=operation_id)

    def delete_document(self, *, owner_id: UUID, document_id: str) -> None:
        if self.delete_error is not None:
            raise MemoryProviderError(self.delete_error)
        super().delete_document(owner_id=owner_id, document_id=document_id)


def _policy(**overrides: object) -> SyncPolicy:
    values: dict[str, object] = {"id_key": KEY, "quiet": QUIET}
    values.update(overrides)
    return SyncPolicy(**values)  # type: ignore[arg-type]


def _reconciler(
    factory: sessionmaker[Session],
    provider: FakeMemoryProvider,
    clock: FakeClock,
    **policy: object,
) -> MemoryReconciler:
    return MemoryReconciler(
        SqlAlchemyMemoryStore(factory), provider, _policy(**policy), clock=clock
    )


def _rows(factory: sessionmaker[Session], owner_id: UUID) -> list[MemorySourceRow]:
    with factory() as session:
        return list(
            session.scalars(
                select(MemorySourceRow)
                .where(MemorySourceRow.owner_id == owner_id)
                .order_by(MemorySourceRow.id)
            )
        )


def _row(factory: sessionmaker[Session], source_id: UUID) -> MemorySourceRow:
    with factory() as session:
        return session.scalars(
            select(MemorySourceRow).where(MemorySourceRow.source_id == source_id)
        ).one()


def _new_contact(factory: sessionmaker[Session], owner: UUID, name: str = "Ada") -> UUID:
    return _contact(factory, owner, name, context_note=f"{name} bor i Lund och är granne.")


def _drive_to_retained(
    reconciler: MemoryReconciler, owner: UUID, clock: FakeClock
) -> list[ReconcileResult]:
    """Two passes: the first sends, the second sees the operation finish."""

    first = reconciler.reconcile_owner(owner)
    clock.advance(timedelta(minutes=1))
    second = reconciler.reconcile_owner(owner)
    return [first, second]


def _setup(
    now: datetime = LIVE_NOW, **policy: object
) -> tuple[sessionmaker[Session], UUID, ScriptedProvider, FakeClock, MemoryReconciler]:
    factory = database_factory()
    owner = _owner(factory)
    _enable_all(factory, owner)
    provider = ScriptedProvider()
    clock = FakeClock(now)
    return factory, owner, provider, clock, _reconciler(factory, provider, clock, **policy)
