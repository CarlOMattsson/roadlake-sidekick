# Guide for coding agents

Roadlake Sidekick is a self-hosted, MCP-first operating system for one person for work and tasks, journal, shopping and
contacts. A modular Python monolith (FastAPI + FastMCP + PostgreSQL) serves MCP Apps rooms (React) in Claude
and a companion Android app. See [README.md](README.md) and [QUICKSTART.md](QUICKSTART.md).

## Boundaries

- Read the whole file before you edit it. Do not guess: if something is unclear, say so in your report.
- **Never read, print or commit `.env` files or any populated secret file.** Use the `*.example` templates.
- Never put secrets, tokens, user text, titles, prompts or request/response bodies in logs, traces, test
  output or error messages. Logs are structured, sanitised and carry a correlation id.
- Do not run tests against a database you do not own. The test suite only accepts disposable `sidekick_test`
  databases on a loopback port, 55433 by default (the guard in `backend/tests/db_guard.py` refuses everything
  else), and clears them. Never point it at a database with real data.
- Do not edit generated files by hand: `backend/src/sidekick/mcp/apps/sidekick.html`,
  `contracts/*.generated.json`. Regenerate them (commands below).
- Do not edit migrations that have been applied; add a new numbered file under `migrations/`. The chain starts at
  the 0.1.0 baseline (`100_schema_baseline_0_1_0.py`); new files take the next number after the highest one there,
  never `101` to `105` (`backend/tests/policy/test_migration_numbering.py`).

## Setting up Sidekick for a user

If you run the local setup (`bash tools/work.sh setup`) on behalf of a person, ask them first which app language they want (propose Swedish) and which rooms they want (propose all except shopping), and do not continue without both answers.

## Repository layout

- `backend/src/sidekick/`: one package per context (`work`, `tasks`, `projects`, `journal`, `contacts`, `shopping`,
  `memory`, `activity`, `search`, `lifecycle`, `license`, `references`, `companion`, `backup`, `owner_export`), the
  shared read records (`structured/`), the two interfaces (`mcp/`, and `api/` with the companion routes), the operator
  CLI (`admin/`), the composition root (`composition.py`) and `shared/`. Layering is enforced by
  `backend/tests/policy/test_interface_layering.py` and
  `test_package_boundaries.py`; the debt lists in those tests may only shrink.
- `frontend/`: the MCP Apps rooms (`src/features/`, React, built into one HTML resource) and the Android app
  (`frontend/android/`, Capacitor and Kotlin).
- `contracts/`: generated snapshots of the current surface, and `contracts/reviewed/`, accepted baselines that
  are never rewritten.
- `deploy/selfhost/` and `deploy/work/`: Docker Compose packages, with `tools/drill.sh` and `tools/work.sh`.
- `docs/`: user and architecture documentation; `docs/decisions/log.md` is the log of product decisions
  that hold today and `docs/decisions/adr/` the accepted architecture decisions.

## Architecture rules

- FastAPI routes and FastMCP tools call the **same application use cases**. An MCP handler never calls
  Sidekick's own HTTP API.
- Business rules stay testable without frameworks, databases, workers or model providers. No generic
  repositories, tool frameworks or speculative layers.
- Every change enforces authorisation server-side (owner filtering and explicit scopes), keeps a
  correlation id, returns safe errors, and has tests for authorisation and redaction. Do not remove or
  weaken a meaningful test to get green.
- MCP tools are curated public contracts: narrow schemas, stable names, structured outputs, bounded reads,
  durable idempotency for writes. They are direct commands: the server checks owner, scope and observed
  version on each call, and there is no generic proposal or approval step. The one review flow is the
  journal draft, which the owner finalizes. "Ask first" wording in a tool description (for example
  `move_to_trash`) is an instruction to the host model, not a server check: never rely on it for safety.
- Runtime processes use the least-privilege `sidekick_app` role; only the migrator runs DDL.

## Code standards

- Follow the existing patterns in the neighbouring code. No copied code, no dead code, no new dependency
  without a reason.
- Add tests with the change. Prefer small, focused commits and small diffs.

## Commands (from the repository root)

```bash
uv sync --project backend --all-groups
npm --prefix frontend ci

# Static checks
(cd backend && uv run ruff format --check . && uv run ruff check --no-cache . && uv run pyright)
npm --prefix frontend run format:check
npm --prefix frontend run check            # lint + typecheck + vitest

# Backend tests need a disposable PostgreSQL on port 55433 (see the "Run the tests" section of docs/contribute/development.md)
(cd backend && uv run pytest --full)

# The whole local suite before a push (tools/check-all.sh --help; --skip-* flags, --dry-run).
# Test database slot K (1 to 20) is yours alone; the script touches no other database.
bash tools/check-all.sh --slot K

# Keep generated artefacts in sync
uv run --project backend python -m sidekick.api.export_openapi --output contracts/openapi.generated.json
uv run --project backend python -m sidekick.mcp.export_contract --output contracts/mcp-tools.generated.json
uv run --project backend python -m sidekick.mcp.export_tool_reference
uv run --project backend python -m sidekick.export_reference
uv run --project backend python -m sidekick.api.export_companion_contract --output contracts/companion-api.generated.json
npm --prefix frontend run build:mcp-app
```

Launch the backend from the repository root, with `--no-access-log` (request URLs can carry search text):
`.env` is resolved against the process working directory, and a missing file silently falls back to defaults.

## Delivery rules

- A change that touches an API or MCP tool regenerates the contract files above in the same change.
- User documentation exists in English and Swedish with the same structure (`README`, `QUICKSTART`,
  `CONTRIBUTING`, `SECURITY`, and the guides listed in `backend/tests/policy/test_docs_language_parity.py`);
  update both. The app's own labels are Swedish by default; code, comments, commit messages and GitHub text
  are English.
- A migration may only expand the schema unless it is marked `# migration-class: contract`; check with
  `python3 tools/check-migration-policy.py --base origin/main`.
- Keep the version in step across `backend/pyproject.toml`, `frontend/package.json` and the Android build
  (`python3 tools/check-version-sync.py`).
- Do not add internal process labels, ticket numbers or planning vocabulary to code comments, tests or docs.
- Report what you ran and what you did not run; do not claim a check that was not executed.
