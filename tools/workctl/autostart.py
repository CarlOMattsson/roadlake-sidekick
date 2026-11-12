"""Text of the login-start files: a launchd agent (macOS) and a systemd user unit (Linux).

Pure rendering: ``work.sh`` decides where the file goes and runs launchctl/systemctl. Paths are escaped for
their target syntax (XML for the plist; backslash, quote, ``%`` and ``$`` for a systemd ExecStart word).
"""

from __future__ import annotations

from xml.sax.saxutils import escape


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
