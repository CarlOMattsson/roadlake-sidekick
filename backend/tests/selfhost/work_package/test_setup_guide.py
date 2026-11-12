"""The `setup` guide and the texts the package ships in both languages."""

import http.server
import json
import re
import shutil
import stat
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.selfhost.work_package.support import (
    REPO_ROOT,
    retired_names,
    run_work,
)


@pytest.fixture(name="model_server")
def _model_server() -> Iterator[str]:
    """A stand-in vLLM: GET /v1/models lists two models, but only for the right bearer key."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path != "/v1/models":
                self.send_error(404)
                return
            if self.headers.get("Authorization") != "Bearer setup-test-key":
                self.send_error(401)
                return
            body = json.dumps({"data": [{"id": "glm-x"}, {"id": "flash-y"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    server.shutdown()


@pytest.mark.skipif(shutil.which("curl") is None, reason="curl is not installed")
def test_setup_asks_tests_the_server_and_writes_work_env_and_can_run_again(
    mini_repo: Path, model_server: str
) -> None:
    answers = [
        "sv",  # language
        "j",  # turn the memory on
        model_server,  # model server address
        "setup-test-key",  # key (hidden input)
        "flash-y",  # memory model, by id
        "embed.company.lan:9443",  # allowlist
        "work",  # rooms
        "en",  # app language (own question, differs from the guide's sv)
        "n",  # autostart
        "n",  # start now
    ]
    result = run_work(mini_repo, "setup", stdin="\n".join(answers) + "\n")
    assert result.returncode == 0, result.stderr
    assert "Appens språk: en. Rum: work." in result.stdout
    assert "2 modeller hittades" in result.stdout
    assert "setup-test-key" not in result.stdout + result.stderr
    env_path = mini_repo / "deploy" / "work" / "work.env"
    env = env_path.read_text(encoding="utf-8")
    assert f"\nSIDEKICK_WORK_MODEL_BASE_URL={model_server}\n" in env
    assert "SIDEKICK_WORK_CHAT_MODEL" not in env
    assert "\nSIDEKICK_WORK_MEMORY_MODEL=flash-y\n" in env
    assert "\nSIDEKICK_WORK_ALLOW=embed.company.lan:9443\n" in env
    assert "\nSIDEKICK_ENABLED_ROOMS=work\n" in env
    assert "\nSIDEKICK_WORK_LOCALE=en\n" in env
    secrets = mini_repo / "deploy" / "work" / "secrets"
    written = (secrets / "sidekick.env").read_text()
    assert "\nWORK_MODEL_API_KEY=setup-test-key\n" in written
    assert not retired_names(written + (secrets / "hindsight.env").read_text())
    assert stat.S_IMODE((secrets / "sidekick.env").stat().st_mode) == 0o600
    env_path.write_text(env + "# a line the guide must not touch\n", encoding="utf-8")
    # Second run, English, every answer left at its default (Enter), key kept: nothing is lost.
    rerun = ["", model_server, "", "", "", "", "", "", "n", "n"]
    result = run_work(mini_repo, "setup", stdin="en\n" + "\n".join(rerun) + "\n")
    assert result.returncode == 0, result.stderr
    assert "2 models found" in result.stdout
    assert "Memory: on" in result.stdout
    assert env_path.read_text(encoding="utf-8") == env + "# a line the guide must not touch\n"
    assert "\nWORK_MODEL_API_KEY=setup-test-key\n" in (secrets / "sidekick.env").read_text()


def test_setup_without_memory_asks_for_no_model_server_and_starts_without_hindsight(
    mini_repo: Path,
) -> None:
    answers = [
        "en",
        "",  # memory: the proposal is no
        "",  # allowlist
        "-",  # rooms
        "",  # app language
        "n",  # autostart
        "y",  # start now
    ]
    result = run_work(mini_repo, "setup", stdin="\n".join(answers) + "\n")
    assert result.returncode == 0, result.stderr
    assert "Do you want to turn memory on? It needs a model server. (y/N)" in result.stderr
    assert "Model server address" not in result.stderr
    assert "Memory: off" in result.stdout
    env = (mini_repo / "deploy" / "work" / "work.env").read_text(encoding="utf-8")
    assert "\nSIDEKICK_WORK_MEMORY=off\n" in env
    calls = (mini_repo / "docker-calls.txt").read_text(encoding="utf-8")
    assert "--profile memory" not in calls
    assert "up -d" in calls
    derived = (mini_repo / "docker-env.txt").read_text(encoding="utf-8")
    assert "SIDEKICK_WORK_MEMORY_ENABLED=false" in derived


@pytest.mark.skipif(shutil.which("curl") is None, reason="curl is not installed")
def test_setup_rejects_a_bad_address_and_a_bad_allowlist_and_asks_again(
    mini_repo: Path, model_server: str
) -> None:
    answers = [
        "en",
        "y",  # memory on
        "ftp://nope",  # not an http(s) address: asked again
        model_server,
        "setup-test-key",
        "",  # memory model: default (first listed)
        "10.0.0.5:443",  # an IP cannot be allowed: asked again
        "",  # then none
        "-",  # rooms: all (Enter alone would take the proposal)
        "",  # app language: the proposal, Swedish
        "n",
        "n",
    ]
    result = run_work(mini_repo, "setup", stdin="\n".join(answers) + "\n")
    assert result.returncode == 0, result.stderr
    assert "That address cannot be used" in result.stderr
    assert "Invalid list" in result.stderr
    env = (mini_repo / "deploy" / "work" / "work.env").read_text(encoding="utf-8")
    assert "\nSIDEKICK_WORK_MEMORY_MODEL=glm-x\n" in env
    assert not re.search(r"^SIDEKICK_WORK_ALLOW=", env, re.M)
    assert not re.search(r"^SIDEKICK_ENABLED_ROOMS=", env, re.M)


@pytest.mark.skipif(shutil.which("curl") is None, reason="curl is not installed")
def test_guide_defaults_to_all_rooms_but_shopping_and_swedish_and_start_passes_them_on(
    mini_repo: Path, model_server: str
) -> None:
    answers = ["en", "y", model_server, "setup-test-key", "", "", "", "", "n", "y"]
    result = run_work(mini_repo, "setup", stdin="\n".join(answers) + "\n")
    assert result.returncode == 0, result.stderr
    assert "Enter = the proposal) [work,journal,contacts,control]" in result.stderr
    assert "Enter = the proposal) [sv]" in result.stderr
    for room in ("work", "journal", "shopping", "contacts", "control"):
        assert f"{room} =" in result.stdout
    work = mini_repo / "deploy" / "work"
    assert "\nSIDEKICK_ENABLED_ROOMS=work,journal,contacts,control\n" in (
        work / "work.env"
    ).read_text(encoding="utf-8")
    # "Start now" wrote the value where compose reads it for the api (and so for the stdio process).
    rooms_env = work / "secrets" / "rooms.env"
    assert (
        rooms_env.read_text(encoding="utf-8")
        == "SIDEKICK_ENABLED_ROOMS=work,journal,contacts,control\n"
    )
    assert (work / "secrets" / "claude_desktop_config.json").is_file()


@pytest.mark.parametrize("suffix", [".sv.md", ".md"])
def test_the_readmes_describe_stdio_and_backup_and_no_node_bridge(suffix: str) -> None:
    # The work guide is split into pages: the first start and the operating pages.
    # Both are read together.
    pages = [REPO_ROOT / "docs" / "start" / f"work-laptop{suffix}"]
    pages += [
        path
        for path in sorted((REPO_ROOT / "docs" / "operate" / "work-laptop").glob("*.md"))
        if path.name.endswith(".sv.md") == (suffix == ".sv.md")
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in pages)
    assert "mcp-remote" not in text and "npx" not in text and "work.sh pat" not in text
    for needed in (
        "sidekick.mcp.stdio",
        "docker exec",
        "hindsight-<",
        "SIDEKICK_BUILD_INFO_FILE",
        "bash tools/work.sh restore",
    ):
        assert needed in text, needed
