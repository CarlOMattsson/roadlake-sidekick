"""Every service of the self-hosted stack is hardened; the exceptions are named and justified."""

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE = REPO_ROOT / "deploy" / "selfhost" / "compose.yaml"

# Postgres: its entrypoint starts as root, chowns the data directory and drops to the postgres user,
# so it keeps its capabilities and a writable root filesystem.
NOT_HARDENED_BY_DESIGN = {"postgres"}
# Caddy runs as root and binds 80 and 443, which needs exactly this one capability.
EXTRA_CAPABILITIES = {"caddy": ["NET_BIND_SERVICE"]}


@pytest.fixture(name="services")
def _services() -> dict[str, dict]:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]


def test_every_service_but_postgres_drops_all_capabilities_on_a_read_only_filesystem(
    services: dict[str, dict],
) -> None:
    for name, service in services.items():
        if name in NOT_HARDENED_BY_DESIGN:
            continue
        assert service.get("read_only") is True, name
        assert service.get("cap_drop") == ["ALL"], name
        assert service.get("cap_add", []) == EXTRA_CAPABILITIES.get(name, []), name


def test_every_service_forbids_privilege_escalation(services: dict[str, dict]) -> None:
    for name, service in services.items():
        assert "no-new-privileges:true" in service.get("security_opt", []), name
        assert service.get("privileged") is not True, name


def test_caddy_and_hindsight_write_only_to_volumes_and_tmp(services: dict[str, dict]) -> None:
    assert services["caddy"]["tmpfs"] == ["/tmp"]  # noqa: S108 - a container path, not a host file
    assert {"caddy_data:/data", "caddy_config:/config"} <= set(services["caddy"]["volumes"])
    hindsight = services["hindsight"]
    assert hindsight["tmpfs"] == ["/tmp"]  # noqa: S108 - a container path, not a host file
    # A read-only root filesystem refuses the hub's refs file, so the image's models run offline.
    assert hindsight["environment"]["HF_HUB_OFFLINE"] == "1"
    assert hindsight["environment"]["TRANSFORMERS_OFFLINE"] == "1"
