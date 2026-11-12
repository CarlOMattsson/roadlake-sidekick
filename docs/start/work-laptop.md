# Sidekick on a work laptop

[Svenska](work-laptop.sv.md)

<!-- description: Run Sidekick and a private memory in Docker on your work laptop and use it from Claude Desktop, with no public address. Sidekick's containers can reach only your company's own model server; what you do in Claude Desktop is still shared with Claude. -->

Run Sidekick and a private memory in Docker on your work laptop and use it from Claude Desktop, with no public address. Sidekick's containers can reach only your company's own model server; what you do in Claude Desktop is still shared with Claude.

## What leaves the laptop

- **Sidekick's containers** have no route out except to the model server in `work.env` (and any hosts you allow in
  `SIDEKICK_WORK_ALLOW`). Hindsight sends it the text it derives memory from: the titles, descriptions and notes of
  the records in the rooms you switched on. Sidekick itself calls no language model, and push notifications are off.
- **Claude Desktop is an external service.** Everything a Claude conversation touches goes to Claude (Anthropic): your
  messages, the names and arguments of the Sidekick tools it calls, and what they return (for example task titles,
  contact names, journal text and dates) together with the usual timing metadata. Claude Desktop also makes its own
  network calls. The container isolation does not cover any of this. Limit what Claude can read by switching rooms off
  (see [Operating the work package](../operate/work-laptop/README.md)).
- **The laptop itself** reaches the internet when you set up and update: `git clone` and `git pull`, and the image build
  and pull (Docker registries and package sources). That traffic carries no Sidekick data.

## What you need

- Ubuntu with Docker Engine and admin rights (the drill in [Verification](../maintainers/verification.md) ran on Linux with Docker 29).
  Another Linux with Docker should work the same way. macOS with Docker Desktop (bash 3.2 is enough) is written for,
  but has never been run.
  Docker with Compose v2.24.4 or newer (`docker compose version`).
- Your user must be able to run `docker` **without `sudo`**: Claude Desktop starts Sidekick with `docker exec`, which
  cannot ask for a password. On Linux: `sudo usermod -aG docker "$USER"`, then log out and in again and check with
  `docker ps` (without `sudo`). Docker Desktop on Mac needs nothing extra.
- `git`, `openssl`, `python3` and `curl` (all standard on Ubuntu and macOS).
- Claude Desktop. Node.js is not needed: Claude Desktop starts Sidekick's stdio server directly in the container.
- The address of the company model server (a vLLM base URL ending in `/v1`) and, if it needs one, its API key.

## Quick way: the guide

`bash tools/work.sh setup` asks (Swedish or English) for the model server address, tests it with `GET /models`,
takes the API key as hidden input, lets you pick the memory model from the server's list, asks which
extra addresses Sidekick may reach, which rooms to switch on (it proposes `work,journal,contacts,control`) and whether Sidekick should start at
login, writes `work.env`, can start everything and writes the Claude Desktop configuration. It can be run again:
answers are offered as defaults and only the settings it asks about are rewritten. The manual steps below do the same
thing one by one.

### Choose the language and the rooms

Setup asks two questions you should answer on purpose:

- **Language of the app and of Claude's answers:** Swedish (`sv`, the proposal) or English (`en`). It is stored as
  `SIDEKICK_WORK_LOCALE` in `deploy/work/work.env` and is separate from the language of the guide's own texts.
- **Rooms:** the proposal for a work machine is every room except shopping: `work` (required), `journal`, `contacts`
  and `control`. Shopping stays off unless you add it; answer `-` to switch every room on. See
  [Rooms](../operate/work-laptop/README.md#rooms).

**For an AI assistant setting this up for the user:** ask the user which language the app should have (propose Swedish)
and which rooms they want (propose all except shopping), and do not continue until both are answered. Never choose them
on the user's behalf.

## Steps

1. Get the repository and go to its root.
2. `bash tools/work.sh init` copies `deploy/work/work.env.example` to `deploy/work/work.env`, generates the
   database passwords and other secrets into `deploy/work/secrets/` (directory mode 700, files mode 600, not in git)
   and asks for the model key (hidden input; Enter if the server needs none).
3. Edit `deploy/work/work.env`: `SIDEKICK_WORK_MODEL_BASE_URL` and
   `SIDEKICK_WORK_MEMORY_MODEL` (the model Hindsight uses). Locale is Swedish by default (`SIDEKICK_WORK_LOCALE=en` for English).
4. `bash tools/work.sh start` builds Sidekick's image (a few minutes the first time), starts the stack, creates the
   owner user and writes a ready Claude Desktop configuration to `deploy/work/secrets/claude_desktop_config.json`.
   Merge that file's `sidekick-work` entry under `mcpServers` in `claude_desktop_config.json` (Linux:
   `~/.config/Claude/`, macOS: `~/Library/Application Support/Claude/`) and restart Claude Desktop completely.
   Alternatively, run `bash tools/work.sh claude-config`: it previews the entry, asks **y/N**, then merges it
   with Python's JSON parser, preserving other servers and settings. An existing file gets a timestamped `.bak.*`
   copy with mode 600 before replacement. It never runs automatically from `setup` or `start`; Enter or EOF declines.
   `bash tools/work.sh status` then lists the model ids the server offers, so you can copy them exactly.

