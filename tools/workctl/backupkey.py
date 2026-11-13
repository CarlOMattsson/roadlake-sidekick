"""The key that encrypts the backups: a file of its own, mode 600, generated on the first backup and kept out of the
backup directory. It fails closed: a missing key is never replaced while encrypted backups exist, because a new
key would make them unreadable. The content is never printed."""

from __future__ import annotations

import base64
import contextlib
import os
import re
import secrets
import tempfile
from pathlib import Path

from .secretfiles import fsync_path

# A Fernet key is 32 random bytes as URL-safe base64.
KEY_FORMAT = re.compile(r"[A-Za-z0-9_-]{43}=")


class KeyProblem(Exception):
    """The key cannot be used; ``key`` names the message of the table and ``values`` fill it in."""

    def __init__(self, key: str, *values: str) -> None:
        super().__init__(key)
        self.key = key
        self.values = values


def _create(key_file: Path) -> bool:
    """Publish a new key through a 600 temporary file and a hard link, durably. The link fails when a key is
    already there (another run was faster), and that key is never replaced: False then, True when this one won."""
    directory = key_file.parent
    directory.mkdir(parents=True, exist_ok=True)
    descriptor, tmp_name = tempfile.mkstemp(dir=directory, prefix=".tmp.")
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            handle.write(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii") + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(tmp_name, key_file)
        except FileExistsError:
            return False
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    fsync_path(directory)
    return True


def ensure_key(key_file: Path, backups_dir: Path, generate: bool) -> bool:
    """Check that a usable key file exists, creating it when ``generate`` is set and no backup exists yet.

    Returns True when a new key was created; raises ``KeyProblem`` (nothing changed) otherwise."""
    if str(key_file).startswith(f"{backups_dir}/"):
        raise KeyProblem("bk_key_inside", str(key_file), str(backups_dir))
    created = False
    if not key_file.exists():
        if not generate or any(backups_dir.glob("*.enc")):
            raise KeyProblem("bk_key_missing", str(key_file), str(backups_dir))
        created = _create(key_file)
    try:
        key = "".join(key_file.read_text(encoding="utf-8").split())
    except (OSError, ValueError):
        key = ""
    if not KEY_FORMAT.fullmatch(key):
        raise KeyProblem("bk_key_bad", str(key_file))
    with contextlib.suppress(OSError):
        key_file.chmod(0o600)
    return created
