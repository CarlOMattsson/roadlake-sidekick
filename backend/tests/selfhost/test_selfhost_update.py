"""Behaviour of deploy/selfhost/update.sh against a fake `docker` and `cosign` (no Docker).

The fake `docker` keeps a small state file (which compose services run, which image the api runs,
whether the migration ran) and logs every call, so each test reads the order of the calls the real
script would have made: workers stopped before the migration, started again after it, and handled
on rollback and on a manual restore.
"""

import fcntl
import http.server
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import yaml

from tests.support.polling import wait_until

REPO_ROOT = Path(__file__).resolve().parents[3]
SELFHOST = REPO_ROOT / "deploy" / "selfhost"
UPDATE_SH = SELFHOST / "update.sh"

PREVIOUS = "roadlake-sidekick:selfhost"
NEW = "registry.example/roadlake/sidekick@sha256:" + "a" * 64
ALL_WORKERS = "automation-worker,backup,push,memory-worker"

FAKE_DOCKER = r"""#!__PYTHON__
import json, os, sys, time

state_path = os.environ["FAKE_STATE"]
with open(state_path, encoding="utf-8") as handle:
    state = json.load(handle)


def save():
    with open(state_path, "w", encoding="utf-8") as handle:
        json.dump(state, handle)


def log(entry):
    with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


def block(stage):
    # Hold the call open until the test signals the script's process group (FAKE_BLOCK = stage).
    if os.environ.get("FAKE_BLOCK") == stage:
        with open(os.environ["FAKE_BLOCK_MARKER"], "w", encoding="utf-8") as handle:
            handle.write(stage)
        # Kept: holding the call open IS the behaviour (the test signals the process group while
        # it is stuck here); the sleep is never waited out.
        time.sleep(30)


def container_status(service):
    # state["status"] overrides the plain running/exited view (restarting, paused, created)
    override = state.get("status", {}).get(service)
    if override:
        return override
    return "running" if state["running"].get(service) else "exited"


args = sys.argv[1:]
if args[:1] != ["compose"]:
    # docker pull / image inspect / inspect
    if args[:1] == ["pull"]:
        block("pull")
        log({"sub": "pull", "args": []})
        sys.exit(0)
    if args[:2] == ["image", "inspect"]:
        label_format, ref = args[3], args[-1]
        if "min-upgrade-from" in label_format:
            print(os.environ.get("FAKE_MIN_FROM", "0.1.0"))
        elif "image.version" in label_format:
            if ref == os.environ["FAKE_NEW_IMAGE"]:
                print(os.environ.get("FAKE_NEW_VERSION", "0.2.0"))
            else:
                print(os.environ.get("FAKE_INSTALLED_VERSION", "0.1.0"))
        else:
            print(os.environ.get("FAKE_MIGRATION_CLASS", "expand"))
        sys.exit(0)
    if args[:1] == ["inspect"] and "State.Health" in args[2]:
        service = args[3][len("cid-"):]
        # state["health"] overrides the default (healthy once running) while the NEW image runs;
        # the previous image's workers are fine.
        health = "healthy"
        if state["image"] == os.environ["FAKE_NEW_IMAGE"]:
            health = state.get("health", {}).get(service, "healthy")
        print(container_status(service), health)
        sys.exit(0)
    if args[:1] == ["inspect"] and "{{.State.Status}}" in args[2]:
        service = args[3][len("cid-"):]
        print(container_status(service), state.get("policy", {}).get(service, "no"))
        sys.exit(0)
    if args[:1] == ["inspect"]:
        print(state["image"])
        sys.exit(0)
    sys.exit(0)

args = args[1:]
profiles = []
while args and args[0].startswith("-"):
    flag = args.pop(0)
    value = args.pop(0)
    if flag == "--profile":
        profiles.append(value)
sub, rest = args[0], args[1:]
services = [item for item in rest if not item.startswith("-")]
image = os.environ.get("SIDEKICK_API_IMAGE", "")
entry = {"sub": sub, "profiles": profiles, "args": rest, "image": image}


def fail_if(variable):
    return int(os.environ.get(variable, "0"))


if sub == "ps":
    service = services[-1]
    # Only the inventory (`ps -a`) fails; the later health wait is a different call.
    if "-a" in rest and fail_if("FAKE_PS_RC_" + service.upper().replace("-", "_")):
        sys.exit(1)
    if "--status" in rest:
        wanted = rest[rest.index("--status") + 1]
        listed = service in state["running"] and container_status(service) == wanted
    elif "-a" in rest:
        listed = service in state["running"]  # a stopped container still exists
    else:
        listed = bool(state["running"].get(service))
    print("cid-" + service if listed else "", end="")
    sys.exit(0)
if sub == "stop":
    log(entry)
    for service in services:
        if not fail_if("FAKE_STOP_NOOP_" + service.upper().replace("-", "_")):
            state["running"][service] = False
            state.get("status", {}).pop(service, None)
    save()
    sys.exit(fail_if("FAKE_STOP_RC_" + services[0].upper().replace("-", "_")))
if sub == "up":
    log(entry)
    for service in services:
        state["running"][service] = True
        state.get("status", {}).pop(service, None)
        if service == "api":
            state["image"] = image
    save()
    sys.exit(0)
if sub == "run":
    log(entry)
    if "migrate" in rest:
        if os.environ.get("FAKE_APPLY_THEN_BLOCK"):
            state["migrated"] = True  # the schema changed, then the process is interrupted
            save()
        block("migrate")
        rc = fail_if("FAKE_MIGRATE_RC")
        state["migrated"] = state["migrated"] or rc == 0
        save()
        sys.exit(rc)
    if "sidekick-backup-worker" in rest:
        block("backup")
        sys.exit(fail_if("FAKE_BACKUP_RC"))
    sys.stdin.buffer.read()
    sys.stdout.write("SIDEKICK-SNAPSHOT-1\nfake")
    sys.exit(0)
if sub == "exec":
    if "psql" in rest:
        print(55 if state["migrated"] else 54)
        sys.exit(0)
    if "pg_restore" in rest:
        sys.stdin.buffer.read()
        log({"sub": "pg_restore", "profiles": profiles, "args": rest, "image": image})
        sys.exit(fail_if("FAKE_PGRESTORE_RC"))
    if "pg_dump" in rest:
        log({"sub": "pg_dump", "profiles": profiles, "args": [], "image": image})
        sys.stdout.write("dump")
        sys.stdout.flush()
        block("snapshot")
        sys.exit(fail_if("FAKE_PGDUMP_RC"))
    log(entry)
    now = state["image"]
    if now in os.environ.get("FAKE_HUNG_IMAGES", "").split(","):
        sys.exit(1)  # the api process does not answer HTTP
    if now in os.environ.get("FAKE_NO_MODULE_IMAGES", "").split(","):
        sys.exit(0)  # an older image: no readiness module, the HTTP answer alone decides
    sys.exit(0 if now in os.environ.get("FAKE_READY_IMAGES", "").split(",") else 1)
log(entry)
"""


