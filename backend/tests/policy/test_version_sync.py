"""One release version: backend/pyproject.toml is the source and every other copy must match it."""

import importlib.util
import json
import re
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

import sidekick

pytestmark = pytest.mark.policy

REPO = Path(__file__).resolve().parents[3]
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def source_version() -> str:
    with (REPO / "backend" / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"]["version"]


def android_version_code(version: str) -> int:
    """The derivation in frontend/android/app/build.gradle."""
    match = SEMVER.match(version)
    assert match is not None
    major, minor, patch = (int(part) for part in match.groups())
    assert minor < 100 and patch < 100
    return major * 10000 + minor * 100 + patch


def test_source_version_is_plain_semver_that_fits_the_android_version_code() -> None:
    version = source_version()
    assert SEMVER.match(version), (
        f"backend/pyproject.toml version {version!r} is not MAJOR.MINOR.PATCH"
    )
    assert 1 <= android_version_code(version) <= 2_100_000_000


def test_package_version_matches_the_source() -> None:
    assert sidekick.__version__ == source_version()


def test_frontend_package_and_lockfile_match_the_source() -> None:
    package = json.loads((REPO / "frontend" / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((REPO / "frontend" / "package-lock.json").read_text(encoding="utf-8"))
    version = source_version()
    assert package["version"] == version
    assert lock["version"] == version
    assert lock["packages"][""]["version"] == version


def test_android_reads_its_version_from_the_frontend_package() -> None:
    gradle = (REPO / "frontend" / "android" / "app" / "build.gradle").read_text(encoding="utf-8")
    assert "rootProject.file('../package.json')" in gradle
    assert re.search(r"^\s*versionName sidekickVersion$", gradle, re.MULTILINE)
    assert re.search(r"^\s*versionCode sidekickVersionCode$", gradle, re.MULTILINE)
    assert "sidekickMajor * 10000 + sidekickMinor * 100 + sidekickPatch" in gradle


def test_android_version_code_grows_with_every_bump() -> None:
    ordered = [
        "0.1.0",
        "0.1.1",
        "0.1.99",
        "0.2.0",
        "0.99.99",
        "1.0.0",
        "1.0.1",
        "2.0.0",
    ]
    codes = [android_version_code(version) for version in ordered]
    assert codes == sorted(codes) and len(set(codes)) == len(codes)


# tools/check-version-sync.py: the same rules as a script the release workflow runs.

TOOL = REPO / "tools" / "check-version-sync.py"
# The changelog is CHANGELOG.md at the repository root (or a copy kept under tools/); without one
# there is nothing to compare.
PUBLISHED_CHANGELOGS = [
    path for path in (REPO / "CHANGELOG.md", *REPO.glob("tools/*/*/CHANGELOG.md")) if path.exists()
]


def load_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_version_sync", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def copy_version_files(target: Path) -> Path:
    """A minimal tree with just the files the script reads, so a test can break one of them."""

    for relative in (
        "backend/pyproject.toml",
        "backend/src/sidekick/__init__.py",
        "frontend/package.json",
        "frontend/package-lock.json",
        "frontend/android/app/build.gradle",
        "backend/src/sidekick/mcp/server.py",
        "frontend/src/features/mcp-apps/sidekick-entry.tsx",
        "frontend/src/features/mcp-apps/app-version.ts",
    ):
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text((REPO / relative).read_text(encoding="utf-8"), encoding="utf-8")
    return target


@pytest.mark.skipif(not PUBLISHED_CHANGELOGS, reason="this checkout has no changelog")
def test_the_repository_is_in_sync_with_the_published_changelog() -> None:
    assert load_tool().main(["--changelog", str(PUBLISHED_CHANGELOGS[0])]) == 0


def test_the_script_names_every_copy_that_drifted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = copy_version_files(tmp_path)
    init = root / "backend/src/sidekick/__init__.py"
    init.write_text(init.read_text(encoding="utf-8").replace("0.1.0", "0.1.1"), encoding="utf-8")
    package = root / "frontend/package.json"
    package.write_text(
        package.read_text(encoding="utf-8").replace("0.1.0", "0.2.0", 1),
        encoding="utf-8",
    )
    assert load_tool().main(["--root", str(root)]) == 1
    error = capsys.readouterr().err
    assert "__init__.py" in error and "frontend/package.json" in error
    assert "package-lock" not in error


def test_the_android_version_must_stay_derived(tmp_path: Path) -> None:
    root = copy_version_files(tmp_path)
    gradle = root / "frontend/android/app/build.gradle"
    gradle.write_text(
        gradle.read_text(encoding="utf-8").replace(
            "versionName sidekickVersion", 'versionName "9"'
        ),
        encoding="utf-8",
    )
    assert load_tool().main(["--root", str(root)]) == 1


def test_the_handshake_versions_must_stay_derived(tmp_path: Path) -> None:
    root = copy_version_files(tmp_path)
    tool = load_tool()
    assert tool.main(["--root", str(root)]) == 0
    server = root / "backend/src/sidekick/mcp/server.py"
    server.write_text(
        server.read_text(encoding="utf-8").replace("version=__version__,", 'version="0.1.0",'),
        encoding="utf-8",
    )
    assert tool.main(["--root", str(root)]) == 1
    root = copy_version_files(tmp_path / "second")
    entry = root / "frontend/src/features/mcp-apps/sidekick-entry.tsx"
    entry.write_text(
        entry.read_text(encoding="utf-8").replace("version: APP_VERSION", 'version: "1.0.0"'),
        encoding="utf-8",
    )
    assert tool.main(["--root", str(root)]) == 1


def test_the_tag_must_match_the_source_version(tmp_path: Path) -> None:
    root = copy_version_files(tmp_path)
    tool = load_tool()
    assert tool.main(["--root", str(root), "--tag", "v0.1.0"]) == 0
    assert tool.main(["--root", str(root), "--tag", "v0.1.1"]) == 1


def test_changelog_rules_before_and_on_the_release_day(tmp_path: Path) -> None:
    root = copy_version_files(tmp_path)
    tool = load_tool()
    changelog = tmp_path / "CHANGELOG.md"
    base = ["--root", str(root), "--changelog", str(changelog)]

    changelog.write_text(
        "# Changelog\n\n## [Unreleased]\n\nPlanned as 0.1.0.\n\n- A thing.\n",
        encoding="utf-8",
    )
    assert tool.main(base) == 0
    assert tool.main([*base, "--release"]) == 1  # not dated yet

    changelog.write_text("# Changelog\n\n## [Unreleased]\n\nNothing named.\n", encoding="utf-8")
    assert tool.main(base) == 1  # [Unreleased] does not name the version

    changelog.write_text(
        "# Changelog\n\n## [Unreleased]\n\n"
        "## [0.1.0] - 2026-11-12\n\n- First release.\n\n"
        "## [0.0.9] - 2026-01-01\n\n- Old.\n",
        encoding="utf-8",
    )
    notes = tmp_path / "notes.md"
    assert tool.main([*base, "--release", "--notes", str(notes)]) == 0
    assert notes.read_text(encoding="utf-8") == "- First release.\n"

    changelog.write_text("# Changelog\n\n## [0.1.0]\n\n- No date.\n", encoding="utf-8")
    assert tool.main(base) == 1


def test_a_missing_file_is_a_usage_error(tmp_path: Path) -> None:
    assert load_tool().main(["--root", str(tmp_path)]) == 2
    root = copy_version_files(tmp_path / "tree")
    assert (
        load_tool().main(["--root", str(root), "--release"]) == 1
    )  # no CHANGELOG.md to release from
