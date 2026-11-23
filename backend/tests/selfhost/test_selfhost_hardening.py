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


MEDIA_PATH = "/var/lib/sidekick/media"


def test_the_photo_files_have_a_volume_of_their_own_that_backup_only_reads(
    services: dict[str, dict],
) -> None:
    """Photos are written by the api and the worker into one volume, and never into the read-only
    root; the backup service mounts the same volume read-only and reads from the same path."""

    document = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    assert "media" in document["volumes"]
    for name, mount in (
        ("api", f"media:{MEDIA_PATH}"),
        ("automation-worker", f"media:{MEDIA_PATH}"),
        ("backup", f"media:{MEDIA_PATH}:ro"),
    ):
        assert mount in services[name]["volumes"], name
        assert services[name]["environment"]["SIDEKICK_MEDIA_DIRECTORY"] == MEDIA_PATH, name
    mounting = {
        name for name, service in services.items() if "media" in str(service.get("volumes"))
    }
    assert mounting == {"api", "automation-worker", "backup"}


def test_the_image_makes_the_media_directory_for_the_service_user() -> None:
    """A named volume starts with the owner and mode of the image's directory at its path."""

    dockerfile = (REPO_ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")

    assert f"-m 0700 /var/lib/sidekick {MEDIA_PATH}" in dockerfile
