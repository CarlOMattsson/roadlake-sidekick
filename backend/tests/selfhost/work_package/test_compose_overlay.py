"""The Compose overlay of the work package and its model gateway: pins, ports, networks, health."""

import os
import re
import shutil
import stat
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from tools.workctl import probe_egress

from sidekick.shared.config import Settings, secret_file_variable_names
from tests.selfhost.work_package.support import (
    MARKER,
    REPO_ROOT,
    SCRIPT,
    SELFHOST,
    WORK,
    ComposeLoader,
    TaggedList,
    directive,
    haproxy_sections,
    retired_names,
    run_work,
)
from tests.support.polling import wait_until

# Registry manifest lists, checked 2026-11-09 (haproxy 3.4.7-alpine, the LTS line).
HAPROXY_DIGEST = "sha256:5312d37032c079c4937d45ef63758852434351f3b425a3703521fd999837abcf"


def _strings(node: Any) -> Iterator[str]:
    """Every string anywhere in a parsed YAML value, keys included."""

    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(key)
            yield from _strings(value)
    elif isinstance(node, list):
        for item in node:
            yield from _strings(item)


# Setting families of removed features (model providers, Journal AI, agent runtime).
# Settings forbids undeclared SIDEKICK_ names, so nothing the package writes may name one: it would
# stop the start. The one exception is the old key name tools/work.sh deletes from a secrets file
# left by an older version.
LEGACY_NAME_THE_SCRIPT_DELETES = {"chat_custom_api_key"}


def test_the_overlay_parses_and_adds_the_gateway(overlay: dict[str, Any]) -> None:
    assert overlay["name"] == "sidekick-work"
    assert {
        "api",
        "memory-worker",
        "automation-worker",
        "hindsight",
        "gateway",
        "migrate",
        "postgres",
    } <= set(overlay["services"])


def test_the_overlay_is_pinned_by_digest() -> None:
    gateway = yaml.load((WORK / "compose.yaml").read_text(encoding="utf-8"), Loader=ComposeLoader)[
        "services"
    ]["gateway"]
    assert re.fullmatch(r"haproxy:\d+\.\d+\.\d+-alpine@sha256:[0-9a-f]{64}", gateway["image"])
    assert gateway["image"].endswith(HAPROXY_DIGEST)


def test_every_service_of_the_stack_rotates_its_container_log(merged: dict[str, Any]) -> None:
    """The gateway sets the limits itself; the others inherit them from the self-hosted file."""

    selfhost = yaml.safe_load((SELFHOST / "compose.yaml").read_text(encoding="utf-8"))
    expected = next(iter(selfhost["services"].values()))["logging"]
    assert merged["services"]
    for name, service in merged["services"].items():
        assert service["logging"] == expected, name


def test_every_external_image_of_the_stack_is_pinned_by_digest(merged: dict[str, Any]) -> None:
    for name in ("hindsight", "gateway"):
        image = merged["services"][name]["image"]
        assert re.search(r"@sha256:[0-9a-f]{64}$", image), (name, image)
    # Sidekick's own image is built from this checkout; the database is the self-hosted pinned tag.
    assert re.fullmatch(
        r"postgres:18\.4-alpine@sha256:[0-9a-f]{64}", merged["services"]["postgres"]["image"]
    )
    selfhost = yaml.safe_load((SELFHOST / "compose.yaml").read_text(encoding="utf-8"))
    assert merged["services"]["hindsight"]["image"] == selfhost["services"]["hindsight"]["image"]


def test_only_the_gateway_publishes_a_port_and_only_on_loopback(merged: dict[str, Any]) -> None:
    for name, service in merged["services"].items():
        ports = service.get("ports") or []
        if name != "gateway":
            assert not ports, name
            continue
        assert len(ports) == 1
        assert ports[0]["host_ip"] == "127.0.0.1"
        assert ports[0]["target"] == 8765
        assert service.get("network_mode") != "host"
        assert service.get("privileged") is not True and "cap_add" not in service


