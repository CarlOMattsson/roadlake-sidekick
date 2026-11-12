"""Bank lifecycle for derived memory: the lost-volume check and the orphan-bank sweep.

Both read Hindsight and write Postgres or Hindsight, and neither holds a transaction across a
network call (read, close, call, then write in a new transaction), like the reconcile pass.
Logs carry owner ids, counts and fixed categories only, never document text.

- `verify_banks_after_start` finds owners whose rows say `retained` while Hindsight holds no
  document for them (a lost volume, a restored `pg_dump`, a rotated derivation key) and sets those
  rows back to `pending`, so the backfill happens under the cost caps instead of recall going
  silently empty. A provider failure changes nothing and is retried by the caller.
- `sweep_orphan_banks` deletes banks that belong to no living user. It never touches an id that is
  not in Sidekick's own bank format, and it refuses outright when the picture looks wrong (see
  `sweep_orphan_banks`), because a wrong deletion costs a full re-import.

D-057: nothing of the owner's data in Postgres is deleted here. `memory_sources` rows only change
status, and rows of a deleted user are removed by the `users` foreign key cascade, not by this code.
"""

from __future__ import annotations

import logging
from collections.abc import Collection
from dataclasses import dataclass
from uuid import UUID

from sidekick.memory.application.store import MemoryStore
from sidekick.memory.ports import (
    BANK_ID_PATTERN,
    MemoryFailureCategory,
    MemoryProvider,
    MemoryProviderError,
)

LOGGER = logging.getLogger("sidekick.memory.lifecycle")

#: A sweep deletes at most this many banks. More orphans than this look like a mistake (wrong
#: instance or key), not an account clean-up, so the sweep deletes none and says so.
MAX_ORPHAN_BANKS_PER_SWEEP = 10


@dataclass(slots=True)
class BankCheckResult:
    """Counts and fixed categories only. Safe to log."""

    owners_checked: int = 0
    owners_reset: int = 0
    rows_reset: int = 0
    owners_locked: int = 0
    #: False when the provider could not answer, so the caller should try again later.
    complete: bool = True
    error_category: str | None = None


@dataclass(slots=True)
class SweepResult:
    """Counts and fixed categories only. Safe to log."""

    banks_listed: int = 0
    banks_ours: int = 0
    orphans_found: int = 0
    banks_deleted: int = 0
    #: A fixed reason the sweep deleted nothing on purpose, or None.
    refused: str | None = None
    error_category: str | None = None


def verify_banks_after_start(store: MemoryStore, provider: MemoryProvider) -> BankCheckResult:
    """For each living owner with `retained` rows, reset them to `pending` if their bank is lost.

    A bank is lost when it is not in `list_banks`, or when it is listed and holds no document. The
    bank list is read first, and a failure there ends the check, so a 404 or a broken proxy can
    never make every bank look lost. Any failure ends the check with `complete=False` and changes
    nothing; the caller runs it again later. A reset is never made on an error. An empty listing
    counts as lost banks (logged as `memory_bank_list_empty`), so a total volume loss is restored.
    """

    result = BankCheckResult()
    with store.read() as session:
        owners = store.owners_with_retained_rows(session)
    if not owners:
        return result
    try:
        listed = frozenset(provider.list_banks())
    except MemoryProviderError as error:
        result.complete = False
        result.error_category = error.category
        LOGGER.warning("memory_bank_check_unavailable", extra={"error_category": error.category})
        return result  # The provider is likely down for everyone; try again later.
    if not listed:
        LOGGER.warning("memory_bank_list_empty")  # Every owner's bank counts as lost below.
    for owner_id in owners:
        try:
            lost = _bank_is_lost(provider, owner_id, listed)
        except MemoryProviderError as error:
            return _unavailable(result, owner_id, error.category)
        result.owners_checked += 1
        if not lost:
            continue
        try:
            reset = _reset_retained_rows(store, provider, owner_id)
        except MemoryProviderError as error:
            return _unavailable(result, owner_id, error.category)
        if reset is None:
            result.owners_locked += 1
            result.complete = False  # A pass holds the lock right now; look again next time.
            continue
        if reset == 0:
            continue  # The recheck under the lock found documents: nothing to reset.
        result.owners_reset += 1
        result.rows_reset += reset
        LOGGER.warning(
            "memory_bank_lost",
            extra={"rows_reset": reset},
        )
    return result


