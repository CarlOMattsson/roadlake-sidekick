"""Self-hosted compose: each service gets only the secrets it reads, and has resource limits."""

import ast
import re
from pathlib import Path

import pytest
import yaml

from sidekick.shared.config import Settings, is_secret_field
from sidekick.shared.config.ai_check import AiCheckSettings
from sidekick.shared.config.ai_runner import AiRunnerSettings
from sidekick.shared.config.ai_steps import AiStepSettings

SELFHOST = Path(__file__).resolve().parents[3] / "deploy" / "selfhost"
SOURCE = Path(__file__).resolve().parents[2] / "src" / "sidekick"
WORKERS = ("automation-worker", "backup", "push", "memory-worker")
# The AI worker follows the rules of the workers above, plus its own (a key file, its own network).
AI_WORKER = "ai-worker"
EVERY_WORKER = (*WORKERS, AI_WORKER)
LIMITED = ("postgres", "migrate", "api", *EVERY_WORKER, "hindsight", "tailscale")
DECLARED = {f"SIDEKICK_{name}".upper() for name in Settings.model_fields}
SECRET_FIELDS = {name for name, field in Settings.model_fields.items() if is_secret_field(field)}
# Secrets that no Sidekick setting reads: another product's service holds them (the Tailscale key).
COMPOSE_ONLY_SECRETS = {"tailscale_authkey": "tailscale"}
# The owner's Anthropic key and the key of the check model are Sidekick settings that only the AI
# worker may hold.
AI_KEY = "ai_anthropic_api_key"
AI_KEY_VARIABLE = "SIDEKICK_AI_ANTHROPIC_API_KEY"
CHECK_KEY = "ai_check_api_key"
CHECK_KEY_VARIABLE = "SIDEKICK_AI_CHECK_API_KEY"
COMMON_SECRETS = {"database_url", "cursor_signing_secret", "token_pepper"}
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
    for name in EVERY_WORKER:
        assert "env_file" not in services[name], name
    assert services["api"]["env_file"] == [{"path": "./selfhost.env", "required": False}]
    for name in ("postgres", "migrate"):
        assert services[name]["env_file"] == [{"path": "./db.env", "required": False}], name
    assert "env_file" not in services["backup"]


def test_every_passed_name_is_a_declared_setting(services: dict[str, dict]) -> None:
    for name in EVERY_WORKER:
        names = _bare_names(services[name])
        assert names, name
        unknown = names - DECLARED
        assert not unknown, (name, sorted(unknown))


def test_every_worker_gets_what_production_requires_to_start(services: dict[str, dict]) -> None:
    required = {
        "SIDEKICK_DATABASE_URL",
        "SIDEKICK_CURSOR_SIGNING_SECRET",
        "SIDEKICK_TOKEN_PEPPER",
    }
    for name in EVERY_WORKER:
        assert services[name]["environment"]["SIDEKICK_ENVIRONMENT"] == "production", name
        assert required <= _bare_names(services[name]), name


def test_no_worker_holds_the_oauth_settings(services: dict[str, dict]) -> None:
    for name in EVERY_WORKER:
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


# --- secrets as files: the same scoping as the plain variables, opt-in per secret ---


def _file_names(service: dict) -> set[str]:
    """The secret settings a service is given as `SIDEKICK_<NAME>_FILE`."""
    return {
        field
        for field in SECRET_FIELDS
        if f"SIDEKICK_{field.upper()}_FILE" in service.get("environment", {})
    }


def _mounted(service: dict) -> set[str]:
    return set(service.get("secrets", []))


def test_the_top_level_secrets_are_the_secret_settings_and_default_to_dev_null() -> None:
    compose = yaml.safe_load((SELFHOST / "compose.yaml").read_text(encoding="utf-8"))
    assert set(compose["secrets"]) == SECRET_FIELDS | set(COMPOSE_ONLY_SECRETS)
    for field, definition in compose["secrets"].items():
        assert definition == {"file": f"${{SELFHOST_{field.upper()}_FILE:-/dev/null}}"}, field


def test_a_secret_file_variable_is_passed_only_when_the_operator_opted_in(
    services: dict[str, dict],
) -> None:
    for name, service in services.items():
        for field in _file_names(service):
            value = service["environment"][f"SIDEKICK_{field.upper()}_FILE"]
            assert value == f"${{SELFHOST_{field.upper()}_FILE:+/run/secrets/{field}}}", (
                name,
                field,
            )