class Harness:
    def __init__(self, directory: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.directory = directory
        self.script = directory / "update.sh"
        shutil.copy(UPDATE_SH, self.script)
        shutil.copy(SELFHOST / "compose.yaml", directory / "compose.yaml")
        shutil.copy(SELFHOST / "snapshot_crypto.py", directory / "snapshot_crypto.py")
        shutil.copy(SELFHOST / "backup_space.sh", directory / "backup_space.sh")
        # A placeholder, not a secret: update.sh only checks that the variable is present.
        (directory / "selfhost.env").write_text(
            "SIDEKICK_BACKUP_ENCRYPTION_KEY=placeholder-for-the-test\n", encoding="utf-8"
        )
        bin_dir = directory / "bin"
        bin_dir.mkdir()
        self._executable(bin_dir / "docker", FAKE_DOCKER.replace("__PYTHON__", sys.executable))
        # Records every path update.sh flushes to disk (a real `sync PATH` flushes just that path).
        self._executable(bin_dir / "sync", '#!/bin/sh\nprintf "%s\\n" "$*" >>"$FAKE_SYNC_LOG"\n')
        self._executable(bin_dir / "cosign", '#!/bin/sh\nexit "${FAKE_COSIGN_RC:-0}"\n')
        # `df -Pk DIR`, POSIX format; FAKE_DF_AVAIL_KIB is the free space, FAKE_DF_BROKEN=1 fails.
        self._executable(
            bin_dir / "df",
            '#!/bin/sh\n[ "${FAKE_DF_BROKEN:-0}" = 1 ] && exit 1\n'
            'echo "Filesystem 1024-blocks Used Available Capacity Mounted on"\n'
            'echo "fake 100000000 1 ${FAKE_DF_AVAIL_KIB:-100000000} 1% /"\n',
        )
        self.state_path = directory / "state.json"
        self.log_path = directory / "calls.log"
        self.env = dict(os.environ)
        self.env.update(
            PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            FAKE_STATE=str(self.state_path),
            FAKE_LOG=str(self.log_path),
            FAKE_READY_IMAGES=NEW,
            FAKE_NEW_IMAGE=NEW,
            FAKE_BLOCK_MARKER=str(directory / "blocked"),
            FAKE_SYNC_LOG=str(directory / "sync.log"),
            SIDEKICK_UPDATE_HEALTH_TIMEOUT="2",
            SIDEKICK_UPDATE_POLL_SECONDS="0.2",
        )
        self.env.pop("SIDEKICK_API_IMAGE", None)
        self.env.pop("COMPOSE_PROJECT_NAME", None)
        monkeypatch.delenv("SIDEKICK_RELEASE_CERT_IDENTITY", raising=False)
        self.set_running(ALL_WORKERS)

    @staticmethod
    def _executable(path: Path, text: str) -> None:
        path.write_text(text, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def set_running(self, workers: str) -> None:
        running = {name: True for name in workers.split(",") if name}
        running["postgres"] = True
        running["api"] = True
        self.state_path.write_text(
            json.dumps({"running": running, "image": PREVIOUS, "migrated": False}),
            encoding="utf-8",
        )

    def set_health(self, service: str, health: str) -> None:
        """Make a worker's compose healthcheck report this status (unhealthy, starting, none)."""

        state = json.loads(self.state_path.read_text())
        state.setdefault("health", {})[service] = health
        self.state_path.write_text(json.dumps(state), encoding="utf-8")

    def set_status(self, service: str, status: str, policy: str = "unless-stopped") -> None:
        """Make one container restarting, paused or created instead of plainly running."""

        state = json.loads(self.state_path.read_text())
        state["running"][service] = status != "created"
        state.setdefault("status", {})[service] = status
        state.setdefault("policy", {})[service] = policy
        self.state_path.write_text(json.dumps(state), encoding="utf-8")

    def run(self, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(self.script), *args],
            env={**self.env, **env},
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def apply(self, *extra: str, **env: str) -> subprocess.CompletedProcess[str]:
        return self.run(
            "--apply", "--image", NEW, "--cert-identity", "release@example", *extra, **env
        )

    def calls(self) -> list[dict]:
        if not self.log_path.exists():
            return []
        return [json.loads(line) for line in self.log_path.read_text().splitlines()]

    def synced(self) -> list[str]:
        log = self.directory / "sync.log"
        return log.read_text().splitlines() if log.exists() else []

    def journal_states(self) -> list[str]:
        journal = self.directory / "update-state" / "journal.log"
        return [line.split()[1] for line in journal.read_text().splitlines()]

    def running_now(self) -> dict[str, bool]:
        return json.loads(self.state_path.read_text())["running"]

    def running_image(self) -> str:
        return json.loads(self.state_path.read_text())["image"]


@pytest.fixture(name="harness")
def _harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Harness:
    return Harness(tmp_path, monkeypatch)


def stops(calls: list[dict]) -> list[str]:
    return [call["args"][0] for call in calls if call["sub"] == "stop"]


def index_of(calls: list[dict], predicate) -> int:
    return next(position for position, call in enumerate(calls) if predicate(call))


def is_migrate(call: dict) -> bool:
    return call["sub"] == "run" and "migrate" in call["args"]


def test_every_running_worker_is_stopped_before_the_migration_and_started_after_it(
    harness: Harness,
) -> None:
    result = harness.apply()
    assert result.returncode == 0, result.stderr
    calls = harness.calls()
    migrate = index_of(calls, is_migrate)
    stopped_before = [c["args"][0] for c in calls[:migrate] if c["sub"] == "stop"]
    assert sorted(stopped_before) == ["api", "automation-worker", "backup", "memory-worker", "push"]
    final_up = [c for c in calls[migrate:] if c["sub"] == "up"][-1]
    assert final_up["image"] == NEW
    assert sorted(final_up["profiles"]) == ["backup", "memory", "push"]
    assert sorted(final_up["args"][-5:]) == [
        "api",
        "automation-worker",
        "backup",
        "memory-worker",
        "push",
    ]
    assert harness.journal_states()[-1] == "DONE"
    assert harness.running_now()["memory-worker"] is True
    assert harness.running_now()["automation-worker"] is True


def test_only_the_workers_that_were_running_are_touched(harness: Harness) -> None:
    harness.set_running("memory-worker")
    result = harness.apply()
    assert result.returncode == 0, result.stderr
    calls = harness.calls()
    assert sorted(stops(calls)) == ["api", "memory-worker"]
    final_up = [c for c in calls if c["sub"] == "up"][-1]
    assert final_up["profiles"] == ["memory"]
    # the default-on automation-worker did not run before and is started anyway (see the next tests)
    assert final_up["args"][-3:] == ["api", "memory-worker", "automation-worker"]
    assert harness.running_now().get("backup") is None
    assert harness.running_now().get("push") is None


def test_the_automation_worker_is_stopped_and_restarted_without_a_profile(
    harness: Harness,
) -> None:
    """It has no compose profile (default on), so no --profile flag may be passed for it."""

    harness.set_running("automation-worker")
    result = harness.apply()
    assert result.returncode == 0, result.stderr
    calls = harness.calls()
    assert sorted(stops(calls)) == ["api", "automation-worker"]
    assert all(c["profiles"] == [] for c in calls if c["sub"] == "stop")
    final_up = [c for c in calls if c["sub"] == "up"][-1]
    assert final_up["profiles"] == []
    assert final_up["args"][-2:] == ["api", "automation-worker"]


def test_a_default_on_worker_that_did_not_exist_before_is_started_by_the_update(
    harness: Harness,
) -> None:
    """An installation that predates the automation worker has no container for it yet."""

    harness.set_running("backup")
    assert "automation-worker" not in harness.running_now()
    result = harness.apply()
    assert result.returncode == 0, result.stderr
    calls = harness.calls()
    assert "automation-worker" not in stops(calls)
    final_up = [c for c in calls if c["sub"] == "up"][-1]
    assert final_up["profiles"] == ["backup"]
    assert final_up["args"][-3:] == ["api", "backup", "automation-worker"]
    assert harness.running_now()["automation-worker"] is True


def test_manual_restore_stops_a_default_on_worker_the_update_started(harness: Harness) -> None:
    harness.set_running("")
    result = harness.apply(
        "--allow-breaking-migration", FAKE_MIGRATION_CLASS="breaking", FAKE_READY_IMAGES=""
    )
    assert result.returncode == 1
    assert harness.journal_states()[-1] == "NEEDS_MANUAL_RESTORE"
    assert not harness.running_now().get("automation-worker")


def test_rollback_also_starts_the_default_on_worker(harness: Harness) -> None:
    harness.set_running("")
    result = harness.apply(FAKE_READY_IMAGES=PREVIOUS)
    assert result.returncode == 1
    assert harness.journal_states()[-1] == "ROLLED_BACK"
    rollback = [c for c in harness.calls() if c["sub"] == "up"][-1]
    assert rollback["image"] == PREVIOUS
    assert rollback["args"][-2:] == ["api", "automation-worker"]


def test_a_failed_owner_backup_starts_the_previous_image_and_workers_again(
    harness: Harness,
) -> None:
    result = harness.apply(FAKE_BACKUP_RC="1", FAKE_READY_IMAGES=PREVIOUS)
    assert result.returncode == 1
    assert not any(is_migrate(call) for call in harness.calls())
    assert harness.journal_states()[-1] == "ABORTED"
    assert all(harness.running_now().values())
    assert harness.running_image() == PREVIOUS
    assert not (harness.directory / "release.env").exists()


def test_a_failed_snapshot_starts_the_previous_image_and_workers_again(harness: Harness) -> None:
    result = harness.apply(FAKE_PGDUMP_RC="1", FAKE_READY_IMAGES=PREVIOUS)
    assert result.returncode == 1
    assert not any(is_migrate(call) for call in harness.calls())
    assert harness.journal_states()[-1] == "ABORTED"
    assert all(harness.running_now().values())
    assert harness.running_image() == PREVIOUS


def test_a_snapshot_is_read_back_flushed_and_renamed_before_the_migration(
    harness: Harness,
) -> None:
    result = harness.apply()
    assert result.returncode == 0, result.stderr
    calls = harness.calls()
    dump = index_of(calls, lambda c: c["sub"] == "pg_dump")
    listing = index_of(calls, lambda c: c["sub"] == "pg_restore")
    assert dump < listing < index_of(calls, is_migrate)
    assert "--list" in calls[listing]["args"]
    snapshots = harness.directory / "update-state" / "snapshots"
    finished = list(snapshots.glob("sidekick-pre-*.dump.enc"))
    assert len(finished) == 1 and not list(snapshots.glob("*.partial"))
    assert oct(finished[0].stat().st_mode & 0o777) == "0o600"
    # The partial file is flushed before the rename, the directory entry after it.
    flushed = harness.synced()
    partial = flushed.index(str(snapshots / (finished[0].name + ".partial")))
    assert str(snapshots) in flushed[partial + 1 :]


def test_a_snapshot_that_cannot_be_read_back_stops_the_update_before_the_migration(
    harness: Harness,
) -> None:
    result = harness.apply(FAKE_PGRESTORE_RC="1", FAKE_READY_IMAGES=PREVIOUS)
    assert result.returncode == 1
    assert "snapshot-unverified" in result.stderr
    assert not any(is_migrate(call) for call in harness.calls())
    snapshots = harness.directory / "update-state" / "snapshots"
    assert not list(snapshots.glob("*")), "an unverified snapshot is not kept"
    assert harness.journal_states()[-1] == "ABORTED"
    assert all(harness.running_now().values())
    assert harness.running_image() == PREVIOUS


def test_an_unknown_worker_state_aborts_before_anything_is_stopped(harness: Harness) -> None:
    """If compose ps fails the updater must not guess that the worker is not running."""

    result = harness.apply(FAKE_PS_RC_PUSH="1")
    assert result.returncode == 1
    calls = harness.calls()
    assert stops(calls) == []
    assert not any(c["sub"] == "pg_dump" for c in calls)
    assert not any(is_migrate(call) for call in calls)
    assert harness.journal_states()[-1] == "ABORTED"
    assert "worker-status" in result.stderr
    assert all(harness.running_now().values())


def test_every_writer_is_stopped_before_the_owner_backup_and_the_snapshot(
    harness: Harness,
) -> None:
    result = harness.apply()
    assert result.returncode == 0, result.stderr
    calls = harness.calls()
    backup = index_of(calls, lambda c: c["sub"] == "run" and "sidekick-backup-worker" in c["args"])
    dump = index_of(calls, lambda c: c["sub"] == "pg_dump")
    last_stop = max(i for i, c in enumerate(calls) if c["sub"] == "stop")
    assert last_stop < backup < dump < index_of(calls, is_migrate)
    stopped_first = {c["args"][0] for c in calls[:backup] if c["sub"] == "stop"}
    assert stopped_first == {"api", "automation-worker", "backup", "memory-worker", "push"}
    assert "postgres" not in stops(calls)
    # backup and snapshot use the current image; the new digest applies from the migration on
    assert calls[backup]["image"] == "" and calls[dump]["image"] == ""
    assert calls[index_of(calls, is_migrate)]["image"] == NEW


@pytest.mark.parametrize("status", ["restarting", "paused", "created"])
def test_a_worker_that_is_not_plainly_running_is_stopped_before_the_backup_and_started_again(
    harness: Harness, status: str
) -> None:
    """`ps --status running` skips a restarting worker; Docker would start it again."""

    harness.set_running("automation-worker,backup,memory-worker")
    harness.set_status("push", status)
    result = harness.apply()
    assert result.returncode == 0, result.stderr
    calls = harness.calls()
    backup = index_of(calls, lambda c: c["sub"] == "run" and "sidekick-backup-worker" in c["args"])
    stopped_before = {c["args"][0] for c in calls[:backup] if c["sub"] == "stop"}
    assert stopped_before == {"api", "automation-worker", "backup", "memory-worker", "push"}
    final_up = [c for c in calls if c["sub"] == "up"][-1]
    assert "push" in final_up["args"] and "push" in final_up["profiles"]
    assert harness.running_now()["push"] is True
    assert harness.journal_states()[-1] == "DONE"


def test_a_created_worker_without_a_restart_policy_is_not_a_writer(harness: Harness) -> None:
    harness.set_running("automation-worker")
    harness.set_status("push", "created", policy="no")
    result = harness.apply()
    assert result.returncode == 0, result.stderr
    assert sorted(stops(harness.calls())) == ["api", "automation-worker"]


def test_a_writer_that_still_runs_after_the_stop_aborts_before_the_owner_backup(
    harness: Harness,
) -> None:
    result = harness.apply(FAKE_STOP_NOOP_MEMORY_WORKER="1", FAKE_READY_IMAGES=PREVIOUS)
    assert result.returncode == 1
    calls = harness.calls()
    assert not any(c["sub"] == "run" and "sidekick-backup-worker" in c["args"] for c in calls)
    assert not any(c["sub"] == "pg_dump" for c in calls)
    assert not any(is_migrate(call) for call in calls)
    assert harness.journal_states()[-1] == "ABORTED"
    assert "writers-still-running" in result.stderr
    assert "memory-worker is still running" in result.stderr
    assert harness.running_image() == PREVIOUS
    assert all(harness.running_now().values())


def test_a_writer_that_restarts_after_the_stop_aborts_before_the_owner_backup(
    harness: Harness,
) -> None:
    """The stop returns 0 but the container is back in a restart loop (restart policy)."""

    harness.set_running("backup")
    harness.set_status("backup", "restarting", policy="always")
    result = harness.apply(FAKE_STOP_NOOP_BACKUP="1", FAKE_READY_IMAGES=PREVIOUS)
    assert result.returncode == 1
    assert not any(c["sub"] == "pg_dump" for c in harness.calls())
    assert harness.journal_states()[-1] == "ABORTED"


def test_rollback_starts_api_and_all_workers_with_the_previous_image(harness: Harness) -> None:
    result = harness.apply(FAKE_READY_IMAGES=PREVIOUS)  # the new image never becomes ready
    assert result.returncode == 1
    assert harness.journal_states()[-3:] == ["MIGRATING", "ROLLING_BACK", "ROLLED_BACK"]
    ups = [c for c in harness.calls() if c["sub"] == "up"]
    rollback = ups[-1]
    assert rollback["image"] == PREVIOUS
    assert sorted(rollback["args"][-5:]) == [
        "api",
        "automation-worker",
        "backup",
        "memory-worker",
        "push",
    ]
    assert all(harness.running_now().values())
    assert not (harness.directory / "release.env").exists()


def test_a_failed_migration_restarts_the_stopped_workers_when_the_schema_is_unchanged(
    harness: Harness,
) -> None:
    result = harness.apply(FAKE_MIGRATE_RC="1", FAKE_READY_IMAGES=PREVIOUS)
    assert result.returncode == 1
    assert harness.journal_states()[-1] == "ROLLED_BACK"
    assert all(harness.running_now().values())


def test_a_breaking_migration_that_cannot_roll_back_leaves_api_and_workers_stopped(
    harness: Harness,
) -> None:
    result = harness.apply(
        "--allow-breaking-migration", FAKE_MIGRATION_CLASS="breaking", FAKE_READY_IMAGES=""
    )
    assert result.returncode == 1
    assert harness.journal_states()[-1] == "NEEDS_MANUAL_RESTORE"
    running = harness.running_now()
    stopped = ("api", "automation-worker", "backup", "push", "memory-worker")
    assert [name for name in stopped if running.get(name)] == []
    assert "STOPPED" in result.stderr
    # no attempt to start the previous image on a schema it may not support
    last_up = [c for c in harness.calls() if c["sub"] == "up"][-1]
    assert last_up["image"] == NEW


def test_a_worker_that_cannot_be_stopped_fails_the_update_and_restores_the_others(
    harness: Harness,
) -> None:
    result = harness.apply(FAKE_STOP_RC_MEMORY_WORKER="1", FAKE_READY_IMAGES=PREVIOUS)
    assert result.returncode == 1
    assert not any(is_migrate(call) for call in harness.calls())
    assert harness.journal_states()[-1] == "ABORTED"
    assert all(harness.running_now().values())


def test_the_api_must_pass_readiness_not_only_run_the_new_image(harness: Harness) -> None:
    result = harness.apply()
    assert result.returncode == 0, result.stderr
    exec_calls = [c for c in harness.calls() if c["sub"] == "exec"]
    assert exec_calls
    assert exec_calls[-1]["args"][-3:-1] == ["python", "-c"]


def test_dry_run_names_the_workers_and_calls_nothing(harness: Harness) -> None:
    result = harness.run()
    assert result.returncode == 0
    assert "automation-worker backup push memory-worker" in result.stdout
    assert harness.calls() == []


def test_workers_in_compose_match_the_updaters_single_worker_list() -> None:
    """A new worker on the api image must be added to WORKERS, or it stays on the old image."""

    compose = yaml.safe_load((SELFHOST / "compose.yaml").read_text(encoding="utf-8"))
    on_api_image = {
        f"{(service.get('profiles') or [''])[0]}:{name}"
        for name, service in compose["services"].items()
        if service.get("image", "").startswith("${SIDEKICK_API_IMAGE")
        and name not in {"api", "migrate"}
    }
    declared = re.search(r"^WORKERS=\((.*)\)$", UPDATE_SH.read_text(), re.MULTILINE)
    assert declared is not None
    assert on_api_image == set(re.findall(r'"([^"]+)"', declared.group(1)))


def test_the_snapshot_format_exists_only_in_snapshot_crypto() -> None:
    """update.sh runs snapshot_crypto.py instead of carrying its own copy of the format."""

    script = UPDATE_SH.read_text(encoding="utf-8")
    assert "cryptography" not in script
    assert "snapshot_crypto.py" in script
    assert 'b"SIDEKICK-SNAPSHOT-1' not in script
    assert 'b"SIDEKICK-SNAPSHOT-1\\n"' in (SELFHOST / "snapshot_crypto.py").read_text(
        encoding="utf-8"
    )


def test_rollback_to_an_image_without_the_readiness_module_is_accepted(harness: Harness) -> None:
    """The previous image may predate sidekick.shared.readiness; its restored api must pass."""

    result = harness.apply(FAKE_READY_IMAGES="", FAKE_NO_MODULE_IMAGES=PREVIOUS)
    assert result.returncode == 1  # the update itself failed: the new image never became ready
    assert harness.journal_states()[-1] == "ROLLED_BACK"
    assert all(harness.running_now().values())
    assert harness.running_image() == PREVIOUS


def test_a_hung_api_process_is_not_ready_even_if_the_database_check_passes(
    harness: Harness,
) -> None:
    result = harness.apply(FAKE_READY_IMAGES=f"{NEW},{PREVIOUS}", FAKE_HUNG_IMAGES=NEW)
    assert result.returncode == 1
    assert harness.journal_states()[-1] == "ROLLED_BACK"
    assert harness.running_image() == PREVIOUS


def healthcheck_code() -> str:
    compose = yaml.safe_load((SELFHOST / "compose.yaml").read_text(encoding="utf-8"))
    test = compose["services"]["api"]["healthcheck"]["test"]
    assert test[:3] == ["CMD", "python", "-c"]
    return test[3]


def test_compose_healthcheck_and_updater_run_the_same_readiness_code() -> None:
    match = re.search(r"^READINESS_PY='(.*?)'$", UPDATE_SH.read_text(), re.MULTILINE | re.DOTALL)
    assert match is not None
    assert match.group(1).strip() == healthcheck_code().strip()
    assert "oauth-protected-resource" not in healthcheck_code()


class _Answer(http.server.BaseHTTPRequestHandler):
    status = 200
    hang = False

    def do_GET(self) -> None:
        if type(self).hang:
            time.sleep(6)  # Kept: a hanging server is the behaviour under test (probe timeout)
            return
        self.send_response(type(self).status)
        self.end_headers()

    def log_message(self, *_args: object) -> None:
        pass


def run_healthcheck(
    tmp_path: Path, *, status: int = 200, hang: bool = False, module_exit: int | None
) -> int:
    """Run the real healthcheck code against a local server and a stand-in readiness module."""

    package = tmp_path / "pkg" / "sidekick" / "shared"
    package.mkdir(parents=True)
    (package.parent / "__init__.py").write_text("")
    (package / "__init__.py").write_text("")
    if module_exit is not None:
        (package / "readiness.py").write_text(
            f"import sys\n\ndef main():\n    sys.exit({module_exit})\n"
        )
    handler = type("Handler", (_Answer,), {"status": status, "hang": hang})
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        code = healthcheck_code().replace("127.0.0.1:8000", f"127.0.0.1:{server.server_port}")
        return subprocess.run(
            [sys.executable, "-c", code],
            env={"PATH": os.environ["PATH"], "PYTHONPATH": str(tmp_path / "pkg")},
            capture_output=True,
            timeout=30,
            check=False,
        ).returncode
    finally:
        server.shutdown()


@pytest.mark.parametrize(
    ("status", "hang", "module_exit", "expected"),
    [
        (200, False, 0, 0),  # answers, database and schema ready
        (200, False, 1, 1),  # answers, database or schema not ready
        (404, False, 0, 0),  # the public surface's 404 is still an answer
        (404, False, None, 0),  # older image without the module: the HTTP answer decides
        (200, False, None, 0),
        (500, False, 0, 1),  # an error status is not an answer that counts, newer image
        (503, False, 0, 1),
        (500, False, None, 1),  # nor on an older image without the module
        (503, False, None, 1),
        (200, True, 0, 1),  # a hung process fails although the module would pass
        (200, True, None, 1),
    ],
)
def test_healthcheck_code_requires_both_parts_when_the_module_exists(
    tmp_path: Path, status: int, hang: bool, module_exit: int | None, expected: int
) -> None:
    assert run_healthcheck(tmp_path, status=status, hang=hang, module_exit=module_exit) == expected


def test_the_automation_worker_is_default_on_and_hardened_like_backup() -> None:
    compose = yaml.safe_load((SELFHOST / "compose.yaml").read_text(encoding="utf-8"))
    worker = compose["services"]["automation-worker"]
    sibling = compose["services"]["backup"]
    assert "profiles" not in worker and "ports" not in worker
    assert worker["command"] == ["sidekick-automation-worker"]
    assert worker["networks"] == ["data"]
    for key in ("image", "read_only", "tmpfs", "cap_drop", "security_opt", "restart"):
        assert worker[key] == sibling[key], key


# --- interrupts: signals at any stage leave a consistent, re-runnable state ---------------------


def interrupt_at(
    harness: Harness, stage: str, signal_number: int, *flags: str, **env: str
) -> subprocess.CompletedProcess[str]:
    """Start --apply, wait until the fake docker blocks in `stage`, then signal the group."""

    marker = harness.directory / "blocked"
    process = subprocess.Popen(
        [
            "bash",
            str(harness.script),
            *("--apply", "--image", NEW, "--cert-identity", "release@example", *flags),
        ],
        env={**harness.env, "FAKE_BLOCK": stage, **env},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,  # like a terminal: the signal reaches the script and its children
    )
    try:

        def reached() -> bool:
            assert process.poll() is None, "the update ended before it reached the stage"
            return marker.exists()

        wait_until(reached, timeout=30, what="the fake docker to reach the stage", interval=0.05)
        os.killpg(process.pid, signal_number)
        stdout, stderr = process.communicate(timeout=30)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
    return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)


def assert_lock_released(harness: Harness) -> None:
    state_dir = harness.directory / "update-state"
    assert not (state_dir / "update.lock.pid").exists()
    lock_file = state_dir / "update.lock"
    if lock_file.exists():  # the flock target is never deleted; it must just not be held any more
        with lock_file.open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)


