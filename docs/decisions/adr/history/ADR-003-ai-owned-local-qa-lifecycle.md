# ADR-003: Isolate the persistent browser QA environment (superseded)

- Status: Superseded by D-082 (2026-11-10). The browser interface this ADR governed was removed.
  What remains in force is the isolation principle, now carried by the disposable per-run test
  databases (`tools/test-db-pool.md`).
- Date: 2026-08-23
- Owners: Sidekick application maintainers

> This ADR is kept as history, per the lifecycle in ADR-004. Nothing below describes a current
> environment: the persistent QA instance, its browser identity and its visible-flow-only data rule
> no longer exist. The user-facing surfaces today are the MCP Apps and the Android app (ADR-005).

## Context

Visible browser QA of the former web interface needed durable, human-like state so navigation,
empty states, transitions, dialogs, confirmations, errors and cross-feature effects could be
inspected over time. It must not mutate a developer's local data, the automated-test database, or
production.

## Decision (as accepted)

Browser QA ran in a dedicated, isolated test environment, never against a developer's working data,
the automated-test database, or production. The environment had its own database, volume and port,
was started, stopped and migrated through explicit commands, and stopping it preserved its data so
state could accumulate across visible journeys.

The environment was operated through one dedicated browser identity. Data was created or changed one
record at a time through visible application flows; seeding, bulk fixtures, database resets and
ad-hoc SQL were not used for browser coverage. CI and automated tests used separate databases.

## Consequences (as accepted)

- QA state was realistic and cumulative instead of an artificial fixture snapshot.
- A separate port, volume, identity and explicit commands made accidental cross-environment use
  easier to detect.

## What replaces it

- D-082 removed the web interface and with it this QA environment.
- End-to-end and integration verification uses isolated, disposable databases
  (`tools/test-db-pool.md`, `deploy/compose.test.yaml`), never a developer's data or production.
