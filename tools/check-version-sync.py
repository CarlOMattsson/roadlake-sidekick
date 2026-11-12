#!/usr/bin/env python3
"""Check that every copy of the release version agrees, and print the release notes for it.

`version` in backend/pyproject.toml is the single source. These must equal it:
backend/src/sidekick/__init__.py, frontend/package.json, frontend/package-lock.json (two places),
the version the MCP server and the MCP App announce in their handshakes (each must be derived from
`sidekick.__version__` and frontend/package.json, never a literal) and the Android build, which reads `versionName` from frontend/package.json and derives
`versionCode` as MAJOR*10000 + MINOR*100 + PATCH (checked structurally in build.gradle).
CHANGELOG.md (present in the published repository) must mention the version: either a
`## [X.Y.Z]` heading or, before the release day, an `## [Unreleased]` section that names it.

Usage:
    tools/check-version-sync.py [--root DIR] [--tag vX.Y.Z] [--release] [--notes FILE]

--tag      the release tag must be v + the source version.
--release  the release day: CHANGELOG.md must hold a dated `## [X.Y.Z] - YYYY-MM-DD` heading, so
           an `[Unreleased]` section is refused. Used by the release workflow, never by CI.
--notes    write the CHANGELOG section of this version (the dated one, else `[Unreleased]`) to FILE.
--changelog PATH  use this changelog instead of ROOT/CHANGELOG.md.

Exit code 0 = all agree, 1 = a mismatch (every one is listed), 2 = a file cannot be read.
Uses only the standard library; no network.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
INIT_VERSION = re.compile(r'^__version__\s*=\s*"([^"]+)"\s*$', re.MULTILINE)
RELEASE_HEADING = re.compile(
    r"^## \[(?P<version>[^\]]+)\](?: - (?P<date>\d{4}-\d{2}-\d{2}))?\s*$"
)
VERSION_CODE_MAX = 2_100_000_000
GRADLE_MARKERS = (
    "rootProject.file('../package.json')",
    "versionCode sidekickVersionCode",
    "versionName sidekickVersion",
    "sidekickMajor * 10000 + sidekickMinor * 100 + sidekickPatch",
)
# Where the handshake versions come from. A literal in either entry file would drift from the release.
HANDSHAKE_SOURCES = (
    (
        "backend/src/sidekick/mcp/server.py",
        ("from sidekick import __version__", "version=__version__,"),
        "the MCP server must announce sidekick.__version__",
    ),
    (
        "frontend/src/features/mcp-apps/sidekick-entry.tsx",
        ('import { APP_VERSION } from "./app-version";', "version: APP_VERSION"),
        "the MCP App must announce APP_VERSION",
    ),
    (
        "frontend/src/features/mcp-apps/app-version.ts",
        ('import { version } from "../../../package.json";',),
        "APP_VERSION must be the version of frontend/package.json",
    ),
)


def android_version_code(version: str) -> int:
    """The derivation in frontend/android/app/build.gradle."""

    match = SEMVER.match(version)
    if match is None:
        raise ValueError(f"{version!r} is not MAJOR.MINOR.PATCH")
    major, minor, patch = (int(part) for part in match.groups())
    if minor > 99 or patch > 99:
        raise ValueError(
            f"{version}: MINOR and PATCH must stay below 100 for the versionCode"
        )
    return major * 10000 + minor * 100 + patch


def changelog_sections(text: str) -> dict[str, tuple[str | None, str]]:
    """Map heading name (`Unreleased` or a version) to (date or None, section body)."""

    sections: dict[str, tuple[str | None, str]] = {}
    name: str | None = None
    date: str | None = None
    body: list[str] = []
    for line in text.splitlines():
        heading = RELEASE_HEADING.match(line)
        if heading or line.startswith("## "):
            if name is not None:
                sections[name] = (date, "\n".join(body).strip())
            name = heading.group("version") if heading else None
            date = heading.group("date") if heading else None
            body = []
        elif name is not None:
            body.append(line)
    if name is not None:
        sections[name] = (date, "\n".join(body).strip())
    return sections


def release_notes(text: str, version: str) -> str | None:
    """The CHANGELOG section for `version` (dated heading first, then `Unreleased`)."""

    sections = changelog_sections(text)
    for key in (version, "Unreleased"):
        if key in sections:
            return sections[key][1]
    return None


def problems(
    root: Path,
    *,
    tag: str | None,
    release: bool,
    changelog: Path | None,
    notes: Path | None,
) -> list[str]:
    found: list[str] = []
    with (root / "backend/pyproject.toml").open("rb") as handle:
        version = tomllib.load(handle)["project"]["version"]
    if not SEMVER.match(version):
        return [f"backend/pyproject.toml version {version!r} is not MAJOR.MINOR.PATCH"]
    try:
        code = android_version_code(version)
    except ValueError as error:
        return [str(error)]
    if not 1 <= code <= VERSION_CODE_MAX:
        found.append(f"versionCode {code} is outside 1..{VERSION_CODE_MAX}")

    init = (root / "backend/src/sidekick/__init__.py").read_text(encoding="utf-8")
    match = INIT_VERSION.search(init)
    if match is None or match.group(1) != version:
        found.append(
            f"backend/src/sidekick/__init__.py __version__ is {match.group(1) if match else 'missing'}"
            f", expected {version}"
        )

    package = json.loads((root / "frontend/package.json").read_text(encoding="utf-8"))
    lock = json.loads((root / "frontend/package-lock.json").read_text(encoding="utf-8"))
    for label, value in (
        ("frontend/package.json version", package.get("version")),
        ("frontend/package-lock.json version", lock.get("version")),
        (
            "frontend/package-lock.json packages[''].version",
            lock["packages"][""].get("version"),
        ),
    ):
        if value != version:
            found.append(f"{label} is {value}, expected {version}")

    gradle = (root / "frontend/android/app/build.gradle").read_text(encoding="utf-8")
    found.extend(
        f"frontend/android/app/build.gradle no longer contains {marker!r}; the Android version "
        "must stay derived from frontend/package.json"
        for marker in GRADLE_MARKERS
        if marker not in gradle
    )

    for relative, markers, meaning in HANDSHAKE_SOURCES:
        source = (root / relative).read_text(encoding="utf-8")
        found.extend(
            f"{relative} no longer contains {marker!r}; {meaning}"
            for marker in markers
            if marker not in source
        )

    if tag is not None and tag != f"v{version}":
        found.append(f"tag {tag} does not match the source version v{version}")

    changelog_path = changelog or root / "CHANGELOG.md"
    if changelog_path.exists():
        text = changelog_path.read_text(encoding="utf-8")
        sections = changelog_sections(text)
        dated = sections.get(version)
        if dated is not None and dated[0] is None:
            found.append(
                f"CHANGELOG.md heading [{version}] has no date (## [{version}] - YYYY-MM-DD)"
            )
        if release:
            if dated is None:
                found.append(
                    f"CHANGELOG.md has no '## [{version}] - YYYY-MM-DD' section; rename [Unreleased] "
                    "to the version and the release day before releasing"
                )
            elif not dated[1]:
                found.append(f"CHANGELOG.md section [{version}] is empty")
        elif dated is None:
            unreleased = sections.get("Unreleased")
            if unreleased is None:
                found.append(f"CHANGELOG.md has neither [{version}] nor [Unreleased]")
            elif version not in unreleased[1]:
                found.append(
                    f"CHANGELOG.md [Unreleased] does not name the version {version}"
                )
        if notes is not None:
            body = release_notes(text, version)
            if not body:
                found.append("CHANGELOG.md has no release notes to extract")
            else:
                notes.write_text(f"{body}\n", encoding="utf-8")
    elif release or changelog is not None or notes is not None:
        found.append(f"{changelog_path} does not exist")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--tag")
    parser.add_argument("--release", action="store_true")
    parser.add_argument("--notes", type=Path)
    parser.add_argument("--changelog", type=Path)
    args = parser.parse_args(argv)
    try:
        found = problems(
            args.root,
            tag=args.tag,
            release=args.release,
            changelog=args.changelog,
            notes=args.notes,
        )
    except (OSError, KeyError, ValueError) as error:
        print(f"cannot read the version files: {error!r}", file=sys.stderr)
        return 2
    if found:
        print("version sync failed:", file=sys.stderr)
        for line in found:
            print(f"  - {line}", file=sys.stderr)
        return 1
    with (args.root / "backend/pyproject.toml").open("rb") as handle:
        version = tomllib.load(handle)["project"]["version"]
    print(
        f"version {version} (android versionCode {android_version_code(version)}) is in sync"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
