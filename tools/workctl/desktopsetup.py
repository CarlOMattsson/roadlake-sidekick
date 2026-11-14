"""What ``start``, ``update`` and ``restore`` do last: check that the image has the stdio entry point, make sure the
user Claude Desktop acts as exists in the database, and write the Claude Desktop entry file."""

from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
from pathlib import Path

from . import desktopconfig, owner
from .stack import Stack, Stop

OWNER_LOGIN = "jobb"
OWNER_NAME = "Sidekick Work"
CONFIG_FILE = "claude_desktop_config.json"


def _stored_owner(stack: Stack) -> str:
    try:
        return "".join((stack.secrets / "user-id").read_text(encoding="utf-8").split())
    except OSError:
        return ""


def publish_owner(stack: Stack, user_id: str) -> None:
    """secrets/user-id, replaced as a whole and mode 600."""
    descriptor, tmp_name = tempfile.mkstemp(dir=stack.secrets, prefix=".tmp.")
    with os.fdopen(descriptor, "w", encoding="ascii") as handle:
        handle.write(user_id + "\n")
    os.replace(tmp_name, stack.secrets / "user-id")


def _create_owner(stack: Stack) -> str | None:
    """A new user jobb through the api's admin command (it asks for no password and prints the UUID)."""
    with tempfile.TemporaryFile() as out:
        argv = ["exec", "-T", "api", "sidekick-admin", "create-user", "--login", OWNER_LOGIN]
        with open(os.devnull, "rb") as nothing:
            created = stack.compose_into(out, nothing, *argv, "--display-name", OWNER_NAME)
        out.seek(0)
        printed = "".join(out.read().decode("utf-8", errors="replace").split())
    return printed if created and owner.is_uuid(printed) else None


def ensure_owner(stack: Stack) -> None:
    """The database is the truth, secrets/user-id only remembers its UUID: the file counts only while that user
    exists in the database. A user-id left from another database (a new, empty data volume) is replaced by the user
    jobb of this database if it has one, else by a new one. Needs the running api (the database is migrated by then)."""
    stored = _stored_owner(stack)
    if owner.is_uuid(stored):
        found = stack.db_scalar(f"select 1 from sidekick.users where id = '{stored}'")  # noqa: S608 - a validated UUID
        if found is None:
            stack.errf("user_fail", stack.log)
            raise Stop(1)
        if found == "1":
            return
        stack.say("owner_stale")
    existing = stack.db_scalar(f"select id from sidekick.users where username = '{OWNER_LOGIN}'")  # noqa: S608 - a constant
    if existing is None:
        stack.errf("user_fail", stack.log)
        raise Stop(1)
    user_id = existing if owner.is_uuid(existing) else _create_owner(stack)
    if user_id is None:
        stack.errf("user_fail", stack.log)
        raise Stop(1)
    publish_owner(stack, user_id)


def write_desktop_config(stack: Stack) -> None:
    """Claude Desktop starts local programs only, with a minimal PATH. The entry runs Sidekick's stdio server inside
    the running api container: ``docker exec -i`` (not ``docker compose exec``, which would need the compose files
    and every derived variable), the docker binary and the container by absolute path/name. The owner is passed with
    -e; the rest of the settings are the container's own. No token: the process is trusted because the OS user that
    can run docker already holds the database credentials."""
    docker_bin = shutil.which("docker") or ""
    if not docker_bin.startswith("/"):
        stack.errf("desktop_nodocker")
        raise Stop(1)
    name = stack.docker_read("inspect", "--format", "{{.Name}}", stack.container_id("api"))
    if name is None:
        raise Stop(1)
    out = stack.secrets / CONFIG_FILE
    desktopconfig.write_desktop_config(out, docker_bin, name.rstrip("\n").removeprefix("/"), _stored_owner(stack))
    stack.sayf("desktop_written", out)
    stack.say("desktop_hint")


def desktop_setup(stack: Stack) -> None:
    if not stack.compose("exec", "-T", "api", "python", "-c", "import sidekick.mcp.stdio"):
        stack.errf("old_image")
        raise Stop(1)
    ensure_owner(stack)
    write_desktop_config(stack)


def drop_owner(stack: Stack) -> None:
    with contextlib.suppress(FileNotFoundError):
        Path(stack.secrets / "user-id").unlink()
