# Self-hosted Sidekick

[Svenska](README.sv.md)

This directory is the Docker Compose package for running Sidekick on a machine you control. It starts
the Sidekick API, PostgreSQL, a one-shot migrator, the automation worker and, depending on the profile, Caddy
(TLS), Hindsight (memory), encrypted backups and the push worker (ntfy). There is deliberately no web UI service: the
product interface is MCP Apps inside your LLM client.

Everything is described in the comments of `compose.yaml`. The guides are in `docs/`, in the order you need them:

- [First start on a server](../../docs/start/self-hosted-server.md)
- [Connect Claude](../../docs/operate/connect-claude.md)
- [Build, install and pair Android](../../docs/operate/pair-android.md)
- [Turn on memory](../../docs/operate/memory.md)
- [Update](../../docs/operate/update.md)
- [Backup and restore](../../docs/operate/backup-and-restore.md)
- [Empty the trash](../../docs/operate/empty-trash.md)
- [Compose profiles and files](../../docs/reference/selfhost-profiles.md): what each profile starts and what each file in this directory is for.