def assert_clean(harness: Harness) -> None:
    assert_lock_released(harness)
    assert not list((harness.directory / "update-state" / "snapshots").glob("*"))
    assert not (harness.directory / "release.env.tmp").exists()


@pytest.mark.parametrize("signal_number", [signal.SIGINT, signal.SIGTERM, signal.SIGHUP])
def test_a_signal_during_the_owner_backup_restarts_the_previous_image_and_releases_the_lock(
    harness: Harness, signal_number: int
) -> None:
    result = interrupt_at(harness, "backup", signal_number, FAKE_READY_IMAGES=PREVIOUS)
    assert result.returncode == 1, result.stderr
    assert "stopping safely" in result.stderr
    assert harness.journal_states()[-1] == "ABORTED"
    assert harness.running_image() == PREVIOUS
    assert all(harness.running_now().values())
    assert not any(is_migrate(call) for call in harness.calls())
    assert not (harness.directory / "release.env").exists()
    assert_clean(harness)


def test_a_signal_before_anything_is_stopped_leaves_the_runtime_untouched(
    harness: Harness,
) -> None:
    result = interrupt_at(harness, "pull", signal.SIGINT)
    assert result.returncode == 1, result.stderr
    assert harness.journal_states()[-1] == "ABORTED"
    assert stops(harness.calls()) == []
    assert all(harness.running_now().values())
    assert_clean(harness)


