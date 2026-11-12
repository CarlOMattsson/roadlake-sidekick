# Verification logs

[Svenska](verification.sv.md)

<!-- description: What has been checked in each guide, how it was done, and what is not verified. -->

What has been checked in each guide, how it was done, and what is not verified.

For maintainers. These records say which parts of the user guides were read against the code, which commands were run,
what was followed from a clean clone, and what has not been verified. They are kept out of the guides on purpose: the
guides are instructions, and this is a test record.

The table of the latest checks is on [the maintainers page](README.md).

## Quickstart

Last checked on 2026-11-11.

- **Checked against the code (read, not run):** the ports in `deploy/compose.dev.yaml` (55440) and
  `deploy/compose.test.yaml` (55433), their service name `db`, the roles in `deploy/postgres-init.sql`, the
  setting names and the 32-character minimum in `backend/src/sidekick/shared/config/` and `.env.example`, the
  `/mcp/`, `/health/*` and `/companion/v1/` routes, the startup record fields, the npm script names in
  `frontend/package.json`, the build output path of `build:mcp-app`, and the `--full` option of the test suite.
- **Run, without side effects:** `uv run --project backend python -c 'import sidekick'`; `--help` of
  `sidekick-admin` (`create-user`, `create-token`), `python -m sidekick.mcp.stdio`, `sidekick.api.export_openapi`,
  `sidekick.mcp.export_contract`, `tools.seed` and `yoyo apply`; `docker compose -f deploy/compose.dev.yaml config -q`
  and the same for `deploy/compose.test.yaml`.
- **Followed from a fresh clone, 2026-11-11** (own compose project, database on another port as
  described in step 2, generated throw-away secrets): steps 1 to 4 and the build in step 6 as written (step 5, the seed and the example question, was checked against the code only). `uv sync`, `npm ci`, the database and
  `yoyo apply`, the backend with `/health/live` and `/health/ready`, `create-user` and `create-token`, an MCP
  `initialize` with the token, the stdio server answering `initialize`, and `build:mcp-app` (the checked-in output came
  back byte-identical). `ruff format --check` and `ruff check` passed. The test database on port 55433 and the
  backend suite were not run.
- **Not verified in this check:** the Claude Desktop stdio connection itself (only the server side), `pyright`, the
  browser checks and the test suites. CI runs the builds and tests on every pull request.

## Android app

Last checked on 2026-11-10.

- **Checked against the code (read, not run):** the SDK levels in `frontend/android/variables.gradle`, the JVM
  target and application ids in `frontend/android/app/build.gradle`, the Gradle version in the wrapper, the
  the debug-only cleartext hosts,
  `allowBackup`, the CI build steps (`build:mobile`, `cap sync android`, `./gradlew test` on Temurin 21), the
  Caddyfile's companion paths, the server settings and their defaults in `backend/src/sidekick/shared/config/`,
  and the pairing, renewal and test-notification limits in `backend/src/sidekick/companion/`.
- **Run, without side effects:** `--help` of `python -m sidekick.companion.cli` and of its `pair` and `grant`
  commands (options, scopes and the `app` preset match this guide).
- **Not verified in this check:** a Gradle build, an install on a phone or emulator, pairing against a running
  server, and push delivery through ntfy. CI builds the web bundle, runs the JVM unit tests and lint, builds the
  unsigned release APK, and runs an instrumented smoke test of pairing and the Capacitor bridge on an emulator. It
  never installs the app on a real phone, pairs it with a real server or delivers a push.

## Self-hosting

This guide is checked as ADR-004 asks of every guide; what was read and what was run is listed below.

- **Checked against the code (read, not run):** the service names, profiles, networks, volumes, env files and
  ports in `compose.yaml` (including the default-on `automation-worker`), the files this guide copies
  (`*.example`, `postgres-init.sh`, `ntfy-init.sh`), the setting names against `backend/src/sidekick/shared/config/`
  and `selfhost.env.example`, the options of `update.sh` and `restore.sh` and the worker list `update.sh` stops,
  the `sidekick-admin` and `sidekick-backup` commands, and the role grants the database restore repeats.
- **Run, without side effects:** `docker compose config -q` with a dummy `--env-file`, for the base stack and with
  all four profiles (`vps`, `memory`, `backup`, `push`), which also listed the services and images;
  `bash -n` on `update.sh` and `restore.sh`, and `sh -n ntfy-init.sh`; `--help` of `sidekick-admin`.
- **Drilled on real containers, 2026-11-11** (`tools/drill.sh all --local-images`, Docker 29 on Linux): install, an
  update with `update.sh --apply` (stand-in signature check, same schema: see [Release drill](release-drill.md)), the
  encrypted snapshot and its decryption, an encrypted database and Hindsight archive, deleting every volume, the
  restore (`pg_restore`, unpacking the Hindsight volume) and the refusal of a wrong or empty key.