def _bank_is_lost(provider: MemoryProvider, owner_id: UUID, listed: Collection[str]) -> bool:
    """True when the owner's bank is not listed, or is listed and holds no document.

    Raises `MemoryProviderError` when the document count cannot be read. That is never a loss.
    """

    if provider.bank_id_for(owner_id) not in listed:
        return True
    return provider.document_count(owner_id=owner_id) == 0


def _unavailable(
    result: BankCheckResult, owner_id: UUID, category: MemoryFailureCategory
) -> BankCheckResult:
    result.complete = False
    result.error_category = category
    LOGGER.warning(
        "memory_bank_check_unavailable",
        extra={"error_category": category},
    )
    return result


def _reset_retained_rows(
    store: MemoryStore, provider: MemoryProvider, owner_id: UUID
) -> int | None:
    """Set the owner's `retained` rows to `pending`. None when the owner's lock is taken.

    The loss is checked again under the owner's lock, before the update, because a pass may have
    retained documents since the first look. Then nothing is reset and 0 is returned. The lock
    connection is autocommit, so no database transaction is open across the provider calls.

    `retained_at` is kept: it records that the bank once held the document. The fingerprint and
    `source_updated_at` stay, so an unchanged record is simply sent again, under the backfill cap.
    """

    lock = store.owner_lock(owner_id)
    if not lock.acquire():
        return None
    try:
        listed = frozenset(provider.list_banks())
        if not listed:
            LOGGER.warning("memory_bank_list_empty")
        if not _bank_is_lost(provider, owner_id, listed):
            return 0
        with store.begin() as session:
            return store.reset_retained_rows(session, owner_id)
    finally:
        lock.release()


def sweep_orphan_banks(
    store: MemoryStore,
    provider: MemoryProvider,
    *,
    max_deletes: int = MAX_ORPHAN_BANKS_PER_SWEEP,
) -> SweepResult:
    """Delete Sidekick-format banks that belong to no living user.

    The bank list is read first and the user list second, so a bank in the list always belongs to
    a user who existed when the users were read. Ownership is decided by deriving every living
    user's bank id with the provider's own key; a bank nobody derives is an orphan. Refuses (and
    deletes nothing) when:

    - there is no living user at all;
    - a living owner has `retained` rows but none of the living banks is in the list, which means
      the list is from another instance or the derivation key changed, not that every bank is an
      orphan;
    - more than `max_deletes` orphans are found.
    """

    result = SweepResult()
    try:
        listed = provider.list_banks()
    except MemoryProviderError as error:
        result.error_category = error.category
        return result
    result.banks_listed = len(listed)
    ours = {bank_id for bank_id in listed if BANK_ID_PATTERN.fullmatch(bank_id)}
    result.banks_ours = len(ours)
    if not ours:
        return result
    with store.read() as session:
        living = store.living_owner_ids(session)
        expecting = store.owners_expecting_banks(session) & set(living)
    living_banks = {provider.bank_id_for(owner_id) for owner_id in living}
    orphans = sorted(ours - living_banks)
    result.orphans_found = len(orphans)
    if not orphans:
        return result
    if not living:
        result.refused = "no_living_user"
    elif expecting and not ours & {provider.bank_id_for(owner_id) for owner_id in expecting}:
        result.refused = "no_living_bank_listed"
    elif len(orphans) > max_deletes:
        result.refused = "too_many_orphans"
    if result.refused is not None:
        LOGGER.warning(
            "memory_orphan_sweep_refused",
            extra={"refused": result.refused, "orphans_found": result.orphans_found},
        )
        return result
    for bank_id in orphans:
        try:
            provider.delete_bank(bank_id=bank_id)
        except MemoryProviderError as error:
            result.error_category = error.category
            break
        result.banks_deleted += 1
        LOGGER.info("memory_orphan_bank_deleted")
    return result