def test_a_signal_during_the_snapshot_removes_the_partial_file(harness: Harness) -> None:
    result = interrupt_at(harness, "snapshot", signal.SIGTERM, FAKE_READY_IMAGES=PREVIOUS)
    assert result.returncode == 1, result.stderr
    assert harness.journal_states()[-1] == "ABORTED"
    assert all(harness.running_now().values())
    assert_clean(harness)


def test_a_signal_during_the_migration_rolls_back_an_expand_release(harness: Harness) -> None:
    result = interrupt_at(harness, "migrate", signal.SIGINT, FAKE_READY_IMAGES=PREVIOUS)
    assert result.returncode == 1, result.stderr
    assert harness.journal_states()[-3:] == ["MIGRATING", "ROLLING_BACK", "ROLLED_BACK"]
    assert harness.running_image() == PREVIOUS
    assert all(harness.running_now().values())
    assert not (harness.directory / "release.env").exists()
    assert_lock_released(harness)


def test_a_signal_during_a_breaking_migration_that_changed_the_schema_needs_a_manual_restore(
    harness: Harness,
) -> None:
    """A breaking migration cannot be rolled back automatically, also not when it is interrupted."""

    result = interrupt_at(
        harness,
        "migrate",
        signal.SIGTERM,
        "--allow-breaking-migration",
        FAKE_MIGRATION_CLASS="breaking",
        FAKE_APPLY_THEN_BLOCK="1",
        FAKE_READY_IMAGES="",
    )
    assert result.returncode == 1
    assert harness.journal_states()[-1] == "NEEDS_MANUAL_RESTORE"
    assert "STOPPED" in result.stderr
    assert_lock_released(harness)


