"""Wake pushes queued in the same transaction as the Task or Step change that caused them
(ADR-005; D-078, push through UnifiedPush).

When push is enabled (`SIDEKICK_PUSH_ENABLED`), `install_wake_hook` registers a `before_flush`
listener on the application's session factory. Whenever a flush writes a `TaskRow` or `StepRow`
(created, changed, completed, reopened, trashed, restored: every path, MCP or companion, goes
through the same rows), one `w` row per active subscription of the row's owner is written to
`push_outbox` in the same transaction, so a rolled-back change leaves no row and the worker sends
only after the commit. A burst of changes is one pending wake per subscription: a further change
only makes the pending row due again with its attempts counted afresh (also when a worker has it
in flight, so the change is never swallowed by a send that started before it).

Wakes are also coalesced in time: a wake queued less than `min_interval`
(`SIDEKICK_PUSH_WAKE_MIN_INTERVAL_SECONDS`) after the subscription's last successful push is due
only at `last_success_at + min_interval`, and so is a pending wake a further change touches. The
free ntfy.sh tier allows about 250 messages a day per sender IP; a burst of changes must not spend
it. Reminder pushes (`r`) are never delayed.

A companion call runs inside `acting_device`; the device that made the change gets no wake, it
already has the result. Nothing here reads or writes an endpoint or any content.
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from itertools import chain
from typing import Any, Final, Literal
from uuid import UUID
from weakref import WeakKeyDictionary

from sqlalchemy import case, event, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from sidekick.shared.persistence.models import (
    CompanionPairingRow,
    PushOutboxRow,
    PushSubscriptionRow,
    StepRow,
    TaskRow,
)
from sidekick.shared.types import new_uuid7, utc_now

WAKE: Final[Literal["w"]] = "w"
REMINDER: Final[Literal["r"]] = "r"
# One pending wake per subscription: the dedup key of every wake is the same.
WAKE_DEDUP_KEY = "w"

_ORIGIN_DEVICE: ContextVar[UUID | None] = ContextVar("sidekick_push_origin_device", default=None)


@contextmanager
def acting_device(device_id: UUID) -> Generator[None]:
    """Mark the writes made inside as made by this companion device: it gets no wake for them."""

    token = _ORIGIN_DEVICE.set(device_id)
    try:
        yield
    finally:
        _ORIGIN_DEVICE.reset(token)


def pending_wake_filter() -> Any:
    """The predicate of the partial unique index that allows one pending wake per subscription.

    Literal SQL on purpose: a bound parameter in an ON CONFLICT target stops Postgres matching the
    partial index once psycopg has turned the statement into a server-side prepared one (after
    `prepare_threshold` runs), and the failed insert then rolls back the caller's transaction. The
    kind is a fixed module constant, never input."""

    return text(f"kind = '{WAKE}' AND delivered_at IS NULL AND next_attempt_at IS NOT NULL")


def reminder_dedup_filter() -> Any:
    """The predicate of the partial unique index that dedups reminder pushes per subscription;
    literal SQL for the same reason as `pending_wake_filter`."""

    return text(f"kind = '{REMINDER}'")


def enqueue_wake(
    session: Session,
    owner_id: UUID,
    *,
    exclude_device_id: UUID | None = None,
    now: datetime | None = None,
    min_interval: timedelta = timedelta(0),
) -> int:
    """Queue (or make due again) a wake for each active subscription of the owner, in the
    caller's transaction. A subscription whose last successful push is less than `min_interval`
    old gets the wake due at the end of that interval instead of now. One query reads the
    subscriptions with their last success, one statement writes the rows. Returns how many
    subscriptions were addressed."""

    moment = now or utc_now()
    statement = (
        select(PushSubscriptionRow.id, PushSubscriptionRow.last_success_at)
        .join(CompanionPairingRow, CompanionPairingRow.id == PushSubscriptionRow.pairing_id)
        .where(PushSubscriptionRow.user_id == owner_id, PushSubscriptionRow.revoked_at.is_(None))
    )
    if exclude_device_id is not None:
        statement = statement.where(
            CompanionPairingRow.device_token_id.is_distinct_from(exclude_device_id)
        )
    subscriptions = session.execute(statement).all()
    if not subscriptions:
        return 0
    insertion = insert(PushOutboxRow).values(
        [
            {
                "id": new_uuid7(),
                "subscription_id": subscription_id,
                "kind": WAKE,
                "dedup_key": WAKE_DEDUP_KEY,
                "created_at": moment,
                "next_attempt_at": _wake_due(moment, last_success_at, min_interval),
                "attempts": 0,
            }
            for subscription_id, last_success_at in subscriptions
        ]
    )
    session.execute(
        insertion.on_conflict_do_update(
            index_elements=[PushOutboxRow.subscription_id],
            index_where=pending_wake_filter(),
            set_={
                # A wake nobody has claimed (attempts 0) is never moved later than it is: a
                # further change must not push it past what the interval allowed when it was
                # queued. A claimed row (a lease or a backoff, attempts > 0) is made due again at
                # once, so the change is not swallowed by the send in flight.
                "next_attempt_at": case(
                    (
                        PushOutboxRow.attempts == 0,
                        func.least(
                            PushOutboxRow.next_attempt_at, insertion.excluded.next_attempt_at
                        ),
                    ),
                    else_=insertion.excluded.next_attempt_at,
                ),
                "attempts": 0,
            },
        )
    )
    return len(subscriptions)


def _wake_due(
    moment: datetime, last_success_at: datetime | None, min_interval: timedelta
) -> datetime:
    """When a wake queued at `moment` may be sent: not before `min_interval` after the last
    successful push."""

    if last_success_at is None:
        return moment
    # In UTC: timedelta arithmetic on an aware datetime in a DST zone is wall-clock arithmetic and
    # is an hour off across a clock change.
    return max(moment, last_success_at.astimezone(UTC) + min_interval)


def enqueue_reminder_push(
    session: Session,
    owner_id: UUID,
    reminder_id: UUID,
    *,
    only_device_id: UUID | None = None,
    now: datetime | None = None,
) -> int:
    """Queue an `r` push for one reminder to each active subscription of the owner (or only the
    one of `only_device_id`), in the caller's transaction. The outbox carries the reminder's id as
    its dedup key and nothing else: the reminder's content stays in `push_reminders`. Returns how
    many pushes were queued."""

    moment = now or utc_now()
    statement = (
        select(PushSubscriptionRow.id)
        .join(CompanionPairingRow, CompanionPairingRow.id == PushSubscriptionRow.pairing_id)
        .where(PushSubscriptionRow.user_id == owner_id, PushSubscriptionRow.revoked_at.is_(None))
    )
    if only_device_id is not None:
        statement = statement.where(CompanionPairingRow.device_token_id == only_device_id)
    subscription_ids = list(session.scalars(statement))
    if not subscription_ids:
        return 0
    insertion = insert(PushOutboxRow).values(
        [
            {
                "id": new_uuid7(),
                "subscription_id": subscription_id,
                "kind": REMINDER,
                "dedup_key": str(reminder_id),
                "created_at": moment,
                "next_attempt_at": moment,
                "attempts": 0,
            }
            for subscription_id in subscription_ids
        ]
    )
    result = session.execute(
        insertion.on_conflict_do_nothing(
            index_elements=[PushOutboxRow.subscription_id, PushOutboxRow.dedup_key],
            index_where=reminder_dedup_filter(),
        ).returning(PushOutboxRow.id)
    )
    return len(result.all())


_HOOKS: WeakKeyDictionary[sessionmaker[Session], Callable[[Session, object, object], None]] = (
    WeakKeyDictionary()
)


def install_wake_hook(
    session_factory: sessionmaker[Session], *, min_interval: timedelta = timedelta(0)
) -> Callable[[], None]:
    """Queue a wake whenever a flush of this factory's sessions writes a Task or Step, no sooner
    than `min_interval` after the subscription's last successful push. Returns a function that
    removes the hook again. Called only when `SIDEKICK_PUSH_ENABLED` is set."""

    def on_before_flush(session: Session, _context: object, _instances: object) -> None:
        owners = {
            row.owner_id
            for row in chain(session.new, session.dirty)
            if isinstance(row, (TaskRow, StepRow))
            and (row in session.new or session.is_modified(row))
        }
        for owner_id in sorted(owners, key=str):
            enqueue_wake(
                session, owner_id, exclude_device_id=_ORIGIN_DEVICE.get(), min_interval=min_interval
            )

    listener = _HOOKS.get(session_factory)
    if listener is None or not event.contains(session_factory, "before_flush", listener):
        listener = on_before_flush
        _HOOKS[session_factory] = listener
        event.listen(session_factory, "before_flush", listener)
    installed = listener
    return lambda: event.remove(session_factory, "before_flush", installed)
