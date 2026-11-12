# Test database pool

**Purpose:** Run database-backed pytest in several terminals, or several parallel xdist workers, at the
same time without them wiping each other's data. Each runner gets its own database, `sidekick_test_K`,
inside the same test container (`deploy/compose.test.yaml`, `127.0.0.1:55433`). `sidekick_test` without a
suffix is still the default database used by CI and single runs; the pool does not touch it.

## Commands

Run from the repository root:

- `bash tools/test-db-pool.sh create N`: creates `sidekick_test_1..N` with the same roles, grants and
  owner (`postgres`) as `sidekick_test`. Idempotent: existing slots are left alone.
- `bash tools/test-db-pool.sh workers K N`: creates `sidekick_test_K_w0..w(N-1)` for xdist workers,
  idempotent, with the same owner and grants as the slots. `K=0` is the base `sidekick_test` and gives
  `sidekick_test_w0..w(N-1)`. For K>0 the base must exist (`create K` first). It does not migrate;
  see "Known limitations".
- `bash tools/test-db-pool.sh list`: lists the pool and worker databases that exist.
- `bash tools/test-db-pool.sh drop N`: drops `sidekick_test_N`. Fails if the slot is in use by someone
  else; there is no `FORCE`.
- `bash tools/test-db-pool.sh env K`: prints `export` lines for slot K. Fails if the slot does not
  exist, so a test run cannot silently skip against a missing database.

The script refuses to run if `SIDEKICK_TEST_DB_BIND` points at a port other than 55433 or if the `db`
service does not publish `127.0.0.1:55433`. Slots are `1..20`. The name is always
`sidekick_test_<digit>`, so the script cannot affect any other database.

## Using a slot

Pick a slot K that no other run is using, then load its settings before running pytest:

```bash
bash tools/test-db-pool.sh create K
pool_env=$(bash tools/test-db-pool.sh env K) && eval "$pool_env"
```

Do not write `eval "$(bash tools/test-db-pool.sh env K)"`: `eval` of an empty string succeeds, so a failed
`env K` (for example a slot that does not exist) would go unnoticed and pytest would fall back to the default
`sidekick_test` database. Assigning first makes the shell check the exit code of `env K`. The export lines set
`SIDEKICK_ENVIRONMENT=test` and the three URLs (app, migrator, admin) for `sidekick_test_K`. Do not point two
concurrent runs at the same slot, because every pytest run clears its database.

## Running the whole backend suite in parallel

The full suite takes about 25 minutes sequentially but about 5.4 minutes with `-n 10` (measured on a
20-core machine). Run it in parallel with a slot K of your own:

```bash
bash tools/test-db-pool.sh create K && bash tools/test-db-pool.sh workers K 10
pool_env=$(bash tools/test-db-pool.sh env K) && eval "$pool_env" && \
  uv run --project backend python -m pytest backend/tests --full -n 10 --dist loadgroup --no-header \
    -p no:cacheprovider -rfE -W ignore
```

Run sequentially (without `-n`) only when debugging a single failure. Each parallel run uses 10 workers, so on
a smaller machine use fewer (`workers K N` and `-n N`).

## Known limitations

- `backend/tests/db.py` accepts exactly `sidekick_test(_[1-9][0-9]?)?(_w[0-9]{1,2})?` and no other name.
- Connection validation (`backend/tests/db_guard.py`) runs once for the test, migrator, admin and worker
  URLs before any connection is opened, and again as a SQLAlchemy `do_connect` hook. The host must be
  loopback (`127.0.0.1`, `localhost`, `::1`), the port must be written in the URL (an omitted port, i.e.
  the default 5432, is refused) and allowed, and the URL may not carry query parameters. Port 55433 (also
  used by CI) is allowed; further test ports can only be added with `SIDEKICK_TEST_EXTRA_ALLOWED_PORTS`
  (for example `55440` for a smoke run against `deploy/compose.dev.yaml`). The ports reserved for
  non-test databases (`RESERVED_PORTS` in `backend/tests/db_guard.py`, extendable with `SIDEKICK_RESERVED_PORTS`, never reducible) are always refused, even if listed there.
- The same module validates the effective connection parameters at the driver boundary (`psycopg`,
  which yoyo also uses, `asyncpg` if installed, and SQLAlchemy `do_connect`, so `creator=` is
  covered too): `hostaddr`, `service`, `servicefile`, `passfile` and `options` are refused, and the libpq
  variables `PGHOST`, `PGHOSTADDR`, `PGPORT`, `PGDATABASE`, `PGSERVICE`, `PGSERVICEFILE`, `PGSYSCONFDIR`
  and `PGPASSFILE` are removed at session start and refused if set later. Tests that spawn child
  processes build their environment with `child_process_environment()` and, for `--env-file`, check the
  file with `validate_child_env_file()`. The guard also sits on the lowest dials (`psycopg.generators.connect`,
  `psycopg.pq.PGconn.connect`/`connect_start`); only there is a loopback `hostaddr`
  accepted, because psycopg resolves `host` into one itself.
- Workers per base: `sidekick_test_K` gives `sidekick_test_K_wN`, and `sidekick_test` gives
  `sidekick_test_wN`. A run on slot K therefore only uses `sidekick_test_K_w*` and cannot clear other
  slots. Under `-n` the suite refuses a URL that already points at a worker database.
- In some restricted shells `eval` is denied; set the variables that `env K` prints explicitly on the
  command line instead.
- Migrations are not applied by `create` or `workers`. At start the test suite checks that the database
  is migrated to the latest file in `migrations/` (`public._yoyo_migration`). If it is not, the schema
  is rebuilt automatically, so an old slot no longer causes silent "Request failed" errors. Manually:
  `uv run --project backend yoyo apply --batch --database <migrator URL for the slot> migrations`.
  The migrator and admin URLs use the `postgresql+psycopg://` scheme (psycopg 3 is the only driver);
  the suite rewrites an older exported `postgresql://` to it at start.