def test_no_service_in_the_work_profile_set_can_publish_on_all_interfaces(
    overlay: dict[str, Any],
) -> None:
    for name, service in overlay["services"].items():
        for port in service.get("ports", []):
            published = port["host_ip"] + ":" if isinstance(port, dict) else str(port)
            assert published.startswith("127.0.0.1:"), (name, port)
    assert "caddy" not in overlay["services"]


def test_only_the_gateway_has_a_route_to_the_outside(merged: dict[str, Any]) -> None:
    networks = merged["networks"]
    internal = {name for name, net in networks.items() if net.get("internal")}
    assert internal == {"data", "edge", "proxy"}
    routed = {name for name in networks if name not in internal}
    assert routed == {"egress"}
    for name, service in merged["services"].items():
        on_routed = routed & set(service.get("networks", {}))
        assert on_routed == ({"egress"} if name == "gateway" else set()), name
    assert "model.work.internal" in merged["services"]["gateway"]["networks"]["edge"]["aliases"]


def test_the_egress_probe_looks_up_a_name_that_exists() -> None:
    # A forwarding resolver answers NXDOMAIN for a made-up name, which would read as blocked.
    # Only a failed lookup of a name that certainly exists proves DNS is closed.
    looked_up: list[str] = []

    def lookup(name: str, _port: int) -> None:
        looked_up.append(name)

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise OSError("refused")

    probe_egress.probe("", "1", "REACHED", "blocked", "direct", refuse, lookup)
    assert looked_up == ["example.com"]


GATEWAY_IMAGE = re.search(
    r"image: (haproxy:\S+)", (WORK / "compose.yaml").read_text(encoding="utf-8")
)


def _in_container(name: str, command: str) -> bool:
    done = subprocess.run(
        ["docker", "exec", name, "sh", "-c", command],
        capture_output=True, timeout=30, check=False,
    )  # fmt: skip
    return done.returncode == 0


@pytest.fixture(scope="module")
def live_gateway() -> Iterator[str]:
    """The real gateway configuration in a throwaway container with no network; yields its name."""

    if shutil.which("docker") is None or GATEWAY_IMAGE is None:
        pytest.skip("docker is not installed")
    name = f"sidekick-gateway-test-{os.getpid()}"
    started = subprocess.run(
        ["docker", "run", "-d", "--rm", "--name", name, "--network", "none",
         "--add-host", "api:127.0.0.1", "--add-host", "up.invalid:127.0.0.1",
         "-v", f"{WORK / 'gateway.haproxy.cfg'}:/usr/local/etc/haproxy/haproxy.cfg:ro",
         "-e", "GATEWAY_MODEL_PORT=9000", "-e", "GATEWAY_MODEL_PATH=/v1",
         "-e", "GATEWAY_UPSTREAM=up.invalid:8080", "-e", "GATEWAY_UPSTREAM_HOST_HEADER=up.invalid",
         "-e", "GATEWAY_UPSTREAM_TLS[*]=", GATEWAY_IMAGE.group(1)],
        capture_output=True, text=True, timeout=120, check=False,
    )  # fmt: skip
    if started.returncode != 0:
        pytest.skip(f"cannot start the gateway image: {started.stderr.strip()[:200]}")
    try:
        wait_until(
            lambda: _in_container(name, "nc -z 127.0.0.1 9000"),
            timeout=30,
            what="the gateway to listen",
            interval=0.2,
        )
        # A stand-in model server in the container: it answers 200 to what the gateway lets through.
        answer = r'printf "HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"'
        loop = f"while true; do {answer} | nc -l -p 8080 >/dev/null; done"
        subprocess.run(["docker", "exec", "-d", name, "sh", "-c", loop], timeout=30, check=False)
        # The whole chain answers once a request through the gateway reaches the stand-in.
        wait_until(
            lambda: _gateway_status(name, "/v1/models") == "200",
            timeout=30,
            what="the stand-in model server to answer through the gateway",
            interval=0.2,
        )
        yield name
    finally:
        subprocess.run(["docker", "stop", name], capture_output=True, timeout=60, check=False)


