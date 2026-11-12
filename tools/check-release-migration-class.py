#!/usr/bin/env python3
"""Refuse a release whose declared migration class is lower than its migrations require.

The release workflow takes `expand` or `breaking` from the operator. That choice is a claim about
the migrations shipped since the previous release, so it is checked against the files themselves,
using the same rules as tools/check-migration-policy.py (DROP, RENAME, ALTER COLUMN ... TYPE,
SET NOT NULL and REVOKE, or the explicit `# migration-class: contract` marker):

    expand    every migration added or changed since the previous release is expand-only
    breaking  at least a contract step is allowed; this is the highest class and always accepted

A migration that holds a contract statement or carries the marker requires `breaking`. Declaring
`expand` for such a migration exits 1 and names the files.

Usage:
    tools/check-release-migration-class.py --release-class expand|breaking [--base REF|none]
    tools/check-release-migration-class.py --release-class expand|breaking --installed COMMIT

`--base` is the previous release and must be an annotated or signed `vX.Y.Z` tag that is an
ancestor of HEAD and not HEAD itself (a commit hash or branch would allow an empty comparison).
Omitted, the newest such tag is used. With no release tag at all the check refuses (exit 2) rather
than guessing; `--base none` is accepted only then, for the first release, and reviews every
migration in the repository against the declared class. Once any `v*` tag exists, `none` is refused.

`--installed COMMIT` is for an installation that builds its image from a checkout and so has no
previous release to compare with (tools/work.sh update): COMMIT is the checkout it ran before it
was updated, any commit that is HEAD or an ancestor of it. The migrations added or changed since
then are checked against the declared class. It cannot be combined with `--base`.

The check trusts the tag: a force-moved tag could make the comparison empty. Protect `v*` tags with
a GitHub tag protection rule (or ruleset); the script cannot do that itself.

Exit code 0 = accepted, 1 = declared class too low, 2 = usage or git error.
Uses only the standard library and the git CLI; no database, no network.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

CLASSES = ("expand", "breaking")
RELEASE_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
FIRST_RELEASE = "none"


def load_policy() -> ModuleType:
    """The migration policy lives in a hyphenated file, so it is loaded by path, not imported."""
    path = Path(__file__).resolve().parent / "check-migration-policy.py"
    spec = importlib.util.spec_from_file_location("check_migration_policy", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def release_tags(root: Path, policy: ModuleType, *, merged: bool) -> list[str]:
    """`vX.Y.Z` tags, newest first; with `merged` only those that are ancestors of HEAD."""
    args = ["tag", "--list", "v*", *(["--merged", "HEAD"] if merged else [])]
    tags = policy.git(*args, root=root).split()
    versions = [
        (tuple(int(part) for part in match.groups()), tag)
        for tag in tags
        if (match := RELEASE_TAG.match(tag))
    ]
    return [tag for _, tag in sorted(versions, reverse=True)]


def commit_of(root: Path, policy: ModuleType, ref: str) -> str:
    return policy.git(
        "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}", root=root
    ).strip()


def refuse(message: str) -> int:
    print(message, file=sys.stderr)
    return 2


def verified_base(root: Path, policy: ModuleType, base: str) -> str | None:
    """The previous release commit for `base`, or None (after printing why) if it is not valid.

    The base must be an annotated (or signed) `vX.Y.Z` tag that is an ancestor of HEAD and not
    HEAD itself. A commit hash, a branch or HEAD would let the comparison be empty, so they are
    refused. A tag can still be force-moved; only a GitHub tag protection rule prevents that, and
    this check relies on it (see docs/contribute/development.md).
    """
    if not RELEASE_TAG.match(base):
        print(f"base {base!r} must be a vX.Y.Z release tag", file=sys.stderr)
        return None
    if base not in release_tags(root, policy, merged=True):
        print(
            f"release tag {base!r} does not exist or is not an ancestor of HEAD",
            file=sys.stderr,
        )
        return None
    if policy.git("cat-file", "-t", f"refs/tags/{base}", root=root).strip() != "tag":
        print(
            f"release tag {base!r} is a lightweight tag; create release tags with "
            "git tag -a (annotated) or -s (signed)",
            file=sys.stderr,
        )
        return None
    revision = commit_of(root, policy, base)
    if revision == commit_of(root, policy, "HEAD"):
        print(
            f"release tag {base!r} points at HEAD; nothing would be compared",
            file=sys.stderr,
        )
        return None
    return revision


def verified_installed(root: Path, policy: ModuleType, installed: str) -> str | None:
    """The commit of the installed checkout, or None (after printing why) if it is not an ancestor.

    Unlike a release base, HEAD itself is valid: an update that brought no commits compares only
    the working tree.
    """
    revision = commit_of(root, policy, installed)
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", revision, "HEAD"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if ancestor.returncode != 0:
        print(
            f"installed commit {installed!r} is not an ancestor of HEAD",
            file=sys.stderr,
        )
        return None
    return revision


def contract_files(root: Path, policy: ModuleType, base: str | None) -> list[Path]:
    """Migrations added or changed since `base` (every migration if None) that need `breaking`."""
    candidates = (
        sorted((root / "migrations").glob("[0-9]*.py"))
        if base is None
        else policy.changed_files(base, root=root)
    )
    return [
        path
        for path in candidates
        if policy.declares_contract(path) or policy.scan(path)
    ]


def main(argv: list[str] | None = None, root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--release-class", required=True, choices=CLASSES)
    parser.add_argument(
        "--base",
        help="previous vX.Y.Z release tag, or 'none' when no release tag exists yet",
    )
    parser.add_argument(
        "--installed",
        help="the commit an installation built from a checkout ran before its update",
    )
    args = parser.parse_args(argv)
    if args.base is not None and args.installed is not None:
        return refuse("--base and --installed cannot be combined")

    policy = load_policy()
    top = root or policy.repo_root()

    if args.release_class == "breaking":
        print("migration class 'breaking' is the highest class; nothing to compare")
        return 0

    if args.installed is not None:
        revision = verified_installed(top, policy, args.installed)
        if revision is None:
            return 2
        return report(top, policy, revision, f"since {args.installed}")

    base = args.base
    if base is None:
        tags = release_tags(top, policy, merged=True)
        if not tags and not release_tags(top, policy, merged=False):
            return refuse(
                "no vX.Y.Z release tag exists; this looks like the first release. Pass --base none "
                "to review every migration against the declared class"
            )
        if not tags:
            return refuse(
                "release tags exist but none is an ancestor of HEAD; pass --base vX.Y.Z"
            )
        base = tags[0]
    if base == FIRST_RELEASE:
        if release_tags(top, policy, merged=False):
            return refuse(
                "--base none is only for the first release, but vX.Y.Z tags exist"
            )
        print(
            "first release: no earlier image; every migration is checked against the class"
        )
        revision = None
    else:
        revision = verified_base(top, policy, base)
        if revision is None:
            return 2
    return report(
        top,
        policy,
        revision,
        "in the repository" if revision is None else f"since {base}",
    )


def report(top: Path, policy: ModuleType, revision: str | None, scope: str) -> int:
    """Print the verdict for `expand` over the migrations in `scope`; exit code 0 or 1."""
    offenders = contract_files(top, policy, revision)
    if offenders:
        print(
            f"declared class 'expand', but {len(offenders)} migration(s) {scope} need 'breaking':"
        )
        for path in offenders:
            print(f"  {path.relative_to(top)}")
            for number, label, text in policy.scan(path):
                print(f"    line {number}: {label}: {text}")
        return 1
    print(f"migrations {scope} are expand-only; declared class 'expand' accepted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
