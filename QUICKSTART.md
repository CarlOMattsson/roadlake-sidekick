# Developer quickstart

[Svenska](QUICKSTART.sv.md)

The shortest way from a fresh clone to a running local instance, for development. All commands run from the
**repository root**. To run Sidekick for real use, see [README.md](README.md#run-it).

You need Python 3.13 with [`uv`](https://docs.astral.sh/uv/), Node.js 22 (22.23.4 or newer) / npm 10 and Docker with Compose v2.

## 1. Set up once

```bash
git clone https://github.com/CarlOMattsson/roadlake-sidekick.git
cd roadlake-sidekick
[ -f .env ] || cp .env.example .env     # then fill in local secrets; never commit this file
uv sync --project backend --all-groups
npm --prefix frontend ci
```

In `.env`, `SIDEKICK_CURSOR_SIGNING_SECRET` and `SIDEKICK_TOKEN_PEPPER` must each be at least 32 characters
(for example `openssl rand -hex 32`) and differ from each other. No API keys are needed to start.

## 2. Start the database and apply migrations

```bash
docker compose -f deploy/compose.dev.yaml up -d db
docker compose -f deploy/compose.dev.yaml ps          # wait until the db service is healthy
uv run --project backend yoyo apply --batch \
  --database postgresql+psycopg://sidekick_migrator:sidekick_migrator@127.0.0.1:55440/sidekick migrations
```

## 3. Start the backend

Start it from the repository root, in its own terminal, and leave it running:

```bash
uv run --project backend uvicorn sidekick.api.app:create_app --factory --reload --no-access-log
```

Check that it is up: `curl http://127.0.0.1:8000/health/ready`. The MCP endpoint is `http://127.0.0.1:8000/mcp/`.

## 4. Create a user and a token

In a new terminal:

```bash
uv run --project backend sidekick-admin create-user --login local-user --display-name "Local User"
uv run --project backend sidekick-admin create-token --user-id <USER_UUID> --label "Local MCP" \
  --scope projects:read --scope tasks:read --expires-in-days 30
```

`create-user` prints the user's UUID. `create-token` shows the token **once**; keep it in your client's secret store.

## 5. Optional: fictitious data and the MCP App

```bash
uv run --project backend python -m tools.seed --confirm      # fake Work, Contacts and Journal data, local databases only
npm --prefix frontend run build:mcp-app                       # after changing frontend/src
```

To see the rooms, connect Claude Desktop or a token client; step 4 and 5 of
[Run Sidekick locally as a developer](docs/start/first-contribution.md) show how.

## Shut down

Stop Uvicorn with `Ctrl+C`, then:

```bash
docker compose -f deploy/compose.dev.yaml down       # keeps the data volume
docker compose -f deploy/compose.dev.yaml down -v    # also deletes the local database; only if you mean it
```

## Go further

- [Run Sidekick locally as a developer](docs/start/first-contribution.md): the same steps with explanations, Claude Desktop over stdio, the MCP Inspector and troubleshooting.
- [Development guide](docs/contribute/development.md): checks, the full test suite, generated files and code style.
