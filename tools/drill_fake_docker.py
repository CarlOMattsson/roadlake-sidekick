"""The fake ``docker`` of ``tools/drill.sh --dry-run``: a small state file, a log of every call, and nothing real.

It stands in for the docker commands that update.sh, tools/work.sh and the drill itself run, keeps the running
services, the schema version, a marker row, the user and the volumes in a JSON state file, and refuses (exit 99) any
project, volume or bind that is not an ``sk-drill-`` one. The environment steers it:

* ``DRILL_FAKE_STATE``  the state file
* ``DRILL_FAKE_LOG``    the file every call is appended to (one JSON line per call)
* ``DRILL_FAKE_FROM`` / ``DRILL_FAKE_TO``  the two images; the schema is 10 for the first and 12 for the second
* ``DRILL_FAKE_FAIL``   a comma list of ways to misbehave, to prove the drill notices: ``lose-marker``,
  ``no-schema-move``, ``wrong-key-accepted``, ``lose-hindsight``

Standard library only; it runs with the host's ``python3 -I``. The exit status is the fake docker's own.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import sys
import tarfile
from collections.abc import Mapping, Sequence
from typing import Any, NoReturn

MAGIC = b"SIDEKICK-SNAPSHOT-1\n"
USER_ID = "00000000-0000-4000-8000-000000000001"
PROJECT_PREFIX = "sk-drill-"
FROM_SCHEMA, TO_SCHEMA = 10, 12
COMPOSE_VALUE_FLAGS = (
    "--wait-timeout",
    "--pull",
    "--scale",
    "-t",
    "--timeout",
    "--status",
)
RUN_VALUE_FLAGS = ("-e", "-v", "-u", "--entrypoint", "-w", "--name")
DOCKER_RUN_VALUE_FLAGS = (
    "-v",
    "--entrypoint",
    "--network",
    "-e",
    "-u",
    "--name",
    "--tmpfs",
    "--cap-drop",
    "--security-opt",
    "--memory",
    "--pids-limit",
)


class Exit(Exception):
    """A command that ends: the exit status, and the text for stderr when there is one."""

    def __init__(self, code: int, text: str = "") -> None:
        super().__init__(code, text)
        self.code = code
        self.text = text


def die(code: int, text: str = "") -> NoReturn:
    raise Exit(code, text)


def short(item: str) -> str:
    return item if len(item) <= 120 else f"<{len(item)} chars>"


def project_ok(name: str) -> bool:
    return name.startswith(PROJECT_PREFIX)


def env_file_value(files: Sequence[str], keys: Sequence[str]) -> str:
    """The last value any of ``keys`` has in the env ``files`` (unreadable files are skipped)."""
    value = ""
    for path in files:
        try:
            with open(path, encoding="utf-8") as handle:
                lines = handle.read().splitlines()
        except OSError:
            continue
        for line in lines:
            for key in keys:
                if line.startswith(key + "="):
                    value = line.split("=", 1)[1]
    return value


def tar_of(files: Mapping[str, str]) -> bytes:
    """A gzip tarball with a root directory entry and one file per item."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        root = tarfile.TarInfo(".")
        root.type = tarfile.DIRTYPE
        root.mode = 0o755
        archive.addfile(root)
        for name, content in files.items():
            data = content.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def untar(data: bytes) -> dict[str, str]:
    """The regular files of a tarball made by ``tar_of``, by name."""
    files = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member in archive.getmembers():
            if member.isfile():
                extracted = archive.extractfile(member)
                assert extracted is not None
                files[member.name.lstrip("./")] = extracted.read().decode()
    return files


def services_of(items: Sequence[str]) -> list[str]:
    """The service names among the arguments of a compose subcommand (flags and their values are skipped)."""
    names, skip = [], False
    for item in items:
        if skip:
            skip = False
        elif item in COMPOSE_VALUE_FLAGS:
            skip = True
        elif not item.startswith("-"):
            names.append(item)
    return names


