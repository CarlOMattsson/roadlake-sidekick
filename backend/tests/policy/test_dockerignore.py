"""The Docker build context must leave out operational data and secrets (no database needed)."""

from pathlib import Path

import pytest

pytestmark = pytest.mark.policy

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCKERIGNORE = REPO_ROOT / ".dockerignore"

REQUIRED_EXCLUDES = (
    "deploy/work/secrets",
    "deploy/work/backups",
    "deploy/work/work.env",
    "deploy/work/*.log",
    "deploy/selfhost/secrets",
    "deploy/selfhost/backups",
    "deploy/selfhost/ntfy-secrets",
    "**/.env",
    "**/.env.*",
    "**/*.env",
    "**/*.pem",
    "**/*.key",
    "**/node_modules",
    "**/.venv",
    "**/__pycache__",
)
REQUIRED_REINCLUDES = ("!**/.env.example", "!**/*.env.example")


def _patterns() -> list[str]:
    # The file is required (and exported): a checkout without it fails here instead of skipping.
    assert DOCKERIGNORE.is_file(), ".dockerignore is missing from the repository root"
    lines = (line.strip() for line in DOCKERIGNORE.read_text(encoding="utf-8").splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def test_dockerignore_exists() -> None:
    assert DOCKERIGNORE.is_file()


@pytest.mark.parametrize("pattern", REQUIRED_EXCLUDES)
def test_dockerignore_excludes_operational_data_and_secrets(pattern: str) -> None:
    assert pattern in _patterns()


def test_dockerignore_reincludes_example_templates_after_the_env_excludes() -> None:
    patterns = _patterns()
    for reinclude in REQUIRED_REINCLUDES:
        assert reinclude in patterns
        assert patterns.index(reinclude) > patterns.index("**/*.env")


def test_dockerignore_keeps_what_the_image_builds_need() -> None:
    patterns = set(_patterns())
    needed = ("backend", "backend/src", "migrations", "contracts", "frontend", "deploy")
    assert not patterns & set(needed)
