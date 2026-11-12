# The 0.1.0 schema baseline

[Svenska](schema-baseline.sv.md)

<!-- description: Sidekick 0.1.0 creates the database from a single baseline. This page explains what that means for new installations and why older installations are not upgraded in place. -->

Sidekick 0.1.0 creates the database from a single baseline. This page explains what that means for new installations and why older installations are not upgraded in place.

## What the baseline is

The `migrations/` directory starts with `100_baseline_0_1_0.py`. It creates the whole schema on an empty
database: tables, constraints, indexes, grants and default privileges, in the schema, roles and database names of
Sidekick (`sidekick`, `sidekick_owner`, `sidekick_migrator`, `sidekick_app`). New migrations continue from
`101_`. The first one after it is `101_tasks_project_and_due_indexes.py`, which only adds two indexes on `tasks`.

- It only creates. On a database that already has the schema it fails at the first statement and changes nothing.
- It cannot be rolled back: that would drop every owner table. The way back is a backup.
- The chain it replaced is not shipped.
- The tables of features that were removed before 0.1.0 (the earlier built-in chat, live voice calls, the agent
  runtime, the assistant autonomy setting, and the preferences of the retired desktop app) are not created (decisions
  D-082 and D-084).
- Two leftovers of the removed browser sign-in are the exception: the baseline still creates the `sessions` table and
  the `users.password_hash` column. Migration `105_drop_sessions_and_password_hash.py` drops both, because
  installations may already have applied the baseline, which is therefore never edited after the fact.

## Changing the schema: the checked-in fingerprint

`backend/tests/fixtures/baseline-catalogue.json` is the schema fingerprint: after `yoyo apply` on an empty database,
the sorted `pg_catalog` rows for tables, columns (type, nullability, default), constraints, indexes, functions,
triggers, policies, owners, grants and default privileges, without OIDs. The test
`test_a_fresh_install_matches_the_checked_in_schema_fingerprint` (`backend/tests/integration/test_migration_baseline.py`)
fails with a diff of the differing rows when a migration changes the schema without the fingerprint. A migration that
changes the schema therefore commits the regenerated file with it:

```
eval "$(bash tools/test-db-pool.sh env N)"
SIDEKICK_UPDATE_BASELINE_SNAPSHOT=1 backend/.venv/bin/python -m pytest backend/tests/integration/test_migration_baseline.py \
  -k checked_in_schema_fingerprint --full
git diff backend/tests/fixtures/baseline-catalogue.json   # review: it must show exactly the intended change
```

Everything the MCP apps and the Android app use is in the baseline: tasks, projects, domains, steps, the journal,
contacts, shopping lists, memory bookkeeping, the activity log and automation, push, the license and the tokens.

## Other deployments

A deployment with its own scripts does the same: start from an empty database, run `yoyo apply` with the migrator role
(the baseline `100_baseline_0_1_0.py` and the numbered migrations after it, in order), create the owner, import. There is nothing to mark or repair by hand.
