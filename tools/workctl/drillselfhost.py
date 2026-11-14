"""The first scenario of the drill: the self-hosted stack with ``deploy/selfhost/update.sh``.

Install the previous image, write a marker (a row in the database and a file in the Hindsight volume), update through
the real ``update.sh``, back up the way the guide does, destroy the volumes, check that a wrong key opens nothing,
restore and find the marker again. The stack runs with its ``memory`` profile (the real Hindsight container, a model
address that goes nowhere), so the Hindsight volume is covered the way the guide archives and restores it.

The scenario is shaped like the repository: ``update.sh`` finds ``tools/workctl`` two directories above itself.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from . import drillsteps as sk
from .drillhost import Done
from .drillsteps import Run, Step, StepFailed, expect_eq

KEY_VARIABLE = "SIDEKICK_BACKUP_ENCRYPTION_KEY"
UUID = re.compile(r"[0-9a-fA-F-]{36}")
NIL_OWNER = "00000000-0000-4000-8000-000000000000"
WAIT = ["--wait", "--wait-timeout", "300"]
MARKER_QUERY = "select token from public.drill_marker"


def db_env(postgres: str, app: str, migrator: str) -> str:
    return (
        f"POSTGRES_PASSWORD={postgres}\nSIDEKICK_DB_APP_PASSWORD={app}\nSIDEKICK_DB_MIGRATOR_PASSWORD={migrator}\n"
        f"SIDEKICK_MIGRATION_DATABASE_URL=postgresql+psycopg://sidekick_migrator:{migrator}@postgres:5432/sidekick\n"
    )


def hindsight_env(tenant_key: str) -> str:
    """The memory profile of the guide: a model address that goes nowhere; Hindsight starts and keeps its volume,
    which is all the drill needs of it."""
    return (
        "HINDSIGHT_API_LLM_PROVIDER=openai\nHINDSIGHT_API_LLM_BASE_URL=http://model.drill.invalid:8000/v1\n"
        "HINDSIGHT_API_LLM_MODEL=drill-model\nHINDSIGHT_API_LLM_API_KEY=not-needed\n"
        "HINDSIGHT_API_ENABLE_OBSERVATIONS=false\nHINDSIGHT_API_RETAIN_CHUNK_SIZE=3000\n"
        "HINDSIGHT_API_RETAIN_MAX_COMPLETION_TOKENS=4000\n"
        "HINDSIGHT_API_EMBEDDINGS_PROVIDER=local\nHINDSIGHT_API_RERANKER_PROVIDER=local\n"
        f"HINDSIGHT_API_TENANT_API_KEY={tenant_key}\n"
    )


def selfhost_env(app_password: str, backup_key: str, owner: str, tenant_key: str) -> str:
    """``selfhost.env``; the worker idles (``SIDEKICK_MEMORY_ENABLED=false``)."""
    return (
        "SELFHOST_DOMAIN=drill.invalid\nSIDEKICK_ENVIRONMENT=production\n"
        f"SIDEKICK_DATABASE_URL=postgresql+psycopg://sidekick_app:{app_password}@postgres:5432/sidekick\n"
        f"SIDEKICK_CURSOR_SIGNING_SECRET={sk.rand_secret()}\nSIDEKICK_TOKEN_PEPPER={sk.rand_secret()}\n"
        "SIDEKICK_MCP_AUTH_MODE=github_oauth\nSIDEKICK_MCP_PUBLIC_BASE_URL=https://drill.invalid\n"
        f"SIDEKICK_MCP_OAUTH_GITHUB_CLIENT_ID=drill-client-id\nSIDEKICK_MCP_OAUTH_GITHUB_CLIENT_SECRET={sk.rand_secret()}\n"
        f"SIDEKICK_MCP_OAUTH_SIGNING_KEY={sk.rand_secret()}\n"
        "SIDEKICK_MCP_OAUTH_STORAGE_DIR=/var/lib/sidekick/oauth-storage\n"
        f"SIDEKICK_MCP_OAUTH_ALLOWED_IDENTITIES=github:1={owner}\n"
        "SIDEKICK_MCP_OAUTH_SCOPES=projects:read,tasks:read,contacts:read,shopping:read\n"
        "SIDEKICK_MEMORY_ENABLED=false\nSIDEKICK_MEMORY_PROVIDER=hindsight\nSIDEKICK_BACKUP_ENABLED=false\n"
        f"SIDEKICK_MEMORY_HINDSIGHT_BASE_URL=http://hindsight:8888\nSIDEKICK_MEMORY_HINDSIGHT_API_TOKEN={tenant_key}\n"
        f"SIDEKICK_MEMORY_ID_DERIVATION_KEY={sk.rand_secret()}\n"
        f"{KEY_VARIABLE}={backup_key}\n"
    )


def port_override(port: int) -> str:
    return f'services:\n  api:\n    ports: !override\n      - "127.0.0.1:{port}:8000"\n'


class Selfhost:
    name = "selfhost"

    def __init__(self, shared: Run, project: str, port: int) -> None:
        self.shared = shared
        self.project = project
        self.port = port
        self.repo = shared.tmp / "selfhost"
        self.dir = self.repo / "deploy" / "selfhost"
        self.backups = self.dir / "drill-backups"

    def steps(self) -> list[tuple[str, Callable[[Step], None]]]:
        return [
            ("install", self.install),
            ("marker", self.marker),
            ("update", self.update),
            ("verify-updated", self.verify_updated),
            ("backup", self.backup),
            ("destroy-volumes", self.destroy),
            ("key-fails-closed", self.key_closed),
            ("restore", self.restore),
            ("verify-restored", self.verify_restored),
        ]

    # -- the stack ----------------------------------------------------------------------------------------------

    def compose(self, *args: str) -> list[str]:
        return [
            "docker",
            "compose",
            "-p",
            self.project,
            "-f",
            str(self.dir / "compose.yaml"),
            "-f",
            str(self.dir / "drill.override.yaml"),
            "--profile",
            "memory",
            "--env-file",
            str(self.dir / "selfhost.env"),
            "--env-file",
            str(self.dir / "release.env"),
            *args,
        ]

    def psql_argv(self, sql: str) -> list[str]:
        psql = ["exec", "-T", "postgres", "psql", "-U", "postgres", "-d", "sidekick"]
        return self.compose(*psql, "-v", "ON_ERROR_STOP=1", "-Atc", sql)

    def psql(self, step: Step, sql: str) -> str:
        return step.read(self.psql_argv(sql))

    def schema(self, step: Step) -> str:
        return self.psql(step, "select count(*) from _yoyo_migration")

    def head(self, step: Step) -> str:
        latest = "select migration_id from _yoyo_migration order by applied_at_utc desc, migration_id desc limit 1"
        return self.psql(step, latest)

    def update_sh(self, *args: str) -> list[str]:
        files = ["-f", str(self.dir / "compose.yaml"), "-f", str(self.dir / "drill.override.yaml")]
        return ["bash", str(self.dir / "update.sh"), "-p", self.project, *files, *args]

    def crypto_argv(self, step: Step, mode: str, *options: str) -> list[str]:
        """api keeps a fixed address on the proxy network, so a one-off api container cannot start beside a running
        one: a running api runs the tool itself, a one-off container is used only when api is stopped (as update.sh
        does)."""
        script = (self.dir / "snapshot_crypto.py").read_text(encoding="utf-8").rstrip("\n")
        running = step.read_bytes(self.compose("ps", "--status", "running", "--quiet", "api")).strip()
        mode_args = ("exec", "-T") if running else ("run", "--rm", "-T", "--no-deps")
        return self.compose(*mode_args, *options, "api", "python", "-I", "-c", script, mode)

    def crypto(self, step: Step, mode: str, data: bytes) -> bytes:
        """``data`` through ``snapshot_crypto.py`` in the api container, with the key of ``selfhost.env`` (the
        container's env_file), the way update.sh does it."""
        return step.read_bytes(self.crypto_argv(step, mode), stdin=data)

    def crypto_with_key(self, step: Step, key: str, mode: str, data: bytes) -> Done:
        """The same with another key (wrong or empty), given through the environment, never on a command line."""
        return step.call(self.crypto_argv(step, mode, "-e", KEY_VARIABLE), stdin=data, env={KEY_VARIABLE: key})

    def write_env(self, app: str, backup_key: str, owner: str, tenant: str) -> None:
        target = self.dir / "selfhost.env"
        pending = target.with_name("selfhost.env.tmp")
        pending.write_text(selfhost_env(app, backup_key, owner, tenant), encoding="utf-8")
        pending.chmod(0o600)
        pending.replace(target)

    # -- the steps ----------------------------------------------------------------------------------------------

    def install(self, step: Step) -> None:
        shared = self.shared
        sk.copy_selfhost_files(shared.repo / "deploy" / "selfhost", self.dir)
        sk.copy_workctl(shared.repo, self.repo / "tools" / "workctl")
        app, migrator, postgres = sk.rand_hex(), sk.rand_hex(), sk.rand_hex()
        backup_key, tenant = sk.fernet_key(), sk.rand_secret()
        shared.kv["sh_backup_key"] = backup_key
        shared.kv["sh_tenant"] = tenant
        (self.dir / "db.env").write_text(db_env(postgres, app, migrator), encoding="utf-8")
        self.write_env(app, backup_key, NIL_OWNER, tenant)
        (self.dir / "release.env").write_text(f"SIDEKICK_API_IMAGE={shared.from_image}\n", encoding="utf-8")
        (self.dir / "drill.override.yaml").write_text(port_override(self.port), encoding="utf-8")
        (self.dir / "hindsight.env").write_text(hindsight_env(tenant), encoding="utf-8")
        for env_file in self.dir.glob("*.env"):
            env_file.chmod(0o600)
        if not shared.dry:
            step.read_bytes(["docker", "pull", shared.from_image])
        # README, "First start" step 3: the owner is created before the identity line can name it.
        create = ["run", "--rm", "-T", "api", "sidekick-admin", "create-user", "--login", "drill"]
        owner = sk.last_line(step.read(self.compose(*create, "--display-name", "Drill")))
        if not UUID.fullmatch(owner):
            raise StepFailed("create-user did not print a UUID")
        self.write_env(app, backup_key, owner, tenant)
        step.sh(self.compose("up", "-d", *WAIT))
        step.note(f"installed {shared.from_image} on 127.0.0.1:{self.port}")

    def marker(self, step: Step) -> None:
        kv = self.shared.kv
        token = f"drill-{sk.rand_hex8()}"
        kv["sh_marker"] = token
        kv["sh_hs"] = f"{token}-hs"
        self.psql(step, sk.marker_sql(token))
        expect_eq("marker row", self.psql(step, MARKER_QUERY), token)
        sk.hs_write(step, self.project, "hindsight", f"{token}-hs")
        expect_eq("Hindsight volume file", sk.hs_read(step, self.project, "hindsight"), f"{token}-hs")
        kv["sh_schema_before"] = self.schema(step)
        kv["sh_head_before"] = self.head(step)

    def update(self, step: Step) -> None:
        shared = self.shared
        if not shared.dry:
            step.read_bytes(["docker", "pull", shared.to_image])
        step.sh(self.update_sh("--apply", "--image", shared.to_image, "--cert-identity", shared.identity))
        journal = (self.dir / "update-state" / "journal.log").read_text(encoding="utf-8").splitlines()
        fields = journal[-1].split() if journal else []
        expect_eq("update journal", fields[1] if len(fields) > 1 else "", "DONE")
        pinned = (self.dir / "release.env").read_text(encoding="utf-8").splitlines()
        if f"SIDEKICK_API_IMAGE={shared.to_image}" not in pinned:
            raise StepFailed("release.env does not pin the new image")

    def verify_updated(self, step: Step) -> None:
        kv = self.shared.kv
        expect_eq("marker row after update", self.psql(step, MARKER_QUERY), kv["sh_marker"])
        expect_eq("Hindsight volume file after update", sk.hs_read(step, self.project, "hindsight"), kv["sh_hs"])
        before, after = kv["sh_schema_before"], self.schema(step)
        kv["sh_schema_after"] = after
        if int(after) > int(before):
            step.note(f"schema moved: {before} -> {after} migrations ({kv['sh_head_before']} -> {self.head(step)})")
        elif self.shared.allow_same_schema:
            step.note(f"schema unchanged ({after} migrations), accepted by --allow-same-schema")
        else:
            raise StepFailed(
                f"schema did not move ({before} -> {after}); the new image has no migration the old one lacked "
                "(--allow-same-schema)"
            )
        # The pre-update snapshot update.sh took must decrypt and still list the marker table.
        snapshots = sorted((self.dir / "update-state" / "snapshots").glob("sidekick-pre-*.dump.enc"))
        if not snapshots or snapshots[0].stat().st_size == 0:
            raise StepFailed("no pre-update snapshot")
        dump = step.read_bytes(self.update_sh("--decrypt-snapshot", str(snapshots[0])))
        if not dump:
            raise StepFailed("snapshot decrypted to nothing")
        listing = step.read_bytes(self.compose("exec", "-T", "postgres", "pg_restore", "-l"), stdin=dump)
        if b"drill_marker" not in listing:
            raise StepFailed("the pre-update snapshot does not list the marker table")

    def backup(self, step: Step) -> None:
        self.backups.mkdir(parents=True, exist_ok=True)
        pg_dump = ["exec", "-T", "postgres", "pg_dump", "-U", "postgres", "-d", "sidekick", "-Fc"]
        dump = step.read_bytes(self.compose(*pg_dump))
        (self.backups / "sidekick.dump.enc").write_bytes(self.crypto(step, "encrypt", dump))
        # The guide's archive: Hindsight stopped for the copy, the volume tarred by a one-off container of its image.
        image = sk.carrier_image(step, self.project, "hindsight")
        volume = sk.hindsight_volume(step, self.project)
        step.sh(self.compose("stop", "hindsight"))
        tar = ["docker", "run", "--rm", "--network", "none", "-v", f"{volume}:/src:ro", "--entrypoint", "tar", image]
        archive = step.read_bytes([*tar, "-C", "/src", "-czf", "-", "."])
        (self.backups / "hindsight.tar.gz.enc").write_bytes(self.crypto(step, "encrypt", archive))
        step.sh(self.compose("up", "-d", *WAIT, "hindsight"))
        for name in ("sidekick.dump.enc", "hindsight.tar.gz.enc"):
            sk.check_backup_file(self.backups / name, self.shared.kv["sh_marker"], "the backup")
        # A fresh restore must work from this set alone: the key file of selfhost.env is the only secret needed.
        plain = self.crypto(step, "decrypt", (self.backups / "hindsight.tar.gz.enc").read_bytes())
        expect_eq("decrypt round trip", sk.count_in_archive(plain, sk.MARKER_FILE), 1)

    def destroy(self, step: Step) -> None:
        step.sh(self.compose("down", "-v", "--remove-orphans"))
        expect_eq("volumes left after down -v", sk.project_volumes(step, self.project), 0)

    def key_closed(self, step: Step) -> None:
        encrypted = (self.backups / "sidekick.dump.enc").read_bytes()
        for key, what in ((sk.fernet_key(), "a wrong key"), ("", "an empty key")):
            done = self.crypto_with_key(step, key, "decrypt", encrypted)
            if done.rc == 0:
                raise StepFailed(f"{what} decrypted the backup")
            expect_eq(f"output with {what}", done.out.decode("utf-8", errors="replace").rstrip("\n"), "")

    def restore(self, step: Step) -> None:
        step.sh(self.compose("up", "-d", *WAIT, "postgres", "hindsight"))
        if step.succeeds(self.psql_argv(MARKER_QUERY)):
            raise StepFailed("the marker exists on a fresh volume; the drill would prove nothing")
        dump = self.crypto(step, "decrypt", (self.backups / "sidekick.dump.enc").read_bytes())
        if not dump:
            raise StepFailed("empty dump")
        restore = ["exec", "-T", "postgres", "pg_restore", "-U", "postgres", "-d", "sidekick"]
        step.sh(self.compose(*restore, "--exit-on-error", "--single-transaction"), stdin=dump)
        # The guide: stop Hindsight, empty the volume, unpack the archive, start it.
        image = sk.carrier_image(step, self.project, "hindsight")
        volume = sk.hindsight_volume(step, self.project)
        if sk.hs_present(step, self.project, "hindsight"):
            raise StepFailed("the Hindsight marker file exists on a fresh volume; the drill would prove nothing")
        step.sh(self.compose("stop", "hindsight"))
        archive = self.crypto(step, "decrypt", (self.backups / "hindsight.tar.gz.enc").read_bytes())
        unpack = "find /dst -mindepth 1 -delete && tar -C /dst -xzf -"
        run = ["docker", "run", "--rm", "-i", "--network", "none", "-v", f"{volume}:/dst", "--entrypoint", "sh", image]
        step.sh([*run, "-c", unpack], stdin=archive)
        step.sh(self.compose("run", "--rm", "-T", "--no-deps", "migrate"))
        step.sh(self.compose("up", "-d", *WAIT))

    def verify_restored(self, step: Step) -> None:
        kv = self.shared.kv
        expect_eq("marker row after restore", self.psql(step, MARKER_QUERY), kv["sh_marker"])
        expect_eq("Hindsight volume file after restore", sk.hs_read(step, self.project, "hindsight"), kv["sh_hs"])
        expect_eq("schema version after restore", self.schema(step), kv["sh_schema_after"])
