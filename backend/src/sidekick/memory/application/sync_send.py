"""Send phase of the reconcile pass: reserve the daily budget, retain one batch, record the outcome.

Before a batch is sent, one transaction counts it against today's caps and bumps `attempts` and
`next_attempt_at` of its rows. A crash after the provider accepted the batch but before `submitted`
is committed leaves those rows `pending` with a future retry time. The retry sends the same
`doc_key` with replace semantics, so the bank never holds a duplicate. A failed send that certainly
delivered nothing is refunded.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date
from uuid import UUID

from sidekick.memory.application.sync_rules import (
    FAILED,
    NOTHING_SENT,
    OPERATION_DEADLINE,
    PARKED,
    PENDING,
    PROVIDER_WIDE,
    SETTINGS_FLAG,
    SendCandidate,
    is_due,
    record_failure,
    retry_backoff,
    select_batch,
)
from sidekick.memory.application.sync_state import (
    BudgetRefused,
    PassDeps,
    PassState,
    SendCollector,
)
from sidekick.memory.ports import MemoryProviderError, validate_retain_items
from sidekick.shared.types import TxSession


class BatchSender:
    """Collects the due documents found by the scan and sends at most one batch of them."""

    def __init__(self, deps: PassDeps, state: PassState) -> None:
        self._store = deps.store
        self._provider = deps.provider
        self._policy = deps.policy
        self._breaker = deps.breaker
        self._clock = deps.clock
        self._state = state
        self._collector = SendCollector()

    def offer(self, candidate: SendCandidate) -> None:
        self._collector.add(candidate)

    def send_batch(self) -> None:
        collected = self._collector.items()
        if not collected:
            return
        now = self._clock.now()
        day = now.astimezone(UTC).date()
        with self._store.read() as session:
            usage = self._store.daily_usage(session, self._state.owner_id, day)
        selected = select_batch(
            collected,
            live_remaining=self._policy.daily_retain_cap - usage.live,
            backfill_remaining=self._policy.backfill_daily_cap - usage.backfill,
            char_cap=self._policy.daily_char_cap,
            chars_used=usage.characters,
        )
        self._state.result.deferred_by_budget = len(collected) - len(selected)
        if not selected:
            return
        reserved = self._reserve(selected, day)
        if reserved is None:
            return
        self._state.lock.assert_alive()
        self._send_group(reserved, day)

    def _reserve(self, selected: list[SendCandidate], day: date) -> list[SendCandidate] | None:
        """One transaction: re-check settings, count the batch against the caps, bump attempts."""

        now = self._clock.now()
        result = self._state.result
        accepted: list[SendCandidate] = []
        try:
            with self._store.begin() as session:
                settings = self._store.settings(session, self._state.owner_id)
                if settings is None or settings.paused:
                    return None
                rows = self._store.source_rows_for_update(
                    session, self._state.owner_id, [c.row_id for c in selected]
                )
                for candidate in selected:
                    row = rows.get(candidate.row_id)
                    if (
                        row is None
                        or row.excluded
                        or row.fingerprint != candidate.fingerprint
                        or not is_due(row, now)
                        or not getattr(settings, SETTINGS_FLAG[row.source_kind])
                    ):
                        continue
                    row.attempts += 1
                    # Until `submitted` is committed, a crash leaves the row due again later.
                    row.next_attempt_at = now + retry_backoff(row.attempts)
                    try:
                        validate_retain_items([candidate.item])
                    except ValueError:
                        if record_failure(row, "rejected", now) == PARKED:
                            result.parked += 1
                        else:
                            result.failed += 1
                        result.note_error("rejected")
                        continue
                    if row.retained_at is None:
                        # Evidence that a retain may reach the bank late, even if this attempt
                        # is never committed as `submitted`. Deletion relies on it.
                        row.retained_at = now
                    accepted.append(candidate)
                if not accepted:
                    return None
                self._charge(session, accepted, day)
        except BudgetRefused:
            result.deferred_by_budget += len(selected)
            return None
        return accepted

    def _charge(self, session: TxSession, items: Sequence[SendCandidate], day: date) -> None:
        """Count documents against today's caps. The upsert refuses atomically past a cap."""

        live = sum(1 for c in items if not c.backfill)
        backfill = sum(1 for c in items if c.backfill)
        characters = sum(c.characters for c in items)
        char_cap = self._policy.daily_char_cap
        if live > self._policy.daily_retain_cap or backfill > self._policy.backfill_daily_cap:
            raise BudgetRefused
        if char_cap <= 0 or (characters > char_cap and len(items) > 1):
            raise BudgetRefused
        # A single document longer than the whole cap is only allowed on a day with nothing sent.
        charged = self._store.charge_usage(
            session,
            self._state.owner_id,
            day,
            live=live,
            backfill=backfill,
            characters=characters,
            live_cap=self._policy.daily_retain_cap,
            backfill_cap=self._policy.backfill_daily_cap,
            char_cap=char_cap,
            single_document=len(items) == 1,
        )
        if not charged:
            raise BudgetRefused

    def _refund(self, session: TxSession, items: Sequence[SendCandidate], day: date) -> None:
        self._store.refund_usage(
            session,
            self._state.owner_id,
            day,
            live=sum(1 for c in items if not c.backfill),
            backfill=sum(1 for c in items if c.backfill),
            characters=sum(c.characters for c in items),
        )

    def _send_group(self, items: list[SendCandidate], day: date) -> None:
        """Send one request. A rejected multi-document batch is retried one document at a time,
        inside the same attempt, so a single bad document cannot park its neighbours."""

        if self._state.provider_down:
            self._release_unsent(items, day)
            return
        self._state.lock.assert_alive()
        try:
            operation_id = self._provider.retain_batch(
                owner_id=self._state.owner_id, items=[c.item for c in items]
            )
        except MemoryProviderError as error:
            if error.category == "rejected" and len(items) > 1:
                for item in items:
                    self._send_group([item], day)
                return
            self._fail_send(items, error.category, day)
            return
        self._mark_submitted(items, operation_id)

    def _release_unsent(self, items: Sequence[SendCandidate], day: date) -> None:
        """Give back the attempt and the budget of documents that were never offered."""

        with self._store.begin() as session:
            for row in self._store.source_rows_for_update(
                session, self._state.owner_id, [c.row_id for c in items]
            ).values():
                if row.status in (PENDING, FAILED):
                    row.attempts = max(row.attempts - 1, 0)
                    row.next_attempt_at = None
            self._refund(session, items, day)

    def _still_allowed(self, items: Sequence[SendCandidate]) -> frozenset[UUID]:
        """Row ids whose retain the owner's policy still permits, read after the provider call.

        The retain may have been slow. If the owner paused memory, switched the kind off, excluded
        the record or deleted it meanwhile, the row must not be recorded as synced.
        """

        with self._store.read() as session:
            settings = self._store.settings(session, self._state.owner_id)
            if settings is None or settings.paused:
                return frozenset()
            flags = self._store.source_flags(
                session, self._state.owner_id, [c.row_id for c in items]
            )
        return frozenset(
            flag.row_id
            for flag in flags
            if not flag.excluded and getattr(settings, SETTINGS_FLAG[flag.source_kind])
        )

    def _mark_submitted(self, items: Sequence[SendCandidate], operation_id: str) -> None:
        """Record the accepted retain as submitted, unless the policy changed during the call.

        A discarded row keeps `retained_at` (set when the send was reserved), so the no-resurrection
        rule still deletes its document twice if the record has been removed or excluded; if the
        owner only paused or switched the kind off, the row stays due and is sent again later.
        """

        allowed = self._still_allowed(items)
        kept = [c for c in items if c.row_id in allowed]
        self._state.result.discarded_by_policy += len(items) - len(kept)
        if not kept:
            return
        items = kept
        now = self._clock.now()
        with self._store.begin() as session:
            self._store.mark_submitted(
                session,
                [c.row_id for c in items],
                operation_id=operation_id,
                deadline=now + OPERATION_DEADLINE,
            )
        self._state.result.sent += len(items)

    def _fail_send(self, items: Sequence[SendCandidate], category: str, day: date) -> None:
        now = self._clock.now()
        result = self._state.result
        result.note_error(category)
        with self._store.begin() as session:
            for row in self._store.source_rows_for_update(
                session, self._state.owner_id, [c.row_id for c in items]
            ).values():
                if row.status in (PENDING, FAILED):
                    if record_failure(row, category, now) == PARKED:
                        result.parked += 1
                    else:
                        result.failed += 1
            if category in NOTHING_SENT:
                self._refund(session, items, day)
        if category in PROVIDER_WIDE:
            self._state.provider_down = True
        if category != "rejected":
            self._breaker.failure(self._state.owner_id, now)
            if self._breaker.is_open(self._state.owner_id, now):
                result.sending_blocked = True
