# Resource limits and secrets per container

[Svenska](limits-and-secrets.sv.md)

<!-- description: Which memory and process limits each self-hosted container has, how to change them, and which settings each container receives. -->

Which memory and process limits each self-hosted container has, how to change them, and which settings each container receives.

## Resource limits

Every container of the base stack and of the `memory`, `backup` and `push` profiles has a memory ceiling and a process limit (`mem_limit` and `pids_limit` in `compose.yaml`). They keep a runaway process from taking the whole host down. The memory value is a ceiling, not a reservation. A container that goes over it is killed and restarted by Docker; `docker inspect <container>` then shows `OOMKilled`.

| Service | Memory | Processes | Variable prefix |
| --- | --- | --- | --- |
| `postgres` | 1g | 256 | `SELFHOST_POSTGRES_` |
| `migrate` | 512m | 64 | `SELFHOST_MIGRATE_` |
| `api` | 3g | 256 | `SELFHOST_API_` |
| `automation-worker` | 512m | 64 | `SELFHOST_AUTOMATION_` |
| `backup` | 3g | 64 | `SELFHOST_BACKUP_` |
| `push` | 512m | 64 | `SELFHOST_PUSH_` |
| `memory-worker` | 512m | 64 | `SELFHOST_MEMORY_` |
| `hindsight` | 4g | 512 | `SELFHOST_HINDSIGHT_` |

The own `ntfy` server keeps its fixed limits (128m, 64 processes).

To change one, add `SELFHOST_<SERVICE>_MEM_LIMIT` or `SELFHOST_<SERVICE>_PIDS_LIMIT` to `selfhost.env` (the commented lines in `selfhost.env.example` list them all), for example `SELFHOST_HINDSIGHT_MEM_LIMIT=6g`, and start the service again with `docker compose --env-file selfhost.env up -d`. The names do not start with `SIDEKICK_`, so the API accepts them in the same file.

Why `backup` and `api` have 3g: a backup holds an entire owner export in memory, at most 512 MiB of plaintext, and the encryption keeps several copies of it alive at once (the text, the bytes, the padded block and the token, which is about a third larger in base64). `update.sh` and `restore.sh` run the snapshot encryption and the backup import as one-off containers of the `api` service, so `api` needs the same room. A normal install uses a small fraction. Lower the two values only on a small host with a small database, and raise them if a backup or an update fails with `Killed` or exit code 137.

The `hindsight` value is an estimate, not a measurement: the local embedding and reranker models run inside it.

## Which settings each container receives

:::caution[Always pass `--env-file selfhost.env`]
Every `docker compose` command needs `--env-file selfhost.env`: `up`, `restart`, `run`, and the commands in your own systemd units or scripts as well. The workers no longer read `selfhost.env` themselves. Without the option they start without a database URL and crash in a restart loop while `api` keeps running, so the fault is easy to miss. Check with `docker compose --env-file selfhost.env ps`.
:::

`selfhost.env` holds all settings, but a container only receives the ones its process reads.

- `api` reads the whole of `selfhost.env`. It is the one process that needs the GitHub sign-in settings, the rooms and the request limits. It never receives `db.env`.
- `automation-worker`, `backup`, `push` and `memory-worker` receive a named list of settings, resolved from the `--env-file selfhost.env` of the command. They have no `env_file`. Every worker gets the database URL, the two signing secrets, the time budgets and the time zone, because production refuses to start without them.
- Only `backup` receives `SIDEKICK_BACKUP_ENCRYPTION_KEY` and the retention settings. Only `push` receives `SIDEKICK_PUSH_AUTH_TOKEN`. The memory token and the key that derives memory ids go to `memory-worker` and to `automation-worker`, because the latter builds the same container as the API.
- No worker receives the GitHub client secret, the OAuth signing key, the allowed identities or the scopes.
- `postgres` and `migrate` read `db.env`. `hindsight` reads `hindsight.env`. `ntfy` reads `ntfy.env`. No other service reads those files. `migrate` still receives the whole of `db.env`, including the PostgreSQL superuser password, although it only needs the migrator URL. It is a one-shot container with no route to the internet.

Practical consequences:

- Always run `docker compose` with `--env-file selfhost.env`, as every guide does. Without it a worker starts without a database URL and stops with an error instead of running on defaults.
- A setting that only the API reads (for example `SIDEKICK_MCP_OAUTH_SCOPES`) takes effect after you restart `api`; the workers do not need it.
- A new `SIDEKICK_` setting that a worker should read must be added to the list in `compose.yaml`. The test `backend/tests/selfhost/test_selfhost_secret_scope.py` checks that every listed name is a declared setting.
- The work package (`tools/work.sh`) is not affected: it replaces the lists with its own secret files.
