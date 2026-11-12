"""CI keeps one checkout pin, shellcheck covers every script and the policy tests run on their own.

Every workflow directory that exists in this checkout is checked.
"""

import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.policy

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_DIRS = [
    directory
    for directory in (
        ROOT / ".github" / "workflows",
        *ROOT.glob("tools/*/overlay/.github/workflows"),
    )
    if directory.is_dir()
]
CI_FILES = [directory / "ci.yml" for directory in WORKFLOW_DIRS]
CHECKOUT = re.compile(r"uses:\s*actions/checkout@(\S+)\s*(?:#\s*(\S+))?")


def _steps(ci: Path, job: str) -> list[dict[str, object]]:
    return yaml.safe_load(ci.read_text(encoding="utf-8"))["jobs"][job]["steps"]


def test_the_workflow_directories_are_found() -> None:
    assert WORKFLOW_DIRS


def test_every_workflow_pins_the_same_checkout() -> None:
    pins = {
        (match[1], match[2])
        for directory in WORKFLOW_DIRS
        for workflow in directory.glob("*.yml")
        for match in CHECKOUT.finditer(workflow.read_text(encoding="utf-8"))
    }
    assert len(pins) == 1, pins
    (sha, _version), *_ = pins
    assert re.fullmatch(r"[0-9a-f]{40}", sha), "checkout is pinned to a full commit sha"


@pytest.mark.parametrize("ci", CI_FILES, ids=lambda path: str(path.relative_to(ROOT)))
def test_shellcheck_covers_every_tracked_shell_script(ci: Path) -> None:
    script = "\n".join(str(step.get("run", "")) for step in _steps(ci, "shellcheck"))
    assert "git ls-files" in script, "the file list comes from git, not from a hand-kept list"
    assert "*.sh" in script, "files with the .sh extension are covered"
    assert "#!" in script, "extensionless scripts are found by their shebang"
    assert "shellcheck --severity=warning" in script


@pytest.mark.parametrize("ci", CI_FILES, ids=lambda path: str(path.relative_to(ROOT)))
def test_the_policy_tests_run_as_their_own_step_and_not_in_the_main_run(ci: Path) -> None:
    runs = [str(step.get("run", "")) for step in _steps(ci, "backend")]
    pytest_runs = [run for run in runs if "uv run pytest" in run]
    main = [run for run in pytest_runs if "--cov-fail-under" in run]
    policy = [run for run in pytest_runs if run.strip().endswith("-m policy")]
    performance = [run for run in pytest_runs if run.strip().endswith("-m performance")]
    assert len(main) == 1 and '-m "not policy and not performance"' in main[0]
    assert len(policy) == 1
    # Wall-clock bounds run serially on their own, so parallel workers cannot inflate them.
    assert len(performance) == 1 and "-n " not in performance[0]


# Files the policy tests read. The backend job runs only when its path filter matches, so a change
# to any of these must also start the job, or a broken doc or config is merged unchecked.
POLICY_INPUTS = [
    "docs/**",
    "deploy/**",
    "tools/**",
    "**/*.md",
    ".env.example",
    ".dockerignore",
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/android/**",
    ".github/**",
]


def _backend_filter(ci: Path) -> list[str]:
    steps = yaml.safe_load(ci.read_text(encoding="utf-8"))["jobs"]["changes"]["steps"]
    (filter_step,) = [step for step in steps if step.get("id") == "filter"]
    filters = yaml.safe_load(filter_step["with"]["filters"])
    return list(filters["backend"])


@pytest.mark.parametrize("ci", CI_FILES, ids=lambda path: str(path.relative_to(ROOT)))
def test_the_backend_filter_covers_the_inputs_of_the_policy_tests(ci: Path) -> None:
    patterns = set(_backend_filter(ci))
    missing = [pattern for pattern in POLICY_INPUTS if pattern not in patterns]
    assert not missing, f"the backend job would skip changes to: {missing}"
