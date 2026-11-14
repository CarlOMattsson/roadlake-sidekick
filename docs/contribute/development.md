# Development guide

[Svenska](development.sv.md)

How to build, check and release Roadlake Sidekick locally. Pull requests are welcome but handled in a limited way (see CONTRIBUTING.md); these are the checks the maintainers apply to every change.

## Development environment

Python 3.13 with `uv`, Node.js 22 with npm 10, and Docker (for PostgreSQL). The full step-by-step setup is in
[Run Sidekick locally as a developer](../start/first-contribution.md). Briefly, from the repository root:

```bash
[ -f .env ] || cp .env.example .env
uv sync --project backend --all-groups
npm --prefix frontend ci
docker compose -f deploy/compose.dev.yaml up -d db
```

Never commit `.env` or any file with real secrets.

## Checks and tests

```bash
# Backend style and types
(cd backend && uv run ruff format --check . && uv run ruff check --no-cache . && uv run pyright)

# Frontend style, types and unit tests
npm --prefix frontend run format:check
npm --prefix frontend run check            # eslint + tsc -b + vitest

# Backend tests (need the disposable PostgreSQL on port 55433 below, "Run the tests")
(cd backend && uv run pytest --full)
# Repository rules only (source, docs and config scans; the release CI runs them as their own step, no database)
(cd backend && uv run pytest --full -m policy)

# MCP App browser tests (Playwright with Chromium: `npx playwright install chromium` in frontend/)
npm --prefix frontend run build:mcp-app
npm --prefix frontend run test:mcp-app
(cd frontend && npx playwright test --config playwright.mobile-audit.config.ts)
```

To run the local suite that should be green before a push in one go, use `tools/check-all.sh`. It runs the backend
tests in parallel on a disposable test database slot of your own (`--slot`, 1 to 20; see `tools/test-db-pool.md`),
with the CI coverage gate (90 %), then ruff and pyright, the version and migration policy checks, shellcheck, gitleaks,
the frontend checks (the mobile bundle is built first, because `mobile-csp.test.ts` reads it), the MCP App build and
browser tests, and the Android Gradle build. It touches no database other than the test container on port 55433. Each part has a `--skip-...` flag, and
`--dry-run` prints the commands without running them:

```bash
bash tools/check-all.sh --slot 3                  # everything
bash tools/check-all.sh --slot 3 --skip-android   # without the Android build
bash tools/check-all.sh --slot 3 --release        # plus the rest of the release gate
bash tools/check-all.sh --help                    # all options
```

shellcheck and gitleaks must be installed locally. When one is missing its stage prints `SKIPPED: <tool> missing
(install: ...)` and is reported as SKIPPED in the summary, never as ok; `--strict` turns that into a failure.

By default it does not run the Playwright mobile audit, the frontend coverage threshold, the dependency audits or the
contract diff. Add `--release` to run those too, in the order of the release CI (see
[the release checklist](../maintainers/release.md)); the dependency audit needs the network and is reported as `SKIPPED`
when it is not reachable. The emulator test, the image build and the Compose smoke test are left to the release CI, so
run the ones below that match what you changed.

CI does not run on pull requests, merges or pushes; it is a gate of every release (and can be started by hand). So
the checks are yours to run before you push: install the hooks with `pre-commit install --hook-type pre-commit --hook-type
pre-push`, and run the commands that match what you changed. The release CI runs more than the commands above:

```bash
# Contract snapshots: regenerate (see "Code style") and check that `git diff --exit-code -- contracts` is clean.

# Migrations: a new file under migrations/ may only contain expand statements unless it is marked
# `# migration-class: contract` (see tools/check-migration-policy.py)
python3 tools/check-migration-policy.py --base origin/main

# Android shell: JVM unit tests (needs JDK 21 and Node.js 22; no emulator, no signing)
npm --prefix frontend run build:mobile
(cd frontend && npx cap sync android)
(cd frontend/android && ./gradlew test)

# Shell scripts (CI also checks extensionless files that start with a sh or bash shebang)
git ls-files -z '*.sh' | xargs -0 shellcheck --severity=warning

