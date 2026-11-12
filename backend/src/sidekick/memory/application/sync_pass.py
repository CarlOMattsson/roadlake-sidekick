"""Poll, tombstone and scan phases of the reconcile pass for one owner.

The phases run in the order described in `sidekick.memory.application.sync`; the send phase lives
in `sidekick.memory.application.sync_send`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sidekick.memory.application.queries import MemoryCandidate
from sidekick.memory.application.records import MemorySourceRecord
from sidekick.memory.application.sync_rules import (
    MAX_DELETES_PER_PASS,
    MAX_POLLED_OPERATIONS,
    PARKED,
    PENDING,
    PROVIDER_WIDE,
    RETAINED,
    SCAN_PAGE_SIZE,
    SUBMITTED,
    SendCandidate,
    derive_doc_key,
    is_backfill,
    is_due,
    is_removed_marker,
    record_failure,
    removal_hold_until,
    reset_to_pending,
    second_delete_pending,
    to_retain_item,
)
from sidekick.memory.application.sync_send import BatchSender
from sidekick.memory.application.sync_state import (
    Deletion,
    PassDeps,
    PassState,
    deletion_of,
)
from sidekick.memory.domain import MEMORY_PIPELINE_VERSION, MemoryKind, canonical_document
from sidekick.memory.ports import MemoryProviderError
from sidekick.shared.types import TxSession


class ReconcilePass:
    """One pass for one owner, run under the owner's lock."""

    def __init__(self, deps: PassDeps, state: PassState, *, full: bool) -> None:
        self._clock = deps.clock
        self._store = deps.store
        self._provider = deps.provider
        self._policy = deps.policy
        self._breaker = deps.breaker
        self._state = state
        self._full = full
        self._deletes_left = MAX_DELETES_PER_PASS
        self._sender = BatchSender(deps, state)

    def _now(self) -> datetime:
        return self._clock.now()

    # -- driver --

    def run(self) -> None:
        now = self._now()
        paused = self._load_paused()
        self._state.may_send = (
            self._policy.ingest_enabled
            and not paused
            and not self._breaker.is_open(self._state.owner_id, now)
        )
        self._state.result.sending_blocked = not self._state.may_send
        self._poll_operations()
        self._delete_tombstones()
        self._scan()
        if self._state.may_send and not self._state.provider_down:
            self._sender.send_batch()

    def _load_paused(self) -> bool:
        with self._store.read() as session:
            settings = self._store.settings(session, self._state.owner_id)
            return settings is None or settings.paused

    # -- 1. polling --

    def _poll_operations(self) -> None:
        with self._store.read() as session:
            rows = self._store.submitted_operations(session, self._state.owner_id)
        deadlines: dict[str, datetime | None] = {}
        for operation_id, deadline in rows:
            if operation_id is not None and deadlines.get(operation_id) is None:
                deadlines[operation_id] = deadline
        for operation_id in list(deadlines)[:MAX_POLLED_OPERATIONS]:
            if self._state.provider_down:
                break
            self._poll_one(operation_id, deadlines[operation_id])

    def _poll_one(self, operation_id: str, deadline: datetime | None) -> None:
        self._state.lock.assert_alive()
        try:
            outcome = self._provider.operation_status(
                owner_id=self._state.owner_id, operation_id=operation_id
            )
        except ValueError:
            # A stored operation id the provider port refuses can never be polled.
            self._finish_operation(operation_id, failed="operation_lost")
            return
        except MemoryProviderError as error:
            category = error.category
            self._state.result.note_error(category)
            if category in PROVIDER_WIDE:
                self._state.provider_down = True
            if deadline is not None and self._now() >= deadline:
                self._finish_operation(operation_id, failed="operation_lost")
            return
        if outcome.state == "retained":
            self._finish_operation(operation_id, failed=None)
        elif outcome.state == "failed":
            self._finish_operation(
                operation_id, failed=outcome.failure_category or "operation_failed"
            )
        elif deadline is not None and self._now() >= deadline:
            self._finish_operation(operation_id, failed="operation_lost")

    def _finish_operation(self, operation_id: str, *, failed: str | None) -> None:
        now = self._now()
        with self._store.begin() as session:
            rows = self._store.submitted_rows_for_update(
                session, self._state.owner_id, operation_id
            )
            for row in rows:
                if failed is None:
                    row.status = RETAINED
                    row.retained_at = now
                    row.operation_id = None
                    row.attempts = 0
                    row.next_attempt_at = None
                    row.failure_category = None
                    self._state.result.retained += 1
                else:
                    if record_failure(row, failed, now) == PARKED:
                        self._state.result.parked += 1
                    else:
                        self._state.result.failed += 1
        if not rows:
            return
        if failed is None:
            self._breaker.success(self._state.owner_id)
        else:
            self._state.result.note_error(failed)
            self._breaker.failure(self._state.owner_id, now)
            if self._breaker.is_open(self._state.owner_id, now):
                self._state.may_send = False
                self._state.result.sending_blocked = True

    # -- 2. tombstones --

    def _delete_tombstones(self) -> None:
        for kind in MemoryKind:
            after: UUID | None = None
            while self._deletes_left > 0 and not self._state.provider_down:
                with self._store.read() as session:
                    page = self._store.tombstone_page(
                        session,
                        self._state.owner_id,
                        kind,
                        after=after,
                        limit=SCAN_PAGE_SIZE,
                    )
                    rows = (
                        self._store.source_rows_by_id(
                            session, self._state.owner_id, [t.memory_source_id for t in page]
                        )
                        if page
                        else {}
                    )
                if not page:
                    break
                after = page[-1].memory_source_id
                deletions = [
                    deletion_of(rows[t.memory_source_id])
                    for t in page
                    if t.memory_source_id in rows
                ]
                self._run_deletions(deletions)
                if len(page) < SCAN_PAGE_SIZE:
                    break

    def _run_deletions(self, deletions: Sequence[Deletion]) -> None:
        for deletion in deletions:
            now = self._now()
            hold_until: datetime | None = None
            if deletion.removed:
                if deletion.next_attempt_at is None and deletion.excluded:
                    continue  # Document gone for good; the row is only the exclusion marker.
                if deletion.next_attempt_at is not None and deletion.next_attempt_at > now:
                    self._state.result.delete_deferred += 1  # Second delete not yet due.
                    continue
                # Due: this delete is the second one, and the last.
            elif deletion.status == SUBMITTED:
                self._state.result.delete_deferred += 1
                continue
            else:
                hold_until = removal_hold_until(
                    status=deletion.status,
                    attempts=deletion.attempts,
                    operation_id=deletion.operation_id,
                    retained_at=deletion.retained_at,
                    now=now,
                )
            if self._deletes_left <= 0 or self._state.provider_down:
                return
            self._deletes_left -= 1
            self._state.lock.assert_alive()
            try:
                self._provider.delete_document(
                    owner_id=self._state.owner_id, document_id=deletion.doc_key
                )
            except MemoryProviderError as error:
                category = error.category
                self._state.result.delete_failed += 1
                self._state.result.note_error(category)
                if category in PROVIDER_WIDE:
                    self._state.provider_down = True
                continue
            self._finish_deletion(deletion, hold_until)

    def _finish_deletion(self, deletion: Deletion, hold_until: datetime | None) -> None:
        with self._store.begin() as session:
            self._store.settle_removed_row(
                session,
                row_id=deletion.row_id,
                doc_key=deletion.doc_key,
                excluded=deletion.excluded,
                hold_until=hold_until,
            )
        self._state.result.deleted += 1

    # -- 3. scan --

    def _scan(self) -> None:
        for kind in MemoryKind:
            after: UUID | None = None
            while True:
                deletions: list[Deletion] = []
                with self._store.begin() as session:
                    page = self._store.candidate_page(
                        session,
                        self._state.owner_id,
                        kind,
                        owner_timezone=self._policy.owner_timezone,
                        after=after,
                        limit=SCAN_PAGE_SIZE,
                    )
                    if not page:
                        break
                    existing = self._store.source_rows_by_record(
                        session, self._state.owner_id, kind, [c.source_id for c in page]
                    )
                    now = self._now()
                    for candidate in page:
                        row = existing.get(candidate.source_id)
                        if row is not None and second_delete_pending(row):
                            # The record may be live again, but the marker must finish its second
                            # delete first, or a late retain of the old document would linger.
                            deletions.append(deletion_of(row))
                            continue
                        if not candidate.is_candidate:
                            if row is not None:
                                deletions.append(deletion_of(row))
                            continue
                        self._reconcile_record(session, kind, candidate, row, now)
                after = page[-1].source_id
                self._run_deletions(deletions)
                if len(page) < SCAN_PAGE_SIZE:
                    break

    def _reconcile_record(
        self,
        session: TxSession,
        kind: MemoryKind,
        candidate: MemoryCandidate,
        row: MemorySourceRecord | None,
        now: datetime,
    ) -> None:
        # A record changed inside the quiet period waits, so one exchange is sent once.
        if candidate.source_updated_at > now - self._policy.quiet:
            return
        if row is not None and row.status == SUBMITTED:
            return  # Wait for the operation; a change is picked up after it completes.
        if row is None:
            document = canonical_document(candidate.record)
            if document is None:
                return
            row = self._store.add_source(
                session,
                owner_id=self._state.owner_id,
                kind=kind,
                source_id=candidate.source_id,
                doc_key=derive_doc_key(
                    self._policy.id_key, self._state.owner_id, kind, candidate.source_id
                ),
                fingerprint=document.fingerprint,
                pipeline_version=MEMORY_PIPELINE_VERSION,
                status=PENDING,
                source_updated_at=candidate.source_updated_at,
            )
            self._state.result.queued += 1
        else:
            removed = is_removed_marker(row)
            stale = row.pipeline_version != MEMORY_PIPELINE_VERSION
            changed = candidate.source_updated_at > row.source_updated_at
            if not (self._full or changed or stale or removed or is_due(row, now)):
                return
            document = canonical_document(candidate.record)
            if document is None:
                return
            if document.fingerprint != row.fingerprint or stale or removed:
                reset_to_pending(row, document, candidate.source_updated_at)
                self._state.result.queued += 1
            elif changed:
                row.source_updated_at = candidate.source_updated_at
        if self._state.may_send and is_due(row, now):
            self._sender.offer(
                SendCandidate(
                    row_id=row.id,
                    source_updated_at=candidate.source_updated_at,
                    backfill=is_backfill(candidate.source_updated_at, now),
                    item=to_retain_item(row.doc_key, document),
                    fingerprint=row.fingerprint,
                )
            )
