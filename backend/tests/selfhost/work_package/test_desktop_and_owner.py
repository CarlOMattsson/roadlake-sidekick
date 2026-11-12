"""The Claude Desktop entry and configuration, and the owner user id the entry names."""

import json
import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

from tests.selfhost.work_package.support import (
    docker_calls,
    docker_calls_if_any,
    ready_repo,
    run_work,
)


def test_start_writes_a_claude_desktop_entry_that_runs_stdio_in_the_container(
    mini_repo: Path,
) -> None:
    """docker exec -i, docker by absolute path, the owner by -e, no token, no Node bridge."""

    work = ready_repo(mini_repo)
    result = run_work(
        mini_repo, "start", STUB_FAIL="no_owner"
    )  # a fresh database: no user jobb yet
    assert result.returncode == 0, result.stderr
    config_file = work / "secrets" / "claude_desktop_config.json"
    assert stat.S_IMODE(config_file.stat().st_mode) == 0o600
    entry = json.loads(config_file.read_text(encoding="utf-8"))["mcpServers"]["sidekick-work"]
    owner = (work / "secrets" / "user-id").read_text(encoding="utf-8").strip()
    assert owner == "5b0c1e2a-1111-4222-8333-444455556666"
    assert entry == {
        "command": str(mini_repo / "bin" / "docker"),
        "args": [
            "exec",
            "-i",
            "-e",
            f"SIDEKICK_MCP_STDIO_OWNER_ID={owner}",
            "sidekick-work-api-1",
            "python",
            "-m",
            "sidekick.mcp.stdio",
        ],
    }
    assert Path(entry["command"]).is_absolute()
    text = config_file.read_text(encoding="utf-8")
    assert "npx" not in text and "mcp-remote" not in text and "Bearer" not in text
    assert not (work / "secrets" / "mcp-token").exists()
    assert str(config_file) in result.stdout and owner not in result.stdout + result.stderr
    # Run again: the owner is created once.
    assert run_work(mini_repo, "start").returncode == 0
    assert docker_calls(mini_repo).count("create-user") == 1


def _start_with_stale_user_id(
    mini_repo: Path, **env: str
) -> tuple[Path, subprocess.CompletedProcess[str]]:
    work = ready_repo(mini_repo)
    user_id = work / "secrets" / "user-id"
    user_id.write_text("00000000-0000-4000-8000-00000000dead\n", encoding="utf-8")
    user_id.chmod(0o600)
    return user_id, run_work(mini_repo, "start", **env)


def test_a_user_id_left_over_from_another_database_is_replaced_by_a_new_owner(
    mini_repo: Path,
) -> None:
    """A new, empty data volume with an old secrets/user-id: the owner is created, not trusted."""

    user_id, result = _start_with_stale_user_id(mini_repo, STUB_FAIL="no_owner")
    assert result.returncode == 0, result.stderr
    assert user_id.read_text(encoding="utf-8").strip() == "5b0c1e2a-1111-4222-8333-444455556666"
    assert docker_calls(mini_repo).count("create-user") == 1
    assert "00000000-0000-4000-8000-00000000dead" not in result.stdout + result.stderr
    assert stat.S_IMODE(user_id.stat().st_mode) == 0o600
    config = (user_id.parent / "claude_desktop_config.json").read_text(encoding="utf-8")
    assert "5b0c1e2a-1111-4222-8333-444455556666" in config and "dead" not in config


def test_a_stale_user_id_is_replaced_by_the_user_jobb_the_database_already_has(
    mini_repo: Path,
) -> None:
    user_id, result = _start_with_stale_user_id(mini_repo)
    assert result.returncode == 0, result.stderr
    assert user_id.read_text(encoding="utf-8").strip() == "7e57d0e5-aaaa-4bbb-8ccc-dddddddddddd"
    assert "create-user" not in docker_calls(mini_repo)


