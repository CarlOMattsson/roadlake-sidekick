"""deploy/selfhost/update_policy.py: the decisions of update.sh, as functions and as a command."""

import ast
import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

SELFHOST = Path(__file__).resolve().parents[3] / "deploy" / "selfhost"
POLICY = SELFHOST / "update_policy.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("update_policy_under_test", POLICY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


policy = _load()


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    """The way update.sh runs it: the host's python3 in isolated mode."""
    return subprocess.run(
        [sys.executable, "-I", str(POLICY), *args],
        capture_output=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )


def test_it_is_standard_library_only_and_python_39_syntax() -> None:
    tree = ast.parse(POLICY.read_text(encoding="utf-8"), feature_version=(3, 9))
    stdlib = sys.stdlib_module_names
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        for alias in (node.names if isinstance(node, ast.Import) else [])
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert imported <= set(stdlib)


def test_the_label_names_are_the_ones_update_sh_inspects() -> None:
    script = (SELFHOST / "update.sh").read_text(encoding="utf-8")
    for name in ("LABEL_CLASS", "LABEL_VERSION", "LABEL_MIN_FROM"):
        assert f'{name}="{getattr(policy, name)}"' in script


def test_update_sh_no_longer_decides_these_things_itself() -> None:
    script = (SELFHOST / "update.sh").read_text(encoding="utf-8")
    assert "version_lt" not in script
    assert "VERSION_RE" not in script
    assert not re.search(r'"\$migration_class" = expand', script)


@pytest.mark.parametrize(
    ("installed", "new", "min_from", "kind"),
    [
        ("0.1.0", "0.2.0", "0.1.0", "ok"),
        ("0.2.0", "0.2.0", "0.1.0", "ok"),
        ("1.10.0", "1.10.1", "1.9.0", "ok"),
        # Numbers, not text: 0.10.0 is newer than 0.9.0.
        ("0.9.0", "0.10.0", "0.9.0", "ok"),
        ("0.10.0", "0.11.0", "0.9.0", "ok"),
        ("0.01.0", "0.2.0", "0.1.0", "ok"),
        ("0.1.0", "0.3.0", "0.2.0", "refused"),
        ("0.9.0", "0.10.0", "0.10.0", "refused"),
        ("0.3.0", "0.2.0", "0.1.0", "refused"),
        ("", "0.2.0", "0.1.0", "unknown"),
        ("v0.1.0", "0.2.0", "0.1.0", "unknown"),
        ("0.1", "0.2.0", "0.1.0", "unknown"),
        ("0.1.0\n", "0.2.0", "0.1.0", "unknown"),
        ("0.1.0", "", "0.1.0", "unknown"),
        ("0.1.0", "0.2.0-rc1", "0.1.0", "unknown"),
        ("0.1.0", "0.2.0", "", "unknown"),
        ("0.1.0", "0.2.0", "unknown", "unknown"),
    ],
)
def test_upgrade_path_kinds(installed: str, new: str, min_from: str, kind: str) -> None:
    assert policy.check_upgrade_path(installed, new, min_from).kind == kind


def test_the_first_unreadable_version_is_the_one_named() -> None:
    assert "installed version cannot be determined" in policy.check_upgrade_path("", "", "").message
    assert "new image has no valid" in policy.check_upgrade_path("0.1.0", "", "").message
    assert "declares no valid io.sidekick.min-upgrade-from label" in (
        policy.check_upgrade_path("0.1.0", "0.2.0", "").message
    )


def test_a_refused_jump_names_the_stepping_stone_and_a_downgrade_is_refused() -> None:
    jump = policy.check_upgrade_path("0.1.0", "0.4.0", "0.3.0").message
    assert "installed version 0.1.0 is older than 0.3.0" in jump and "stepping-stone" in jump
    assert "does not downgrade" in policy.check_upgrade_path("0.5.0", "0.4.0", "0.1.0").message


def test_upgrade_path_command_prints_ok_on_stdout() -> None:
    result = _run("upgrade-path", "--installed", "0.1.0", "--new", "0.2.0", "--min-from", "0.1.0")
    assert (result.returncode, result.stdout, result.stderr) == (
        0,
        "update.sh: upgrade path ok: 0.1.0 -> 0.2.0\n",
        "",
    )