def test_an_unexpected_exit_restores_a_consistent_state(harness: Harness) -> None:
    """release.env.tmp is a directory, so the write after the migration fails under set -e."""

    (harness.directory / "release.env.tmp").mkdir()
    result = harness.apply(FAKE_READY_IMAGES=PREVIOUS)
    assert result.returncode == 1
    assert "exited unexpectedly" in result.stderr
    assert "unexpected-exit" in (harness.directory / "update-state" / "journal.log").read_text()
    assert harness.journal_states()[-1] == "ROLLED_BACK"
    assert harness.running_image() == PREVIOUS
    assert all(harness.running_now().values())
    assert_lock_released(harness)


def test_every_failure_path_releases_the_lock(harness: Harness) -> None:
    for variables in ({"FAKE_BACKUP_RC": "1"}, {"FAKE_MIGRATE_RC": "1"}, {"FAKE_COSIGN_RC": "1"}):
        harness.set_running(ALL_WORKERS)
        result = harness.apply(FAKE_READY_IMAGES=PREVIOUS, **variables)
        assert result.returncode == 1
        assert_lock_released(harness)
    harness.set_running(ALL_WORKERS)
    assert harness.apply().returncode == 0
    assert_lock_released(harness)


# --- crash recovery: a killed update is resumed or refused, never silently half applied ----------