The entry looks like this (the path to `docker` is your machine's own and absolute, because Claude Desktop starts
programs with a minimal `PATH`; the UUID is the owner user's):

```json
{
  "mcpServers": {
    "sidekick-work": {
      "command": "/usr/bin/docker",
      "args": ["exec", "-i", "-e", "SIDEKICK_MCP_STDIO_OWNER_ID=<owner UUID>",
               "sidekick-work-api-1", "python", "-m", "sidekick.mcp.stdio"]
    }
  }
}
```

**How it works.** `claude_desktop_config.json` starts local programs and speaks MCP over their stdin and stdout.
Sidekick has its own stdio entry point (`python -m sidekick.mcp.stdio`) with the same tools, apps and rooms as the
ordinary MCP surface over HTTP; both call the same functions in Sidekick, so permissions and rules are the same. It runs inside the already running api container with `docker exec -i`:
the container holds the database credentials, the model routes and `SIDEKICK_ENABLED_ROOMS`, so none of that is put in
Claude Desktop's settings and no token is needed. The process trusts whoever can run `docker` on the machine (the same
person who can already reach the database credentials) and acts as the owner user `jobb` (Swedish for "work"; the name the setup gives the single owner account); if the account is disabled, a
running session stops answering. `docker exec` is used rather than `docker compose exec`, because the latter needs the
compose files and every derived variable, and it works the same with Docker Desktop on Mac. The container must be
running: start Docker and Sidekick (`autostart on`) before Claude Desktop. The image must be built from a version that
has the stdio entry point; otherwise `start` tells you to run `start --build`.

**Security assumption.** The stdio process proves nothing about who calls it: whoever can start it (here, anyone who can run `docker exec` on the machine) gets every scope of the MCP surface, except those of rooms that are switched off. Treat access to the Docker socket as owner access.

## Verify

`bash tools/work.sh status` must show every service healthy, the MCP port without a token as 401, the Claude Desktop
configuration as present, and the egress check as "blocked" for `example.com`, `1.1.1.1` and the model server called
directly, both from Sidekick and from Hindsight, while the model list comes back through the gateway. In Claude
Desktop the connector is named "Sidekick Work".

## Troubleshooting the first start

**Strict umask (for example 077).** `setup` and `start` warn when the caller's umask is stricter than 022.
Secrets stay private (directories 700, files 600). The image makes copied source and migrations readable and
traversable by its runtime user; `start` makes the public `postgres-init.sh` executable (755) and generated
mounts readable (644, directory 755). The shared selfhost Compose entrypoint also copies the role script inside
the Postgres container with mode 755 before its official entrypoint drops privileges, so a host file with mode
600 works there too. Only public code gets these permissions.

**Rebuild an old image.** Run `bash tools/work.sh start --build`. To bypass all build layers explicitly:

```bash
bash tools/work.sh start --build --no-cache
```

`--no-cache` requires `--build`; it affects the image build only. It does not reset database volumes.

**A failed first initialization left a database without roles.** On a failed start, the script inspects bounded
migration and Postgres logs. Authentication failure for `sidekick_migrator`, or `initdb.d ... Permission denied`,
triggers a read-only check as the local Postgres administrator. Only a confirmed absent or empty migration table
produces the recovery instructions. An initialized volume skips `initdb.d` on restart, so after fixing permissions
you must remove this incomplete database volume yourself. The script prints its exact name using the Compose
project/volume labels (default `sidekick-work_pgdata`) and the exact command. For the default project:

```bash
bash tools/work.sh stop
docker volume rm sidekick-work_pgdata
bash tools/work.sh start --build
```

**The volume command deletes its database contents.** Use it only for the incomplete first installation identified
by the diagnostic. Keep `deploy/work/secrets/` so the retry uses the same passwords. The script never deletes the
volume for you. If the database cannot be inspected or migrations already exist, it prints no removal advice;
investigate `deploy/work/work.log` instead. `stop --purge` is broader and is not needed for this repair.

**Hindsight reports APIConnectionError at startup.** It now waits for the gateway's existing healthcheck before
starting. That check confirms the gateway listener, not that the company model server is reachable. If the error
persists, check the model address, VPN and `bash tools/work.sh status`.

**Claude Desktop has no Sidekick entry.** Run `bash tools/work.sh claude-config` after a successful `start`, review
its preview and answer y. Restart Claude Desktop completely. Invalid JSON is refused without replacing the file;
repair it first or merge the generated entry by hand. The command previews only the new Sidekick entry, never the
credentials in other connectors. To undo a merge, put back the timestamped backup beside the configuration file.