# Dependencies: pip-audit and `npm audit --audit-level=high --omit=dev`, OSV-Scanner on the Gradle lockfiles (.github/workflows/audit.yml)
bash .github/audit/pip-audit.sh
bash .github/audit/osv-gradle.sh
```

CI also scans for committed secrets (gitleaks) and builds the API image (`backend/Dockerfile`). Several jobs
run only when the files they cover changed.

The backend tests clear the database they use. Run them only against the disposable database described under
"Run the tests" below, never one that holds real data.

### Generated files that are checked in

`backend/src/sidekick/mcp/apps/sidekick.html` (the single-file MCP App) and `contracts/mcp-tools.generated.json`
(the tool contract) are build output, but they are committed on purpose: the backend serves the HTML as-is, so a fresh
clone or a Docker image runs without a Node toolchain, and the committed contract makes every change to a tool visible
in review. Rebuild them after changing the MCP App sources or the tool definitions, and commit the result:

```bash
npm --prefix frontend run build:mcp-app
uv run --project backend python -m sidekick.mcp.export_contract --output contracts/mcp-tools.generated.json
```

`tools/check-all.sh` rebuilds the MCP App HTML and fails when the committed bundle differs. With `--release` it also
compares the contract files; regenerate the tool contract with the second command whenever you change a tool.

### Android dependency locks

Every Gradle configuration of the Android shell is locked (`dependencyLocking` in `frontend/android/build.gradle`), and the
lock files are `frontend/android/gradle/locks/<project>.lockfile`. After a dependency change, rewrite them by running the
tasks CI runs, so that every configuration in use lands in a lock:

```bash
cd frontend/android
./gradlew :app:ktlintCheck :app:testDebugUnitTest :app:lintDebug :app:assembleRelease :app:assembleDebugAndroidTest --write-locks
```

Review the diff of `gradle/locks/` as a dependency change. A dependency missing from a lock makes the build fail instead
of silently resolving a newer one.

## Website

The public website is an Astro Starlight project in `website/`. It renders the documents of this repository
(listed in `website/content-map.mjs`) in Swedish and English next to a few hand-written pages, and builds to
static files in `website/dist/`. It needs Node.js 22.23.4 or newer (`website/.node-version`).

```bash
npm --prefix website ci --ignore-scripts   # once; the lockfile is exact, never use plain npm install
npm --prefix website test                  # unit tests of the sync script
npm --prefix website run build             # sync the documents, then build into website/dist/
npm --prefix website run preview           # preview at http://localhost:4321
npm --prefix website run check             # links, accessibility, prices, privacy and the page budget
```

`SITE_URL` and `SITE_BASE` set the address the site is built for (default `https://roadlake.com`, no base path).
Pages for the documents are generated from the sources by `website/scripts/sync-docs.mjs` and are not committed.
To change which documents appear, edit `website/content-map.mjs`, not the script.

Checks that guard the site:

- `backend/tests/policy/test_docs_language_parity.py`: every published document has an English and a Swedish
  twin with the same structure, and the hand-written pages and interface strings match in both languages.
- `tools/check-all.sh`: the `website` stage runs the tests, the build and the site checks; it is skipped (and a
  failure with `--strict`) when `website/node_modules` is missing. `--skip-website` leaves it out.
- `.github/workflows/pages.yml`: builds, checks and publishes the site when a release is published or when run by
  hand. It uses no secrets.

## Code style

- Python: `ruff format` and `ruff check` (line length and rules are in `backend/pyproject.toml`), typed with
  `pyright`.
- TypeScript/React: `eslint` and `prettier`, run as `npm --prefix frontend run lint` and `format:check`.
- Follow the neighbouring code. No copied code, no dead code, no new dependency without a reason.
- Add tests with the change, including authorization and redaction tests where they apply. Do not weaken or
  remove a meaningful test to make a run green.
