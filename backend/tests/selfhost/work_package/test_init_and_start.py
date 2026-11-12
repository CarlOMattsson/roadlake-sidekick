"""`tools/work.sh init` and `start`: secrets, refusals, derived settings, autostart."""

import json
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.selfhost.work_package.support import (
    SCRIPT,
    directive,
    haproxy_sections,
    ready_repo,
    retired_names,
    run_work,
    write_env,
)


def test_the_script_parses_and_is_executable() -> None:
    result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert SCRIPT.stat().st_mode & stat.S_IXUSR


def test_init_writes_the_secrets_with_restrictive_modes_and_prints_none(mini_repo: Path) -> None:
    key = "model-key-that-must-never-be-printed-1234567890"
    result = run_work(mini_repo, "init", SIDEKICK_WORK_MODEL_API_KEY=key)
    assert result.returncode == 0, result.stderr
    secrets = mini_repo / "deploy" / "work" / "secrets"
    assert stat.S_IMODE(secrets.stat().st_mode) == 0o700
    files = {p.name for p in secrets.iterdir()}
    assert {"sidekick.env", "db.env", "hindsight.env"} <= files
    assert "admin-password" not in files
    for path in secrets.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600, path.name
    sidekick = (secrets / "sidekick.env").read_text(encoding="utf-8")
    hindsight = (secrets / "hindsight.env").read_text(encoding="utf-8")
    assert f"WORK_MODEL_API_KEY={key}" in sidekick
    assert not retired_names(sidekick + hindsight)
    assert f"HINDSIGHT_API_LLM_API_KEY={key}" in hindsight
    assert not re.search(r"^[A-Z_]+=.*replace-with", hindsight, re.M)
    token = re.search(r"^SIDEKICK_MEMORY_HINDSIGHT_API_TOKEN=(.+)$", sidekick, re.M)
    assert token and f"HINDSIGHT_API_TENANT_API_KEY={token.group(1)}" in hindsight
    for line in re.findall(r"=(\S{16,})", sidekick + hindsight):
        assert line not in result.stdout + result.stderr
    assert key not in result.stdout + result.stderr
    assert (mini_repo / "deploy" / "work" / "work.env").exists()


def test_init_run_again_keeps_the_existing_secrets(mini_repo: Path) -> None:
    assert run_work(mini_repo, "init").returncode == 0
    secrets = mini_repo / "deploy" / "work" / "secrets"
    before = (secrets / "db.env").read_text(encoding="utf-8")
    result = run_work(mini_repo, "init")
    assert result.returncode == 0
    assert (secrets / "db.env").read_text(encoding="utf-8") == before


@pytest.mark.parametrize(
    "base_url, reason",
    [
        ("http://<vllm-host>:<port>/v1", "platshållare"),
        ("ftp://host:21/v1", "http"),
        ("http://host:8000", "sökväg"),
        ("http://user:pw@host:8000/v1", "inloggning"),
        ("http://host:8765/v1", "krockar"),
    ],
)
def test_start_refuses_a_missing_or_unusable_model_address(
    mini_repo: Path, base_url: str, reason: str
) -> None:
    assert run_work(mini_repo, "init").returncode == 0
    (mini_repo / "deploy" / "work" / "work.env").write_text(
        f"SIDEKICK_WORK_MODEL_BASE_URL={base_url}\nSIDEKICK_WORK_MEMORY_MODEL=m\n", encoding="utf-8"
    )
    result = run_work(mini_repo, "start")
    assert result.returncode == 1
    assert reason in result.stderr
    assert not (mini_repo / "deploy" / "work" / "work.log").exists(), "nothing was started"


def test_start_refuses_a_missing_or_placeholder_memory_model(mini_repo: Path) -> None:
    assert run_work(mini_repo, "init").returncode == 0
    for line in ("", "SIDEKICK_WORK_MEMORY_MODEL=<model-id>\n"):
        (mini_repo / "deploy" / "work" / "work.env").write_text(
            f"SIDEKICK_WORK_MODEL_BASE_URL=http://vllm:8000/v1\n{line}", encoding="utf-8"
        )
        result = run_work(mini_repo, "start")
        assert result.returncode == 1
        assert "SIDEKICK_WORK_MEMORY_MODEL" in result.stderr


def test_start_refuses_without_secrets(mini_repo: Path) -> None:
    (mini_repo / "deploy" / "work" / "work.env").write_text(
        "SIDEKICK_WORK_MODEL_BASE_URL=http://vllm:8000/v1\n", encoding="utf-8"
    )
    result = run_work(mini_repo, "start")
    assert result.returncode == 1 and "init" in result.stderr


def _derived(repo: Path) -> dict[str, str]:
    text = (repo / "docker-env.txt").read_text(encoding="utf-8")
    return dict(line.split("=", 1) for line in text.splitlines())


