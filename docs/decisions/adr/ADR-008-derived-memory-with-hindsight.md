# ADR-008: Keep memory derived and optional, with PostgreSQL authoritative and Hindsight behind a port

- Status: Accepted (D-091, 2026-11-11); records the delivered design, no behaviour changed
- Date: 2026-11-11
- Owners: Sidekick application maintainers

## Context

Claude is the assistant (ADR-002), and it benefits from remembering facts across conversations: who a contact is,
what a project is about, what was decided in a journal entry. Sidekick's records live in PostgreSQL and must stay the
single source of truth. A memory service extracts facts with a language model, which means private text leaves
Sidekick for a service the owner configures, and a fact it returns can be stale, wrong or about something the owner
has since deleted or asked to be forgotten. The integration had to make that boundary explicit and removable.

## Decision

### PostgreSQL is authoritative; Hindsight is a derived, replaceable index

Application code depends on the `MemoryProvider` port (`backend/src/sidekick/memory/ports.py`), not on Hindsight.
Settings select one of two providers: a deterministic in-process `fake` (the default, and what tests use) or the
`hindsight` HTTP adapter (`backend/src/sidekick/memory/factory.py`, `backend/src/sidekick/memory/adapters/`). Memory
is off unless `SIDEKICK_MEMORY_ENABLED` is set, and a configuration that enables the real provider without a base URL,
API token or id-derivation key refuses to start (`backend/src/sidekick/shared/config/memory.py`). Every provider failure is
a `MemoryProviderError` with a fixed category; messages, document text and response bodies never cross the port.

### What leaves Sidekick is a closed set of canonical documents

`backend/src/sidekick/memory/domain.py` builds the documents from plain dataclasses that hold only the fields
allowed to leave. The kinds are journal entries (title, summary, key points, raw text, linked contact names and
project titles), contacts, projects and tasks. Contact e-mail, phone and address, identifiers, and task status,
priority, due date, estimate and rank have no field, so they cannot reach a document. The pipeline version is part of
every fingerprint, so changing the document format re-sends everything. Four domains feed memory (journal,
contacts, projects, tasks); each can be switched off, memory can be paused, and a single record can be excluded.

### One writer: the reconcile pass

`backend/src/sidekick/memory/application/sync.py` is the only code that sends owner data to the provider and the
only code that deletes from it. The worker (`backend/src/sidekick/memory/worker.py`) runs a pass per owner under a
per-owner PostgreSQL advisory lock (`infrastructure/lock.py`), so two workers cannot work on one owner. State lives
in `memory_sources` rows (`pending`, `submitted`, `retained`, `failed`, `parked`) keyed by an opaque document id.
Sends are batched, delayed by a quiet period after a change, and held under daily count and character caps;
a batch is counted against the caps in its own transaction before it is sent. Deletions are never
delayed: a record that is permanently gone, replaced, excluded or in a switched-off domain loses its document first.
Owner-level `--wipe` and `--forget-owner` exist and need `--confirm`. Each full pass can end with an orphan-bank
sweep, which is off unless `SIDEKICK_MEMORY_ORPHAN_SWEEP_ENABLED` is set.

### Verified recall: the provider is not trusted

`recall_memory` returns a fact only after Postgres confirms it (`backend/src/sidekick/memory/application/recall.py`):
the document maps to a non-excluded `memory_sources` row of this owner, the source record still exists and is not in
the trash, the fact is of an allowed type (observations are refused), it still describes the current version of its
source, the owner's settings switch the kind on, and the caller holds the read scope of that kind. A changed
source is held back until its replacement is retained. The result is `ok`, `empty`, `unavailable`, `disabled` or
`paused`, so Claude can say honestly that memory is down and fall back to search.

### Scopes, identity and transport

Memory has no scope of its own. Reading status needs a domain read scope; switching a domain, pausing or excluding a
record needs the write scope of the domain; turning a domain off deletes derived documents and requires an explicit
`confirm`, otherwise the call reports what would be removed (`backend/src/sidekick/memory/application/settings.py`).
Settings use optimistic versions. The bank id sent to Hindsight is an HMAC of the owner id under a dedicated key, so
neither the URL nor the provider sees a Sidekick identifier. The adapter reaches only a private destination (the
Compose service name, `.internal` or `.local`, or loopback in local development; one shared rule in
`backend/src/sidekick/shared/private_endpoint.py`), does not follow redirects or trust proxy variables, bounds
timeouts and response size. Logs carry owner ids, counts and fixed categories only.

### The model provider is the owner's choice

Hindsight itself calls a language model that the owner configures (`deploy/selfhost/hindsight.env.example`). Derived
text goes to that provider; the threat model states this plainly. The reviewed pin of the Hindsight image is kept in
`contracts/reviewed/hindsight-memory/hindsight-memory-sources.yaml` and deployments use the digest, never a tag.

## Consequences

- Memory can be removed at any time without losing a record; recall degrades to "unavailable" and search still works.
- A wrong or stale fact cannot be shown for a deleted, excluded or since-edited record, at the cost of a Postgres
  round trip per recalled fact and a short window after each edit where the record's facts are withheld.
- Costs are bounded by the daily caps and the quiet period, so a large history is imported gradually.
- Changing what leaves Sidekick means editing `domain.py` and bumping the pipeline version, which is visible in review.
- A lost Hindsight volume, a restored dump or a rotated derivation key is detected after start: rows that say
  `retained` while the provider holds nothing go back to `pending` and are resent under the caps
  (`backend/src/sidekick/memory/application/lifecycle.py`).

## Rejected and deferred

- Treating Hindsight as a source of truth or letting Claude read it directly: rejected.
- Returning observations (facts synthesised by the service): refused in the adapter and again in recall.
- Sending contact e-mail, phone, address, identifiers or task state: not representable in the document types.
- A write-back from memory into records: there is none; the flow is one way, from Postgres to the provider.

## Evidence

- `backend/src/sidekick/memory/ports.py`
- `backend/src/sidekick/memory/domain.py`
- `backend/src/sidekick/memory/factory.py`
- `backend/src/sidekick/memory/adapters/hindsight.py`
- `backend/src/sidekick/memory/application/sync.py`
- `backend/src/sidekick/memory/application/recall.py`
- `backend/src/sidekick/memory/application/settings.py`
- `backend/src/sidekick/memory/application/lifecycle.py`
- `backend/src/sidekick/memory/worker.py`
- `backend/src/sidekick/shared/private_endpoint.py`
- `backend/tests/memory/test_recall.py`
- `backend/tests/memory/test_sync.py`
- `contracts/reviewed/hindsight-memory/hindsight-memory-sources.yaml`