@pytest.mark.parametrize("worker", WORKERS)
def test_a_worker_gets_the_file_of_exactly_the_secrets_it_gets_as_variables(
    services: dict[str, dict], worker: str
) -> None:
    service = services[worker]
    held = {field for field in SECRET_FIELDS if f"SIDEKICK_{field.upper()}" in _bare_names(service)}
    assert held, worker
    assert _file_names(service) == held, worker
    assert _mounted(service) == held, worker


def test_api_gets_every_secret_as_a_file_except_the_ai_keys(services: dict[str, dict]) -> None:
    assert _file_names(services["api"]) == SECRET_FIELDS - {AI_KEY, CHECK_KEY}
    assert _mounted(services["api"]) == SECRET_FIELDS - {AI_KEY, CHECK_KEY}


def test_no_other_service_mounts_a_secret(services: dict[str, dict]) -> None:
    for name, service in services.items():
        if name not in ("api", *EVERY_WORKER):
            assert set(service.get("secrets", [])) == {
                secret for secret, owner in COMPOSE_ONLY_SECRETS.items() if owner == name
            }, name
            assert not _file_names(service), name


def test_a_compose_only_secret_reaches_only_its_service_and_never_the_api(
    services: dict[str, dict],
) -> None:
    for secret, owner in COMPOSE_ONLY_SECRETS.items():
        holders = {n for n, service in services.items() if secret in service.get("secrets", [])}
        assert holders == {owner}, secret


# --- the AI worker: the owner's Anthropic key reaches it alone, and it alone has a route out ---


def test_the_anthropic_key_is_a_secret_setting_and_reaches_only_the_ai_worker(
    services: dict[str, dict],
) -> None:
    assert AI_KEY in SECRET_FIELDS
    holders = {name for name, service in services.items() if AI_KEY in service.get("secrets", [])}
    assert holders == {AI_WORKER}
    for name, service in services.items():
        environment = service.get("environment", {})
        assert (f"{AI_KEY_VARIABLE}_FILE" in environment) == (name == AI_WORKER), name
        # Only as a file: a plain value would also reach api through selfhost.env, which refuses it.
        assert AI_KEY_VARIABLE not in environment, name
    assert services[AI_WORKER]["environment"][f"{AI_KEY_VARIABLE}_FILE"] == (
        f"${{SELFHOST_{AI_KEY.upper()}_FILE:+/run/secrets/{AI_KEY}}}"
    )


def test_the_check_key_is_a_secret_setting_and_reaches_only_the_ai_worker(
    services: dict[str, dict],
) -> None:
    assert CHECK_KEY in SECRET_FIELDS
    holders = {
        name for name, service in services.items() if CHECK_KEY in service.get("secrets", [])
    }
    assert holders == {AI_WORKER}
    for name, service in services.items():
        environment = service.get("environment", {})
        assert (f"{CHECK_KEY_VARIABLE}_FILE" in environment) == (name == AI_WORKER), name
        # Only as a file: a plain value would also reach api through selfhost.env, which refuses it.
        assert CHECK_KEY_VARIABLE not in environment, name
    assert services[AI_WORKER]["environment"][f"{CHECK_KEY_VARIABLE}_FILE"] == (
        f"${{SELFHOST_{CHECK_KEY.upper()}_FILE:+/run/secrets/{CHECK_KEY}}}"
    )


def test_the_ai_worker_gets_the_common_secrets_and_the_keys_and_no_other_secret(
    services: dict[str, dict],
) -> None:
    service = services[AI_WORKER]
    assert _file_names(service) == COMMON_SECRETS | {AI_KEY, CHECK_KEY}
    assert _mounted(service) == COMMON_SECRETS | {AI_KEY, CHECK_KEY}
    secret_variables = {f"SIDEKICK_{field}".upper() for field in SECRET_FIELDS}
    common = {f"SIDEKICK_{field}".upper() for field in COMMON_SECRETS}
    assert _bare_names(service) & secret_variables == common


def test_only_the_ai_worker_sets_anthropic_variables_and_nobody_sets_custom_headers(
    services: dict[str, dict],
) -> None:
    # The Anthropic SDK reads ANTHROPIC_* names from the environment (ANTHROPIC_CUSTOM_HEADERS
    # adds a header to every request), so nothing but the telemetry switch is ever set.
    for name, service in services.items():
        anthropic = {v for v in service.get("environment", {}) if v.startswith("ANTHROPIC_")}
        assert anthropic == ({"ANTHROPIC_OPEN_TELEMETRY"} if name == AI_WORKER else set()), name
    assert services[AI_WORKER]["environment"]["ANTHROPIC_OPEN_TELEMETRY"] == "false"
    text = (SELFHOST / "compose.yaml").read_text(encoding="utf-8")
    assert "ANTHROPIC_CUSTOM_HEADERS" not in text
    # The SDK's own key name must not be set; the key is only a Sidekick setting, read from a file.
    assert not re.search(r"(?<![A-Z_])ANTHROPIC_API_KEY", text)