@pytest.mark.parametrize(
    "base_url, resolve, addr, host_header, tls_parts",
    [
        (
            "http://vllm.company.lan:8000/v1",
            "",
            "vllm.company.lan:8000",
            "vllm.company.lan:8000",
            [],
        ),
        ("http://10.1.2.3/v1", "", "10.1.2.3:80", "10.1.2.3", []),
        (
            "http://vllm.company.lan:8000/v1",
            "10.9.9.9",
            "10.9.9.9:8000",
            "vllm.company.lan:8000",
            [],
        ),
        (
            "https://llm.corp.test/v1/",
            "",
            "llm.corp.test:443",
            "llm.corp.test",
            ["ssl verify required", "verifyhost llm.corp.test", "sni str(llm.corp.test)"],
        ),
        ("https://10.1.2.3:8443/v1", "", "10.1.2.3:8443", "10.1.2.3:8443", ["verifyhost 10.1.2.3"]),
    ],
)
def test_start_derives_the_one_upstream_from_the_model_address(
    mini_repo: Path, base_url: str, resolve: str, addr: str, host_header: str, tls_parts: list[str]
) -> None:
    assert run_work(mini_repo, "init").returncode == 0
    values = {"SIDEKICK_WORK_MODEL_BASE_URL": base_url, "SIDEKICK_WORK_MEMORY_MODEL": "m"}
    if resolve:
        values["SIDEKICK_WORK_MODEL_RESOLVE_IP"] = resolve
    write_env(mini_repo, **values)
    result = run_work(mini_repo, "start")
    assert result.returncode == 0, result.stderr
    derived = _derived(mini_repo)
    assert derived["SIDEKICK_WORK_UPSTREAM_ADDR"] == addr
    assert derived["SIDEKICK_WORK_UPSTREAM_HOST_HEADER"] == host_header
    assert derived["SIDEKICK_WORK_MODEL_PATH"] == "/v1"
    for part in tls_parts:
        assert part in derived["SIDEKICK_WORK_UPSTREAM_TLS"]
    if not tls_parts:
        assert derived["SIDEKICK_WORK_UPSTREAM_TLS"] == ""
    info_file = mini_repo / "deploy" / "work" / "generated" / "build-info.json"
    info = json.loads(info_file.read_text(encoding="utf-8"))
    assert set(info) == {"commit", "commit_date", "built_at", "updated_at", "previous_commit"}


def test_the_allowlist_becomes_passthrough_listeners_and_network_aliases(mini_repo: Path) -> None:
    assert run_work(mini_repo, "init").returncode == 0
    values = {
        "SIDEKICK_WORK_MODEL_BASE_URL": "http://vllm:8000/v1",
        "SIDEKICK_WORK_MEMORY_MODEL": "m",
    }
    write_env(
        mini_repo,
        SIDEKICK_WORK_ALLOW="Embed.Company.lan:9443, files.company.lan:9444",
        **values,
    )
    assert run_work(mini_repo, "start").returncode == 0
    generated = mini_repo / "deploy" / "work" / "generated"
    config = haproxy_sections((generated / "gateway.haproxy.cfg").read_text(encoding="utf-8"))
    assert "frontend model" in config, "the template stays"
    for index, host, port in ((1, "embed.company.lan", 9443), (2, "files.company.lan", 9444)):
        frontend = config[f"frontend allow_{index}"]
        backend = config[f"backend allow_{index}_server"]
        assert "mode tcp" in frontend and f"bind :{port}" in frontend
        assert f"default_backend allow_{index}_server" in frontend
        assert "mode tcp" in backend
        assert [t[:5] for t in directive(backend, "server")] == [
            ["server", "upstream", f"{host}:{port}", "resolvers", "docker"]
        ]
    override = yaml.safe_load((generated / "allow.compose.yaml").read_text(encoding="utf-8"))
    assert override["services"]["gateway"]["networks"]["edge"]["aliases"] == [
        "embed.company.lan",
        "files.company.lan",
    ]
    write_env(mini_repo, **values)
    assert run_work(mini_repo, "start").returncode == 0
    assert not (generated / "allow.compose.yaml").exists()
    plain = haproxy_sections((generated / "gateway.haproxy.cfg").read_text(encoding="utf-8"))
    assert not [header for header in plain if "allow_" in header]


@pytest.mark.parametrize(
    "allow, reason",
    [
        ("10.0.0.5:443", "IP-adresser"),
        ("host.lan", "värdnamn:port"),
        ("a.lan:443,b.lan:443", "används redan"),
        ("a.lan:8000", "används redan"),
        ("a.lan:8765", "används redan"),
        ("a.lan:99999", "värdnamn:port"),
    ],
)
def test_start_refuses_an_invalid_allowlist(mini_repo: Path, allow: str, reason: str) -> None:
    assert run_work(mini_repo, "init").returncode == 0
    write_env(
        mini_repo,
        SIDEKICK_WORK_MODEL_BASE_URL="http://vllm:8000/v1",
        SIDEKICK_WORK_MEMORY_MODEL="m",
        SIDEKICK_WORK_ALLOW=allow,
    )
    result = run_work(mini_repo, "start")
    assert result.returncode == 1 and reason in result.stderr
    assert not (mini_repo / "deploy" / "work" / "work.log").exists()


