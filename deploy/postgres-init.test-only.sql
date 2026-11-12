-- TEST AND DEVELOPMENT ONLY. Each role's password equals its name; never run this against a real instance.
-- Self-hosted installs bootstrap roles with deploy/selfhost/postgres-init.sh, using generated passwords.
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sidekick_owner') THEN
    CREATE ROLE sidekick_owner NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sidekick_migrator') THEN
    CREATE ROLE sidekick_migrator LOGIN PASSWORD 'sidekick_migrator' NOINHERIT;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sidekick_app') THEN
    CREATE ROLE sidekick_app LOGIN PASSWORD 'sidekick_app' NOINHERIT;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sidekick_hindsight_migrator') THEN
    CREATE ROLE sidekick_hindsight_migrator LOGIN PASSWORD 'sidekick_hindsight_migrator' NOINHERIT;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sidekick_hindsight_app') THEN
    CREATE ROLE sidekick_hindsight_app LOGIN PASSWORD 'sidekick_hindsight_app' NOINHERIT;
  END IF;
END $$;
GRANT sidekick_owner TO sidekick_migrator;
DO $do$
DECLARE
  database_name text := current_database();
BEGIN
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO sidekick_migrator, sidekick_app, sidekick_hindsight_migrator, sidekick_hindsight_app', database_name);
  EXECUTE format('GRANT CREATE ON DATABASE %I TO sidekick_owner, sidekick_hindsight_migrator', database_name);
END
$do$;
GRANT CREATE, USAGE ON SCHEMA public TO sidekick_migrator;
