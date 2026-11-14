"""The second scenario of the drill: the work package with ``tools/work.sh``.

The same stations as the self-hosted one (install, marker, update, backup, destroy, restore), through the real
``work.sh``: its encrypted database and Hindsight backups with their own key, and the guided restore. The code route of
``work.sh update`` (git pull, build) is replaced by the released image: the new image goes into ``work.env`` and
``start`` recreates the stack, which runs the migrator again.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable

from . import drillsteps as sk
from .drillsteps import Run, Step, StepFailed, expect_eq

IMAGE_LINE = "SIDEKICK_WORK_API_IMAGE="
KEY_FILE_VARIABLE = "SIDEKICK_WORK_BACKUP_KEY_FILE"
MARKER_QUERY = "select token from public.drill_marker"


def work_env(port: int, image: str) -> str:
    return (
        "SIDEKICK_WORK_MODEL_BASE_URL=http://model.drill.invalid:8000/v1\nSIDEKICK_WORK_MEMORY_MODEL=drill-model\n"
        "SIDEKICK_WORK_INSTANCE_LABEL=Sidekick Drill\nSIDEKICK_WORK_LOCALE=en\nSIDEKICK_WORK_TIMEZONE=UTC\n"
        f"SIDEKICK_WORK_PORT={port}\nSIDEKICK_ENABLED_ROOMS=work\n{IMAGE_LINE}{image}\n"
    )


def with_image(text: str, image: str) -> str:
    """``work.env`` with the api image replaced (or added)."""
    kept = [line for line in text.splitlines() if not line.startswith(IMAGE_LINE)]
    return "\n".join([*kept, f"{IMAGE_LINE}{image}"]) + "\n"


class Work:
    name = "work"

    def __init__(self, shared: Run, project: str, port: int) -> None:
        self.shared = shared
        self.project = project
        self.port = port
        self.repo = shared.tmp / "work" / "repo"
        self.env_file = self.repo / "deploy" / "work" / "work.env"
        self.backups = self.repo / "deploy" / "work" / "backups"

    def steps(self) -> list[tuple[str, Callable[[Step], None]]]:
        return [
            ("install", self.install),
            ("marker", self.marker),
            ("update", self.update),
            ("verify-updated", self.verify_updated),
            ("backup", self.backup),
            ("destroy-volumes", self.destroy),
            ("fresh-stack", self.fresh),
            ("key-fails-closed", self.key_closed),
            ("restore", self.restore),
            ("verify-restored", self.verify_restored),
        ]

    # -- the stack ----------------------------------------------------------------------------------------------

    def wk_argv(self, *args: str) -> list[str]:
        return ["bash", "tools/work.sh", *args]

    def wk_env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        return {"SIDEKICK_WORK_PROJECT": self.project, "SIDEKICK_WORK_LANG": "en", **(extra or {})}

    def wk(self, step: Step, *args: str, stdin: bytes | None = None, env: dict[str, str] | None = None) -> None:
        """``work.sh`` from the scenario's own checkout; a failure fails the step."""
        step.sh(self.wk_argv(*args), stdin=stdin, env=self.wk_env(env), cwd=self.repo)

    def wk_status(self, step: Step, *args: str, env: dict[str, str] | None = None) -> int:
        """The exit status of ``work.sh`` (its output goes to the log)."""
        return step.call(self.wk_argv(*args), env=self.wk_env(env), cwd=self.repo, merge=True).rc

    def postgres_argv(self, step: Step, sql: str) -> list[str]:
        listed = step.read(
            [
                "docker",
                "ps",
                "-q",
                "--filter",
                f"{sk.CARRIER_PROJECT}{self.project}",
                "--filter",
                "label=com.docker.compose.service=postgres",
            ]
        )
        container = sk.first_line(listed)
        if not container:
            raise StepFailed("no postgres container")
        return [
            "docker",
            "exec",
            container,
            "psql",
            "-U",
            "postgres",
            "-d",
            "sidekick",
            "-v",
            "ON_ERROR_STOP=1",
            "-Atc",
            sql,
        ]

    def pg(self, step: Step, sql: str) -> str:
        return step.read(self.postgres_argv(step, sql))

    def schema(self, step: Step) -> str:
        return self.pg(step, "select count(*) from _yoyo_migration")

    def marker_present(self, step: Step) -> bool:
        return step.succeeds(self.postgres_argv(step, MARKER_QUERY))

    # -- the steps ----------------------------------------------------------------------------------------------

    def install(self, step: Step) -> None:
        shared = self.shared
        (self.repo / "tools").mkdir(parents=True, exist_ok=True)
        (self.repo / "deploy" / "work").mkdir(parents=True, exist_ok=True)
        shutil.copy(shared.repo / "tools" / "work.sh", self.repo / "tools" / "work.sh")
        # work.sh delegates its logic to the standard-library package tools/workctl.
        sk.copy_workctl(shared.repo, self.repo / "tools" / "workctl")
        sk.copy_selfhost_files(shared.repo / "deploy" / "selfhost", self.repo / "deploy" / "selfhost")
        for name in ("compose.yaml", "gateway.haproxy.cfg", "work.env.example"):
            shutil.copy(shared.repo / "deploy" / "work" / name, self.repo / "deploy" / "work" / name)
        self.env_file.write_text(work_env(self.port, shared.from_image), encoding="utf-8")
        self.env_file.chmod(0o600)
        if not shared.dry:
            step.read_bytes(["docker", "pull", shared.from_image])
        self.wk(step, "init")
        self.wk(step, "start")
        step.note(f"installed {shared.from_image}, gateway on 127.0.0.1:{self.port}")

    def marker(self, step: Step) -> None:
        kv = self.shared.kv
        token = f"drill-{sk.rand_hex8()}"
        kv["wk_marker"] = token
        kv["wk_hs"] = f"{token}-hs"
        self.pg(step, sk.marker_sql(token))
        expect_eq("marker row", self.pg(step, MARKER_QUERY), token)
        sk.hs_write(step, self.project, "hindsight", f"{token}-hs")
        expect_eq("Hindsight volume file", sk.hs_read(step, self.project, "hindsight"), f"{token}-hs")
        kv["wk_schema_before"] = self.schema(step)

    def update(self, step: Step) -> None:
        # What `work.sh update` does first: a backup of the database and the memory.
        self.wk(step, "backup")
        if not self.shared.dry:
            step.read_bytes(["docker", "pull", self.shared.to_image])
        pending = self.env_file.with_name("work.env.tmp")
        pending.write_text(
            with_image(self.env_file.read_text(encoding="utf-8"), self.shared.to_image), encoding="utf-8"
        )
        pending.replace(self.env_file)
        self.wk(step, "start")

    def verify_updated(self, step: Step) -> None:
        kv = self.shared.kv
        expect_eq("marker row after update", self.pg(step, MARKER_QUERY), kv["wk_marker"])
        expect_eq("Hindsight volume file after update", sk.hs_read(step, self.project, "hindsight"), kv["wk_hs"])
        before, after = kv["wk_schema_before"], self.schema(step)
        kv["wk_schema_after"] = after
        if int(after) > int(before):
            step.note(f"schema moved: {before} -> {after} migrations")
        elif self.shared.allow_same_schema:
            step.note(f"schema unchanged ({after} migrations), accepted by --allow-same-schema")
        else:
            raise StepFailed(f"schema did not move ({before} -> {after}) (--allow-same-schema)")

    def backup(self, step: Step) -> None:
        self.wk(step, "backup")
        database = sorted(self.backups.glob("sidekick-*.sql.enc"))[-1:]
        if not database:
            raise StepFailed("no database backup")
        stamp = database[0].name.removeprefix("sidekick-").removesuffix(".sql.enc")
        memory = self.backups / f"hindsight-{stamp}.tar.gz.enc"
        self.shared.kv["wk_ts"] = stamp
        for file in (database[0], memory):
            sk.check_backup_file(file, self.shared.kv["wk_marker"], "a backup")
        key = self.repo / "deploy" / "work" / "secrets" / "backup.key"
        if not key.is_file() or key.stat().st_size == 0:
            raise StepFailed("no backup key")
        (self.shared.tmp / "wrong.key").write_text(sk.fernet_key() + "\n", encoding="utf-8")

    def destroy(self, step: Step) -> None:
        step.sh(["docker", "compose", "-p", self.project, "down", "-v", "--remove-orphans"])
        expect_eq("volumes left after down -v", sk.project_volumes(step, self.project), 0)

    def fresh(self, step: Step) -> None:
        self.wk(step, "start")
        if self.marker_present(step):
            raise StepFailed("the marker exists on a fresh stack; the drill would prove nothing")

    def key_closed(self, step: Step) -> None:
        stamp = self.shared.kv["wk_ts"]
        wrong = {KEY_FILE_VARIABLE: str(self.shared.tmp / "wrong.key")}
        if self.wk_status(step, "restore", stamp, env=wrong) == 0:
            raise StepFailed("restore accepted a wrong key")
        missing = {KEY_FILE_VARIABLE: str(self.shared.tmp / "no-such.key")}
        if self.wk_status(step, "restore", stamp, env=missing) == 0:
            raise StepFailed("restore went on without a key")
        if self.marker_present(step):
            raise StepFailed("a refused restore changed the database")

    def restore(self, step: Step) -> None:
        self.wk(step, "restore", self.shared.kv["wk_ts"], "--apply", stdin=f"{self.project}\n".encode())

    def verify_restored(self, step: Step) -> None:
        kv = self.shared.kv
        expect_eq("marker row after restore", self.pg(step, MARKER_QUERY), kv["wk_marker"])
        expect_eq("Hindsight volume file after restore", sk.hs_read(step, self.project, "hindsight"), kv["wk_hs"])
        owner = self.pg(step, "select count(*) from sidekick.users where username = 'jobb'")
        expect_eq("owner user after restore", owner, 1)
        expect_eq("schema version after restore", self.schema(step), kv["wk_schema_after"])
