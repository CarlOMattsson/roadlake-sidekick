"""The Scorecard workflow publishes its result under the restrictions of the official action.

The Scorecard API rejects a publishing workflow that has workflow-level write permissions,
environment variables, run steps or actions outside a short list, and the action refuses any ref but
the default branch, so the workflow runs by hand from main only.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.policy

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "scorecard.yml"
ALLOWED_ACTIONS = (
    "actions/checkout@",
    "actions/upload-artifact@",
    "github/codeql-action/upload-sarif@",
    "ossf/scorecard-action@",
    "step-security/harden-runner@",
)


def load() -> dict[Any, Any]:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_it_runs_by_hand_only() -> None:
    """No push, schedule or release trigger: a release runs on a tag, which the action refuses."""

    assert set(load()[True]) == {"workflow_dispatch"}


def test_it_publishes_and_follows_the_restrictions_for_publishing() -> None:
    workflow = load()
    assert not workflow["permissions"], "no workflow-level permission, least of all a write"
    assert "env" not in workflow and "defaults" not in workflow
    (job,) = workflow["jobs"].values()
    assert "env" not in job and "defaults" not in job
    assert "container" not in job and "services" not in job
    assert job["permissions"]["id-token"] == "write"
    steps = job["steps"]
    assert not [step for step in steps if "run" in step], "a publishing job may not run shell steps"
    assert all(step["uses"].startswith(ALLOWED_ACTIONS) for step in steps)
    (analysis,) = [step for step in steps if step["uses"].startswith("ossf/scorecard-action@")]
    assert analysis["with"]["publish_results"] is True
