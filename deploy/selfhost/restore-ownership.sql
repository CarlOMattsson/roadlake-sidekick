-- Ownership repair after restoring a `pg_dump --no-owner` dump of the sidekick database.
--
-- The work-laptop backup (`tools/work.sh backup`, the sidekick-*.sql.enc set) is made with
-- `pg_dump --no-owner` and leaves out who owns what. Restored by the postgres superuser, every object
-- then belongs to `postgres`, and the migrator role could no longer alter the tables in a later
-- migration. This file gives each object back the owner the migrations give it:
--   schema sidekick, its tables, views and functions  -> sidekick_owner
--   the yoyo bookkeeping tables in schema public      -> sidekick_migrator
-- Grants (sidekick_app and sidekick_migrator) are part of the dump and need no repair.
--
-- Used by: `tools/work.sh restore --apply` (restore_database), which runs it right after the dump
-- has been read into the new database. Not used for the update snapshot: `deploy/selfhost/update.sh`
-- writes `pg_dump -Fc` without --no-owner, so that dump already carries its owners.
--
-- Run it once, as the postgres superuser, in the restored database and nowhere else:
--   psql -U postgres -d sidekick -v ON_ERROR_STOP=1 -f restore-ownership.sql
\set ON_ERROR_STOP on

BEGIN;

ALTER SCHEMA sidekick OWNER TO sidekick_owner;

DO $repair$
DECLARE
  item record;
BEGIN
  FOR item IN
    SELECT c.oid::regclass AS name
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'sidekick' AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
  LOOP
    EXECUTE format('ALTER TABLE %s OWNER TO sidekick_owner', item.name);
  END LOOP;

  FOR item IN
    SELECT p.oid::regprocedure AS name
    FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'sidekick' AND p.prokind IN ('f', 'p')
  LOOP
    EXECUTE format('ALTER ROUTINE %s OWNER TO sidekick_owner', item.name);
  END LOOP;

  FOR item IN
    SELECT c.oid::regclass AS name
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
      AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = c.oid AND d.deptype = 'e')
  LOOP
    EXECUTE format('ALTER TABLE %s OWNER TO sidekick_migrator', item.name);
  END LOOP;
END
$repair$;

COMMIT;
