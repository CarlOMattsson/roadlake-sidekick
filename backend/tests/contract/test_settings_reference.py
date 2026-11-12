"""`docs/reference/configuration.md` is rendered from `Settings`; example env files match it.

Regenerate with:
    uv run --project backend python -m sidekick.shared.export_settings_reference
and verify without writing by adding `--check`.
"""

import re
import subprocess
from pathlib import Path

import pytest

from sidekick.shared import export_settings_reference as reference
from sidekick.shared.config import Settings, declared_variable_names

ROOT = Path(__file__).resolve().parents[3]
REFERENCE_FILE = ROOT / "docs" / "reference" / "configuration.md"

# `SIDEKICK_*` keys that appear in the example env files but are deliberately not `Settings`
# fields. Each is read by something other than the backend settings class.
NOT_SETTINGS_SIDEKICK_KEYS = {
    "SIDEKICK_SEED_LOGIN": "read by `python -m tools.seed` from its own file (.env.seed)",
    "SIDEKICK_SEED_DISPLAY_NAME": "read by `python -m tools.seed` from its own file (.env.seed)",
    "SIDEKICK_DB_APP_PASSWORD": "Compose and postgres-init.sh create the application role",
    "SIDEKICK_DB_MIGRATOR_PASSWORD": "Compose and postgres-init.sh create the migrator role",
    "SIDEKICK_MIGRATION_DATABASE_URL": "the migration runner's own connection, not the app's",
    "SIDEKICK_WORK_MODEL_BASE_URL": "tools/work.sh and deploy/work/compose.yaml",
    "SIDEKICK_WORK_MODEL_RESOLVE_IP": "tools/work.sh and deploy/work/compose.yaml",
    "SIDEKICK_WORK_ALLOW": "tools/work.sh and deploy/work/compose.yaml",
    "SIDEKICK_WORK_MEMORY_MODEL": "tools/work.sh and deploy/work/compose.yaml",
    "SIDEKICK_WORK_EMBEDDINGS_PROVIDER": "tools/work.sh and deploy/work/compose.yaml",
    "SIDEKICK_WORK_EMBEDDINGS_MODEL": "tools/work.sh and deploy/work/compose.yaml",
    "SIDEKICK_WORK_INSTANCE_LABEL": "tools/work.sh and deploy/work/compose.yaml",
    "SIDEKICK_WORK_LOCALE": "tools/work.sh and deploy/work/compose.yaml",
    "SIDEKICK_WORK_TIMEZONE": "tools/work.sh and deploy/work/compose.yaml",
    "SIDEKICK_WORK_PORT": "tools/work.sh and deploy/work/compose.yaml",
    "SIDEKICK_WORK_CA_BUNDLE": "tools/work.sh and deploy/work/compose.yaml",
    "SIDEKICK_WORK_API_IMAGE": "tools/work.sh and deploy/work/compose.yaml",
}
# Keys of other services configured through the same kind of file.
NOT_SIDEKICK_KEY_PATTERN = re.compile(
    r"HINDSIGHT_API_[A-Z0-9_]+"  # the Hindsight server, a separate process
    r"|HINDSIGHT_RUNTIME_ROLE"  # Hindsight migration role
    r"|NTFY_[A-Z0-9_]+|TS_AUTHKEY"  # the ntfy server and its Tailscale sidecar
    r"|POSTGRES_PASSWORD|SELFHOST_DOMAIN"  # the self-host Compose stack
    r"|SELFHOST_[A-Z0-9_]+_(?:MEM|PIDS)_LIMIT"  # its per-service resource limits
)
KEY = re.compile(r"^\s*#?\s*(?:export\s+)?([A-Z][A-Z0-9_]*)=")


def _example_files() -> list[Path]:
    listed = subprocess.run(
        ["git", "ls-files", "*.env.example", ".env*.example"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    return [ROOT / name for name in listed]


def _keys(path: Path) -> set[str]:
    return {
        match.group(1)
        for line in path.read_text(encoding="utf-8").splitlines()
        if (match := KEY.match(line))
    }


def test_committed_configuration_reference_matches_the_generator() -> None:
    assert reference.stale_problems(reference.render(), REFERENCE_FILE) == []


def test_check_mode_fails_on_a_stale_file_and_passes_after_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "configuration.md"
    arguments = ["--output", str(target)]

    monkeypatch.setattr("sys.argv", ["export_settings_reference", *arguments, "--check"])
    assert reference.main() == 1
    assert "missing" in capsys.readouterr().err

    monkeypatch.setattr("sys.argv", ["export_settings_reference", *arguments])
    assert reference.main() == 0
    monkeypatch.setattr("sys.argv", ["export_settings_reference", *arguments, "--check"])
    assert reference.main() == 0
    target.write_text("edited by hand\n", encoding="utf-8")
    assert reference.main() == 1
    assert "out of date" in capsys.readouterr().err


def test_every_setting_is_documented_with_a_description_and_listed_once() -> None:
    page = reference.render()
    for name, field in Settings.model_fields.items():
        assert field.description, f"Settings.{name} lacks Field(description=...)"
        assert page.count(f"| `SIDEKICK_{name.upper()}` |") == 1


def test_the_reference_never_prints_a_secret_default() -> None:
    page = reference.render()
    for name, field in Settings.model_fields.items():
        if isinstance(field.default, str) and field.repr is False and "secret" in name:
            assert field.default not in page


def test_example_env_files_use_only_declared_settings() -> None:
    declared = declared_variable_names()
    undeclared: list[str] = []
    for path in _example_files():
        for key in sorted(_keys(path)):
            if key.startswith("SIDEKICK_"):
                if key not in declared and key not in NOT_SETTINGS_SIDEKICK_KEYS:
                    undeclared.append(f"{path.name}: {key}")
            elif not NOT_SIDEKICK_KEY_PATTERN.fullmatch(key):
                undeclared.append(f"{path.name}: {key}")
    assert undeclared == []


def test_listed_non_settings_keys_are_not_settings_and_still_appear_in_an_example() -> None:
    declared = declared_variable_names()
    present: set[str] = set().union(*(_keys(path) for path in _example_files()))
    for key in NOT_SETTINGS_SIDEKICK_KEYS:
        assert key not in declared, f"{key} is a Settings field now; drop it from the list"
        assert key in present, f"{key} is in no example env file any more; drop it from the list"