def write_journal(harness: Harness, *lines: str) -> None:
    state_dir = harness.directory / "update-state"
    state_dir.mkdir(exist_ok=True)
    (state_dir / "journal.log").write_text(
        "".join(f"2026-11-10T10:00:00Z {line}\n" for line in lines), encoding="utf-8"
    )


def stop_everything(harness: Harness) -> None:
    state = json.loads(harness.state_path.read_text())
    state["running"] = {name: False for name in state["running"]}
    state["running"]["postgres"] = True
    harness.state_path.write_text(json.dumps(state), encoding="utf-8")


def test_an_update_killed_while_stopping_the_writers_is_resumed_and_starts_them_again(
    harness: Harness,
) -> None:
    """kill -9 left the workers stopped and the lock behind; the journal names the workers."""

    write_journal(
        harness,
        f"STARTED image={NEW} previous={PREVIOUS}",
        "STOPPING_WRITERS workers=:automation-worker,backup:backup,push:push,memory:memory-worker",
    )
    stop_everything(harness)
    # What a killed run leaves behind: the lock file (flock dropped by the kernel) and its pid.
    dead = subprocess.Popen(["true"])
    dead.wait()
    state_dir = harness.directory / "update-state"
    (state_dir / "update.lock").touch()
    (state_dir / "update.lock.pid").write_text(f"{dead.pid}\n", encoding="utf-8")
    result = harness.apply()
    assert result.returncode == 0, result.stderr
    assert "resuming" in result.stderr
    assert "stale lock" in result.stderr
    states = harness.journal_states()
    assert "RESUMING" in states and states[-1] == "DONE"
    running = harness.running_now()
    assert all(running[n] for n in ("api", "automation-worker", "backup", "push", "memory-worker"))
    final_up = [c for c in harness.calls() if c["sub"] == "up"][-1]
    assert sorted(final_up["profiles"]) == ["backup", "memory", "push"]
    assert_lock_released(harness)


def test_a_lock_held_by_a_live_process_is_never_taken_over(harness: Harness) -> None:
    state_dir = harness.directory / "update-state"
    state_dir.mkdir(parents=True)
    with (state_dir / "update.lock").open("a") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX)
        result = harness.apply()
    assert result.returncode == 1
    assert "another update is running" in result.stderr
    assert harness.calls() == []


def test_a_stale_looking_pid_file_does_not_let_a_second_run_take_a_held_lock(
    harness: Harness,
) -> None:
    """The old PID lock let two runs see a dead pid; the second then deleted the first's lock."""

    state_dir = harness.directory / "update-state"
    state_dir.mkdir(parents=True)
    dead = subprocess.Popen(["true"])
    dead.wait()
    pid_file = state_dir / "update.lock.pid"
    pid_file.write_text(f"{dead.pid}\n", encoding="utf-8")
    with (state_dir / "update.lock").open("a") as holder:
        fcntl.flock(
            holder, fcntl.LOCK_EX
        )  # a live run holds the lock although the recorded pid is dead
        result = harness.apply()
        assert pid_file.read_text(encoding="utf-8") == f"{dead.pid}\n", (
            "the holder's record must survive"
        )
    assert result.returncode == 1
    assert "another update is running" in result.stderr
    assert "stale lock" not in result.stderr
    assert harness.calls() == []
    assert not (state_dir / "journal.log").exists()


