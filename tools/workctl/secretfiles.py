"""The secret files in ``deploy/work/secrets/``: generation, and single-line edits (the model server's key).

Every file is created with mode 600 from the start (never widened and narrowed again), nothing is printed, and
a file that already exists is never overwritten: it may belong to a database that already exists, whose
passwords cannot be changed.
"""

from __future__ import annotations

import base64
import os
import re
import secrets
import tempfile
from pathlib import Path

DB_FILE = "db.env"
APP_FILE = "sidekick.env"
HINDSIGHT_FILE = "hindsight.env"
MODEL_KEY_NAME = "WORK_MODEL_API_KEY"
HINDSIGHT_KEY_NAME = "HINDSIGHT_API_LLM_API_KEY"
# Hindsight insists on a value even when the server does not check it (upstream's own local-LLM example).
NO_KEY = "not-needed"


class SecretsExist(FileExistsError):
    """A secrets file is already there (or a symlink in its place)."""


def rand_hex() -> str:
    return secrets.token_hex(32)


def rand_b64() -> str:
    return base64.b64encode(secrets.token_bytes(48)).decode("ascii")


def _create(path: Path, text: str) -> None:
    """Write a new file with mode 600; fails if the path exists (a symlink counts)."""
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise SecretsExist(str(path)) from error
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)


def _hindsight_text(example: str, gateway_name: str, tenant_key: str) -> str:
    """The self-hosted example with provider, URL, model and keys replaced (the other settings are reused, so
    there is one copy of them; compose overrides provider, URL, model and language per work.env)."""
    replacements = [
        ("HINDSIGHT_API_LLM_PROVIDER", "openai"),
        ("HINDSIGHT_API_LLM_BASE_URL", f"http://{gateway_name}/v1"),
        ("HINDSIGHT_API_LLM_MODEL", "set-in-work-env"),
        (HINDSIGHT_KEY_NAME, NO_KEY),
        ("HINDSIGHT_API_TENANT_API_KEY", tenant_key),
    ]
    lines = example.split("\n")
    for key, value in replacements:
        lines = [f"{key}={value}" if line.startswith(f"{key}=") else line for line in lines]
    return "\n".join(lines)


def generate_secrets(secrets_dir: Path, hindsight_example: Path, gateway_name: str) -> None:
    """Create db.env, sidekick.env and hindsight.env; raises SecretsExist and writes nothing if any of the
    three is already there."""
    for name in (APP_FILE, DB_FILE, HINDSIGHT_FILE):
        target = secrets_dir / name
        if target.exists() or target.is_symlink():
            raise SecretsExist(str(target))
    # Read every input before the first file exists, so a missing example leaves nothing half-made behind.
    example = hindsight_example.read_text(encoding="utf-8")
    app, migrator, postgres, hindsight = rand_hex(), rand_hex(), rand_hex(), rand_b64()
    db_url = "postgresql+psycopg://{user}:{password}@postgres:5432/sidekick"
    texts = {
        DB_FILE: f"POSTGRES_PASSWORD={postgres}\n"
        f"SIDEKICK_DB_APP_PASSWORD={app}\n"
        f"SIDEKICK_DB_MIGRATOR_PASSWORD={migrator}\n"
        f"SIDEKICK_MIGRATION_DATABASE_URL={db_url.format(user='sidekick_migrator', password=migrator)}\n",
        APP_FILE: f"SIDEKICK_DATABASE_URL={db_url.format(user='sidekick_app', password=app)}\n"
        f"SIDEKICK_CURSOR_SIGNING_SECRET={rand_b64()}\n"
        f"SIDEKICK_TOKEN_PEPPER={rand_b64()}\n"
        f"SIDEKICK_MEMORY_HINDSIGHT_API_TOKEN={hindsight}\n"
        f"SIDEKICK_MEMORY_ID_DERIVATION_KEY={rand_b64()}\n",
        HINDSIGHT_FILE: _hindsight_text(example, gateway_name, hindsight),
    }
    created: list[Path] = []
    try:
        for name, text in texts.items():
            _create(secrets_dir / name, text)
            created.append(secrets_dir / name)
    except BaseException:
        # A failed init must not leave files behind: the next init refuses to overwrite them.
        for path in created:
            path.unlink(missing_ok=True)
        raise


def _rewrite(path: Path, keep: str, append: str | None) -> None:
    """Rewrite ``path`` without the lines that start with ``keep`` (a "KEY=" prefix), then append a line,
    through a 600 temporary file in the same directory and an atomic rename."""
    # A missing file counts as empty (the line is added to a new file), as the shell version did.
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    lines = [line for line in lines if not line.startswith(keep)]
    if append is not None:
        lines.append(append)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".tmp.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("".join(f"{line}\n" for line in lines))
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    except BaseException:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def set_line(path: Path, key: str, value: str) -> None:
    """Replace or append KEY=value without printing anything."""
    _rewrite(path, f"{key}=", f"{key}={value}")


def drop_line(path: Path, key: str) -> None:
    """Remove KEY=... (no output, mode 600 kept)."""
    _rewrite(path, f"{key}=", None)


def apply_model_key(secrets_dir: Path, key: str) -> None:
    """Write the model server's API key into the two 600 files; an empty key means "the server checks nothing".
    The api container only gets it for the status probe, under a name without the SIDEKICK_ prefix (Settings
    refuses unknown SIDEKICK_ names)."""
    if key:
        set_line(secrets_dir / APP_FILE, MODEL_KEY_NAME, key)
        set_line(secrets_dir / HINDSIGHT_FILE, HINDSIGHT_KEY_NAME, key)
    else:
        drop_line(secrets_dir / APP_FILE, MODEL_KEY_NAME)
        set_line(secrets_dir / HINDSIGHT_FILE, HINDSIGHT_KEY_NAME, NO_KEY)


def stored_model_key(secrets_dir: Path) -> str:
    """The key currently stored (empty when none); the last WORK_MODEL_API_KEY= line wins."""
    path = secrets_dir / APP_FILE
    if not path.is_file():
        return ""
    pattern = re.compile(rf"^{MODEL_KEY_NAME}=(.*)$")
    found = ""
    for line in path.read_text(encoding="utf-8").split("\n"):
        match = pattern.match(line)
        if match:
            found = match.group(1)
    return found