def test_upgrade_path_command_refuses_an_unknown_version_unless_allowed() -> None:
    base = ["upgrade-path", "--installed", "", "--new", "0.2.0", "--min-from", "0.1.0"]
    refused = _run(*base)
    assert refused.returncode == policy.EXIT_UNKNOWN_VERSION
    assert refused.stdout == ""
    assert refused.stderr.startswith("update.sh: the installed version cannot be determined")
    assert "update.sh: refusing. Re-run with --allow-unknown-version" in refused.stderr
    allowed = _run(*base, "--allow-unknown")
    assert allowed.returncode == 0
    assert allowed.stderr.endswith("update.sh: continuing because of --allow-unknown-version\n")


def test_upgrade_path_command_never_lets_the_override_pass_a_refused_jump() -> None:
    result = _run(
        "upgrade-path",
        "--installed",
        "0.1.0",
        "--new",
        "0.4.0",
        "--min-from",
        "0.3.0",
        "--allow-unknown",
    )
    assert result.returncode == policy.EXIT_REFUSED_VERSION
    assert "continuing" not in result.stderr


@pytest.mark.parametrize(
    ("label", "klass"),
    [
        ("expand", "expand"),
        ("breaking", "breaking"),
        ("", "unknown"),
        ("<no value>", "unknown"),
        ("other", "unknown"),
    ],
)
def test_migration_class_names_only_the_known_labels(label: str, klass: str) -> None:
    assert policy.migration_class(label) == klass


@pytest.mark.parametrize(
    ("label", "flags", "code"),
    [
        ("expand", [], 0),
        ("expand", ["--allow-breaking", "--allow-unknown"], 0),
        ("breaking", [], policy.EXIT_BREAKING_NOT_ALLOWED),
        ("breaking", ["--allow-unknown"], policy.EXIT_BREAKING_NOT_ALLOWED),
        ("breaking", ["--allow-breaking"], 0),
        ("", [], policy.EXIT_CLASS_MISSING),
        ("", ["--allow-breaking"], policy.EXIT_CLASS_MISSING),
        ("", ["--allow-unknown"], 0),
    ],
)
def test_migration_class_command_prints_the_class_and_the_verdict(
    label: str, flags: list[str], code: int
) -> None:
    result = _run("migration-class", "--label", label, *flags)
    assert result.returncode == code
    assert result.stdout == policy.migration_class(label) + "\n"
    assert result.stderr == ""


@pytest.mark.parametrize(
    ("klass", "before", "after", "allowed"),
    [
        ("expand", "unknown", "unknown", True),
        ("expand", "5", "7", True),
        ("breaking", "5", "5", True),
        ("breaking", "5", "7", False),
        ("breaking", "unknown", "unknown", False),
        ("unknown", "5", "5", True),
        ("unknown", "5", "unknown", False),
        ("unknown", "unknown", "5", False),
    ],
)
def test_rollback_needs_an_expand_only_change_or_no_applied_migration(
    klass: str, before: str, after: str, allowed: bool
) -> None:
    assert policy.rollback_allowed(klass, before, after) is allowed
    result = _run("rollback-allowed", "--class", klass, "--before", before, "--after", after)
    assert result.returncode == (0 if allowed else 1)


@pytest.mark.parametrize("state", ["", "DONE", "ROLLED_BACK", "ABORTED"])
def test_a_settled_journal_means_a_fresh_run(state: str) -> None:
    assert policy.recovery(state, "t DONE x") == policy.Recovery("fresh")


@pytest.mark.parametrize(
    "state", ["MIGRATING", "ROLLING_BACK", "NEEDS_MANUAL_RESTORE", "NEEDS_RESTART", "x"]
)
def test_a_later_state_needs_a_decision(state: str) -> None:
    assert policy.recovery(state, "t " + state).action == "blocked"


