# Run Sidekick locally as a developer

[Svenska](first-contribution.sv.md)

<!-- description: Run Sidekick locally from source, with your own database and fictitious data. You can try the tools from Claude Desktop or straight against the MCP server. -->

Run Sidekick locally from source, with your own database and fictitious data. You can try the tools from Claude Desktop or straight against the MCP server.

How to run Roadlake Sidekick from a fresh clone for development
(`git clone https://github.com/CarlOMattsson/roadlake-sidekick.git && cd roadlake-sidekick`). All commands run from the **repository root**.
To run Sidekick for real use, see [README.md](../../README.md#run-it) instead.

## Prerequisites

- Python 3.13 with [`uv`](https://docs.astral.sh/uv/)
- Node.js 22 and npm 10
- Docker with Compose v2 (for local PostgreSQL)

```bash
uv --version && node --version && npm --version && docker compose version
```

## 1. One-time setup

```bash
[ -f .env ] || cp .env.example .env     # then fill in local secrets; never commit this file
uv sync --project backend --all-groups
npm --prefix frontend ci
```

`SIDEKICK_CURSOR_SIGNING_SECRET` and `SIDEKICK_TOKEN_PEPPER` in `.env` must each be at least 32 characters (for
example `openssl rand -hex 32`), and should differ from each other. The cursor signing secret signs list cursors;
the pepper is mixed into the stored token hashes, so changing it later invalidates every token already
issued. Safe defaults use deterministic fake providers and keep external AI off, so no API keys are needed
to start. [.env.example](../../.env.example) holds the settings a local developer needs, not the full list: the
complete set is the `Settings` class in `backend/src/sidekick/shared/config/`, and
[deploy/selfhost/selfhost.env.example](../../deploy/selfhost/selfhost.env.example) shows the production set.
Environment variables override `.env`, and undeclared `SIDEKICK_*` settings are rejected.

## 2. Start PostgreSQL and apply migrations

```bash
docker compose -f deploy/compose.dev.yaml up -d db
docker compose -f deploy/compose.dev.yaml ps          # wait until the db service is healthy

uv run --project backend yoyo apply --batch \
  --database postgresql+psycopg://sidekick_migrator:sidekick_migrator@127.0.0.1:55440/sidekick migrations
```

`yoyo apply --batch` prints nothing when it succeeds. To see the result, run `uv run --project backend yoyo list --database <the same URL> migrations`;
every migration is marked `A` (applied).

The database listens on `127.0.0.1:55440`. To change that, put the variable in front of the compose command only,
for example `SIDEKICK_DEV_DB_BIND=127.0.0.1:55441 docker compose -f deploy/compose.dev.yaml up -d db`, and change the
port in the `yoyo` URL above and in `SIDEKICK_DATABASE_URL` in `.env` as well. Do not export it in your shell or put
it in `.env`: it is a compose setting, not a Sidekick setting, and the backend refuses to start on an undeclared
`SIDEKICK_` variable. `deploy/postgres-init.test-only.sql`
creates the `sidekick_owner`, `sidekick_migrator` and least-privilege `sidekick_app` roles. Only the migrator
performs DDL; the application never does. Re-run `yoyo apply` whenever new files appear under `migrations/`.

## 3. Start the backend

```bash
uv run --project backend uvicorn sidekick.api.app:create_app --factory --reload --no-access-log
```

- MCP (Streamable HTTP): `http://127.0.0.1:8000/mcp/`
- Health: `http://127.0.0.1:8000/health/live` and `/health/ready`
- With `SIDEKICK_COMPANION_ENABLED=true` (the Android app, see [Build, install and pair Android](../operate/pair-android.md)) the
  companion API is served under `/companion/v1/`.

There is no REST API for a web shell: the product surface is MCP. `--no-access-log` keeps request URLs, which
can carry search text, out of the logs, as the self-hosting package does.

**Start it from the repository root.** `.env` is resolved against the process working directory, not the
repository. Started from `backend/` the file is silently not found and every setting falls back to its
default (including the fake memory provider). The startup record `config_dotenv_file` tells you which
happened: `found` means the file was read, `missing` means it was never found. `config_environment_only`
names (never prints the values of) settings that came from the process environment.

## 4. Create a user and a scoped MCP token

```bash
uv run --project backend sidekick-admin create-user --login local-user --display-name "Local User"

uv run --project backend sidekick-admin create-token --user-id <USER_UUID> --label "Local MCP" \
  --scope projects:read --scope tasks:read --expires-in-days 30
```

`create-user` asks for nothing (no terminal needed; Sidekick has no passwords) and prints the new user's UUID, which `create-token` and the settings below take. `create-token` shows the raw bearer value **once**;
keep it in your client's secret store. `--scope` is required (no scope is implied) and a token lasts 90 days unless `--expires-in-days` (at most 365) or `--never-expires` says otherwise. The HTTP MCP endpoint has no unauthenticated bypass: every request needs
`Authorization: Bearer <token>` with scopes that cover the tool. That token mode (`pat`, the default) suits
clients that can send a bearer header, such as the MCP Inspector or Claude Code. The curated tool list is in
[contracts/mcp-tools.generated.json](../../contracts/mcp-tools.generated.json), and the readable
[MCP tool reference](../reference/mcp/index.md) lists each tool with its scopes and parameters.

**Empty the trash.** Deleting only moves a record to the trash. From a clone, `uv run --project backend sidekick-admin empty-trash` prints how many records of each type are in it, and `--yes` deletes them for good. The options and what is kept anyway are in [Empty the trash](../operate/empty-trash.md).

**Connect Claude.** Claude Desktop on the same machine can start Sidekick itself over stdio, with no token: set
`SIDEKICK_MCP_STDIO_OWNER_ID=<USER_UUID>` in `.env`, add this server under `mcpServers` in
`claude_desktop_config.json` (use absolute paths, and the absolute path of `uv` if Claude Desktop cannot find
it), and restart Claude Desktop:

```json
{ "command": "uv", "args": ["run", "--project", "/ABSOLUTE/PATH/backend", "python", "-m", "sidekick.mcp.stdio", "--env-file", "/ABSOLUTE/PATH/.env"] }
```

Claude's hosted custom connector (claude.ai and the mobile apps) needs a **public HTTPS origin** and GitHub
sign-in (`SIDEKICK_MCP_AUTH_MODE=github_oauth`), not a bearer token: see
[Connect Claude](../operate/connect-claude.md).

## 5. See it work

Put fake data in the database, connect Claude Desktop, and ask one question. This uses the user from step 4
(the seeder reuses the login `local-user` and never changes an existing user), so run it after step 4:

```bash
uv run --project backend python -m tools.seed --confirm
```

The seeder writes fake Work, Contacts and Journal data into the local development database and refuses
production and any non-local database. It reads optional login settings from `.env.seed`
(see [.env.seed.example](../../.env.seed.example)). Then connect Claude Desktop over stdio as described under
**Connect Claude** in step 4 (it needs `SIDEKICK_MCP_STDIO_OWNER_ID` and a restart of Claude Desktop), start a new
chat, and ask:

> What is on my agenda today?

Claude calls `get_work_agenda` and shows the Work agenda as an inline card: dated tasks grouped as overdue, today
and upcoming, built from the seeded data. Open the card to get the full room, and use its menu to move on to
Contacts or Journal.

A bearer-token client such as the MCP Inspector or Claude Code needs a token that covers every room. The
command below grants the ten default scopes a personal token can hold (the two `automation:*` scopes are opt-in and left out) (`create-token` does not accept a
shortcut for "all"):

```bash
uv run --project backend sidekick-admin create-token --user-id <USER_UUID> --label "Local full" \
  --scope projects:read --scope projects:write --scope tasks:read --scope tasks:write \
  --scope contacts:read --scope contacts:write --scope journal:read --scope journal:write \
  --scope shopping:read --scope shopping:write \
  --expires-in-days 30
```


**Without Claude Desktop: the MCP Inspector.** The Inspector is a browser tool that lists a server's tools and shows what each returns. It does not draw the rooms; Claude and the Android app do that. With the backend running (step 3) and a token from the command above, start it:

```bash
npx @modelcontextprotocol/inspector
```

In the page that opens, choose the transport **Streamable HTTP**, set the URL to `http://127.0.0.1:8000/mcp/`, add the header `Authorization` with the value `Bearer <token>`, and press Connect. Under **Tools**, run `get_work_agenda` to see the same data that Claude turns into the agenda card.

## 6. Build the MCP App

There is no web shell and no Vite dev server. The MCP Apps rooms that Claude and the Android app display
are built from React sources:

```bash
npm --prefix frontend run build:mcp-app    # writes backend/src/sidekick/mcp/apps/sidekick.html
```

That file is a checked-in build output. Never edit it by hand: rebuild it, and commit the result together
with the source change (CI fails on a stale copy).

## Shut down

Stop Uvicorn with `Ctrl+C`, then:

```bash
docker compose -f deploy/compose.dev.yaml down       # keeps the data volume
docker compose -f deploy/compose.dev.yaml down -v    # also deletes the local database; only if you mean it
```

## Troubleshooting

- **`db` never becomes healthy:** `docker compose -f deploy/compose.dev.yaml logs db`; port 55440 may be taken
  (set `SIDEKICK_DEV_DB_BIND` on the compose command, as above).
- **A setting in `.env` has no effect:** exported `SIDEKICK_*` variables win over the file (list the names with `env | grep -o '^SIDEKICK_[A-Z_]*'`),
  or the backend was started from another directory (see step 3).
- **Migration errors:** make sure the database is healthy and the connection string points at the right port.
- **`password authentication failed for user "sidekick_migrator"` on the first run:** the roles in
  `deploy/postgres-init.test-only.sql` were never created, because the database volume was initialised by a failed first start
  and PostgreSQL skips initialisation on every later start. Run `docker compose -f deploy/compose.dev.yaml down -v`
  (it deletes the local database) and start again. The compose file copies the file as root, so a strict `umask`
  (`077`) on the checkout is no longer a cause; to see what the container read:
  `docker compose -f deploy/compose.dev.yaml exec db ls -l /docker-entrypoint-initdb.d/` lists the roles file the container copied (named 001-roles, ending in .sql).
- **Two clones on one machine:** the compose project is called `sidekick-dev` in both, so they share one database
  volume. Give the second a project name of its own: `docker compose -p sidekick-dev-2 -f deploy/compose.dev.yaml ...`
  with a different `SIDEKICK_DEV_DB_BIND`.
