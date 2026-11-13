"""Start at login. Linux: a systemd user unit that brings the stack up at login (containers also come back on their
own when the Docker service starts, unless they were stopped with ``stop``). macOS: a launchd agent that waits for
Docker Desktop.

The file is rendered here, with its paths escaped for the target syntax (XML for the plist; backslash, quote, ``%``
and ``$`` for a systemd ExecStart word), and written with mode 600. ``launchctl`` / ``systemctl`` are run only when
the file lives in its real place: an override directory (tests) skips them.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from pathlib import Path
from xml.sax.saxutils import escape

from .secretfiles import write_private

LABEL = "local.sidekick.work"
UNIT = "sidekick-work.service"


class AutostartError(Exception):
    """launchctl or systemctl failed (or is not installed)."""


def xml_escape(text: str) -> str:
    """Escape text for an XML element body."""
    return escape(text)


def systemd_quote(word: str) -> str:
    """Quote one word for a systemd ExecStart= line: backslash and quote escaped, ``%`` and ``$`` doubled so
    systemd does not expand them."""
    word = word.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$")
    return f'"{word}"'


def render_launchd(label: str, script: str, log: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        "<dict>\n"
        f"  <key>Label</key><string>{xml_escape(label)}</string>\n"
        "  <key>ProgramArguments</key>\n"
        f"  <array><string>/bin/bash</string><string>{xml_escape(script)}</string>"
        "<string>start</string><string>--wait-docker</string></array>\n"
        "  <key>RunAtLoad</key><true/>\n"
        f"  <key>StandardOutPath</key><string>{xml_escape(log)}</string>\n"
        f"  <key>StandardErrorPath</key><string>{xml_escape(log)}</string>\n"
        "</dict>\n"
        "</plist>\n"
    )


def render_systemd(script: str) -> str:
    return (
        "[Unit]\n"
        "Description=Sidekick Work (local Sidekick for the work laptop)\n"
        "After=docker.service network-online.target\n"
        "Wants=network-online.target\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        "RemainAfterExit=yes\n"
        f"ExecStart=/bin/bash {systemd_quote(script)} start --wait-docker\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def unit_file(platform: str, override_dir: str, home: Path, config_home: str) -> Path:
    """Where the login-start file lives: in ``override_dir`` when given, else the user's own location."""
    darwin = platform == "Darwin"
    name = f"{LABEL}.plist" if darwin else UNIT
    if override_dir:
        return Path(override_dir) / name
    if darwin:
        return home / "Library" / "LaunchAgents" / name
    return Path(config_home or home / ".config") / "systemd" / "user" / name


def _run(argv: Sequence[str], *, quiet: bool = False, check: bool = True, hide_errors: bool = True) -> None:
    """Run a command. ``quiet`` hides its output; with ``hide_errors`` False its error output stays visible."""
    out = subprocess.DEVNULL if quiet else None
    err = subprocess.DEVNULL if quiet and hide_errors else None
    try:
        result = subprocess.run(argv, stdout=out, stderr=err, check=False)  # noqa: S603 - fixed arguments
    except OSError as error:
        if check:
            raise AutostartError(f"{argv[0]}: {error}") from error
        return
    if check and result.returncode != 0:
        raise AutostartError(f"{argv[0]} failed with exit code {result.returncode}")


def _launchd_target() -> str:
    return f"gui/{os.getuid()}/{LABEL}"


def enable(file: Path, platform: str, script: str, log: str, managed: bool) -> None:
    """Write the file and, when ``managed``, tell launchd / systemd about it."""
    file.parent.mkdir(parents=True, exist_ok=True)
    if platform == "Darwin":
        write_private(file, render_launchd(LABEL, script, log))
        if managed:
            _run(["launchctl", "bootout", _launchd_target()], quiet=True, check=False)
            _run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(file)])
    else:
        write_private(file, render_systemd(script))
        if managed:
            _run(["systemctl", "--user", "daemon-reload"])
            _run(["systemctl", "--user", "enable", UNIT], quiet=True, hide_errors=False)


def disable(file: Path, platform: str, managed: bool) -> None:
    """Switch the login start off and remove the file; a missing registration is not an error."""
    if managed:
        if platform == "Darwin":
            _run(["launchctl", "bootout", _launchd_target()], quiet=True, check=False)
        else:
            _run(["systemctl", "--user", "disable", UNIT], quiet=True, check=False)
    file.unlink(missing_ok=True)
    if managed and platform != "Darwin":
        _run(["systemctl", "--user", "daemon-reload"], quiet=True, check=False)
