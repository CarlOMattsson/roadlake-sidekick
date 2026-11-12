#!/bin/sh
# First-start role bootstrap for the self-hosted Postgres.
#
# The postgres image runs every file in /docker-entrypoint-initdb.d once, on an empty data volume.
# This is the self-hosted counterpart of deploy/postgres-init.test-only.sql. That file is for the disposable
# test database and sets each password to the role name, which a real installation must never do.
# Here the passwords come from db.env, so nothing secret is written to the repository.
set -eu

: "${SIDEKICK_DB_APP_PASSWORD:?set SIDEKICK_DB_APP_PASSWORD in db.env}"
: "${SIDEKICK_DB_MIGRATOR_PASSWORD:?set SIDEKICK_DB_MIGRATOR_PASSWORD in db.env}"

# Plain statements with psql variables, not a DO block: psql does not substitute :'name' inside
# dollar-quoted bodies. The heredoc is quoted, so the shell does not expand anything in the SQL.
psql -v ON_ERROR_STOP=1 \
  -v app_password="$SIDEKICK_DB_APP_PASSWORD" \
  -v migrator_password="$SIDEKICK_DB_MIGRATOR_PASSWORD" \
  --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
CREATE ROLE sidekick_owner NOLOGIN;
CREATE ROLE sidekick_migrator LOGIN NOINHERIT PASSWORD :'migrator_password';
CREATE ROLE sidekick_app LOGIN NOINHERIT PASSWORD :'app_password';
GRANT sidekick_owner TO sidekick_migrator;

DO $do$
DECLARE
  database_name text := current_database();
BEGIN
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO sidekick_migrator, sidekick_app', database_name);
  EXECUTE format('GRANT CREATE ON DATABASE %I TO sidekick_owner', database_name);
END
$do$;

GRANT CREATE, USAGE ON SCHEMA public TO sidekick_migrator;
SQL
