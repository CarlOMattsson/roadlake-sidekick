# The 0.1.0 schema baseline

[Svenska](schema-baseline.sv.md)

<!-- description: Sidekick 0.1.0 creates the database from a single baseline. What that means for new installations, and why older ones are not upgraded in place. -->

Sidekick 0.1.0 creates the database from a single baseline. This page explains what that means for new installations and why older installations are not upgraded in place.

## What the baseline is

The `migrations/` directory starts with `100_schema_baseline_0_1_0.py`. It creates the whole schema on an empty
database: tables, constraints, indexes, grants and default privileges, in the schema, roles and database names of
Sidekick (`sidekick`, `sidekick_owner`, `sidekick_migrator`, `sidekick_app`). New migrations are numbered from
`106_`, because `101` to `105` are taken by the folded chain in the migration log of older databases.

- It creates the schema on an empty database. On a database that already has a `sidekick` schema it creates nothing:
  it either recognises or upgrades the database (see the next section) or refuses with a message and changes nothing.
- It cannot be rolled back: that would drop every owner table. The way back is a backup.
- The chain it replaced is not shipped.
- The tables of features that were removed before 0.1.0 (the earlier built-in chat, live voice calls, the agent
  runtime, the assistant autonomy setting, and the preferences of the retired desktop app) are not created (decisions
  D-082 and D-084).
- The leftovers of the removed browser sign-in (the `sessions` table and the `users.password_hash` column) are not
  created either.

## The folded development chain

Before the first release the schema was built by `100_baseline_0_1_0.py` followed by five migrations: `101` (two
indexes on `tasks`), `102` (the event ledger and the activity projection became append-only for the app role), `103`
(delete grants on `domains` and `processes`), `104` (`audit_events.source`) and `105_drop_sessions_and_password_hash`
(the sign-in leftovers). They were folded into this baseline, so it builds the schema they ended in; a test pins that
to the checked-in fingerprint. The old files are not shipped, but one installation, the owner's, had applied them.

The baseline decides from the database's own bookkeeping (`public._yoyo_migration`):

| Database | What the baseline does |
| --- | --- |
| No `sidekick` schema | Creates the schema. |
| `sidekick` schema and `105_drop_sessions_and_password_hash` applied | Nothing: the schema is already this one. yoyo records the baseline as applied; no table, row or grant is touched. |
| `sidekick` schema and a prefix of the chain applied (`100_baseline_0_1_0`, or it and `101` up to `104`, in order) | Runs exactly the statements of the missing steps, verbatim from the folded migrations, in the one transaction, then the same checks as above; any failure rolls everything back. Only the baseline is recorded; the ids already there stay. |
| Anything else: a gap in the chain, an unknown id, or no id at all | Refuses with the applied ids and what to do, changes nothing and records nothing. |

A database that stood on `102` when the chain was folded receives the statements of `103`, `104` and
`105` (delete grants, `audit_events.source`, the drop of `sessions` and `users.password_hash`, which deletes any
leftover sessions and password hashes), and keeps all other data. A database that is refused should be rebuilt from
an empty database with a restore through `sidekick-backup import`. Exports and backups stamped with any of the
old ids are still accepted by the import.

## Migration 106: the retired automation tables

`106_drop_retired_automation_tables.py` drops `assistant_automation_policies`, `assistant_automation_control`,
`assistant_automation_runs` and `assistant_task_review_findings`, which the baseline still creates (installations have
already applied it, so it is not edited). Nothing writes or reads them any more, so they are empty. The migration
refuses, with the table named and nothing changed, if one of them holds a row, and it cannot be rolled back. The ledger
column `domain_events.automation_run_id` and the ledger type `automation_run` stay. The owner export dropped the four
collections too (format 5); a format 4 export is still read, and is refused if one of those collections is not empty.

## Migration 107: tags on Contacts and Journal entries

`107_contact_and_journal_entry_tags.py` is an additive (expand) migration. It creates the link tables `contact_tags` and
`journal_entry_tags`, shaped like `task_tags`: one row per tag and record, the tag and the record both owned by the same
owner (composite foreign keys), removed with either. The tag vocabulary `work_tags` is shared by every kind of record.
Rolling it back drops only the two link tables. The owner export carries them as two new collections (format 6); a
format 5 export has none and restores without tags.

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
(the baseline `100_schema_baseline_0_1_0.py` and the numbered migrations after it, in order), create the owner, import. There is nothing to mark or repair by hand.
