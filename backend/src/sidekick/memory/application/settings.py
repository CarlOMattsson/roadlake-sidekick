"""Derived-memory settings, status and per-record exclusion. Owner-scoped, scope-checked.

Three use cases behind the MCP tools `get_memory_status`, `set_memory_settings` and
`exclude_from_memory`. None of them calls the provider. Switching a domain off or excluding a record
only changes Postgres; the sync pass (`application/sync.py`) then deletes the documents, because
`queries.tombstone_page` lists every row of a switched-off domain and every row with
`excluded = true`.

Scopes (the choice is documented here, next to the code that checks it). Memory has no scope of
its own.
- Reading status needs at least one of the read scopes in `recall.KIND_READ_SCOPE`
  (`journal:read`, `contacts:read`, `projects:read`, `tasks:read`) and counts only the kinds whose
  read scope the actor holds.
- Switching a domain needs that domain's write scope, the one its existing write tools use:
  `journal` -> `journal:write`, `contacts` -> `contacts:write`, `projects` -> `projects:write`,
  `tasks` -> `tasks:write`. Every domain named in the call is checked, also when the value is
  unchanged, so a client cannot probe a domain it may not touch.
- `paused` is global and needs at least one of those four write scopes.
- Excluding a record needs the write scope of its kind (`KIND_WRITE_SCOPE`).

Destructive switch. Turning a domain OFF deletes derived documents, and turning it on again costs a
new import. Without `confirm` the call changes nothing and returns what would be removed. The
number of documents is given only for a domain whose read scope the actor holds; a write-only
caller sees that the domain's facts go, without a count. Turning on and pausing never need
`confirm`. Settings use optimistic locking on `version`; a missing row reads as the defaults (the
four domains on, paused off) at version 0, and the first write creates it as version 1. Owners get
their row when they are provisioned (`provision_owner_settings`, called by `AuthService` through
a composition hook) and a backfill covered existing owners, so
a missing row is an exception, not the normal state. A call whose values are all already set returns
`unchanged` without a version check, so a repeated successful call is not a conflict.

Exclusion. A record is excluded through its `memory_sources` row (`excluded = true`). A record that
was never synced gets a marker row (`parked`, failure category `removed`, no document ever sent), so
the exclusion is remembered and the sync never creates a document for it; its tombstone pass skips
such a marker. `excluded = false` clears the flag; the scan then treats a removed marker as stale
and imports the record again. A never-sent marker whose id is random (written while no derivation
key was set) is deleted instead, so the next pass creates a normal candidate with the derived id. A
row that was ever sent only has its flag cleared, so its document id stays the same. Ownership and
trash are checked: a record of another owner, a missing one and a trashed one are all
`NotFoundError`. Nothing here logs titles or ids of records.
"""

from __future__ import annotations

import secrets
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from sidekick.memory.application.recall import KIND_READ_SCOPE
from sidekick.memory.application.records import MemorySettingsRecord, MemorySourceRecord
from sidekick.memory.application.store import MemoryStore
from sidekick.memory.application.sync import PARKED, derive_doc_key
from sidekick.memory.domain import MemoryKind
from sidekick.shared.errors import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from sidekick.shared.types import Actor, TxSession

Domain = Literal["journal", "contacts", "projects", "tasks"]
DOMAINS: tuple[Domain, ...] = ("journal", "contacts", "projects", "tasks")

DOMAIN_KIND: dict[str, MemoryKind] = {
    "journal": MemoryKind.JOURNAL_ENTRY,
    "contacts": MemoryKind.CONTACT,
    "projects": MemoryKind.PROJECT,
    "tasks": MemoryKind.TASK,
}

DOMAIN_WRITE_SCOPE: dict[str, str] = {
    "journal": "journal:write",
    "contacts": "contacts:write",
    "projects": "projects:write",
    "tasks": "tasks:write",
}

#: Every setting name `change_settings` accepts.
ALLOWED_SETTINGS: frozenset[str] = frozenset((*DOMAINS, "paused"))

KIND_WRITE_SCOPE: dict[MemoryKind, str] = {
    kind: DOMAIN_WRITE_SCOPE[domain] for domain, kind in DOMAIN_KIND.items()
}

