"""The host side of ``work.sh status``: the version line from ``build-info.json`` and the translation of the
gateway probe's neutral lines (see ``probe_gateway``) into the user's language."""

from __future__ import annotations

import json
from pathlib import Path

from . import messages

INDENT = "  "


def version_line(lang: str, build_info: Path) -> str:
    """The "version: commit ..." line, or an empty string when the file is missing or unreadable."""
    try:
        info = json.loads(build_info.read_text(encoding="utf-8"))
        values = (info["commit"][:10], info["commit_date"][:10], info["built_at"], info["updated_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return ""
    if not values[0]:
        return ""
    return messages.fill(lang, "st_version", *values)


def via_report(lang: str, probe_output: str, wanted_model: str) -> list[str]:
    """The indented lines under "Through the gateway ...", one per line the probe printed, then the check that
    ``wanted_model`` (empty = no check) is among the models the server listed."""
    lines: list[str] = []
    listed = ""
    for line in probe_output.splitlines():
        if line.startswith("models "):
            listed = line[len("models ") :]
            lines.append(messages.fill(lang, "st_models", listed))
        elif line.startswith("models_error "):
            lines.append(messages.fill(lang, "st_models_err", line[len("models_error ") :]))
        elif line == "outside_reached":
            lines.append(messages.text(lang, "st_outside_reached"))
        elif line.startswith("outside_error "):
            lines.append(messages.fill(lang, "st_outside_err", line[len("outside_error ") :]))
        elif line.startswith("outside "):
            lines.append(messages.fill(lang, "st_outside", line[len("outside ") :]))
    if wanted_model:
        key = "st_model_ok" if f",{wanted_model}," in f",{listed}," else "st_model_missing"
        lines.append(messages.fill(lang, key, wanted_model))
    return [INDENT + line for line in lines]
