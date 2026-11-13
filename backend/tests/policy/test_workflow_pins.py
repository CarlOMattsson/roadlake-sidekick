"""The workflows pin remote actions, never inherit secrets and keep the signing secrets in two jobs.

Every workflow directory that exists in this checkout is checked, the published copies under the
export overlay included.
"""

import json
import re
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
SIGNING_SECRETS = (
    "ANDROID_KEYSTORE_BASE64",
    "ANDROID_KEYSTORE_PASSWORD",
    "ANDROID_KEY_ALIAS",
    "ANDROID_KEY_PASSWORD",
)
# The only jobs that read the signing secrets: the presence check and the one that signs the APK.
SIGNING_SECRET_JOBS = {"secrets-check", "sign-apk"}
PINNED = re.compile(r"[\w./-]+@[0-9a-f]{40}")


def label(path: Path) -> str:
    return str(path.relative_to(ROOT))


def load(path: Path) -> dict[Any, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def references(job: dict[str, Any]) -> list[str]:
    """Every `uses:` of a job: the reusable workflow it calls and the actions of its steps."""

    return [item["uses"] for item in (job, *job.get("steps", [])) if "uses" in item]


def test_the_workflows_are_found() -> None:
    assert WORKFLOWS


@pytest.mark.parametrize("path", WORKFLOWS, ids=label)
def test_every_remote_action_is_pinned_to_a_full_commit_and_local_ones_exist(path: Path) -> None:
    for job in load(path)["jobs"].values():
        for reference in references(job):
            if reference.startswith("./"):
                assert (ROOT / reference).exists(), (label(path), reference)
            else:
                assert PINNED.fullmatch(reference), (label(path), reference)


@pytest.mark.parametrize("path", WORKFLOWS, ids=label)
def test_no_workflow_hands_over_all_its_secrets(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert "secrets: inherit" not in text and "secrets:inherit" not in text, label(path)
    for name, job in load(path)["jobs"].items():
        if "uses" in job:
            # No called workflow takes a secret; adding one is a deliberate change, never `inherit`.
            assert "secrets" not in job, (
                f"{label(path)}: job {name} passes secrets to {job['uses']}"
            )


@pytest.mark.parametrize("path", WORKFLOWS, ids=label)
def test_a_job_that_signs_pushes_or_sits_in_an_environment_runs_no_local_action(
    path: Path,
) -> None:
    """A privileged job writes its steps out: no local action and no reusable workflow."""

    for name, job in load(path)["jobs"].items():
        granted = job.get("permissions") or {}
        privileged = (
            "environment" in job
            or "id-token" in granted
            or any(value == "write" for value in granted.values())
        )
        if privileged:
            local = [use for use in references(job) if use.startswith("./")]
            assert not local, f"{label(path)}: privileged job {name} uses {local}"


@pytest.mark.parametrize("path", WORKFLOWS, ids=label)
def test_the_signing_secrets_are_read_only_by_the_two_signing_environment_jobs(
    path: Path,
) -> None:
    document = load(path)
    holders = {
        name
        for name, job in document["jobs"].items()
        if any(secret in yaml.safe_dump(job) for secret in SIGNING_SECRETS)
    }
    if path.name == "release-image.yml":
        assert holders == SIGNING_SECRET_JOBS, label(path)
        for name in SIGNING_SECRET_JOBS:
            assert document["jobs"][name]["environment"] == "release-signing", name
    else:
        assert not holders, label(path)


@pytest.mark.parametrize("path", WORKFLOWS, ids=label)
def test_setup_node_reads_the_node_version_from_one_file(path: Path) -> None:
    for job in load(path)["jobs"].values():
        for step in job.get("steps", []):
            if step.get("uses", "").startswith("actions/setup-node@"):
                assert "node-version" not in step["with"], "no version written into the workflow"
                assert step["with"]["node-version-file"] in (
                    ".node-version",
                    "website/.node-version",
                )


def test_the_node_version_of_the_root_the_website_and_the_frontend_agree() -> None:
    pinned = (ROOT / ".node-version").read_text(encoding="utf-8")
    assert re.fullmatch(r"\d+\.\d+\.\d+\n", pinned)
    version = pinned.strip()
    assert (ROOT / "website" / ".node-version").read_text(encoding="utf-8").strip() == version
    for project in ("frontend", "website"):
        manifest = json.loads((ROOT / project / "package.json").read_text(encoding="utf-8"))
        assert manifest["engines"]["node"] == f">={version}", project
        lock = json.loads((ROOT / project / "package-lock.json").read_text(encoding="utf-8"))
        assert lock["packages"][""]["engines"] == manifest["engines"], project