#: Row statuses reported by `get_memory_status`. `submitted` counts as pending (in flight).
STATUS_BUCKETS: tuple[str, ...] = ("retained", "pending", "failed", "parked", "excluded")


@dataclass(frozen=True, slots=True)
class MemorySettingsView:
    """The owner's settings. No row reads as the defaults: domains on, not paused, version 0."""

    journal: bool = True
    contacts: bool = True
    projects: bool = True
    tasks: bool = True
    paused: bool = False
    version: int = 0

    def enabled(self, domain: str) -> bool:
        return bool(getattr(self, domain))


@dataclass(frozen=True, slots=True)
class SourceCounts:
    """How many `memory_sources` rows of one kind sit in each state."""

    retained: int = 0
    pending: int = 0
    failed: int = 0
    parked: int = 0
    excluded: int = 0


@dataclass(frozen=True, slots=True)
class MemoryStatus:
    settings: MemorySettingsView
    counts: dict[MemoryKind, SourceCounts]


@dataclass(frozen=True, slots=True)
class Removal:
    """A domain being switched off and how many retained documents that removes.

    `documents` is None when the actor may not read that domain's kind (write scope only).
    """

    domain: Domain
    documents: int | None


@dataclass(frozen=True, slots=True)
class SettingsOutcome:
    status: Literal["updated", "unchanged", "needs_confirmation"]
    settings: MemorySettingsView
    turning_off: tuple[Removal, ...]


@dataclass(frozen=True, slots=True)
class ExclusionOutcome:
    kind: MemoryKind
    source_id: UUID
    title: str | None
    excluded: bool
    changed: bool


def _view(row: MemorySettingsRecord | None) -> MemorySettingsView:
    if row is None:
        return MemorySettingsView()
    return MemorySettingsView(
        journal=row.journal,
        contacts=row.contacts,
        projects=row.projects,
        tasks=row.tasks,
        paused=row.paused,
        version=row.version,
    )


def provision_owner_settings(
    store: MemoryStore, session: TxSession, owner_id: UUID, now: datetime
) -> None:
    """Give a new owner the default memory settings row (all four domains on, paused off).

    The sync and recall read this row, so it is written with the user; a missing row would leave
    the owner out of the worker's scan. Joins the caller's transaction and is a no-op when the row
    already exists. `AuthService` reaches it through a hook the composition root passes in.
    """

    store.insert_default_settings(session, owner_id, now)


def readable_kinds(actor: Actor) -> tuple[MemoryKind, ...]:
    """The kinds the actor may see counts for; empty when it holds no read scope at all."""

    return tuple(kind for kind in MemoryKind if KIND_READ_SCOPE[kind] in actor.scopes)


def memory_status(store: MemoryStore, session: TxSession, actor: Actor) -> MemoryStatus:
    """The owner's settings and `memory_sources` counts per readable kind.

    Raises PermissionDeniedError when the actor holds none of the read scopes. A removed marker
    whose record is not excluded is a deleted document, not a parked failure, and is not counted.
    """

    kinds = readable_kinds(actor)
    if not kinds:
        raise PermissionDeniedError("missing required scope: journal:read")
    owner_id = actor.user_id
    settings = _view(store.settings(session, owner_id))
    rows = store.source_counts(session, owner_id, list(kinds))
    tally: dict[MemoryKind, Counter[str]] = {kind: Counter() for kind in kinds}
    for row in rows:
        bucket = (
            "excluded"
            if row.excluded
            else None
            if row.removed_marker
            else "pending"
            if row.status == "submitted"
            else row.status
        )
        if bucket in STATUS_BUCKETS:
            tally[MemoryKind(row.source_kind)][bucket] += row.count
    return MemoryStatus(
        settings=settings,
        counts={
            kind: SourceCounts(**{bucket: counter[bucket] for bucket in STATUS_BUCKETS})
            for kind, counter in tally.items()
        },
    )


def _removal_count(
    store: MemoryStore, session: TxSession, actor: Actor, owner_id: UUID, domain: Domain
) -> int | None:
    """Retained documents that switching `domain` off removes, or None without its read scope.

    A write-only caller learns that the domain's facts go, not how many, so the count is not read.
    """

    kind = DOMAIN_KIND[domain]
    if KIND_READ_SCOPE[kind] not in actor.scopes:
        return None
    return store.retained_document_count(session, owner_id, kind)


