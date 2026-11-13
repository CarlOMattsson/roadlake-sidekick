"""Fixtures the work-package tests share."""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.selfhost.work_package.support import (
    CRYPTO_STUB,
    DERIVED_ENV,
    MARKER,
    MEMORY_OFF_ENV,
    REPO_ROOT,
    SCRIPT,
    SELFHOST,
    WORK,
    ComposeLoader,
)


@pytest.fixture(name="overlay")
def _overlay() -> dict[str, Any]:
    return yaml.load((WORK / "compose.yaml").read_text(encoding="utf-8"), Loader=ComposeLoader)


def _render_merged(tmp_path: Path, derived: dict[str, str], profiles: list[str]) -> dict[str, Any]:
    """The real result of both files, from Docker Compose itself (client side; no daemon needed).

    Run in a copy of deploy/ with stand-in secret files, because Compose reads env_file."""

    if shutil.which("docker") is None:
        pytest.skip("docker is not installed")
    deploy = tmp_path / "deploy"
    # Copy only public inputs; never traverse a real installation's secrets or generated files.
    for source, target in ((SELFHOST, deploy / "selfhost"), (WORK, deploy / "work")):
        target.mkdir(parents=True)
        shutil.copy(source / "compose.yaml", target)
    secrets = deploy / "work" / "secrets"
    secrets.mkdir()
    (secrets / "db.env").write_text(f"POSTGRES_PASSWORD={MARKER}\n", encoding="utf-8")
    (secrets / "hindsight.env").write_text(
        f"HINDSIGHT_API_TENANT_API_KEY={MARKER}\n", encoding="utf-8"
    )
    (secrets / "sidekick.env").write_text(
        "SIDEKICK_DATABASE_URL=postgresql+psycopg://sidekick_app:pw@postgres:5432/sidekick\n"
        f"SIDEKICK_CURSOR_SIGNING_SECRET={MARKER}\nSIDEKICK_TOKEN_PEPPER={MARKER}\n"
        f"SIDEKICK_MEMORY_HINDSIGHT_API_TOKEN={MARKER}\nSIDEKICK_MEMORY_ID_DERIVATION_KEY={MARKER}\n",
        encoding="utf-8",
    )
    # A stray self-hosted env file on the machine must not leak into this instance.
    (deploy / "selfhost" / "db.env").write_text(
        "POSTGRES_PASSWORD=from-selfhost\n", encoding="utf-8"
    )
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-p",
            "sidekick-work-test",
            "--project-directory",
            str(deploy / "selfhost"),
            "-f",
            str(deploy / "selfhost" / "compose.yaml"),
            "-f",
            str(deploy / "work" / "compose.yaml"),
            "--env-file",
            str(WORK / "work.env.example"),
            *[arg for profile in profiles for arg in ("--profile", profile)],
            "config",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, **derived},
    )
    if result.returncode != 0 and "is not a docker command" in result.stderr:
        pytest.skip("docker compose is not available")
    assert result.returncode == 0, result.stderr
    return yaml.safe_load(result.stdout)


@pytest.fixture(name="merged")
def _merged(tmp_path: Path) -> dict[str, Any]:
    """Memory on: the memory profile, as tools/work.sh passes it."""

    return _render_merged(tmp_path, DERIVED_ENV, ["memory"])


@pytest.fixture(name="merged_without_memory")
def _merged_without_memory(tmp_path: Path) -> dict[str, Any]:
    """Memory off: what tools/work.sh derives without a model server, and no memory profile."""

    return _render_merged(tmp_path, MEMORY_OFF_ENV, [])


