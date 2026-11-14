"""The files compose mounts, written for a checkout, and the setup of the Claude Desktop entry."""

import json
import stat
from pathlib import Path

import pytest
from tools.workctl import desktopsetup, messages, stackfiles
from tools.workctl.stack import Stop

from tests.selfhost.work_package.fakestack import FakeStack

OWNER = "5b0c1e2a-1111-4222-8333-444455556666"
OTHER = "7e57d0e5-aaaa-4bbb-8ccc-dddddddddddd"
TEMPLATE = "global\n# @ALLOWLIST@\ndefaults\n"


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _checkout(tmp_path: Path) -> FakeStack:
    stack = FakeStack(tmp_path)
    (stack.work / "gateway.haproxy.cfg").write_text(TEMPLATE, encoding="utf-8")
    (stack.selfhost / "postgres-init.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    return stack


def test_the_generated_files_are_readable_for_the_unprivileged_gateway(tmp_path: Path) -> None:
    stack = _checkout(tmp_path)
    (stack.selfhost / "postgres-init.sh").chmod(0o600)
    stack.gen.chmod(0o700)
    stackfiles.render_generated(stack, [("embed.a.lan", 443), ("x.b", 8443)])
    assert _mode(stack.selfhost / "postgres-init.sh") == 0o755
    assert _mode(stack.gen) == 0o755
    for name in ("gateway.haproxy.cfg", "allow.compose.yaml", "build-info.json"):
        assert _mode(stack.gen / name) == 0o644, name
    assert "frontend allow_2" in (stack.gen / "gateway.haproxy.cfg").read_text(encoding="utf-8")
    assert "aliases: [embed.a.lan, x.b]" in (stack.gen / "allow.compose.yaml").read_text(
        encoding="utf-8"
    )


def test_without_allowed_addresses_an_old_override_is_removed(tmp_path: Path) -> None:
    stack = _checkout(tmp_path)
    (stack.gen / "allow.compose.yaml").write_text("old\n", encoding="utf-8")
    stackfiles.render_generated(stack, [])
    assert not (stack.gen / "allow.compose.yaml").exists()
    assert "# @ALLOWLIST@" not in (stack.gen / "gateway.haproxy.cfg").read_text(encoding="utf-8")


def test_the_build_information_is_kept_unless_asked_for_again(tmp_path: Path) -> None:
    stack = FakeStack(tmp_path)
    stackfiles.ensure_build_info(stack)
    path = stack.gen / "build-info.json"
    path.write_text('{"commit": "kept"}\n', encoding="utf-8")
    stackfiles.ensure_build_info(stack)
    assert json.loads(path.read_text(encoding="utf-8")) == {"commit": "kept"}
    stackfiles.write_build_info(stack, "abc123", updated=True)
    info = json.loads(path.read_text(encoding="utf-8"))
    assert info["previous_commit"] == "abc123"
    assert info["commit"] == "unknown"  # the temporary directory is no checkout
    assert info["updated_at"] == info["built_at"]
    assert _mode(path) == 0o644


class _Docker:
    """A docker on the PATH of the test (the absolute path goes into the Claude Desktop entry)."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        self.path = bin_dir / "docker"
        self.path.write_text("#!/bin/sh\n", encoding="utf-8")
        self.path.chmod(0o755)
        monkeypatch.setenv("PATH", str(bin_dir))


def _owner_stack(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    users: dict[str, str | None] | None = None,
    created: bytes | bool = OWNER.encode() + b"\n",
) -> tuple[FakeStack, _Docker]:
    """A stack whose database answers ``users`` (a part of the query, mapped to what it prints)."""
    docker = _Docker(tmp_path, monkeypatch)
    replies = users or {}

    def answer(call: str) -> object:
        if "create-user" in call:
            return created
        if "inspect --format" in call:
            return "/sidekick-work-api-1\n"
        for part, reply in replies.items():
            if part in call:
                return reply
        return ""

    return FakeStack(tmp_path, answer), docker


def test_a_remembered_owner_that_exists_in_the_database_is_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stack, _ = _owner_stack(tmp_path, monkeypatch, users={f"id = '{OWNER}'": "1\n"})
    (stack.secrets / "user-id").write_text(OWNER + "\n", encoding="utf-8")
    desktopsetup.ensure_owner(stack)
    assert (stack.secrets / "user-id").read_text(encoding="utf-8") == OWNER + "\n"
    assert not any("create-user" in call for call in stack.calls)


def test_an_owner_of_another_database_is_replaced_by_the_user_this_one_has(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stack, _ = _owner_stack(
        tmp_path, monkeypatch, users={f"id = '{OWNER}'": "", "username = 'jobb'": OTHER + "\n"}
    )
    (stack.secrets / "user-id").write_text(OWNER + "\n", encoding="utf-8")
    desktopsetup.ensure_owner(stack)
    assert (stack.secrets / "user-id").read_text(encoding="utf-8") == OTHER + "\n"
    assert _mode(stack.secrets / "user-id") == 0o600
    assert messages.text("en", "owner_stale") in capsys.readouterr().out
    assert not any("create-user" in call for call in stack.calls)


def test_without_any_owner_a_new_one_is_created_and_remembered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stack, _ = _owner_stack(tmp_path, monkeypatch)
    desktopsetup.ensure_owner(stack)
    assert (stack.secrets / "user-id").read_text(encoding="utf-8") == OWNER + "\n"
    assert _mode(stack.secrets / "user-id") == 0o600
    assert not list(stack.secrets.glob(".tmp.*"))


@pytest.mark.parametrize("created", [False, b"not a uuid\n"])
def test_a_user_that_cannot_be_created_stops_with_the_log_named(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    created: bytes | bool,
) -> None:
    stack, _ = _owner_stack(tmp_path, monkeypatch, created=created)
    with pytest.raises(Stop) as stop:
        desktopsetup.ensure_owner(stack)
    assert stop.value.code == 1
    assert str(stack.log) in capsys.readouterr().err
    assert not (stack.secrets / "user-id").exists()
    assert not list(stack.secrets.glob(".tmp.*"))


def test_a_database_that_cannot_be_asked_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stack, _ = _owner_stack(tmp_path, monkeypatch, users={"username = 'jobb'": None})
    with pytest.raises(Stop):
        desktopsetup.ensure_owner(stack)


def test_the_desktop_entry_names_the_running_container_and_the_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stack, docker = _owner_stack(tmp_path, monkeypatch)
    (stack.secrets / "user-id").write_text(OWNER + "\n", encoding="utf-8")
    desktopsetup.write_desktop_config(stack)
    out = stack.secrets / "claude_desktop_config.json"
    entry = json.loads(out.read_text(encoding="utf-8"))["mcpServers"]["sidekick-work"]
    assert entry["command"] == str(docker.path)
    assert "sidekick-work-api-1" in entry["args"]
    assert f"SIDEKICK_MCP_STDIO_OWNER_ID={OWNER}" in entry["args"]
    assert _mode(out) == 0o600
    assert str(out) in capsys.readouterr().out


def test_an_image_without_the_stdio_entry_point_stops_before_anything_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stack, _ = _owner_stack(tmp_path, monkeypatch)
    stack.answer = lambda call: "import sidekick.mcp.stdio" not in call
    with pytest.raises(Stop) as stop:
        desktopsetup.desktop_setup(stack)
    assert stop.value.code == 1
    assert not (stack.secrets / "user-id").exists()