def change_settings(
    store: MemoryStore,
    session: TxSession,
    actor: Actor,
    *,
    changes: dict[str, bool],
    expected_version: int,
    confirm: bool,
    now: datetime,
    correlation_id: str | None = None,
) -> SettingsOutcome:
    """Apply `changes` (domain names and `paused` -> new value) with optimistic locking.

    Order: scope, then whether any value changes, then version, then the confirmation gate. A call
    that changes no value returns `unchanged` with the current settings and version, without a
    version check and without a write, so a repeat of a successful call is not a conflict. A switch
    from on to off without `confirm` writes nothing and returns `needs_confirmation` with the
    retained documents it would remove (None for a domain the actor may not read). The caller owns
    the transaction (`session_factory.begin()`).

    A write appends one content-free audit event per changed setting (`memory.<name>_on` or
    `_off`, the owner id and the correlation id) in the same transaction. A repeat of the call
    changes no value, writes nothing and so records nothing.
    """

    # The setting names and values are a closed set: only the four domains and `paused`, each a real
    # boolean. Anything else is refused before any scope check or write, so no caller can store an
    # unknown fact type or a truthy non-boolean in the owner's row.
    for name, value in changes.items():
        if name not in ALLOWED_SETTINGS:
            raise ValidationError("unknown memory setting")
        if not isinstance(value, bool):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise ValidationError("memory settings must be true or false")
    # An empty call and `paused` ask for no single domain, so any write scope is enough to proceed.
    no_write_scope = not any(scope in actor.scopes for scope in DOMAIN_WRITE_SCOPE.values())
    if (not changes or "paused" in changes) and no_write_scope:
        raise PermissionDeniedError("missing required scope: journal:write")
    for name in changes:
        if name != "paused":
            actor.require(DOMAIN_WRITE_SCOPE[name])
    if not changes:
        raise ValidationError("at least one memory setting is required")
    if expected_version < 0:
        raise ValidationError("expected version must not be negative")
    owner_id = actor.user_id
    row = store.settings_for_update(session, owner_id)
    current = _view(row)
    effective = {name: value for name, value in changes.items() if getattr(current, name) != value}
    if not effective:
        if row is None:
            # No row reads as all on, but the worker and recall only follow stored rows, so an
            # owner confirming the default gets one.
            store.insert_default_settings(session, owner_id, now)
        return SettingsOutcome("unchanged", current, ())
    if current.version != expected_version:
        raise ConflictError("memory settings version is stale", reason="stale_version")
    turning_off = tuple(
        Removal(domain, _removal_count(store, session, actor, owner_id, domain))
        for domain in DOMAINS
        if effective.get(domain) is False
    )
    if turning_off and not confirm:
        return SettingsOutcome("needs_confirmation", current, turning_off)
    if row is None:
        created = store.create_settings(
            session,
            owner_id,
            journal=effective.get("journal", True),
            contacts=effective.get("contacts", True),
            projects=effective.get("projects", True),
            tasks=effective.get("tasks", True),
            paused=effective.get("paused", False),
            now=now,
        )
        if not created:
            raise ConflictError("memory settings version is stale", reason="stale_version")
    else:
        for name, value in effective.items():
            setattr(row, name, value)
        row.version = current.version + 1
        row.updated_at = now
        session.flush()
    for name, value in effective.items():
        store.append_audit(
            session,
            actor_id=owner_id,
            event=f"memory.{name}_{'on' if value else 'off'}",
            outcome="success",
            target_type="memory_settings",
            target_id=owner_id,
            correlation_id=correlation_id,
        )
    saved = _view(store.settings(session, owner_id, fresh=True))
    return SettingsOutcome("updated", saved, turning_off)


def _title_of(
    store: MemoryStore, session: TxSession, owner_id: UUID, kind: MemoryKind, source_id: UUID
) -> str | None:
    """The record's title when it exists, is the owner's and is not in the trash; else raises."""

    found = store.record_title(session, owner_id, kind, source_id)
    if found is None:
        raise NotFoundError("record not found")
    return str(found.title)