def test_the_rooms_setting_reaches_the_api_only_when_set(mini_repo: Path) -> None:
    assert run_work(mini_repo, "init").returncode == 0
    rooms = mini_repo / "deploy" / "work" / "secrets" / "rooms.env"
    values = {
        "SIDEKICK_WORK_MODEL_BASE_URL": "http://vllm:8000/v1",
        "SIDEKICK_WORK_MEMORY_MODEL": "m",
    }
    write_env(mini_repo, **values)
    assert run_work(mini_repo, "start").returncode == 0 and not rooms.exists()
    write_env(mini_repo, SIDEKICK_ENABLED_ROOMS="work", **values)
    assert run_work(mini_repo, "start").returncode == 0
    assert rooms.read_text(encoding="utf-8") == "SIDEKICK_ENABLED_ROOMS=work\n"
    assert stat.S_IMODE(rooms.stat().st_mode) == 0o600


def test_autostart_writes_and_removes_the_unit(mini_repo: Path) -> None:
    unit_dir = mini_repo / "autostart"
    result = run_work(mini_repo, "autostart", "on")
    assert result.returncode == 0, result.stderr
    if sys.platform == "darwin":
        unit = (unit_dir / "local.sidekick.work.plist").read_text(encoding="utf-8")
        assert "<key>RunAtLoad</key><true/>" in unit and "--wait-docker" in unit
    else:
        unit = (unit_dir / "sidekick-work.service").read_text(encoding="utf-8")
        assert f"ExecStart=/bin/bash {mini_repo}/tools/work.sh start --wait-docker" in unit
        assert "WantedBy=default.target" in unit and "After=docker.service" in unit
    assert run_work(mini_repo, "autostart", "status").stdout.startswith("på")
    assert run_work(mini_repo, "autostart", "off").returncode == 0
    assert not list(unit_dir.iterdir())
    assert run_work(mini_repo, "autostart", "status").stdout.strip() == "av"


def test_the_setup_guide_does_not_overwrite_old_secrets_either(mini_repo: Path) -> None:
    secrets = mini_repo / "deploy" / "work" / "secrets"
    secrets.mkdir(parents=True)
    (secrets / "db.env").write_text("OLD-db\n", encoding="utf-8")
    result = run_work(mini_repo, "setup", stdin="sv\n")
    assert result.returncode == 1
    assert (secrets / "db.env").read_text(encoding="utf-8") == "OLD-db\n"
    assert not (secrets / "sidekick.env").exists()


def test_start_refuses_an_image_without_the_stdio_entry_point(mini_repo: Path) -> None:
    (mini_repo / "bin" / "docker").write_text(
        "#!/bin/sh\ncase \"$*\" in\n  *'import sidekick.mcp.stdio'*) exit 1 ;;\nesac\nexit 0\n",
        encoding="utf-8",
    )
    ready_repo(mini_repo)
    result = run_work(mini_repo, "start")
    assert result.returncode == 1 and "start --build" in result.stderr


def test_the_old_token_command_is_gone(mini_repo: Path) -> None:
    result = run_work(mini_repo, "pat")
    assert result.returncode == 2 and "användning" in result.stderr
    assert "cmd_pat" not in SCRIPT.read_text(encoding="utf-8")


def test_the_build_info_file_exists_after_init_and_the_api_reads_it(
    mini_repo: Path, overlay: dict[str, Any]
) -> None:
    info_file = mini_repo / "deploy" / "work" / "generated" / "build-info.json"
    assert run_work(mini_repo, "init").returncode == 0
    assert info_file.is_file(), "the reminder needs a date from day one, before any update"
    assert set(json.loads(info_file.read_text(encoding="utf-8"))) >= {
        "commit",
        "updated_at",
        "built_at",
    }
    api = overlay["services"]["api"]
    assert api["environment"]["SIDEKICK_BUILD_INFO_FILE"] == "/etc/sidekick/build-info.json"
    assert "../work/generated/build-info.json:/etc/sidekick/build-info.json:ro" in api["volumes"]


def test_the_other_commands_speak_the_chosen_language(mini_repo: Path) -> None:
    write_env(mini_repo, SIDEKICK_WORK_MODEL_BASE_URL="http://<vllm-host>:<port>/v1")
    sv = run_work(mini_repo, "start")
    en = run_work(mini_repo, "start", SIDEKICK_WORK_LANG="en")
    assert "Hemligheter saknas" in sv.stderr and "Secrets are missing" in en.stderr
    assert "användning" in run_work(mini_repo, "nope").stderr
    assert "usage" in run_work(mini_repo, "nope", SIDEKICK_WORK_LANG="en").stderr
    # With nothing else said, the language the guide wrote into work.env is used.
    assert run_work(mini_repo, "init").returncode == 0
    (mini_repo / "deploy" / "work" / "work.env").write_text(
        "SIDEKICK_WORK_MODEL_BASE_URL=http://<x>/v1\nSIDEKICK_WORK_LOCALE=en\n", encoding="utf-8"
    )
    assert "placeholder" in run_work(mini_repo, "start", SIDEKICK_WORK_LANG="").stderr
