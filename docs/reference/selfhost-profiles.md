# Compose profiles and files

[Svenska](selfhost-profiles.sv.md)

<!-- description: Which services each Compose profile starts, and what the files in the self-hosting package are for. -->

Which services each Compose profile starts, and what the files in the self-hosting package are for.

## Profiles

The base stack needs no profile. Add profiles to the same `docker compose --env-file selfhost.env` command line.

| Profile | Services it adds | What it is for |
| --- | --- | --- |
| none | `postgres`, `migrate`, `api`, `automation-worker` | The API, the database, the one-shot migrator and the worker that runs scheduled processes. Only the API is published, on `127.0.0.1:8000`. |
| `vps` | `caddy` | TLS on ports 80 and 443 with an automatic certificate. Leave it out on a home machine behind a tunnel. |
| `memory` | `hindsight`, `memory-worker` | Derived memory. Needs `hindsight.env` and the `SIDEKICK_MEMORY_*` settings; see [Turn on memory](../operate/memory.md). |
| `backup` | `backup` | Encrypted backups. Needs `SIDEKICK_BACKUP_ENCRYPTION_KEY` in `selfhost.env`; see [Backup and restore](../operate/backup-and-restore.md). |
| `push` | `push`, `ntfy` | Reminders to the Android app. Needs `SIDEKICK_PUSH_ENABLED=true`. The own ntfy server is published through Caddy, so it needs the `vps` profile; `up -d push` alone starts just the worker, which then delivers through ntfy.sh. See [Reminders through ntfy](../operate/push-reminders.md). |

## Files in `deploy/selfhost`

| File | What it is for |
| --- | --- |
| `compose.yaml` | The whole stack, with every service and profile described in its comments. |
| `selfhost.env.example` | The settings of the API and the workers. Copy it to `selfhost.env` and keep that file at mode 600. |
| `db.env.example` | The database passwords. Copy it to `db.env`. PostgreSQL reads it only on the first start of an empty volume. |
| `hindsight.env.example` | The provider, model and key for the `memory` profile. Copy it to `hindsight.env`. |
| `ntfy.env.example` | The settings of the own ntfy server, for the `push` profile. |
| `Caddyfile.example` | The Caddy configuration for the `vps` profile. Copy it to `Caddyfile`. |
| `ntfy/server.yml` | The hardened ntfy server's configuration. |
| `ntfy-init.sh` | One-time setup of the ntfy accounts. It prints no secret. |
| `postgres-init.sh` | Creates the database roles on the first start of an empty volume. |
| `update.sh` | Updates to a signed, digest-pinned image, with an encrypted snapshot first. See [Update](../operate/update.md). |
| `restore.sh` | Restores one owner from an encrypted backup or a plain export. See [Backup and restore](../operate/backup-and-restore.md). |
| `restore-ownership.sql` | Gives each object back its owner after a plain SQL dump has been restored. |
| `backup_space.sh` | Checks free space before a backup and prunes finished backup files. Shared with the work package. |
| `snapshot_crypto.py` | Encrypts and decrypts the database snapshots that `update.sh` takes. |
| `min-upgrade-from.txt` | The oldest version a new release can be updated from. |