def test_the_ai_worker_is_an_opt_in_profile_with_the_worker_hardening(
    services: dict[str, dict],
) -> None:
    service = services[AI_WORKER]
    assert service["profiles"] == ["ai"]
    assert service["command"] == ["sidekick-ai-worker"]
    assert service["image"] == services["api"]["image"]
    assert service["read_only"] is True and service["tmpfs"] == ["/tmp"]  # noqa: S108
    assert service["cap_drop"] == ["ALL"] and "cap_add" not in service
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert service["restart"] == "unless-stopped"
    assert "ports" not in service and "volumes" not in service and "privileged" not in service
    # A model call that is under way must be allowed to finish before Docker kills the container.
    assert service["stop_grace_period"] == "6m"
    assert _default(service["mem_limit"], "_MEM_LIMIT") == "512m"
    assert _default(service["pids_limit"], "_PIDS_LIMIT") == "64"
    assert service["depends_on"]["migrate"] == {"condition": "service_completed_successfully"}


def test_only_the_ai_worker_joins_the_ai_network_and_it_is_on_no_other_route_out(
    services: dict[str, dict],
) -> None:
    compose = yaml.safe_load((SELFHOST / "compose.yaml").read_text(encoding="utf-8"))
    assert set(services[AI_WORKER]["networks"]) == {"data", "ai"}
    assert {n for n, s in services.items() if "ai" in (s.get("networks") or [])} == {AI_WORKER}
    for network in ("edge", "proxy", "push"):
        assert network not in services[AI_WORKER]["networks"], network
    # The one network with an internet route (not internal, no fixed addresses); `data` has none.
    assert compose["networks"]["ai"] in (None, {})
    assert compose["networks"]["data"] == {"internal": True}


def test_the_ai_worker_is_passed_every_non_secret_ai_setting_it_reads(
    services: dict[str, dict],
) -> None:
    # The Claude Code start limit is api's alone; every other AI setting is the worker's.
    fields = (
        set(AiRunnerSettings.model_fields)
        | set(AiStepSettings.model_fields)
        | set(AiCheckSettings.model_fields)
    ) - {
        AI_KEY,
        CHECK_KEY,
        "environment",
        "ai_claude_code_starts_per_day",
        # Production refuses a loopback address, and the worker always runs in production.
        "ai_check_allow_loopback",
    }
    expected = {f"SIDEKICK_{field}".upper() for field in fields}
    assert expected <= _bare_names(services[AI_WORKER])
    assert "SIDEKICK_AI_CLAUDE_CODE_STARTS_PER_DAY" not in _bare_names(services[AI_WORKER])


def test_the_ai_settings_are_off_in_the_env_example_and_it_never_carries_a_key_value() -> None:
    text = (SELFHOST / "selfhost.env.example").read_text(encoding="utf-8")
    lines = [line.strip() for line in text.splitlines()]
    # Every SIDEKICK_AI_* line is commented out: nothing is on until the owner opts in.
    assert not [line for line in lines if line.startswith("SIDEKICK_AI_")]
    assert "# SIDEKICK_AI_RUNNER_ENABLED=false" in lines
    assert "#SELFHOST_AI_ANTHROPIC_API_KEY_FILE=./secrets/ai_anthropic_api_key" in lines
    assert not [line for line in lines if re.match(r"#? ?SIDEKICK_AI_ANTHROPIC_API_KEY=", line)]
    assert "sk-ant-" not in text
    assert "#SELFHOST_AI_CHECK_API_KEY_FILE=./secrets/ai_check_api_key" in lines
    assert not [line for line in lines if re.match(r"#? ?SIDEKICK_AI_CHECK_API_KEY=", line)]


def test_the_env_example_documents_a_file_line_for_every_secret_setting() -> None:
    text = (SELFHOST / "selfhost.env.example").read_text(encoding="utf-8")
    for field in SECRET_FIELDS:
        assert f"\n#SELFHOST_{field.upper()}_FILE=./secrets/{field}\n" in text, field


def test_the_migration_script_moves_exactly_the_secret_settings() -> None:
    text = (SELFHOST / "secrets-to-files.sh").read_text(encoding="utf-8")
    block = text.split('secrets="', 1)[1].split('"', 1)[0]
    pairs = dict(line.split(":") for line in block.split())
    assert pairs == {f"SIDEKICK_{field.upper()}": field for field in SECRET_FIELDS}


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
        ("work/worker.py", "composition.py", "memory/factory.py"),
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
