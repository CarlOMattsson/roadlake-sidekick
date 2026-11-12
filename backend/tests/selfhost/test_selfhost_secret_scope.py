"""Self-hosted compose: each service gets only the secrets it reads, and has resource limits."""

import ast
import re
from pathlib import Path

import pytest
import yaml

from sidekick.shared.config import Settings
from sidekick.shared.config.environment import RENAMED_SETTINGS

SELFHOST = Path(__file__).resolve().parents[3] / "deploy" / "selfhost"
SOURCE = Path(__file__).resolve().parents[2] / "src" / "sidekick"
WORKERS = ("automation-worker", "backup", "push", "memory-worker")
LIMITED = ("postgres", "migrate", "api", *WORKERS, "hindsight")
DECLARED = {f"SIDEKICK_{name}".upper() for name in Settings.model_fields}
BACKUP_FLOOR_BYTES = 2 * 1024**3  # 512 MiB of plaintext, several copies alive while it is encrypted
UNITS = {"m": 1024**2, "g": 1024**3}


@pytest.fixture(name="services")
def _services() -> dict[str, dict]:
    compose = yaml.safe_load((SELFHOST / "compose.yaml").read_text(encoding="utf-8"))
    return compose["services"]


def _bare_names(service: dict) -> set[str]:
    """Names passed through from the --env-file of the command (declared without a value)."""
    return {name for name, value in service.get("environment", {}).items() if value is None}


def _default(expression: str, variable_suffix: str) -> str:
    match = re.fullmatch(
        r"\$\{(SELFHOST_[A-Z_]+" + variable_suffix + r"):-([^}]+)\}", str(expression)
    )
    assert match, expression
    return match.group(2)


def test_workers_have_no_env_file_and_api_alone_reads_all_of_selfhost_env(
    services: dict[str, dict],
) -> None:
    for name in WORKERS:
        assert "env_file" not in services[name], name
    assert services["api"]["env_file"] == [{"path": "./selfhost.env", "required": False}]
    for name in ("postgres", "migrate"):
        assert services[name]["env_file"] == [{"path": "./db.env", "required": False}], name
    assert "env_file" not in services["backup"]


def test_every_passed_name_is_a_declared_setting(services: dict[str, dict]) -> None:
    for name in WORKERS:
        names = _bare_names(services[name])
        assert names, name
        # A removed name is passed on on purpose: Settings then stops and names its successor.
        unknown = names - DECLARED - {f"SIDEKICK_{old}" for old in RENAMED_SETTINGS}
        assert not unknown, (name, sorted(unknown))


def test_every_worker_gets_what_production_requires_to_start(services: dict[str, dict]) -> None:
    required = {
        "SIDEKICK_DATABASE_URL",
        "SIDEKICK_CURSOR_SIGNING_SECRET",
        "SIDEKICK_TOKEN_PEPPER",
    }
    for name in WORKERS:
        assert services[name]["environment"]["SIDEKICK_ENVIRONMENT"] == "production", name
        assert required <= _bare_names(services[name]), name


def test_no_worker_holds_the_oauth_settings(services: dict[str, dict]) -> None:
    for name in WORKERS:
        leaked = {n for n in _bare_names(services[name]) if n.startswith("SIDEKICK_MCP_OAUTH_")}
        assert not leaked, (name, leaked)
        assert "SIDEKICK_MCP_AUTH_MODE" not in services[name]["environment"], name


@pytest.mark.parametrize(
    ("secret", "owner"),
    [
        ("SIDEKICK_BACKUP_ENCRYPTION_KEY", "backup"),
        ("SIDEKICK_PUSH_AUTH_TOKEN", "push"),
        ("SIDEKICK_MEMORY_HINDSIGHT_API_TOKEN", "memory-worker"),
    ],
)
def test_a_service_specific_secret_reaches_only_the_services_that_read_it(
    services: dict[str, dict], secret: str, owner: str
) -> None:
    holders = {name for name in WORKERS if secret in _bare_names(services[name])}
    assert owner in holders
    # The memory token is also read by the automation worker (it builds the same container as api).
    assert holders <= {owner, "automation-worker"}, holders
    if secret != "SIDEKICK_MEMORY_HINDSIGHT_API_TOKEN":
        assert holders == {owner}, holders


def test_ntfy_credentials_stay_with_ntfy(services: dict[str, dict]) -> None:
    for name, service in services.items():
        files = [entry["path"] for entry in service.get("env_file", [])]
        assert ("./ntfy.env" in files) == (name == "ntfy"), name
        assert ("./hindsight.env" in files) == (name == "hindsight"), name


def test_every_service_that_runs_our_code_or_data_has_resource_limits(
    services: dict[str, dict],
) -> None:
    for name in LIMITED:
        memory = _default(services[name]["mem_limit"], "_MEM_LIMIT")
        pids = _default(services[name]["pids_limit"], "_PIDS_LIMIT")
        assert re.fullmatch(r"\d+[mg]", memory), (name, memory)
        assert int(pids) >= 64, (name, pids)


def test_backup_and_api_memory_fits_a_maximum_size_backup(services: dict[str, dict]) -> None:
    # api runs the snapshot encryption and the backup import for update.sh and restore.sh.
    for name in ("backup", "api"):
        memory = _default(services[name]["mem_limit"], "_MEM_LIMIT")
        assert int(memory[:-1]) * UNITS[memory[-1]] >= BACKUP_FLOOR_BYTES, name


