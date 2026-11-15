"""The container images that CI and the local gate (tools/check-all.sh) both run are pinned in one
place.

tools/ci-images.sh holds them by tag and digest. A local run and CI then see the same shellcheck,
actionlint, gitleaks and Playwright browsers and fonts, instead of whatever the runner or the
developer's machine has installed.
"""

import json
import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.policy

ROOT = Path(__file__).resolve().parents[3]
PINS = ROOT / "tools" / "ci-images.sh"
SCRIPTS = (
    "playwright-docker.sh",
    "shellcheck-ci.sh",
    "actionlint-ci.sh",
    "gitleaks-ci.sh",
    "image-scan.sh",
)
WORKFLOWS = [
    path
    for path in (
        ROOT / ".github" / "workflows" / "ci.yml",
        ROOT / "tools" / "export" / "overlay" / ".github" / "workflows" / "ci.yml",
    )
    if path.is_file()
]


def _pins() -> dict[str, str]:
    return dict(re.findall(r'^(\w+_IMAGE)="([^"]+)"$', PINS.read_text(encoding="utf-8"), re.M))


def test_every_image_is_pinned_by_tag_and_digest() -> None:
    pins = _pins()
    assert set(pins) == {
        "PLAYWRIGHT_IMAGE",
        "GITLEAKS_IMAGE",
        "SHELLCHECK_IMAGE",
        "ACTIONLINT_IMAGE",
        "TRIVY_IMAGE",
    }
    for name, reference in pins.items():
        assert re.fullmatch(r"[\w./-]+:v?[\d][\w.-]*@sha256:[0-9a-f]{64}", reference), name


def test_the_playwright_image_carries_the_version_of_the_installed_package() -> None:
    package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    version = package["devDependencies"]["@playwright/test"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), "an exact version, so the browsers match"
    assert f"/playwright:v{version}-" in _pins()["PLAYWRIGHT_IMAGE"]


@pytest.mark.parametrize("script", SCRIPTS)
def test_the_scripts_read_the_pins_and_repeat_none_of_them(script: str) -> None:
    text = (ROOT / "tools" / script).read_text(encoding="utf-8")
    assert '. "$HERE/ci-images.sh"' in text
    assert "sha256:" not in text


IMAGE_WORKFLOWS = [
    path
    for path in (
        ROOT / ".github" / "workflows" / "release-image.yml",
        ROOT / "tools" / "export" / "overlay" / ".github" / "workflows" / "release-image.yml",
    )
    if path.is_file()
]


@pytest.mark.parametrize("workflow", IMAGE_WORKFLOWS, ids=lambda path: str(path.relative_to(ROOT)))
def test_the_local_image_scan_selects_what_the_release_workflow_scans(workflow: Path) -> None:
    """tools/image-scan.sh fails on what the release Trivy step fails on."""

    scan = (ROOT / "tools" / "image-scan.sh").read_text(encoding="utf-8")
    text = workflow.read_text(encoding="utf-8")
    for option in ("severity: HIGH,CRITICAL", "ignore-unfixed: true", "scanners: vuln"):
        assert option in text, option
    for flag in (
        "--severity HIGH,CRITICAL",
        "--ignore-unfixed",
        "--scanners vuln",
        "--exit-code 1",
    ):
        assert flag in scan, flag
    assert "--pkg-types os,library" in scan
    assert "vuln-type: os,library" in text


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda path: str(path.relative_to(ROOT)))
def test_ci_runs_the_browser_tests_secret_scan_shellcheck_and_actionlint_through_the_scripts(
    workflow: Path,
) -> None:
    text = workflow.read_text(encoding="utf-8")
    assert "bash tools/playwright-docker.sh npx playwright test --config playwright.mcp-app" in text
    assert "bash tools/playwright-docker.sh npx playwright test --config playwright.mobile" in text
    assert "bash tools/gitleaks-ci.sh" in text
    assert "bash tools/shellcheck-ci.sh" in text
    assert "bash tools/actionlint-ci.sh" in text
    assert "playwright install" not in text, "the browsers come from the pinned image"
    assert "gitleaks-action" not in text, "the scan runs from the pinned image"


@pytest.mark.parametrize("workflow", IMAGE_WORKFLOWS, ids=lambda path: str(path.relative_to(ROOT)))
def test_the_release_workflow_installs_the_trivy_version_of_the_local_scan(workflow: Path) -> None:
    """Every Trivy step in the release workflow pins `version` to the tag of TRIVY_IMAGE."""

    pinned = re.fullmatch(r"[\w./-]+/trivy:v?([\d.]+)@sha256:[0-9a-f]{64}", _pins()["TRIVY_IMAGE"])
    assert pinned, "TRIVY_IMAGE carries a version tag"
    steps = [
        step
        for job in yaml.safe_load(workflow.read_text(encoding="utf-8"))["jobs"].values()
        for step in job.get("steps", [])
        if "trivy-action" in step.get("uses", "")
    ]
    assert len(steps) == 2, "one scan per image platform"
    for step in steps:
        assert step["with"]["version"] == f"v{pinned.group(1)}"