- **Followed from a clean export of the publishing tree, 2026-11-11** (own compose project, generated
  throw-away secrets, home-machine profile, no tunnel): build, `create-user`, identity line, `up -d` (healthy, schema
  applied), the OAuth discovery documents, dynamic client registration, authorize and consent (redirects to GitHub),
  the token endpoint refusing an unknown code, the 401 challenge on `/mcp`, widening the scopes and recreating the API,
  `sidekick-backup keygen` and the backup profile, copying a backup out, `restore.sh` plan and `--apply` into a second
  owner, the from-source update, `update.sh` dry run and `--check`, the companion pairing code. The sign-in after
  GitHub, the token exchange, the MCP `initialize` and tool listing calls, `create_task` and `list_tasks` ran in the real image against
  the real database with GitHub answered by a stand-in (a real GitHub account cannot be used from a test).
- **Fresh clone under `umask 077`, 2026-11-11:** an export of the publishing tree was cloned and this guide followed on
  Docker 29 (Compose 2.40) with a strict umask. It found two failures that an earlier run under the default umask
  had not shown: PostgreSQL could not read the mounted `postgres-init.sh`, and the image held code the unprivileged
  user could not read. The run went through after those were worked around by hand: build, `create-user`, identity
  line, `up -d` (healthy), the discovery documents, `401` on `/mcp`. The fixes now in the repository replace the manual
  steps (tests cover them). The run was repeated afterwards with them, from a fresh clone under `umask 077`: build,
  `create-user` while the GitHub client id, secret and identity line still held their placeholders, the identity line,
  `up -d` (healthy), the discovery document, `readiness` printing `ok`, `401` on `/mcp/`. No manual step was needed.
- **Not verified in this check:** a real GitHub sign-in and a real Claude connection, the `vps` profile (Caddy, TLS),
  an update across a real schema change, and the real cosign signature check against a released image.

## Work package

KNOWN (2026-11-11 follow-up): the umask handling, cache flag, failed-initialization diagnosis and optional
Claude merge are checked with a stand-in Docker, temporary files and a local model-server fixture. OPEN: these
changes have not been exercised in a real Ubuntu installation with umask 077 or in a real Claude Desktop session;
no containers were started for this follow-up.

Checked on 2026-11-10. Verified:

- `tools/work.sh` parses (`bash -n`) and is checked by shellcheck in CI (`--severity=warning`); `backend/tests/selfhost/work_package/` runs the
  commands `setup`, `init`, `start`, `stop`, `backup`, `update`, `restore` and `autostart` (not `status`) on Linux against a
  stand-in `docker` that records the calls and fails on demand. For `restore` that covers the dry run, refusing a missing
  or partial set, the typed confirmation, the order of the steps with `--apply`, putting both back when a step fails
  or is interrupted (also right after the rename), and leaving everything stopped when putting back fails; for the
  backups themselves that the files are encrypted (no plain dump or archive on disk), the key is created private and
  kept out of the backup directory, a backup that cannot be read back is not kept, a missing, wrong or changed key
  file or backup file stops `backup` and `restore` before anything changes, and a backup followed by a restore hands
  Postgres and the volume exactly what was backed up (the stand-in `docker` runs the real encryption code); for all
  changing commands the shared lock (flock and the mkdir fallback) and stopping before any change when the pause
  of the writers fails or cannot be confirmed.
- When Docker is installed, the same tests let Docker Compose itself merge `deploy/selfhost/compose.yaml` and
  `deploy/work/compose.yaml` and check the result (pinned images, the only published port on loopback, the only route out
  through the gateway).
- The database statements `restore` runs (rename, create with grants, load, ownership repair) were run by hand against a scratch Postgres set up
  with the package's role bootstrap; the result had the same owners and grants as the original and the migrator could
  still change its tables.
- The drill (`bash tools/drill.sh work --local-images`, see the release drill in
  [release drill](release-drill.md)) ran the package on real containers on
  Linux (Docker 29): `init`, `start`, `backup` (database and Hindsight, encrypted and read back), an update
  that swaps the api image and recreates the stack, deleting every volume, `restore --apply` (database, owner and the
  Hindsight volume) and the refusal of a wrong or missing key.

Not verified:

- Limits of that drill: the Hindsight check is a marker file in the
  volume, not a memory bank read back through Hindsight; `update` was drilled as an image swap, not the `git pull`
  and build route; both images carry the same schema; the model server is a dummy address, so nothing calls a model.
  Drill a backup and a restore once on your own machine before you rely on them.
- macOS (Docker Desktop, launchd, keychain) has never been run. Other Linux distributions than Ubuntu have not been
  tried.
