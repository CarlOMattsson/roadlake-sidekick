"""The tailscale profile: Funnel in a container, pinned, key as a file, and nothing else changes."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

SELFHOST = Path(__file__).resolve().parents[3] / "deploy" / "selfhost"
IMAGE = re.compile(r"tailscale/tailscale:v\d+\.\d+\.\d+@sha256:[0-9a-f]{64}")
KEY_PREFIX = "tskey-"


@pytest.fixture(name="compose")
def _compose() -> dict:
    return yaml.safe_load((SELFHOST / "compose.yaml").read_text(encoding="utf-8"))


@pytest.fixture(name="service")
def _service(compose: dict) -> dict:
    return compose["services"]["tailscale"]


@pytest.fixture(name="serve")
def _serve() -> dict:
    return json.loads((SELFHOST / "tailscale" / "serve.json").read_text(encoding="utf-8"))


def test_the_profile_is_opt_in_and_the_image_is_an_exact_version_pinned_by_digest(
    service: dict,
) -> None:
    assert service["profiles"] == ["tailscale"]
    assert IMAGE.fullmatch(service["image"]), service["image"]


def test_the_stack_without_the_profile_does_not_start_it(compose: dict) -> None:
    default_services = {
        name for name, service in compose["services"].items() if "profiles" not in service
    }
    assert default_services == {"postgres", "migrate", "api", "automation-worker"}


def test_the_node_publishes_no_port_and_sits_on_edge_alone(service: dict, compose: dict) -> None:
    assert "ports" not in service
    assert service["networks"] == {"edge": {}}
    # Not the proxy network: api trusts forwarded headers only from Caddy's address there.
    assert "tailscale" not in {
        name for name, s in compose["services"].items() if "proxy" in (s.get("networks") or {})
    }


def test_the_auth_key_is_a_mounted_file_never_an_environment_value(service: dict) -> None:
    assert service["secrets"] == ["tailscale_authkey"]
    credentials = {"TS_AUTHKEY", "TS_AUTH_KEY", "TS_CLIENT_ID", "TS_CLIENT_SECRET", "TS_ID_TOKEN"}
    assert not credentials & set(service["environment"])
    assert "env_file" not in service
    assert "/run/secrets/tailscale_authkey" in " ".join(service["command"])
    assert KEY_PREFIX not in yaml.safe_dump(service)


def test_the_node_state_survives_in_a_named_volume(service: dict, compose: dict) -> None:
    state_dir = service["environment"]["TS_STATE_DIR"]
    assert f"tsstate:{state_dir}" in service["volumes"]
    assert "tsstate" in compose["volumes"]
    assert service["environment"]["TS_AUTH_ONCE"] == "true"


def test_it_runs_in_userspace_with_the_serve_config_from_the_repository(service: dict) -> None:
    assert service["environment"]["TS_USERSPACE"] == "true"
    config = service["environment"]["TS_SERVE_CONFIG"]
    mounted = [v for v in service["volumes"] if v.startswith("./tailscale:")]
    assert mounted == [f"./tailscale:{Path(config).parent}:ro"]
    assert Path(config).name == "serve.json"
    assert "devices" not in service


def test_funnel_publishes_the_api_over_https_on_the_nodes_own_name(serve: dict) -> None:
    host = "${TS_CERT_DOMAIN}:443"
    assert serve["TCP"] == {"443": {"HTTPS": True}}
    assert serve["AllowFunnel"] == {host: True}
    assert serve["Web"] == {host: {"Handlers": {"/": {"Proxy": "http://api:8000"}}}}


def test_the_env_example_documents_the_profile_and_holds_no_key() -> None:
    text = (SELFHOST / "selfhost.env.example").read_text(encoding="utf-8")
    for line in (
        "#SELFHOST_TAILSCALE_HOSTNAME=sidekick",
        "#SELFHOST_TAILSCALE_AUTHKEY_FILE=./secrets/tailscale_authkey",
    ):
        assert f"\n{line}\n" in text, line
    # The example names the prefix only inside a command a person types; no line assigns a key.
    assert not re.search(rf"^[A-Z_]+={KEY_PREFIX}", text, re.MULTILINE)
    assert not re.search(rf"{KEY_PREFIX}[A-Za-z0-9]{{8,}}", text)


def test_no_file_of_the_package_carries_a_tailscale_key() -> None:
    for path in SELFHOST.rglob("*"):
        if path.is_file() and path.suffix in {".yaml", ".json", ".example", ".md", ".sh"}:
            assert not re.search(
                rf"{KEY_PREFIX}[A-Za-z0-9]{{8,}}", path.read_text(encoding="utf-8")
            ), path


@pytest.mark.skipif(shutil.which("docker") is None, reason="needs the docker CLI (no daemon)")
def test_compose_accepts_the_profile_and_only_the_profile_adds_the_service(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / "selfhost.env"
    shutil.copy(SELFHOST / "selfhost.env.example", env_file)

    def services(*profile: str) -> set[str]:
        result = subprocess.run(
            ["docker", "compose", "--env-file", str(env_file), *profile, "config", "--services"],
            cwd=SELFHOST,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        return set(result.stdout.split())

    base = services()
    assert "tailscale" not in base
    assert services("--profile", "tailscale") == base | {"tailscale"}