@pytest.mark.parametrize(
    ("state", "last_line", "stopped", "workers"),
    [
        ("STARTED", "2026-01-01T00:00:00Z STARTED image=a previous=b", False, ""),
        (
            "STARTED",
            "2026-01-01T00:00:00Z STARTED image=a previous=b workers=backup:backup,push:push",
            True,
            "backup:backup,push:push",
        ),
        ("STARTED", "2026-01-01T00:00:00Z STARTED image=a previous=b workers=", True, ""),
        (
            "RESUMING",
            "2026-01-01T00:00:00Z RESUMING from=STARTED workers=:automation-worker",
            True,
            ":automation-worker",
        ),
        (
            "STOPPING_WRITERS",
            "2026-01-01T00:00:00Z STOPPING_WRITERS workers=push:push",
            True,
            "push:push",
        ),
        ("STOPPING_WRITERS", "2026-01-01T00:00:00Z STOPPING_WRITERS", True, ""),
        # The last key wins, like the sed expression it replaced.
        ("RESUMING", "t RESUMING from=STARTED workers=a workers=b", True, "b"),
    ],
)
def test_an_interrupted_run_is_resumed_with_the_workers_it_had_stopped(
    state: str, last_line: str, stopped: bool, workers: str
) -> None:
    assert policy.recovery(state, last_line) == policy.Recovery("resume", stopped, workers)


def test_recovery_command_reports_the_plan_and_the_reason() -> None:
    journal = ["--journal", "/x/journal.log"]
    resumed = _run(
        "recovery", "--state", "STARTED", "--last-line", "t STARTED workers=push:push", *journal
    )
    assert resumed.returncode == policy.EXIT_RESUME
    assert resumed.stdout == "writers_stopped=1\nworkers=push:push\n"
    assert (
        resumed.stderr
        == "update.sh: an earlier update was killed in state STARTED before the migration; "
        "resuming\n"
    )
    fresh = _run("recovery", "--state", "DONE", *journal)
    assert (fresh.returncode, fresh.stdout, fresh.stderr) == (0, "", "")
    blocked = _run("recovery", "--state", "MIGRATING", *journal)
    assert blocked.returncode == 1
    assert blocked.stderr == (
        "update.sh: previous update ended in state MIGRATING (see /x/journal.log); "
        "resolve it by hand before a new update\n"
    )


@pytest.mark.parametrize(
    ("line", "active"),
    [
        ("running no", True),
        ("running always", True),
        # An empty policy name leaves a trailing blank, which a shell may drop.
        ("running", True),
        ("restarting on-failure", True),
        ("paused no", True),
        ("created always", True),
        ("created unless-stopped", True),
        ("created no", False),
        ("created", False),
        ("exited always", False),
        ("exited no", False),
        ("dead", False),
        ("", False),
    ],
)
def test_a_container_is_active_when_docker_runs_or_may_start_it(line: str, active: bool) -> None:
    assert policy.container_active(line) is active
    result = _run("container-active", f"--inspect-line={line}")
    assert (result.returncode, result.stdout) == (0, "active\n" if active else "inactive\n")


def test_container_active_never_answers_with_an_exit_status_a_crash_could_share() -> None:
    # No argument: argparse exits 2 with nothing on stdout, which update.sh reads as no answer.
    result = _run("container-active")
    assert result.returncode == 2 and result.stdout == ""


@pytest.mark.parametrize(
    ("line", "ready"),
    [
        ("running healthy", True),
        ("running none", True),
        ("running starting", False),
        ("running unhealthy", False),
        ("exited none", False),
        ("running", False),
        ("", False),
    ],
)
def test_a_worker_is_ready_when_running_and_healthy_or_unchecked(line: str, ready: bool) -> None:
    assert _run("worker-ready", f"--inspect-line={line}").returncode == (0 if ready else 1)


def test_merging_resumed_workers_keeps_known_names_once() -> None:
    known = [":automation-worker", "backup:backup", "push:push", "memory:memory-worker"]
    assert policy.merge_workers(known, [], "backup:backup,push:push") == [
        "backup:backup",
        "push:push",
    ]
    assert policy.merge_workers(known, ["push:push"], "backup:backup,push:push") == [
        "push:push",
        "backup:backup",
    ]
    # An unknown name from a hand-edited journal is ignored.
    assert policy.merge_workers(known, [], "evil;rm,backup:backup") == ["backup:backup"]
    assert policy.merge_workers(known, ["backup:backup"], "") == ["backup:backup"]


def test_merge_workers_command_prints_one_entry_per_line() -> None:
    known = [":automation-worker", "backup:backup", "push:push"]
    result = _run(
        "merge-workers",
        "--known",
        *known,
        "--running",
        ":automation-worker",
        "--resumed",
        "push:push",
    )
    assert (result.returncode, result.stdout) == (0, ":automation-worker\npush:push\n")
    empty = _run("merge-workers", "--known", *known, "--running", "--resumed", "")
    assert (empty.returncode, empty.stdout) == (0, "")
