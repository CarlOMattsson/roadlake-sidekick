"""The workctl command line as work.sh calls it: stdout, stderr and exit codes of real subprocesses.

Also two package-wide checks: Python 3.9 syntax, and standard library imports only."""

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from tools.workctl import secretfiles

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

    assert secretfiles.stored_model_key(model_secrets) == "sk-cli-secret-42"


def test_model_key_apply_with_empty_stdin_means_no_key(tmp_path: Path, model_secrets: Path) -> None:
    secrets_arg = ["--secrets-dir", str(model_secrets)]
    _workctl(tmp_path, "model-key-apply", *secrets_arg, stdin="sk-cli-secret-42\n")
    cleared = _workctl(tmp_path, "model-key-apply", *secrets_arg, stdin="")
    assert cleared.returncode == 0
    assert cleared.stdout == ""

    assert secretfiles.stored_model_key(model_secrets) == ""
    assert "HINDSIGHT_API_LLM_API_KEY=not-needed" in (model_secrets / "hindsight.env").read_text(
        encoding="utf-8"
    )


def test_claude_config_reads_the_answer_from_stdin(tmp_path: Path) -> None:
    source = tmp_path / "entry.json"
    source.write_text('{"mcpServers":{"sidekick-work":{"command":"docker"}}}', encoding="utf-8")
    target = tmp_path / "claude.json"
    args = ("claude-config", "--lang", "en", "--source", str(source), "--platform", "Linux")
    env = {"SIDEKICK_WORK_CLAUDE_CONFIG": str(target)}

    declined = _workctl(tmp_path, *args, stdin="n\n", extra_env=env)
    assert declined.returncode == 0
    assert declined.stderr == "Save the change? (y/N): "
    assert not target.exists()

    accepted = _workctl(tmp_path, *args, stdin="y\n", extra_env=env)
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
        "--platform",
        "Linux",
        extra_env={"SIDEKICK_WORK_CLAUDE_CONFIG": str(tmp_path / "claude.json")},
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