def _marker_doc_key(id_key: bytes | None, owner_id: UUID, kind: MemoryKind, source_id: UUID) -> str:
    """The document id for a marker row: the sync's HMAC id, or a random one while no key is set.

    The row stores it, and the sync always reads `doc_key` from the row, so a random id stays
    stable. It has the same shape (`d1_` and 64 hex characters) and names no record.
    """

    if id_key:
        return derive_doc_key(id_key, owner_id, kind, source_id)
    return f"d1_{secrets.token_hex(32)}"


def _unsent_marker_with_random_id(
    row: MemorySourceRecord, id_key: bytes | None, owner_id: UUID, kind: MemoryKind, source_id: UUID
) -> bool:
    """A marker that was never sent and does not carry the HMAC id the sync would use now.

    It was written while no derivation key was set, so its id is random. Nothing was ever sent
    under that id (`retained_at` is empty), so the row can simply go; the next sync pass creates a
    plain candidate with the derived id, or nothing while no key is set.
    """

    if row.status != PARKED or row.retained_at is not None:
        return False
    return id_key is None or row.doc_key != derive_doc_key(id_key, owner_id, kind, source_id)


def set_exclusion(
    store: MemoryStore,
    session: TxSession,
    actor: Actor,
    *,
    kind: MemoryKind,
    source_id: UUID,
    excluded: bool,
    id_key: bytes | None,
    now: datetime,
    correlation_id: str | None = None,
) -> ExclusionOutcome:
    """Exclude a record from memory, or bring it back. Reversible; the caller owns the transaction.

    Needs the write scope of `kind`. The record must be the owner's and not trashed (NotFoundError
    otherwise). Excluding a record with no `memory_sources` row creates a marker row; including a
    record with no row is a no-op. Including a marker that was never sent and has a random id
    deletes the marker, so the sync creates a normal candidate with the derived id. Any other row
    only has its flag flipped. Safe against a concurrent sync insert: the insert is an upsert.
    A change appends one content-free audit event in the same transaction.
    """

    actor.require(KIND_WRITE_SCOPE[kind])
    owner_id = actor.user_id
    outcome = _apply_exclusion(
        store,
        session,
        owner_id,
        kind=kind,
        source_id=source_id,
        excluded=excluded,
        id_key=id_key,
        now=now,
    )
    if outcome.changed:
        # Content-free: the kind, the record id and the correlation id, never the title. A repeat
        # changes nothing, so it records nothing.
        store.append_audit(
            session,
            actor_id=owner_id,
            event="memory.excluded" if outcome.excluded else "memory.included",
            outcome="success",
            target_type=kind.value,
            target_id=source_id,
            correlation_id=correlation_id,
        )
    return outcome


def _apply_exclusion(
    store: MemoryStore,
    session: TxSession,
    owner_id: UUID,
    *,
    kind: MemoryKind,
    source_id: UUID,
    excluded: bool,
    id_key: bytes | None,
    now: datetime,
) -> ExclusionOutcome:
    title = _title_of(store, session, owner_id, kind, source_id)
    row = store.source_row_for_update(session, owner_id, kind, source_id)
    if row is not None:
        if not excluded and _unsent_marker_with_random_id(row, id_key, owner_id, kind, source_id):
            changed = row.excluded
            session.delete(row)
            session.flush()
            return ExclusionOutcome(kind, source_id, title, False, changed)
        changed = row.excluded != excluded
        if changed:
            row.excluded = excluded
            session.flush()
        return ExclusionOutcome(kind, source_id, title, excluded, changed)
    if not excluded:
        return ExclusionOutcome(kind, source_id, title, False, False)
    store.upsert_exclusion_marker(
        session,
        owner_id,
        kind,
        source_id,
        doc_key=_marker_doc_key(id_key, owner_id, kind, source_id),
        now=now,
    )
    return ExclusionOutcome(kind, source_id, title, True, True)


def domain_names(domains: Sequence[str]) -> str:
    """`a`, `a and b`, `a, b and c`."""

    if len(domains) <= 1:
        return "".join(domains)
    return f"{', '.join(domains[:-1])} and {domains[-1]}"