def _gateway_status(name: str, raw_path: str) -> str:
    request = f"GET {raw_path} HTTP/1.1\\r\\nHost: x\\r\\nConnection: close\\r\\n\\r\\n"
    script = '{ printf "%b" "$1"; sleep 0.5; } | nc -w 3 127.0.0.1 9000 | head -1'
    done = subprocess.run(
        ["docker", "exec", name, "sh", "-c", script, "_", request],
        capture_output=True, text=True, timeout=30, check=False,
    )  # fmt: skip
    return done.stdout.split()[1] if done.stdout.startswith("HTTP/") else ""


@pytest.mark.parametrize(
    "raw_path",
    [
        "/v1x", "/v1x/models", "/admin", "/v1/../admin", "/v1/..", "/../v1/models",
        "/v1/%2e%2e/admin", "/v1/%2E./admin", "/v1/..%2fadmin", "/v1/%%32%65%%32%65/admin",
        "/v1/..;/admin", "/v1/a;b",
        "/v1/a%5cb", "/v1/a\\\\b", "/v1/%252e%252e/admin", "/v1/models%00", "/v1%2fmodels",
    ],
)  # fmt: skip
def test_the_live_gateway_refuses_paths_that_could_be_read_as_another_path(
    live_gateway: str, raw_path: str
) -> None:
    assert _gateway_status(live_gateway, raw_path) == "403"


@pytest.mark.parametrize(
    "raw_path",
    ["/v1", "/v1/", "/v1/models", "/v1/chat/completions", "/v1/models/a:b", "/v1/./models",
     "//v1/models", "/v1/models?x=%20"],
)  # fmt: skip
def test_the_live_gateway_passes_the_base_path_and_what_lies_under_it(
    live_gateway: str, raw_path: str
) -> None:
    assert _gateway_status(live_gateway, raw_path) == "200"


