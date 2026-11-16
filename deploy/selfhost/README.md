# Self-hosted Sidekick

[Svenska](README.sv.md)

This directory is the Docker Compose package for running Sidekick on a machine you control. It starts
the Sidekick API, PostgreSQL, a one-shot migrator, the automation worker and, depending on the profile, Caddy
(TLS) or Tailscale Funnel (home machine), Hindsight (memory), encrypted backups and the push worker (ntfy). There is
deliberately no web UI service: the product interface is MCP Apps inside your LLM client.

Everything is described in the comments of `compose.yaml`. The guides are in `docs/`, in the order you need them:

- [First start on a server](../../docs/start/self-hosted-server.md)
- [Connect Claude](../../docs/operate/connect-claude.md)
- [Build, install and pair Android](../../docs/operate/pair-android.md)
- [Turn on memory](../../docs/operate/memory.md)
- [Update](../../docs/operate/update.md)
- [Backup and restore](../../docs/operate/backup-and-restore.md)
- [Empty the trash](../../docs/operate/empty-trash.md)
- [Home machine with Tailscale Funnel](../../docs/start/self-hosted-server.md#first-start): `docker compose --env-file selfhost.env --profile tailscale up -d` publishes the API at your `ts.net` name; no router or firewall change.
- [Compose profiles and files](../../docs/reference/selfhost-profiles.md): what each profile starts and what each file in this directory is for.

## AI steps on the server (profile `ai`, optional)

The `ai` profile starts one extra container, `ai-worker`, that runs approved AI steps on the server with your own
Anthropic API key. It is off until you turn it on:

1. Put the key in a file that only you can enter, and nothing else in it:
   `mkdir -p secrets && chmod 700 secrets && printf '%s\n' <your key> > secrets/ai_anthropic_api_key && chmod 644 secrets/ai_anthropic_api_key`
   (mode 644 inside a mode 700 directory is how Compose secrets work here, see `selfhost.env.example`). Never put the key in `selfhost.env`:
   the API refuses to start in production when it finds it there.
2. In `selfhost.env` set `SELFHOST_AI_ANTHROPIC_API_KEY_FILE=./secrets/ai_anthropic_api_key` and
   `SIDEKICK_AI_RUNNER_ENABLED=true`. Choose a model with `SIDEKICK_AI_MODEL` if you want another than the default.
3. Start it: `docker compose --env-file selfhost.env --profile ai up -d`. `update.sh` keeps it running across updates
   once it runs; a server that never started the profile is not affected.

The key reaches `ai-worker` only, as a file. That container is the only one on the `ai` network, the one outbound route to
the internet (the Anthropic API); it shares no network with Hindsight or ntfy. Set a spending limit for the key in the
Anthropic Console as the outer belt; Sidekick's own caps (`SIDEKICK_AI_MONTHLY_CAP_USD` and the per-task cap) are the inner one.
