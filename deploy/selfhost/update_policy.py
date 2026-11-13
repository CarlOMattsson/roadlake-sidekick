"""The decisions of update.sh, as small functions with a command line. update.sh runs the commands and acts on
their exit status and output; the rules live here and nowhere else.

Standard library only and Python 3.9 syntax: it runs with the host's own ``python3`` (``python3 -I``), next to
update.sh, which refuses to apply an update without it. It never touches docker, the network or a file, and it
prints nothing a secret could be part of.

Commands (all arguments are plain values that update.sh read from docker and the journal):

* ``upgrade-path``      installed, new and minimum version: may this update run?
* ``migration-class``   the image's migration class label: may this update run?
* ``rollback-allowed``  may the previous image be started after a failure from the migration on?
* ``recovery``          what the last journal line says about an earlier, interrupted run
* ``container-active``  prints ``active`` or ``inactive`` for a ``docker inspect`` line (a container that is or may
  become active); anything else is no answer
* ``worker-ready``      does a ``docker inspect`` line describe a worker that is running and healthy?
* ``merge-workers``     the running workers plus those a killed run had stopped
"""

from __future__ import annotations

import argparse
import re
import sys
from typing import NamedTuple, Sequence

LABEL_CLASS = "io.sidekick.migration-class"
LABEL_VERSION = "org.opencontainers.image.version"
LABEL_MIN_FROM = "io.sidekick.min-upgrade-from"
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
LAST_WORKERS = re.compile(r".* workers=([^ ]*)")
# States an earlier run can have ended in without leaving anything half done, and the ones that are resumed
# (the migration had not begun).
SETTLED_STATES = ("", "DONE", "ROLLED_BACK", "ABORTED")
RESUMABLE_STATES = ("STARTED", "STOPPING_WRITERS", "RESUMING")
# Docker states in which a container is, or by itself becomes, active.
ACTIVE_STATES = ("running", "restarting", "paused")
READY_STATES = ("running healthy", "running none")

# Exit statuses. 0 always means "go on"; update.sh maps each refusal to its phase name in the journal.
EXIT_UNKNOWN_VERSION = 10
EXIT_REFUSED_VERSION = 11
EXIT_BREAKING_NOT_ALLOWED = 12
EXIT_CLASS_MISSING = 13
EXIT_RESUME = 20


class PathCheck(NamedTuple):
    kind: str  # ok | unknown | refused
    message: str


class Recovery(NamedTuple):
    action: str  # fresh | resume | blocked
    writers_stopped: bool = False
    workers: str = ""


def version_key(version: str) -> tuple[int, int, int]:
    major, minor, patch = (int(part) for part in version.split("."))
    return (major, minor, patch)


def check_upgrade_path(installed: str, new: str, min_from: str) -> PathCheck:
    """Whether ``installed`` may be updated to ``new``, which declares ``min_from`` as the oldest version it can be
    updated from. A version that cannot be read makes the answer ``unknown`` (it can be overridden); a skipped
    stepping-stone or a downgrade is ``refused`` (it cannot)."""
    if not VERSION.fullmatch(installed):
        return PathCheck(
            "unknown",
            "the installed version cannot be determined (the running image has no valid "
            f"{LABEL_VERSION} label; a local build or a pre-release image). The upgrade path cannot be verified.",
        )
    if not VERSION.fullmatch(new):
        return PathCheck(
            "unknown",
            f"the new image has no valid {LABEL_VERSION} label, so its version cannot be checked.",
        )
    if not VERSION.fullmatch(min_from):
        return PathCheck(
            "unknown",
            f"the new image declares no valid {LABEL_MIN_FROM} label (installed {installed}, new {new}); "
            "it cannot say which versions it can be updated from.",
        )
    if version_key(installed) < version_key(min_from):
        return PathCheck(
            "refused",
            f"installed version {installed} is older than {min_from}, the oldest version release {new} can be "
            f"updated from. Update to a release between {min_from} and {new} first (a stepping-stone), then run "
            "this update again. Nothing was changed.",
        )
    if version_key(new) < version_key(installed):
        return PathCheck(
            "refused",
            f"the new image ({new}) is older than the installed version ({installed}). update.sh does not "
            "downgrade; use the pre-update snapshot restore steps in README.md instead. Nothing was changed.",
        )
    return PathCheck("ok", "")


def migration_class(label: str) -> str:
    """The class of an image: its label when it is a known one, else ``unknown``."""
    return label if label in ("expand", "breaking") else "unknown"


def class_allowed(klass: str, allow_breaking: bool, allow_unknown: bool) -> bool:
    return (
        klass == "expand"
        or (klass == "breaking" and allow_breaking)
        or (klass == "unknown" and allow_unknown)
    )


def rollback_allowed(klass: str, before_count: str, after_count: str) -> bool:
    """The previous image may be started again when the new code only added what the old code can run against
    (``expand``), or when no migration was applied (the counts are known and equal)."""
    return klass == "expand" or (
        before_count != "unknown" and before_count == after_count
    )


def recovery(state: str, last_line: str) -> Recovery:
    """What an earlier run's last journal state means for this one. Before the migration only the stop of the
    writers can have happened: resume. Any later state needs a person's decision."""
    if state in SETTLED_STATES:
        return Recovery("fresh")
    if state not in RESUMABLE_STATES:
        return Recovery("blocked")
    # A "workers=" key (even an empty one) means the earlier run had begun to stop the writers; a plain STARTED,
    # written before that, means nothing was stopped.
    if state == "STOPPING_WRITERS" or " workers=" in last_line:
        listed = LAST_WORKERS.match(last_line)
        return Recovery("resume", True, listed.group(1) if listed else "")
    return Recovery("resume")


