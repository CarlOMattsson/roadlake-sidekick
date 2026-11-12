"""Claude Desktop configuration: the entry ``start`` writes into ``deploy/work/secrets/`` and the guarded merge
of that entry into the user's own ``claude_desktop_config.json`` (``claude-config``), plus the model id list
of an OpenAI-compatible ``/models`` answer.

The entry holds no secret (no token: the stdio process is trusted because the OS user that can run docker
already holds the database credentials) but the file is written with mode 600 like the others.
"""

from __future__ import annotations

import datetime
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, TextIO, cast

SERVER_NAME = "sidekick-work"
_YES = ("j", "ja", "y", "yes")

_TEXT = {
    "sv": {
        "missing": "Sidekick-posten saknas. Kör först: bash tools/work.sh start",
        "invalid": "Inställningsfilen kunde inte läsas som ett JSON-objekt med mcpServers. Inget ändrat.",
        "preview": "Ändring i {path}: {action} mcpServers.sidekick-work med följande post (andra poster behålls):",
        "add": "lägg till",
        "replace": "ersätt",
        "ask": "Spara ändringen? (j/N): ",
        "abort": "Avbrutet, inget ändrat.",
        "same": "Sidekick-posten är redan aktuell. Inget ändrat.",
        "changed": "Inställningsfilen ändrades efter förhandsvisningen. Kör kommandot igen. Inget ändrat.",
        "backup": "Säkerhetskopia: {path}",
        "saved": "Sparat: {path}. Starta om Claude Desktop helt.",
        "failed": "Kunde inte spara inställningen. Originalet behålls; eventuell säkerhetskopia ligger bredvid filen.",
    },
    "en": {
        "missing": "The Sidekick entry is missing. First run: bash tools/work.sh start",
        "invalid": "Could not read the configuration as a JSON object with mcpServers. Nothing changed.",
        "preview": "Change in {path}: {action} mcpServers.sidekick-work with the following entry "
        "(other entries are kept):",
        "add": "add",
        "replace": "replace",
        "ask": "Save the change? (y/N): ",
        "abort": "Aborted, nothing changed.",
        "same": "The Sidekick entry is already current. Nothing changed.",
        "changed": "The configuration changed after the preview. Run the command again. Nothing changed.",
        "backup": "Backup: {path}",
        "saved": "Saved: {path}. Restart Claude Desktop completely.",
        "failed": "Could not save the configuration. The original is kept; any backup is next to the file.",
    },
}


def desktop_config(docker_bin: str, container: str, owner: str) -> dict[str, Any]:
    """The configuration ``start`` writes: Claude Desktop runs the stdio MCP server inside the api container."""
    return {
        "mcpServers": {
            SERVER_NAME: {
                "command": docker_bin,
                "args": [
                    "exec",
                    "-i",
                    "-e",
                    f"SIDEKICK_MCP_STDIO_OWNER_ID={owner}",
                    container,
                    "python",
                    "-m",
                    "sidekick.mcp.stdio",
                ],
            }
        }
    }


def write_desktop_config(out_file: Path, docker_bin: str, container: str, owner: str) -> None:
    """Write the entry file, mode 600 from the first byte (also when the file already exists)."""
    config = desktop_config(docker_bin, container, owner)
    descriptor = os.open(out_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2)
        handle.write("\n")
    os.chmod(out_file, 0o600)


def parse_model_ids(body: str) -> list[str]:
    """The ids of an OpenAI-compatible ``/models`` answer; ``ValueError`` when it is not one."""
    try:
        data = json.loads(body).get("data", [])
        return [model["id"] for model in data if isinstance(model, dict) and "id" in model]
    except (ValueError, AttributeError, TypeError) as error:
        raise ValueError("not a model list") from error


def _load(source: Path, target: Path) -> tuple[dict[str, Any], bytes | None, dict[str, Any]]:
    """The entry to merge, the target's current bytes and its parsed configuration.

    ``OSError``, ``ValueError``, ``KeyError`` or ``TypeError`` mean the files are unusable.
    """
    entry: object = json.loads(source.read_bytes())["mcpServers"][SERVER_NAME]
    if target.is_symlink():
        raise ValueError("symlink")
    original = target.read_bytes() if target.exists() else None
    config: object = json.loads(original) if original is not None else {}
    if (
        not isinstance(config, dict)
        or not isinstance(cast("dict[str, Any]", config).get("mcpServers", {}), dict)
        or not isinstance(entry, dict)
    ):
        raise ValueError("object expected")
    return cast("dict[str, Any]", entry), original, cast("dict[str, Any]", config)


def _write_merged(target: Path, config: dict[str, Any]) -> None:
    """Replace ``target`` atomically; the temporary file never outlives the call."""
    temporary: str | None = None
    try:
        descriptor, temporary = tempfile.mkstemp(prefix=".claude-config-", dir=target.parent)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(config, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)


def merge_into_claude_config(
    source: Path,
    target: Path,
    lang: str,
    read_answer: Callable[[], str],
    out: TextIO,
    err: TextIO,
) -> int:
    """Preview the change, ask, back up the old file and merge only ``mcpServers.sidekick-work``.

    Exit code 0 also covers "already current" and "answered no"; 1 means nothing was changed and the reason
    is on ``err``. ``read_answer`` is called once, after the preview.
    """
    texts = _TEXT[lang]
    if not source.is_file():
        print(texts["missing"], file=err)
        return 1
    try:
        entry, original, config = _load(source, target)
    except (OSError, ValueError, KeyError, TypeError):
        print(texts["invalid"], file=err)
        return 1
    servers = config.setdefault("mcpServers", {})
    if servers.get(SERVER_NAME) == entry:
        print(texts["same"], file=out)
        return 0
    action = texts["replace"] if SERVER_NAME in servers else texts["add"]
    print(texts["preview"].format(path=target, action=action), file=out)
    # Show only the proposed Sidekick entry, never other connectors' credentials or the previous entry's env.
    print(json.dumps({"mcpServers": {SERVER_NAME: entry}}, ensure_ascii=False, indent=2), file=out)
    print(texts["ask"], end="", file=err, flush=True)
    if read_answer().strip().lower() not in _YES:
        print(texts["abort"], file=out)
        return 0
    try:
        current = target.read_bytes() if target.exists() else None
        if target.is_symlink() or current != original:
            print(texts["changed"], file=err)
            return 1
        target.parent.mkdir(parents=True, exist_ok=True)
        if original is not None:
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            backup = target.with_name(target.name + ".bak." + stamp)
            with backup.open("xb") as handle:
                handle.write(original)
            print(texts["backup"].format(path=backup), file=out)
        servers[SERVER_NAME] = entry
        _write_merged(target, config)
    except (OSError, ValueError):
        print(texts["failed"], file=err)
        return 1
    print(texts["saved"].format(path=target), file=out)
    return 0
