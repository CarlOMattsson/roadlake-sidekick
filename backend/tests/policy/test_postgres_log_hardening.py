"""Every PostgreSQL server in the compose files keeps data out of its error log.

A failing statement is logged in full by default (``log_min_error_statement=error``), and constraint
errors add DETAIL lines that quote row values. Journal text and contact details can be in both,
and the
Python-side redaction never sees the database's own stderr.
"""

from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]

# The published compose files must exist and carry a hardened PostgreSQL server. Any other compose
# file that happens to be in the checkout (the maintainer's own stacks are not exported) is
# discovered, not named, and is checked when it has a PostgreSQL server.
EXPORTED_FILES = (
    "deploy/selfhost/compose.yaml",
    "deploy/compose.dev.yaml",
    "deploy/compose.test.yaml",
)


def compose_files() -> tuple[str, ...]:
    found = {
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "deploy").glob("compose*.yaml")
    }
    return tuple(sorted(found | set(EXPORTED_FILES)))


POSTGRES_COMPOSE_FILES = compose_files()

REQUIRED_SETTINGS = {
    "log_min_error_statement": "panic",
    "log_error_verbosity": "terse",
    "log_parameter_max_length_on_error": "0",
    "log_parameter_max_length": "0",
    "log_statement": "none",
    "log_min_duration_statement": "-1",
}


def postgres_server_settings(command: Any) -> dict[str, str]:
    """The ``-c name=value`` pairs of a ``postgres ...`` command."""

    assert isinstance(command, list), command
    assert command[0] == "postgres", command
    settings: dict[str, str] = {}
    for flag, value in pairwise(command[1:]):
        if flag == "-c":
            name, _, setting = str(value).partition("=")
            settings[name] = setting
    return settings


def postgres_servers(relative: str) -> dict[str, dict[str, Any]]:
    path = REPO_ROOT / relative
    if not path.exists():
        if relative in EXPORTED_FILES:
            pytest.fail(f"{relative} is missing")
        pytest.skip(f"{relative} is not part of this checkout")
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        name: service
        for name, service in document["services"].items()
        if str(service.get("image", "")).startswith("postgres:")
        # Skip one-shot psql clients that reuse the image.
        and "psql" not in str(service.get("command", ""))
    }


@pytest.mark.policy
@pytest.mark.parametrize("relative", POSTGRES_COMPOSE_FILES)
def test_postgres_server_keeps_data_out_of_its_error_log(relative: str) -> None:
    services = postgres_servers(relative)
    if not services and relative not in EXPORTED_FILES:
        pytest.skip(f"{relative} has no PostgreSQL server")
    assert services, f"{relative} has no PostgreSQL server service"
    for name, service in services.items():
        settings = postgres_server_settings(service.get("command"))
        for setting, expected in REQUIRED_SETTINGS.items():
            assert settings.get(setting) == expected, (relative, name, setting)


@pytest.mark.policy
def test_work_package_does_not_replace_the_selfhost_database_command() -> None:
    """The work stack extends the self-hosted file, so the database keeps the hardened command."""

    text = (REPO_ROOT / "deploy/work/compose.yaml").read_text(encoding="utf-8")
    postgres_block = text.split("\n  postgres:\n", 1)[1].split("\n  migrate:\n", 1)[0]
    assert "command:" not in postgres_block
