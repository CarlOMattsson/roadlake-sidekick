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


@pytest.mark.parametrize("ci", CI_FILES, ids=lambda path: str(path.relative_to(ROOT)))
def test_ci_runs_only_as_a_release_gate_or_on_demand(ci: Path) -> None:
    """CI is a release gate: no runs on pull requests, merge queues or pushes."""

    workflow = yaml.safe_load(ci.read_text(encoding="utf-8"))
    assert set(workflow[True]) == {"workflow_dispatch", "workflow_call"}
    assert "changes" not in workflow["jobs"], "there is no change filter without pull requests"
    text = ci.read_text(encoding="utf-8")
    assert "github.event_name" not in text and "paths-filter" not in text


# The CI of the public copy is a second file that must stay the same workflow as this one.
# Only these differences are intended: each concerns a file that the public copy does not
# contain (tests/ops and the production Compose files are the maintainer's own deployment tooling).
SOURCE_ONLY_JOBS = {"compose-smoke"}
SOURCE_ONLY_RUN_FLAGS = (" --ignore=tests/ops",)
SOURCE_CI = ROOT / ".github" / "workflows" / "ci.yml"
OVERLAY_CI = ROOT / "tools" / "export" / "overlay" / ".github" / "workflows" / "ci.yml"


def _normalized_source_run(run: str) -> str:
    for flag in SOURCE_ONLY_RUN_FLAGS:
        run = run.replace(flag, "")
    return run


def _normalized_source_job(job: object) -> object:
    assert isinstance(job, dict)
    steps = [
        {
            key: _normalized_source_run(value) if key == "run" else value
            for key, value in step.items()
        }
        for step in job.get("steps", [])
    ]
    return {**job, **({"steps": steps} if "steps" in job else {})}


@pytest.mark.skipif(
    not (SOURCE_CI.is_file() and OVERLAY_CI.is_file()),
    reason="the overlay exists only in the working repository",
)
def test_the_published_ci_differs_from_the_source_ci_only_in_the_listed_ways() -> None:
    source = yaml.safe_load(SOURCE_CI.read_text(encoding="utf-8"))
    overlay = yaml.safe_load(OVERLAY_CI.read_text(encoding="utf-8"))
    assert {key: value for key, value in source.items() if key != "jobs"} == {
        key: value for key, value in overlay.items() if key != "jobs"
    }, "the workflow name, triggers, permissions and env must match"
    assert set(source["jobs"]) - set(overlay["jobs"]) == SOURCE_ONLY_JOBS
    assert set(overlay["jobs"]) <= set(source["jobs"]), "the published CI has no jobs of its own"
    for name, job in overlay["jobs"].items():
        assert _normalized_source_job(source["jobs"][name]) == job, (
            f"job {name} drifted between source and overlay"
        )