def container_active(inspect_line: str) -> bool:
    """``inspect_line`` is "<state> <restart policy>". Every state counts, not only running: a worker in a restart
    loop is restarting between two attempts and Docker starts it again. A created container is only started by
    Docker when it has a restart policy."""
    state, _, policy = inspect_line.partition(" ")
    if state in ACTIVE_STATES:
        return True
    return state == "created" and policy not in ("", "no")


def merge_workers(
    known: Sequence[str], running: Sequence[str], resumed: str
) -> list[str]:
    """``running`` plus the workers of the comma separated ``resumed`` list; only names in ``known`` count."""
    merged = list(running)
    for name in resumed.replace(",", " ").split():
        if name in known and name not in merged:
            merged.append(name)
    return merged


def _cmd_upgrade_path(args: argparse.Namespace) -> int:
    check = check_upgrade_path(args.installed, args.new, args.min_from)
    if check.kind == "ok":
        print(f"update.sh: upgrade path ok: {args.installed} -> {args.new}")
        return 0
    print(f"update.sh: {check.message}", file=sys.stderr)
    if check.kind == "refused":
        return EXIT_REFUSED_VERSION
    if args.allow_unknown:
        print(
            "update.sh: continuing because of --allow-unknown-version", file=sys.stderr
        )
        return 0
    print(
        "update.sh: refusing. Re-run with --allow-unknown-version only if you know this installation is at or "
        "above the new image's minimum version.",
        file=sys.stderr,
    )
    return EXIT_UNKNOWN_VERSION


def _cmd_migration_class(args: argparse.Namespace) -> int:
    klass = migration_class(args.label)
    print(klass)
    if class_allowed(klass, args.allow_breaking, args.allow_unknown):
        return 0
    return EXIT_BREAKING_NOT_ALLOWED if klass == "breaking" else EXIT_CLASS_MISSING


def _cmd_rollback_allowed(args: argparse.Namespace) -> int:
    return 0 if rollback_allowed(args.klass, args.before, args.after) else 1


def _cmd_recovery(args: argparse.Namespace) -> int:
    plan = recovery(args.state, args.last_line)
    if plan.action == "blocked":
        print(
            f"update.sh: previous update ended in state {args.state} (see {args.journal}); "
            "resolve it by hand before a new update",
            file=sys.stderr,
        )
        return 1
    if plan.action == "fresh":
        return 0
    print(
        f"update.sh: an earlier update was killed in state {args.state} before the migration; resuming",
        file=sys.stderr,
    )
    print(f"writers_stopped={int(plan.writers_stopped)}")
    print(f"workers={plan.workers}")
    return EXIT_RESUME


def _cmd_container_active(args: argparse.Namespace) -> int:
    # The answer is a word on stdout, never an exit status: a crash exits 1 and must not read as "not active".
    print("active" if container_active(args.inspect_line) else "inactive")
    return 0


def _cmd_worker_ready(args: argparse.Namespace) -> int:
    return 0 if args.inspect_line in READY_STATES else 1


def _cmd_merge_workers(args: argparse.Namespace) -> int:
    for entry in merge_workers(args.known, args.running, args.resumed):
        print(entry)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="update_policy", description="The decisions of update.sh."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    def add(name: str, handler: object, help_text: str) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, help=help_text)
        sub.set_defaults(handler=handler)
        return sub

    sub = add(
        "upgrade-path",
        _cmd_upgrade_path,
        "exit 0 to go on, 10 unknown version refused, 11 refused",
    )
    sub.add_argument("--installed", required=True)
    sub.add_argument("--new", required=True)
    sub.add_argument("--min-from", required=True)
    sub.add_argument("--allow-unknown", action="store_true")

    sub = add(
        "migration-class",
        _cmd_migration_class,
        "print the class; exit 0 to go on, 12 breaking, 13 missing",
    )
    sub.add_argument("--label", required=True)
    sub.add_argument("--allow-breaking", action="store_true")
    sub.add_argument("--allow-unknown", action="store_true")

    sub = add(
        "rollback-allowed",
        _cmd_rollback_allowed,
        "exit 0 when the previous image may be started again",
    )
    sub.add_argument("--class", dest="klass", required=True)
    sub.add_argument("--before", required=True)
    sub.add_argument("--after", required=True)

    sub = add(
        "recovery",
        _cmd_recovery,
        "exit 0 fresh, 20 resume (then writers_stopped= and workers=), 1 blocked",
    )
    sub.add_argument("--state", required=True)
    sub.add_argument("--last-line", default="")
    sub.add_argument("--journal", required=True)

    sub = add(
        "container-active",
        _cmd_container_active,
        "print active or inactive (exit 0); any other outcome is no answer",
    )
    sub.add_argument("--inspect-line", required=True)

    sub = add(
        "worker-ready",
        _cmd_worker_ready,
        "exit 0 when the worker runs and is healthy (or has no check)",
    )
    sub.add_argument("--inspect-line", required=True)

    sub = add(
        "merge-workers",
        _cmd_merge_workers,
        "print the merged worker entries, one per line",
    )
    sub.add_argument("--known", nargs="+", required=True)
    sub.add_argument("--running", nargs="*", default=[])
    sub.add_argument("--resumed", default="")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    sys.exit(main())