def test_the_limits_are_documented_in_the_env_example_and_never_as_sidekick_names(
    services: dict[str, dict],
) -> None:
    text = (SELFHOST / "selfhost.env.example").read_text(encoding="utf-8")
    for name in LIMITED:
        for field in ("mem_limit", "pids_limit"):
            variable = re.search(r"\$\{(SELFHOST_[A-Z_]+):-", str(services[name][field]))
            assert variable, (name, field)
            assert re.search(rf"^#{variable.group(1)}=", text, re.MULTILINE), variable.group(1)
    # selfhost.env is api's env_file: an undeclared SIDEKICK_ name there would stop the api.
    for line in text.splitlines():
        name = line.lstrip("# ").split("=", 1)[0]
        if name.startswith("SIDEKICK_") and "=" in line:
            assert name in DECLARED, name


# --- the settings each worker's code path reads must be in its environment list ---------------

# Properties of Settings and the fields they are computed from.
PROPERTY_FIELDS = {
    "cursor_signing_key": {"cursor_signing_secret"},
    "database_timeouts": {
        "db_connect_timeout_seconds",
        "db_statement_timeout_ms",
        "db_lock_timeout_ms",
        "db_idle_in_transaction_timeout_ms",
    },
    "push_allowed_host_set": {"push_allowed_hosts"},
    "owner_zone": {"owner_timezone"},
}
MEMORY_FIELDS = {
    "memory_allow_loopback",
    "memory_enabled",
    "memory_hindsight_api_token",
    "memory_hindsight_base_url",
    "memory_hindsight_max_response_bytes",
    "memory_id_derivation_key",
    "memory_provider",
}
# Per worker: the source files its code path covers, and the `settings.<name>` it reads (static,
# kept by hand). A new `settings.x` in these files makes the first test fail until it is listed
# here and in the compose environment.
WORKER_CODE = {
    "automation-worker": (
        ("automation/**/*.py", "composition.py", "memory/factory.py"),
        MEMORY_FIELDS
        | {
            "cursor_signing_key",
            "database_timeouts",
            "database_url",
            "environment",
            "license_public_key",
            "mcp_app_locale",
            "owner_zone",
            "push_enabled",
            "push_wake_min_interval_seconds",
            "token_pepper",
        },
    ),
    "backup": (
        ("backup/**/*.py",),
        {
            "backup_directory",
            "backup_enabled",
            "backup_encryption_key",
            "backup_interval_seconds",
            "backup_min_keep",
            "backup_retention_count",
            "backup_retention_days",
            "backup_space_margin_pct",
            "database_timeouts",
            "database_url",
            "environment",
        },
    ),
    "push": (
        ("companion/push_*.py",),
        {
            "cursor_signing_key",
            "database_timeouts",
            "database_url",
            "environment",
            "owner_zone",
            "push_allowed_host_set",
            "push_auth_host",
            "push_auth_token",
            "push_due_lead_minutes",
            "push_enabled",
            "push_poll_seconds",
            "push_quiet_end",
            "push_quiet_start",
            "push_summary_time",
            "push_wake_min_interval_seconds",
        },
    ),
    "memory-worker": (
        ("memory/**/*.py",),
        MEMORY_FIELDS
        | {
            "database_timeouts",
            "database_url",
            "environment",
            "memory_backfill_daily_cap",
            "memory_daily_char_cap",
            "memory_daily_retain_cap",
            "memory_ingest_enabled",
            "memory_orphan_sweep_enabled",
            "memory_quiet_seconds",
            "owner_zone",
        },
    ),
}


def _settings_reads(patterns: tuple[str, ...]) -> set[str]:
    """Settings fields or properties read as `settings.<name>` in the given files."""
    known = set(Settings.model_fields) | set(PROPERTY_FIELDS)
    found: set[str] = set()
    for pattern in patterns:
        for path in SOURCE.glob(pattern):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if not isinstance(node, ast.Attribute) or node.attr not in known:
                    continue
                owner = node.value
                name = owner.id if isinstance(owner, ast.Name) else getattr(owner, "attr", "")
                if name in ("settings", "_settings"):
                    found.add(node.attr)
    return found


@pytest.mark.parametrize("worker", WORKER_CODE)
def test_the_settings_a_worker_reads_are_the_listed_ones(worker: str) -> None:
    patterns, listed = WORKER_CODE[worker]
    assert _settings_reads(patterns) == listed, worker


@pytest.mark.parametrize("worker", WORKER_CODE)
def test_every_setting_a_worker_reads_is_in_its_environment(
    services: dict[str, dict], worker: str
) -> None:
    _, listed = WORKER_CODE[worker]
    needed: set[str] = set()
    for field in listed:
        for real in PROPERTY_FIELDS.get(field, {field}):
            needed.add(f"SIDEKICK_{real}".upper())
    # Production validation also needs these in every process that builds Settings.
    needed |= {"SIDEKICK_CURSOR_SIGNING_SECRET", "SIDEKICK_TOKEN_PEPPER", "SIDEKICK_DATABASE_URL"}
    pinned = set(services[worker]["environment"]) - _bare_names(services[worker])
    missing = needed - _bare_names(services[worker]) - pinned
    assert not missing, (worker, sorted(missing))


def test_the_removed_cursor_secret_name_still_reaches_every_worker(
    services: dict[str, dict],
) -> None:
    """Passed on so a stale selfhost.env stops startup with a message instead of being ignored."""

    for name in WORKERS:
        assert "SIDEKICK_SESSION_SECRET" in _bare_names(services[name]), name