def test_two_concurrent_updates_never_overlap_the_second_refuses(harness: Harness) -> None:
    marker = harness.directory / "blocked"
    first = subprocess.Popen(
        [
            "bash",
            str(harness.script),
            "--apply",
            "--image",
            NEW,
            "--cert-identity",
            "release@example",
        ],
        env={**harness.env, "FAKE_BLOCK": "backup"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:

        def reached() -> bool:
            assert first.poll() is None, "the first update ended before it reached the backup"
            return marker.exists()

        wait_until(reached, timeout=30, what="the first update to reach the backup", interval=0.05)
        calls_before = harness.calls()
        second = harness.apply()
        assert second.returncode == 1
        assert "another update is running" in second.stderr
        assert harness.calls() == calls_before, "the refused run must not touch anything"
        assert harness.journal_states().count("STARTED") == 1
        # The refused run did not release or remove the first run's lock.
        assert (harness.directory / "update-state" / "update.lock.pid").read_text().strip() == str(
            first.pid
        )
        os.killpg(first.pid, signal.SIGTERM)
        first.communicate(timeout=30)
    finally:
        if first.poll() is None:
            os.killpg(first.pid, signal.SIGKILL)
            first.communicate()
    assert_lock_released(harness)


SAVED_WORKERS = ":automation-worker,backup:backup,push:push,memory:memory-worker"


def test_a_resumed_run_that_fails_the_signature_check_starts_the_stopped_writers_again(
    harness: Harness,
) -> None:
    """Killed after STOPPING_WRITERS, resumed, pre-check fails: writers must not stay stopped."""

    write_journal(
        harness,
        f"STARTED image={NEW} previous={PREVIOUS}",
        f"STOPPING_WRITERS workers={SAVED_WORKERS}",
    )
    stop_everything(harness)
    result = harness.apply(FAKE_COSIGN_RC="1", FAKE_READY_IMAGES=PREVIOUS)
    assert result.returncode == 1
    running = harness.running_now()
    assert all(running[n] for n in ("api", "automation-worker", "backup", "push", "memory-worker"))
    assert harness.running_image() == PREVIOUS
    journal = (harness.directory / "update-state" / "journal.log").read_text().splitlines()
    assert "ABORTED" in journal[-1] and "writers restarted" in journal[-1]
    assert "untouched" not in journal[-1]
    assert not any(is_migrate(call) for call in harness.calls())
    assert_lock_released(harness)


def test_a_resumed_run_with_no_stopped_workers_still_starts_the_api_again(harness: Harness) -> None:
    write_journal(
        harness,
        f"STARTED image={NEW} previous={PREVIOUS}",
        "STOPPING_WRITERS workers=",
    )
    stop_everything(harness)
    result = harness.apply(FAKE_COSIGN_RC="1", FAKE_READY_IMAGES=PREVIOUS)
    assert result.returncode == 1
    assert harness.running_now()["api"] is True
    assert harness.journal_states()[-1] == "ABORTED"


def test_the_worker_list_survives_a_second_kill_of_the_resumed_run(harness: Harness) -> None:
    """kill -9, resume, kill -9 again during the pull, resume with a failing check: no loss."""

    write_journal(
        harness,
        f"STARTED image={NEW} previous={PREVIOUS}",
        f"STOPPING_WRITERS workers={SAVED_WORKERS}",
    )
    stop_everything(harness)
    interrupt_at(harness, "pull", signal.SIGKILL)
    journal = (harness.directory / "update-state" / "journal.log").read_text().splitlines()
    assert journal[-1].split()[1] == "STARTED"
    assert f"workers={SAVED_WORKERS}" in journal[-1], "the list must stay in the journal"
    assert not harness.running_now()["backup"], (
        "still stopped: the killed run never restarted anything"
    )
    result = harness.apply(FAKE_COSIGN_RC="1", FAKE_READY_IMAGES=PREVIOUS)
    assert result.returncode == 1
    running = harness.running_now()
    assert all(running[n] for n in ("api", "automation-worker", "backup", "push", "memory-worker"))
    assert harness.journal_states()[-1] == "ABORTED"
    assert_lock_released(harness)


def test_a_failed_worker_inventory_on_resume_still_starts_every_saved_worker(
    harness: Harness,
) -> None:
    """compose ps of `push` fails after a resume: the saved list must not be dropped."""

    write_journal(
        harness,
        f"STARTED image={NEW} previous={PREVIOUS}",
        f"STOPPING_WRITERS workers={SAVED_WORKERS}",
    )
    stop_everything(harness)
    result = harness.apply(FAKE_PS_RC_PUSH="1", FAKE_READY_IMAGES=PREVIOUS)
    assert result.returncode == 1
    running = harness.running_now()
    assert all(running[n] for n in ("api", "automation-worker", "backup", "push", "memory-worker"))
    journal = (harness.directory / "update-state" / "journal.log").read_text().splitlines()
    assert "ABORTED" in journal[-1] and "writers restarted" in journal[-1]
    assert not any(is_migrate(call) for call in harness.calls())
    assert_lock_released(harness)


def test_a_plain_started_state_resumes_without_pretending_anything_was_stopped(
    harness: Harness,
) -> None:
    write_journal(harness, f"STARTED image={NEW} previous={PREVIOUS}")
    result = harness.apply(FAKE_COSIGN_RC="1", FAKE_READY_IMAGES=PREVIOUS)
    assert result.returncode == 1
    journal = (harness.directory / "update-state" / "journal.log").read_text().splitlines()
    assert "untouched" in journal[-1], "nothing had been stopped, so nothing is restarted"
    assert not any(call["sub"] == "up" for call in harness.calls())


@pytest.mark.parametrize("state", ["MIGRATING", "ROLLING_BACK", "NEEDS_MANUAL_RESTORE"])
def test_a_killed_update_past_the_migration_is_not_resumed(harness: Harness, state: str) -> None:
    write_journal(harness, f"STARTED image={NEW} previous={PREVIOUS}", f"{state} class=expand")
    result = harness.apply()
    assert result.returncode == 1
    assert f"ended in state {state}" in result.stderr
    assert harness.calls() == []
    assert_lock_released(harness)


# --- upgrade path: the installed version against the new release's minimum -----------------------


def test_the_installed_baseline_version_may_update_to_the_next_release(harness: Harness) -> None:
    result = harness.apply(FAKE_INSTALLED_VERSION="0.1.0", FAKE_MIN_FROM="0.1.0")
    assert result.returncode == 0, result.stderr
    assert "upgrade path ok: 0.1.0 -> 0.2.0" in result.stdout


def test_an_installation_older_than_the_minimum_is_refused_before_anything_is_stopped(
    harness: Harness,
) -> None:
    result = harness.apply(
        FAKE_INSTALLED_VERSION="0.1.0", FAKE_MIN_FROM="0.2.0", FAKE_NEW_VERSION="0.3.0"
    )
    assert result.returncode == 1
    assert "installed version 0.1.0 is older than 0.2.0" in result.stderr
    assert "stepping-stone" in result.stderr
    calls = harness.calls()
    assert stops(calls) == [] and not any(is_migrate(call) for call in calls)
    assert harness.journal_states()[-1] == "ABORTED"
    assert all(harness.running_now().values())
    assert harness.running_image() == PREVIOUS
    assert_lock_released(harness)


def test_the_refusal_cannot_be_overridden_by_the_unknown_version_flag(harness: Harness) -> None:
    result = harness.apply(
        "--allow-unknown-version",
        FAKE_INSTALLED_VERSION="0.1.0",
        FAKE_MIN_FROM="0.2.0",
        FAKE_NEW_VERSION="0.3.0",
    )
    assert result.returncode == 1
    assert stops(harness.calls()) == []


@pytest.mark.parametrize(
    "variables",
    [
        {"FAKE_INSTALLED_VERSION": ""},  # local build or pre-release image: no version label
        {"FAKE_INSTALLED_VERSION": "not-a-version"},
        {"FAKE_NEW_VERSION": ""},
        {"FAKE_MIN_FROM": ""},  # the new image declares no minimum
    ],
)
def test_an_unknown_version_is_refused_with_a_message_unless_explicitly_allowed(
    harness: Harness, variables: dict[str, str]
) -> None:
    result = harness.apply(**variables)
    assert result.returncode == 1
    assert "--allow-unknown-version" in result.stderr
    assert stops(harness.calls()) == []
    assert harness.journal_states()[-1] == "ABORTED"
    allowed = harness.apply("--allow-unknown-version", **variables)
    assert allowed.returncode == 0, allowed.stderr
    assert harness.journal_states()[-1] == "DONE"


def test_a_downgrade_is_refused(harness: Harness) -> None:
    result = harness.apply(FAKE_INSTALLED_VERSION="0.3.0", FAKE_NEW_VERSION="0.2.0")
    assert result.returncode == 1
    assert "does not downgrade" in result.stderr
    assert stops(harness.calls()) == []


def test_the_dry_run_describes_the_version_check_and_the_resume_states(harness: Harness) -> None:
    result = harness.run()
    assert "io.sidekick.min-upgrade-from" in result.stdout
    assert "STOPPING_WRITERS" in result.stdout


def test_release_pipeline_declares_the_minimum_upgrade_version_consistently() -> None:
    minimum = (SELFHOST / "min-upgrade-from.txt").read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+", minimum)
    dockerfile = (REPO_ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    assert "io.sidekick.min-upgrade-from=" in dockerfile
    assert "SIDEKICK_MIN_UPGRADE_FROM" in dockerfile
    workflow = (REPO_ROOT / ".github" / "workflows" / "release-image.yml").read_text(
        encoding="utf-8"
    )
    assert "deploy/selfhost/min-upgrade-from.txt" in workflow
    assert "io.sidekick.min-upgrade-from=" in workflow
    assert "SIDEKICK_MIN_UPGRADE_FROM=" in workflow


def seed_snapshots(harness: Harness, names: list[str], size: int = 100) -> list[Path]:
    snapshots = harness.directory / "update-state" / "snapshots"
    snapshots.mkdir(parents=True, exist_ok=True)
    paths = [snapshots / name for name in names]
    for path in paths:
        path.write_bytes(b"x" * size)
    return paths


def test_too_little_free_space_refuses_the_update_before_anything_is_stopped(
    harness: Harness,
) -> None:
    seed_snapshots(harness, ["sidekick-pre-20260101T000000Z.dump.enc"], size=4096)
    # Needed: 4096 * 150 / 100 = 6144 bytes (floor 0); 5 KiB is free.
    result = harness.apply(SIDEKICK_BACKUP_SPACE_FLOOR_MB="0", FAKE_DF_AVAIL_KIB="5")
    assert result.returncode == 1
    assert "snapshot-disk-space" in result.stderr
    assert "5120 bytes free, 6144 needed" in result.stderr
    calls = harness.calls()
    assert stops(calls) == []
    assert not any(c["sub"] == "pg_dump" for c in calls)
    assert not any(is_migrate(call) for call in calls)
    assert harness.journal_states()[-1] == "ABORTED"
    assert all(harness.running_now().values())
    assert harness.running_image() == PREVIOUS
    assert not (harness.directory / "release.env").exists()


def test_the_floor_applies_to_the_first_snapshot(harness: Harness) -> None:
    result = harness.apply(FAKE_DF_AVAIL_KIB="1000")  # 1000 KiB free, floor 64 MiB
    assert result.returncode == 1
    assert "snapshot-disk-space" in result.stderr
    assert stops(harness.calls()) == []


@pytest.mark.parametrize(
    "env",
    [
        {"FAKE_DF_BROKEN": "1"},
        {"SIDEKICK_BACKUP_SPACE_MARGIN_PCT": "99"},
        {"SIDEKICK_BACKUP_SPACE_MARGIN_PCT": "abc"},
    ],
)
def test_a_free_size_that_cannot_be_judged_refuses_the_update(
    harness: Harness, env: dict[str, str]
) -> None:
    result = harness.apply(**env)
    assert result.returncode == 1
    assert "snapshot-disk-space-unknown" in result.stderr
    assert stops(harness.calls()) == []
    assert harness.journal_states()[-1] == "ABORTED"


def test_enough_free_space_lets_the_update_through(harness: Harness) -> None:
    seed_snapshots(harness, ["sidekick-pre-20260101T000000Z.dump.enc"], size=4096)
    result = harness.apply(SIDEKICK_BACKUP_SPACE_FLOOR_MB="0", FAKE_DF_AVAIL_KIB="6")
    assert result.returncode == 0, result.stderr


def test_old_snapshots_are_pruned_after_a_successful_update_keeping_the_newest_n(
    harness: Harness,
) -> None:
    names = [f"sidekick-pre-2026010{day}T000000Z.dump.enc" for day in range(1, 8)]
    seed_snapshots(harness, names)
    snapshots = harness.directory / "update-state" / "snapshots"
    unrelated = [
        snapshots / "notes.txt",
        snapshots / "sidekick-pre-20260101T000000Z.dump.enc.bak",
        snapshots / "sidekick-pre-2026.dump.enc",
    ]
    for path in unrelated:
        path.write_text("keep me", encoding="utf-8")
    result = harness.apply(SIDEKICK_SNAPSHOT_KEEP="3")
    assert result.returncode == 0, result.stderr
    finished = sorted(path.name for path in snapshots.glob("sidekick-pre-*T*Z.dump.enc"))
    # The snapshot just taken is the newest (today); the two newest seeded ones stay with it.
    assert len(finished) == 3
    assert finished[:2] == names[-2:]
    assert all(path.exists() for path in unrelated), "only exact finished names are ever pruned"
    assert "removed 5 older" in result.stdout


def test_the_default_keeps_the_newest_five_snapshots(harness: Harness) -> None:
    names = [f"sidekick-pre-2026010{day}T000000Z.dump.enc" for day in range(1, 8)]
    seed_snapshots(harness, names)
    assert harness.apply().returncode == 0
    snapshots = harness.directory / "update-state" / "snapshots"
    assert len(list(snapshots.glob("sidekick-pre-*.dump.enc"))) == 5


def test_a_failed_update_prunes_no_snapshot(harness: Harness) -> None:
    names = [f"sidekick-pre-2026010{day}T000000Z.dump.enc" for day in range(1, 8)]
    paths = seed_snapshots(harness, names)
    result = harness.apply(
        SIDEKICK_SNAPSHOT_KEEP="1", FAKE_MIGRATE_RC="1", FAKE_READY_IMAGES=PREVIOUS
    )
    assert result.returncode == 1
    assert all(path.exists() for path in paths), "restore points stay while an update is failing"


def test_an_invalid_snapshot_keep_refuses_the_update_before_anything_is_stopped(
    harness: Harness,
) -> None:
    result = harness.apply(SIDEKICK_SNAPSHOT_KEEP="0")
    assert result.returncode == 1
    assert "snapshot-keep-invalid" in result.stderr
    assert stops(harness.calls()) == []


# --- every started worker must be healthy, not only the api ----------------------------------


@pytest.mark.parametrize("health", ["unhealthy", "starting"])
def test_a_worker_that_does_not_become_healthy_fails_the_update_and_rolls_back(
    harness: Harness, health: str
) -> None:
    harness.set_health("memory-worker", health)
    # The api passes readiness with the new and the previous image: only the worker decides.
    result = harness.apply(FAKE_READY_IMAGES=f"{NEW},{PREVIOUS}")
    assert result.returncode == 1
    assert "failed in phase: health-check" in result.stderr
    assert "DONE" not in harness.journal_states()
    assert harness.journal_states()[-3:] == ["MIGRATING", "ROLLING_BACK", "ROLLED_BACK"]
    assert harness.running_image() == PREVIOUS
    assert all(harness.running_now().values())
    assert not (harness.directory / "release.env").exists()


def test_an_unhealthy_worker_after_a_breaking_migration_never_reports_done(
    harness: Harness,
) -> None:
    harness.set_health("push", "unhealthy")
    result = harness.apply("--allow-breaking-migration", FAKE_MIGRATION_CLASS="breaking")
    assert result.returncode == 1
    assert "DONE" not in harness.journal_states()
    assert harness.journal_states()[-1] in {"ROLLED_BACK", "NEEDS_MANUAL_RESTORE"}


def test_healthy_or_healthcheck_less_workers_let_the_update_finish(harness: Harness) -> None:
    harness.set_health("backup", "none")  # a service without a healthcheck only has to run
    result = harness.apply()
    assert result.returncode == 0, result.stderr
    assert harness.journal_states()[-1] == "DONE"


# --- the journal and the release pointer are replaced atomically and flushed -------------------


def test_the_journal_is_flushed_through_a_temporary_file_and_never_left_behind(
    harness: Harness,
) -> None:
    result = harness.apply()
    assert result.returncode == 0, result.stderr
    state_dir = harness.directory / "update-state"
    assert not list(state_dir.glob("*.tmp"))
    flushed = harness.synced()
    assert str(state_dir / "journal.log.tmp") in flushed
    assert str(state_dir) in flushed
    # Lines accumulate: the rewrite keeps every earlier entry.
    assert harness.journal_states()[:2] == ["STARTED", "STOPPING_WRITERS"]


def test_the_release_pointer_is_flushed_before_the_rename_and_its_directory_after(
    harness: Harness,
) -> None:
    result = harness.apply()
    assert result.returncode == 0, result.stderr
    assert (harness.directory / "release.env").is_file()
    assert not (harness.directory / "release.env.tmp").exists()
    flushed = harness.synced()
    tmp = str(harness.directory / "release.env.tmp")
    assert tmp in flushed
    assert str(harness.directory) in flushed[flushed.index(tmp) + 1 :]