def out(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


class FakeDocker:
    """One call of the fake docker: the state is read first and written whenever a command changes it."""

    def __init__(
        self,
        *,
        state_path: str,
        log_path: str,
        from_image: str,
        to_image: str,
        fail: frozenset[str],
        environ: Mapping[str, str],
    ) -> None:
        self.state_path = state_path
        self.log_path = log_path
        self.to_image = to_image
        self.fail = fail
        self.environ = environ
        self.schema_of = {
            from_image: FROM_SCHEMA,
            to_image: FROM_SCHEMA if "no-schema-move" in fail else TO_SCHEMA,
        }
        self.state: dict[str, Any] = self._load()

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> FakeDocker:
        return cls(
            state_path=environ["DRILL_FAKE_STATE"],
            log_path=environ["DRILL_FAKE_LOG"],
            from_image=environ["DRILL_FAKE_FROM"],
            to_image=environ["DRILL_FAKE_TO"],
            fail=frozenset(
                item for item in environ.get("DRILL_FAKE_FAIL", "").split(",") if item
            ),
            environ=environ,
        )

    def _load(self) -> dict[str, Any]:
        try:
            with open(self.state_path, encoding="utf-8") as handle:
                return json.load(handle)
        except FileNotFoundError:
            return {
                "running": {},
                "image": "",
                "schema": 0,
                "marker": None,
                "jobb": False,
                "volumes": {},
                "db": False,
            }

    def save(self) -> None:
        # Atomic: pipeline stages (docker run ... tar | docker ... encrypt) start together and the second one reads the
        # state while the first saves, so a plain truncate-and-write would let it see an empty, half-written file.
        scratch = f"{self.state_path}.{os.getpid()}"
        with open(scratch, "w", encoding="utf-8") as handle:
            json.dump(self.state, handle)
        os.replace(scratch, self.state_path)

    def run(self, argv: Sequence[str]) -> int:
        """Log the call, run it, and return the exit status (its stderr text goes to stderr)."""
        with open(self.log_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"argv": [short(item) for item in argv]}) + "\n")
        try:
            self._dispatch(list(argv))
        except Exit as ended:
            if ended.text:
                sys.stderr.write(ended.text + "\n")
            return ended.code
        return 0

    # -- the database and the backup crypto in a container ------------------------------------------------------

    def reset_db(self) -> None:
        self.state.update(marker=None, schema=0, jobb=False, db=True)

    def apply_dump(self, text: str) -> None:
        marker = re.search(r"^MARKER=(.*)$", text, re.M)
        schema = re.search(r"^SCHEMA=(\d+)$", text, re.M)
        jobb = re.search(r"^JOBB=(\d)$", text, re.M)
        self.state["marker"] = (marker.group(1) or None) if marker else None
        self.state["schema"] = int(schema.group(1)) if schema else self.state["schema"]
        self.state["jobb"] = bool(jobb and jobb.group(1) == "1")
        self.save()

    def crypto(self, args: Sequence[str], key_from_env: bool) -> None:
        source = args[3] if len(args) > 3 else ""
        mode = (
            args[4]
            if len(args) > 4
            else ("decrypt" if ").decrypt(" in source else "encrypt")
        )
        key = (
            self.environ.get("SIDEKICK_BACKUP_ENCRYPTION_KEY", "")
            if key_from_env
            else "ENVFILE"
        )
        fingerprint = hashlib.sha256(key.encode()).hexdigest()[:16].encode()
        raw = sys.stdin.buffer.read()
        if mode == "encrypt":
            if not raw or not key:
                die(1, "backup encrypt failed: ValueError")
            sys.stdout.buffer.write(MAGIC + fingerprint + b"\n" + base64.b64encode(raw))
            die(0)
        if not raw.startswith(MAGIC):
            die(1, "backup decrypt failed: ValueError")
        header, _, body = raw[len(MAGIC) :].partition(b"\n")
        if (header != fingerprint or not key) and "wrong-key-accepted" not in self.fail:
            die(1, "backup decrypt failed: InvalidToken")
        sys.stdout.buffer.write(base64.b64decode(body))
        die(0)

    def psql(self, rest: Sequence[str], text: str) -> None:
        state = self.state
        if "--single-transaction" in rest:
            self.apply_dump(sys.stdin.read())
            die(0)
        if "CREATE DATABASE sidekick" in text:
            self.reset_db()
            self.save()
        if "count(*) from _yoyo_migration" in text:
            out("%d\n" % state["schema"])
        elif "migration_id from _yoyo_migration" in text:
            out("%03d_head\n" % state["schema"])
        elif "drill_marker" in text:
            if "CREATE TABLE" in text:
                token = re.search(r"VALUES \('([^']+)'\)", text)
                if token and "lose-marker" not in self.fail:
                    state["marker"] = token.group(1)
                    self.save()
            elif state["marker"]:
                out(state["marker"] + "\n")
            else:
                die(1, 'ERROR:  relation "public.drill_marker" does not exist')
        elif "from sidekick.users" in text:
            if "username = 'jobb'" in text and "count(*)" not in text:
                out(USER_ID + "\n" if state["jobb"] else "")
            elif "count(*)" in text:
                out("1\n" if state["jobb"] else "0\n")
            elif state["jobb"]:
                out("1\n")
        die(0)

    def in_container(self, rest: Sequence[str], key_from_env: bool = False) -> None:
        if not rest:
            die(0)
        tool, text = rest[0], " ".join(rest)
        if tool == "psql":
            self.psql(rest, text)
        if tool == "pg_dump":
            state = self.state
            out(
                "MARKER=%s\nSCHEMA=%d\nJOBB=%d\n-- PostgreSQL database dump complete\n"
                % (state["marker"] or "", state["schema"], 1 if state["jobb"] else 0)
            )
            die(0)
        if tool == "pg_restore":
            data = sys.stdin.read()
            if "-l" in rest:
                out(
                    "TABLE public drill_marker\n"
                    if re.search(r"^MARKER=.+$", data, re.M)
                    else ""
                )
            else:
                self.apply_dump(data)
            die(0)
        if tool == "sidekick-admin" and "create-user" in rest:
            self.state["jobb"] = True
            self.save()
            out(USER_ID + "\n")
            die(0)
        if tool == "python" and "-I" in rest and "-c" in rest:
            self.crypto(rest, key_from_env)
        die(0)

    # -- docker compose ----------------------------------------------------------------------------------------

    def compose(self, args: list[str]) -> None:
        project, files, profiles, env_files = "", [], [], []
        while args and args[0].startswith("-"):
            flag = args.pop(0)
            value = args.pop(0)
            if flag == "-p":
                project = value
            elif flag == "-f":
                files.append(value)
            elif flag == "--env-file":
                env_files.append(value)
            elif flag == "--profile":
                profiles.append(value)
        if project and not project_ok(project):
            die(99, "fake docker: refusing project " + project)
        if not args:
            die(0)
        sub, rest = args[0], args[1:]
        image = (
            self.environ.get("SIDEKICK_API_IMAGE")
            or self.environ.get("SIDEKICK_WORK_API_IMAGE")
            or env_file_value(
                env_files, ("SIDEKICK_API_IMAGE", "SIDEKICK_WORK_API_IMAGE")
            )
        )
        if sub == "config":
            out(
                "postgres:18.4-alpine\nghcr.io/vectorize-io/hindsight@sha256:"
                + "d" * 64
                + "\n"
            )
        elif sub == "ps":
            names = services_of(rest)
            if names and self.state["running"].get(names[-1]):
                out("cid-%s\n" % names[-1])
        elif sub == "up":
            self.compose_up(project, profiles, rest, image)
        elif sub == "stop":
            running = self.state["running"]
            for name in services_of(rest) or list(running):
                running[name] = False
            self.save()
        elif sub == "down":
            self.state.update(
                running={}, schema=0, marker=None, jobb=False, volumes={}, db=False
            )
            self.save()
        elif sub == "run":
            self.compose_run(rest, image)
        elif sub == "exec":
            names = services_of(rest)
            self.in_container(rest[rest.index(names[0]) + 1 :] if names else [])
        die(0)

    def volume_for(self, project: str, name: str) -> str:
        for volume, labels in self.state["volumes"].items():
            if (
                labels.get("com.docker.compose.project") == project
                and labels.get("com.docker.compose.volume") == name
            ):
                return volume
        return ""

    def compose_up(
        self, project: str, profiles: Sequence[str], rest: Sequence[str], image: str
    ) -> None:
        state = self.state
        names = services_of(rest)
        if not names:
            names = ["postgres", "api", "automation-worker"]
            if "memory" in profiles:
                names += ["memory-worker", "hindsight"]
        if "postgres" in names and not state["db"]:
            self.reset_db()
        if "hindsight" in names and not self.volume_for(project, "hindsight_pg0"):
            state["volumes"][project + "_hindsight_pg0"] = {
                "com.docker.compose.project": project,
                "com.docker.compose.volume": "hindsight_pg0",
            }
        for name in names:
            state["running"][name] = True
        if "api" in names:
            if image:
                state["image"] = image
            state["schema"] = max(state["schema"], self.schema_of.get(image, 0))
        self.save()

    def compose_run(self, rest: Sequence[str], image: str) -> None:
        key_from_env, items, skip = False, [], False
        for index, item in enumerate(rest):
            if skip:
                skip = False
                continue
            if item in RUN_VALUE_FLAGS:
                key_from_env = key_from_env or (
                    item == "-e"
                    and rest[index + 1].startswith("SIDEKICK_BACKUP_ENCRYPTION_KEY")
                )
                skip = True
            elif not item.startswith("-"):
                items = list(rest[index:])
                break
        service, command = items[0], items[1:]
        if service == "migrate":
            self.state["schema"] = max(
                self.state["schema"], self.schema_of.get(image, 0)
            )
            self.save()
            die(0)
        if service == "api":
            self.in_container(command, key_from_env)
        die(0)

    # -- docker itself -----------------------------------------------------------------------------------------

    def docker_run(self, args: Sequence[str]) -> None:
        volume, entrypoint, rest, skip, key_from_env = "", "", [], False, False
        for index, item in enumerate(args):
            if skip:
                skip = False
                continue
            if item in DOCKER_RUN_VALUE_FLAGS:
                value = args[index + 1]
                if item == "-v":
                    volume = value.split(":")[0]
                elif item == "--entrypoint":
                    entrypoint = value
                elif item == "-e":
                    key_from_env = key_from_env or value.startswith(
                        "SIDEKICK_BACKUP_ENCRYPTION_KEY"
                    )
                skip = True
            elif not item.startswith("-"):
                rest = list(args[index + 1 :])
                break
        if (
            entrypoint == "python"
        ):  # the backup encryption, in a container without a volume
            self.crypto([entrypoint, *rest], key_from_env)
        if volume and not project_ok(volume):
            die(99, "fake docker: refusing volume " + volume)
        if volume not in self.state["volumes"]:
            die(1, "no such volume")
        files = self.state["volumes"][volume].setdefault("files", {})
        script = " ".join(rest)
        if entrypoint == "tar":
            sys.stdout.buffer.write(tar_of(files))
        elif entrypoint == "cat":
            name = rest[0].rsplit("/", 1)[-1]
            if name not in files:
                die(1, "cat: no such file")
            out(files[name])
        elif entrypoint == "sh" and "tar -C /dst -xzf" in script:
            data = sys.stdin.buffer.read()
            files.clear()
            if "lose-hindsight" not in self.fail:
                files.update(untar(data))
        elif entrypoint == "sh" and "drill-marker.txt" in script:
            token = re.search(r"printf '%s' '([^']+)'", script)
            files["drill-marker.txt"] = token.group(1) if token else ""
        if (
            entrypoint == "sh"
        ):  # only these two change the state; a read-only tar or cat must not rewrite it
            self.save()
        die(0)

    def image_inspect(self, argv: Sequence[str]) -> None:
        if "-f" in argv:
            fmt, ref = argv[argv.index("-f") + 1], argv[-1]
            if "min-upgrade-from" in fmt:
                out("0.1.0\n")
            elif "image.version" in fmt:
                out(("0.2.0" if ref == self.to_image else "0.1.0") + "\n")
            elif "migration-class" in fmt:
                out("expand\n")
        die(0)

    def inspect(self, argv: Sequence[str]) -> None:
        fmt = (
            argv[argv.index("-f") + 1]
            if "-f" in argv
            else argv[argv.index("--format") + 1]
        )
        cid = argv[-1]
        running = self.state["running"].get(cid.replace("cid-", "", 1))
        if (
            "State.Health" in fmt
        ):  # update.sh worker_ready: "<status> <health>", no healthcheck declared
            out("running none\n" if running else "exited none\n")
        elif "State.Status" in fmt:
            out("running no\n" if running else "exited no\n")
        elif ".Name" in fmt:
            out("/" + cid + "\n")
        else:
            out(self.state["image"] + "\n")
        die(0)

    def ps(self, argv: Sequence[str]) -> None:
        service = ""
        for item in argv:
            if item.startswith("label=com.docker.compose.service="):
                service = item.split("=", 2)[2]
            if item.startswith("label=com.docker.compose.project=") and not project_ok(
                item.split("=", 2)[2]
            ):
                die(99, "fake docker: refusing project")
        if service and self.state["running"].get(service):
            out(
                "cid-%s\n" % service
                if "-q" in argv
                else "fake/%s@sha256:%s\n" % (service, "c" * 64)
            )
        die(0)

    def volume(self, argv: Sequence[str]) -> None:
        sub = argv[1] if len(argv) > 1 else ""
        volumes = self.state["volumes"]
        if sub == "ls":
            wanted = {
                item.split("=", 1)[1].split("=", 1)[0]: item.split("=", 1)[1].split(
                    "=", 1
                )[1]
                for item in argv
                if item.startswith("label=")
            }
            for name, labels in volumes.items():
                if all(labels.get(key) == value for key, value in wanted.items()):
                    out(name + "\n")
        elif sub == "create":
            name = argv[-1]
            if not project_ok(name):
                die(99, "fake docker: refusing volume " + name)
            labels = {}
            for index, item in enumerate(argv):
                if item == "--label":
                    key, _, value = argv[index + 1].partition("=")
                    labels[key] = value
            volumes[name] = labels
            self.save()
        elif sub == "rm":
            if not project_ok(argv[-1]):
                die(99, "fake docker: refusing volume " + argv[-1])
            volumes.pop(argv[-1], None)
            self.save()
        die(0)

    def _dispatch(self, argv: list[str]) -> None:
        if not argv:
            die(0)
        cmd = argv[0]
        if cmd == "compose":
            self.compose(argv[1:])
        elif cmd == "image" and argv[1:2] == ["inspect"]:
            self.image_inspect(argv)
        elif cmd == "inspect":
            self.inspect(argv)
        elif cmd == "ps":
            self.ps(argv)
        elif cmd == "exec":
            names = [item for item in argv[1:] if not item.startswith("-")]
            self.in_container(argv[1:][argv[1:].index(names[0]) + 1 :] if names else [])
        elif cmd == "volume":
            self.volume(argv)
        elif cmd == "run":
            self.docker_run(argv[1:])
        die(0)


def main(argv: Sequence[str] | None = None) -> int:
    return FakeDocker.from_environ(os.environ).run(
        sys.argv[1:] if argv is None else argv
    )


if __name__ == "__main__":
    sys.exit(main())
