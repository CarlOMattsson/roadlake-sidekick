"""Checks of the self-hosted ntfy server (D-080): pinned, hardened, reachable only on /up<topic>."""

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

from tests.support.ntfy_paths import (
    NOT_NTFY_PATHS,
    NTFY_PATHS,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SELFHOST = REPO_ROOT / "deploy" / "selfhost"


@pytest.fixture(name="compose")
def _compose() -> dict:
    return yaml.safe_load((SELFHOST / "compose.yaml").read_text(encoding="utf-8"))


@pytest.fixture(name="ntfy")
def _ntfy(compose: dict) -> dict:
    return compose["services"]["ntfy"]


@pytest.fixture(name="server")
def _server() -> dict:
    return yaml.safe_load((SELFHOST / "ntfy" / "server.yml").read_text(encoding="utf-8"))


@pytest.fixture(name="caddy")
def _caddy() -> str:
    return (SELFHOST / "Caddyfile.example").read_text(encoding="utf-8")


def _ntfy_path_regex(caddy: str) -> re.Pattern[str]:
    block = re.search(r"@ntfy \{(.*?)\n\t\}", caddy, re.S)
    assert block, "no @ntfy matcher in the Caddyfile example"
    patterns = re.findall(r"^\s*path_regexp (\S+)$", block.group(1), re.M)
    assert len(patterns) == 1
    return re.compile(patterns[0])


def test_the_image_is_pinned_to_v2_37_2_by_digest(ntfy: dict) -> None:
    assert re.fullmatch(r"binwiederhier/ntfy:v2\.37\.2@sha256:[0-9a-f]{64}", ntfy["image"])
    # Docker Hub manifest list for v2.37.2, checked 2026-11-09.
    assert ntfy["image"].endswith(
        "sha256:1875ddcf815c8a3c981d6d78c67a93452d0abba79b1ab9520b1f5f5238902bd7"
    )


def test_ntfy_is_in_the_push_profile_only(ntfy: dict) -> None:
    assert ntfy["profiles"] == ["push"]


def test_the_container_is_hardened(ntfy: dict) -> None:
    assert "ports" not in ntfy and "expose" not in ntfy
    assert ntfy["read_only"] is True
    assert ntfy["cap_drop"] == ["ALL"] and "cap_add" not in ntfy
    assert "no-new-privileges:true" in ntfy["security_opt"]
    uid, _, gid = str(ntfy["user"]).partition(":")
    assert uid.isdigit() and int(uid) > 0 and gid.isdigit() and int(gid) > 0
    assert ntfy.get("privileged") is not True and "network_mode" not in ntfy
    assert ntfy["init"] is True
    assert ntfy["mem_limit"] == "128m" and ntfy["cpus"] == 0.5 and ntfy["pids_limit"] == 64
    assert ntfy["logging"]["options"] == {"max-size": "10m", "max-file": "3"}


def test_the_state_directory_is_a_small_private_tmpfs(ntfy: dict) -> None:
    assert not ntfy.get("volumes", []) or all(str(v).endswith(":ro") for v in ntfy["volumes"]), (
        "every bind mount is read-only; there is no named volume"
    )
    state = [t for t in ntfy["tmpfs"] if t.startswith("/var/lib/ntfy")]
    assert len(state) == 1
    assert "mode=0700" in state[0] and "uid=10001" in state[0] and "size=16m" in state[0]


def test_ntfy_sits_on_the_internal_push_network_only(compose: dict, ntfy: dict) -> None:
    assert ntfy["networks"] == ["push"]
    assert compose["networks"]["push"] == {"internal": True}
    assert set(compose["services"]["caddy"]["networks"]) == {"edge", "proxy", "push"}
    # Nothing else may join it: that would put another service next to the ntfy port.
    members = [n for n, s in compose["services"].items() if "push" in (s.get("networks") or [])]
    assert sorted(members) == ["caddy", "ntfy"]


def test_no_other_service_publishes_a_port_to_ntfy(compose: dict) -> None:
    for name, service in compose["services"].items():
        for port in service.get("ports", []):
            assert "8080" not in str(port), name


def test_the_server_config_denies_by_default_and_grants_one_write_and_one_read(
    server: dict,
) -> None:
    assert server["auth-default-access"] == "deny-all"
    assert server["auth-access"] == ["sidekick:up*:wo", "phone:up*:ro"]
    assert server["web-root"] == "disable"
    assert server["enable-login"] is False
    assert server["enable-signup"] is False
    assert server["enable-reservations"] is False


def test_the_server_config_keeps_nothing_on_disk_and_logs_no_topics(server: dict) -> None:
    assert server["cache-duration"] == "2h"
    assert server["message-size-limit"] == "1K"
    assert server["log-level"] == "warn"
    assert server["log-format"] == "json"
    assert server["auth-file"].startswith("/var/lib/ntfy/")
    forbidden = {
        "cache-file",
        "attachment-cache-dir",
        "upstream-base-url",
        "firebase-key-file",
        "enable-metrics",
        "experimental-listen-admin-unix",
        "visitor-subscriber-rate-limiting",
        "auth-users",
        "auth-tokens",
    }
    assert not forbidden & set(server)
    assert not [key for key in server if key.startswith("smtp-")]


def test_the_server_config_holds_no_secret(server: dict) -> None:
    text = (SELFHOST / "ntfy" / "server.yml").read_text(encoding="utf-8")
    assert "$2a$" not in text and "tk_" not in text


def test_caddy_forwards_the_topic_path_and_nothing_else_to_ntfy(caddy: str) -> None:
    pattern = _ntfy_path_regex(caddy)
    for path in NTFY_PATHS:
        assert pattern.search(path), path
    for path in NOT_NTFY_PATHS:
        assert not pattern.search(path), path


def test_caddy_has_exactly_one_route_to_ntfy_and_it_comes_before_the_404(caddy: str) -> None:
    assert caddy.count("ntfy:8080") == 1
    handle = caddy.index("handle @ntfy {")
    assert (
        handle < caddy.index("reverse_proxy ntfy:8080") < caddy.index("handle {\n\t\trespond 404")
    )
    # The route is limited to the three methods ntfy needs here.
    assert re.search(r"@ntfy \{\n\t\tmethod GET POST PUT\n", caddy)


def test_caddy_keeps_the_topic_out_of_its_access_log(caddy: str) -> None:
    # The topic is part of the path and the path is never logged: the ntfy route is class `push`.
    assert "log_append route {route_class}" in caddy
    assert "log_append path" not in caddy
    assert re.search(r"^\t\t~\(\?i\)\^/up\[A-Za-z0-9_-\]\{8,64\}\(/\|\$\) push$", caddy, re.M)


def test_the_env_example_documents_the_format_without_a_real_secret() -> None:
    text = (SELFHOST / "ntfy.env.example").read_text(encoding="utf-8")
    assert re.search(r"^NTFY_AUTH_USERS='sidekick:\$2a\$.*:user,phone:\$2a\$.*:user'$", text, re.M)
    assert re.search(r"^NTFY_AUTH_TOKENS='sidekick:tk_.*:sidekick'$", text, re.M)
    assert "replace-with" in text


def test_the_selfhost_env_example_keeps_the_own_ntfy_settings_commented_out() -> None:
    text = (SELFHOST / "selfhost.env.example").read_text(encoding="utf-8")
    assert re.search(r"^SIDEKICK_PUSH_ALLOWED_HOSTS=ntfy\.sh$", text, re.M)
    assert re.search(r"^# SIDEKICK_PUSH_AUTH_HOST=", text, re.M)
    assert re.search(r"^# SIDEKICK_PUSH_AUTH_TOKEN=", text, re.M)
    assert not re.search(r"^SIDEKICK_PUSH_AUTH_(HOST|TOKEN)=", text, re.M)


def test_ntfy_init_parses() -> None:
    result = subprocess.run(
        ["sh", "-n", str(SELFHOST / "ntfy-init.sh")], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


@pytest.fixture(name="init_dir")
def _init_dir(tmp_path: Path) -> Path:
    """A copy of the script next to the real compose.yaml, with a stand-in for `docker` on PATH.

    The stand-in answers `ntfy user hash` with a fixed bcrypt-shaped string: no image is needed."""

    work = tmp_path / "selfhost"
    work.mkdir()
    for name in ("ntfy-init.sh", "compose.yaml"):
        (work / name).write_text((SELFHOST / name).read_text(encoding="utf-8"), encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        "cat >/dev/null\n"
        "printf 'password: \\r  \\rconfirm: \\r  \\r"
        "$2a$10$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ0123456\\n'\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    return work


def _run_init(work: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PATH": f"{work.parent / 'bin'}:{os.environ['PATH']}"}
    return subprocess.run(
        ["sh", str(work / "ntfy-init.sh"), *args], capture_output=True, text=True, env=env
    )


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_ntfy_init_writes_private_files_and_prints_no_secret(init_dir: Path) -> None:
    result = _run_init(init_dir)
    assert result.returncode == 0, result.stderr
    env_file = init_dir / "ntfy.env"
    token_file = init_dir / "ntfy-secrets" / "sidekick-token"
    password_file = init_dir / "ntfy-secrets" / "phone-password"
    assert _mode(env_file) == _mode(token_file) == _mode(password_file) == 0o600
    assert _mode(init_dir / "ntfy-secrets") == 0o700
    token = token_file.read_text(encoding="utf-8").strip()
    password = password_file.read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"tk_[A-Za-z0-9]{29}", token)
    assert re.fullmatch(r"[A-Za-z0-9]{24}", password)
    env_text = env_file.read_text(encoding="utf-8")
    assert f"NTFY_AUTH_TOKENS='sidekick:{token}:sidekick'" in env_text
    assert re.search(
        r"^NTFY_AUTH_USERS='sidekick:\$2a\$[^:,]+:user,phone:\$2a\$[^:,]+:user'$", env_text, re.M
    )
    assert password not in env_text, "only the hash of the phone password goes to the server"
    for stream in (result.stdout, result.stderr):
        assert token not in stream and password not in stream and "$2a$" not in stream
    # It says where the files are.
    assert str(env_file) in result.stdout and str(token_file) in result.stdout


def test_ntfy_init_makes_the_server_config_readable_for_the_container_user(init_dir: Path) -> None:
    config = init_dir / "ntfy" / "server.yml"
    config.parent.mkdir()
    config.write_text("listen-http: ':8080'\n", encoding="utf-8")
    config.chmod(0o600)  # what a checkout made under umask 077 leaves behind
    assert _run_init(init_dir).returncode == 0
    assert _mode(config) == 0o644
    config.chmod(0o600)
    again = _run_init(init_dir)
    assert "nothing changed" in again.stdout, "accounts exist, so nothing else is rewritten"
    assert _mode(config) == 0o644, "an existing installation is repaired too"


def test_ntfy_init_is_idempotent_and_rotate_replaces_the_secrets(init_dir: Path) -> None:
    assert _run_init(init_dir).returncode == 0
    files = [init_dir / "ntfy.env", *sorted((init_dir / "ntfy-secrets").iterdir())]
    before = [f.read_text(encoding="utf-8") for f in files]
    again = _run_init(init_dir)
    assert again.returncode == 0 and "nothing changed" in again.stdout
    assert [f.read_text(encoding="utf-8") for f in files] == before
    rotated = _run_init(init_dir, "--rotate")
    assert rotated.returncode == 0, rotated.stderr
    after = [f.read_text(encoding="utf-8") for f in files]
    assert all(a != b for a, b in zip(after, before, strict=True))
    assert all(_mode(f) == 0o600 for f in files)


def test_ntfy_init_refuses_a_half_written_state(init_dir: Path) -> None:
    (init_dir / "ntfy.env").write_text("x\n", encoding="utf-8")
    result = _run_init(init_dir)
    assert result.returncode == 1 and "only some of the files exist" in result.stderr
    assert (init_dir / "ntfy.env").read_text(encoding="utf-8") == "x\n"


def test_ntfy_init_writes_to_the_directory_and_file_it_is_told_to(init_dir: Path) -> None:
    secrets = init_dir.parent / "elsewhere" / "secrets"
    env_file = init_dir.parent / "elsewhere" / "accounts.env"
    result = _run_init(init_dir, "--secrets-dir", str(secrets), "--env-file", str(env_file))
    assert result.returncode == 0, result.stderr
    assert _mode(env_file) == _mode(secrets / "sidekick-token") == 0o600
    assert _mode(secrets / "phone-password") == 0o600 and _mode(secrets) == 0o700
    assert not (init_dir / "ntfy.env").exists() and not (init_dir / "ntfy-secrets").exists()
    assert "Next:" not in result.stdout, "the selfhost hint does not apply to another layout"
    token = (secrets / "sidekick-token").read_text(encoding="utf-8").strip()
    assert f"NTFY_AUTH_TOKENS='sidekick:{token}:sidekick'" in env_file.read_text(encoding="utf-8")
    again = _run_init(init_dir, "--secrets-dir", str(secrets), "--env-file", str(env_file))
    assert "nothing changed" in again.stdout


def test_ntfy_init_rejects_unknown_and_incomplete_options(init_dir: Path) -> None:
    assert _run_init(init_dir, "--nope").returncode == 2
    assert _run_init(init_dir, "--secrets-dir").returncode == 2


def test_ntfy_init_warns_once_per_file_that_git_does_not_ignore(init_dir: Path) -> None:
    subprocess.run(["git", "init", "-q", str(init_dir)], check=True)
    result = _run_init(init_dir)
    assert result.returncode == 0, result.stderr
    warned = [line for line in result.stderr.splitlines() if "is not gitignored" in line]
    assert len(warned) == 3
    assert any(line.endswith("ntfy.env is not gitignored; never commit it") for line in warned)


def test_ntfy_init_is_silent_when_git_ignores_the_files(init_dir: Path) -> None:
    subprocess.run(["git", "init", "-q", str(init_dir)], check=True)
    (init_dir / ".gitignore").write_text("ntfy.env\nntfy-secrets/\n", encoding="utf-8")
    result = _run_init(init_dir)
    assert result.returncode == 0, result.stderr
    assert "gitignored" not in result.stderr