- After an API or MCP change, regenerate the committed artefacts instead of editing them by hand:

  ```bash
  uv run --project backend python -m sidekick.api.export_openapi --output contracts/openapi.generated.json
  uv run --project backend python -m sidekick.mcp.export_contract --output contracts/mcp-tools.generated.json
  uv run --project backend python -m sidekick.api.export_companion_contract --output contracts/companion-api.generated.json
  npm --prefix frontend run build:mcp-app
  ```

- Do not edit a migration that has already been applied; add a new numbered file under `migrations/`. The schema
  starts from the 0.1.0 baseline (`100_schema_baseline_0_1_0.py`), and new files take the next number after the highest one there. Numbers `101` to `105` are never used: older databases
  already carry them in their migration log (`backend/tests/policy/test_migration_numbering.py`). Moving data between
  0.1.0 installations (there is no import from earlier ones) is described in [the baseline runbook](../explanation/schema-baseline.md).

## Releasing

Tags, versions and the release steps are in [Release a version](../maintainers/release.md).

## Run the tests

Static checks and frontend unit tests:

```bash
(cd backend && uv run ruff format --check . && uv run ruff check --no-cache . && uv run pyright)
npm --prefix frontend run format:check
npm --prefix frontend run check            # lint + typecheck + vitest
npm --prefix frontend run build
```

The backend suite uses a **disposable** PostgreSQL on port **55433** and refuses any other database,
because it clears the data it finds. Never point it at a database that holds real data.

```bash
docker compose -f deploy/compose.test.yaml up -d --wait db

uv run --project backend yoyo apply --batch \
  --database postgresql+psycopg://sidekick_migrator:sidekick_migrator@127.0.0.1:55433/sidekick_test migrations

(cd backend && uv run pytest --full)
```

The suite selects its database itself and ignores `.env` and ordinary `SIDEKICK_*` runtime settings; it keeps
and validates only explicit test-database settings (`SIDEKICK_TEST_DATABASE_URL` and the other `SIDEKICK_TEST_*`
variables, which must name a disposable `sidekick_test` database on a loopback test port, 55433 by default).
With `--full` (and with `CI=true`) a database-dependent test fails when the database cannot be reached; only a
quick run without `--full` skips such tests, with the reason printed, and a run with many skips is not a full
verification. `docker compose -f deploy/compose.test.yaml down` removes the database
again. To run several suites at once, or in parallel with `-n`, give each its own database; see
[tools/test-db-pool.md](../../tools/test-db-pool.md).

Browser checks load the built MCP App in a simulated host:

```bash
(cd frontend && npx playwright install chromium)
npm --prefix frontend run build:mcp-app
npm --prefix frontend run test:mcp-app
npm --prefix frontend run test:mobile-audit
```

A small separate suite runs the same built app against a real server, so the contract between the app and the
server's tools is exercised for real: the host is still simulated, but every tool call goes to a Sidekick server
(FastAPI and FastMCP on a free loopback port) started by the suite on a test database slot, with a user and a token
made for that run only. It covers creating and finishing a task in the Agenda, adding and checking off a step, a
task changed elsewhere (the conflict and the reload), the tag filter and setting a tag, a contact's nickname and tag,
writing a journal note and the shopping list. It needs the backend environment and the test database
([Test database pool](../../tools/test-db-pool.md)); the suite empties the database it is given, so use a slot of your own:

```bash
bash tools/test-db-pool.sh create K
pool_env=$(bash tools/test-db-pool.sh env K) && eval "$pool_env"
npm --prefix frontend run test:real-backend
```

`E2E_BACKEND_PYTHON` names the Python of the backend environment when it is not `backend/.venv/bin/python`. The
suite is not part of CI.

Keep the generated contract snapshots in sync after an API or MCP change:

```bash
uv run --project backend python -m sidekick.api.export_openapi --output contracts/openapi.generated.json
uv run --project backend python -m sidekick.mcp.export_contract --output contracts/mcp-tools.generated.json
uv run --project backend python -m sidekick.mcp.export_tool_reference
uv run --project backend python -m sidekick.export_reference
uv run --project backend python -m sidekick.api.export_companion_contract --output contracts/companion-api.generated.json
```
