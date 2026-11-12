# ADR-006: Persist in PostgreSQL behind least-privilege roles, and make every write idempotent and versioned

- Status: Accepted (D-089, 2026-11-11); records the delivered design, no behaviour changed
- Date: 2026-11-11
- Owners: Sidekick application maintainers

## Context

Sidekick keeps one owner's records (journal, contacts, tasks, projects, shopping, memory bookkeeping, audit) and is
written to by clients that retry: a Claude host that repeats a tool call, an Android outbox that replays after a
dropped connection, an updater that restarts a service in the middle of a request. The records are personal, so a
duplicated write, a silently overwritten edit or a stored copy of private text in a bookkeeping table are all
failures, and so is a runtime bug that can change the schema or rewrite history.

The decision had to hold for every transport (FastAPI routes, FastMCP tools, the companion adapter) without each
re-implementing it, and had to be testable without a framework (ADR-002).

## Decision

### One database, three roles, expand-only migrations

PostgreSQL is the only store of record. Three roles split authority (`deploy/postgres-init.test-only.sql`):
`sidekick_owner` owns the schema and has no login, `sidekick_migrator` runs migrations, and `sidekick_app` is the
role every runtime process uses and holds data privileges only. At production start the runtime refuses a role that
is a superuser, owns objects, can create in the schema or bypasses row-level security
(`backend/src/sidekick/shared/persistence/runtime_role.py`). Runtime processes never migrate; migrations are an
explicit one-shot step that runs before the new image starts (Yoyo, `migrations/`, baseline
`100_schema_baseline_0_1_0.py`; `docs/explanation/architecture/backend.md`).

A release may only run expand migrations. A file that drops, renames, retypes, adds `NOT NULL`, revokes or truncates
must declare `# migration-class: contract`, and `tools/check-migration-policy.py` fails the build on an unmarked one.
History tables are append-only for the app role: `audit_events`, `domain_events` and `activity_entries` grant the
runtime `INSERT` and `SELECT` only (set in `migrations/100_schema_baseline_0_1_0.py`; the grant was narrowed by migration 102
before it was folded into the baseline).
Permanent removal (`sidekick-admin empty-trash`) runs as the same app role, which holds `DELETE` on the tables it
removes from, including `domains` and `processes` (granted in the baseline, formerly migration 103). It deletes the
record, never that history: the ledger keeps the titles and values it recorded. `journal_entries` and the shopping
tables keep no `DELETE`, so permanent removal refuses them with a safe error and the sweep counts them as kept; an
immutable Journal source has no `UPDATE` or `DELETE` grant either. Erasing Journal entries is not supported.

### Every write is an explicit command with a version and an idempotency key

Writes are application commands that run in one transaction (`SqlAlchemyStore.transaction`,
`backend/src/sidekick/shared/persistence/stores/base.py`). Two guards apply to them:

- **Optimistic versions.** Editable records such as journal entries, task steps and actions carry a `version`; a command names
  the `expected_version` it read and a stale one is refused instead of overwriting (`_require_transition` in
  `backend/src/sidekick/journal/domain/entry.py`, `expected_version` in
  `backend/src/sidekick/work/application/steps_service.py`).
- **Idempotency keys.** `SqlAlchemyStore.idempotent` runs the work once per `(actor, operation, key)`. The key is
  8 to 128 characters (`run_idempotent_operation`, `backend/src/sidekick/shared/idempotent_operation.py`).
  A transaction-scoped advisory lock derived from the triple serializes concurrent retries; a unique constraint on
  `idempotency_operations` backs it (`IdempotencyRow`). The same key with a different payload hash raises
  `IdempotencyKeyReusedError`, a plain `conflict` to clients. Records older than 30 days are pruned.

### Replay records keep identifiers, not content

What an idempotency row stores is a projection, not the answer. `replay_record` accepts either an explicit projection
(`backend/src/sidekick/shared/replay.py`: ids, and ids in order) or an operation named in
`IDENTITY_REPLAY_OPERATIONS`, checks that the record holds identifiers, versions, flags and timestamps only, and caps
it at 16 KiB. A retry returns the stored record and the application layer re-reads the rest by id, so no title, note
or name is kept in the idempotency table and a retry never returns a stale copy of text that has since changed.

### History and removal

Security and mutation events append to the audit log, and task mutations append to the domain event ledger of
which the activity feed is a projection.
Deleting a record from the product moves it to the trash and it can be restored; permanent deletion is not an MCP
tool (`backend/src/sidekick/lifecycle/persistence.py`). Backups are encrypted and restore-checked before
they count (see `docs/explanation/threat-model.md`).

## Consequences

- A client may repeat any write safely; the cost is a key per command and an advisory-lock round trip.
- A compromised or buggy runtime cannot alter the schema or erase history, but retention work (pruning, owner
  removal) must run with the owner role or through foreign-key cascades.
- Adding a write means choosing a replay projection or adding a reviewed allow-list entry; the store raises
  `ReplayRecordError` otherwise, so the choice cannot be skipped.
- Contract migrations are possible but visible in review and in the release gate.

## Rejected and deferred

- Row-level security as the isolation mechanism: not used. Every read and write filters by `owner_id` in the
  persistence adapters (`docs/explanation/architecture/backend.md`),. The runtime role check refuses a role that bypasses
  row-level security. `DEFERRED`: policies as defence in depth.
- Storing whole results for retries is refused by the store, because it would duplicate private text.

## Evidence

- `backend/src/sidekick/shared/persistence/stores/base.py`
- `backend/src/sidekick/shared/idempotent_operation.py`
- `backend/src/sidekick/shared/persistence/runtime_role.py`
- `backend/src/sidekick/shared/replay.py`
- `backend/src/sidekick/shared/persistence/models/` (`IdempotencyRow`, `AuditEventRow`, `DomainEventRow`)
- `migrations/100_schema_baseline_0_1_0.py`
- `tools/check-migration-policy.py`
- `deploy/postgres-init.test-only.sql`
- `docs/explanation/architecture/backend.md`
