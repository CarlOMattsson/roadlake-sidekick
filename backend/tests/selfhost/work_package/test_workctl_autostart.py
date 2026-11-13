"""The login-start files of tools/workctl: escaping, exact output, location, writing and removal."""

import os
import plistlib
import stat
import subprocess
from pathlib import Path

import pytest
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


HOME = Path("/home/someone")


def test_the_unit_file_lives_in_the_override_directory_when_one_is_given() -> None:
    assert autostart.unit_file("Linux", "/x", HOME, "") == Path("/x/sidekick-work.service")
    assert autostart.unit_file("Darwin", "/x", HOME, "") == Path("/x/local.sidekick.work.plist")


def test_the_unit_file_lives_in_the_users_own_location_otherwise() -> None:
    assert (
        autostart.unit_file("Linux", "", HOME, "")
        == HOME / ".config/systemd/user/sidekick-work.service"
    )
    assert autostart.unit_file("Linux", "", HOME, "/cfg") == Path(
        "/cfg/systemd/user/sidekick-work.service"
    )
    assert autostart.unit_file("Darwin", "", HOME, "") == (
        HOME / "Library/LaunchAgents/local.sidekick.work.plist"
    )


def test_enable_writes_the_unit_with_mode_600_and_runs_nothing_when_not_managed(
    tmp_path: Path,
) -> None:
    file = tmp_path / "units" / "sidekick-work.service"
    autostart.enable(file, "Linux", "/a/work.sh", "/a/log", managed=False)
    assert file.read_text(encoding="utf-8") == autostart.render_systemd("/a/work.sh")
    assert stat.S_IMODE(file.stat().st_mode) == 0o600


def test_enable_writes_the_plist_on_macos(tmp_path: Path) -> None:
    file = tmp_path / "local.sidekick.work.plist"
    autostart.enable(file, "Darwin", "/a/work.sh", "/a/log", managed=False)
    assert file.read_text(encoding="utf-8") == autostart.render_launchd(
        autostart.LABEL, "/a/work.sh", "/a/log"
    )


def test_enable_registers_the_unit_with_systemd_when_managed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(autostart, "_run", lambda argv, **_kw: calls.append(list(argv)))
    autostart.enable(tmp_path / "u.service", "Linux", "/a/work.sh", "/a/log", managed=True)
    assert calls == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "sidekick-work.service"],
    ]


def test_enable_registers_the_agent_with_launchd_when_managed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(autostart, "_run", lambda argv, **_kw: calls.append(list(argv)))
    file = tmp_path / "a.plist"
    autostart.enable(file, "Darwin", "/a/work.sh", "/a/log", managed=True)
    assert [call[:2] for call in calls] == [["launchctl", "bootout"], ["launchctl", "bootstrap"]]
    assert calls[1][2:] == [f"gui/{os.getuid()}", str(file)]


def test_disable_removes_the_file_and_is_fine_when_it_is_gone(tmp_path: Path) -> None:
    file = tmp_path / "sidekick-work.service"
    file.write_text("x", encoding="utf-8")
    autostart.disable(file, "Linux", managed=False)
    autostart.disable(file, "Linux", managed=False)
    assert not file.exists()


def test_disable_ignores_a_missing_systemctl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    file = tmp_path / "sidekick-work.service"
    file.write_text("x", encoding="utf-8")
    autostart.disable(file, "Linux", managed=True)
    assert not file.exists()


def test_enable_fails_with_an_error_when_systemctl_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(autostart.AutostartError):
        autostart.enable(tmp_path / "u.service", "Linux", "/a/work.sh", "/a/log", managed=True)


def test_systemctl_enable_hides_only_its_output_so_errors_stay_visible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[tuple[str, ...], dict[str, object]] = {}

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen[tuple(argv)] = kwargs
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(autostart.subprocess, "run", fake_run)
    autostart.enable(tmp_path / "u.service", "Linux", "/a/work.sh", "/a/log", managed=True)
    enable = seen[("systemctl", "--user", "enable", "sidekick-work.service")]
    assert enable["stdout"] == subprocess.DEVNULL
    assert enable["stderr"] is None
