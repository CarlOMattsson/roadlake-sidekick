"""Text of the login-start files in tools/workctl: XML and systemd escaping, exact output."""

import plistlib

from tools.workctl import autostart

# Space, &, <, $, %, and a double quote: every character the two escaping schemes must handle.
KNEPIG_SCRIPT = '/srv/we ird&<$%"x/tools/work.sh'


def test_xml_escape_escapes_ampersand_and_angle_brackets() -> None:
    assert autostart.xml_escape("&<>") == "&amp;&lt;&gt;"


def test_xml_escape_escapes_ampersand_before_entities() -> None:
    assert autostart.xml_escape("&lt;") == "&amp;lt;"


def test_xml_escape_leaves_quotes_unchanged() -> None:
    assert autostart.xml_escape('"it\'s"') == '"it\'s"'


def test_systemd_quote_escapes_backslash_and_quote() -> None:
    assert autostart.systemd_quote(r'a\b"c') == r'"a\\b\"c"'


def test_systemd_quote_doubles_percent() -> None:
    assert autostart.systemd_quote("100%") == '"100%%"'


def test_systemd_quote_doubles_dollar() -> None:
    assert autostart.systemd_quote("$HOME") == '"$$HOME"'


def test_systemd_quote_combines_all_escapes() -> None:
    assert autostart.systemd_quote(KNEPIG_SCRIPT) == '"/srv/we ird&<$$%%\\"x/tools/work.sh"'


def test_render_systemd_exact_text() -> None:
    expected = (
        "[Unit]\n"
        "Description=Sidekick Work (local Sidekick for the work laptop)\n"
        "After=docker.service network-online.target\n"
        "Wants=network-online.target\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        "RemainAfterExit=yes\n"
        'ExecStart=/bin/bash "/a/b c/work.sh" start --wait-docker\n'
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )

    assert autostart.render_systemd("/a/b c/work.sh") == expected


def test_render_systemd_escapes_knepig_script_path() -> None:
    text = autostart.render_systemd(KNEPIG_SCRIPT)

    # systemd sees doubled % and $ and an escaped quote; other characters pass through.
    assert 'ExecStart=/bin/bash "/srv/we ird&<$$%%\\"x/tools/work.sh" start --wait-docker\n' in text


def test_render_launchd_exact_text() -> None:
    expected = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        "<dict>\n"
        "  <key>Label</key><string>local.sidekick.work</string>\n"
        "  <key>ProgramArguments</key>\n"
        "  <array><string>/bin/bash</string><string>/a/b c/work.sh</string>"
        "<string>start</string><string>--wait-docker</string></array>\n"
        "  <key>RunAtLoad</key><true/>\n"
        "  <key>StandardOutPath</key><string>/a/b c/work.log</string>\n"
        "  <key>StandardErrorPath</key><string>/a/b c/work.log</string>\n"
        "</dict>\n"
        "</plist>\n"
    )

    assert (
        autostart.render_launchd("local.sidekick.work", "/a/b c/work.sh", "/a/b c/work.log")
        == expected
    )


def test_render_launchd_escapes_knepig_paths_and_parses_as_plist() -> None:
    log = '/srv/log&<$%"x/work.log'
    text = autostart.render_launchd("local.sidekick.work", KNEPIG_SCRIPT, log)

    # The XML-escaped form is what ends up in the file; plistlib must read the raw paths back.
    assert 'we ird&amp;&lt;$%"x' in text
    plist = plistlib.loads(text.encode("utf-8"))

    assert plist["Label"] == "local.sidekick.work"
    assert plist["ProgramArguments"] == ["/bin/bash", KNEPIG_SCRIPT, "start", "--wait-docker"]
    assert plist["RunAtLoad"] is True
    assert plist["StandardOutPath"] == log
    assert plist["StandardErrorPath"] == log