def test_the_gateway_is_locked_down(merged: dict[str, Any]) -> None:
    gateway = merged["services"]["gateway"]
    assert gateway["read_only"] is True
    assert gateway["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in gateway["security_opt"]
    config = haproxy_sections((WORK / "gateway.haproxy.cfg").read_text(encoding="utf-8"))
    servers = {header: directive(lines, "server") for header, lines in config.items()}
    assert {header: len(found) for header, found in servers.items() if found} == {
        "backend sidekick_api": 1,
        "backend model_server": 1,
    }, "one server for api, one for the model upstream"
    model = config["frontend model"]
    # The base path is one whole segment: exactly "/v1" or beginning "/v1/", never "/v1x".
    assert [t[3] for t in directive(model, "acl", "base_path")] == [
        '"${GATEWAY_MODEL_PATH}"',
        '"${GATEWAY_MODEL_PATH}/"',
    ]
    assert [t[2] for t in directive(model, "acl", "base_path")] == ["path", "path_beg"]
    denies = directive(model, "http-request", "deny", "deny_status", "403")
    assert [" ".join(tokens[tokens.index("if") :]) for tokens in denies] == [
        "if odd_path or dotdot_path",
        "if !base_path",
    ], "all else is a 403"
    # Refusing "%", ";", a backslash and a ".." segment looks at the raw path, before normalizing.
    order = [
        line.split()[1] if line.startswith("acl") else " ".join(line.split()[:3]) for line in model
    ]
    assert order.index("odd_path") < order.index("http-request normalize-uri path-strip-dotdot")
    assert order.index("dotdot_path") < order.index("http-request normalize-uri path-merge-slashes")
    assert not directive(model, "http-request", "normalize-uri", "percent-decode-unreserved"), (
        "percent-encoding is refused, never decoded"
    )
    assert not directive(config["frontend mcp"], "option", "forwardfor"), (
        "nothing in api reads X-Forwarded-For"
    )
    for header, lines in config.items():
        assert not directive(lines, "log"), header
        assert not directive(lines, "option", "httplog"), header
        assert not directive(lines, "option", "tcplog"), header


def test_the_stack_uses_the_work_secrets_and_never_the_selfhost_env_files(
    merged: dict[str, Any], overlay: dict[str, Any]
) -> None:
    declared = overlay["services"]
    assert not any("selfhost.env" in s or "./db.env" in s for s in _strings(declared))
    env_files = {name: s["env_file"] for name, s in declared.items() if "env_file" in s}
    assert len(env_files) >= 5
    for name, entries in env_files.items():
        assert isinstance(entries, TaggedList) and entries.tag == "override", name
        for entry in entries:
            path = entry["path"] if isinstance(entry, dict) else entry
            assert path.startswith("../work/secrets/"), (name, path)
    services = merged["services"]
    assert services["postgres"]["environment"]["POSTGRES_PASSWORD"] == MARKER
    assert services["migrate"]["environment"]["POSTGRES_PASSWORD"] == MARKER
    assert services["api"]["environment"]["SIDEKICK_CURSOR_SIGNING_SECRET"] == MARKER
    assert services["memory-worker"]["environment"]["SIDEKICK_TOKEN_PEPPER"] == MARKER
    assert services["automation-worker"]["environment"]["SIDEKICK_TOKEN_PEPPER"] == MARKER
    assert services["hindsight"]["environment"]["HINDSIGHT_API_TENANT_API_KEY"] == MARKER


def test_every_sidekick_setting_in_the_overlay_is_declared_and_the_settings_validate(
    merged: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The api refuses an undeclared SIDEKICK_ variable; production validates the model routes."""

    declared = {f"SIDEKICK_{name}".upper() for name in Settings.model_fields}
    declared |= secret_file_variable_names(Settings)
    for name in ("api", "memory-worker", "automation-worker"):
        environment = merged["services"][name]["environment"]
        assert not {k for k in environment if k.startswith("SIDEKICK_")} - declared, name
        assert not retired_names(" ".join(environment)), name
    environment = dict(merged["services"]["api"]["environment"])
    for key in [k for k in os.environ if k.startswith("SIDEKICK_")]:
        monkeypatch.delenv(key)
    for key, value in environment.items():
        monkeypatch.setenv(key, str(value))
    monkeypatch.chdir(tmp_path)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.mcp_auth_mode == "pat"
    assert settings.mcp_server_name == "Sidekick Work"
    assert settings.memory_enabled and settings.memory_provider == "hindsight"
    assert not settings.companion_enabled and not settings.push_enabled


def test_hindsight_uses_the_openai_provider_through_the_gateway_with_local_embeddings(
    merged: dict[str, Any],
) -> None:
    environment = merged["services"]["hindsight"]["environment"]
    assert environment["HINDSIGHT_API_LLM_PROVIDER"] == "openai"
    assert environment["HINDSIGHT_API_LLM_BASE_URL"] == "http://model.work.internal:8000/v1"
    assert environment["HINDSIGHT_API_LLM_MODEL"] == "flash-test"
    assert environment["HINDSIGHT_API_EMBEDDINGS_PROVIDER"] == "local"
    assert environment["HF_HUB_OFFLINE"] == "1"


def test_without_memory_there_is_no_hindsight_or_memory_worker_and_sidekick_memory_is_off(
    merged_without_memory: dict[str, Any],
) -> None:
    services = merged_without_memory["services"]
    assert "hindsight" not in services and "memory-worker" not in services
    assert {"api", "gateway", "automation-worker", "postgres"} <= set(services)
    assert services["api"]["environment"]["SIDEKICK_MEMORY_ENABLED"] == "false"


def test_the_package_names_no_retired_sidekick_setting() -> None:
    files = [
        SCRIPT,
        REPO_ROOT / "tools" / "workctl" / "messages.json",
        *sorted((REPO_ROOT / "tools" / "workctl").glob("*.py")),
        WORK / "compose.yaml",
        WORK / "work.env.example",
        *sorted((REPO_ROOT / "docs" / "start").glob("work-laptop*.md")),
        *sorted((REPO_ROOT / "docs" / "operate" / "work-laptop").glob("*.md")),
    ]
    for path in files:
        retired = retired_names(path.read_text(encoding="utf-8")) - LEGACY_NAME_THE_SCRIPT_DELETES
        assert not retired, (path.name, retired)
    text = SCRIPT.read_text(encoding="utf-8")
    assert "SIDEKICK_WORK_CHAT_MODEL" not in text and "SIDEKICK_WORK_CHAT_MODEL" not in (
        WORK / "work.env.example"
    ).read_text(encoding="utf-8")


def test_the_env_example_holds_no_secret_and_only_work_names() -> None:
    text = (WORK / "work.env.example").read_text(encoding="utf-8")
    names = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", text, re.M))
    assert names
    assert all(n.startswith("SIDEKICK_WORK_") or n == "SIDEKICK_ENABLED_ROOMS" for n in names), (
        names
    )
    assert re.search(r"^SIDEKICK_WORK_INSTANCE_LABEL=Sidekick Work$", text, re.M)
    # A work machine shows every room but shopping, from the first start.
    assert re.search(r"^SIDEKICK_ENABLED_ROOMS=work,journal,contacts,control$", text, re.M)
    assert re.search(r"^SIDEKICK_WORK_MODEL_BASE_URL=http://<vllm-host>:<port>/v1$", text, re.M)
    assert not re.search(r"(?i)(api_?key|token|password|secret)\s*=\s*\S", text)
    assert not re.search(r"sk-[A-Za-z0-9]{10,}|[A-Za-z0-9+/]{40,}={0,2}", text)


def test_the_secret_files_are_ignored_and_the_examples_are_not() -> None:
    for path in (
        "deploy/work/work.env",
        "deploy/work/secrets/sidekick.env",
        "deploy/work/secrets/db.env",
        "deploy/work/secrets/hindsight.env",
        "deploy/work/secrets/mcp-token",
        "deploy/work/secrets/claude_desktop_config.json",
        "deploy/work/secrets/backup.key",
        "deploy/work/backups/sidekick-20261109.sql.enc",
        "deploy/work/.work.lock",
        "deploy/work/.work.lock.d/owner",
    ):
        result = subprocess.run(["git", "check-ignore", "-q", path], cwd=REPO_ROOT)
        assert result.returncode == 0, f"{path} must be gitignored"
    for path in (
        "deploy/work/work.env.example",
        "deploy/work/compose.yaml",
        "deploy/work/gateway.haproxy.cfg",
        "tools/work.sh",
    ):
        result = subprocess.run(["git", "check-ignore", "-q", path], cwd=REPO_ROOT)
        assert result.returncode == 1, f"{path} must be tracked"


def test_the_readiness_code_is_the_one_the_selfhost_updater_runs() -> None:
    pattern = r"^READINESS_PY='(.*?)'$"
    ours = re.search(pattern, SCRIPT.read_text(encoding="utf-8"), re.MULTILINE | re.DOTALL)
    theirs = re.search(
        pattern, (SELFHOST / "update.sh").read_text(encoding="utf-8"), re.MULTILINE | re.DOTALL
    )
    assert ours is not None and theirs is not None
    assert ours.group(1).strip() == theirs.group(1).strip()


def test_the_api_health_is_the_selfhost_readiness_and_the_gateway_waits_for_it(
    overlay: dict[str, Any],
) -> None:
    """Same readiness as selfhost: the api has no healthcheck of its own in the overlay."""

    assert "healthcheck" not in overlay["services"]["api"], "the MCP-only check must not return"
    compose = yaml.safe_load((SELFHOST / "compose.yaml").read_text(encoding="utf-8"))
    test = compose["services"]["api"]["healthcheck"]["test"]
    ours = re.search(
        r"^READINESS_PY='(.*?)'$", SCRIPT.read_text(encoding="utf-8"), re.MULTILINE | re.DOTALL
    )
    assert ours is not None
    assert test[:3] == ["CMD", "python", "-c"]
    assert test[3].strip() == ours.group(1).strip()
    assert "sidekick.shared.readiness" in test[3]
    assert overlay["services"]["gateway"]["depends_on"] == {"api": {"condition": "service_healthy"}}


def test_the_merged_api_healthcheck_is_the_readiness_code(merged: dict[str, Any]) -> None:
    test = merged["services"]["api"]["healthcheck"]["test"]
    assert "sidekick.shared.readiness" in test[-1]
    assert merged["services"]["gateway"]["depends_on"]["api"]["condition"] == "service_healthy"


def test_the_overlay_keeps_the_worker_healthchecks_of_the_selfhost_file(
    overlay: dict[str, Any],
) -> None:
    """The workers inherit the heartbeat check; an overlay `healthcheck` would replace it."""

    for name in ("memory-worker", "automation-worker"):
        assert "healthcheck" not in overlay["services"][name], name


def test_the_merged_workers_are_healthy_only_while_their_loop_beats(
    merged: dict[str, Any],
) -> None:
    for name, worker in (("memory-worker", "memory"), ("automation-worker", "automation")):
        health = merged["services"][name]["healthcheck"]
        selfhost = yaml.safe_load((SELFHOST / "compose.yaml").read_text(encoding="utf-8"))
        code = selfhost["x-sidekick-worker-health-check"]
        assert health["test"] == ["CMD", "python", "-c", code, worker], name


def test_hindsight_waits_for_the_gateway_healthcheck_without_a_dependency_cycle(
    overlay: dict[str, Any],
) -> None:
    services = yaml.safe_load((SELFHOST / "compose.yaml").read_text(encoding="utf-8"))["services"]
    for name, service in overlay["services"].items():
        services.setdefault(name, {}).setdefault("depends_on", {}).update(
            service.get("depends_on", {})
        )
    assert services["hindsight"]["depends_on"]["gateway"] == {"condition": "service_healthy"}
    assert overlay["services"]["gateway"]["healthcheck"]["test"][-1].endswith("/__gateway_health")

    def visit(name: str, ancestors: tuple[str, ...] = ()) -> None:
        assert name not in ancestors, (*ancestors, name)
        for dependency in services[name].get("depends_on", {}):
            visit(dependency, (*ancestors, name))

    for name in services:
        visit(name)


def test_selfhost_copies_the_role_script_before_the_official_entrypoint(tmp_path: Path) -> None:
    postgres = yaml.safe_load((SELFHOST / "compose.yaml").read_text(encoding="utf-8"))["services"][
        "postgres"
    ]
    mount = "./postgres-init.sh:/usr/local/share/sidekick/postgres-init.sh:ro"
    assert mount in postgres["volumes"]
    entrypoint = postgres["entrypoint"]
    assert entrypoint[:2] == ["sh", "-ec"]
    source, destination = tmp_path / "source.sh", tmp_path / "roles.sh"
    source.write_text("#!/bin/sh\n# public role bootstrap\n", encoding="utf-8")
    source.chmod(0o600)
    official = tmp_path / "docker-entrypoint.sh"
    official.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n', encoding="utf-8")
    official.chmod(0o755)
    script = entrypoint[2].replace("$$", "$")
    script = script.replace("/usr/local/share/sidekick/postgres-init.sh", str(source))
    script = script.replace("/docker-entrypoint-initdb.d/10-sidekick-roles.sh", str(destination))
    result = subprocess.run(
        [*entrypoint[:2], script, entrypoint[3], *postgres["command"]],
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"},
        umask=0o077,
    )
    assert result.returncode == 0, result.stderr
    assert destination.read_bytes() == source.read_bytes()
    assert stat.S_IMODE(destination.stat().st_mode) == 0o755
    assert result.stdout.splitlines() == postgres["command"], "all PostgreSQL flags survive"


@pytest.mark.parametrize("mask, warned", [(0o077, True), (0o027, True), (0o022, False), (0, False)])
@pytest.mark.parametrize("command", ["setup", "start"])
def test_setup_and_start_warn_about_the_callers_umask(
    mini_repo: Path, command: str, mask: int, warned: bool
) -> None:
    # A partial init makes setup stop immediately after the warning, without asking for an address.
    secrets = mini_repo / "deploy" / "work" / "secrets"
    secrets.mkdir()
    (secrets / "db.env").write_text("synthetic\n", encoding="utf-8")
    result = run_work(mini_repo, command, stdin="en\n", umask=mask, SIDEKICK_WORK_LANG="en")
    assert ("WARNING: umask" in result.stderr) == warned
    if warned:
        assert "stricter than 022" in result.stderr