def test_a_user_id_that_exists_in_the_database_is_kept_and_nothing_is_created(
    mini_repo: Path,
) -> None:
    work = ready_repo(mini_repo)
    user_id = work / "secrets" / "user-id"
    user_id.write_text("5b0c1e2a-1111-4222-8333-444455556666\n", encoding="utf-8")
    assert run_work(mini_repo, "start", STUB_FAIL="no_owner").returncode == 0
    assert user_id.read_text(encoding="utf-8") == "5b0c1e2a-1111-4222-8333-444455556666\n"
    assert "create-user" not in docker_calls(mini_repo)


def test_start_stops_when_the_database_cannot_be_asked_about_the_owner(mini_repo: Path) -> None:
    user_id, result = _start_with_stale_user_id(mini_repo, STUB_FAIL="owner_query")
    assert result.returncode == 1
    assert "ägaranvändaren" in result.stderr
    assert user_id.read_text(encoding="utf-8").strip() == "00000000-0000-4000-8000-00000000dead"
    assert "create-user" not in docker_calls(mini_repo)


@pytest.mark.parametrize(
    "existing",
    [
        # The old file name is written in two parts so that the old-name guard stays strict.
        ("db.env", "hindsight.env", "char" + "lie.env"),  # an installation from before the rename
        ("db.env",),
        ("hindsight.env",),
        ("sidekick.env",),
        ("db.env", "sidekick.env"),  # an init that was interrupted
    ],
)
def test_init_never_overwrites_an_existing_secrets_file(
    mini_repo: Path, existing: tuple[str, ...]
) -> None:
    """Old files but no complete set (the first init after the rename): refuse, change nothing."""

    secrets = mini_repo / "deploy" / "work" / "secrets"
    secrets.mkdir(parents=True)
    kept = {name: f"OLD-{name}-DO-NOT-LOSE\n" for name in existing}
    for name, text in kept.items():
        (secrets / name).write_text(text, encoding="utf-8")
    before = sorted(p.name for p in secrets.iterdir())
    result = run_work(mini_repo, "init")
    assert result.returncode == 1
    assert (
        "skriver aldrig över" in result.stderr and "sidekick-backup import --help" in result.stderr
    )
    assert "sidekick-transition" not in result.stderr  # an internal document that is not exported
    assert sorted(p.name for p in secrets.iterdir()) == before
    for name, text in kept.items():
        assert (secrets / name).read_text(encoding="utf-8") == text
    assert "OLD-" not in result.stdout + result.stderr


def _claude_files(repo: Path) -> tuple[Path, Path]:
    work = ready_repo(repo)
    target = repo / "claude" / "claude_desktop_config.json"
    target.parent.mkdir()
    result = run_work(repo, "start", SIDEKICK_WORK_CLAUDE_CONFIG=str(target))
    assert result.returncode == 0, result.stderr
    assert not target.exists(), "start never installs the entry automatically"
    return work / "secrets" / "claude_desktop_config.json", target


