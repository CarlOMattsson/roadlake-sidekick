"""Constants and helpers the work-package tests share."""

import os
import re
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any

import yaml
from cryptography.fernet import Fernet

from sidekick.shared.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[4]
DEPLOY = REPO_ROOT / "deploy"
SELFHOST = DEPLOY / "selfhost"
WORK = DEPLOY / "work"
SCRIPT = REPO_ROOT / "tools" / "work.sh"
CRYPTO_MAGIC = b"SIDEKICK-SNAPSHOT-1\n"

# The stand-in docker runs the real deploy/selfhost/snapshot_crypto.py for the encryption step (a
# one-off api container in the real stack), so every backup in these tests is really encrypted.
# STUB_FAIL=crypto_encrypt or crypto_decrypt makes that direction fail. Checked before the call is
# logged.
CRYPTO_STUB = r"""case "$*" in
  *"-e SIDEKICK_BACKUP_ENCRYPTION_KEY api python"*)
    while [ "$1" != "-c" ]; do shift; done
    src="$2"; mode="$3"
    echo "$mode" >> "${STUB_CALLS}.crypto"
    [ "${STUB_FAIL:-}" = "crypto_$mode" ] && exit 1
    [ "$mode" = encrypt ] && stat -L -c %a /proc/self/fd/1 >> "${STUB_CALLS}.modes" 2>/dev/null
    exec "$STUB_PYTHON" -I -c "$src" "$mode" ;;
esac
"""


# What `tools/work.sh` exports before it runs compose: a plain http model server on port 8000.
DERIVED_ENV = {
    "SELFHOST_DOMAIN": "work.invalid",
    "SIDEKICK_WORK_MODEL_PORT": "8000",
    "SIDEKICK_WORK_MODEL_PATH": "/v1",
    "SIDEKICK_WORK_UPSTREAM_ADDR": "vllm.company.lan:8000",
    "SIDEKICK_WORK_UPSTREAM_HOST_HEADER": "vllm.company.lan:8000",
    "SIDEKICK_WORK_UPSTREAM_TLS": "",
    "SIDEKICK_WORK_MEMORY_MODEL": "flash-test",
}


class ComposeLoader(yaml.SafeLoader):
    """Reads the overlay as Compose does: `!override` and `!reset` replace the base value."""


class TaggedList(list[Any]):
    """A sequence that carried a Compose tag (`!override`, `!reset`); the tag stays inspectable."""

    tag: str = ""


class TaggedDict(dict[str, Any]):
    """A mapping that carried a Compose tag; the tag stays inspectable."""

    tag: str = ""


def tagged(loader: yaml.SafeLoader, tag_suffix: str, node: yaml.Node) -> Any:
    if isinstance(node, yaml.SequenceNode):
        items = TaggedList(loader.construct_sequence(node, deep=True))
        items.tag = tag_suffix
        return items
    if isinstance(node, yaml.MappingNode):
        mapping = TaggedDict(loader.construct_mapping(node, deep=True))
        mapping.tag = tag_suffix
        return mapping
    return loader.construct_scalar(node)  # type: ignore[arg-type]


ComposeLoader.add_multi_constructor("!", tagged)


def haproxy_sections(text: str) -> dict[str, list[str]]:
    """A HAProxy configuration as {section header: its stripped directive lines}.

    A header starts in column 0 (`frontend model`, `global`); comments and blanks are dropped."""

    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not raw[0].isspace():
            assert line not in sections, f"duplicate section: {line}"
            current = sections.setdefault(line, [])
        else:
            assert current is not None, f"directive outside a section: {line}"
            current.append(line)
    return sections


def directive(lines: list[str], *prefix: str) -> list[list[str]]:
    """The tokens of every line whose first tokens are `prefix`."""

    return [line.split() for line in lines if line.split()[: len(prefix)] == list(prefix)]


MARKER = "m" * 48


REMOVED_FAMILY = re.compile(
    r"(agent|assistant|bedrock|anthropic|openrouter|chat|conversation_analysis|journal_ai|live_voice"
    r"|dev_auth)_"
)


def retired_names(text: str) -> set[str]:
    found = {m.lower() for m in re.findall(r"\bSIDEKICK_([A-Z0-9_]+)\b", text)}
    return {
        name for name in found if name not in Settings.model_fields and REMOVED_FAMILY.match(name)
    }


RESTART_HINDSIGHT = "up -d --wait --wait-timeout 300 --no-deps hindsight"


STOP_WRITERS = "stop api memory-worker automation-worker"


