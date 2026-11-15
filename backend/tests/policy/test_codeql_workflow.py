"""CodeQL is the only workflow that runs on push and on a schedule, and it stays read-only.

Every other workflow runs by hand or as a release gate. The CodeQL analysis is the one stated
exception, because static analysis should see every commit that lands on main (the OpenSSF Scorecard
SAST check looks for `github/codeql-action/analyze`). The exception must not widen: no other
workflow, the published copies under the export overlay included, gains an automatic trigger.
"""

from pathlib import Path
from typing import Any

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
WORKFLOWS = sorted(path for directory in WORKFLOW_DIRS for path in directory.glob("*.yml"))
CODEQL = ROOT / ".github" / "workflows" / "codeql.yml"
AUTOMATIC_TRIGGERS = {"push", "schedule", "pull_request", "pull_request_target", "merge_group"}
CODEQL_ACTION = "github/codeql-action/"


def label(path: Path) -> str:
    return str(path.relative_to(ROOT))


def load(path: Path) -> dict[Any, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def triggers(path: Path) -> set[str]:
    # PyYAML reads the bare key `on` as the boolean True.
    on = load(path)[True]
    return {on} if isinstance(on, str) else set(on)


@pytest.mark.parametrize("path", WORKFLOWS, ids=label)
def test_only_the_codeql_workflow_runs_on_push_or_on_a_schedule(path: Path) -> None:
    automatic = triggers(path) & AUTOMATIC_TRIGGERS
    if path == CODEQL:
        assert automatic == {"push", "schedule"}, label(path)
    else:
        assert not automatic, f"{label(path)} runs on {sorted(automatic)}"


def test_codeql_runs_on_main_weekly_and_by_hand() -> None:
    workflow = load(CODEQL)
    assert triggers(CODEQL) == {"push", "schedule", "workflow_dispatch"}
    assert workflow[True]["push"] == {"branches": ["main"]}
    (schedule,) = workflow[True]["schedule"]
    *_, day, month, weekday = schedule["cron"].split()
    assert (day, month) == ("*", "*") and weekday != "*", "once a week, not daily"


def test_codeql_is_read_only_and_runs_no_shell() -> None:
    workflow = load(CODEQL)
    assert workflow["permissions"] == {}, "no workflow-level permission"
    assert "env" not in workflow and "secrets." not in CODEQL.read_text(encoding="utf-8")
    (job,) = workflow["jobs"].values()
    assert job["permissions"] == {"contents": "read", "security-events": "write"}
    steps = job["steps"]
    assert not [step for step in steps if "run" in step], "the analysis runs no shell steps"
    (checkout,) = [step for step in steps if step["uses"].startswith("actions/checkout@")]
    assert checkout["with"]["persist-credentials"] is False


def test_codeql_analyses_every_source_language_without_a_build() -> None:
    (job,) = load(CODEQL)["jobs"].values()
    assert job["strategy"]["matrix"]["language"] == ["python", "javascript-typescript", "actions"]
    steps = {step["uses"].split("@")[0]: step for step in job["steps"]}
    init = steps[CODEQL_ACTION + "init"]["with"]
    assert init["build-mode"] == "none"
    assert init["queries"] == "security-extended"
    assert CODEQL_ACTION + "analyze" in steps, "Scorecard detects the analyze action"
    pins = {step["uses"].split("@")[1] for step in job["steps"] if CODEQL_ACTION in step["uses"]}
    assert len(pins) == 1, "init and analyze come from one release"


ALLOWLIST = ROOT / "tools" / "export" / "allowlist.txt"


@pytest.mark.skipif(
    not ALLOWLIST.is_file(), reason="the export lists exist only in the working repository"
)
def test_codeql_is_exported_to_the_public_repository() -> None:
    assert ".github/workflows/codeql.yml" in ALLOWLIST.read_text(encoding="utf-8").splitlines()