@pytest.fixture(name="mini_repo")
def _mini_repo(tmp_path: Path) -> Path:
    """The script in a bare layout with a stand-in `docker` that succeeds and does nothing."""

    (tmp_path / "tools").mkdir()
    shutil.copy(SCRIPT, tmp_path / "tools" / "work.sh")
    shutil.copytree(
        REPO_ROOT / "tools" / "workctl",
        tmp_path / "tools" / "workctl",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    for checker in ("check-release-migration-class.py", "check-migration-policy.py"):
        shutil.copy(REPO_ROOT / "tools" / checker, tmp_path / "tools" / checker)
    (tmp_path / "deploy" / "selfhost").mkdir(parents=True)
    shutil.copy(SELFHOST / "hindsight.env.example", tmp_path / "deploy" / "selfhost")
    shutil.copy(SELFHOST / "compose.yaml", tmp_path / "deploy" / "selfhost")
    shutil.copy(SELFHOST / "restore-ownership.sql", tmp_path / "deploy" / "selfhost")
    shutil.copy(SELFHOST / "snapshot_crypto.py", tmp_path / "deploy" / "selfhost")
    shutil.copy(SELFHOST / "postgres-init.sh", tmp_path / "deploy" / "selfhost")
    (tmp_path / "deploy" / "work").mkdir()
    for name in ("compose.yaml", "work.env.example", "gateway.haproxy.cfg"):
        shutil.copy(WORK / name, tmp_path / "deploy" / "work")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    # A stand-in docker. It records the SIDEKICK_WORK_* values tools/work.sh derived and every
    # call, and answers what the script asks for: a container id and name, the owner's UUID, a
    # finished dump, a Hindsight volume and image, a tiny tar archive. STUB_FAIL=database|memory
    # makes that step fail; STUB_FAIL=interrupt sends the script SIGTERM while the archive is made;
    # STUB_FAIL=recreate fails the final restart of `update`, migrate its migration, notready the
    # readiness check in the api; term_recreate sends the script SIGTERM during the restart.
    # Owner: owner_query fails the queries for the owner user, no_owner makes the database hold no
    # user jobb (a user id is found only when it is one of the two the stub itself hands out).
    # Restore: load fails reading the dump in, unpack the first unpacking of a memory archive
    # (unpack_always every one), term_unpack sends SIGTERM during the first unpacking.
    # State: <calls>.dbs holds the database names (renames and creates follow it) and
    # <calls>.stopped marks the writers stopped, so `docker inspect` answers from it.
    # rename fails the rename of sidekick, term_rename sends SIGTERM right after it succeeded,
    # ps fails `ps -a -q`, inspect fails `docker inspect`, still_running makes the stop of the
    # writers do nothing. STUB_WRITER=<service>:<status policy before>:<status policy after>.
    # Update: build fails the build of the api image, recreate_all fails only the start of the whole
    # stack (after the api alone has become ready); `docker image inspect` answers a fixed image id.
    docker.write_text(
        """#!/bin/sh
env | grep '^SIDEKICK_WORK_' > "${STUB_RECORD:-/dev/null}"
"""
        + CRYPTO_STUB
        + """echo "$*" >> "${STUB_CALLS:-/dev/null}"
state="${STUB_CALLS:-/tmp/stub}"
all="$*"
case "$all" in
  *"ALTER DATABASE sidekick RENAME TO "*)
    [ "${STUB_FAIL:-}" = rename ] && exit 1
    old="${all##*RENAME TO }"
    echo "${old%% *}" > "$state.dbs"
    [ "${STUB_FAIL:-}" = term_rename ] && kill -TERM "$PPID" ;;
  *"RENAME TO sidekick"*) echo sidekick > "$state.dbs" ;;
  *"CREATE DATABASE sidekick"*) echo sidekick >> "$state.dbs" ;;
  *"stop api"*) [ "${STUB_FAIL:-}" = still_running ] || touch "$state.stopped" ;;
  *"up -d --wait --wait-timeout 300 api"*|*--force-recreate*) rm -f "$state.stopped" ;;
esac
case "$all" in
  *"logs --no-color --tail 80 migrate"*) printf '%s\\n' "${STUB_MIGRATION_LOG:-}" ;;
  *"logs --no-color --tail 120 postgres"*) printf '%s\\n' "${STUB_POSTGRES_LOG:-}" ;;
  *"select coalesce(to_regclass("*)
    [ "${STUB_SCHEMA:-}" = unknown ] && exit 1
    echo "${STUB_SCHEMA-absent}" ;;
  *"select count(*) from public._yoyo_migration"*) echo "${STUB_MIGRATIONS:-0}" ;;
  *"FROM pg_database"*) cat "$state.dbs" 2>/dev/null || echo sidekick ;;
  *"ps -a -q"*)
    [ "${STUB_FAIL:-}" = ps ] && exit 1
    echo "cid-${all##* }" ;;
  *"inspect -f {{.State.Status}}"*)
    [ "${STUB_FAIL:-}" = inspect ] && exit 1
    svc="${all##* }"; svc="${svc#cid-}"
    # Default: running with a restart policy until the writers are stopped, then exited.
    if [ -e "$state.stopped" ]; then pick=3; else pick=2; fi
    line="running always"; [ -e "$state.stopped" ] && line="exited no"
    case "${STUB_WRITER:-}" in
      "$svc":*) line="$(echo "$STUB_WRITER" | cut -d: -f$pick)" ;;
    esac
    echo "$line" ;;
  *create-user*) echo 5b0c1e2a-1111-4222-8333-444455556666 ;;
  *"select 1 from sidekick.users where id = '"*)
    [ "${STUB_FAIL:-}" = owner_query ] && exit 1
    case "$all" in
      *"id = '5b0c1e2a-1111-4222-8333-444455556666'"*) echo 1 ;;
      *"id = '7e57d0e5-aaaa-4bbb-8ccc-dddddddddddd'"*) echo 1 ;;
    esac ;;
  *"username = 'jobb'"*)
    [ "${STUB_FAIL:-}" = owner_query ] && exit 1
    [ "${STUB_FAIL:-}" = no_owner ] || echo 7e57d0e5-aaaa-4bbb-8ccc-dddddddddddd ;;
  *--single-transaction*)
    cat > "$state.loaded"
    if [ "${STUB_FAIL:-}" = load_leak ]; then
      # Like psql: only the error code with VERBOSITY=sqlstate, else the message quotes the row.
      case "$all" in
        *VERBOSITY=sqlstate*) echo "ERROR:  22P02" >&2 ;;
        *) echo 'ERROR:  invalid input syntax for type uuid: "FAILING-ROW-VALUE-4711"' >&2
           echo 'CONTEXT:  COPY tasks, line 3: "FAILING-ROW-VALUE-4711"' >&2 ;;
      esac
      exit 1
    fi
    [ "${STUB_FAIL:-}" = load ] && exit 1 ;;
  *pg_dump*)
    [ "${STUB_FAIL:-}" = database ] && exit 1
    [ "${STUB_FAIL:-}" = incomplete_dump ] && { echo "-- cut off"; exit 0; }
    echo "-- PostgreSQL database dump complete" ;;
  *"ps -q"*) echo cid ;;
  *"image inspect -f {{.Id}}"*) echo sha256:5ca1ab1e ;;
  *" build api"*) [ "${STUB_FAIL:-}" = build ] && exit 1 ;;
  "tag "*:work) [ -n "${STUB_RETAG_FAIL:-}" ] && exit 1 ;;
  *"inspect --format {{.Name}}"*) echo /sidekick-work-api-1 ;;
  "volume ls"*)
    case "$all" in
      *"volume=pgdata"*) echo "${STUB_PG_VOLUME:-sidekick-work_pgdata}" ;;
      *) echo sidekick-work_hindsight_pg0 ;;
    esac ;;
  *"config --images"*) echo ghcr.io/vectorize-io/hindsight@sha256:0000 ;;
  *"run --rm -T --no-deps migrate"*) [ "${STUB_FAIL:-}" = migrate ] && exit 1 ;;
  *"exec -T api python"*) [ "${STUB_FAIL:-}" = notready ] && exit 1 ;;
  *"up -d --wait --wait-timeout 420")
    if [ -n "${STUB_START_FAIL:-}" ]; then
      printf '%s\\n' "${STUB_START_FAIL}" >&2
      exit 1
    fi
    [ "${STUB_FAIL:-}" = recreate_all ] && exit 1 ;;
  *--force-recreate*)
    [ "${STUB_FAIL:-}" = term_recreate ] && kill -TERM "$PPID"
    [ "${STUB_FAIL:-}" = recreate ] && exit 1 ;;
  *"up -d --wait --wait-timeout 300 api memory-worker automation-worker"*)
    if [ "${STUB_FAIL:-}" = term_restart ] && [ ! -e "${STUB_CALLS}.termed" ]; then
      touch "${STUB_CALLS}.termed"
      kill -TERM "$PPID"
    fi ;;
  "run --rm -i "*)
    cat > "$state.unpacked.$$"
    [ "${STUB_FAIL:-}" = unpack_always ] && exit 1
    if [ ! -e "${STUB_CALLS}.unpacked" ]; then
      touch "${STUB_CALLS}.unpacked"
      [ "${STUB_FAIL:-}" = unpack ] && exit 1
      [ "${STUB_FAIL:-}" = term_unpack ] && kill -TERM "$PPID"
    fi ;;
  "run "*)
    [ "${STUB_FAIL:-}" = memory ] && exit 1
    [ "${STUB_FAIL:-}" = interrupt ] && kill -TERM "$PPID"
    printf 16 > "$state.member"
    tar -czf - -C "$(dirname "$state")" "$(basename "$state").member" ;;
esac
exit 0
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    return tmp_path