RESTART_WRITERS = "up -d --wait --wait-timeout 300 api memory-worker automation-worker"


STUB_IMAGE_ID = "sha256:5ca1ab1e"


def run_work(
    repo: Path, *args: str, stdin: str | None = None, umask: int = -1, **env: str
) -> subprocess.CompletedProcess[str]:
    full = {
        **os.environ,
        "PATH": f"{repo / 'bin'}:{os.environ['PATH']}",
        "STUB_RECORD": str(repo / "docker-env.txt"),
        "STUB_CALLS": str(repo / "docker-calls.txt"),
        "STUB_PYTHON": sys.executable,
        "SIDEKICK_WORK_LANG": "sv",
        "SIDEKICK_WORK_AUTOSTART_DIR": str(repo / "autostart"),
        **env,
    }
    return subprocess.run(
        ["bash", str(repo / "tools" / "work.sh"), *args],
        capture_output=True,
        text=True,
        env=full,
        input=stdin,
        stdin=None if stdin is not None else subprocess.DEVNULL,
        umask=umask,
    )


def write_env(repo: Path, **values: str) -> None:
    lines = [f"{key}={value}" for key, value in values.items()]
    (repo / "deploy" / "work" / "work.env").write_text("\n".join(lines) + "\n", encoding="utf-8")


def ready_repo(repo: Path, **extra: str) -> Path:
    """init and a usable work.env; returns the work directory."""

    assert run_work(repo, "init").returncode == 0
    write_env(
        repo,
        SIDEKICK_WORK_MODEL_BASE_URL="http://vllm:8000/v1",
        SIDEKICK_WORK_MEMORY_MODEL="m",
        **extra,
    )
    return repo / "deploy" / "work"


def docker_calls(repo: Path) -> str:
    return (repo / "docker-calls.txt").read_text(encoding="utf-8")


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t.invalid", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def make_clone(repo: Path, origin: Path) -> str:
    """Turns the stand-in checkout into a git clone of `origin` on main; returns HEAD."""

    git(origin, "init", "--bare", "-b", "main")
    git(repo, "init", "-b", "main")
    git(repo, "add", "tools", "deploy/selfhost")
    git(repo, "commit", "-m", "base")
    git(repo, "remote", "add", "origin", str(origin))
    git(repo, "push", "-u", "origin", "main")
    return git(repo, "rev-parse", "HEAD")


MIGRATE = "run --rm -T --no-deps migrate"


READINESS_CALL = "exec -T api python -c"


RESTORE_STAMP = "20260101-000000"


def backup_key(work: Path) -> bytes:
    """The backup key file (created like `backup` would, when it is not there yet)."""

    path = work / "secrets" / "backup.key"
    if not path.exists():
        path.write_bytes(Fernet.generate_key() + b"\n")
        path.chmod(0o600)
    return path.read_bytes().strip()


def encrypt(work: Path, data: bytes) -> bytes:
    """What snapshot_crypto.py writes: the magic line, then one Fernet token."""

    return CRYPTO_MAGIC + Fernet(backup_key(work)).encrypt(data)


def backup_set(work: Path, stamp: str = RESTORE_STAMP) -> tuple[Path, Path]:
    """A complete backup set as `backup` writes it: an encrypted finished dump and archive."""

    backups = work / "backups"
    backups.mkdir(exist_ok=True)
    dump = backups / f"sidekick-{stamp}.sql.enc"
    dump.write_bytes(encrypt(work, b"-- PostgreSQL database dump complete\n"))
    member = work / "PG_VERSION"
    member.write_text("16\n", encoding="utf-8")
    plain = work / "plain.tar.gz"
    with tarfile.open(plain, "w:gz") as tar:
        tar.add(member, arcname="./PG_VERSION")
    member.unlink()
    archive = backups / f"hindsight-{stamp}.tar.gz.enc"
    archive.write_bytes(encrypt(work, plain.read_bytes()))
    plain.unlink()
    return dump, archive


def docker_calls_if_any(repo: Path) -> str:
    calls = repo / "docker-calls.txt"
    return calls.read_text(encoding="utf-8") if calls.exists() else ""


def changes_nothing(calls: str) -> None:
    for verb in (" stop ", " up ", " run ", "pg_dump", "psql", "--network none"):
        assert verb not in calls, verb


def run_restore(repo: Path, *extra: str, **env: str) -> subprocess.CompletedProcess[str]:
    return run_work(
        repo, "restore", RESTORE_STAMP, "--apply", *extra, stdin="sidekick-work\n", **env
    )