@pytest.mark.parametrize("answer", ["", "\n", "n\n", "nej\n"])
def test_claude_config_previews_but_changes_nothing_without_explicit_consent(
    mini_repo: Path, answer: str
) -> None:
    _, target = _claude_files(mini_repo)
    before = '{"mcpServers":{"other":{"command":"keep"}},"preferences":{"theme":"dark"}}\n'
    target.write_text(before, encoding="utf-8")
    result = run_work(
        mini_repo, "claude-config", stdin=answer, SIDEKICK_WORK_CLAUDE_CONFIG=str(target)
    )
    assert result.returncode == 0, result.stderr
    assert '"sidekick-work"' in result.stdout and str(target) in result.stdout
    assert "Spara ändringen? (j/N)" in result.stderr
    assert target.read_text(encoding="utf-8") == before
    assert not list(target.parent.glob("*.bak.*"))


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("language, answer", [("sv", "j\n"), ("en", "y\n")])
def test_claude_config_merges_only_sidekick_and_keeps_a_private_timestamped_backup(
    mini_repo: Path, existing: bool, language: str, answer: str
) -> None:
    source, target = _claude_files(mini_repo)
    before = {
        "mcpServers": {
            "other": {"command": "keep", "env": {"TOKEN": "synthetic-other-secret"}},
            "sidekick-work": {"command": "old", "env": {"TOKEN": "synthetic-old-secret"}},
        },
        "preferences": {"theme": "dark", "nested": [1, 2]},
    }
    raw = (json.dumps(before, separators=(",", ":")) + "\n").encode()
    if existing:
        target.write_bytes(raw)
    result = run_work(
        mini_repo,
        "claude-config",
        stdin=answer,
        SIDEKICK_WORK_CLAUDE_CONFIG=str(target),
        SIDEKICK_WORK_LANG=language,
    )
    assert result.returncode == 0, result.stderr
    merged = json.loads(target.read_bytes())
    expected_entry = json.loads(source.read_bytes())["mcpServers"]["sidekick-work"]
    assert merged["mcpServers"]["sidekick-work"] == expected_entry
    if existing:
        assert merged["preferences"] == before["preferences"]
        assert merged["mcpServers"]["other"] == before["mcpServers"]["other"]
    else:
        assert merged == {"mcpServers": {"sidekick-work": expected_entry}}
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    backups = list(target.parent.glob("*.bak.*"))
    assert len(backups) == int(existing)
    if existing:
        assert re.search(r"\.bak\.\d{8}-\d{6}-\d{6}$", backups[0].name)
        assert backups[0].read_bytes() == raw, "the backup keeps the original bytes"
        assert stat.S_IMODE(backups[0].stat().st_mode) == 0o600
        assert str(backups[0]) in result.stdout
    assert "synthetic-other-secret" not in result.stdout + result.stderr
    assert "synthetic-old-secret" not in result.stdout + result.stderr
    assert not list(target.parent.glob(".claude-config-*"))
    # Repeating the command is a no-op, even without an answer.
    saved = target.read_bytes()
    rerun = run_work(mini_repo, "claude-config", SIDEKICK_WORK_CLAUDE_CONFIG=str(target))
    assert rerun.returncode == 0
    assert target.read_bytes() == saved and len(list(target.parent.glob("*.bak.*"))) == len(backups)


@pytest.mark.parametrize("bad", ['{"broken":', "[]", '{"mcpServers":[]}', '{"mcpServers":null}'])
def test_claude_config_refuses_malformed_existing_json_without_overwriting_it(
    mini_repo: Path, bad: str
) -> None:
    _, target = _claude_files(mini_repo)
    target.write_text(bad, encoding="utf-8")
    result = run_work(
        mini_repo, "claude-config", stdin="j\n", SIDEKICK_WORK_CLAUDE_CONFIG=str(target)
    )
    assert result.returncode == 1
    assert "Inget ändrat" in result.stderr
    assert target.read_text(encoding="utf-8") == bad
    assert not list(target.parent.glob("*.bak.*"))


def test_claude_config_requires_the_generated_entry_and_never_starts_docker(
    mini_repo: Path,
) -> None:
    target = mini_repo / "claude.json"
    result = run_work(
        mini_repo, "claude-config", stdin="j\n", SIDEKICK_WORK_CLAUDE_CONFIG=str(target)
    )
    assert result.returncode == 1
    assert "bash tools/work.sh start" in result.stderr
    assert not target.exists() and not docker_calls_if_any(mini_repo)


def test_claude_config_does_not_overwrite_an_edit_made_during_confirmation(mini_repo: Path) -> None:
    _, target = _claude_files(mini_repo)
    target.write_text('{"mcpServers":{}}\n', encoding="utf-8")
    env = {
        **os.environ,
        "SIDEKICK_WORK_LANG": "en",
        "SIDEKICK_WORK_CLAUDE_CONFIG": str(target),
    }
    with subprocess.Popen(
        ["bash", str(mini_repo / "tools" / "work.sh"), "claude-config"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    ) as process:
        assert process.stderr is not None
        prompt = "Save the change? (y/N): "
        assert process.stderr.read(len(prompt)) == prompt
        changed = '{"mcpServers":{"new-connector":{"command":"keep"}}}\n'
        target.write_text(changed, encoding="utf-8")
        _, error = process.communicate("y\n", timeout=10)
    assert process.returncode == 1
    assert "configuration changed after the preview" in error
    assert target.read_text(encoding="utf-8") == changed
    assert not list(target.parent.glob("*.bak.*"))
