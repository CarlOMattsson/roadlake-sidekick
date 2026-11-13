"""The workctl command line as work.sh calls it: stdout, stderr and exit codes of real subprocesses.

Also two package-wide checks: Python 3.9 syntax, and standard library imports only."""

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.selfhost.work_package.support import REPO_ROOT

WORKCTL_DIR = REPO_ROOT / "tools" / "workctl"
GATEWAY = "gateway.work.lan"
WORKCTL_SOURCES = sorted(WORKCTL_DIR.glob("*.py"))


def _workctl(
    cwd: Path, *args: str, stdin: str = "", extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run ``python -m workctl`` as work.sh does: package on PYTHONPATH, no other environment."""
    env = {
        **(extra_env or {}),
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(REPO_ROOT / "tools"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    return subprocess.run(
        [sys.executable, "-m", "workctl", *args],
        cwd=cwd,
        env=env,
        input=stdin,
        capture_output=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )


@pytest.fixture(name="model_secrets")
def _model_secrets(tmp_path: Path) -> Path:
    """A secrets directory with the two files the model key touches."""
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "sidekick.env").write_text("SIDEKICK_DATABASE_URL=x\n", encoding="utf-8")
    (secrets_dir / "hindsight.env").write_text(
        "HINDSIGHT_API_LLM_API_KEY=not-needed\n", encoding="utf-8"
    )
    return secrets_dir


def test_base_url_prints_the_five_parts(tmp_path: Path) -> None:
    result = _workctl(tmp_path, "base-url", "https://embed.a.lan:8443/v1")
    assert result.returncode == 0
    assert result.stdout == "https\nembed.a.lan\n8443\n/v1\n0\n"
    assert result.stderr == ""


def test_base_url_rejects_a_bad_address_with_one_line_on_stderr(tmp_path: Path) -> None:
    result = _workctl(tmp_path, "base-url", "--lang", "en", "ftp://embed.a.lan/v1")
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "the address must start with http:// or https:// and have a host\n"


def test_allowlist_prints_host_and_port_lines(tmp_path: Path) -> None:
    result = _workctl(
        tmp_path, "allowlist", "--lang", "en", "--model-port", "8000", "embed.a.lan:443,x.b:8443"
    )
    assert result.returncode == 0
    assert result.stdout == "embed.a.lan 443\nx.b 8443\n"
    assert result.stderr == ""


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("10.0.0.5:443", "'10.0.0.5:443': IP addresses cannot be allowed, use a host name"),
        (
            "embed.a.lan:8000",
            "'embed.a.lan:8000': port 8000 is already used "
            "(the model server, MCP or another entry)",
        ),
    ],
)
def test_allowlist_rejects_a_bad_entry(tmp_path: Path, raw: str, reason: str) -> None:
    result = _workctl(tmp_path, "allowlist", "--lang", "en", "--model-port", "8000", raw)
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == reason + "\n"


def test_autostart_on_writes_the_systemd_unit_into_the_override_directory(tmp_path: Path) -> None:
    result = _workctl(
        tmp_path,
        "autostart",
        "--platform",
        "Linux",
        "--script",
        "/opt/work/tools/work.sh",
        "--log",
        "/opt/work/autostart.log",
        "on",
        extra_env={"SIDEKICK_WORK_AUTOSTART_DIR": str(tmp_path / "units")},
    )
    unit = (tmp_path / "units" / "sidekick-work.service").read_text(encoding="utf-8")
    assert result.returncode == 0
    assert unit.startswith("[Unit]\n")
    assert 'ExecStart=/bin/bash "/opt/work/tools/work.sh" start --wait-docker\n' in unit
    assert result.stdout.startswith("Autostart på (systemd --user): ")
    assert result.stderr == ""


def test_generate_secrets_prints_nothing_and_refuses_the_second_time(tmp_path: Path) -> None:
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    example = tmp_path / "hindsight.env.example"
    example.write_text(
        "HINDSIGHT_API_LLM_API_KEY=x\nHINDSIGHT_API_TENANT_API_KEY=x\n", encoding="utf-8"
    )
    args = (
        "generate-secrets",
        "--secrets-dir",
        str(secrets_dir),
        "--hindsight-example",
        str(example),
        "--gateway",
        GATEWAY,
    )

    first = _workctl(tmp_path, *args)
    assert first.returncode == 0
    assert first.stdout == ""
    assert first.stderr == ""
    assert sorted(path.name for path in secrets_dir.iterdir()) == [
        "db.env",
        "hindsight.env",
        "sidekick.env",
    ]

    second = _workctl(tmp_path, *args)
    assert second.returncode == 1
    assert second.stdout == ""
    assert second.stderr.startswith("a secrets file already exists: ")
    assert len(second.stderr.splitlines()) == 1


def test_model_key_apply_reads_stdin_and_the_key_is_shown_only_by_show(
    tmp_path: Path, model_secrets: Path
) -> None:
    secrets_arg = ["--secrets-dir", str(model_secrets)]
    applied = _workctl(tmp_path, "model-key-apply", *secrets_arg, stdin="sk-cli-secret-42\n")
    assert applied.returncode == 0
    assert applied.stdout == ""
    assert applied.stderr == ""
    assert "sk-cli-secret-42" in (model_secrets / "sidekick.env").read_text(encoding="utf-8")
    assert "HINDSIGHT_API_LLM_API_KEY=sk-cli-secret-42" in (
        model_secrets / "hindsight.env"
    ).read_text(encoding="utf-8")

    shown = _workctl(tmp_path, "model-key-show", *secrets_arg)
    assert shown.returncode == 0
    assert shown.stdout == "sk-cli-secret-42\n"
    assert shown.stderr == ""


def test_model_key_apply_with_empty_stdin_means_no_key(tmp_path: Path, model_secrets: Path) -> None:
    secrets_arg = ["--secrets-dir", str(model_secrets)]
    _workctl(tmp_path, "model-key-apply", *secrets_arg, stdin="sk-cli-secret-42\n")
    cleared = _workctl(tmp_path, "model-key-apply", *secrets_arg, stdin="")
    assert cleared.returncode == 0
    assert cleared.stdout == ""

    shown = _workctl(tmp_path, "model-key-show", *secrets_arg)
    assert shown.returncode == 0
    assert shown.stdout == ""
    assert "HINDSIGHT_API_LLM_API_KEY=not-needed" in (model_secrets / "hindsight.env").read_text(
        encoding="utf-8"
    )


def test_render_gateway_writes_the_gateway_and_the_override(tmp_path: Path) -> None:
    template = tmp_path / "gateway.haproxy.cfg"
    template.write_text("global\n# @ALLOWLIST@\ndefaults\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    result = _workctl(
        tmp_path,
        "render-gateway",
        "--template",
        str(template),
        "--out-dir",
        str(out_dir),
        "--allow",
        "embed.a.lan 443\nx.b 8443\n",
    )
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
    cfg = (out_dir / "gateway.haproxy.cfg").read_text(encoding="utf-8")
    assert "frontend allow_1" in cfg
    assert "frontend allow_2" in cfg
    assert "# @ALLOWLIST@" not in cfg
    assert "aliases: [embed.a.lan, x.b]" in (out_dir / "allow.compose.yaml").read_text(
        encoding="utf-8"
    )


def test_render_gateway_without_allow_removes_an_old_override(tmp_path: Path) -> None:
    template = tmp_path / "gateway.haproxy.cfg"
    template.write_text("global\n# @ALLOWLIST@\ndefaults\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "allow.compose.yaml").write_text("old\n", encoding="utf-8")
    result = _workctl(
        tmp_path, "render-gateway", "--template", str(template), "--out-dir", str(out_dir)
    )
    assert result.returncode == 0
    assert not (out_dir / "allow.compose.yaml").exists()


def test_build_info_writes_and_then_updates_the_file(tmp_path: Path) -> None:
    path = tmp_path / "build-info.json"
    common = ("build-info", "--path", str(path), "--commit-date", "2026-11-11", "--now")

    first = _workctl(tmp_path, *common, "2026-11-12T10:00:00Z", "--commit", "abc123")
    assert first.returncode == 0
    assert first.stdout == ""
    assert first.stderr == ""
    created = path.read_text(encoding="utf-8")
    assert created.endswith("\n")

    second = _workctl(
        tmp_path,
        *common,
        "2026-11-12T12:00:00Z",
        "--commit",
        "def456",
        "--previous",
        "abc123",
        "--updated",
        "updated",
    )
    assert second.returncode == 0
    assert second.stdout == ""
    info = path.read_text(encoding="utf-8")
    assert '"commit": "def456"' in info
    assert '"previous_commit": "abc123"' in info
    assert '"updated_at": "2026-11-12T12:00:00Z"' in info


def test_desktop_config_writes_the_entry_file_and_prints_nothing(tmp_path: Path) -> None:
    out_file = tmp_path / "claude_desktop_config.json"
    result = _workctl(
        tmp_path,
        "desktop-config",
        "--out",
        str(out_file),
        "--docker",
        "/usr/bin/docker",
        "--container",
        "sidekick-work-api-1",
        "--owner",
        "user-1",
    )
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    entry = json.loads(out_file.read_text(encoding="utf-8"))["mcpServers"]["sidekick-work"]
    assert entry["command"] == "/usr/bin/docker"
    assert "SIDEKICK_MCP_STDIO_OWNER_ID=user-1" in entry["args"]


def test_claude_config_reads_the_answer_from_stdin(tmp_path: Path) -> None:
    source = tmp_path / "entry.json"
    source.write_text('{"mcpServers":{"sidekick-work":{"command":"docker"}}}', encoding="utf-8")
    target = tmp_path / "claude.json"
    args = ("claude-config", "--lang", "en", "--source", str(source), "--target", str(target))

    declined = _workctl(tmp_path, *args, stdin="n\n")
    assert declined.returncode == 0
    assert declined.stderr == "Save the change? (y/N): "
    assert not target.exists()

    accepted = _workctl(tmp_path, *args, stdin="y\n")
    assert accepted.returncode == 0
    assert accepted.stdout.endswith(f"Saved: {target}. Restart Claude Desktop completely.\n")
    assert json.loads(target.read_text(encoding="utf-8")) == {
        "mcpServers": {"sidekick-work": {"command": "docker"}}
    }


def test_claude_config_without_the_entry_file_exits_1(tmp_path: Path) -> None:
    result = _workctl(
        tmp_path,
        "claude-config",
        "--lang",
        "en",
        "--source",
        str(tmp_path / "missing.json"),
        "--target",
        str(tmp_path / "claude.json"),
    )
    assert result.returncode == 1
    assert result.stderr == "The Sidekick entry is missing. First run: bash tools/work.sh start\n"


@pytest.mark.parametrize(
    ("lang", "expected"),
    [("sv", "Sidekick Work: installationsguide"), ("en", "Sidekick Work: setup guide")],
)
def test_text_prints_the_message_without_a_newline(
    tmp_path: Path, lang: str, expected: str
) -> None:
    result = _workctl(tmp_path, "text", "--lang", lang, "title")
    assert (result.returncode, result.stdout, result.stderr) == (0, expected, "")


def test_text_prints_the_key_when_the_table_has_no_message(tmp_path: Path) -> None:
    result = _workctl(tmp_path, "text", "--", "-no_such_key")
    assert (result.returncode, result.stdout, result.stderr) == (0, "-no_such_key", "")


def test_text_is_utf8_whatever_the_locale(tmp_path: Path) -> None:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(REPO_ROOT / "tools"),
        "LC_ALL": "C",
    }
    result = subprocess.run(
        [sys.executable, "-m", "workctl", "text", "--lang", "sv", "usage"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert "användning:".encode() in result.stdout


@pytest.mark.parametrize("argv", [["no-such-command"], []])
def test_a_usage_error_exits_with_code_2(tmp_path: Path, argv: list[str]) -> None:
    result = _workctl(tmp_path, *argv)
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.startswith("usage: workctl")


def test_the_package_has_sources() -> None:
    assert WORKCTL_SOURCES


@pytest.mark.parametrize("source", WORKCTL_SOURCES, ids=lambda path: path.name)
def test_every_module_parses_as_python_39(source: Path) -> None:
    ast.parse(source.read_text(encoding="utf-8"), filename=str(source), feature_version=(3, 9))


def _top_level_imports(tree: ast.AST) -> set[str]:
    """The first name of each absolute import; relative imports belong to the package."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_the_package_imports_only_the_standard_library() -> None:
    stdlib = set(sys.stdlib_module_names)
    offenders: dict[str, list[str]] = {}
    for source in WORKCTL_SOURCES:
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        outside = sorted(_top_level_imports(tree) - stdlib)
        if outside:
            offenders[source.name] = outside
    assert offenders == {}
