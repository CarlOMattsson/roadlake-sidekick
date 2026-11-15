#!/usr/bin/env python3
"""Which local checks a change touches: the plan behind `tools/check-all.sh --changed [BASE]`.

The changed files are what differs between the working tree (staged, unstaged and untracked files)
and the merge base of HEAD with BASE (default: origin/main, else main). For each stage of
check-all.sh the plan says `run` (the whole stage), `some` (only the files listed after it) or
`skip` (nothing it checks changed).

Backend tests are chosen by a simple rule that errs towards running more, never by tracing every
import: the full gate before a push is what catches the rest.

- A change to what every test depends on runs the whole suite: backend/pyproject.toml and uv.lock,
  the migrations, sidekick/shared/, sidekick/__init__.py and composition.py, the test database
  setup, and the files at the top of backend/tests (conftest.py, db.py and the other helpers there)
  and in backend/tests/fixtures/.
- A file under backend/src/sidekick/<package>/ selects the test files that name `sidekick.<package>`
  (an import or a patch target) or the path `sidekick/<package>/`.
- A changed test file selects itself. A conftest.py or __init__.py selects its directory, and a
  data file the test files that name it (else those of its directory). A helper
  module under backend/tests selects the test files that import it by its dotted name, following
  helpers that import other helpers; when a top-level conftest.py imports it, the whole suite.
- Any other file selects the test files that name its file name (tests that read the repository's
  own files name them).
- The policy tests (backend/tests/policy and every file marked `pytest.mark.policy`) and the
  generated-contract test always run: they are quick and read the whole repository.

Usage:
    tools/select-checks.py [--base REF] [--root DIR]

Prints one tab-separated record per line:
    base     <merge base sha>  <ref>
    changed  <path>            (one line per changed file)
    stage    <name>  run|some|skip  <reason>
    test     <path>            (with `stage backend-tests some`)
    ruff     <path>            (with `stage backend-static some`)
    pyright  <path>            (with `stage backend-static some`)
Paths are relative to the repository root. Exit code 0 = a plan, 2 = git or the base failed.
Uses only the standard library.
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

TESTS = "backend/tests"
SOURCE = "backend/src/sidekick"

#: Changes that every backend test depends on, so the whole suite runs. fnmatch patterns.
WHOLE_SUITE = (
    (
        "backend/pyproject.toml",
        "the backend dependencies or the pytest configuration changed",
    ),
    ("backend/uv.lock", "the locked backend dependencies changed"),
    ("migrations/*", "a migration changed"),
    ("yoyo.ini", "the migration configuration changed"),
    (f"{SOURCE}/shared/*", "sidekick/shared, which every package uses, changed"),
    (f"{SOURCE}/__init__.py", "the sidekick package itself changed"),
    (
        f"{SOURCE}/composition.py",
        "composition.py, which wires every package together, changed",
    ),
    ("tools/test-db-pool.sh", "the test database setup changed"),
    ("deploy/compose.test.yaml", "the test database setup changed"),
    ("deploy/postgres-init.test-only.sql", "the test database setup changed"),
    (f"{TESTS}/fixtures/*", "a shared test fixture changed"),
)

#: The tests that always run with backend-tests: quick, no database, and they read the whole tree.
ALWAYS_DIRS = (f"{TESTS}/policy",)
ALWAYS_FILES = (f"{TESTS}/contract/test_generated_contracts.py",)
POLICY_MARK = re.compile(r"\bpytest\.mark\.policy\b")

#: Stages that run as a whole when any changed file matches one of their patterns.
STAGE_PATTERNS: Mapping[str, tuple[str, ...]] = {
    "frontend": (
        "frontend/*",
        "contracts/*",
        ".node-version",
        ".prettierignore",
        f"{SOURCE}/mcp/apps/*",
    ),
    "mcp-app": (
        "frontend/*",
        f"{SOURCE}/mcp/apps/*",
        "tools/playwright-docker.sh",
        "tools/ci-images.sh",
    ),
    "android": (
        "frontend/android/*",
        "frontend/capacitor.config.ts",
        "frontend/package.json",
        "frontend/package-lock.json",
        "frontend/vite.mobile.config.ts",
        "frontend/mobile.html",
        "frontend/src/mobile/*",
    ),
    "website": ("website/*", "docs/*", "assets/brand/*"),
    "published-tree": (
        "tools/export/*",
        "tools/check-extra.sh",
        "tools/check-export-frontend.sh",
        "docs/*",
        "*.md",
    ),
    "actionlint": (
        ".github/workflows/*",
        "tools/*/overlay/.github/workflows/*",
        "tools/ci-images.sh",
        "tools/actionlint-ci.sh",
    ),
}
#: Within frontend/, the Android project is the android stage's alone.
ANDROID_ONLY = ("frontend/android/*",)
WEB_STAGES = ("frontend", "mcp-app")
#: Stages whose checks read every file (or take seconds): they run for any change.
ANY_CHANGE_STAGES = ("policy", "gitleaks")
#: Changes after which ruff and pyright check everything instead of the changed files.
STATIC_WHOLE = ("backend/pyproject.toml", "backend/uv.lock", "*ruff.toml")
#: The trees `ruff` and `pyright` cover in check-all.sh (backend-static).
RUFF_TREES = ("backend/", "tools/workctl/")
PYRIGHT_TREES = ("backend/src/", "tools/workctl/")


def _matches(path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


@dataclass
class Selection:
    """The backend tests to run: every test (with the reason) or the listed files."""

    whole_suite_reason: str | None = None
    files: set[str] = field(default_factory=set[str])


def _test_dir_files(directory: str, tests: Mapping[str, str]) -> set[str]:
    prefix = directory.rstrip("/") + "/"
    return {path for path in tests if path.startswith(prefix) and _is_test_file(path)}


def _is_test_file(path: str) -> bool:
    name = PurePosixPath(path).name
    return name.startswith("test_") and name.endswith(".py")


def _mentioning(pattern: re.Pattern[str], tests: Mapping[str, str]) -> set[str]:
    return {path for path, text in tests.items() if pattern.search(text)}


def _dotted(path: str) -> str:
    """backend/tests/support/fakes.py -> tests.support.fakes"""
    relative = PurePosixPath(path).relative_to("backend").with_suffix("")
    return ".".join(relative.parts)


def _helper_users(helper: str, tests: Mapping[str, str]) -> tuple[set[str], str | None]:
    """The test files that import the helper module, directly or through other helpers. The
    second value is a reason to run the whole suite (a top-level conftest.py imports it)."""

    selected: set[str] = set()
    seen = {helper}
    queue = [helper]
    while queue:
        dotted = _dotted(queue.pop())
        pattern = re.compile(rf"\b{re.escape(dotted)}\b")
        for user in _mentioning(pattern, tests):
            if user in seen:
                continue
            seen.add(user)
            if user == f"{TESTS}/conftest.py":
                return set(), f"{dotted} is used by the top-level conftest.py"
            if _is_test_file(user):
                selected.add(user)
            elif PurePosixPath(user).name == "conftest.py":
                selected |= _test_dir_files(str(PurePosixPath(user).parent), tests)
            else:
                queue.append(user)
    return selected, None


def _select_for_test_tree(
    path: str, tests: Mapping[str, str]
) -> tuple[set[str], str | None]:
    pure = PurePosixPath(path)
    if pure.parent == PurePosixPath(TESTS):
        if _is_test_file(path):
            return ({path} if path in tests else set()), None
        return set(), f"{path}, which the whole suite shares, changed"
    if _is_test_file(path):
        return ({path} if path in tests else set()), None
    if pure.name in ("conftest.py", "__init__.py"):
        return _test_dir_files(str(pure.parent), tests), None
    if pure.suffix != ".py":
        return _data_file_users(pure, tests), None
    return _helper_users(path, tests)


def _data_file_users(path: PurePosixPath, tests: Mapping[str, str]) -> set[str]:
    """The test files that name a data file, else those of the nearest directory above it that
    has any (below backend/tests itself, whose files are handled as shared)."""

    named = {
        user
        for user in _mentioning(re.compile(re.escape(path.name)), tests)
        if _is_test_file(user)
    }
    if named:
        return named
    directory = path.parent
    while directory != PurePosixPath(TESTS):
        files = _test_dir_files(str(directory), tests)
        if files:
            return files
        directory = directory.parent
    return set()


def _select_for_source(path: str, tests: Mapping[str, str]) -> set[str]:
    package = PurePosixPath(path).relative_to(SOURCE).parts[0].removesuffix(".py")
    pattern = re.compile(
        rf"\bsidekick\.{re.escape(package)}\b"
        rf"|^\s*from sidekick import [^\n]*\b{re.escape(package)}\b"
        rf"|sidekick/{re.escape(package)}\b",
        re.MULTILINE,
    )
    return _mentioning(pattern, tests)


def select_backend_tests(changed: Sequence[str], tests: Mapping[str, str]) -> Selection:
    """The backend test files for the changed paths. `tests` maps every .py file under
    backend/tests (repository-relative path) to its text; deleted files are simply absent."""

    selection = Selection()
    if not changed:
        return selection
    for path in changed:
        for pattern, reason in WHOLE_SUITE:
            if fnmatch.fnmatchcase(path, pattern):
                return Selection(whole_suite_reason=f"{reason} ({path})")
    for path in changed:
        if path.startswith(f"{TESTS}/"):
            files, reason = _select_for_test_tree(path, tests)
            if reason is not None:
                return Selection(whole_suite_reason=reason)
            selection.files |= files
        elif path.startswith(f"{SOURCE}/"):
            selection.files |= _select_for_source(path, tests)
        else:
            name = PurePosixPath(path).name
            selection.files |= _mentioning(re.compile(re.escape(name)), tests)
    for directory in ALWAYS_DIRS:
        selection.files |= _test_dir_files(directory, tests)
    selection.files |= {path for path in ALWAYS_FILES if path in tests}
    selection.files |= {
        path
        for path, text in tests.items()
        if _is_test_file(path) and POLICY_MARK.search(text)
    }
    selection.files = {path for path in selection.files if _is_test_file(path)}
    return selection


def _is_shell_script(path: str, root: Path) -> bool:
    if path.endswith(".sh"):
        return True
    file = root / path
    if "." in PurePosixPath(path).name or not file.is_file():
        return False
    with file.open("rb") as handle:
        first = handle.readline(128)
    return re.match(rb"^#!.*\b(ba)?sh\b", first) is not None


def stage_plan(changed: Sequence[str], root: Path) -> dict[str, tuple[str, str]]:
    """Stage name -> (run|skip, reason) for the stages that run whole or not at all."""

    plan: dict[str, tuple[str, str]] = {}
    for stage in ANY_CHANGE_STAGES:
        plan[stage] = (
            ("run", "runs for any change") if changed else ("skip", "unchanged")
        )
    for stage, patterns in STAGE_PATTERNS.items():
        hits = [path for path in changed if _matches(path, patterns)]
        if stage in WEB_STAGES:
            hits = [path for path in hits if not _matches(path, ANDROID_ONLY)]
        plan[stage] = ("run", f"{hits[0]} changed") if hits else ("skip", "unchanged")
    scripts = [path for path in changed if _is_shell_script(path, root)]
    plan["shellcheck"] = (
        ("run", f"{scripts[0]} changed") if scripts else ("skip", "unchanged")
    )
    return plan


def static_targets(
    changed: Sequence[str], root: Path
) -> tuple[str | None, list[str], list[str]]:
    """(reason to check everything, files for ruff, files for pyright). Deleted files are left out."""

    for path in changed:
        if _matches(path, STATIC_WHOLE):
            return f"{path} changed", [], []
    present = [
        path for path in changed if path.endswith(".py") and (root / path).is_file()
    ]
    ruff = [path for path in present if path.startswith(RUFF_TREES)]
    pyright = [path for path in present if path.startswith(PYRIGHT_TREES)]
    return None, ruff, pyright


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout


def default_base(root: Path) -> str:
    for ref in ("origin/main", "main"):
        probe = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
            cwd=root,
            capture_output=True,
            check=False,
        )
        if probe.returncode == 0:
            return ref
    raise ValueError("neither origin/main nor main exists; pass a base: --changed BASE")


def changed_files(root: Path, base: str) -> tuple[str, list[str]]:
    """(merge base, changed paths) of the working tree against the merge base of HEAD and base."""

    merge_base = _git(root, "merge-base", "HEAD", base).strip()
    tracked = _git(root, "diff", "--name-only", "--no-renames", merge_base).splitlines()
    untracked = _git(root, "ls-files", "--others", "--exclude-standard").splitlines()
    return merge_base, sorted({path for path in [*tracked, *untracked] if path})


def read_tests(root: Path) -> dict[str, str]:
    tests: dict[str, str] = {}
    for file in sorted((root / TESTS).rglob("*.py")):
        relative = file.relative_to(root).as_posix()
        if "/node_modules/" not in relative:
            tests[relative] = file.read_text(encoding="utf-8", errors="replace")
    return tests


def plan_lines(
    root: Path, base: str, merge_base: str, changed: Sequence[str]
) -> list[str]:
    lines = [f"base\t{merge_base}\t{base}", *(f"changed\t{path}" for path in changed)]
    selection = select_backend_tests(changed, read_tests(root))
    if selection.whole_suite_reason is not None:
        lines.append(f"stage\tbackend-tests\trun\t{selection.whole_suite_reason}")
    elif selection.files:
        count = len(selection.files)
        lines.append(f"stage\tbackend-tests\tsome\t{count} test files")
        lines += [f"test\t{path}" for path in sorted(selection.files)]
    else:
        lines.append("stage\tbackend-tests\tskip\tunchanged")
    whole, ruff, pyright = static_targets(changed, root)
    if whole is not None:
        lines.append(f"stage\tbackend-static\trun\t{whole}")
    elif ruff:
        lines.append(f"stage\tbackend-static\tsome\t{len(ruff)} Python files")
        lines += [f"ruff\t{path}" for path in ruff]
        lines += [f"pyright\t{path}" for path in pyright]
    else:
        lines.append("stage\tbackend-static\tskip\tunchanged")
    for stage, (state, reason) in stage_plan(changed, root).items():
        lines.append(f"stage\t{stage}\t{state}\t{reason}")
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--base", help="compare with the merge base of HEAD and this ref"
    )
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args(argv)
    root: Path = args.root.resolve()
    try:
        base = args.base or default_base(root)
        merge_base, changed = changed_files(root, base)
    except (ValueError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", None) or str(error)
        print(f"select-checks: {detail.strip()}", file=sys.stderr)
        return 2
    print("\n".join(plan_lines(root, base, merge_base, changed)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
